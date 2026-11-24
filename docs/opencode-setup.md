# OpenCode 本地演示接入

## 2026-10-30 更新：用户级持久接入已安装

Guardian 现在位于 `C:\Users\lenovo\.config\opencode\plugins\guardian-agent-security.js`。首次重启 OpenCode 后，普通入口、不同项目的新实例都会加载，不必使用下面的演示目录。真实 OpenCode 已从两个不同目录加载插件并注册成功，证据见 `opencode-global-verification.json`；这项验证未调用模型，不代表工具阻断测试。

控制台已增加在线实例数、短 ID 和心跳超时失联状态。后台重启后插件会重新注册。双击根目录 `Open-Guardian.cmd` 可启动/打开控制台并复制令牌，不启动或限制 OpenCode 的工作目录。默认观察模式，尚未安装登录自启动。

以下保留为隔离演示步骤。

适配器依据 OpenCode 官方 tool.execute.before 插件接口：
https://opencode.ai/docs/plugins/#env-protection

只在本项目的 `demos/opencode` 目录加载，不修改全局 OpenCode 配置，不更换模型提供商，不增加工具授权。注意：OpenCode 原来的模型提供商仍可能是云服务；业务会话仍按该客户端的设置发送，Guardian 检查本身只发往本机。

```powershell
cd D:\defence_agent\demos\opencode
$env:GUARDIAN_MODE = 'observe'
opencode
```

告诉 OpenCode：`只读取当前目录的 notes.txt，总结一句话，不访问其他文件，也不运行命令。`
控制台选择“真实接入”，应出现来源 OpenCode 的 Read 事件。

关闭这次 OpenCode 后，可以把 GUARDIAN_MODE 改成 protect 再启动。规则命中 deny/review 时插件抛错停止工具；当前不实现 OpenCode 内的单次审批。服务无法访问时保护模式停止、观察模式只告警。现有启发式可误报和漏报。

需要无害规则触发样例时，可以请求只打印 `rm -rf GUARDIAN_DEMO` 这段文字，禁止真的执行删除命令。该样例验证的是插件边界，不是准确率，因为打印文本也会命中现有规则。

恢复：退出演示目录即不会加载这个项目插件；`Remove-Item Env:GUARDIAN_MODE -ErrorAction SilentlyContinue` 清理本终端环境变量。不要使用 `--pure` 验证，因为它跳过外部插件。

验证层级：Node 插件协议与本地后台集成测试；真实 OpenCode 会话是否成功加载和遵守钩子需要另外确认。不能把测试直接调用插件当成客户端已经验收。

实际工具验证补充：`opencode-local-verification.json` 已记录真实 CLI 的正常输出及 Guardian 拒绝结果，均通过。测试仅执行无害 printf，不调用云端；风险样例只是打印触发文本，不是真实删除。此前 30 秒冷启动超时已通过延长隔离测试等待解决。
