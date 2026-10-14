"""0.1.1 regressions: disposable configuration, mocked transactions, local PTYs."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from test_pkgs import Isolated, ROOT
from pkgs_lib import cli, completion, ui, fzf
from pkgs_lib.common import Package, Error, Cache, budget, run, query, which
from pkgs_lib.backends import Backend
from pkgs_lib.catalog import external, EvidenceCache, inventory


class FileOnlyCompletion(Isolated):
    def install(self, shell='zsh', directory=None):
        return completion.manage(shell, 'install', directory or self.home/'custom completions')

    def test_no_startup_file_created(self):
        for shell in ('zsh', 'bash'):
            result = self.install(shell)
            self.assertTrue(Path(result['file']).is_file())
            self.assertFalse(completion.locations(shell)[1].exists())
            self.assertIn('unverified', result['activation'])

    def test_exact_migration_preserves_symlink_permissions_and_bytes(self):
        for shell in ('zsh', 'bash'):
            legacy, rc = completion.locations(shell)
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_text(completion.generated(shell).replace('0.1.1', '0.1.0'))
            before, after = '# before\r\n\n\n', '\n\n# after\r\n'
            block = completion.START + '\n' + completion.startup(shell, legacy) + '\n' + completion.END + '\n'
            original = before + block + after
            rc.parent.mkdir(parents=True, exist_ok=True)
            target = self.home/(shell+'rc-target')
            target.write_bytes(original.encode())
            target.chmod(0o640)
            rc.symlink_to(target)
            result = self.install(shell)
            self.assertTrue(rc.is_symlink())
            self.assertEqual(target.read_bytes(), (before+after).encode())
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)
            self.assertTrue(any(Path(p).read_bytes() == original.encode() for p in result['backups']))
            self.assertFalse(legacy.exists())
            first = completion.state_path().stat().st_mtime_ns
            repeated = self.install(shell)
            self.assertEqual(repeated['backups'], [])
            self.assertEqual(completion.state_path().stat().st_mtime_ns, first)

    def test_malformed_and_edited_blocks_do_not_mutate(self):
        for text in (completion.START+'\n', completion.END+'\n'+completion.START+'\n',
                     completion.START+'\necho custom\n'+completion.END+'\n',
                     (completion.START+'\nx\n'+completion.END+'\n')*2):
            _, rc = completion.locations('zsh')
            rc.parent.mkdir(parents=True, exist_ok=True)
            rc.write_text(text)
            with self.assertRaises(Error): self.install()
            self.assertEqual(rc.read_text(), text)
            self.assertFalse((self.home/'custom completions').exists())
            self.assertFalse(completion.state_path().exists())

    def test_unrelated_legacy_completion_retained(self):
        legacy, _ = completion.locations('zsh')
        legacy.parent.mkdir(parents=True)
        legacy.write_text('# user completion\n')
        result = self.install()
        self.assertEqual(legacy.read_text(), '# user completion\n')
        self.assertTrue(result['notices'])

    def test_managed_header_does_not_authorize_overwrite(self):
        dest = self.home/'custom completions/_pkgs'
        dest.parent.mkdir()
        dest.write_text('# pkgs managed completion 0.1.0\n# edited\n')
        with self.assertRaises(Error): self.install()
        self.assertIn('# edited', dest.read_text())

    def test_recorded_destination_survives_data_and_zdotdir_changes(self):
        result = self.install()
        with patch.dict(os.environ, {'XDG_DATA_HOME': str(self.home/'different'), 'ZDOTDIR': str(self.home/'other rc')}):
            self.assertEqual(completion.manage('zsh', 'status')['file'], result['file'])
            completion.manage('zsh', 'update')
            completion.manage('zsh', 'uninstall')
        self.assertFalse(Path(result['file']).exists())

    def test_zsh_requires_context_without_override(self):
        with self.assertRaisesRegex(Error, 'FPATH'):
            completion.manage('zsh', 'install')
        self.assertFalse(completion.state_path().exists())
        directory = self.home/'active completions'
        directory.mkdir()
        with patch.dict(os.environ, {'FPATH': str(directory)}):
            result = completion.manage('zsh', 'install')
            self.assertEqual(result['file'], str(directory/'_pkgs'))
            self.assertTrue(completion.manage('zsh', 'status')['in_supplied_fpath'])

    def test_earlier_foreign_zsh_completion_conflicts(self):
        first = self.home/'first';first.mkdir()
        (first/'_pkgs').write_text('# user-owned')
        with patch.dict(os.environ, {'FPATH': str(first)+':'+str(self.home/'next')}):
            with self.assertRaisesRegex(Error, 'precedes'): self.install(directory=self.home/'next')

    def test_missing_bash_loader_and_custom_user_autoload(self):
        with patch('pkgs_lib.completion.bash_loader', return_value=''):
            with self.assertRaisesRegex(Error, 'autoload'): completion.manage('bash', 'install')
            explicit = self.install('bash')
            self.assertIn('not found', explicit['loader'])
            completion.manage('bash', 'uninstall')
        with patch('pkgs_lib.completion.bash_loader', return_value='/prefix/share/bash-completion/bash_completion'), patch.dict(os.environ, {'BASH_COMPLETION_USER_DIR': str(self.home/'bash custom')}):
            result = completion.manage('bash', 'install')
            self.assertEqual(result['file'], str(self.home/'bash custom/completions/pkgs'))

    def test_unwritable_destination_rejected(self):
        with patch('pkgs_lib.completion.writable', return_value=False):
            with self.assertRaisesRegex(Error, 'writable'): self.install()
        self.assertFalse(completion.state_path().exists())

    def test_completion_symlink_left_untouched(self):
        dest = self.home/'custom completions/_pkgs';dest.parent.mkdir()
        target = self.home/'target';target.write_text(completion.generated('zsh'))
        dest.symlink_to(target)
        with self.assertRaisesRegex(Error, 'symlink'): self.install()
        self.assertTrue(dest.is_symlink())
        self.assertEqual(target.read_text(), completion.generated('zsh'))

    def test_installer_preflight_is_nonmutating_and_overrides_work(self):
        env = dict(os.environ)
        prefix = self.home/'install prefix'
        result = subprocess.run([sys.executable, str(ROOT/'install.py'), '--prefix', str(prefix)], env=env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(prefix.exists())
        args = [sys.executable, str(ROOT/'install.py'), '--prefix', str(prefix)]
        for shell in ('bash','zsh','fish'):
            args += ['--completion-dir', shell+'='+str(self.home/(shell+' completion'))]
        for _ in range(2):
            result = subprocess.run(args, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.home/'.bashrc').exists())
        self.assertFalse(completion.locations('zsh')[1].exists())
        result = subprocess.run([sys.executable,str(ROOT/'install.py'),'--prefix',str(prefix),'--uninstall'],env=env,text=True,capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for shell in ('bash','zsh','fish'):
            name = completion.locations(shell)[0].name
            self.assertFalse((self.home/(shell+' completion')/name).exists())


class Responsiveness(Isolated):
    def test_picker_launch_has_no_ownership_calls(self):
        self.cfg['external_detection'] = True
        def picker(args, **kwargs):
            self.assertIn('--no-expect', args)
            self.assertNotIn('--expect=', args)
            data = kwargs['stdin'].read()
            self.assertIn('[i]', data)
            self.assertEqual(len(data.splitlines()), 5000)
            self.session_path = Path(kwargs['env']['PKGS_SESSION'])
            return subprocess.CompletedProcess(args, 130, '')
        with patch('pkgs_lib.ui.invocation', return_value=(['fake-fzf'], dict(os.environ))), patch('pkgs_lib.ui.which', return_value='fake-fzf'), patch.object(Backend, 'owner', side_effect=AssertionError('startup ownership')), patch('pkgs_lib.ui.subprocess.run', side_effect=picker):
            rows = [Package('package'+str(i), installed=i==1) for i in range(5000)]
            self.assertEqual(ui.pick(rows, Backend('apt'), self.cfg), [])
        self.assertFalse(self.session_path.exists())

    def test_owner_failure_is_unknown_not_external(self):
        b = Backend('apt')
        for result in (subprocess.CompletedProcess([],1,'','database broken'), subprocess.CompletedProcess([],2,'','permission denied')):
            with patch('pkgs_lib.backends.query', return_value=result):
                self.assertIsNone(b.owner('/test'))
        with patch('pkgs_lib.backends.query', return_value=subprocess.CompletedProcess([],1,'','dpkg-query: no path found matching pattern /test')):
            self.assertEqual(b.owner('/test'), '')

    def test_source_fzf_fallback_and_evidence_cache_invalidation(self):
        exe=self.home/'.fzf/bin/fzf';exe.parent.mkdir(parents=True);exe.write_text('source build');exe.chmod(0o755)
        b=Backend('apt');self.cfg['external_detection']=True
        with patch.dict(os.environ, {'PATH': str(self.home/'empty')}), patch.object(b,'database_fingerprint',return_value=['database-v1']), patch.object(b,'owner',return_value='') as owner:
            cache=EvidenceCache(b,self.cfg)
            p=external(Package('fzf'),b,self.cfg,cache=cache)
            self.assertIn('fallback',p.external[0]['position'])
            external(Package('fzf'),b,self.cfg,cache=EvidenceCache(b,self.cfg))
            self.assertEqual(owner.call_count,1)
            exe.write_text('new source build')
            external(Package('fzf'),b,self.cfg,cache=EvidenceCache(b,self.cfg))
            self.assertEqual(owner.call_count,2)
        with patch.dict(os.environ, {'PATH': str(self.home/'empty')}), patch.object(b,'database_fingerprint',return_value=['database-v2']):
            self.assertIsNone(EvidenceCache(b,self.cfg).get('fzf'))

    def test_unknown_symlink_owner_does_not_become_external(self):
        folder=self.home/'bin';folder.mkdir();target=folder/'real';target.write_text('');target.chmod(0o755)
        (folder/'fzf').symlink_to(target)
        self.cfg['external_detection']=True
        with patch.dict(os.environ, {'PATH': str(folder)}), patch.object(Backend,'owner',return_value=None) as owner:
            self.assertFalse(external(Package('fzf'),Backend('apt'),self.cfg).external)
            self.assertEqual(owner.call_count,1)

    def test_failed_catalog_is_not_cached_or_empty_success(self):
        b=Backend('apt')
        with patch.object(b,'installed',return_value=[]), patch.object(b,'inventory',side_effect=Error('local catalog failed')):
            with self.assertRaisesRegex(Error,'catalog failed'): inventory(b,self.cfg)
        self.assertIsNone(Cache(b.cache_key).load())

    def test_cache_write_failure_preserves_results(self):
        b=Backend('apt')
        with patch.object(b,'installed',return_value=[]), patch.object(b,'inventory',return_value=[Package('one')]), patch('pkgs_lib.common.atomic',side_effect=OSError('read-only')), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(inventory(b,self.cfg)[0].name,'one')
        self.assertIn('not saved',err.getvalue())

    def test_budget_kills_slow_query_promptly(self):
        start=time.monotonic()
        with budget(.1), self.assertRaises(Error):
            run([sys.executable,'-c','import time;time.sleep(30)'])
        self.assertLess(time.monotonic()-start,2)

    def test_native_completion_is_local_and_has_small_deadline(self):
        from pkgs_lib.common import remaining
        def inv(*args,**kwargs):
            self.assertTrue(kwargs['offline'])
            self.assertLessEqual(remaining(),1.5)
            raise Error('backend timeout')
        with patch('pkgs_lib.completion.default_manager',return_value='apt'), patch('pkgs_lib.completion.available',return_value=True), patch('pkgs_lib.completion.inventory',side_effect=inv):
            rc,out,err=self.invoke('__complete','--','uninstall','')
        self.assertEqual(rc,1)
        self.assertEqual(out,'')
        self.assertEqual(err,'')

    def test_preview_streams_basic_data_before_slow_enrichment(self):
        data={'backend':'apt','global':False,'cfg':self.cfg,'packages':[{'name':'fzf'}]}
        (self.home/'state.json').write_text(json.dumps(data))
        out=io.StringIO()
        def slow(p,*args):
            self.assertIn('Loading metadata',out.getvalue())
            return p,'Metadata unavailable: timeout'
        with patch.dict(os.environ,{'PKGS_SESSION':str(self.home)}), contextlib.redirect_stdout(out), patch('pkgs_lib.ui.enrich',side_effect=slow):
            ui.session('preview','0')
        self.assertIn('timeout',out.getvalue())

    def test_fzf_defaults_and_shell_are_preserved_or_bounded(self):
        with patch('pkgs_lib.fzf.details',return_value={'supported':True,'with_shell':True}), patch('pkgs_lib.fzf.which',side_effect=lambda x:'/bin/'+x), patch.dict(os.environ,{'FZF_DEFAULT_OPTS':'--color=fg:7 --expect=enter','BASH_ENV':'/slow-startup'}):
            args,env=fzf.invocation()
            self.assertIn('--color=fg:7',env['FZF_DEFAULT_OPTS'])
            self.assertNotIn('BASH_ENV',env)
            self.assertIn('--noprofile',args[-1])
        with patch('pkgs_lib.fzf.details',return_value={'supported':True}), patch('pkgs_lib.fzf.which',return_value='/fake'), patch.dict(os.environ,{'FZF_DEFAULT_OPTS':'--filter=fzf'}):
            with self.assertRaisesRegex(Error,'Incompatible'): fzf.invocation()

    def test_simple_fuzzy_completion_uses_same_protocol(self):
        with patch('pkgs_lib.completion.invocation',return_value=(['fake'],{})), patch('pkgs_lib.completion.which',return_value='fake'), patch('pkgs_lib.completion.subprocess.run',return_value=subprocess.CompletedProcess([],130,'')) as proc:
            self.assertEqual(completion.complete(['in'],self.cfg,True),[])
        self.assertIn('--no-expect',proc.call_args.args[0])
        self.assertNotIn('--expect=',proc.call_args.args[0])

class AdditionalRegressions(Isolated):
    def test_move_completion_then_uninstall(self):
        first=self.home/'one';second=self.home/'two'
        completion.manage('zsh','install',first)
        completion.manage('zsh','update',second)
        self.assertFalse((first/'_pkgs').exists())
        self.assertTrue((second/'_pkgs').exists())
        self.assertNotIn('retired',completion.read_state()['shells']['zsh'])
        completion.manage('zsh','uninstall')
        self.assertFalse((second/'_pkgs').exists())

    def test_directory_symlink_does_not_retire_same_file(self):
        first=self.home/'one';first.mkdir()
        alias=self.home/'alias';alias.symlink_to(first,target_is_directory=True)
        completion.manage('zsh','install',first)
        completion.manage('zsh','update',alias)
        self.assertTrue((first/'_pkgs').exists())
        self.assertTrue(alias.is_symlink())
        self.assertEqual(completion.manage('zsh','status')['status'],'current')

    def test_interrupted_retirement_is_recorded_for_retry(self):
        first=self.home/'one';second=self.home/'two'
        completion.manage('zsh','install',first)
        original=Path.unlink
        def fail_old(path,*args,**kwargs):
            if path==first/'_pkgs':raise OSError('fixture unlink failure')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',fail_old),self.assertRaises(OSError):
            completion.manage('zsh','update',second)
        self.assertIn('retired',completion.read_state()['shells']['zsh'])
        completion.manage('zsh','update')
        self.assertFalse((first/'_pkgs').exists())
        self.assertNotIn('retired',completion.read_state()['shells']['zsh'])

    def test_completion_dry_run_does_not_create_files(self):
        rc,out,err=self.invoke('completion','zsh','install','--directory',str(self.home/'new'),'--dry-run')
        self.assertEqual(rc,0,err)
        self.assertIn('dry-run',out)
        self.assertFalse((self.home/'new').exists())
        self.assertFalse(completion.state_path().exists())

    def test_supported_owner_unowned_contracts(self):
        cases=[('apt',1,'','dpkg-query: no path found matching pattern /file'),
               ('pacman',1,'','error: No package owns /file'),
               ('paru',1,'','error: No package owns /file'),
               ('yay',1,'','error: No package owns /file'),
               ('dnf',1,'file /file is not owned by any package',''),
               ('xbps',0,'','')]
        for name,rc,out,err in cases:
            with self.subTest(name=name),patch('pkgs_lib.backends.query',return_value=subprocess.CompletedProcess([],rc,out,err)):
                self.assertEqual(Backend(name).owner('/file'),'')
            with patch('pkgs_lib.backends.query',return_value=subprocess.CompletedProcess([],1,'','database error')):
                self.assertIsNone(Backend(name).owner('/file'))

    def test_older_fzf_shell_fallback(self):
        with patch('pkgs_lib.fzf.details',return_value={'supported':True,'with_shell':False}),patch('pkgs_lib.fzf.which',side_effect=lambda x:'/bin/'+x):
            args,env=fzf.invocation()
        self.assertFalse(any(x.startswith('--with-shell') for x in args))
        self.assertEqual(env['SHELL'],'/bin/bash')

    def test_corrupt_cache_is_rebuilt(self):
        b=Backend('apt');cache=Cache(b.cache_key);cache.path.parent.mkdir(parents=True);cache.path.write_text('{broken')
        with patch.object(b,'installed',return_value=[]),patch.object(b,'inventory',return_value=[Package('fresh')]):
            self.assertEqual(inventory(b,self.cfg)[0].name,'fresh')
        self.assertEqual(cache.load()[0].name,'fresh')

    def test_explicit_info_failure_reports_nonzero(self):
        b=Backend('apt')
        with patch('pkgs_lib.cli.choose_manager',return_value=b),patch.object(b,'installed',return_value=[]),patch.object(b,'info',side_effect=Error('metadata failed')):
            rc,out,err=self.invoke('info','fzf')
        self.assertEqual(rc,1)
        self.assertIn('metadata failed',out)

    def test_read_query_timeout_kills_descendants(self):
        pidfile=self.home/'descendant.pid'
        program=('import subprocess,time;from pathlib import Path;'
                 f'p=subprocess.Popen([{sys.executable!r},"-c","import time;time.sleep(30)"]);'
                 f'Path({str(pidfile)!r}).write_text(str(p.pid));time.sleep(30)')
        with budget(.4),self.assertRaises(Error):run([sys.executable,'-c',program])
        self.assertTrue(pidfile.exists())
        stat=Path('/proc')/pidfile.read_text()/'stat'
        limit=time.monotonic()+1
        while stat.exists() and stat.read_text().split()[2]!='Z' and time.monotonic()<limit:time.sleep(.02)
        self.assertTrue(not stat.exists() or stat.read_text().split()[2]=='Z')

    def test_real_zsh_autoload_registration(self):
        if not shutil.which('zsh'):self.skipTest('zsh unavailable')
        dest=self.home/'zsh completions'
        completion.manage('zsh','install',dest)
        code='fpath=("$1" $fpath); autoload -Uz compinit; compinit -D; print -r -- $_comps[pkgs]'
        env=dict(os.environ);env.pop('FPATH',None)
        result=subprocess.run(['zsh','-f','-c',code,'test',str(dest)],env=env,text=True,capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'_pkgs')

    def test_real_bash_autoload_registration(self):
        prefix = Path(os.environ.get('PREFIX') or '/usr')
        candidates = [prefix/'share/bash-completion/bash_completion',
                      Path('/data/data/com.termux/files/usr/share/bash-completion/bash_completion'),
                      Path('/usr/share/bash-completion/bash_completion')]
        loader = next((p for p in candidates if p.is_file()), None)
        if not loader: self.skipTest('bash-completion unavailable')
        dest=self.home/'bash data/completions'
        completion.manage('bash','install',dest)
        env={**os.environ,'BASH_COMPLETION_USER_DIR':str(dest.parent)}
        code='source "$1"; if declare -F _completion_loader >/dev/null; then _completion_loader pkgs; else _comp_load pkgs; fi; complete -p pkgs'
        result=subprocess.run(['bash','--noprofile','--norc','-c',code,'test',str(loader)],env=env,text=True,capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('_pkgs_complete',result.stdout)

    def test_corrupt_evidence_cache_is_ignored(self):
        b=Backend('apt')
        with patch.object(b,'database_fingerprint',return_value=['test']):
            cache=EvidenceCache(b,self.cfg)
            cache.path.parent.mkdir(parents=True,exist_ok=True)
            cache.path.write_text(json.dumps({'time':time.time(),'signature':cache.signature,'records':[]}))
            self.assertIsNone(EvidenceCache(b,self.cfg).get('fzf'))
            cache.records={'fzf':{'paths':[],'evidence':['invalid']}}
            self.assertIsNone(cache.get('fzf'))
