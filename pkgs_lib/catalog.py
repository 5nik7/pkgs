import os
from pathlib import Path
import re
from .common import Cache, Error, which
from .detect import SYSTEM


def key(name, manager):
    return re.sub(r'[-_.]+', '-', name).lower() if manager in ('pip', 'uv-tool') else name


def inventory(backend, cfg, query='', installed_only=False, offline=False, refresh=False):
    installed = backend.installed()  # Always refresh local state; never from catalog TTL.
    if installed_only:
        return sorted(installed, key=lambda p: p.name.lower())
    cache = Cache(backend.cache_key)
    cached = cache.load(None if offline else cfg['cache_seconds'])
    if backend.remote_inventory:
        rows = cached or []
        if query and not offline:
            found = backend.inventory(query)
            by_name = {key(p.name, backend.name): p for p in rows}
            by_name.update({key(p.name, backend.name): p for p in found})
            cache.save(list(by_name.values()))
            rows = found
        elif not rows and backend.name in ('paru', 'yay'):
            rows = backend.inventory(offline=True)
            cache.save(rows)
    else:
        rows = cached if cached is not None and not refresh else backend.inventory(offline=True)
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


def external(p, backend, cfg, owners=None):
    if not cfg.get('external_detection') or backend.name not in SYSTEM:
        return p
    owners = owners if owners is not None else {}
    base = p.name.partition(':')[0]
    mapped = base in cfg['commands']
    commands = cfg['commands'].get(base, [base])
    evidence = []
    for command in commands:
        if '/' in command:
            continue
        paths = []
        for directory in os.get_exec_path():
            candidate = Path(directory) / command
            if candidate.is_file() and os.access(candidate, os.X_OK):
                path = str(candidate.absolute())
                if path not in paths:
                    paths.append(path)
        if not paths and (found := which(command)):
            paths.append(found)
        for index, path in enumerate(paths):
            resolved = str(Path(path).resolve())
            if path not in owners:
                owner = backend.owner(path)
                if not owner and resolved != path:
                    owner = backend.owner(resolved)
                owners[path] = owner
            owner = owners[path]
            if owner == '':
                evidence.append({'command': command, 'path': path, 'resolved': resolved,
                                 'match': 'known command mapping' if mapped else 'same-name candidate',
                                 'position': 'first executable on PATH' if index == 0 else 'additional executable',
                                 'ownership': 'not owned by selected system database'})
    p.external = evidence
    return p
