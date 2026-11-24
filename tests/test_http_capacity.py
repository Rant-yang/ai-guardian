import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from unittest.mock import patch
from pathlib import Path

from guardian.engine import Engine
from guardian.server import Server


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.engine=Engine(':memory:')
        self.server=Server(('127.0.0.1',0),self.engine,'fixture-token',max_connections=2,socket_timeout=.4)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.sockets=[]

    def tearDown(self):
        for connection in self.sockets:connection.close()
        self.wait_active(0)
        self.server.shutdown();self.server.server_close();self.thread.join();self.engine.close()

    def wait_active(self,count):
        deadline=time.monotonic()+3
        while self.server.capacity_snapshot()['active_connections']!=count and time.monotonic()<deadline:
            time.sleep(.005)
        self.assertEqual(self.server.capacity_snapshot()['active_connections'],count)

    def connect(self):
        connection=socket.create_connection(self.server.server_address,timeout=2)
        self.sockets.append(connection)
        return connection

    def health(self):
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request=urllib.request.Request(self.server.origin+'/api/health',headers={'Authorization':'Bearer fixture-token'})
        with opener.open(request,timeout=2) as response:return json.load(response)

    def test_idle_connections_are_bounded_overload_has_no_decision_and_recovers(self):
        self.connect();self.connect();self.wait_active(2)
        excess=self.connect()
        response=excess.recv(4096)
        self.assertTrue(response.startswith(b'HTTP/1.1 503'))
        self.assertIn(b'Retry-After: 1',response)
        self.assertIn(b'http_capacity',response)
        self.assertEqual(self.server.capacity_snapshot()['rejected_connections'],1)
        self.assertEqual(self.engine.events(),[])
        self.wait_active(0)
        health=self.health()
        self.assertEqual(health['status'],'ready')
        self.assertEqual(health['checks']['http']['max_connections'],2)
        self.assertEqual(health['checks']['http']['rejected_connections'],1)

    def test_partial_headers_timeout_without_blocking_later_health(self):
        connection=self.connect();connection.sendall(b'GET /api/health HTTP/1.1\r\nHost: ')
        self.wait_active(1);self.wait_active(0)
        self.assertEqual(self.health()['status'],'ready')
        self.assertEqual(self.engine.events(),[])

    def test_authenticated_partial_body_times_out_and_releases_worker(self):
        connection=self.connect()
        connection.sendall((f'POST /api/check HTTP/1.1\r\nHost: 127.0.0.1:{self.server.server_port}\r\n'
            'Authorization: Bearer fixture-token\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{').encode())
        self.wait_active(1);self.wait_active(0)
        self.assertEqual(self.engine.events(),[])
        self.assertEqual(self.health()['status'],'ready')

    def test_real_hook_protection_blocks_and_observation_warns_under_capacity(self):
        self.server.socket_timeout=5
        self.connect();self.connect();self.wait_active(2)
        action={'hook_event_name':'PreToolUse','session_id':'fixture','tool_use_id':'one',
            'tool_name':'Read','tool_input':{'file_path':'fixture.txt'}}
        with tempfile.TemporaryDirectory() as directory:
            token=Path(directory)/'token';token.write_text('fixture-token')
            for mode in ('protect','observe'):
                result=subprocess.run([sys.executable,'-m','guardian.hook','--token-file',str(token),
                    '--port',str(self.server.server_port),'--mode',mode],input=json.dumps(action),
                    capture_output=True,text=True,timeout=4)
                self.assertEqual(result.returncode,0,result.stderr)
                output=json.loads(result.stdout)
                if mode=='protect':self.assertEqual(output['hookSpecificOutput']['permissionDecision'],'deny')
                else:
                    self.assertIn('observation incomplete',output['systemMessage'])
                    self.assertNotIn('hookSpecificOutput',output)
        self.assertEqual(self.server.capacity_snapshot()['rejected_connections'],2)
        self.assertEqual(self.engine.events(),[])

    def test_thread_start_failure_releases_reserved_capacity(self):
        left,right=socket.socketpair()
        try:
            with patch('threading.Thread.start',side_effect=RuntimeError('fixture start failure')):
                with self.assertRaises(RuntimeError):self.server.process_request(left,('127.0.0.1',0))
            self.assertEqual(self.server.capacity_snapshot()['active_connections'],0)
        finally:left.close();right.close()
        self.assertEqual(self.health()['status'],'ready')

    def test_trickling_headers_and_body_cannot_extend_absolute_read_deadline(self):
        self.server.socket_timeout=1
        self.server.request_read_timeout=.25
        errors=patch.object(self.server,'handle_error');handle_error=errors.start();self.addCleanup(errors.stop)
        for phase in ('headers','body'):
            with self.subTest(phase=phase):
                connection=self.connect()
                prefix=(f'POST /api/check HTTP/1.1\r\nHost: 127.0.0.1:{self.server.server_port}\r\n'
                    'Authorization: Bearer fixture-token\r\nContent-Type: application/json\r\n')
                prefix+=('X-Slow: ' if phase=='headers' else 'Content-Length: 1000\r\n\r\n{')
                connection.sendall(prefix.encode());self.wait_active(1)
                started=time.monotonic()
                while time.monotonic()-started<.55:
                    try:connection.sendall(b' ')
                    except OSError:break
                    time.sleep(.03)
                self.wait_active(0)
                self.assertLess(time.monotonic()-started,.9)
                self.assertEqual(self.engine.events(),[])
                self.assertEqual(self.health()['status'],'ready')
        handle_error.assert_not_called()

    def test_truncated_valid_json_is_not_evaluated(self):
        body=json.dumps({'payload':{'session_id':'s','tool_use_id':'one','tool_name':'Read',
            'tool_input':{'file_path':'fixture.txt'}}}).encode()
        connection=self.connect()
        connection.sendall((f'POST /api/check HTTP/1.1\r\nHost: 127.0.0.1:{self.server.server_port}\r\n'
            'Authorization: Bearer fixture-token\r\nContent-Type: application/json\r\n'
            f'Content-Length: {len(body)+1}\r\n\r\n').encode()+body)
        connection.shutdown(socket.SHUT_WR)
        self.assertIn(b'400',connection.recv(4096).split(b'\r\n')[0])
        self.wait_active(0);self.assertEqual(self.engine.events(),[])

    def test_ambiguous_framing_is_rejected_before_evaluation(self):
        for framing in ('Content-Length: 2\r\nContent-Length: 2','Content-Length: 2\r\nTransfer-Encoding: chunked'):
            connection=self.connect()
            connection.sendall((f'POST /api/check HTTP/1.1\r\nHost: 127.0.0.1:{self.server.server_port}\r\n'
                'Authorization: Bearer fixture-token\r\nContent-Type: application/json\r\n'+framing+'\r\n\r\n{}').encode())
            self.assertIn(b'400',connection.recv(4096).split(b'\r\n')[0])
            self.wait_active(0)
        self.assertEqual(self.engine.events(),[])

    def test_completed_input_deadline_does_not_interrupt_handler_work(self):
        self.server.socket_timeout=1
        self.server.request_read_timeout=.15
        original=self.engine.storage_status
        def slow_status():
            time.sleep(.3)
            return original()
        with patch.object(self.engine,'storage_status',side_effect=slow_status):
            self.assertEqual(self.health()['status'],'ready')

    def test_drain_rejects_new_work_and_close_waits_for_accepted_handler(self):
        entered=threading.Event();release=threading.Event();closed=threading.Event();results=[]
        original=self.engine.storage_status
        def held_status():
            entered.set()
            if not release.wait(3):raise RuntimeError('fixture wait exceeded')
            return original()
        def close():
            self.server.server_close();closed.set()
        with patch.object(self.engine,'storage_status',side_effect=held_status):
            client=threading.Thread(target=lambda:results.append(self.health()))
            client.start()
            self.assertTrue(entered.wait(1))
            self.server.begin_drain()
            excess=self.connect();response=excess.recv(4096)
            self.assertIn(b'http_draining',response)
            self.server.shutdown()
            closer=threading.Thread(target=close);closer.start()
            try:
                self.assertFalse(closed.wait(.1))
                self.assertFalse(self.server.reviewer.closed)
            finally:
                release.set();client.join(3);closer.join(3)
            self.assertTrue(closed.is_set())
            self.assertEqual(results[0]['status'],'stopping')
            self.assertTrue(self.server.reviewer.closed)
            self.assertTrue(self.server.wait_drained(0))
