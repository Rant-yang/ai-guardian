"""Local presentation preferences only; never a security policy or data eraser."""
import json,os,threading,uuid
from pathlib import Path

class Presentation:
    def __init__(self,path=None):
        self.path=Path(path) if path else None
        self.lock=threading.RLock();self.enabled=False
        if self.path and self.path.exists():
            try:
                if self.path.is_symlink() or self.path.stat().st_size>1024:raise ValueError('Invalid preference file')
                data=json.loads(self.path.read_text(encoding='utf-8'))
                if set(data)!={'privacy_mode'} or type(data['privacy_mode']) is not bool:raise ValueError('Invalid preference')
                self.enabled=data['privacy_mode']
            except (OSError,ValueError,TypeError):self.enabled=True
    def snapshot(self):
        with self.lock:return {'privacy_mode':self.enabled}
    def set(self,enabled):
        if type(enabled) is not bool:raise ValueError('Invalid privacy mode')
        with self.lock:
            if self.path:
                if self.path.is_symlink():raise ValueError('Linked preference')
                self.path.parent.mkdir(parents=True,exist_ok=True)
                temp=self.path.with_name(self.path.name+'.'+uuid.uuid4().hex+'.tmp')
                try:
                    with temp.open('x',encoding='utf-8') as stream:json.dump({'privacy_mode':enabled},stream)
                    if self.path.is_symlink():raise ValueError('Linked preference')
                    os.replace(temp,self.path)
                finally:
                    if temp.exists():temp.unlink()
            self.enabled=enabled
            return self.snapshot()
