# Pi 原生扩展（实验接入）

通过控制台扫描向导选择 Pi，预览后安装。仅创建 `~/.pi/agent/extensions/guardian-agent-security.js`；支持 `PI_CODING_AGENT_DIR` 自定义目录。不会修改 settings.json、模型、认证文件或其他扩展。已有会话须按 Pi 的方式 `/reload` 或重启后验证。卸载仅删除与本安装器完全一致的专用加载器，用户改过的文件拒绝覆盖和删除。

当前为实验适配。已在隔离安装的 `@earendil-works/pi-coding-agent@1.5.0` 真实 CLI 中验证全局扩展自动加载、RPC 原生确认协议及实际文件副作用；终端界面交互、重载和原窗口导航仍未完成真实客户端验收。目录中出现 Pi、安装成功、收到检查和实际阻断是不同事实。

实现依据为 [官方扩展文档](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md)、[事件类型](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/extensions/types.ts) 与 [配置目录解析](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/config.ts)。独立实现 Guardian 适配器；读取的是 main 分支接口，不能据此保证所有发行版本兼容。

## 执行流程

1. `tool_call` 发送工具名称、参数、调用 ID、当前会话 ID 与 cwd 到固定回环地址。每次检查重新读取模式和服务端点；无云端请求，不读取对话文件。
2. 观察模式只记录。保护模式明确拒绝返回 `{block:true}`；review 使用 Pi 原生确认，对话展示后端脱敏动作摘要。
3. 无 UI、取消、超过五分钟/后端有效期、确认期间会话/工具/参数/cwd 改变，均不放行。客户端把原生确认结果绑定原事件和动作摘要，后台独立持久化 `native_confirmation`；确认记录失败、策略已撤销或审批过期均停止执行。收到审计响应后再次核对上下文。只确认当前动作，不执行或重放工具、不产生可复用授权。
4. `tool_result` 按会话及调用 ID 关联成功或失败回执，不发送返回正文。重复或无法关联的结果不伪造执行记录；会话关闭后清理未完成映射。
5. 服务异常或响应不合法：保护模式阻止，观察模式继续并尽可能在客户端提示。加载器模块缺失时仍读取本地模式，保护模式注册阻止处理器。

能力范围：没有覆盖用户 `!` / `!!` 命令、扩展自行执行的系统操作或其他未经过 tool_call 的行为。其他扩展后续修改参数、关闭/禁用本扩展、工具在产生 tool_result 前被其他组件中断等情况，不属于本次证明范围。缺回执保持未知，不当成成功。未实现 Pi 心跳和语义模型门控；已增加关联终端前置尝试与持久会话的手动恢复命令，具体限制见 [来源导航](source-navigation.md)。确认记录是客户端上报的审计事实，不是操作系统层的执行证明；其他原生 hook 客户端未上报确认时仍明确显示缺少该证据。

## 验证

隔离测试覆盖安装预览/撤销、保留其他配置、用户改动不覆盖、加载器缺失、模式故障、工具身份、原生确认/拒绝/超时、确认期间参数和会话变更、无 UI、成功/失败回执及不传输正文。Guardian 实际 HTTP 路由另验证原生确认状态、调用参数绑定和 Pi PowerShell 工具的删除规则。PowerShell 加入规则工具别名，归一化版本更新为 tools10；保留原始工具名和参数用于审批绑定。

上述单元测试中的 Pi API 是事件夹具。另外，`scripts/verify_pi_local.py` 启动真实 Pi CLI 和本机模型协议夹具，使用独立配置目录自动加载全局扩展，调用真实 write 工具。2026-11-04 在 Pi 1.5.0 的 JSON/print 模式中五项通过：允许产生文件、保护模式拒绝不产生文件、观察模式继续产生文件、无 UI 的待审批不产生文件、写入目录失败返回 failed。每项还检查唯一关联事件及执行回执。

同一脚本还通过真实 Pi 的 [RPC 扩展 UI 协议](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc-extension-ui.md) 接收确认请求并返回响应。它等待 `agent_settled`，而不是把 prompt 接收成功当成工具执行完成。验证确认后写入、拒绝后不写入、确认期间撤销授权后不写入；审计分别为 confirmed、not_confirmed 和未接受确认。另在隔离目录卸载专用加载器后启动新 Pi 进程，验证不再出现 Guardian 确认或事件，原工具仍可写入。

测试模型只提供固定工具调用，不连接云端；拒绝与待审批规则为测试注入，不代表生产规则准确率。脚本不安装 Pi，不修改日常配置，不是终端 UI、其他工具或所有扩展组合的兼容性证明。可先在隔离目录安装上述明确版本，再执行 `python scripts/verify_pi_local.py --pi-cli <Pi 的 dist/bundle/cli.js 绝对路径>`；结果默认保存到 `.local/pi-real-verification.json`，包含客户端版本和适配器文件摘要。发布前仍需验证终端真实 UI 确认、运行中重新加载和原窗口返回。


新增第十项真实 CLI 验证：持久会话按完整 ID 恢复后，以 RPC get_state 核对同一 sessionId，且没有新增模型请求。其他临时会话用例同时确认不提供恢复命令。扩展只传 PID 和持久化标记，不传 sessionFile 路径或内容；Windows 终端可见性仍需另行验收。
