# Agent 安全卫士 —— 项目总结

生成日期：2026-10-30
读取范围：`D:\defence_agent` 全目录（含 `docs/`、`design/`、`guardian/`、`web/`、`integrations/`、`scripts/`、`tests/`、`demos/`、`artifacts/`、`.local/` 的文件清单）
读取方式：递归列举目录并逐个读取源码与文档；`demos/**/node_modules/`、`artifacts/upstream/` 内的第三方文件只做结构与体量统计，未逐行阅读；`.local/access-token` 的实际令牌值未读取、未记录。

---

## 1. 一句话结论

这是一个**Windows 优先、本地优先的 Agent 行动检查实验版**：通过各客户端"工具执行前"钩子，把工具调用的**元数据摘要**送到本机 Python 服务做启发式判定，再把 `deny / ask / 放行` 交回客户端，同时把脱敏事件写进 SQLite 并用一个科幻风浏览器控制台实时展示。

产品能力与宣传口径之间的落差被作者刻意写清楚：**当前是规则演示原型，不是可长期使用的安全产品**。文档里明确区分"已验证"与"未验证"，这一点是全项目最值得保留的工程习惯。

---

## 2. 目录结构与体量

| 目录/文件 | 文件数 | 体积 | 作用 |
|---|---|---|---|
| `README.md` | 1 | 4.1 KB | 项目门面：启动、测试、试用、边界四条主线 |
| `guardian/` | 5 个源码 + pycache | 约 20 KB | 主服务：规则引擎、HTTP 服务、钩子、MCP 演示服务 |
| `web/` | 4 | 约 42 KB | 控制台前端（原生 JS + Canvas，无框架） |
| `integrations/opencode/` | 1 | 2.2 KB | OpenCode 项目级插件（`tool.execute.before`） |
| `scripts/` | 11 | 约 30 KB | 启动/停止、配置生成、本地验证、模型探针 |
| `tests/` | 3 | 约 12 KB | 15 项 Python 测试 + Canvas/MCP 契约测试 |
| `docs/` | 12 | 约 110 KB | 架构、实施记录、接入指南、上游调研、验证证据 JSON |
| `design/` | 3 | 约 88 KB | 产品定义交接文档（47 KB）+ 两版视觉参考稿 |
| `demos/` | 3677 | 52.9 MB | 四个客户端的隔离演示目录（体积主要在 OpenCode 的 `node_modules`） |
| `artifacts/upstream/` | 1115 | 51.3 MB | Adrian 与 IntentProbe 的上游源码快照（不纳入版本控制） |
| `.local/` | 9 | 约 84 KB | 访问令牌、SQLite 事件库、后台服务 PID 与日志 |
| `.gitignore` | 1 | 45 B | 忽略本地状态与上游快照 |

**注意**：该目录当前**不是 git 仓库**（无 `.git`），只有 `.gitignore`。这意味着所有"版本锁定""快照"的说法目前只是文档约定，没有提交历史可追溯。

---

## 3. 产品定位（来自 `design/Agent_Security_Product_Codex_Handoff_v1.md`）

- **一句话定位**：优先本地运行的开源 agent 安全卫士，帮用户看清 AI 正在读什么、准备执行什么、要把数据发往哪里，并在**支持的执行边界**上告警、暂停或阻断。
- **已确认决策（D01–D12 摘要）**：面向真实使用的开源安全产品、首发 Windows、本地后台 + 浏览器控制台、默认本地检测、视觉必须是核心需求（实时事件流 + 粒子抽离聚合）、积极复用已有项目、内部模型监测作为可选增强、短期目标是短视频 + GitHub 代表作。
- **明确不为**：通用杀毒 / 内核 EDR / 覆盖全机所有 AI 应用 / 读取闭源远程模型隐藏状态 / 默认读取全部个人文件。
- **核心原则**：防护只对经过其控制点的行为生效；"连接成功"≠"已保护"；日志订阅不等于执行前保护。

设计文档共 27 节，涵盖威胁模型、接入能力矩阵、事件模型、控制台信息架构、视觉规范、性能与故障、隐私、验收矩阵、M0–M5 里程碑、风险登记。

---

## 4. 已实现架构

```
客户端工具调用
   │  PreToolUse / BeforeTool / plugin hook / MCP tool
   ▼
适配器（guardian/hook.py、integrations/opencode/guardian.mjs、guardian/mcp_demo.py）
   │  只带元数据 → HTTP POST + Bearer token → 127.0.0.1
   ▼
guardian/server.py  ──  Host / Origin / Sec-Fetch-Site 校验 + 令牌比对
   │
   ▼
guardian/engine.py  ──  detect() 启发式 → 决策 → 幂等键 → SQLite
   │
   ▼
返回 verdict（pass / warn / review / deny）
   │
   ▼
适配器翻译成本客户端语义（Claude: deny/ask/空对象；Gemini: decision；OpenCode: 抛错停止）
   │
   ▼
web/ 控制台轮询 /api/events 渲染事件、粒子、详情
```

设计取舍记录在 `docs/architecture.md` 的三条 ADR：

- **ADR 001**：先用 Python 标准库 HTTP + SQLite + 原生 JS/Canvas 把协议和事件跑通，这是原型不是生产架构；
- **ADR 002**：来源与能力由适配器硬编码，不接受工具自称的可信来源；Demo 与真实事件严格分离；**决策 ≠ 已落实**；
- **ADR 003**：默认本地规则 + 可选本地语义检测；云端复核需显式配置；不得把本地故障静默降级为云端回退。

---

## 5. 代码模块清单

| 文件 | 关键内容 |
|---|---|
| `guardian/engine.py`（95 行） | `detect()` 三条启发式规则；`Engine.evaluate()` 负责参数校验、幂等去重、决策映射、事件落库、2000 条滚动裁剪；`demo_outcome()` 供演示回填执行结果 |
| `guardian/server.py`（160 行） | `ThreadingHTTPServer`；静态资源 + 6 个 API；令牌 `hmac.compare_digest`；边界校验；CSP/`no-store`/`nosniff`；请求体 ≤256 KB；5 秒 socket 超时；仅绑定 127.0.0.1 |
| `guardian/hook.py`（59 行） | Claude `PreToolUse` 与 Gemini `BeforeTool` 共用；**永不返回 allow**（避免绕过客户端原有权限询问）；异常时保护模式 fail-closed，观察模式只告警 |
| `guardian/mcp_demo.py`（59 行） | 最小 stdio MCP 服务，只暴露两个无害合成工具；唯一网络目标是本机 Guardian |
| `integrations/opencode/guardian.mjs`（41 行） | OpenCode 项目级插件；`protect` 模式对 `deny/review` 直接抛错；服务不可达时保护模式停止、观察模式记日志 |
| `web/app.js` / `viz.js` / `style.css` / `index.html` | Demo / Live 双视图、事件详情、风险过滤、粒子与点云动效、减少动态效果选项；统计数据全部来自 API |
| `scripts/*` | 后台启停（健康检查 + PID + 日志 + 重复启动复用）、项目级配置生成、CLI 真实验证、本地模型探针、视觉参考稿抽取 |
| `tests/test_guardian.py` | 15 项测试，覆盖规则、模式、幂等、隐私、认证、边界、四个适配器进程、故障模式 |

### 5.1 检测规则（当前全部实现）

| 规则标签 | 触发条件 | 建议决策 |
|---|---|---|
| `possible_injection` | 参数文本命中 `ignore ... instructions` / `忽略…指令` / `system prompt` | warn |
| `destructive_command` | Bash 命令命中 `rm -r*f` / `Remove-Item -Recurse` / `format x:` | deny |
| `outbound_transfer_review` | `curl/wget/Invoke-WebRequest` 且带 `--data/-d/-T/-Body/@`，或 `guardian_demo_upload` | review（交客户端确认） |

决策映射：`deny > review > warn > pass`；`observe` 模式把一切降级为 `warn`（有命中）或 `pass`（无命中）。代码注释明确写着：**"deliberately not a shell parser or semantic model"**。

### 5.2 事件模型（落库字段）

`event_id`、`session_id`（SHA-256 截断 16 位）、`occurred_at`（UTC ISO）、`tool_name`、`arguments_digest`、`phase`（`before_tool` / `model_input`）、`adapter_id`、`source_adapter`、`is_demo`、`mode`、`verdict`、`proposed_verdict`、`findings`、`enforcement_status`（默认 `decision_only`）、`detector`（`rules/0.1`）、`policy_version`、`latency_ms`、`limitations`。

**原始工具参数不落盘**，只保存 `sha256(tool, tool_input)`；同一 `call_id` 携带不同参数会被拒绝（防重放/参数替换）。

### 5.3 API 面

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/`、`/app.js`、`/viz.js`、`/style.css` | 静态资源（无需令牌，但受 Host/Origin 约束） |
| GET | `/api/events` | 最近 200 条事件 |
| GET | `/api/health` | 返回 `degraded`、规则就绪、语义不可用、验证级别 |
| POST | `/api/check` | Claude 钩子入口 |
| POST | `/api/opencode/check` | OpenCode 插件入口 |
| POST | `/api/gemini/check` | Gemini 钩子入口 |
| POST | `/api/mcp/demo` | Codex MCP 合成工具 |
| POST | `/api/ollama/demo` | 固定合成文本发往 11435 端口的本地 qwen3:8b |
| POST | `/api/demo` | 四场景内存演示（无真实副作用） |

---

## 6. 多客户端接入与验证程度（本项目最有价值的部分）

| 来源 | 接入方式 | 当前证据 | 覆盖限制 |
|---|---|---|---|
| Claude Code 2.1.220 | `PreToolUse` 命令钩子 | **真实 CLI + 本地伪模型**跑通放行与拒绝；每日默认观察模式 | 只覆盖钩子点；其他插件参数改写/钩子冲突未验证 |
| OpenCode 1.19.0 | 项目级插件 `tool.execute.before` | 插件与 HTTP 协议测试通过 | **真实隔离客户端停在初始化超时**，完整会话未验证 |
| Gemini CLI 0.41.1 | `BeforeTool` 命令钩子 | 钩子进程协议测试通过 | 完整模型会话待验证 |
| Codex CLI 0.128.0 | 临时 `-c` MCP 配置 | 配置解析 + MCP 子进程调用通过 | **仅两个合成工具**，不是桌面端原生工具保护 |
| Codex 桌面端 | 未接入 | 未安装配置 | 不显示为"已保护" |
| Ollama | 独立 11435 实例 | qwen3:8b 真实 GPU 推理成功，18 tokens 中文摘要 | 只是推理演示，**不是安全语义分类** |
| ZCode | 未找到安装入口 | PATH/卸载记录/开始菜单均无 | 不能断言未安装 |
| GenericAgent | 发现 `D:\GenericAgent` | 未接入 | 未改源码、未读密钥文件 |

**设计态度**：界面只根据收到的事件更新来源状态，"已安装"不会被渲染成"已保护"；`/api/health` 自称 `degraded`。

---

## 7. 安全与隐私设计

- **认证**：`.local/access-token` 生成 32 字节 URL-safe 令牌，`hmac.compare_digest` 比对，`Bearer` 头传递；令牌只保存在页面内存，不进 URL、不进持久存储。
- **请求边界**：只监听 `127.0.0.1`；校验 `Host`、`Origin`、`Sec-Fetch-Site`；`POST` 必须同时通过边界和令牌。
- **响应头**：严格 CSP（`default-src 'self'`、`frame-ancestors 'none'`）、`Cache-Control: no-store`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: no-referrer`。
- **数据最小化**：只落盘参数哈希 + 工具名 + 风险标签 + 时间；SQLite 上限 2000 条；界面显示 200 条。
- **失败策略**：保护模式 fail-closed（拒绝并说明"protection failed closed"），观察模式只提示"observation incomplete"；错误路径不打印原始参数、令牌、路径。
- **已知弱项**：同 OS 用户下的恶意进程不在强隔离范围内；本地 API 尚未做完整安全审计；无用户级 ACL、无保留期限与清理界面。

---

## 8. 测试与验证证据

`tests/test_guardian.py` 共 **15 项**（文档记载全部通过）：

1. 正常调用保留客户端原有权限询问
2. 研究引用注入文本只告警不阻断
3. 危险命令 + 观察模式降级
4. 上传请求交客户端 review
5. 幂等与参数替换拒绝
6. 原始内容不落盘
7. Demo 事件不能被真实事件回执
8. Demo 保护模式阻断副作用 / 观察模式放行
9. API 认证与跨站边界
10. 真实钩子进程协议
11. 钩子故障模式
12. OpenCode 插件真实 HTTP
13. Gemini 钩子进程
14. MCP 演示进程
15. Ollama 固定目标与失败路径

其他证据：

- `scripts/verify_claude_local.py`：真实 Claude CLI + 临时独立配置 + 本机伪端点。规则 0.6 起，测试服务临时注入合成拒绝标记，工具只可能打印 `GUARDIAN_BLOCK_FIXTURE`；生产规则不含该标记。**证明钩子落实，不证明语义准确**，不再依赖字面量打印误报。
- `docs/local-model-smoke.json`：GPT-2 XL 离线加载成功，49 组隐藏状态、末层 1600 维、冷加载约 19.7 s、首次前向 1.146 s、峰值显存约 3.20 GB。
- `docs/ollama-local-verification.json`：qwen3:8b 真实 GPU 推理成功。
- `docs/claude-local-verification.json`、`docs/opencode-local-verification.json`：各客户端验证快照。
- Canvas 单元测试 `tests/viz.test.cjs`、MCP 契约 `tests/opencode-contract.mjs`。

**未执行**：真实文件上传/删除、云模型调用、读取用户真实对话或密钥、覆盖用户客户端全局配置。

---

## 9. 上游调研与复用判断（`docs/upstream-review.md`）

| 项目 | 固定版本 | 结论 |
|---|---|---|
| **Adrian**（secureagentics） | commit `8ad3bdb`，Apache-2.0 | 借鉴事件关联、独立策略决策、Pre/Post 分工、显式等待执行前决策；**注意其 Claude 插件默认 `ADRIAN_CC_FAIL_OPEN=true`，异常路径放行**，不能与 SDK 的阻断路径混为一谈。暂不整平台依赖 |
| **IntentProbe**（mcpware） | commit `ebd6d19`，v0.1.6，Apache-2.0 | 借鉴探针元数据、模型配方绑定、静态证据与激活证据分离、证据联合后才阻断。投毒检测需 **Qwen2.5-0.5B 指定层**，现有 GPT-2 XL / Qwen3 不能顶替。本机 3 项静态测试通过，激活检测未复现 |
| **Pipelock** | 未锁 commit | 候选 MCP/网络 sidecar，未安装，不宣称覆盖原生 shell |
| **Undercurrent** | 未引入 | 后续评估 |
| **Orca**（stablyai） | 本机 1.4.224 | 仅借鉴"本机扫描 + 选择 Agent"接入向导流程，未复制实现 |
| LlamaFirewall / ProbeX | — | 本轮未实测 |

上游快照放在 `artifacts/upstream/` 且被版本控制忽略，**没有把上游源码复制进产品，也没有执行下载来的安装脚本**。

---

## 10. 当前边界与未完成项

**能力边界**

- 规则只有 3 类，可被编码、别名、其他工具绕过；不解析任意 shell。
- 真实事件只记录"决策已发出"（`decision_only`），**没有 PostToolUse 执行回执**，不能说"已确认阻断"。
- 覆盖范围仅限各适配器的特定钩子点；MCP 网关不覆盖原生 shell，日志订阅不等于执行前保护。
- 语义检测与激活探针**尚未接入主服务**；GPT-2 XL 测试不是安全效果评测。
- 云端复核未实现；默认无遥测、无云端检测调用。

**功能缺口**

- 无 SSE（前端 1.5 秒轮询）；无真实心跳与断线恢复；无单次审批绑定与过期。
- 无保留期限、无清理界面、无用户级 ACL。
- 无 Windows 安装/卸载恢复流程；无长时间稳定性测试。
- 前端全面响应式、可访问性、帧率验收未完成；**浏览器自动验收曾被工具 URL 安全策略拒绝**，现有 `docs/console-preview.png` 是旧版截图。

---

## 11. 里程碑状态

| 里程碑 | 定义 | 状态 |
|---|---|---|
| M0 环境与复用验证 | 客户端能力表、依赖验证、架构决策、Windows 运行路径 | **部分完成** |
| M1 真实垂直闭环 + 视觉骨架 | 后台、事件协议、一个适配器、规则检测、控制台、粒子初版 | **首条闭环与视觉骨架完成初步实现，未达全部验收条件** |
| M2 可长期使用的 Alpha | 本地语义检测、策略与审批、异常处理、安装引导、日志隐私 | 未开始 |
| M3 第二客户端与调查能力 | 另一个客户端适配、有界调查助手、跨事件上下文 | 未开始（已提前铺开 4 个适配器，但验证深度不足） |
| M4 内部模型增强 | 经校准的本地探针，可解释增益与代价 | 未开始（仅 smoke 测试） |
| M5 社区扩展 | 稳定插件契约、发布自动化、桌面外壳 | 未开始 |

---

## 12. 建议的下一步（按 `docs/architecture.md` 给出的顺序）

1. 完成本地控制台浏览器验收（布局、状态、响应式），并留下可复现的验收记录。
2. 固定版本跑 Adrian 或 Pipelock 的隔离边界实验，与当前钩子比较**失败策略**差异。
3. 获取并校验 IntentProbe 所需 Qwen2.5-0.5B，完成正常/投毒成对实验与成本测量（不覆盖 `D:/models` 现有内容）。
4. 接入 worker 超时、队列与语义降级；建立检测器契约与结构化证据。
5. 补可信任务记录、PostToolUse 回执、心跳、SSE、单次审批摘要绑定与过期。
6. 确认 Codex 桌面端真实扩展点；OpenCode / ZCode 分别调查，不假设兼容。
7. Windows 安装与卸载恢复、日志清理、长跑与攻击变体评估通过后再进入 Alpha。

**工程侧额外建议（本次通读补充）**

- **纳入版本控制**：当前无 `.git`，`artifacts/upstream/`（51 MB）与 `demos/**/node_modules`（约 50 MB）应按现有 `.gitignore` 排除，其余源码与文档应尽快提交，否则"固定 commit 快照""验证证据"无法回溯。
- **把 `docs/*.json` 验证证据接入 CI**：现在它们是手工快照，容易与代码漂移。
- **前端编码统一**：`design/` 下部分文档为 GBK/混合编码，`web/app.js` 中的中文文案在非 UTF-8 控制台会乱码，建议统一 UTF-8。
- **`prepare_agents.py` 中硬编码 `D:/python/python.exe` 之外的路径依赖**：`demos/claude/guardian.settings.json` 里写死了本机解释器路径，换机即失效。

---

## 13. 文档地图（想深入看哪里）

| 想了解 | 读这个 |
|---|---|
| 产品完整定义、威胁模型、视觉规范、里程碑 | `design/Agent_Security_Product_Codex_Handoff_v1.md` |
| 当前架构与 ADR | `docs/architecture.md` |
| 实施进度、实机环境、验收记录 | `docs/implementation-status.md` |
| 四个客户端的启动与验证程度 | `docs/multi-agent-demo.md` |
| OpenCode 接入细节 | `docs/opencode-setup.md` |
| 上游项目选型与复用判断 | `docs/upstream-review.md` |
| 统一接入向导规划（借鉴 Orca） | `docs/agent-onboarding-plan.md` |
| v6 视觉落地与启动修复 | `docs/ui-v6-update.md` |
| 快速上手 | `README.md` |

---

## 14. 总体评价

**做得好的地方**

- 能力边界写得比能力本身更清楚：`degraded` 健康状态、"连接成功≠已保护"、`decision_only`、"启发式可能误报漏报"贯穿 README、代码注释、界面文案三处一致。
- 安全工程基本功到位：不返回 `allow`、失败 fail-closed、不落盘原文、幂等键绑定参数、HMAC 令牌比对、CSP + Origin 校验。
- 多客户端适配抽象统一（同一个 `evaluate()` 接受 5 种 adapter），新增接入成本低。

**最大的风险**

1. **适配器数量领先于验证深度**——4 个客户端接入，但只有 Claude 达到"真实 CLI + 钩子"级别，OpenCode 真实会话仍停在初始化。
2. **规则层极薄**（3 条正则），距离"可信防护"很远，当前更接近可视化演示器。
3. **无版本控制**，与其"锁 commit、留证据"的自我要求不匹配。

**判断**：作为 M1 阶段的公开演示与短视频素材，完成度足以支撑；作为"可长期使用的安全产品"（M2），还差语义检测、执行回执、审批闭环、安装/卸载与长跑验证五块硬骨头。
