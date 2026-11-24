# 上游源码与复用判断

核查日期：2026-10-29。源码快照位于忽略版本控制的 `artifacts/upstream/`，没有将上游源码复制进产品，没有执行下载来的安装脚本。

## Adrian

- 来源：https://github.com/secureagentics/Adrian
- 固定 commit：`8ad3bdb4abb2184fd56c00718b82c4d8a497bc16`。
- 仓库 LICENSE 标注 Apache-2.0；依赖和模型还需独立核对。
- 阅读 `integrations/claude-code/hooks/hooks.json`、`adrian_cc/agent.py`、`sdk/python/adrian/anthropic_handler.py`、`compose.yaml`。
- 值得借鉴：事件关联、独立策略决策、Pre/Post hooks 分工、服务端模式快照、显式等待执行前决策。
- 具体发现：Claude 插件默认 `ADRIAN_CC_FAIL_OPEN=true`，main 的异常路径也返回放行；SDK Anthropic gate 对缺少登录回执和等待超时则会阻断。不能把不同适配器混成同一种故障保证。
- 官方 Compose 路径涉及 Go 后台、Web 前端、可选本地分类器与容器 GPU 配置。可以自托管本地模型，但没有完成本机安装或资源测量。
- 判断：先借鉴契约与故障测试，暂不把整个平台作为主服务依赖。下一步针对固定版本适配器开展故障矩阵实验。

## IntentProbe

- 来源：https://github.com/mcpware/IntentProbe
- 固定 commit：`ebd6d19ba67e46df382d74d7577832015cbae092`；pyproject 版本 0.1.6，代码 Apache-2.0。
- 阅读 `scanner/core.py`、`scanner/configs.py`、`scanner/artifacts/*/metadata.json`、`tests/test_static_checks.py`。
- 值得借鉴：探针元数据、模型配方绑定、静态证据与激活证据分离、证据联合后再决定是否阻断，而非单独拿激活分数封禁。
- 正式工具投毒检测配方使用 Qwen2.5-0.5B 指定层；模型权重需额外下载并核对许可。现有 GPT-2 XL / Qwen3 不能代替该模型后沿用探针权重。
- 依赖包括 torch、transformers、numpy、scikit-learn 等；默认本地推理，首次模型取得需要网络。
- 本机执行原仓库 3 项静态测试全部通过，包含否定句不应被误报的案例。激活检测、端到端准确率和 CPU/GPU 性能尚未复现。
- 判断：优先下一步独立 worker 验证，不让模型加载阻塞工具钩子。不要把研究版授权探针与已发布工具扫描器混为一谈。

## 其余候选

| 项目 | 已核对 | 当前决定 |
|---|---|---|
| [Pipelock](https://github.com/pipelab-org/pipelock) | 官方边界与 LICENSE；核心 Apache-2.0，enterprise 独立条款 | 候选 MCP/网络 sidecar；未安装、未锁 commit，不宣称覆盖原生 shell |
| [Undercurrent](https://github.com/wrynx/undercurrent) | 官方仓库与激活干预定位 | 后续评估，未引入 |
| LlamaFirewall / ProbeX | 交接材料候选 | 本轮未实测 |

Claude 协议依据：https://code.claude.com/docs/en/hooks 。本机测试以已安装 2.1.220 为准，在线文档可能包含更高版本能力。

本文件记载的是本项目的选型判断，不能替代正式依赖许可证审计或上游产品安全结论。

## 2026-11-05：HTTP 并发背压

核对 [Uvicorn h11_impl.py](https://github.com/Kludex/uvicorn/blob/main/uvicorn/protocols/http/h11_impl.py) 中 limit_concurrency：连接或任务达到上限时转入 service_unavailable 返回 503。读取的文件 blob SHA 为 `c842a877f6151620ec97fde5a4666407f01e1800`。借鉴容量超限显式拒绝的设计，独立实现 `guardian/http_capacity.py`，未引入或复制 Uvicorn 实现，也未切换 ASGI。

Guardian 在工作线程创建之前限制 32 个活动连接，默认 socket 空闲超时 5 秒，过载回 503 和 Retry-After，恢复后继续接受请求。实际回环测试覆盖空连接超限、部分头/正文超时、线程创建异常回收，以及真实 Python Hook 在过载时保护拒绝、观察警告。此项不证明恶意慢速持续流量下的绝对时限或长期公平性；未解决关闭时所有后台任务排空问题。
