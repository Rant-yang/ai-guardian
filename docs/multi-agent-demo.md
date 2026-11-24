# 本机多客户端演示

最新入口与覆盖请看 [快速体验指南](quick-start.md)：已扩展 Claude/Gemini 用户级钩子及 Codex 有限 MCP 接入，统一页面可以启停，Guardian.vbs 自动连接。以下包含历史演示步骤，日常使用无需逐一运行。

2026-10-30 更新：OpenCode 已安装独立用户级 Guardian 插件，其他客户端仍使用项目演示配置。界面只根据收到的事件更新来源状态，不把“已安装”当作“已保护”。

## OpenCode 日常接入

已安装到 `C:\Users\lenovo\.config\opencode\plugins\guardian-agent-security.js`。首次安装后重启 OpenCode，之后可从普通终端、任意项目目录启动；不再要求专用启动器。默认观察模式。后台需运行；电脑重启后的自动启动尚未安装。插件每 15 秒心跳，45 秒未收到心跳显示失联，后台恢复后会重新注册。

控制台刷新后可看到 OpenCode 在线实例数和实例短 ID；这是实例连接，不代表工具阻断已验证。纯文字聊天也可显示实例在线，工具事件仍须实际调用工具后出现。

卸载（退出 OpenCode 后执行）：`python D:\defence_agent\scripts\install_opencode.py uninstall --config-dir C:\Users\lenovo\.config\opencode`。只移除与本安装器内容一致的专属插件；内容冲突会停止，不删除其他文件。

## 其他客户端及演示入口

OpenCode 快捷入口：在资源管理器中双击项目根目录 `OpenCode-Demo.cmd`。它自动启动/复用后台、通过一次性连接票据打开默认浏览器，并在演示目录启动 OpenCode。页面自动连接，切换“真实接入”；在 OpenCode 请求读取 notes.txt 即可。无需手动输入启动命令。此入口不修改全局客户端配置，默认观察模式。

在 PowerShell 执行：

```powershell
cd D:\defence_agent
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-background.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-ollama-demo.ps1
# 日常直接双击 Guardian.vbs，使用一次性票据自动连接；无需复制上报令牌。
```

使用 Guardian.vbs 打开并自动连接控制台。access-token 是适配器上报凭据，不能用于管理登录；不要复制到剪贴板或分享。

分别在不同终端启动需要演示的客户端：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File D:\defence_agent\scripts\start-agent.ps1 -Client claude
powershell -NoProfile -ExecutionPolicy Bypass -File D:\defence_agent\scripts\start-agent.ps1 -Client opencode
powershell -NoProfile -ExecutionPolicy Bypass -File D:\defence_agent\scripts\start-agent.ps1 -Client gemini
powershell -NoProfile -ExecutionPolicy Bypass -File D:\defence_agent\scripts\start-agent.ps1 -Client codex
```

前三个默认观察模式。输入：`只读取当前目录 notes.txt，用一句话总结；不要访问其他文件或执行命令。` 控制台切到“真实接入”，观察各自来源。客户端仍保留自己的权限与模型设置；如果原来使用云模型，业务提示词仍会按原设置发往云端。Guardian 不新增工具权限，也不接管客户端所有行为。

Codex 入口是 CLI 的临时 MCP 配置，仅覆盖两个合成工具，不是桌面端全局接入。输入：`调用 guardian_read_demo，然后调用 guardian_upload_demo；不要使用其他工具。` 在“演示”视图查看 MCP 事件。模拟上传在保护模式应被阻断，真实上传始终为零。启动器临时覆盖 service_tier 为 fast，以兼容本机 CLI；没有改动全局配置。

“运行安全演示”提供保护/观察对比。“运行本地模型演示”将固定合成文本发给独立 Ollama 实例的 qwen3:8b；模型目录 D:\.ollama\models，端口 11435，不下载模型。冷加载最多等待约五分钟，完成后保留模型五分钟以避免演示反复加载。真实推理与安全语义分类是不同能力，目前未启用内部探针或语义安全分类。

## 已验证与限制

| 来源 | 当前证据 |
|---|---|
| Claude Code 2.1.220 | 真实 CLI、本地伪模型、钩子放行/拒绝已验证；日常启动默认为观察 |
| OpenCode 1.19.0 | 两个目录的真实实例全局加载通过；真实 CLI + 本地伪模型的正常放行/风险拒绝通过 |
| Gemini CLI 0.41.1 | BeforeTool 钩子进程测试通过；完整模型会话待验证 |
| Codex CLI 0.128.0 | 临时 MCP 配置解析通过，MCP 子进程调用测试通过；客户端实际调用待验证 |
| Codex 桌面端 | 尚未安装 MCP 配置，不显示为已保护 |
| Ollama | qwen3:8b 真实本地推理成功，生成 18 tokens 中文摘要；证据见 ollama-local-verification.json。qwen3.5:latest 文件存在但未运行 |
| ZCode | PATH、卸载记录、常用安装位置与开始菜单未找到，不能据此断言未安装 |
| GenericAgent | 发现 D:\GenericAgent，代码有工具调度边界；尚未连接，不改其源码或读取 mykey.py |

17 项 Python 测试及 Canvas 测试通过。原始工具参数仅参与内存规则判断，不写入事件库；界面展示元数据。服务只监听回环地址并检查令牌和请求来源。这是有限覆盖的实验版，连接成功不等于所有操作安全。

退出客户端即可结束这一演示会话。停止后台：`powershell -NoProfile -ExecutionPolicy Bypass -File D:\defence_agent\scripts\stop-background.ps1`。没有安装开机自启。
