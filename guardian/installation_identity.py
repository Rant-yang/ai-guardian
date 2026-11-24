"""Local identity for configuration scopes and executable candidates.

Paths are normalized lexically, not resolved through symlinks. These IDs are
correlation hints, never credentials or proof that a runtime loaded the config.
"""
import hashlib
import json
import os
from pathlib import Path


def identity(client, path, *, kind='configuration', runtime=None):
    runtime=runtime or ('windows' if os.name=='nt' else os.name)
    normalized=os.path.normcase(os.path.abspath(str(path)))
    value=json.dumps([1,client,runtime,kind,normalized],ensure_ascii=False,separators=(',',':'))
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:32]


def configuration_scope(client,path):
    return dict(installation_id=identity(client,path),configuration_path=str(Path(path).absolute()),
                runtime='windows' if os.name=='nt' else os.name,scope='user',
                runtime_binding='unverified')
