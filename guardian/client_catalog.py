"""Reviewed discovery signatures, independent from installed/verified coverage.

Entries are data only: discovery never executes commands or imports third-party plugins.
An executable name is an installation clue, not authenticated product identity.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Client:
    id: str
    name: str
    command: str
    config: str = ''
    coverage: str = '仅发现候选入口 · 监督适配尚未实现'
    installable: bool = False
    kind: str = 'agent'
    aliases: tuple[str, ...] = ()
    adapter: str = ''
    target: str = ''
    config_root_env: str = ''
    requires_trust: bool = False
    config_root_default: str = ''


CLIENTS = (
    Client('claude', 'Claude Code', 'claude', '.claude/settings.json', '用户级工具钩子', True, adapter='json-hooks', target='settings.json', config_root_env='CLAUDE_CONFIG_DIR', config_root_default='.claude'),
    Client('opencode', 'OpenCode', 'opencode', '.config/opencode/opencode.json', '用户级插件', True, adapter='opencode-plugin', target='opencode/plugins/guardian-agent-security.js', config_root_env='XDG_CONFIG_HOME',config_root_default='.config'),
    Client('gemini', 'Gemini CLI', 'gemini', '.gemini/settings.json', '用户级工具钩子', True, adapter='json-hooks', target='settings.json',config_root_default='.gemini'),
    Client('codex', 'Codex CLI', 'codex', '.codex/config.toml', '原生 Hooks · 当前安装仍需验证真实动作', True, adapter='codex-hooks', target='hooks.json', requires_trust=True, config_root_env='CODEX_HOME',config_root_default='.codex'),
    Client('pi', 'Pi Coding Agent', 'pi', '.pi/agent/settings.json', '原生扩展 · 实验适配，需验证真实动作', True, adapter='pi-extension', target='extensions/guardian-agent-security.js', config_root_env='PI_CODING_AGENT_DIR', config_root_default='.pi/agent'),
    Client('deepseek-harness', 'DeepSeek Harness', 'dsh', coverage='插件适配待实现 · 当前未监督'),
    Client('zcode', '智谱 ZCode', 'zcode', coverage='运行时适配待验证 · 当前未监督'),
    Client('qoder', 'Qoder CLI', 'qoder', '.qoder/settings.json', '原生 Hooks · 实验适配，需验证真实动作', True, aliases=('qodercli',), adapter='json-hooks', target='settings.json', config_root_env='QODER_CONFIG_DIR', config_root_default='.qoder'),
    Client('qcode', 'Qcode（产品身份待核实）', 'qcode', coverage='仅检查同名入口 · 不自动认作 Qoder 或 ZCode'),
    Client('ollama', 'Ollama', 'ollama', '.ollama', '模型服务 · 不等于 Agent 工具监控', kind='model'),
)
