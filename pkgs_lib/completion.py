"""Offline candidates and repeatable, minimally invasive shell setup."""
import os
import fcntl
import hashlib
import json
import re
import tempfile
from pathlib import Path
import shlex
import shutil
import subprocess
import time
from . import VERSION
from .common import ROOT, Error, atomic, which, clean, budget, diagnostic, remaining
from .detect import MANAGERS, available, default_manager
from .backends import Backend
from .catalog import inventory
from .ui import pick
from .fzf import invocation, PROTOCOL

COMMANDS = {'install': 'Install exact names or open a picker', 'uninstall': 'Remove installed packages',
            'remove': 'Alias for uninstall', 'search': 'Read-only search picker', 'list': 'Print package inventory',
            'info': 'Readable package details', 'upgrade': 'Upgrade packages', 'refresh': 'Refresh repository metadata',
            'managers': 'Detected managers and capabilities', 'doctor': 'Detection and completion diagnostics',
            'completion': 'Generate or install shell completions', 'cache': 'Clear cached catalogs', 'help': 'Show usage'}
OPTIONS = {'--manager': 'Select manager', '--query': 'Filter/search the picker', '--global': 'npm global scope',
           '--installed': 'Installed inventory only', '--json': 'Machine-readable output', '--color': 'auto/always/never',
           '--preview': 'fzf preview-window layout', '--dry-run': 'Print transaction without executing',
           '--directory': 'Completion destination directory', '--debug': 'Phase diagnostics on stderr',
           '--yes': 'Confirm transaction automatically', '--help': 'Show help', '-H': 'Show help', '--version': 'Show version'}
VALUE_OPTIONS = ('--manager', '--query', '--color', '--preview', '-p', '--directory')


def context(words, cfg):
    current = words[-1] if words else ''
    before = words[:-1]
    manager = cfg.get('manager', 'auto')
    command = None
    global_scope = False
    used = []
    skip = False
    for i, w in enumerate(before):
        if skip:
            skip = False
            continue
        if w in VALUE_OPTIONS:
            if i + 1 < len(before) and w == '--manager': manager = before[i+1]
            skip = True
        elif w.startswith('--manager='): manager = w.split('=', 1)[1]
        elif w == '--global': global_scope = True
        elif not w.startswith('-'):
            if command is None: command = w
            else: used.append(w)
    return current, before, manager, command, global_scope, used


def complete(words, cfg, fuzzy=False):
    with budget(45 if fuzzy else 1.5):
        return _complete(words, cfg, fuzzy)


def _complete(words, cfg, fuzzy=False):
    current, before, manager, command, global_scope, used = context(words, cfg)
    candidates = []
    if before and before[-1] == '--manager':
        candidates = [(m, 'package manager') for m in MANAGERS if available(m)]
    elif before and before[-1] == '--color':
        candidates = [(m, 'color mode') for m in ('auto', 'always', 'never')]
    elif before and before[-1] in ('--query', '--preview', '-p', '--directory'):
        return []
    elif current.startswith('-'):
        candidates = list(OPTIONS.items())
    elif not command:
        candidates = list(COMMANDS.items())
    elif command == 'completion':
        candidates = [(x, 'shell') for x in ('bash', 'zsh', 'fish')] if not used else [(x, 'completion action') for x in ('install', 'update', 'status', 'uninstall')]
    elif command == 'cache':
        candidates = [('clear', 'Clear package inventory cache')]
    elif command in ('install', 'uninstall', 'remove', 'info', 'upgrade', 'search', 'list'):
        name = default_manager() if manager == 'auto' else manager
        if name not in MANAGERS or not available(name): return []
        backend = Backend(name, global_scope)
        rows = inventory(backend, cfg, installed_only=command in ('uninstall', 'remove', 'upgrade'), offline=True)
        rows = [p for p in rows if p.name not in used]
        if fuzzy:
            return [(p.name, '') for p in pick(rows, backend, cfg, current, completion=True)]
        candidates = [(p.name, ('[i] ' if p.installed else '') + (p.description or p.version)) for p in rows]
    if fuzzy and candidates and which('fzf'):
        # Simple menus for commands/options; package candidates use the full preview above.
        args, env = invocation()
        p = subprocess.run(args + ['--ansi', '--no-multi', '+e', '--query=' + current,
                            '--delimiter=\t', '--with-nth=1,2', '--no-preview', '--header=Enter insert · Esc cancel',
                            ] + PROTOCOL,
                           input=''.join(a + '\t' + clean(b) + '\n' for a, b in candidates),
                           stdout=subprocess.PIPE, text=True, env=env)
        if p.returncode in (1, 130): return []
        if p.returncode: raise Error(f'fzf exited {p.returncode}')
        selected = p.stdout.split('\t', 1)[0].strip()
        return [(a, b) for a, b in candidates if a == selected]
    remaining()
    return [(a, clean(b)) for a, b in candidates if a.startswith(current)]


# Exact release artifacts; a marker alone never establishes ownership.
LEGACY_HASHES = {'bash': 'd52ace45685867ccf893ebec75e6534791e18e85704b12cca7d3bff2b80c3c2f', 'zsh': '9a80252ffa62dde206e6ce95f5c51d225cb2bacdddaba79f47ead6b9eb2ddf2e', 'fish': '10967cb42d9c6489bc770c0f0020efb2e40749851418a1500dbd9a4785f82a26'}
START, END = '# >>> pkgs completion >>>', '# <<< pkgs completion <<<'


def locations(shell):
    """Legacy destinations, also used for conservative migration discovery."""
    home = Path.home()
    data = Path(os.environ.get('XDG_DATA_HOME', home / '.local/share'))
    cfg = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config'))
    if shell == 'bash':
        return data / 'bash-completion/completions/pkgs', home / '.bashrc'
    if shell == 'zsh':
        return data / 'zsh/site-functions/_pkgs', Path(os.environ.get('ZDOTDIR', str(home))) / '.zshrc'
    if shell == 'fish':
        return cfg / 'fish/completions/pkgs.fish', cfg / 'fish/conf.d/pkgs.fish'
    raise Error('Shell must be bash, zsh, or fish.')


def generated(shell):
    return (ROOT / 'completions' / ('pkgs.' + shell)).read_text()


def startup(shell, dest):
    """Historical templates for recognition; only Fish still installs one."""
    q = shlex.quote(str(dest))
    if shell == 'bash':
        return '[ -r ' + q + ' ] && source ' + q
    if shell == 'zsh':
        return 'fpath=(' + shlex.quote(str(dest.parent)) + ' $fpath)\nautoload -Uz compinit\n(( $+functions[compdef] )) || compinit\nautoload -Uz _pkgs\ncompdef _pkgs pkgs'
    q = "'" + str(dest).replace('\\', '\\\\').replace("'", "\\'") + "'"
    return 'if status is-interactive\n    source ' + q + '\nend'


def read_text(path):
    # Path.read_text's universal-newline translation would alter unrelated bytes.
    if path.is_symlink() and not path.exists():
        raise Error(f'Dangling symlink: {path}')
    return path.read_bytes().decode('utf-8') if path.exists() else ''


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def state_path():
    return Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'pkgs/completions.json'


def read_state():
    path = state_path()
    if not path.exists():
        return {'format': 1, 'shells': {}}
    try:
        state = json.loads(read_text(path))
        if state['format'] != 1 or not isinstance(state['shells'], dict):
            raise ValueError('unsupported format')
        for shell, record in state['shells'].items():
            if shell not in ('bash', 'zsh', 'fish') or not Path(record['file']).is_absolute():
                raise ValueError('invalid destination')
            if not re.fullmatch('[0-9a-f]{64}', record['hash']):
                raise ValueError('invalid content hash')
            if record.get('startup') and not Path(record['startup']).is_absolute():
                raise ValueError('invalid startup location')
            for item in record.get('retired', []):
                if not Path(item['file']).is_absolute() or not re.fullmatch('[0-9a-f]{64}', item['hash']):
                    raise ValueError('invalid retired destination')
        return state
    except (ValueError, KeyError, TypeError) as e:
        raise Error(f'Invalid completion state {path}: {e}') from e


def writable(directory):
    directory = Path(directory)
    while not directory.exists() and directory != directory.parent:
        directory = directory.parent
    return directory.is_dir() and os.access(directory, os.W_OK | os.X_OK)


def bash_loader():
    prefix = Path(os.environ.get('PREFIX') or '/usr')
    candidates = [prefix / 'share/bash-completion/bash_completion',
                  Path('/usr/local/share/bash-completion/bash_completion'),
                  Path('/usr/share/bash-completion/bash_completion')]
    # Only recognize an actual autoload implementation, without executing it.
    for path in dict.fromkeys(candidates):
        if path.is_file():
            text = read_text(path)
            if 'BASH_COMPLETION_USER_DIR' in text and 'completions/' in text:
                return str(path)
    return ''


def resolve(shell, directory=None, record=None):
    legacy, _ = locations(shell)
    if directory is not None:
        return Path(directory).expanduser().absolute() / legacy.name, 'explicit override'
    if record:
        return Path(record['file']), 'recorded destination'
    if shell == 'fish':
        return legacy.absolute(), 'Fish XDG convention'
    if shell == 'zsh':
        for entry in dict.fromkeys(os.environ.get('FPATH', '').split(':')):
            if entry and Path(entry).is_absolute() and Path(entry).is_dir() and writable(entry):
                return Path(entry) / '_pkgs', 'inherited FPATH (caller supplied)'
        raise Error('Cannot establish a writable active Zsh completion directory. From Zsh use '
                    'FPATH="$FPATH" pkgs completion zsh install, or pass --directory DIR '
                    '(installer: --completion-dir zsh=DIR). No startup files were changed.')
    if not bash_loader():
        raise Error('bash-completion autoload support was not found. Install/load it yourself, '
                    'or explicitly choose --directory DIR for file-only installation '
                    '(installer: --completion-dir bash=DIR). Activation is unverified.')
    bases = os.environ.get('BASH_COMPLETION_USER_DIR')
    bases = bases.split(':') if bases else [str(legacy.parent.parent)]
    for base in bases:
        if base and Path(base).is_absolute() and writable(Path(base) / 'completions'):
            return Path(base) / 'completions/pkgs', 'bash-completion user autoload convention'
    raise Error('No writable bash-completion autoload directory. Pass --directory DIR.')


def block_span(text):
    if START not in text and END not in text:
        return None
    if text.count(START) != 1 or text.count(END) != 1:
        raise Error('Malformed/duplicate pkgs startup blocks; left untouched.')
    a, b = text.index(START), text.index(END)
    if b <= a or (a and text[a-1] != '\n'):
        raise Error('Malformed pkgs startup block; left untouched.')
    end = b + len(END)
    if end < len(text) and text[end] != '\n':
        raise Error('Edited pkgs startup block; left untouched.')
    return a, end + (end < len(text)), text[a:end]


def managed_block(text, body=None):
    """Fish's existing managed setup; preserve bytes outside the block."""
    span = block_span(text)
    if span:
        a, b, _ = span
        text = text[:a] + text[b:]
    if body is not None:
        text += ('\n' if text and not text.endswith('\n') else '') + START + '\n' + body + '\n' + END + '\n'
    return text


def legacy_block(text, shell):
    span = block_span(text)
    if not span:
        return text, None
    a, b, block = span
    body = block[len(START)+1:-len(END)-1]
    try:
        if shell == 'bash':
            words = shlex.split(body)
            dest = Path(words[2])
        else:
            first = body.splitlines()[0]
            words = shlex.split(first[len('fpath=('):-len(' $fpath)')])
            dest = Path(words[0]) / '_pkgs'
        if not dest.is_absolute() or body != startup(shell, dest):
            raise ValueError('not an exact historical template')
    except (ValueError, IndexError):
        raise Error('Edited pkgs startup block; left untouched. Remove it manually after review.')
    return text[:a] + text[b:], dest


def backup(path):
    dest = path.with_name(path.name + '.pkgs-backup-' + str(time.time_ns()))
    shutil.copy2(path, dest)
    return dest


def replace_startup(path, original, updated):
    """Preserve a symlink and the metadata of its resolved target."""
    if read_text(path) != original:
        raise Error(f'{path} changed during installation; retry after reviewing it.')
    target = path.resolve() if path.is_symlink() else path
    saved = backup(target) if target.exists() else None
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.pkgs-', dir=target.parent)
    os.close(fd)
    try:
        if target.exists():
            shutil.copy2(target, tmp)
            stat = target.stat()
            if (os.stat(tmp).st_uid, os.stat(tmp).st_gid) != (stat.st_uid, stat.st_gid):
                os.chown(tmp, stat.st_uid, stat.st_gid)
        with open(tmp, 'w', newline='') as stream:
            stream.write(updated)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return str(saved) if saved else None


def known_file(path, shell, state):
    if path.is_symlink():
        raise Error(f'Completion symlink left untouched: {path}. Choose a different destination.')
    if not path.exists():
        return
    text = read_text(path)
    hashes = {LEGACY_HASHES[shell], digest(generated(shell))}
    record = state['shells'].get(shell)
    if record:
        if record['file'] == str(path): hashes.add(record['hash'])
        hashes.update(item['hash'] for item in record.get('retired', []) if item['file'] == str(path))
    if digest(text) not in hashes:
        raise Error(f'Edited or unrelated completion left untouched: {path}')


def preflight(shell, action='install', directory=None):
    shell = shell.lower()
    legacy, rc = locations(shell)
    state = read_state()
    record = state['shells'].get(shell)
    if record and record.get('startup'):
        rc = Path(record['startup'])
    # Uninstall can safely discover a known legacy file without proving activation.
    if action == 'uninstall' and not record and directory is None:
        dest, source = legacy.absolute(), 'legacy destination'
    else:
        dest, source = resolve(shell, directory, record)
    original = read_text(rc)
    if shell == 'fish':
        span = block_span(original)
        if span:
            body = span[2][len(START)+1:-len(END)-1]
            old = Path(record['file']) if record else legacy
            if body != startup('fish', old):
                raise Error(f'Edited Fish startup block left untouched: {rc}')
        updated = original
        desired = startup(shell, dest) if action != 'uninstall' else None
        if not span or action == 'uninstall' or body != desired:
            updated = managed_block(original, desired)
        block_dest = None
    else:
        try:
            updated, block_dest = legacy_block(original, shell)
        except Error as e:
            raise Error(f'{rc}: {e}') from e
    old_paths = {legacy.absolute()}
    if record:
        old_paths.add(Path(record['file']))
        old_paths.update(Path(item['file']) for item in record.get('retired', []))
    if block_dest: old_paths.add(block_dest)
    # Known legacy locations may be removed; unrelated old locations are retained.
    cleanup, notices = [], []
    for old in old_paths - {dest}:
        if old.resolve() == dest.resolve(): continue
        if old.exists() or old.is_symlink():
            try:
                known_file(old, shell, state)
                cleanup.append(old)
            except Error as e:
                notices.append(str(e))
    known_file(dest, shell, state)
    if action != 'uninstall' and not writable(dest.parent):
        raise Error(f'Completion directory is not writable: {dest.parent}')
    if shell == 'zsh' and action != 'uninstall':
        for entry in os.environ.get('FPATH', '').split(':'):
            if not entry: continue
            candidate = Path(entry) / '_pkgs'
            if candidate.resolve() == dest.resolve(): break
            if candidate.exists() and candidate not in cleanup:
                raise Error(f'{candidate} precedes the destination in FPATH; resolve this conflict first.')
    if original != updated and not writable(rc.resolve().parent):
        raise Error(f'Startup target is not writable for migration: {rc}')
    if not writable(state_path().parent):
        raise Error(f'Completion state directory is not writable: {state_path().parent}')
    return dict(shell=shell, dest=dest, source=source, rc=rc, original=original, updated=updated,
                cleanup=cleanup, notices=notices, state=state)


def status(shell, directory=None):
    state = read_state()
    record = state['shells'].get(shell)
    loader = bash_loader() if shell == 'bash' else ''
    try:
        dest, source = resolve(shell, directory, record)
        issue = ''
    except Error as e:
        dest, _ = locations(shell)
        source, issue = 'unresolved (legacy file inspected only)', str(e)
    current = read_text(dest)
    installed_version = re.search(r'^# pkgs managed completion (\S+)$', current, re.MULTILINE)
    result = {'shell': shell, 'file': str(dest), 'resolution': source,
              'status': 'current' if current == generated(shell) else 'outdated' if current else 'missing',
              'version': VERSION, 'installed_version': installed_version.group(1) if installed_version else None,
              'activation': 'unverified: cannot inspect the parent shell',
              'loader': loader or ('not found' if shell == 'bash' else 'shell-owned setup')}
    if issue: result['notice'] = issue
    _, rc = locations(shell)
    if record and record.get('startup'): rc = Path(record['startup'])
    try:
        rc_text = read_text(rc)
        if shell == 'fish':
            if startup(shell, dest) not in rc_text:
                result['activation'] = 'unavailable: Fish conf.d setup missing or changed'
                if result['status'] == 'current': result['status'] = 'outdated'
        else:
            _, legacy = legacy_block(rc_text, shell)
            result['legacy_startup'] = str(rc) if legacy else 'none'
    except Error as e:
        result['legacy_startup'] = str(e)
    if shell == 'bash' and not loader:
        result['activation'] = 'unavailable: bash-completion loader not found'
    if shell == 'zsh':
        result['in_supplied_fpath'] = str(dest.parent) in os.environ.get('FPATH', '').split(':')
    return result


def manage(shell, action, directory=None):
    shell = shell.lower()
    locations(shell)  # Validate even when a state record exists.
    if action == 'status': return status(shell, directory)
    if action not in ('install', 'update', 'uninstall'):
        raise Error('Completion action must be install, update, status, or uninstall.')
    # Preflight before creating even a lock/state directory.
    preflight(shell, action, directory)
    state_path().parent.mkdir(parents=True, exist_ok=True)
    with (state_path().parent / 'completions.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        plan = preflight(shell, action, directory)
        dest, rc, state = plan['dest'], plan['rc'], plan['state']
        original_state = json.loads(json.dumps(state))
        backups = []
        expected = generated(shell)
        if action != 'uninstall':
            if read_text(dest) != expected:
                if dest.exists(): backups.append(str(backup(dest)))
                atomic(dest, expected, 0o644)
            state['shells'][shell] = {'file': str(dest), 'startup': str(rc), 'hash': digest(expected),
                                      'version': VERSION, 'resolution': state['shells'].get(shell, {}).get('resolution', plan['source'])}
            if plan['cleanup']:
                state['shells'][shell]['retired'] = [{'file': str(old), 'hash': digest(read_text(old))} for old in plan['cleanup']]
            # Record the published file before retiring old artifacts.
            encoded = json.dumps(state, indent=2) + '\n'
            if read_text(state_path()) != encoded: atomic(state_path(), encoded)
        if plan['original'] != plan['updated']:
            saved = replace_startup(rc, plan['original'], plan['updated'])
            if saved: backups.append(saved)
        retired = plan['cleanup'] + ([dest] if action == 'uninstall' else [])
        for old in retired:
            if old.exists():
                known_file(old, shell, original_state)
                backups.append(str(backup(old)))
                old.unlink()
        if action == 'uninstall':
            state['shells'].pop(shell, None)
        else:
            state['shells'][shell].pop('retired', None)
        encoded = json.dumps(state, indent=2) + '\n'
        if read_text(state_path()) != encoded: atomic(state_path(), encoded)
    result = {'shell': shell, 'file': str(dest), 'resolution': plan['source'],
              'status': 'removed' if action == 'uninstall' else 'installed', 'backups': backups,
              'activation': 'unverified: cannot inspect the parent shell', 'notices': plan['notices']}
    if action != 'uninstall':
        if shell == 'zsh':
            result['activate'] = 'In Zsh verify this directory is in $fpath, then run your existing completion reload; or run: autoload -Uz compinit; compinit; autoload -Uz _pkgs; compdef _pkgs pkgs'
        elif shell == 'bash':
            result['loader'] = bash_loader() or 'not found: file installed, autoload unavailable'
            result['activate'] = 'With bash-completion loaded, start a new Bash session; for this session only: source ' + shlex.quote(str(dest))
        else:
            result['activate'] = 'source ' + shlex.quote(str(rc))
    return result
