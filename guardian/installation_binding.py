"""Correlate a loader's declaration with a fixed, locally managed installation.

This is diagnostic evidence, not remote attestation or an authorization grant.
Never accept a filesystem path from an adapter request.
"""
from pathlib import Path
from .adapter_registry import target
from .config_files import check_path
from .installation_identity import identity


def resolve_binding(client,installation_id,loader_revision,home=None):
    if installation_id is None:return 'not_reported'
    if client!='opencode' or loader_revision!='scope-1':return 'unsupported_loader'
    try:
        path=target(client,Path.home() if home is None else home)
        if identity(client,path)!=installation_id:return 'different_configuration'
        check_path(path)
        if not path.is_file():return 'configuration_removed'
        from scripts.install_opencode import plugin_text
        expected=plugin_text(path.parent.parent)
        with path.open('rb') as stream:raw=stream.read(len(expected.encode('utf-8'))+1)
        if raw!=expected.encode('utf-8'):return 'configuration_changed'
        return 'matched_local_configuration'
    except (OSError,ValueError):return 'configuration_unreadable'
