"""Implemented protocol capabilities, never evidence of an installation working.

Keep this server-owned: a heartbeat must not promote its own protection abilities.
Native approvals and retry approvals have different resume semantics.
"""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class JsonHookProtocol:
    """Reviewed wire format; sharing a format does not enable a new client."""
    before: str
    receipts: tuple[str, ...] = ()
    matcher: str = ''
    timeout: int = 5
    posix_command: bool = True
    hook_name: str | None = None
    explicit_shell: bool = False


JSON_HOOK_PROTOCOLS = {
    'qoder': JsonHookProtocol('PreToolUse', ('PostToolUse', 'PostToolUseFailure'), explicit_shell=True),
    'claude': JsonHookProtocol('PreToolUse', ('PostToolUse', 'PostToolUseFailure')),
    'gemini': JsonHookProtocol('BeforeTool', matcher='.*', timeout=5000,
                               posix_command=False, hook_name='guardian-local'),
}


@dataclass(frozen=True)
class Contract:
    client: str
    integration: str
    precheck: bool = False
    blocking: bool = False
    receipt: bool = False
    heartbeat: bool = False
    approval: str = 'unsupported'
    navigation: str = 'unsupported'
    revision: str | None = None
    scope: str = 'native_tools'


CONTRACTS={
    'pi-extension':Contract('pi','pi',True,True,True,approval='native_confirmation',navigation='terminal_window'),
    'qoder-hook':Contract('qoder','qoder',True,True,True,approval='native_confirmation'),
    'claude-hook':Contract('claude','claude',True,True,True,approval='native_confirmation',navigation='terminal_window'),
    'gemini-hook':Contract('gemini','gemini',True,True,approval='retry_required'),
    'codex-hook':Contract('codex','codex-native',True,True,True,approval='retry_required',navigation='terminal_or_desktop_request'),
    'opencode-plugin':Contract('opencode','opencode',True,True,True,True,'retry_required','session_request_and_terminal','scope-4'),
    'codex-mcp':Contract('codex','codex',scope='synthetic_demo'),
}


def capabilities(adapter):
    contract=CONTRACTS.get(adapter)
    return asdict(contract) if contract else asdict(Contract('unknown','unknown',scope='unsupported'))


def native_adapter(client):
    return next((key for key,value in CONTRACTS.items() if value.client==client and value.scope=='native_tools'),None)


INTEGRATION_ADAPTERS={value.integration:key for key,value in CONTRACTS.items()}


def mode_adapters():
    return tuple(key for key, value in CONTRACTS.items()
                 if value.scope == 'native_tools' and value.precheck and value.blocking)


def presentation_catalog():
    """Public display metadata; never an installed/online/protected claim."""
    from .client_catalog import CLIENTS
    names={client.id:client.name for client in CLIENTS}
    rows=[]
    for adapter,contract in CONTRACTS.items():
        name=names.get(contract.client,contract.client)
        if contract.scope=='synthetic_demo':name+=' MCP 演示'
        rows.append(dict(adapter=adapter,client=contract.client,integration=contract.integration,
                         name=name,mode_control=adapter in mode_adapters(),scope=contract.scope,navigation=contract.navigation))
    rows.append(dict(adapter='ollama-local',client='ollama',integration=None,
                     name='Ollama',mode_control=False,scope='model_only',navigation='unsupported'))
    return rows


def lifecycle(*, configured, readiness, online, capabilities):
    """Orthogonal facts: no event aggregate can prove every window is protected."""
    return dict(
        configuration='attention' if readiness in ('config_error','partial_config','upgrade_required') else 'configured' if configured else 'not_configured',
        presence='online' if online else 'offline' if readiness=='heartbeat_lost' else 'unknown',
        observation='checks_and_receipts' if readiness=='receiving' else 'checks_only' if readiness=='checks_only' else 'unverified',
        protection='unverified' if capabilities['blocking'] else 'unsupported',
        navigation=capabilities['navigation'],
    )
