# Codex 原生钩子接入（2026-11-01）

用户已明确授权最小钩子配置变更，前提是不影响其他客户端功能。已向 `C:/Users/lenovo/.codex/hooks.json` 追加 Guardian PreToolUse / PostToolUse，保留原有 Orca 钩子与其他事件。原文件备份为同目录 `hooks.json.guardian-backup-20261101-224753-681a8a76`。安装前后 config.toml SHA-256 一致；未改模型、API、权限策略或业务项目。

安装器：`python scripts/install_codex_hooks.py status|install|uninstall`。卸载只移除本工具拥有的两项命令，保留其他钩子。常规控制台的外部配置修改接口仍锁定，本轮授权通过专用安装器执行。

钩子绝对路径调用 `guardian/codex_hook.py`，不依赖业务项目工作目录。Codex 模式默认 observe；正常动作返回空对象，规则命中也不阻断、不自动授权；故障只返回观测不完整提示。存在本地调用耗时（网络超时 3 秒，宿主钩子超时 4 秒）。执行后只报告工具返回，不把返回当作业务成功。

## 当前验证状态

- 桌面端自带 Codex 0.160.0 的 hooks/list 已发现两项 Guardian 钩子，enabled=true，trustStatus=untrusted。
- 未修改 trusted_hash、未代替用户确认信任、未使用信任绕过参数。
- 45 项 Python 与 19 项前端回归通过，包括跨工作目录启动、配置保留和单次授权链路。
- 尚未完成真实 Codex 桌面会话的动作验证；配置完成不等于实际生效。

## 用户剩余一步

在 Codex 的钩子审核入口确认这两项 Guardian 命令。官方 CLI 入口是 `/hooks`，见 https://developers.openai.com/codex/hooks 。只确认命令指向 `D:/defence_agent/guardian/codex_hook.py` 的 PreToolUse / PostToolUse，不变更其他钩子。

本机 PATH 的旧 CLI 是 0.128.0，对当前共享配置存在兼容问题；不要为了审核去修改 service_tier。必要时可在 PowerShell 运行桌面自带版本：

```powershell
& 'C:/Users/lenovo/AppData/Local/OpenAI/Codex/bin/8aaf1547b825b104/codex.exe'
```

进入后输入 `/hooks` 审核。软件更新可能改变内置程序路径。完成后重开 Codex 会话，做一次无害读取，在 Guardian 选择“Codex 原生 Hooks”，检查出现真实事件及工具返回回执。首次审核不要求调用模型或提交业务任务。
