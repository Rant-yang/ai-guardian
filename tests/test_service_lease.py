import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from guardian.service_lease import ServiceLease

ROOT=Path(__file__).resolve().parents[1]


class ServiceLeaseTests(unittest.TestCase):
    def test_live_backend_survives_duplicate_launch_on_another_port(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            command=[sys.executable,'-m','guardian.server','--port','0','--data-dir',directory]
            process=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            try:
                endpoint=root/'service-endpoint.json'
                for _ in range(150):
                    if endpoint.exists() or process.poll() is not None:break
                    time.sleep(.05)
                self.assertTrue(endpoint.exists())
                before=endpoint.read_bytes()
                token=(root/'admin-token').read_text().strip()
                port=json.loads(before)['port']
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                def health():
                    request=urllib.request.Request(f'http://127.0.0.1:{port}/api/health',headers={'Authorization':'Bearer '+token})
                    with opener.open(request,timeout=3) as response:return json.load(response)
                self.assertEqual(health()['service'],'agent-guardian')
                duplicate=subprocess.run(command,cwd=ROOT,capture_output=True,timeout=15)
                self.assertNotEqual(duplicate.returncode,0)
                self.assertIn(b'already in use',duplicate.stderr)
                self.assertEqual(endpoint.read_bytes(),before)
                self.assertIsNone(process.poll())
                self.assertEqual(health()['service'],'agent-guardian')
            finally:
                process.terminate();process.communicate(timeout=5)
            with ServiceLease(root):pass

    def test_exclusive_scope_and_release_after_exception(self):
        with tempfile.TemporaryDirectory() as first,tempfile.TemporaryDirectory() as second:
            with self.assertRaisesRegex(ValueError,'fixture'):
                with ServiceLease(first):
                    with self.assertRaises(RuntimeError):
                        with ServiceLease(first):pass
                    with ServiceLease(second):pass
                    raise ValueError('fixture')
            with ServiceLease(first):pass

    def test_process_exit_releases_lease_without_deleting_lock_file(self):
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'ready'
            code="from guardian.service_lease import ServiceLease; from pathlib import Path; import sys,time\nwith ServiceLease(sys.argv[1]):\n Path(sys.argv[2]).write_text('ready'); time.sleep(60)"
            process=subprocess.Popen([sys.executable,'-c',code,directory,str(marker)],cwd=ROOT,
                                     stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            try:
                for _ in range(100):
                    if marker.exists() or process.poll() is not None:break
                    time.sleep(.05)
                self.assertTrue(marker.exists())
                with self.assertRaises(RuntimeError):
                    with ServiceLease(directory):pass
            finally:
                process.terminate();process.communicate(timeout=5)
            self.assertTrue((Path(directory)/'service.lock').exists())
            with ServiceLease(directory):pass

    def test_second_server_refuses_before_touching_database_or_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            sentinels={'events.sqlite3':b'fixture database do not open',
                       'service-endpoint.json':json.dumps({'version':1,'host':'127.0.0.1','port':12345}).encode()}
            for name,value in sentinels.items():(root/name).write_bytes(value)
            with ServiceLease(root):
                result=subprocess.run([sys.executable,'-m','guardian.server','--port','0','--data-dir',directory],
                                      cwd=ROOT,capture_output=True,timeout=15)
            self.assertNotEqual(result.returncode,0)
            self.assertIn(b'already in use',result.stderr)
            for name,value in sentinels.items():self.assertEqual((root/name).read_bytes(),value)
            self.assertFalse((root/'access-token').exists())


if __name__=='__main__':unittest.main()
