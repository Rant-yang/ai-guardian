# 多 Agent 一次接入、跨窗口生效：GitHub 调研与设计决策

日期：2026-10-30。用户纠正：专用启动脚本和限定演示目录不符合日常使用；目标是一次启用客户端，之后从普通终端、任意项目打开的新会话自动连接。已有窗口是否需重启必须说明。

## 调研范围与证据等级

通过 GitHub 搜索与官方文档检索筛选多 Agent 管理、状态采集、配置同步、MCP 聚合、模型代理和安全代理。以下七个项目实际阅读了 README；Orca、CC Switch、Agent Deck Companion、agentglass 进一步阅读了相关源码或本机发布产物。未安装这些候选，也未将其文档宣称视为本机兼容性测试。源码链接指向本次查询的默认分支，不是已锁定依赖版本；直接复用代码前另行固定 commit 和核对许可证。

| 项目 | 实际机制与可借鉴点 | 对本产品的适用边界 |
|---|---|---|
| [Orca](https://github.com/stablyai/orca) | 客户端发现、启动管理、hook 状态汇聚；本机 OpenCode 全局插件读取端点文件，按文件变化刷新端口和 token | 学习安装发现、会话身份、服务重启重连；部分关联信息依赖 Orca 启动环境，不能推断任意外部窗口天然全覆盖 |
| [CC Switch](https://github.com/farion1231/cc-switch) | 统一管理各客户端配置、按应用开关同步 MCP；模型路由集中到本地服务；备份并保留无关配置 | 学习一次配置、跨项目生效、变更预览、撤销和各客户端重启提示；模型路由不等于 shell 执行拦截 |
| [Agent Deck Companion](https://github.com/xuan-team/agent-deck-companion) | Agent 注册表、显式安装 hooks、认证回环事件 API；配置合并、备份、原子替换和只卸载自己的条目 | 学习统一适配器注册及会话事件；平台实现大量依赖 macOS，不能直接当作 Windows 方案 |
| [agentglass](https://github.com/SirAllap/agentglass) | 全局 hook 安装器，将多个会话汇聚到本地工作台；观测与审批门分别启用 | 学习全局安装、幂等、故障策略分离；其 README 将 Windows 标为未实机验证，tmux 工作流也不能照搬 |
| [MCPHub](https://github.com/samanhappy/mcphub) | 将多个 stdio/SSE/HTTP MCP 服务汇聚为稳定端点；分组路由、认证、健康检查、热配置 | 适合多个本机工具端口统一管理；客户端仍需配置连接，而且不包含绕过 MCP 的原生文件/shell 工具 |
| [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) | 本地兼容模型 API，多个客户端指向同一代理，集中管理上游 | 适合模型服务和 API 流量治理；不能仅凭代理证明最终工具被阻断，不应为接入事件强迫用户改模型供应商 |
| [Pipelock](https://github.com/pipelab-org/pipelock) | 通过网络代理、MCP 包装及部署边界执行检查，提供发现与 doctor 诊断、决策证据 | 学习“已配置”与“可执行约束”分离；主机隔离方案需独立评估 Windows，不能把代理启动等同强制覆盖 |

## 深读证据

1. [Orca endpoint 文件解析](https://github.com/stablyai/orca/blob/main/src/shared/agent-hook-endpoint-file.ts)：解析 endpoint.env/endpoint.cmd，取得端口、token 和版本等字段。本机 1.4.224 的 `C:\Users\lenovo\.config\opencode\plugins\orca-opencode-status.js` 还显示文件优先于启动时环境变量，并缓存 mtime、size、inode；用于避免 Orca 重启后旧进程沿用过期端点。这里只读插件代码，没有读取端点凭据。
2. [CC Switch MCP 同步服务](https://github.com/farion1231/cc-switch/blob/main/src-tauri/src/services/mcp.rs)：按客户端分派同步，开关变更和重新同步共享锁，防止并发写入覆盖配置；结果按应用报告。
3. [Agent Deck hook 安装](https://github.com/xuan-team/agent-deck-companion/blob/main/src-tauri/src/hook_integration.rs)：JSON 备份、临时文件写入再 rename、按自身 handler 身份卸载；桥接器使用回环地址与本地 token。它的桥接器属于观测路径，不能直接复用为故障时必须阻断的保护路径。
4. [agentglass 全局安装器](https://github.com/SirAllap/agentglass/blob/main/hooks/install_hooks.py)：默认用户级 Claude settings，可选择项目级；幂等合并、备份、保留其他 hooks，观测与 gate 是两个开关，要求新会话生效。
5. [OpenCode 官方插件文档](https://docs.opencode.ai/docs/plugins/)：用户级 `~/.config/opencode/plugins/` 与项目级 `.opencode/plugins/` 均在启动时加载；本地重复插件可能分别运行，因此全局化后要避免项目入口重复检查。最新文档不替代本机 1.19.0 实机验证。

## 核心结论

用户感受到的“一次连接”，实际需要三件事一起成立：持久安装在客户端用户级入口；常驻服务能持续被找到；每个新会话携带自己的身份注册。窗口不是可靠身份，端口也不是会话身份。一个进程可能服务多个窗口/会话，多个进程也可以共用一个收集端口。

端口扫描只能发现监听者。stdio MCP 不一定监听 TCP；CLI 的本地工具执行也不一定经网络。因此本产品应以官方 hooks/plugins 为工具执行前入口，以已配置端点和有限探测辅助服务发现，不采用“扫描所有端口即全接管”的假设。

## 本产品采用的设计

```text
一次启用某客户端
    ↓
用户级适配器安装（备份、幂等、可撤销）
    ↓
用户从普通入口启动任意项目的新会话
    ↓
适配器读取本地服务描述 → 注册实例/会话 → 定期心跳
    ↓
工具执行前同步检查 → 客户端执行 → 成功/失败回执
    ↓
Guardian 常驻后台 → 所有窗口的事件汇聚 → 控制台按会话展示
```

- **客户端注册表**：发现、安装、验证、移除使用统一接口；记录 CLI/桌面、版本、用户配置目录和覆盖能力。Ollama 与其他模型服务单独分组。
- **用户级 OpenCode 插件**：作为下一项实现优先级，默认观察模式，适配用户实际配置目录，包括 XDG/独立配置环境；不覆盖已有 Orca 插件和模型配置。普通新窗口不依赖特定 cwd 或启动器。
- **本地服务描述**：固定受信任路径、原子更新、回环地址约束；插件按需刷新端点/token，后台短暂重启后自动恢复。管理接口与插件上报应分配不同权限 token。
- **常驻生命周期**：后台与网页生命周期分离；单实例/端口占用身份核验、失败状态和重连退避；后续提供托盘及登录启动开关，不能让每个客户端各自启动一份后台。
- **实例与会话注册**：实例 ID、客户端版本、适配器版本、session ID、受限项目标识、last_seen 和能力。无工具调用时也能显示“已连接、空闲”；离线状态随心跳超时，而不是靠历史事件假装在线。
- **端口服务注册**：模型 HTTP、MCP HTTP、客户端内部 API 使用类型化连接器；只访问已知/用户选择的回环服务，探测请求有超时，不能把未知监听端口标记为可控 Agent。
- **状态呈现**：分别显示未安装、配置完成/待重启、在线观察、保护已验证、失联；配置成功后要有无害验证事件。
- **保护与观测分离**：同步工具门保留严格超时/故障策略；异步状态事件不能拖慢或阻断工具。保护开关不能悄悄降低客户端原有权限约束。

## 必须兑现的体验与验收

首次安装或升级插件后，已运行的 OpenCode 实例通常需要重启以加载；不能承诺把新代码注入所有旧窗口。安装后的普通新实例应自动接入。同一用户不同配置目录、WSL、远程机器应分别发现和说明范围。

验收场景：两个不同目录分别正常启动 OpenCode；各自产生事件且会话不混淆；打开演示目录不重复加载；后台重启后原会话恢复；无事件时仍能区分空闲与失联；禁用/卸载只撤销 Guardian 变更；原 Orca 插件、模型配置与其他插件保持有效。

## 本轮实际变更

后续实施更新（2026-10-30）：OpenCode 全局插件已经安装；跨两个目录的真实客户端实例注册验证通过，见 `opencode-global-verification.json`。新增心跳和失联显示、专属文件冲突保护与可撤销安装。下面段落描述调研时的旧状态。

完成调研并提升“一次用户级接入”优先级。现有实现仍是项目级演示适配，尚未安装 Guardian 全局插件，也未新增登录自启动；不能把这份设计写成已实现能力。下一步先完成 OpenCode 全局安装与跨目录实机验证，再推广到 Claude/Gemini，Codex 桌面端单独确认官方扩展边界。
