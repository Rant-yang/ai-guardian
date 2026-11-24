"""One live backend per data directory, independent of port and launcher.

The OS owns the advisory lock and releases it when the process exits. Keep the
lock file in place: unlinking it would let another process lock a different inode.
"""
import os
from pathlib import Path


class ServiceLease:
    def __init__(self,data_dir):
        self.path=Path(data_dir)/'service.lock'
        self.stream=None

    def __enter__(self):
        stream=self.path.open('a+b')
        try:
            if os.fstat(stream.fileno()).st_size==0:
                stream.write(b'\0');stream.flush()
            stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise RuntimeError('Guardian data directory is already in use or cannot be locked; existing service was not changed.') from None
        self.stream=stream
        return self

    def __exit__(self,*_):
        stream=self.stream
        self.stream=None
        if stream is not None:
            try:
                stream.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
            finally:stream.close()
