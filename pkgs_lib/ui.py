"""ANSI preview, safe fzf records, file-backed filtering and URL actions."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
import urllib.parse
from .common import ROOT, Package, Error, clean, atomic, which, budget, phase, diagnostics, diagnostic, run
from .backends import Backend
from .catalog import external, EvidenceCache
from .fzf import invocation, PROTOCOL
from .detect import termux

PALETTE = {'title': '1;35', 'heading': '1;36', 'good': '32', 'warn': '33', 'dim': '2', 'label': '36'}

def colored(text, kind, mode='auto', preview=False):
    enabled = mode == 'always' or (mode == 'auto' and 'NO_COLOR' not in os.environ and (preview or sys.stdout.isatty()))
    return '\x1b[' + PALETTE[kind] + 'm' + str(text) + '\x1b[0m' if enabled else str(text)


def render(p, backend, color='auto', preview=False, message=''):
    try:
        width = max(16, min(120, int(os.environ.get('FZF_PREVIEW_COLUMNS', '80')) - 2))
    except ValueError:
        width = 78
    out = []
    def c(s, k): return colored(s, k, color, preview)
    def wrap(value, indent=''):
        for para in str(value).splitlines() or ['']:
            out.extend(textwrap.wrap(clean(para), width=width, initial_indent=indent,
                                     subsequent_indent=indent) or [''])
    def heading(s): out.extend(['', c(s.upper(), 'heading')])
    def field(label, value, kind=None):
        if value in ('', None): return
        prefix = label + ': '
        if len(prefix) + 12 >= width:
            out.append(c(label + ':', 'label'))
            wrap(value, '  ')
        else:
            lines = textwrap.wrap(clean(value), width=max(10, width-len(prefix))) or ['']
            out.append(c(prefix, 'label') + (c(lines[0], kind) if kind else lines[0]))
            out.extend(' ' * len(prefix) + l for l in lines[1:])
    out.append(c(clean(p.name), 'title'))
    out.append(c('─' * min(width, 44), 'dim'))
    field('Manager', backend.name)
    field('Scope', backend.scope)
    field('Status', 'Installed [i]' if p.installed else 'Not installed', 'good' if p.installed else 'dim')
    field('Version', p.version)
    field('Installed', p.installed_version)
    field('Repository', p.repo)
    heading('Description')
    wrap(p.description or 'No description supplied by this package source.')
    if p.external:
        heading('External commands [e]')
        for e in p.external:
            field(e['command'], e['path'], 'warn')
            if e.get('resolved') != e['path']:
                field('Resolves to', e.get('resolved'))
            wrap(e['match'] + '; ' + e['position'] + '; ' + e['ownership'])
        wrap('An executable match is evidence, not proof that the repository package is installed.')
    if p.details:
        heading('Package details')
        for k, v in p.details.items():
            field(clean(k), v)
    heading('Links')
    wrap(p.url if valid_url(p.url) else 'No HTTP(S) homepage supplied.')
    if message:
        heading('Notice')
        wrap(message)
    if preview:
        out.extend(['', c('Alt-O open URL · Ctrl-X preview', 'dim')])
    return '\n'.join(out)


def valid_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        return parsed.scheme in ('https', 'http') and bool(parsed.hostname) and not re.search(r'[\x00-\x20\x7f]', url)
    except (ValueError, TypeError):
        return False


def opener(url):
    if not valid_url(url):
        raise Error('No valid HTTP(S) homepage available for this package.')
    if termux():
        for exe in ('termux-open-url', 'termux-open'):
            if which(exe):
                return [which(exe), url]
    if sys.platform == 'darwin' and which('open'):
        return [which('open'), url]
    if which('wslview'):
        return [which('wslview'), url]
    if which('xdg-open'):
        return [which('xdg-open'), url]
    if which('gio'):
        return [which('gio'), 'open', url]
    raise Error('No supported URL opener found (termux-open-url, termux-open, open, wslview, xdg-open, gio).')


def row(p, index, color):
    marker = (colored('[i]', 'good', color, True) if p.installed else '   ')
    marker += colored('[e]', 'warn', color, True) if p.external else '   '
    text = marker + ' ' + colored(clean(p.name), 'title', color, True)
    if p.version:
        text += ' ' + colored(clean(p.version), 'dim', color, True)
    if p.repo:
        text += ' [' + clean(p.repo) + ']'
    if p.description:
        text += ' — ' + clean(p.description)
    return str(index) + '\t' + text


def pick(rows, backend, cfg, query='', completion=False):
    fzf = which('fzf')
    if not fzf:
        raise Error('fzf is required for the picker. Install fzf or add ~/.fzf/bin to PATH.')
    if not rows:
        if backend.remote_inventory:
            raise Error('No cached candidates. Use install --query NAME (pip/uv: exact name), or supply exact package names.')
        diagnostic('No packages in the selected manager/scope.', warning=True)
        return []
    with phase('Preparing picker rows'):
        if cfg.get('external_detection'):
            EvidenceCache(backend, cfg).apply(rows)
    args, env = invocation(fzf)
    with tempfile.TemporaryDirectory(prefix='pkgs-') as tmp:
        root = Path(tmp)
        state = {'backend': backend.name, 'global': backend.global_scope, 'cfg': cfg,
                 'packages': [asdict(p) for p in rows]}
        atomic(root / 'state.json', json.dumps(state))
        atomic(root / 'all', '\n'.join(row(p, i, cfg['color']) for i, p in enumerate(rows)) + '\n')
        hidden_rows = [row(p, i, cfg['color']) for i, p in enumerate(rows) if not p.installed]
        atomic(root / 'hide', '\n'.join(hidden_rows) + ('\n' if hidden_rows else ''))
        env.update(PKGS_SESSION=tmp, PKGS_MAIN=str(ROOT / 'main.py'), PKGS_PYTHON=sys.executable)
        helper = 'exec "$PKGS_PYTHON" "$PKGS_MAIN" __session '
        binds = ['ctrl-x:toggle-preview', 'alt-i:reload(' + helper + 'toggle)',
                 'alt-o:execute-silent(' + helper + 'open {1})+refresh-preview',
                 'tab:toggle+down', 'shift-tab:toggle+up']
        args += ['--ansi', '--multi', '--cycle', '+e', '--no-hscroll',
                '--delimiter=\t', '--with-nth=2..', '--preview=' + helper + 'preview {1}',
                '--preview-window=' + cfg['preview'], '--query=' + query,
                '--header=' + backend.name + ' · ' + backend.scope + '\nTab select · Ctrl-X preview · Alt-I installed · Alt-O URL\nEnter ' + ('insert names' if completion else 'accept') + ' · Esc cancel · [e] cached; highlight for current evidence',
                '--bind=' + ','.join(binds)]
        if cfg['color'] == 'never' or (cfg['color'] == 'auto' and 'NO_COLOR' in os.environ):
            args += ['--color=bw']
        # Preserve FZF_DEFAULT_OPTS/FILE (including colors); override record/output settings only.
        args += PROTOCOL
        with (root / 'all').open() as stream:
            diagnostic('Launching fzf: ' + fzf)
            proc = subprocess.run(args, stdin=stream, stdout=subprocess.PIPE, text=True, env=env)
        if proc.returncode in (1, 130):
            return []
        if proc.returncode:
            raise Error(f'fzf exited {proc.returncode}')
        selected = []
        for line in proc.stdout.splitlines():
            if not line: continue
            ident = line.partition('\t')[0]
            if not ident.isdigit() or int(ident) >= len(rows):
                raise Error('Unexpected fzf output. Check output-changing FZF_DEFAULT_OPTS.')
            p = rows[int(ident)]
            if p.name not in [x.name for x in selected]:
                selected.append(p)
        return selected


def session(action, ident=None):
    root = Path(os.environ['PKGS_SESSION'])
    if action == 'toggle':
        flag = root / 'hidden'
        if flag.exists():
            flag.unlink()
            source = 'all'
        else:
            flag.touch()
            source = 'hide'
        print((root / source).read_text(), end='')
        return 0
    data = json.loads((root / 'state.json').read_text())
    if action not in ('preview', 'open') or ident is None or not ident.isdigit():
        raise Error('Invalid preview action or identifier.')
    index = int(ident)
    p = Package(**data['packages'][index])
    backend = Backend(data['backend'], data['global'])
    detail_file = root / ('detail-' + str(index) + '.json')
    message_file = root / ('message-' + str(index))
    message = message_file.read_text() if message_file.exists() else ''
    cfg = data['cfg']
    if action == 'preview':
        print(render(p, backend, cfg['color'], True, 'Loading metadata and external evidence…'), flush=True)
    with diagnostics(cfg.get('debug', False), quiet=True):
        if detail_file.exists():
            saved = json.loads(detail_file.read_text())
            p = Package(**saved['package'])
            message = saved.get('notice', '') or message
        else:
            with budget(5):
                p, notice = enrich(p, backend, cfg)
            message = notice or message
            atomic(detail_file, json.dumps({'package': asdict(p), 'notice': notice}))
    if action == 'open':
        try:
            run(opener(p.url), timeout=5)
            message = 'Opened package homepage.'
        except (Error, OSError) as e:
            message = str(e)
        atomic(message_file, message)
        return 0
    # fzf supports clearing a streamed preview; this escape is our own control,
    # never untrusted metadata. Basic information was visible throughout the wait.
    print('\x1b[2J' + render(p, backend, cfg['color'], True, message), flush=True)
    return 0


def enrich(p, backend, cfg):
    """Bounded optional enrichment, also used after accepting search results."""
    notices = []
    with budget(5):
        try:
            with phase('Reading package metadata'):
                p = backend.info(p)
        except (Error, OSError, ValueError) as e:
            notices.append('Metadata unavailable: ' + str(e))
        try:
            p = external(p, backend, cfg, cache=EvidenceCache(backend, cfg))
        except (Error, OSError) as e:
            notices.append('External evidence unavailable: ' + str(e))
    return p, '; '.join(notices)
