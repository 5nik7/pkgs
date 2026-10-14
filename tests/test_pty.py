"""Actual fzf in a pseudo-terminal, with fake metadata and no transactions."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import patch

from test_pkgs import Isolated
from pkgs_lib import ui
from pkgs_lib.common import Package, which
from pkgs_lib.backends import Backend

REAL_FZF = which('fzf')


@unittest.skipUnless(REAL_FZF, 'real fzf unavailable')
class RealPicker(Isolated):
    def exercise(self, keys, slow=False, options_file=False, toggles=False):
        fakebin = self.home/'bin';fakebin.mkdir()
        meta = fakebin/'apt-cache'
        pidfile = self.home/'metadata.pid'
        meta.write_text('#!'+sys.executable+'\nimport os,time\n'
                        'from pathlib import Path\n'
                        f'Path({str(pidfile)!r}).write_text(str(os.getpid()))\n'
                        + ('time.sleep(30)\n' if slow else '')
                        + 'print("Package: alpha\\nDescription: fixture metadata\\nHomepage: https://example.org")\n')
        meta.chmod(0o755)
        hook=self.home/'bad-startup';hook.write_text('sleep 30\n')
        opts='--color=fg:7 --layout=reverse --expect=enter'
        optsfile=self.home/'fzf-options';optsfile.write_text(opts)
        started=time.monotonic();pid,fd=pty.fork()
        if pid==0:
            try:
                fcntl.ioctl(1,termios.TIOCSWINSZ,struct.pack('HHHH',40,140,0,0))
                os.environ['PATH']=str(fakebin)+':'+os.environ['PATH']
                os.environ['BASH_ENV']=str(hook)
                os.environ['FZF_DEFAULT_OPTS']=opts if not options_file else ''
                os.environ['FZF_DEFAULT_OPTS_FILE']=str(optsfile) if options_file else ''
                tempfile.tempdir=str(self.home)
                self.cfg['external_detection']=False
                original=ui.which
                with patch('pkgs_lib.ui.which',side_effect=lambda name:REAL_FZF if name=='fzf' else original(name)):
                    selected=ui.pick([Package('alpha',description='needle-marker'),Package('beta',installed=True)],Backend('apt'),self.cfg)
                print('PICK_RESULT='+json.dumps([p.name for p in selected]),flush=True)
                os._exit(0)
            except BaseException as e:
                print('PICK_ERROR='+repr(e),flush=True);os._exit(1)
        data=b'';sent=False;cancelled=None;status=None;ready=None;toggled=False;toggle_time=0
        try:
            while time.monotonic()-started<10:
                if select.select([fd],[],[],.05)[0]:
                    try: data+=os.read(fd,65536)
                    except OSError: break
                if ready is None and b'needle-marker' in data:ready=time.monotonic()-started
                if not sent and ready is not None and pidfile.exists() and (slow or b'fixture metadata' in data):
                    if toggles and not toggled:
                        os.write(fd,b'\x18\x1bi');toggled=True;toggle_time=time.monotonic()
                    elif not toggles or (list(self.home.glob('pkgs-*/hidden')) and time.monotonic()-toggle_time>.2):
                        os.write(fd,keys);sent=True;cancelled=time.monotonic()
                ended,st=os.waitpid(pid,os.WNOHANG)
                if ended:status=st;break
            if status is None:
                ended,st=os.waitpid(pid,os.WNOHANG)
                if ended:status=st
                else:
                    os.kill(pid,signal.SIGKILL);status=os.waitpid(pid,0)[1]
        finally:
            os.close(fd)
        self.assertEqual(os.waitstatus_to_exitcode(status),0,data[-1500:].decode(errors='replace'))
        self.assertIsNotNone(ready)
        self.assertTrue(sent, data[-1500:].decode(errors='replace'))
        self.assertLess(time.monotonic()-cancelled,2)
        self.assertFalse(list(self.home.glob('pkgs-*')))
        if pidfile.exists():
            child=int(pidfile.read_text())
            stat=Path('/proc')/str(child)/'stat'
            limit=time.monotonic()+1
            while stat.exists() and stat.read_text().split()[2]!='Z' and time.monotonic()<limit:
                time.sleep(.02)
            self.assertTrue(not stat.exists() or stat.read_text().split()[2]=='Z','metadata child survived picker exit')
        return data

    def test_selection_real_protocol_and_preview(self):
        data=self.exercise(b'\t\t\r')
        self.assertIn(b'PICK_RESULT=["alpha", "beta"]',data)

    def test_escape_with_options_file(self):
        self.assertIn(b'PICK_RESULT=[]',self.exercise(b'\x1b',options_file=True))

    def test_ctrl_c_during_slow_preview(self):
        self.assertIn(b'PICK_RESULT=[]',self.exercise(b'\x03',slow=True))

    def test_installed_and_preview_toggles(self):
        self.assertIn(b'PICK_RESULT=["alpha"]',self.exercise(b'\t\r',toggles=True))
