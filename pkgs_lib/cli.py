"""User interface. Exact names, picker queries, and transactions stay distinct."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
from . import VERSION
from .common import Error, Package, Cache, config, clean, validate_names, which, budget, phase, diagnostics, diagnostic, ROOT
from .detect import MANAGERS, default_manager, available, termux
from .backends import Backend
from .catalog import inventory, key, EvidenceCache, invalidate_evidence
from .ui import colored, render, pick, session, enrich
from .completion import COMMANDS, generated, manage, complete, preflight
from .fzf import details as fzf_details

DESCRIPTION = '''Fuzzy package management for Termux and Linux.

Commands:
  install [NAME ...]       Install exact names; no names opens picker
  uninstall [NAME ...]     Remove installed packages; no names opens picker
  search [QUERY]           Read-only search picker (Enter shows details)
  list                    Print package inventory
  info NAME ...           Colorized, wrapped package information
  upgrade [NAME ...]       Upgrade using the selected manager
  refresh                 Refresh repository metadata where supported
  managers                Show detected managers and capabilities
  doctor                  Explain environment, dependencies, completions
  completion SHELL [install|update|status|uninstall]
                          Print or manage Bash/Zsh/Fish completion
  cache clear             Clear pkgs inventory caches
  help                    Show this usage

Examples:
  pkgs install --query editor
  pkgs uninstall
  pkgs install --manager npm --global typescript
  pkgs install --manager uv-tool ruff
  pkgs completion ZSH install

Picker: Tab select, Ctrl-X preview, Alt-I installed, Alt-O homepage.
Bare invocation shows help. Completion inserts names and never installs.
'''

def parser():
    p = argparse.ArgumentParser(prog='pkgs', description=DESCRIPTION, add_help=False,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('command', nargs='?', choices=list(COMMANDS))
    p.add_argument('names', nargs='*', metavar='ARG')
    p.add_argument('-h', '-H', '--help', action='help')
    p.add_argument('-V', '--version', action='version', version='pkgs ' + VERSION)
    p.add_argument('--manager', choices=('auto',) + MANAGERS, default=None)
    p.add_argument('--query', default='')
    p.add_argument('--global', dest='global_scope', action='store_true', help='npm global scope')
    p.add_argument('--installed', action='store_true')
    p.add_argument('--json', action='store_true', help='machine-readable reporting output')
    p.add_argument('--color', choices=('auto', 'always', 'never'))
    p.add_argument('-p', '--preview', help='fzf preview-window layout')
    p.add_argument('--directory', help='completion destination directory (file-only for Bash/Zsh)')
    p.add_argument('--debug', action='store_true', help='phase timing diagnostics on stderr')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('-y', '--yes', action='store_true')
    return p


def report(data, as_json, color):
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                title = item.get('manager') or item.get('shell') or ''
                print(colored(title, 'title', color))
                for k, v in item.items():
                    if k not in ('manager', 'shell'):
                        print('  ' + k + ': ' + clean(v))
            else:
                print(clean(item))
    else:
        for k, v in data.items():
            print(colored(k + ': ', 'label', color) + clean(json.dumps(v) if isinstance(v, (dict, list)) else v))


def choose_manager(args, cfg):
    name = args.manager or cfg['manager']
    if name == 'auto':
        name = default_manager()
        if name == 'pacman' and not termux() and args.query:
            name = next((m for m in ('paru', 'yay') if available(m)), name)
    if name not in MANAGERS or not available(name):
        raise Error(f'Manager {name!r} is unavailable. Run pkgs managers.')
    if args.global_scope and name != 'npm':
        raise Error('--global is supported only with --manager npm.')
    return Backend(name, args.global_scope)


def execute(backend, action, names, args, cfg):
    names = validate_names(names, backend.name)
    if action == 'uninstall':
        with budget(45), phase('Reading installed packages'):
            installed = {key(p.name, backend.name) for p in backend.installed()}
        missing = [n for n in names if key(n, backend.name) not in installed and not
                   (backend.name == 'apt' and any(x.partition(':')[0] == n for x in installed))]
        if missing:
            raise Error('Not installed in selected scope: ' + ', '.join(missing))
    if backend.name == 'uv-tool' and action == 'install':
        plans = [backend.transaction(action, [n], args.yes) for n in names]
    else:
        plans = [backend.transaction(action, names, args.yes)]
    print(colored(f'{action.upper()} · {backend.name} · {backend.scope}', 'heading', cfg['color']))
    for cmd in plans:
        print('  ' + shlex.join(cmd))
    if args.dry_run:
        print('Dry run: no packages changed.')
        return 0
    if not args.yes:
        try:
            with open('/dev/tty', 'r+') as tty:
                tty.write('Proceed? [y/N] ')
                tty.flush()
                confirmed = tty.readline().strip().lower() in ('y', 'yes')
        except OSError:
            raise Error('No controlling terminal. Use --yes for an intentional noninteractive transaction.')
        if not confirmed:
            print('Cancelled; no packages changed.')
            return 0
    sys.stdout.flush()
    try:
        for cmd in plans:
            try:
                tty = open('/dev/tty', 'r')
            except OSError:
                tty = None
            try:
                rc = subprocess.run(cmd, stdin=tty).returncode
            finally:
                if tty: tty.close()
            if rc:
                return rc if rc > 0 else 128 - rc
    finally:
        # A failed backend may still have made partial progress.
        try:
            Cache(backend.cache_key).clear()
            invalidate_evidence(backend)
        except OSError as e:
            diagnostic(f'Cache invalidation failed: {e}', warning=True)
    return 0


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    with diagnostics('--debug' in args or os.environ.get('PKGS_DEBUG') == '1',
                     quiet=bool(args and args[0] in ('__complete', '__session'))):
        return _main(args)


def _main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv and argv[0] == '__session':
            return session(*argv[1:])
        if argv and argv[0] == '__complete':
            split = argv.index('--') if '--' in argv else len(argv)
            fuzzy = '--pick' in argv[:split]
            try:
                candidates = complete(argv[split+1:], config(), fuzzy)
                for name, desc in candidates:
                    print(name if fuzzy else name + '\t' + desc)
            except (Error, ValueError) as e:
                # No diagnostics in completion candidate output; only interactive pickers report failures.
                if fuzzy: print('pkgs: ' + str(e), file=sys.stderr)
                else: diagnostic(str(e))
                return 1
            return 0
        # Accept completion SHELL --install as a spelling of the action.
        if 'completion' in argv:
            argv = ['install' if a == '--install' else a for a in argv]
        p = parser()
        args = p.parse_intermixed_args(argv)
        if not args.command or args.command == 'help':
            p.print_help()
            return 0
        cfg = config()
        cfg['debug'] = args.debug
        if args.directory and args.command != 'completion':
            raise Error('--directory applies only to completion management.')
        if args.color: cfg['color'] = args.color
        if args.preview: cfg['preview'] = args.preview
        command = 'uninstall' if args.command == 'remove' else args.command
        if args.json and command not in ('list', 'info', 'managers', 'doctor', 'completion'):
            raise Error('--json is available for list, info, managers, doctor, and completion status.')
        if command == 'completion':
            if not 1 <= len(args.names) <= 2:
                raise Error('Usage: pkgs completion SHELL [install|update|status|uninstall]')
            shell = args.names[0].lower()
            if shell not in ('bash', 'zsh', 'fish'): raise Error('Shell must be bash, zsh, or fish.')
            if len(args.names) == 1:
                print(generated(shell), end='')
            else:
                if args.json and args.names[1] != 'status': raise Error('--json is supported for completion status.')
                if args.dry_run and args.names[1] != 'status':
                    if args.names[1] not in ('install', 'update', 'uninstall'):
                        raise Error('Unknown completion action.')
                    plan = preflight(shell, args.names[1], args.directory)
                    report({'shell': shell, 'file': str(plan['dest']), 'status': 'dry-run; no files changed'}, False, cfg['color'])
                else:
                    report(manage(shell, args.names[1], args.directory), args.json, cfg['color'])
            return 0
        if command == 'managers':
            report([{'manager': m, 'scope': Backend(m, args.global_scope and m == 'npm').scope,
                     'catalog': 'query + cached candidates' if m in ('npm', 'gem', 'paru', 'yay') else
                                'exact-name lookup + cached candidates' if m in ('pip', 'uv-tool') else 'local repository catalog',
                     'actions': 'install, uninstall, info, upgrade, list, search'} for m in MANAGERS if available(m)], args.json, cfg['color'])
            return 0
        if command == 'doctor':
            try:
                with budget(45), phase('Detecting backend'):
                    detected = default_manager()
            except Error as e:
                detected = str(e)
            report({'version': VERSION, 'environment': 'Termux' if termux() else sys.platform,
                    'default_manager': detected, 'configured_manager': cfg['manager'],
                    'python': sys.executable, 'fzf': fzf_details(),
                    'launcher': str(ROOT / 'pkgs'), 'pkgs_on_path': which('pkgs') or 'missing',
                    'command_shadowed': bool(which('pkgs') and Path(which('pkgs')).resolve() != (ROOT / 'pkgs').resolve()),
                    'cwd': str(Path.cwd()), 'virtual_env': os.environ.get('VIRTUAL_ENV', 'none'),
                    'completions': [manage(s, 'status') for s in ('bash', 'zsh', 'fish')]}, args.json, cfg['color'])
            return 0
        if command == 'cache':
            if args.names != ['clear']: raise Error('Usage: pkgs cache clear')
            directory = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'pkgs'
            for file in directory.glob('*.json'):
                # Only hashed catalog filenames belong to us.
                if len(file.stem) == 24 and all(c in '0123456789abcdef' for c in file.stem): file.unlink()
            print('Package inventory cache cleared.')
            return 0
        if command == 'search' and args.names:
            if args.query: raise Error('Use a positional query or --query, not both.')
            args.query = ' '.join(args.names)
            args.names = []
        elif args.query and args.names:
            raise Error('Use exact names or --query, not both.')
        if command in ('list', 'refresh') and args.names:
            raise Error(f'{command} does not accept package names.')
        if command == 'info' and not args.names: raise Error('Usage: pkgs info NAME ...')
        if args.query and command not in ('install', 'uninstall', 'search', 'list'):
            raise Error('--query applies to install, uninstall, search, and list.')
        preparation_started = time.monotonic()
        with budget(45), phase('Detecting backend'):
            backend = choose_manager(args, cfg)
        if command == 'info':
            names = validate_names(args.names, backend.name)
            with budget(45), phase('Reading installed packages'):
                installed = {key(p.name, backend.name): p for p in backend.installed()}
            rows = []
            metadata_failed = False
            for n in names:
                package = installed.get(key(n, backend.name), Package(n))
                package, notice = enrich(package, backend, cfg)
                if notice:
                    package.details['Notice'] = notice
                    metadata_failed |= notice.startswith('Metadata unavailable:')
                rows.append(package)
            if args.json: print(json.dumps([asdict(p) for p in rows], indent=2))
            else: print('\n\n'.join(render(p, backend, cfg['color']) for p in rows))
            return 1 if metadata_failed else 0
        if command in ('upgrade', 'refresh') or (command in ('install', 'uninstall') and args.names):
            return execute(backend, command, args.names, args, cfg)
        with budget(max(0, 45 - (time.monotonic() - preparation_started))):
            rows = inventory(backend, cfg, args.query if command != 'uninstall' else '',
                             installed_only=args.installed or command == 'uninstall')
        if command == 'list':
            if args.query:
                rows = [p for p in rows if args.query.lower() in (p.name + ' ' + p.description).lower()]
            if cfg.get('external_detection'):
                EvidenceCache(backend, cfg).apply(rows)
            if args.json: print(json.dumps([asdict(p) for p in rows], indent=2))
            else:
                for item in rows:
                    markers = ('[i]' if item.installed else '   ') + ('[e]' if item.external else '   ')
                    print(colored(markers, 'good' if item.installed else 'warn', cfg['color']) + ' ' + colored(item.name, 'title', cfg['color']) + ' ' + clean(item.version) + '  ' + clean(item.description))
            return 0
        selected = pick(rows, backend, cfg, args.query)
        if not selected: return 0
        if command == 'search':
            metadata_failed = False
            for item in selected:
                item, notice = enrich(item, backend, cfg)
                print(render(item, backend, cfg['color'], message=notice))
                metadata_failed |= notice.startswith('Metadata unavailable:')
            return 1 if metadata_failed else 0
        return execute(backend, command, [p.name for p in selected], args, cfg)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
    except (Error, OSError, ValueError, KeyError, IndexError) as e:
        print('pkgs: ' + str(e), file=sys.stderr)
        return 1
