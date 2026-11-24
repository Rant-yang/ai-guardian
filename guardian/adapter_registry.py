"""Trusted adapters behind a shared discovery/plan/install contract.

Catalog data cannot execute arbitrary handlers. New protocols require a reviewed
handler here and protocol tests; discovery alone never enables an integration.
"""
import os
from pathlib import Path
from .client_catalog import CLIENTS


def _json_hooks(spec, home, target, action):
    from .integrations import manage
    return manage(spec.id, action, home,target_path=target)


def _codex_hooks(spec, home, target, action):
    from scripts.install_codex_hooks import manage
    return manage(home, action,target_path=target)


def _opencode_plugin(spec, home, target, action):
    from scripts.install_opencode import manage
    return manage(target.parent.parent, action)


def _pi_extension(spec,home,target,action):
    from scripts.install_pi import manage
    return manage(target,action)


HANDLERS={'pi-extension':_pi_extension,'json-hooks':_json_hooks,'codex-hooks':_codex_hooks,'opencode-plugin':_opencode_plugin}
SPECS={spec.id:spec for spec in CLIENTS}


def available(spec):
    return bool(spec.installable and spec.target and spec.adapter in HANDLERS)


def supported():
    return {spec.id:spec.name for spec in CLIENTS if available(spec)}


def descriptor(client):
    spec=SPECS.get(client)
    if spec is None or not available(spec):
        raise ValueError('客户端尚无经过实现的接入适配器')
    return spec


def target(client, home, environ=None):
    spec=descriptor(client)
    env=os.environ if environ is None else environ
    value=env.get(spec.config_root_env) if spec.config_root_env else None
    root=Path(value) if value else Path(home)/spec.config_root_default
    if not root.is_absolute():raise ValueError('客户端配置目录必须为绝对路径')
    return root/spec.target


def operate(client, action, home, *, bound_target=None):
    if action not in ('status','install','uninstall'):raise ValueError('不支持的接入操作')
    spec=descriptor(client)
    resolved=target(client,home) if bound_target is None else bound_target
    return HANDLERS[spec.adapter](spec,Path(home),resolved,action)


def preflight(client, state):
    """Common onboarding contract. Static checks never certify runtime coverage."""
    from .adapter_contracts import capabilities, native_adapter
    spec=descriptor(client)
    caps=capabilities(native_adapter(client))
    plugin=spec.adapter in ('pi-extension','opencode-plugin')
    warnings=list(state.get('warnings',[]))
    if plugin:
        warnings.append('仅检查 Guardian 扩展文件；其他插件及其加载顺序尚未验证，配置完成后需验证真实动作。')
    if not caps['receipt']:
        warnings.append('此适配器目前没有执行回执；收到检查事件不代表动作已执行成功。')
    if caps['navigation']=='unsupported':
        warnings.append('此适配器尚不支持自动返回原会话窗口。')
    reload_hint=('重新启动对应的客户端进程，让扩展重新加载；只刷新 Guardian 页面不会加载扩展。' if plugin
                 else '在对应客户端重新打开会话；若没有新检查事件，请完全退出并重启客户端。')
    if spec.requires_trust:reload_hint+=' 如客户端请求信任 Hook，请在客户端审阅并确认。'
    return dict(scope='configuration_only',execution_verified=False,
                configuration='attention' if state.get('conflict') or state.get('outdated') or state.get('partial') else 'configured' if state.get('installed') else 'not_configured',
                third_party_check='not_checked' if plugin else 'shell_hints_only',
                warnings=list(dict.fromkeys(warnings)),reload_hint=reload_hint,
                verification_hint='请让该客户端读取一个普通项目文件，再检查是否收到这次真实动作。'+('同时核对执行回执。' if caps['receipt'] else '此客户端暂不提供执行回执。'))
