# Gemini CLI 当前接入证据

2026-11-03，本机安装 @google/gemini-cli 0.66.0，实际 CLI 进程验证两例：读取临时文件返回固定标记；隔离服务将同一无害读取判为合成拒绝时，模型端收到 fixture_execution_gate，未收到文件标记。证据 docs/gemini-local-verification.json；重现入口 scripts/verify_gemini_local.py。

使用临时 GEMINI_CLI_HOME、临时 settings.json、本地 Google 兼容伪模型端点与假 API key。只信任测试自行创建的临时工作区，未变更用户持久信任、模型或 hooks。最初两次分别停在认证类型和目录信任校验，随后在临时测试环境显式配置再验证通过。测试拒绝仅注入隔离 Engine，不进入产品规则，且动作始终只是临时文件读取。

此证据证明该版本执行前 hook 的 normal/deny 链路，不证明真实模型检测效果、所有工具覆盖或版本升级兼容性。当前产品只安装 BeforeTool；没有精确关联的执行后回执。接入诊断与验证面板明确显示该限制。

官方 [hooks 协议](https://geminicli.com/docs/hooks/reference/) 提供 BeforeTool / AfterTool，但没有规定共享工具调用 ID。本机 0.66.0 bundle 的 fireBeforeToolEvent/fireAfterToolEvent 也未传递此标识。因此不凭相同工具名和参数将并发或重复动作拼成一条成功回执；后续需可靠关联方案或上游支持，不能伪造执行结果。
