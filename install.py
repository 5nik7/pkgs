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
from pkgs_lib.common import ROOT, Error, atomic
from pkgs_lib.completion import manage

MARKER = 'pkgs-user-install-v1'

def main():
    p = argparse.ArgumentParser(description='Install/uninstall pkgs and detected-shell completions.')
    p.add_argument('--prefix', type=Path, default=Path.home() / '.local')
    p.add_argument('--no-completions', action='store_true')
    p.add_argument('--uninstall', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
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
        if args.dry_run: return
        if not args.no_completions:
            for shell in previous.get('shells', []): manage(shell, 'uninstall')
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
    shells = [] if args.no_completions else [s for s in ('bash', 'zsh', 'fish') if shutil.which(s)]
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
            result = subprocess.run([sys.executable, str(target / 'main.py'), 'completion', shell, 'install'])
            if result.returncode: raise Error(f'pkgs installed, but {shell} completion setup failed; rerun pkgs completion {shell} install after fixing the reported conflict.')
    finally:
        if stage.exists(): shutil.rmtree(stage)
    print('Installed: ' + str(launcher))
    print('Add ' + str(prefix / 'bin') + ' to PATH if needed. Reload your shell config to activate completion.')

if __name__ == '__main__':
    try:
        main()
    except (Error, OSError, ValueError) as e:
        sys.exit('pkgs installer: ' + str(e))
