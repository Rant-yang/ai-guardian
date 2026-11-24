"""Bound local HTTP workers before reading headers or starting a thread."""
import threading
import socket
import time
from http.server import ThreadingHTTPServer


class BoundedHTTPServer(ThreadingHTTPServer):
    request_queue_size=32

    def __init__(self,address,handler,*,max_connections=32,socket_timeout=5,request_read_timeout=10):
        if type(max_connections) is not int or not 1<=max_connections<=128:
            raise ValueError('Invalid HTTP connection capacity')
        if not 0<socket_timeout<=30:raise ValueError('Invalid HTTP idle timeout')
        if not 0<request_read_timeout<=60:raise ValueError('Invalid HTTP read deadline')
        self.max_connections=max_connections
        self.socket_timeout=socket_timeout
        self.request_read_timeout=request_read_timeout
        self._capacity=threading.BoundedSemaphore(max_connections)
        self._capacity_lock=threading.Lock()
        self._active_connections=0
        self._rejected_connections=0
        self._draining=False
        self._drained=threading.Event();self._drained.set()
        super().__init__(address,handler)

    def capacity_snapshot(self):
        with self._capacity_lock:
            return dict(max_connections=self.max_connections,active_connections=self._active_connections,
                rejected_connections=self._rejected_connections,socket_idle_timeout_seconds=self.socket_timeout,
                request_read_timeout_seconds=self.request_read_timeout,draining=self._draining)

    def begin_drain(self):
        with self._capacity_lock:self._draining=True

    def wait_drained(self,timeout=None):
        return self._drained.wait(timeout)

    def process_request(self,request,client_address):
        with self._capacity_lock:
            accepted=not self._draining and self._capacity.acquire(blocking=False)
            if accepted:
                self._active_connections+=1
                self._drained.clear()
            else:self._rejected_connections+=1
            draining=self._draining
        if not accepted:
            try:
                # Do not spawn another worker or wait for authentication to reject overload.
                body=(b'{"error":"service stopping; no decision","code":"http_draining"}' if draining else
                    b'{"error":"service busy; no decision","code":"http_capacity"}')
                request.settimeout(0.05)
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n'
                    b'Retry-After: 1\r\nCache-Control: no-store\r\nContent-Type: application/json\r\n'
                    b'Content-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body)
            except OSError:pass
            finally:self.shutdown_request(request)
            return
        try:
            request.settimeout(self.socket_timeout)
            super().process_request(request,client_address)
        except BaseException:
            self._release_capacity()
            raise

    def _release_capacity(self):
        with self._capacity_lock:
            self._active_connections-=1
            self._capacity.release()
            if self._active_connections==0:self._drained.set()

    def process_request_thread(self,request,client_address):
        try:super().process_request_thread(request,client_address)
        finally:self._release_capacity()


class ReadDeadline:
    """Absolute input deadline; cancellation cannot interrupt subsequent work."""
    def __init__(self,connection,seconds):
        self.connection=connection
        self.deadline=time.monotonic()+seconds
        self.lock=threading.Lock()
        self.done=False
        self.expired=False
        self.timer=threading.Timer(seconds,self._expire)
        self.timer.daemon=True
        self.timer.start()

    def _expire(self):
        with self.lock:
            if self.done:return
            self.expired=True
            # Unblock buffered reads even when small chunks arrive before each idle timeout.
            try:self.connection.shutdown(socket.SHUT_RD)
            except OSError:pass

    def complete(self):
        with self.lock:
            allowed=not self.expired and time.monotonic()<self.deadline
            self.done=True
            self.timer.cancel()
            return allowed

    def cancel(self):
        with self.lock:
            self.done=True
            self.timer.cancel()
