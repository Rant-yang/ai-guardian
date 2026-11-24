"""Bounded, ephemeral adapter presence; never infer presence from event history."""
import threading
import time
import uuid
import re
from .adapter_contracts import CONTRACTS, capabilities

OPENCODE_REVISION=CONTRACTS['opencode-plugin'].revision


class Connections:
    def __init__(self,installation_resolver=None):
        self.lock = threading.Lock()
        self.rows = {}
        self.installation_resolver=installation_resolver

    def heartbeat(self, data):
        identity = str(uuid.UUID(data['instance_id']))
        adapter=data.get('adapter')
        contract=CONTRACTS.get(adapter) if isinstance(adapter,str) else None
        if contract is None or not contract.heartbeat or data.get('mode') not in ('observe', 'protect'):
            raise ValueError('invalid adapter')
        project = data.get('project_id', '')
        installation=data.get('installation_id')
        loader=data.get('loader_revision')
        if installation is not None and (not isinstance(installation,str) or not re.fullmatch(r'[a-f0-9]{32}',installation)):
            raise ValueError('invalid installation identifier')
        if loader is not None and (not isinstance(loader,str) or not re.fullmatch(r'[a-zA-Z0-9._-]{1,40}',loader)):
            raise ValueError('invalid loader revision')
        binding=self.installation_resolver(contract.client,installation,loader) if self.installation_resolver else 'unverified'
        revision=data.get('adapter_revision')
        if revision is not None and (not isinstance(revision,str) or not re.fullmatch(r'[a-zA-Z0-9._-]{1,40}',revision)):
            raise ValueError('invalid adapter revision')
        if not isinstance(project, str) or len(project) != 16 or any(c not in '0123456789abcdef' for c in project):
            raise ValueError('invalid project identifier')
        with self.lock:
            now = time.time()
            self.rows = {k:v for k,v in self.rows.items() if now-v['last_seen'] < 3600}
            previous=self.rows.get(identity)
            if previous and (previous['adapter']!=adapter or previous['project_id']!=project or previous.get('installation_id')!=installation):
                raise ValueError('runtime identity cannot be rebound')
            if identity not in self.rows and len(self.rows) >= 256:
                stale=[k for k,v in self.rows.items() if now-v['last_seen']>=45]
                if not stale:raise ValueError('connection capacity')
                del self.rows[min(stale,key=lambda k:self.rows[k]['last_seen'])]
            self.rows[identity] = dict(instance_id=identity, adapter=adapter,
                client=contract.client,capabilities=capabilities(adapter),
                installation_id=installation,loader_revision=loader,installation_binding=binding,
                mode=data['mode'], project_id=project, last_seen=now,adapter_revision=revision,
                revision_current=revision==contract.revision)
        return {'registered': True}

    def snapshot(self):
        with self.lock:
            now = time.time()
            return [dict(row, online=now-row['last_seen'] < 45) for row in self.rows.values()]
