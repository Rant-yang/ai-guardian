# 多客户端接入：源码研究与本轮落地

2026-10-30。针对用户列出的七个项目读取相关源文件与调用逻辑；这不是对整个仓库的完整审计。采用设计思路，在现有 Python/JS 实现中独立实现，没有引入这些项目作为运行依赖。

| 项目及实际阅读入口 | 借鉴和本轮结果 |
|---|---|
| [Orca · agent-hook-status-cache.ts](https://github.com/stablyai/orca/blob/main/src/shared/agent-hook-status-cache.ts) | 有界状态缓存优先淘汰过期项。Guardian 达到 256 个实例时优先移除超过 45 秒无心跳的实例，保留活跃实例。会话聚合额外区分客户端与演示来源，避免同名会话串流。 |
| [CC Switch · services/mcp.rs](https://github.com/farion1231/cc-switch/blob/main/src-tauri/src/services/mcp.rs) | 按客户端同步、精确拥有配置项、明确每次操作的结果。沿用独立启停和备份机制，补充旧版钩子原位升级及升级状态，不覆盖其他客户端设置。 |
| [Agent Deck Companion · hook_integration.rs](https://github.com/xuan-team/agent-deck-companion/blob/main/src-tauri/src/hook_integration.rs) | 一次写入用户级 hooks；识别归属后合并或移除。加强现有 JSON 结构校验，卸载时保留其他钩子及原有空组，增加旧版本迁移回归。 |
| [agentglass · hooksetup.ts](https://github.com/SirAllap/agentglass/blob/main/server/src/hooksetup.ts) | 观察与阻断必须分开；观察脚本缺失也不能经 shell 退出码变成工具拒绝。给全局观察命令增加外层故障放行，实测 Windows Git Bash / cmd 的缺失脚本场景。保护模式的决策逻辑没有改为放行。 |
| [MCPHub · mcpService.ts](https://github.com/samanhappy/mcphub/blob/main/src/services/mcpService.ts) | 阅读会话隔离、连接清理、重连相关段落。统一 `/api/overview` 状态入口，明确离线与恢复；控制台退避重连，最高 30 秒。没有照搬工具调用重试，避免重复产生副作用。 |
| [CLIProxyAPI · config_reload.go](https://github.com/router-for-me/CLIProxyAPI/blob/main/internal/watcher/config_reload.go) | 配置刷新与普通请求分开、避免无效重载。采用 5 秒配置状态缓存，管理操作后立即强制刷新；前端配置及实例列表内容不变时不重建。未引入模型认证代理。 |
| [Pipelock · status.go](https://github.com/pipelab-org/pipelock/blob/main/internal/cli/status.go) | 配置事实与运行探测分别展示。新增客户端诊断：配置冲突、待升级、未启用、等待事件、曾收到事件、实例在线。历史事件不等于当前在线，接入不等于已验证阻断。 |

## 用户可见变化

- 桌面 Guardian 入口保持不变，服务启动无需同时启动模型或所有 Agent。
- 页面周期刷新由三个接口合为一个；后台缓存配置读取，管理操作会主动失效缓存。
- 最近 200 条事件可按客户端、会话及风险筛选；会话数和计数仅针对这一窗口，不宣称完整历史。
- 服务中断后显示状态未知、禁用配置按钮；重连成功恢复展示。配置故障有独立提示。
- Claude/Gemini 已有观察钩子可原位升级；默认观察，不更改客户端原有权限。

## 验证与边界

27 项 Python 回归覆盖认证、配置保留、升级、钩子协议、缺失脚本放行、缓存、会话隔离、实例淘汰等；3 项 Node 测试覆盖界面逻辑与 Canvas。界面逻辑测试不等同于实机视觉验收。

当前 Claude/OpenCode 有此前真实 CLI 隔离验证；Gemini 完整模型会话、Codex 桌面端加载仍待体验。Codex 仅接入合成 MCP 工具，未覆盖原生 shell。没有把未实现的自动发现、模型代理、语义安全探针标为完成。本轮也没有引入登录自启动或预加载大模型。
