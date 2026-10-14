#!/usr/bin/env python3
"""Install pkgs into a user prefix; never touches package-manager databases."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from pkgs_lib import VERSION
from pkgs_lib.common import ROOT, Error, atomic, which
from pkgs_lib.completion import manage, preflight

MARKER = 'pkgs-user-install-v1'

def main():
    p = argparse.ArgumentParser(description='Install/uninstall pkgs and detected-shell completions.')
    p.add_argument('--prefix', type=Path, default=Path.home() / '.local')
    p.add_argument('--completion-dir', action='append', default=[], metavar='SHELL=DIR',
                   help='explicit completion directory; repeat for multiple shells')
    p.add_argument('--no-completions', action='store_true')
    p.add_argument('--uninstall', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    overrides = {}
    for setting in args.completion_dir:
        shell, sep, directory = setting.partition('=')
        if shell not in ('bash', 'zsh', 'fish') or not sep or not directory:
            raise Error('--completion-dir requires bash=DIR, zsh=DIR, or fish=DIR')
        overrides[shell] = directory
    if args.no_completions and overrides:
        raise Error('--no-completions cannot be combined with --completion-dir')
    prefix = args.prefix.expanduser().absolute()
    target = prefix / 'lib/pkgs'
    manifest = target / 'install.json'
    launcher = prefix / 'bin/pkgs'
    man = prefix / 'share/man/man1/pkgs.1'
    previous = json.loads(manifest.read_text()) if manifest.exists() else {}
    if target.exists() and previous.get('marker') != MARKER:
        raise Error(f'{target} is not a managed pkgs installation.')
    if args.uninstall:
        if not previous:
            print('No managed installation at ' + str(target))
            return
        print('Remove managed pkgs installation: ' + str(target))
        if not args.no_completions:
            for shell in previous.get('shells', []): preflight(shell, 'uninstall', overrides.get(shell))
        if args.dry_run: return
        if not args.no_completions:
            for shell in previous.get('shells', []): manage(shell, 'uninstall', overrides.get(shell))
        for link in (launcher, man):
            if link.is_symlink() and link.resolve().is_relative_to(target.resolve()):
                link.unlink()
        shutil.rmtree(target)
        print('Removed pkgs. User configuration and caches were retained.')
        return
    for link in (launcher, man):
        if link.exists() or link.is_symlink():
            if not (link.is_symlink() and link.resolve().is_relative_to(target.resolve())):
                raise Error(f'Refusing to overwrite unrelated file: {link}')
    shells = [] if args.no_completions else [s for s in ('bash', 'zsh', 'fish') if shutil.which(s) or s in overrides]
    destinations = {}
    for shell in shells:
        plan = preflight(shell, 'install', overrides.get(shell))
        destinations[shell] = str(plan['dest'].parent)
        print(f'{shell} completion → {plan["dest"]} ({plan["source"]}; activation unverified)')
    print(f'Install pkgs {VERSION} → {target}')
    print('Completion shells: ' + (', '.join(shells) or 'none'))
    if args.dry_run: return
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.pkgs-install-', dir=target.parent))
    try:
        shutil.copytree(ROOT, stage, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.git'))
        atomic(stage / 'install.json', json.dumps({'marker': MARKER, 'version': VERSION, 'shells': sorted(set(shells + previous.get('shells', [])))}))
        if target.exists():
            # Keep one explicit recoverable installation backup, with no overwrite.
            backup = target.with_name('pkgs.backup-' + str(time.time_ns()))
            target.rename(backup)
            print('Previous installation backup: ' + str(backup))
        stage.rename(target)
        for link, source in ((launcher, target / 'pkgs'), (man, target / 'docs/pkgs.1')):
            link.parent.mkdir(parents=True, exist_ok=True)
            temporary = link.with_name(link.name + '.pkgs-new')
            if temporary.exists() or temporary.is_symlink():
                raise Error(f'Stale staging link exists: {temporary}')
            temporary.symlink_to(source)
            os.replace(temporary, link)
        for shell in shells:
            result = subprocess.run([sys.executable, str(target / 'main.py'), 'completion', shell, 'install', '--directory', destinations[shell]])
            if result.returncode: raise Error(f'pkgs installed, but {shell} completion setup failed; rerun pkgs completion {shell} install after fixing the reported conflict.')
    finally:
        if stage.exists(): shutil.rmtree(stage)
    print('Installed: ' + str(launcher))
    found = which('pkgs')
    if found and Path(found).resolve() != launcher.resolve():
        print('Warning: pkgs currently resolves to ' + found + '; use ' + str(launcher) + ' to test this installation.')
    print('Use the printed shell-specific activation instructions; startup configuration is owned by you.')

if __name__ == '__main__':
    try:
        main()
    except (Error, OSError, ValueError) as e:
        sys.exit('pkgs installer: ' + str(e))
