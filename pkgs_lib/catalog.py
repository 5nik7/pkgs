import os
import json
import time
from pathlib import Path
import re
from .common import Cache, Error, which, phase, atomic, diagnostic, remaining
from .detect import SYSTEM


def key(name, manager):
    return re.sub(r'[-_.]+', '-', name).lower() if manager in ('pip', 'uv-tool') else name


def inventory(backend, cfg, query='', installed_only=False, offline=False, refresh=False):
    with phase('Reading installed packages'):
        installed = backend.installed()  # Never use stale installed state.
    if installed_only:
        return sorted(installed, key=lambda p: p.name.lower())
    cache = Cache(backend.cache_key)
    with phase('Reading catalog cache'):
        cached = cache.load(None if offline else cfg['cache_seconds'])
    if backend.remote_inventory:
        rows = cached or []
        if query and not offline:
            with phase('Searching package source'):
                found = backend.inventory(query)
            by_name = {key(p.name, backend.name): p for p in rows}
            by_name.update({key(p.name, backend.name): p for p in found})
            cache.save(list(by_name.values()))
            rows = found
        elif not rows and backend.name in ('paru', 'yay'):
            with phase('Reading available packages'):
                rows = backend.inventory(offline=True)
            cache.save(rows)
    else:
        if cached is not None and not refresh:
            rows = cached
        else:
            with phase('Reading available packages'):
                rows = backend.inventory(offline=True)
        if cached is None or refresh:
            cache.save(rows)
    available = {}
    for p in rows:
        p.installed = False
        p.installed_version = ''
        available.setdefault(key(p.name, backend.name), p)
    for p in installed:
        k = key(p.name, backend.name)
        # dpkg native architectures often print as name:arch; retain other architectures.
        base = p.name.partition(':')[0]
        if backend.name == 'apt' and k not in available and base in available:
            k = base
        if k in available:
            available[k].installed = True
            available[k].installed_version = p.installed_version
        else:
            available[k] = p
    return sorted(available.values(), key=lambda p: p.name.lower())


def path_signature(path):
    try:
        p = Path(path)
        s, target = p.lstat(), p.stat()
        return [str(p.resolve()), s.st_ino, s.st_mtime_ns, s.st_ctime_ns,
                target.st_ino, target.st_size, target.st_mtime_ns, target.st_ctime_ns]
    except OSError:
        return None


class EvidenceCache:
    """Sparse cache: load only previously highlighted packages, never scan a catalog."""
    def __init__(self, backend, cfg):
        self.backend, self.cfg = backend, cfg
        self.path = Cache('external|' + backend.cache_key).path
        self.database = backend.database_fingerprint()
        directories = list(dict.fromkeys(os.path.abspath(p) for p in os.get_exec_path()))
        directories.append(str(Path.home() / '.fzf/bin'))
        self.signature = [self.database, cfg['commands'],
                          [[p, path_signature(p)] for p in directories]]
        self.records = {}
        try:
            data = json.loads(self.path.read_text())
            if self.database and isinstance(data['records'], dict) and data['signature'] == self.signature and time.time() - data['time'] < cfg['cache_seconds']:
                self.records = data['records']
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def get(self, name):
        record = self.records.get(name)
        if not isinstance(record, dict): return None
        try:
            paths, evidence = record['paths'], record['evidence']
            fields = ('command', 'path', 'resolved', 'match', 'position', 'ownership')
            if not isinstance(paths, dict) or not isinstance(evidence, list): return None
            if not all(isinstance(e, dict) and all(isinstance(e.get(k), str) for k in fields)
                       and e['path'] in paths for e in evidence): return None
            if all(isinstance(p, str) and sig is not None and path_signature(p) == sig for p, sig in paths.items()):
                return evidence
        except (KeyError, TypeError):
            pass
        return None

    def apply(self, rows):
        for p in rows:
            p.external = self.get(p.name) or []

    def save(self, name, evidence, paths):
        if not self.database: return
        self.records[name] = {'evidence': evidence, 'paths': {p: path_signature(p) for p in paths}}
        try:
            atomic(self.path, json.dumps({'time': time.time(), 'signature': self.signature, 'records': self.records}))
        except OSError as e:
            diagnostic(f'External evidence cache not saved: {e}')


def invalidate_evidence(backend):
    Cache('external|' + backend.cache_key).clear()


def external(p, backend, cfg, owners=None, cache=None):
    if not cfg.get('external_detection') or backend.name not in SYSTEM:
        return p
    owners = owners if owners is not None else {}
    cached = cache.get(p.name) if cache else None
    if cached is not None:
        p.external = cached
        return p
    base = p.name.partition(':')[0]
    mapped = base in cfg['commands']
    commands = cfg['commands'].get(base, [base])
    evidence, checked = [], []
    unknown = False
    directories = list(dict.fromkeys(os.path.abspath(d) for d in os.get_exec_path()))
    for command in dict.fromkeys(commands):
        if '/' in command or not command:
            continue
        remaining()
        paths = []
        for directory in directories:
            candidate = Path(directory) / command
            if candidate.is_file() and os.access(candidate, os.X_OK):
                paths.append(str(candidate))
        fallback = None
        if not paths and (found := which(command)):
            fallback = found
            paths.append(found)
        for index, path in enumerate(paths):
            resolved = str(Path(path).resolve())
            checked.append(path)
            for candidate in dict.fromkeys([path, resolved]):
                if candidate not in owners:
                    with phase('Checking executable ownership'):
                        owners[candidate] = backend.owner(candidate)
                # Unknown does not mean unowned, including through a symlink.
                if owners[candidate] is None or owners[candidate] != '': break
            owner = owners[candidate]
            if owner is None:
                unknown = True
            elif owner == '':
                evidence.append({'command': command, 'path': path, 'resolved': resolved,
                                 'match': 'known command mapping' if mapped else 'same-name candidate',
                                 'position': '~/.fzf/bin/fzf fallback (not on PATH)' if fallback else
                                             'first executable on PATH' if index == 0 else 'additional executable on PATH',
                                 'ownership': 'not owned by selected system database'})
    p.external = evidence
    if unknown:
        p.details['External check'] = getattr(backend, 'ownership_error', 'Ownership unavailable; no external marker inferred.')
    elif cache:
        cache.save(p.name, evidence, checked)
    return p
