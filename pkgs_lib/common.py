"""Shared data, subprocess boundaries, configuration and cache."""
import json
import contextlib
import contextvars
import signal
import threading
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, asdict

ROOT = Path(__file__).resolve().parent.parent
class Error(Exception):
    pass

@dataclass
class Package:
    name: str
    version: str = ''
    description: str = ''
    installed: bool = False
    installed_version: str = ''
    repo: str = ''
    url: str = ''
    details: dict = field(default_factory=dict)
    external: list = field(default_factory=list)

def clean(value):
    # Metadata is display text, never terminal instructions.
    return re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', str(value)).strip()

_deadline = contextvars.ContextVar('pkgs_deadline', default=None)
_debug = contextvars.ContextVar('pkgs_debug', default=False)
_quiet = contextvars.ContextVar('pkgs_quiet', default=False)


def diagnostic(message, warning=False):
    if _debug.get() or (warning and not _quiet.get()):
        print('pkgs: ' + clean(message), file=sys.stderr, flush=True)


@contextlib.contextmanager
def diagnostics(debug=False, quiet=False):
    d, q = _debug.set(debug), _quiet.set(quiet)
    try:
        yield
    finally:
        _debug.reset(d)
        _quiet.reset(q)


@contextlib.contextmanager
def budget(seconds):
    deadline = time.monotonic() + seconds
    previous = _deadline.get()
    token = _deadline.set(min(previous, deadline) if previous else deadline)
    try:
        yield
    finally:
        _deadline.reset(token)


def remaining(maximum=45):
    deadline = _deadline.get()
    seconds = min(maximum, deadline - time.monotonic()) if deadline else maximum
    if seconds <= 0:
        raise Error('Read-only operation exceeded its time budget.')
    return seconds


@contextlib.contextmanager
def phase(label):
    start = time.monotonic()
    done = threading.Event()
    # Only delayed human stderr output; never touch candidates or JSON stdout.
    def progress():
        if not done.wait(0.5):
            print('pkgs: ' + label + '…', file=sys.stderr, flush=True)
    thread = None
    if not _quiet.get() and sys.stderr.isatty():
        thread = threading.Thread(target=progress, daemon=True)
        thread.start()
    diagnostic('start ' + label)
    try:
        remaining()
        yield
    finally:
        done.set()
        if thread: thread.join()
        diagnostic(f'{label}: {time.monotonic() - start:.3f}s')


def _stop_query(proc, grouped):
    if grouped:
        try: os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    else:
        # fzf owns the preview process group. Keep descendants in it so fzf can
        # cancel the entire preview, including when it uses SIGKILL.
        if os.getpgrp() == os.getpid():
            previous = signal.signal(signal.SIGTERM, signal.SIG_IGN)
            try: os.killpg(os.getpgrp(), signal.SIGTERM)
            finally: signal.signal(signal.SIGTERM, previous)
        proc.kill()
    proc.communicate()


def query(args, timeout=45):
    """Read-only child, never the runner for interactive transactions."""
    seconds = remaining(timeout)
    grouped = not bool(os.environ.get('PKGS_SESSION'))
    start = time.monotonic()
    proc = None
    try:
        proc = subprocess.Popen([str(x) for x in args], text=True, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=grouped,
                                env={**os.environ, 'LC_ALL': 'C', 'NO_COLOR': '1'})
        try:
            stdout, stderr = proc.communicate(timeout=seconds)
        except BaseException:
            _stop_query(proc, grouped)
            raise
        return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Error(f'{args[0]}: {e}') from e
    finally:
        diagnostic(f'query {args[0]}: {time.monotonic() - start:.3f}s')


def run(args, allowed=(0,), timeout=45):
    p = query(args, timeout)
    if p.returncode not in allowed:
        raise Error(f'{args[0]} exited {p.returncode}: {clean(p.stderr or p.stdout)[-1500:]}')
    return p.stdout

def which(name):
    p = shutil.which(name)
    if not p and name == 'fzf':
        candidate = Path.home() / '.fzf/bin/fzf'
        if candidate.is_file() and os.access(candidate, os.X_OK):
            p = str(candidate)
    return p

def atomic(path, text, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.pkgs-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def config():
    path = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'pkgs/config.json'
    defaults = {'manager': 'auto', 'preview': 'bottom:55%:wrap', 'color': 'auto',
                'cache_seconds': 300, 'external_detection': True,
                'commands': {'ripgrep': ['rg'], 'fd-find': ['fdfind', 'fd'],
                             'bat': ['bat', 'batcat'], 'python3': ['python3'],
                             'nodejs': ['node'], 'ruby': ['ruby']}}
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                raise ValueError('expected an object')
            mappings = {**defaults['commands'], **data.get('commands', {})}
            defaults.update(data)
            defaults['commands'] = mappings
            if defaults['color'] not in ('auto', 'always', 'never'):
                raise ValueError('color must be auto, always, or never')
            if not isinstance(defaults['cache_seconds'], (int, float)) or defaults['cache_seconds'] < 0:
                raise ValueError('cache_seconds must be nonnegative')
            if not all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in mappings.values()):
                raise ValueError('commands must map package names to lists of command names')
        except (ValueError, TypeError) as e:
            raise Error(f'Invalid {path}: {e}') from e
    return defaults

class Cache:
    def __init__(self, scope):
        import hashlib
        self.path = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'pkgs' / (hashlib.sha256(scope.encode()).hexdigest()[:24] + '.json')
    def load(self, ttl=None):
        try:
            obj = json.loads(self.path.read_text())
            if ttl is not None and time.time() - obj['time'] > ttl:
                return None
            return [Package(**p) for p in obj['packages']]
        except (OSError, ValueError, KeyError, TypeError) as e:
            diagnostic(f'Catalog cache miss: {e}')
            return None
    def save(self, rows):
        try:
            with phase('Saving catalog cache'):
                atomic(self.path, json.dumps({'time': time.time(), 'packages': [asdict(p) for p in rows]}))
        except OSError as e:
            diagnostic(f'Catalog cache not saved: {e}', warning=True)
    def clear(self):
        self.path.unlink(missing_ok=True)

def validate_names(names, manager):
    for n in names:
        pattern = r'(?:@[a-zA-Z0-9_.-]+/)?[a-zA-Z0-9][a-zA-Z0-9_.+-]*' if manager == 'npm' else r'[a-zA-Z0-9][a-zA-Z0-9_.+:-]*'
        if not re.fullmatch(pattern, n):
            raise Error(f'Invalid package name: {n!r}. Use exact names, without flags, URLs or version expressions.')
    return list(dict.fromkeys(names))
