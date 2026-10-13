"""Offline candidates and repeatable, minimally invasive shell setup."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time
from . import VERSION
from .common import ROOT, Error, atomic, which, clean
from .detect import MANAGERS, available, default_manager
from .backends import Backend
from .catalog import inventory
from .ui import pick

COMMANDS = {'install': 'Install exact names or open a picker', 'uninstall': 'Remove installed packages',
            'remove': 'Alias for uninstall', 'search': 'Read-only search picker', 'list': 'Print package inventory',
            'info': 'Readable package details', 'upgrade': 'Upgrade packages', 'refresh': 'Refresh repository metadata',
            'managers': 'Detected managers and capabilities', 'doctor': 'Detection and completion diagnostics',
            'completion': 'Generate or install shell completions', 'cache': 'Clear cached catalogs', 'help': 'Show usage'}
OPTIONS = {'--manager': 'Select manager', '--query': 'Filter/search the picker', '--global': 'npm global scope',
           '--installed': 'Installed inventory only', '--json': 'Machine-readable output', '--color': 'auto/always/never',
           '--preview': 'fzf preview-window layout', '--dry-run': 'Print transaction without executing',
           '--yes': 'Confirm transaction automatically', '--help': 'Show help', '-H': 'Show help', '--version': 'Show version'}
VALUE_OPTIONS = ('--manager', '--query', '--color', '--preview', '-p')


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
    current, before, manager, command, global_scope, used = context(words, cfg)
    candidates = []
    if before and before[-1] == '--manager':
        candidates = [(m, 'package manager') for m in MANAGERS if available(m)]
    elif before and before[-1] == '--color':
        candidates = [(m, 'color mode') for m in ('auto', 'always', 'never')]
    elif before and before[-1] in ('--query', '--preview', '-p'):
        return []
    elif current.startswith('-'):
        candidates = list(OPTIONS.items())
    elif not command:
        candidates = list(COMMANDS.items())
    elif command == 'completion':
        candidates = [(x, 'shell') for x in ('bash', 'zsh', 'fish')] if not used else [(x, 'completion action') for x in ('install', 'status', 'uninstall')]
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
        p = subprocess.run([which('fzf'), '--ansi', '--no-multi', '+e', '--query=' + current,
                            '--delimiter=\t', '--with-nth=1,2', '--no-preview', '--header=Enter insert · Esc cancel',
                            '--no-print-query', '--no-read0', '--no-print0', '--expect='],
                           input=''.join(a + '\t' + clean(b) + '\n' for a, b in candidates),
                           stdout=subprocess.PIPE, text=True)
        if p.returncode in (1, 130): return []
        if p.returncode: raise Error(f'fzf exited {p.returncode}')
        selected = p.stdout.split('\t', 1)[0].strip()
        return [(a, b) for a, b in candidates if a == selected]
    return [(a, clean(b)) for a, b in candidates if a.startswith(current)]


def locations(shell):
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
    q = shlex.quote(str(dest))
    if shell == 'bash':
        return '[ -r ' + q + ' ] && source ' + q
    if shell == 'zsh':
        return 'fpath=(' + shlex.quote(str(dest.parent)) + ' $fpath)\nautoload -Uz compinit\n(( $+functions[compdef] )) || compinit\nautoload -Uz _pkgs\ncompdef _pkgs pkgs'
    # Fish accepts single-quoted paths but not POSIX quote concatenation escapes.
    q = "'" + str(dest).replace('\\', '\\\\').replace("'", "\\'") + "'"
    return 'if status is-interactive\n    source ' + q + '\nend'


def backup(path):
    if path.exists():
        dest = path.with_name(path.name + '.pkgs-backup-' + str(time.time_ns()))
        shutil.copy2(path, dest)
        return dest


def managed_block(text, body=None):
    start, end = '# >>> pkgs completion >>>', '# <<< pkgs completion <<<'
    if text.count(start) != text.count(end) or text.count(start) > 1:
        raise Error('Malformed/duplicate pkgs startup blocks; repair them before reinstalling.')
    if start in text:
        a, b = text.index(start), text.index(end) + len(end)
        if b <= a: raise Error('Malformed pkgs startup block.')
        text = text[:a] + text[b:].lstrip('\n')
    if body is not None:
        text = text.rstrip('\n') + ('\n\n' if text.strip() else '') + start + '\n' + body + '\n' + end + '\n'
    return text


def manage(shell, action):
    shell = shell.lower()
    dest, rc = locations(shell)
    expected = generated(shell)
    body = startup(shell, dest)
    current = dest.read_text() if dest.exists() else ''
    rc_text = rc.read_text() if rc.exists() else ''
    if action == 'status':
        return {'shell': shell, 'file': str(dest), 'startup': str(rc),
                'status': 'current' if current == expected and body in rc_text else 'outdated' if current else 'missing',
                'version': VERSION}
    if action not in ('install', 'uninstall'):
        raise Error('Completion action must be install, status, or uninstall.')
    if current and '# pkgs managed completion' not in current:
        raise Error(f'{dest} is not a pkgs-managed file. Move it aside before installing.')
    updated = managed_block(rc_text, body if action == 'install' else None)
    backups = []
    # Preserve existing symlink targets and startup-file permissions.
    rc_target = rc.resolve() if rc.is_symlink() else rc
    if updated != rc_text:
        saved = backup(rc_target)
        if saved: backups.append(str(saved))
        mode = rc_target.stat().st_mode & 0o777 if rc_target.exists() else 0o600
        atomic(rc_target, updated, mode)
    if action == 'install' and current != expected:
        if current:
            saved = backup(dest)
            backups.append(str(saved))
        atomic(dest, expected, 0o644)
    elif action == 'uninstall' and dest.exists():
        if current != expected:
            saved = backup(dest)
            backups.append(str(saved))
        dest.unlink()
    return {'shell': shell, 'file': str(dest), 'status': 'installed' if action == 'install' else 'removed',
            'backups': backups, 'activate': ('source ' + shlex.quote(str(rc))) if shell != 'fish' else 'source ' + str(rc)}
