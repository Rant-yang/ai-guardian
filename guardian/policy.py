"""Atomic, local mode settings, also readable by adapters during service outages."""
import json
import os
from pathlib import Path
import threading
from .adapter_contracts import mode_adapters

CLIENTS = mode_adapters()


class Policy:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.lock = threading.RLock()
        self.modes = {}
        if self.path and self.path.exists():
            self.modes = json.loads(self.path.read_text(encoding='utf-8'))
            if any(k not in CLIENTS or v not in ('observe','protect') for k,v in self.modes.items()):
                raise ValueError('Invalid persisted modes')
        elif self.path:
            for client in CLIENTS:self.set(client,'observe')

    def snapshot(self):
        with self.lock:
            return {client:self.modes.get(client,'observe') for client in CLIENTS}

    def resolve(self, client, fallback):
        with self.lock:
            return self.modes.get(client, fallback)

    def set(self, client, mode):
        if client not in CLIENTS or mode not in ('observe','protect'):
            raise ValueError('Unsupported mode or client')
        with self.lock:
            updated = {**self.modes,client:mode}
            if self.path:
                self.path.parent.mkdir(parents=True,exist_ok=True)
                temp=self.path.with_suffix('.tmp')
                temp.write_text(json.dumps(updated),encoding='utf-8')
                os.replace(temp,self.path)
            self.modes=updated
            return self.snapshot()
