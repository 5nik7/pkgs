"""Shared fzf protocol and child-shell boundary (fzf >= 0.48)."""
import os
from pathlib import Path
import re
import shlex
import shutil
from .common import Error, which, run

PROTOCOL = ['--no-read0', '--no-print0', '--no-print-query', '--no-expect',
            '--bind=enter:accept,esc:abort,ctrl-c:abort']


def details(executable=None):
    executable = executable or which('fzf')
    result = {'path': executable or '', 'source': 'PATH' if shutil.which('fzf') else '~/.fzf/bin/fzf fallback'}
    if not executable:
        result.update(version='missing', supported=False)
        return result
    try:
        version = run([executable, '--version'], timeout=2).strip()
        match = re.match(r'(\d+)\.(\d+)', version)
        pair = tuple(map(int, match.groups())) if match else (0, 0)
        result.update(version=version, supported=pair >= (0, 48), with_shell=pair >= (0, 51))
    except Error as e:
        result.update(version=str(e), supported=False)
    return result


def invocation(executable=None):
    executable = executable or which('fzf')
    if not executable:
        raise Error('fzf is required for the picker (PATH or ~/.fzf/bin/fzf).')
    info = details(executable)
    if not info['supported']:
        raise Error(f'fzf 0.48+ required: {info["path"]}: {info["version"]}')
    bash = which('bash')
    if not bash:
        raise Error('Bash is required for pkgs picker helpers.')
    env = {**os.environ, 'SHELL': bash}
    for key in ('BASH_ENV', 'ENV', 'SHELLOPTS', 'BASHOPTS'):
        env.pop(key, None)
    # Keep colors and compatible user defaults. Reject known output-changing
    # settings rather than allowing --filter to silently accept a transaction.
    defaults = env.get('FZF_DEFAULT_OPTS', '')
    if env.get('FZF_DEFAULT_OPTS_FILE'):
        try: defaults = Path(env['FZF_DEFAULT_OPTS_FILE']).read_text() + '\n' + defaults
        except OSError as e: raise Error(f'Cannot read FZF_DEFAULT_OPTS_FILE: {e}') from e
    try:
        tokens = shlex.split(defaults, comments=True)
    except ValueError as e:
        raise Error(f'Invalid fzf defaults: {e}') from e
    for token in tokens:
        if token.split('=', 1)[0] in ('--filter', '-f', '--accept-nth', '--print') or (token.startswith('-f') and not token.startswith('--')):
            raise Error(f'Incompatible fzf default {token!r}; use a per-command override for this picker.')
    args = [executable]
    if info.get('with_shell'):
        args += ['--with-shell=' + shlex.join([bash, '--noprofile', '--norc', '-c'])]
    return args, env
