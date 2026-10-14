import contextlib
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pkgs_lib import VERSION
from pkgs_lib.common import Package, Error, Cache, config, validate_names
from pkgs_lib.backends import Backend
from pkgs_lib.catalog import inventory, external
from pkgs_lib import cli, ui, completion, detect

class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='pkgs-test-')
        self.home = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'HOME': str(self.home), 'XDG_CACHE_HOME': str(self.home/'cache'),
                                         'XDG_STATE_HOME': str(self.home/'state'), 'FPATH': '', 'FZF_DEFAULT_OPTS': '', 'FZF_DEFAULT_OPTS_FILE': '',
                                         'BASH_COMPLETION_USER_DIR': '', 'XDG_CONFIG_HOME': str(self.home/'config'), 'XDG_DATA_HOME': str(self.home/'data'),
                                         'ZDOTDIR': str(self.home/'z dot'), 'TERMUX_VERSION': '', 'TERMUX_APP_PACKAGE_MANAGER': '',
                                         'PREFIX': '', 'PKGS_FUZZY_TAB': '0'})
        self.env.start()
        self.cfg = config()
        self.cfg['external_detection'] = False
    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()
    def invoke(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(list(args))
        return rc, out.getvalue(), err.getvalue()

class Core(Isolated):
    def test_bare_help_no_backends(self):
        with patch('pkgs_lib.cli.choose_manager', side_effect=AssertionError):
            rc, out, _ = self.invoke()
        self.assertEqual(rc, 0)
        self.assertIn('Alt-O', out)
    def test_help_aliases_and_version(self):
        for flag in ('-h', '-H', '--help'):
            p = subprocess.run([str(ROOT/'pkgs'), flag], text=True, capture_output=True)
            self.assertEqual(p.returncode, 0)
            self.assertIn('usage:', p.stdout)
        self.assertIn(VERSION, subprocess.check_output([str(ROOT/'pkgs'), '--version'], text=True))
    def test_missing_option_value(self):
        p = subprocess.run([str(ROOT/'pkgs'), 'install', '--preview'], text=True, capture_output=True)
        self.assertEqual(p.returncode, 2)
    def test_options_before_and_after_command(self):
        p = cli.parser()
        a = p.parse_intermixed_args(['--manager', 'npm', 'install', '--global', '@scope/name', '--dry-run'])
        self.assertEqual(a.names, ['@scope/name'])
        self.assertTrue(a.global_scope and a.dry_run)
    def test_package_injection_rejected(self):
        for name in ('-bad', 'x;touch bad', '$(id)', 'x\ny', 'https://bad', 'x*', 'x/../../y'):
            with self.assertRaises(Error): validate_names([name], 'apt')
        self.assertEqual(validate_names(['@scope/pkg'], 'npm'), ['@scope/pkg'])
    def test_query_exact_separation(self):
        self.assertEqual(self.invoke('install', 'git', '--query', 'git')[0], 1)
    def test_invalid_manager_configuration(self):
        path = self.home/'config/pkgs/config.json'
        path.parent.mkdir(parents=True)
        path.write_text('{"commands":{"fzf":"not-a-list"}}')
        with self.assertRaises(Error): config()
    def test_backend_error_propagates(self):
        b = Backend('apt')
        with patch.object(b, 'installed', side_effect=Error('database broke')):
            with self.assertRaisesRegex(Error, 'database broke'): inventory(b, self.cfg)
    def test_failed_transaction_invalidates_catalog(self):
        b = Backend('apt')
        c = Cache(b.cache_key)
        c.save([Package('git')])
        args = cli.parser().parse_intermixed_args(['install', 'git', '--yes'])
        with patch.object(b, 'transaction', return_value=['fake', 'git']), patch('pkgs_lib.cli.subprocess.run', return_value=MagicMock(returncode=42)):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.execute(b, 'install', ['git'], args, self.cfg), 42)
        self.assertIsNone(c.load())
    def test_dry_run_never_executes(self):
        b = Backend('apt')
        with patch('pkgs_lib.cli.choose_manager', return_value=b), patch.object(b, 'transaction', return_value=['apt', 'install', 'git']), patch('pkgs_lib.cli.subprocess.run', side_effect=AssertionError):
            rc, out, _ = self.invoke('install', 'git', '--dry-run')
        self.assertEqual(rc, 0)
        self.assertIn('no packages changed', out)
    def test_external_only_uninstall_rejected(self):
        b = Backend('apt')
        with patch('pkgs_lib.cli.choose_manager', return_value=b), patch.object(b, 'installed', return_value=[]):
            rc, _, err = self.invoke('uninstall', 'fzf', '--dry-run')
        self.assertEqual(rc, 1)
        self.assertIn('Not installed', err)

class Backends(Isolated):
    def test_dpkg_only_installed_status(self):
        fixture = 'git\t2.0\tinstalled\tversion control\nold\t1\tconfig-files\tremoved\npartial\t1\tunpacked\tpartial\n'
        with patch('pkgs_lib.backends.run', return_value=fixture):
            self.assertEqual([p.name for p in Backend('apt').installed()], ['git'])
    def test_apt_metadata_wrapping_source(self):
        fixture = 'Package: fzf\nVersion: 0.65\nHomepage: https://example.org\nDescription: Fuzzy finder\n Finds packages quickly.\n .\n Second paragraph.\nInstalled-Size: 200\n'
        with patch('pkgs_lib.backends.run', return_value=fixture):
            p = Backend('apt').info(Package('fzf'))
        self.assertEqual(p.url, 'https://example.org')
        self.assertIn('\n\n', p.description)
        self.assertEqual(p.details['Installed size'], '200 KiB')
    def test_catalog_built_once_and_installed_state_live(self):
        b = Backend('apt')
        with patch.object(b, 'installed', side_effect=[[Package('git', installed=True, installed_version='1')], []]), patch.object(b, 'inventory', return_value=[Package('git')]) as source:
            first = inventory(b, self.cfg)
            second = inventory(b, self.cfg)
        self.assertTrue(first[0].installed)
        self.assertFalse(second[0].installed)
        self.assertEqual(source.call_count, 1)
    def test_uninstall_never_queries_remote(self):
        b = Backend('npm')
        with patch.object(b, 'installed', return_value=[Package('one', installed=True)]), patch.object(b, 'inventory', side_effect=AssertionError):
            self.assertEqual(inventory(b, self.cfg, installed_only=True)[0].name, 'one')
    def test_offline_registry_uses_cache(self):
        b = Backend('npm')
        Cache(b.cache_key).save([Package('known')])
        with patch.object(b, 'installed', return_value=[]), patch.object(b, 'inventory', side_effect=AssertionError):
            self.assertEqual(inventory(b, self.cfg, 'k', offline=True)[0].name, 'known')
    def test_pacman_and_aur_formats(self):
        with patch('pkgs_lib.backends.run', return_value='extra/fzf 0.65-1 [installed]\n    fuzzy finder\naur/foo 1-1\n    test package\n'):
            rows = Backend('yay').inventory('finder')
        self.assertEqual([p.name for p in rows], ['fzf', 'foo'])
        self.assertEqual(rows[0].description, 'fuzzy finder')
    def test_xbps_hyphenated_names(self):
        with patch('pkgs_lib.backends.run', return_value='ii foo-bar-1.2_1 Description\nhr removed-1_1 Gone\n'):
            rows = Backend('xbps').installed()
        self.assertEqual([(p.name, p.version) for p in rows], [('foo-bar', '1.2_1')])
    def test_npm_json_scope(self):
        with patch('pkgs_lib.backends.run', return_value='{"dependencies":{"@scope/p":{"version":"2"},"missing":{"missing":true}}}') as run:
            rows = Backend('npm', True).installed()
        self.assertEqual([p.name for p in rows], ['@scope/p'])
        self.assertIn('--global', run.call_args.args[0])
    def test_uv_list_ignores_entry_points(self):
        with patch('pkgs_lib.backends.run', return_value='ruff v0.9.0\n- ruff\nhttpie v3.2\n- http\n- https\n'):
            self.assertEqual([p.name for p in Backend('uv-tool').installed()], ['ruff', 'httpie'])
    def test_gem_local_list(self):
        with patch('pkgs_lib.backends.run', return_value='rake (13.2, 13.1)\njson (default: 2.0)\n'):
            self.assertEqual(len(Backend('gem').installed()), 2)
    def test_pip_json(self):
        with patch('pkgs_lib.backends.run', return_value='[{"name":"my-tool","version":"1.0"}]') as run:
            self.assertEqual(Backend('pip').installed()[0].name, 'my-tool')
            self.assertEqual(run.call_args.args[0][:3], [sys.executable, '-m', 'pip'])
    def test_dnf_architecture_identity(self):
        with patch('pkgs_lib.backends.run', return_value='git.x86_64\t2.1-1\tVersion control\n'):
            self.assertEqual(Backend('dnf').inventory()[0].name, 'git.x86_64')
    def test_termux_pacman_confirmation_flag(self):
        with patch('pkgs_lib.backends.termux', return_value=True), patch('pkgs_lib.backends.which', return_value='/prefix/bin/pkg'):
            b = Backend('pacman')
            cmd = b.transaction('install', ['fzf'], True)
        self.assertEqual(cmd, ['pkg', 'install', '--noconfirm', 'fzf'])
    def test_termux_never_sudo(self):
        with patch('pkgs_lib.backends.termux', return_value=True), patch('pkgs_lib.backends.which', return_value='/prefix/bin/pkg'), patch('os.geteuid', return_value=1000):
            self.assertEqual(Backend('apt').transaction('install', ['git'])[0], 'pkg')
    def test_pacman_refresh_guard(self):
        with self.assertRaises(Error): Backend('pacman').transaction('refresh', [])
    def test_pip_upgrade_requires_names(self):
        with self.assertRaises(Error): Backend('pip').transaction('upgrade', [])
    def test_termux_detection_explicit_backend(self):
        with patch.dict(os.environ, {'TERMUX_APP_PACKAGE_MANAGER': 'pacman'}), patch('pkgs_lib.detect.available', return_value=True):
            self.assertEqual(detect.default_manager(), 'pacman')
    def test_termux_ambiguous_not_assumed_apt(self):
        with patch.dict(os.environ, {'TERMUX_VERSION': 'test', 'PREFIX': str(self.home/'empty')}):
            with self.assertRaises(Error): detect.default_manager()

class Preview(Isolated):
    def test_color_and_no_color(self):
        p = Package('fzf', '0.1', 'Easy to read descriptions.', True, '0.1')
        with patch.dict(os.environ, {'NO_COLOR': '1'}):
            self.assertNotIn('\x1b', ui.render(p, Backend('apt'), preview=True))
        self.assertIn('\x1b', ui.render(p, Backend('apt'), 'always', True))
    def test_narrow_preview_and_control_sanitization(self):
        p = Package('demo', description='unsafe\x1b]52;clipboard\x07\n' + 'wrapped description '*12, url='https://example.org')
        with patch.dict(os.environ, {'FZF_PREVIEW_COLUMNS': '32'}):
            out = ui.render(p, Backend('apt'), 'never')
        self.assertNotIn('\x1b', out)
        self.assertNotIn('\x07', out)
        self.assertTrue(all(len(l) <= 30 for l in out.splitlines()))
    def test_url_schemes(self):
        for url in ('file:///etc/passwd', 'javascript:alert(1)', 'https://bad\nurl', '-bad', 'https://'):
            with self.assertRaises(Error): ui.opener(url)
    def test_termux_url_opener_array(self):
        with patch('pkgs_lib.ui.termux', return_value=True), patch('pkgs_lib.ui.which', side_effect=lambda x: '/bin/'+x if x == 'termux-open-url' else None):
            self.assertEqual(ui.opener('https://example.org/a?x=1&y=2'), ['/bin/termux-open-url', 'https://example.org/a?x=1&y=2'])
    def test_external_source_command_and_mapping(self):
        folder = self.home/'bin'
        folder.mkdir()
        exe = folder/'rg'
        exe.write_text('#!/bin/sh\n')
        exe.chmod(0o755)
        b = Backend('apt')
        self.cfg['external_detection'] = True
        with patch.dict(os.environ, {'PATH': str(folder)}), patch.object(b, 'owner', return_value=''):
            p = external(Package('ripgrep'), b, self.cfg)
        self.assertEqual(p.external[0]['command'], 'rg')
        self.assertEqual(p.external[0]['match'], 'known command mapping')
    def test_owned_command_not_external(self):
        folder = self.home/'bin'
        folder.mkdir()
        exe = folder/'fzf'
        exe.write_text('')
        exe.chmod(0o755)
        self.cfg['external_detection'] = True
        b = Backend('apt')
        with patch.dict(os.environ, {'PATH': str(folder)}), patch.object(b, 'owner', return_value='fzf: /bin/fzf'):
            self.assertFalse(external(Package('fzf'), b, self.cfg).external)
    def fake_fzf(self, body):
        path = self.home/'fake-fzf'
        path.write_text('#!' + sys.executable + '\nimport sys\nif \"--version\" in sys.argv: print(\"0.74.5\"); sys.exit(0)\n' + body)
        path.chmod(0o755)
        return str(path)
    def test_picker_raw_identity_and_cleanup(self):
        path = self.fake_fzf('import sys,os\nlines=sys.stdin.read().splitlines()\nprint(lines[1])\n')
        with patch('pkgs_lib.ui.which', return_value=path):
            rows = ui.pick([Package('first'), Package('@scope/name', description='tabs\there')], Backend('npm'), self.cfg)
        self.assertEqual([p.name for p in rows], ['@scope/name'])
    def test_picker_cancel_and_failure_distinct(self):
        for rc in (130, 1, 2):
            path = self.fake_fzf(f'import sys\nsys.exit({rc})\n')
            with patch('pkgs_lib.ui.which', return_value=path):
                if rc == 2:
                    with self.assertRaises(Error): ui.pick([Package('git')], Backend('apt'), self.cfg)
                else:
                    self.assertEqual(ui.pick([Package('git')], Backend('apt'), self.cfg), [])
    def test_toggle_files_preserve_identifiers(self):
        (self.home/'all').write_text('0\tinstalled\n1\tavailable\n')
        (self.home/'hide').write_text('1\tavailable\n')
        with patch.dict(os.environ, {'PKGS_SESSION': str(self.home)}):
            out = io.StringIO()
            with contextlib.redirect_stdout(out): ui.session('toggle')
            self.assertEqual(out.getvalue(), '1\tavailable\n')
            with contextlib.redirect_stdout(io.StringIO()): ui.session('toggle')
        self.assertFalse((self.home/'hidden').exists())

class Completions(Isolated):
    def test_install_is_idempotent_and_preserves_config(self):
        for shell in ('bash', 'zsh', 'fish'):
            dest, rc = completion.locations(shell)
            rc.parent.mkdir(parents=True, exist_ok=True)
            rc.write_text('# user settings\n')
            completion.manage(shell, 'install', dest.parent)
            first = rc.read_text()
            completion.manage(shell, 'install', dest.parent)
            self.assertEqual(first, rc.read_text())
            self.assertEqual(first.count('# >>> pkgs completion >>>'), 1 if shell == 'fish' else 0)
            if shell != 'fish': self.assertEqual(first, '# user settings\n')
            self.assertEqual(completion.manage(shell, 'status')['status'], 'current')
            completion.manage(shell, 'uninstall')
            self.assertIn('# user settings', rc.read_text())
            self.assertFalse(dest.exists())
    def test_foreign_completion_not_overwritten(self):
        dest, _ = completion.locations('bash')
        dest.parent.mkdir(parents=True)
        dest.write_text('# custom completion')
        with self.assertRaises(Error): completion.manage('bash', 'install', dest.parent)
        self.assertEqual(dest.read_text(), '# custom completion')
    def test_startup_symlink_preserved(self):
        _, rc = completion.locations('bash')
        target = self.home/'actual-bashrc'
        target.write_text('# settings\n')
        rc.symlink_to(target)
        completion.manage('bash', 'install', self.home/'completions')
        self.assertTrue(rc.is_symlink())
        self.assertIn('# settings', target.read_text())
    def test_context_respects_manager_and_scope(self):
        context = completion.context(['--manager','npm','install','--global','one',''], self.cfg)
        self.assertEqual(context[2:6], ('npm', 'install', True, ['one']))
    def test_completion_filters_installed(self):
        with patch('pkgs_lib.completion.default_manager', return_value='apt'), patch('pkgs_lib.completion.available', return_value=True), patch('pkgs_lib.completion.inventory', return_value=[Package('git')]) as inv:
            result = completion.complete(['uninstall', 'g'], self.cfg)
        self.assertEqual(result[0][0], 'git')
        self.assertTrue(inv.call_args.kwargs['installed_only'])
        self.assertTrue(inv.call_args.kwargs['offline'])
    def test_bash_zsh_syntax(self):
        for shell in ('bash', 'zsh'):
            if not __import__('shutil').which(shell): continue
            subprocess.run([shell, '-n', str(ROOT/'completions'/('pkgs.'+shell))], check=True)
    def test_bash_native_candidates(self):
        env = {**os.environ, 'PATH': str(ROOT)+':'+os.environ['PATH'], 'PKGS_FUZZY_TAB': '0'}
        script = 'source "$1"; COMP_WORDS=(pkgs in); COMP_CWORD=1; _pkgs_complete; printf "%s\\n" "${COMPREPLY[@]}"'
        p = subprocess.run(['bash', '-c', script, 'test', str(ROOT/'completions/pkgs.bash')], env=env, text=True, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.splitlines(), ['install', 'info'])

    def test_zsh_native_candidates(self):
        if not __import__('shutil').which('zsh'): self.skipTest('zsh unavailable')
        env = {**os.environ, 'PATH': str(ROOT)+':'+os.environ['PATH'], 'PKGS_FUZZY_TAB': '0'}
        script = "function compadd() { print -l -- \"$@\"; }; function test_completion() { source \"$1\"; }; words=(pkgs in); CURRENT=2; test_completion \"$1\""
        p = subprocess.run(['zsh', '-f', '-c', script, 'test', str(ROOT/'completions/pkgs.zsh')], env=env, text=True, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.splitlines()[-2:], ['install', 'info'])

if __name__ == '__main__': unittest.main()
