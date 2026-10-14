"""Read-only inventories and explicit transaction argument arrays."""
import json
import os
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request
from .common import Package, Error, run, which, clean, query, remaining, diagnostic
from .detect import termux, SYSTEM


def paragraphs(text):
    result = []
    obj = {}
    key = None
    for line in text.splitlines() + ['']:
        if not line.strip():
            if obj:
                result.append(obj)
            obj, key = {}, None
        elif line[:1].isspace() and key:
            obj[key] += '\n' + line.strip()
        elif ':' in line:
            k, v = line.split(':', 1)
            key = k.strip().lower()
            obj[key] = v.strip()
    return result


def pypi(name):
    url = 'https://pypi.org/pypi/' + urllib.parse.quote(name, safe='') + '/json'
    try:
        with urllib.request.urlopen(url, timeout=remaining(12)) as r:
            data = json.load(r)['info']
        links = data.get('project_urls') or {}
        return Package(data['name'], data['version'], data.get('summary') or '',
                       url=links.get('Homepage') or data.get('home_page') or data['package_url'],
                       details={'License': data.get('license') or '', 'Python': data.get('requires_python') or ''})
    except Exception as e:
        raise Error(f'PyPI metadata unavailable for {name}: {e}') from e

class Backend:
    def __init__(self, name, global_scope=False):
        self.name = name
        self.global_scope = global_scope
        self.termux = termux()
        self.bin = ('dnf5' if which('dnf5') else 'dnf') if name == 'dnf' else name
        if name == 'apt':
            self.bin = 'apt' if which('apt') else 'apt-get'
        self.scope = ('global' if global_scope else str(Path.cwd())) if name == 'npm' else (
            f'Python {sys.executable}; venv={os.environ.get("VIRTUAL_ENV", "none")}' if name == 'pip' else
            'uv isolated tools' if name == 'uv-tool' else
            'RubyGems ' + os.environ.get('GEM_HOME', 'active default environment') if name == 'gem' else
            'Termux' if self.termux else 'system')
        self.cache_key = '|'.join([name, self.scope, os.environ.get('PREFIX', ''), os.environ.get('PATH', ''), os.environ.get('GEM_PATH', ''), os.environ.get('UV_TOOL_DIR', '')])
        self.remote_inventory = name in ('npm', 'pip', 'uv-tool', 'gem', 'paru', 'yay')

    def installed(self):
        n = self.name
        if n == 'apt':
            text = run(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Status}\t${binary:Summary}\n'])
            rows = []
            for l in text.splitlines():
                v = l.split('\t', 3)
                if len(v) == 4 and v[2] == 'installed':
                    rows.append(Package(v[0], v[1], v[3], True, v[1]))
            return rows
        if n in ('pacman', 'paru', 'yay'):
            # -Q supplies stable package/version fields; empty database exits 0.
            return [Package(v[0], v[1], installed=True, installed_version=v[1])
                    for l in run(['pacman', '-Q']).splitlines() if len(v := l.split()) >= 2]
        if n == 'dnf':
            text = run(['rpm', '-qa', '--qf', '%{NAME}.%{ARCH}\t%{VERSION}-%{RELEASE}\t%{SUMMARY}\n'])
            return [Package(v[0], v[1], v[2], True, v[1]) for l in text.splitlines() if len(v := l.split('\t', 2)) == 3]
        if n == 'xbps':
            rows = []
            for l in run(['xbps-query', '-l']).splitlines():
                v = l.split(None, 2)
                if len(v) >= 2 and v[0] == 'ii':
                    name, _, version = v[1].rpartition('-')
                    rows.append(Package(name, version, v[2] if len(v) > 2 else '', True, version))
            return rows
        if n == 'npm':
            args = ['npm', 'ls', '--depth=0', '--json'] + (['--global'] if self.global_scope else [])
            data = json.loads(run(args, allowed=(0, 1)))
            if 'dependencies' not in data and data.get('error'):
                raise Error(clean(data['error']))
            return [Package(k, v.get('version', ''), installed=True, installed_version=v.get('version', ''))
                    for k, v in data.get('dependencies', {}).items() if not v.get('missing')]
        if n == 'pip':
            return [Package(p['name'], p['version'], installed=True, installed_version=p['version'])
                    for p in json.loads(run([sys.executable, '-m', 'pip', 'list', '--format=json', '--disable-pip-version-check']))]
        if n == 'uv-tool':
            rows = []
            for l in run(['uv', 'tool', 'list']).splitlines():
                m = re.match(r'^([A-Za-z0-9_.-]+) v(\S+)', l)
                if m:
                    rows.append(Package(m[1], m[2], installed=True, installed_version=m[2]))
            return rows
        if n == 'gem':
            rows = []
            for l in run(['gem', 'list', '--local']).splitlines():
                m = re.match(r'^(\S+) \((.+)\)$', l)
                if m:
                    rows.append(Package(m[1], m[2], installed=True, installed_version=m[2]))
            return rows
        raise Error(f'Unsupported manager: {n}')

    def inventory(self, query='', offline=False):
        n = self.name
        if n == 'apt':
            rows = []
            for l in run(['apt-cache', 'search', '.']).splitlines():
                name, sep, desc = l.partition(' - ')
                if sep:
                    rows.append(Package(name, description=desc))
            return rows
        if n == 'pacman' or (n in ('paru', 'yay') and (not query or offline)):
            rows = []
            for l in run(['pacman', '-Sl']).splitlines():
                v = l.split()
                if len(v) >= 3:
                    rows.append(Package(v[1], v[2], repo=v[0]))
            return rows
        if n in ('paru', 'yay'):
            text = run([n, '-Ss', '--color', 'never', '--', query], allowed=(0, 1))
            rows = []
            for l in text.splitlines():
                if l[:1].isspace() and rows:
                    rows[-1].description = l.strip()
                else:
                    m = re.match(r'^(\S+)/(\S+)\s+(\S+)', l)
                    if m:
                        rows.append(Package(m[2], m[3], repo=m[1]))
            return rows
        if n == 'dnf':
            text = run([self.bin, '-q', '-C', 'repoquery', '--available', '--qf',
                        '%{name}.%{arch}\t%{version}-%{release}\t%{summary}\n'])
            return [Package(v[0], v[1], v[2]) for l in text.splitlines() if len(v := l.split('\t', 2)) == 3]
        if n == 'xbps':
            rows = []
            for l in run(['xbps-query', '-Rs', '']).splitlines():
                m = re.match(r'^\[[^]]+\]\s+(\S+)\s*(.*)$', l)
                if m:
                    name, _, version = m[1].rpartition('-')
                    rows.append(Package(name, version, m[2]))
            return rows
        if offline or not query:
            return []
        if n == 'npm':
            data = json.loads(run(['npm', 'search', '--json', '--', query]))
            return [Package(p['name'], p.get('version', ''), p.get('description', ''),
                            url=(p.get('links') or {}).get('homepage', '')) for p in data]
        if n in ('pip', 'uv-tool'):
            # No pip search service. Explicit queries are exact-name metadata lookups.
            return [pypi(query)]
        if n == 'gem':
            rows = []
            for l in run(['gem', 'search', '--remote', '--', re.escape(query)]).splitlines():
                m = re.match(r'^(\S+) \((.+)\)$', l)
                if m:
                    rows.append(Package(m[1], m[2]))
            return rows
        return []

    def info(self, p):
        n = self.name
        if n == 'apt':
            docs = paragraphs(run(['apt-cache', 'show', '--', p.name]))
            if not docs:
                raise Error(f'No metadata for {p.name}')
            d = docs[0]
            p.version = d.get('version', p.version)
            desc = d.get('description-en') or d.get('description') or p.description
            p.description = desc.replace('\n.\n', '\n\n')
            p.url = d.get('homepage', '')
            p.details = {k.title(): d[k] for k in ('architecture', 'section', 'installed-size', 'depends', 'maintainer') if k in d}
            if 'Installed-Size' in p.details:
                p.details['Installed size'] = p.details.pop('Installed-Size') + ' KiB'
        elif n in ('pacman', 'paru', 'yay'):
            cmd = ['pacman', '-Qi', '--', p.name] if p.installed else [n, '-Si', '--', p.name]
            docs = paragraphs(run(cmd))
            if not docs:
                raise Error(f'No metadata for {p.name}')
            d = docs[0]
            p.version, p.description, p.url = d.get('version', p.version), d.get('description', p.description), d.get('url', '')
            p.repo = d.get('repository', p.repo)
            p.details = {k.title(): d[k] for k in ('architecture', 'licenses', 'installed size', 'depends on', 'packager') if k in d}
        elif n == 'dnf':
            docs = paragraphs(run([self.bin, '-q', '-C', 'info', '--', p.name]))
            if not docs:
                raise Error(f'No metadata for {p.name}')
            d = docs[0]
            p.version, p.url = d.get('version', p.version), d.get('url', '')
            p.description = d.get('description', d.get('summary', p.description))
            p.details = {k.title(): d[k] for k in ('architecture', 'license', 'size', 'repository') if k in d}
        elif n == 'xbps':
            docs = paragraphs(run(['xbps-query'] + ([] if p.installed else ['-R']) + [p.name]))
            if not docs:
                raise Error(f'No metadata for {p.name}')
            d = docs[0]
            p.url, p.description = d.get('homepage', ''), d.get('short_desc', p.description)
            p.details = {k.replace('_', ' ').title(): d[k] for k in ('architecture', 'license', 'installed_size', 'maintainer') if k in d}
        elif n == 'npm':
            d = json.loads(run(['npm', 'view', p.name, '--json']))
            p.version, p.description = d.get('version', p.version), d.get('description', p.description)
            p.url = d.get('homepage') or 'https://www.npmjs.com/package/' + urllib.parse.quote(p.name, safe='@/')
            p.details = {'License': d.get('license', ''), 'Dependencies': ', '.join(d.get('dependencies', {}))}
        elif n in ('pip', 'uv-tool'):
            meta = pypi(p.name)
            p.version, p.description, p.url, p.details = meta.version, meta.description, meta.url, meta.details
        elif n == 'gem':
            # Official registry metadata; installed state remains from the local gem database.
            try:
                url = 'https://rubygems.org/api/v1/gems/' + urllib.parse.quote(p.name, safe='') + '.json'
                with urllib.request.urlopen(url, timeout=remaining(12)) as r:
                    d = json.load(r)
                p.version, p.description = d.get('version', p.version), d.get('info', p.description)
                p.url = d.get('homepage_uri') or d.get('project_uri', '')
                p.details = {'License': ', '.join(d.get('licenses') or [])}
            except Exception as e:
                raise Error(f'RubyGems metadata unavailable: {e}') from e
        return p

    def owner(self, path):
        n = self.name
        if n == 'apt':
            args = ['dpkg-query', '-S', path]
        elif n in ('pacman', 'paru', 'yay'):
            args = ['pacman', '-Qo', '--', path]
        elif n == 'dnf':
            args = ['rpm', '-qf', path]
        elif n == 'xbps':
            args = ['xbps-query', '-o', path]
        else:
            return None
        try:
            result = query(args, timeout=3)
            text = clean(result.stdout + ' ' + result.stderr)
            # XBPS returns a successful empty scan for an unowned path.
            if n == 'xbps' and result.returncode == 0 and not text:
                return ''
            if result.returncode == 0 and result.stdout.strip():
                return clean(result.stdout)
            unowned = {'apt': 'no path found matching pattern',
                       'pacman': 'no package owns', 'paru': 'no package owns',
                       'yay': 'no package owns', 'dnf': 'is not owned by any package',
                       'xbps': 'is not owned by any package'}
            if result.returncode == 1 and unowned[n] in text.lower():
                return ''
            self.ownership_error = f'{args[0]} ownership unavailable (exit {result.returncode}): {text}'
        except Error as e:
            self.ownership_error = str(e)
        diagnostic(self.ownership_error)
        return None

    def database_fingerprint(self):
        """Only persist ownership when a known local database can be identified."""
        prefix = Path(os.environ.get('PREFIX') or '/usr')
        if self.name == 'apt':
            root = Path(os.environ.get('DPKG_ADMINDIR') or
                        (str(prefix / 'var/lib/dpkg') if self.termux else '/var/lib/dpkg'))
            paths = [root / 'status', root / 'info']
        elif self.name in ('pacman', 'paru', 'yay'):
            paths = [prefix / 'var/lib/pacman/local' if self.termux else Path('/var/lib/pacman/local')]
        else:
            # RPM/XBPS layouts vary. Session cache only; never guess a database.
            return None
        try:
            return [[str(p), p.stat().st_ino, p.stat().st_mtime_ns, p.stat().st_ctime_ns, p.stat().st_size] for p in paths]
        except OSError:
            return None

    def transaction(self, action, names, yes=False):
        n = self.name
        if action == 'refresh' and n in ('pacman', 'paru', 'yay'):
            raise Error('Use pkgs upgrade with pacman to synchronize and upgrade together.')
        if self.termux and n in ('apt', 'pacman') and which('pkg'):
            args = ['pkg', {'uninstall': 'uninstall', 'refresh': 'update'}.get(action, action)]
            if yes:
                args += ['--noconfirm' if n == 'pacman' else '-y']
            args += names
        elif n == 'apt':
            args = [self.bin, {'uninstall': 'remove', 'refresh': 'update'}.get(action, action)] + (['-y'] if yes else []) + ['--'] + names
        elif n in ('pacman', 'paru', 'yay'):
            args = [n, {'install': '-S', 'uninstall': '-R', 'upgrade': '-Syu', 'refresh': '-Syy'}[action]] + (['--noconfirm'] if yes else []) + ['--'] + names
            if action == 'refresh':
                raise Error('Use pkgs upgrade on pacman to synchronize and upgrade together; standalone refresh can lead to partial upgrades.')
        elif n == 'dnf':
            args = [self.bin, {'uninstall': 'remove', 'refresh': 'makecache'}.get(action, action)] + (['-y'] if yes else []) + ['--'] + names
        elif n == 'xbps':
            args = ['xbps-remove' if action == 'uninstall' else 'xbps-install']
            if action == 'upgrade':
                args += ['-Su']
            elif action == 'refresh':
                args += ['-S']
            if yes:
                args += ['-y']
            args += names
        elif n == 'npm':
            if action == 'refresh':
                raise Error('npm has no local catalog to refresh; use search --query.')
            args = ['npm', 'update' if action == 'upgrade' else action] + (['--global'] if self.global_scope else []) + ['--'] + names
        elif n == 'uv-tool':
            if action == 'refresh':
                raise Error('uv tools have no local catalog to refresh.')
            args = ['uv', 'tool', action] + names
            if action == 'upgrade' and not names:
                args += ['--all']
        elif n == 'pip':
            if action == 'refresh':
                raise Error('pip has no local search catalog to refresh.')
            if action == 'upgrade' and not names:
                raise Error('Choose packages to upgrade for pip; a blanket environment upgrade is not supported.')
            args = [sys.executable, '-m', 'pip', 'install' if action == 'upgrade' else action]
            if action == 'upgrade':
                args += ['--upgrade']
            if action == 'uninstall' and yes:
                args += ['-y']
            args += names
        elif n == 'gem':
            if action == 'refresh':
                raise Error('RubyGems has no local search catalog to refresh.')
            args = ['gem', 'update' if action == 'upgrade' else action] + names
        else:
            raise Error('Unsupported transaction')
        if n in ('apt', 'pacman', 'dnf', 'xbps') and not self.termux and os.geteuid() != 0:
            if not which('sudo'):
                raise Error('sudo is required for system transactions (or run as root).')
            args.insert(0, 'sudo')
        return args
