"""Environment detection: database evidence takes priority over PATH guesses."""
import os
from pathlib import Path
import shlex
import sys
from .common import Error, run, which

SYSTEM = ('apt', 'pacman', 'paru', 'yay', 'dnf', 'xbps')
MANAGERS = SYSTEM + ('npm', 'uv-tool', 'pip', 'gem')

def termux():
    return bool(os.environ.get('TERMUX_VERSION') or os.environ.get('TERMUX_APP_PACKAGE_MANAGER') or
                '/com.termux/' in os.environ.get('PREFIX', '') or
                '/com.termux/' in os.environ.get('HOME', ''))

def available(name):
    if name == 'apt':
        return bool(which('apt-cache') and which('dpkg-query') and (which('apt') or which('apt-get')))
    if name in ('paru', 'yay'):
        return bool(which(name) and which('pacman'))
    if name == 'xbps':
        return bool(which('xbps-query') and which('xbps-install'))
    if name == 'uv-tool':
        return bool(which('uv'))
    if name == 'pip':
        try:
            run([sys.executable, '-m', 'pip', '--version'])
            return True
        except Error:
            return False
    return bool(which(name) or (name == 'dnf' and which('dnf5')))

def default_manager():
    if termux():
        pm = os.environ.get('TERMUX_APP_PACKAGE_MANAGER', '').lower()
        if pm in ('apt', 'pacman') and available(pm):
            return pm
        prefix = Path(os.environ.get('PREFIX', '/data/data/com.termux/files/usr'))
        helper = prefix / 'bin/termux-setup-package-manager'
        if helper.is_file():
            # Official helper is sourced, as by pkg. Fixed shell program; path is an argument.
            pm = run(['bash', '-c', '. "$1" >/dev/null; printf "%s" "$TERMUX_APP_PACKAGE_MANAGER"', 'pkgs', str(helper)]).strip()
            if pm in ('apt', 'pacman') and available(pm):
                return pm
        found = [m for m, p in [('apt', prefix / 'var/lib/dpkg/status'),
                                ('pacman', prefix / 'var/lib/pacman/local')] if p.exists() and available(m)]
        if len(found) == 1:
            return found[0]
        raise Error('Cannot determine the Termux backend. Use --manager apt or --manager pacman; see pkgs doctor.')
    ids = []
    try:
        for line in Path('/etc/os-release').read_text().splitlines():
            k, sep, v = line.partition('=')
            if sep and k in ('ID', 'ID_LIKE'):
                ids.extend(' '.join(shlex.split(v)).lower().split())
    except OSError:
        pass
    for ident in ids:
        m = {'debian': 'apt', 'ubuntu': 'apt', 'arch': 'pacman', 'manjaro': 'pacman',
             'fedora': 'dnf', 'rhel': 'dnf', 'centos': 'dnf', 'void': 'xbps'}.get(ident)
        if m and available(m):
            return m
    raise Error('No supported default system manager detected. Choose --manager; run pkgs managers.')
