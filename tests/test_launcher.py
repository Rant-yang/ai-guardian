"""Windows bootstrap integration checks; isolated checkout, data and loopback port."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.request

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.name=='nt','Windows launcher integration')
class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='guardian-launch-')
        self.root=Path(self.temp.name)/'中文 space checkout';self.root.mkdir()
        shutil.copytree(ROOT/'guardian',self.root/'guardian',ignore=shutil.ignore_patterns('__pycache__'))
        (self.root/'scripts').mkdir()
        for name in ('start-background.ps1','stop-background.ps1','runtime.ps1'):
            shutil.copy2(ROOT/'scripts'/name,self.root/'scripts'/name)
        for source in (ROOT/'scripts').glob('*.py'):shutil.copy2(source,self.root/'scripts'/source.name)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]
        self.pid=self.root/'.local'/f'server-{self.port}.pid'
    def call(self,name='start-background.ps1'):
        with tempfile.TemporaryFile() as out,tempfile.TemporaryFile() as err:
            result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(self.root/'scripts'/name),'-Port',str(self.port)],stdout=out,stderr=err,timeout=35)
            out.seek(0);err.seek(0);result.stdout=out.read();result.stderr=err.read()
            return result
    def tearDown(self):
        if self.pid.exists() and self.pid.read_text().strip().isdigit():self.call('stop-background.ps1')
        self.temp.cleanup()
    def test_unicode_space_checkout_repeat_and_parallel_launch(self):
        command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(self.root/'scripts/start-background.ps1'),'-Port',str(self.port)]
        streams=[tempfile.TemporaryFile() for _ in range(2)]
        children=[subprocess.Popen(command,stdout=stream,stderr=stream) for stream in streams]
        results=[]
        try:
            for child,stream in zip(children,streams):
                code=child.wait(timeout=35);stream.seek(0);results.append((stream.read(),code))
        finally:
            for child in children:
                if child.poll() is None:child.kill();child.wait()
            for stream in streams:stream.close()
        for output,code in results:
            error_file=self.root/'.local'/f'server-{self.port}.error.log'
            self.assertEqual(code,0,(output,error_file.read_text() if error_file.exists() else 'no log'))
        pid=self.pid.read_text().strip()
        again=self.call();self.assertEqual(again.returncode,0,again.stderr)
        self.assertEqual(self.pid.read_text().strip(),pid)
        token=(self.root/'.local/access-token').read_text().strip()
        request=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/health',headers={'Authorization':'Bearer '+token})
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request,timeout=3) as response:health=json.load(response)
        self.assertEqual(health['service'],'agent-guardian');self.assertEqual(health['api_version'],1)
        self.assertRegex(health['backend_source_at_start'],r'^[0-9a-f]{64}$')
        source=self.root/'guardian/overview.py'
        with source.open('a',encoding='utf-8') as stream:stream.write('\n# changed source fixture\n')
        changed=self.call()
        self.assertEqual(changed.returncode,0,changed.stderr)
        self.assertIn(b'backend source changed since startup',changed.stdout)
        self.assertEqual(self.pid.read_text().strip(),pid)
        with opener.open(request,timeout=3) as response:unchanged=json.load(response)
        self.assertEqual(unchanged['backend_source_at_start'],health['backend_source_at_start'])

    def test_venv_launcher_records_actual_service_and_stops_gracefully(self):
        subprocess.run([sys.executable,'-m','venv','--without-pip',str(self.root/'.venv')],check=True,timeout=35)
        started=self.call();self.assertEqual(started.returncode,0,started.stderr)
        identity=json.loads((self.root/'.local'/f'server-{self.port}.identity.json').read_text(encoding='utf-8-sig'))
        token=(self.root/'.local/access-token').read_text().strip()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/health',headers={'Authorization':'Bearer '+token})
        with opener.open(request,timeout=3) as response:health=json.load(response)
        self.assertEqual(identity['pid'],health['process_id'])
        self.assertEqual(int(self.pid.read_text()),health['process_id'])
        stopped=self.call('stop-background.ps1');self.assertEqual(stopped.returncode,0,stopped.stderr)
        with socket.socket() as probe:
            probe.settimeout(2)
            self.assertNotEqual(probe.connect_ex(('127.0.0.1',self.port)),0)
    def test_occupied_port_preserves_existing_pid_and_other_service(self):
        self.pid.parent.mkdir();self.pid.write_text('unrelated-pid-marker')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',self.port));sock.listen()
            result=self.call();self.assertNotEqual(result.returncode,0)
            self.assertIn(b'occupied',result.stderr)
            self.assertEqual(self.pid.read_text(),'unrelated-pid-marker')
            self.assertFalse((self.root/'.local/admin-token').exists())
    def test_failed_child_does_not_replace_pid(self):
        self.pid.parent.mkdir();self.pid.write_text('previous-pid-marker')
        (self.root/'guardian/server.py').write_text('raise RuntimeError("fixture startup failure")')
        result=self.call();self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.pid.read_text(),'previous-pid-marker')
        self.assertIn('fixture startup failure',(self.root/'.local'/f'server-{self.port}.error.log').read_text())

    def test_stop_requires_matching_creation_time_and_checkout_identity(self):
        started=self.call();self.assertEqual(started.returncode,0,started.stderr)
        identity_path=self.root/'.local'/f'server-{self.port}.identity.json'
        original=identity_path.read_text(encoding='utf-8-sig')
        record=json.loads(original)
        try:
            for changes in ({'started_utc_ticks':'0'},{'project_root':str(self.root/'another-checkout')}):
                identity_path.write_text(json.dumps({**record,**changes}),encoding='utf-8')
                stopped=self.call('stop-background.ps1')
                self.assertNotEqual(stopped.returncode,0)
                self.assertIn(b'refusing to stop',stopped.stderr.lower())
                self.assertEqual(self.call().returncode,0)  # Existing authenticated service still alive.
                self.assertEqual(int(self.pid.read_text().strip()),record['pid'])
            identity_path.unlink()
            stopped=self.call('stop-background.ps1')
            self.assertNotEqual(stopped.returncode,0)
            self.assertIn(b'legacy process',stopped.stderr)
            self.assertEqual(self.call().returncode,0)
            self.assertEqual(int(self.pid.read_text().strip()),record['pid'])
        finally:identity_path.write_text(original,encoding='utf-8')
        stopped=self.call('stop-background.ps1');self.assertEqual(stopped.returncode,0,stopped.stderr)

    def test_launch_record_failure_stops_new_service_and_retry_recovers(self):
        self.pid.parent.mkdir()
        identity=self.pid.parent/f'server-{self.port}.identity.json'
        identity.mkdir()  # Deterministic write failure without changing host permissions.
        self.pid.write_text('previous-marker')
        failed=self.call()
        self.assertNotEqual(failed.returncode,0)
        self.assertIn(b'launch records could not be saved',failed.stderr)
        self.assertEqual(self.pid.read_text(),'previous-marker')
        with socket.socket() as probe:
            probe.settimeout(2)
            self.assertNotEqual(probe.connect_ex(('127.0.0.1',self.port)),0)
        identity.rmdir()
        retried=self.call();self.assertEqual(retried.returncode,0,retried.stderr)
        self.assertEqual(json.loads(identity.read_text(encoding='utf-8-sig'))['pid'],int(self.pid.read_text()))

    def test_repeated_setup_reuses_ready_environment_without_network(self):
        import importlib.metadata
        try:version=importlib.metadata.version('pywebview')
        except importlib.metadata.PackageNotFoundError:self.skipTest('Desktop dependency not installed on test host')
        if version!='6.2.1':self.skipTest('Pinned desktop dependency not installed on test host')
        for name in ('setup.ps1','requirements-desktop.txt'):shutil.copy2(ROOT/name,self.root/name)
        subprocess.run([sys.executable,'-m','venv','--system-site-packages',str(self.root/'.venv')],check=True,timeout=45,capture_output=True)
        environment={**os.environ,'PIP_NO_INDEX':'1'}
        for _ in range(2):
            result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(self.root/'setup.ps1'),'-NoOpen'],env=environment,capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(b'no network installation needed',result.stdout)
        self.assertFalse((self.root/'.local').exists())

    def test_partial_environment_is_repaired_and_retry_finishes_offline(self):
        import importlib.metadata
        try:version=importlib.metadata.version('pywebview')
        except importlib.metadata.PackageNotFoundError:self.skipTest('Desktop dependency not installed')
        if version!='6.2.1':self.skipTest('Pinned desktop dependency not installed')
        for name in ('setup.ps1','requirements-desktop.txt'):shutil.copy2(ROOT/name,self.root/name)
        managed=self.root/'.venv';(managed/'Scripts').mkdir(parents=True)
        marker=managed/'preserve.txt';marker.write_text('fixture marker',encoding='utf-8')
        environment={**os.environ,'PIP_NO_INDEX':'1'}
        command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(self.root/'setup.ps1'),'-NoOpen']
        failed=subprocess.run(command,env=environment,capture_output=True,timeout=90)
        self.assertNotEqual(failed.returncode,0)  # Missing desktop packages; network disabled.
        self.assertIn(b'Dependency installation failed',failed.stderr)
        python=managed/'Scripts/python.exe'
        self.assertTrue(python.is_file())
        self.assertEqual(subprocess.run([str(python),'-c','import sys; assert sys.version_info >= (3,11)'],capture_output=True).returncode,0)
        self.assertEqual(marker.read_text(encoding='utf-8'),'fixture marker')
        config=managed/'pyvenv.cfg'
        config.write_text(config.read_text(encoding='utf-8').replace('include-system-site-packages = false','include-system-site-packages = true'),encoding='utf-8')
        # Test-only access to existing host dependencies; not a production fallback.
        children=[subprocess.Popen(command,env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
        try:
            for child in children:
                stdout,stderr=child.communicate(timeout=60)
                self.assertEqual(child.returncode,0,stderr)
                self.assertIn(b'no network installation needed',stdout)
        finally:
            for child in children:
                if child.poll() is None:child.kill();child.wait()
        self.assertEqual(marker.read_text(encoding='utf-8'),'fixture marker')
        self.assertFalse((self.root/'.local').exists())

    def test_mismatched_transitive_dependency_cannot_report_ready_offline(self):
        for name in ('setup.ps1','requirements-desktop.txt'):shutil.copy2(ROOT/name,self.root/name)
        requirements=self.root/'requirements-desktop.txt'
        requirements.write_text(requirements.read_text(encoding='utf-8').replace('cffi==2.0.0','cffi==0.0.0'),encoding='utf-8')
        subprocess.run([sys.executable,'-m','venv','--system-site-packages',str(self.root/'.venv')],check=True,timeout=45,capture_output=True)
        result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(self.root/'setup.ps1'),'-NoOpen'],
            env={**os.environ,'PIP_NO_INDEX':'1'},capture_output=True,timeout=60)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Dependency installation failed',result.stderr)
        self.assertNotIn(b'no network installation needed',result.stdout)
        self.assertNotIn(b'Ready. No Agent configuration',result.stdout)

    def test_missing_pip_restored_without_hidden_network_success(self):
        for name in ('setup.ps1','requirements-desktop.txt'):shutil.copy2(ROOT/name,self.root/name)
        managed=self.root/'.venv'
        subprocess.run([sys.executable,'-m','venv','--without-pip',str(managed)],check=True,timeout=45,capture_output=True)
        environment={**os.environ,'PIP_NO_INDEX':'1'}
        result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(self.root/'setup.ps1'),'-NoOpen'],
                              env=environment,capture_output=True,timeout=90)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Dependency installation failed',result.stderr)
        check=subprocess.run([str(managed/'Scripts/python.exe'),'-m','pip','--version'],capture_output=True,timeout=10)
        self.assertEqual(check.returncode,0,check.stderr)
