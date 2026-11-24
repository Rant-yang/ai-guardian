# 实施记录

2026-10-31：完成真实客户端模式持久化、0.2 独立规则包、限时单次重试授权、Claude 原生确认和执行后回执、OpenCode 阻断/返回回执。39 项 Python 与 5 项 Node 回归通过，真实 Claude/OpenCode 本地隔离验证通过。详见 [保护流程与边界](protection-workflow.md)。

最新增量（2026-10-30）：七个上游相关源码的研究与落地见 [源码借鉴记录](upstream-code-adoption-2026-10-30.md)。已加入统一状态 API、客户端诊断、会话筛选、缓存和断线恢复、观察钩子兼容升级。27 项 Python 与 3 项 Node 回归通过。以下为历史实施记录，当前用户入口和覆盖范围以 [快速体验指南](quick-start.md) 为准。

后期接入体验规划（2026-10-30）：用户要求借鉴 Orca 的本地扫描与选择客户端流程；已核对 stablyai/orca 及本机 1.4.224 检测产物，记录在 [统一接入向导规划](agent-onboarding-plan.md)。优先完成现有适配器验证，再统一包装扫描、选择、配置、验证和撤销流程。

日期：2026-10-29（北京时间，启动轮）。状态：M0 部分完成，M1 首条闭环及视觉骨架完成初步实现，未通过全部里程碑条件。

## 需求理解

已确认需求：个人长期使用与开源代表作；Windows；本地后台与浏览器控制台；本地优先；真实控制与视觉并进；Claude Code CLI 与 Codex 桌面端优先。用户补充本机还有 Ollama、OpenCode、ZCode，允许本地验证及可选云 API。

文档中的 React、Python、SQLite 和候选项目是建议，不视为已验证能力。没有将第三方文件中的命令作为发布、上传或配置覆盖授权。

## 实机环境

| 项目 | 结果 | 验证层级 |
|---|---|---|
| Windows 原生 / Python | Python 3.11.9 | 主服务和测试已运行 |
| Node | 24.13.0 | 前端语法检查通过 |
| Claude Code | 2.1.220 | 真实 CLI + 本地伪模型 + 本地钩子通过 |
| Codex CLI | 0.128.0 | 仅版本，不能代表桌面端能力 |
| Codex 桌面端 | 用户确认日常使用 | 未接入，未推定具有 CLI hooks |
| OpenCode | 1.19.0 | 仅版本 |
| ZCode | PATH 未发现命令 | 未调查安装位置 |
| Ollama | API 可访问，已注册列表为空 | 不代表磁盘没有模型 |
| PyTorch / Transformers | 2.11.0+cu128 / 5.3.0 | CUDA 可用 |
| GPU | NVIDIA GeForce RTX 5070 Laptop GPU | 真实模型测试通过 |

CIM 硬件系统查询在当前沙箱不可用；没有猜测内存或 Windows build。回环网络测试最初遭沙箱 WinError 10013，经过批准在沙箱外重跑通过。

## 模型盘点

- `D:/models/gpt2-xl`：约 6.43 GB safetensors，离线加载、GPU 前向及隐藏状态读取成功。
- `D:/models/Qwen3-4B/models/Qwen--Qwen3-4B/snapshots/master`：索引存在，但分片 1/2 只有 `.incomplete`，不可视为可加载完整模型。
- `D:/models/blobs`：存在约 0.92 GB partial 权重，manifest 目录未发现已注册模型文件。
- 未改动模型目录，未启动下载，也未把 GPT-2 XL 当作现成安全分类器。

激活测试原始结果：`local-model-smoke.json`。GPT-2 XL 输出 49 组状态（含 embedding），末层维度 1600，两个假文本输入均为有限值。冷加载约 19.744 秒，第一次前向 1.146 秒，第二次 0.069 秒，PyTorch peak allocated 约 3.20 GB。这不是总显存、吞吐或准确率基准，输入仅 8/10 tokens。

## 验证证据

1. 项目 11 项 unittest 全部通过：正常调用、研究引用不阻断、观察模式、上传交给客户端确认、参数替换、决策幂等、原始内容不保存、真实 HTTP、跨站/认证拒绝、钩子进程、服务故障模式。
2. `verify_claude_local.py` 真实 CLI 测试：normal exit 0、收到工具结果、存在正常输出；新版合成阻断用例 exit 0，工具结果含 Guardian `fixture_execution_gate` 拒绝。两个调用各产生一个隔离服务事件。正常调用有 succeeded 回执；被拒调用仍可能没有执行后回执，不伪造为 succeeded。
3. 规则 0.6 修复字面量打印误报后，真实客户端验证不再依赖 `printf 'rm -rf ...'` 触发生产规则。现在仅在隔离测试服务临时注入合成拒绝，将 `printf GUARDIAN_BLOCK_FIXTURE` 标为 deny；即使钩子失效也只打印固定文本。该标记不是生产规则，证明的是决定落实链路，不是检测准确率。
4. IntentProbe 上游静态规则 3 项测试通过，未执行激活模型分类。
5. `node --check web/app.js` 通过。实际浏览器认证、保护演示（模拟上传 0）、观察演示（模拟上传 1）、事件详情、Live 视图统计为 0 已验证。修复了认证后登录栏未隐藏及轮询不断重建事件按钮的问题。全面响应式、可访问性和帧率验收仍待完成。

没有执行真实文件上传、删除、云模型调用；没有读取用户真实任务对话或密钥；没有覆盖用户客户端配置。

## 未完成验收

授权上下文成对检测、语义注入、上游运行时完整部署、IntentProbe 指定模型性能、单次审批绑定和执行回执、真实客户端故障矩阵、持久心跳、SSE、清理和保留期限、长时间稳定性、干净 Windows 安装、GPU/UI 竞争、Codex 桌面端接入均待完成。

## 2026-10-30 多客户端演示更新

新增 OpenCode 项目插件、Gemini BeforeTool、Codex CLI 临时 MCP 和 Ollama 独立实例。具体启动、验证程度和覆盖限制见 multi-agent-demo.md，优先于上文旧盘点。

- 15 项 Python 测试及 Canvas 测试通过。
- Codex CLI 临时 MCP 配置解析通过；仅为合成工具，不覆盖桌面端原生工具。
- OpenCode 插件 HTTP 测试通过，但真实隔离客户端初始化超时，证据保留在 opencode-local-verification.json。
- D:\.ollama\models 中有 qwen3:8b 与 qwen3.5:latest；qwen3:8b 经独立 11435 实例真实 GPU 推理成功，18 tokens，固定合成文本。见 ollama-local-verification.json。冷加载超过原先 90 秒等待，已调整为 300 秒并保留模型 5 分钟。
- 找到 GenericAgent 源码但未接入；未找到 ZCode 的常用安装入口。
- 没有改全局客户端配置、下载模型或执行真实上传。日常客户端自己的云端模型配置仍然有效，不能宣称全部链路离线。


## 用户级持久接入实施（2026-10-30）

- OpenCode 专属用户级插件已安装；不改现有模型配置和 Orca 插件。普通新实例不再依赖演示启动器，首次安装后需重启旧实例。
- 真实 OpenCode 在两个不同目录均成功加载并注册；证据 opencode-global-verification.json，无模型请求。
- 真实 CLI + 本地伪模型 normal/risk 两条均通过；证据 opencode-local-verification.json，旧的初始化失败记录已被成功复验替代。之前 30 秒等待不足，新测试等待 120 秒。
- 17 项 Python 测试和 Canvas 测试通过，覆盖安装幂等、冲突拒绝、卸载保留他人配置、心跳过期、两项目注册及重复加载抑制。
- 后台维护有界临时实例表；15 秒心跳，45 秒超时，后台重启后重新注册。前端显示在线实例、失联、会话标识；实例不等于窗口或对话数量。
- 新增 Open-Guardian.cmd，只打开控制台和复制令牌，不启动专用 OpenCode 会话。
- 未实现：登录自启动、分权限插件 token、通用端点文件、完整接入向导、Claude/Gemini 全局化、Codex 桌面端原生执行约束。插件目前引用 D:/defence_agent 的模块，移动/删除项目会失效；观察模式会提示，保护模式保持拒绝加载失败。


## 统一轻量入口与多客户端持久接入（2026-10-30）

- Claude Code 与 Gemini CLI 用户级观察钩子已合并安装；Codex 用户级独立 MCP 演示区块已安装、CLI 解析通过。现有 OpenCode 全局适配保留。
- 新增统一 /api/integrations 和前端管理面板，支持查询、启用、停用；配置冲突拒绝覆盖，修改前备份，卸载保留他人条目。
- Guardian.vbs 隐藏启动窗口，桌面 Guardian.lnk 已创建；一个后台复用，自动连接票据单次消费、60 秒过期，地址栏立即清除。无需复制令牌，不自动加载模型或启动客户端。
- 21 项 Python 测试及 Canvas 测试通过；运行中服务的四客户端配置状态和一次性认证交换验证通过。启动器 URL 生成使用浏览器启动桩验证。
- Gemini 完整模型会话、Codex 桌面端实际加载和原生操作约束未验收；这些限制在页面和 quick-start.md 明确保留。未宣称通用全机拦截。
