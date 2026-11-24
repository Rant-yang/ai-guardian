# 本地安装候选包

本阶段只做交付演练，不上传 GitHub、不生成发行版，也不自动决定项目许可证。

`packaging/preview-files.json` 是逐文件白名单。新增产品模块、资源或启动脚本后需明确加入；缺少已列出的文件会构建失败。当前候选包括运行源码、静态资源、接入安装器、启动脚本、必要文档及测试。不打包 `.local`、令牌、事件库、配置备份、虚拟环境、模型、上游仓库、设计图片或本机验证截图。

```powershell
python scripts/package_preview.py --output .local/releases/my-local-preview.zip
python scripts/package_preview.py --verify .local/releases/my-local-preview.zip
```

构建不启动服务、不联网、不扫描或改写用户 Agent 配置。固定 ZIP 时间戳与文件顺序；相同文件字节生成相同 ZIP 字节。已有相同包可复用，存在不同内容时拒绝覆盖，请使用新文件名。

每个包内包含 `BUNDLE_MANIFEST.json`，列出文件大小和 SHA-256。校验器核对清单、摘要、重复项、额外文件、路径与大小限制。摘要校验只能验证完整性，不是签名，也不能证明作者身份或源码无敏感内容。白名单需人工审阅，正式发布前仍需隐私、许可证与品牌审查。

## 历史独立包验收：v22

`.local/releases/guardian-local-preview-v22.zip`，102 个白名单文件，265781 字节，SHA-256 `be4bc43fc9b6e43511c49f23b98e343f9d7770a00699d2dc528d99af201ac756`。完整性校验后解压到 `.local/package-validation/中文 preview v22`，没有覆盖旧冻结目录。

清除测试进程的 PYTHONPATH 后，从该目录导入 guardian，实测导入路径属于解压目录。全部 191 项 Python（142.492 秒）和 58 项 Node 测试通过；setup.ps1 -CheckOnly 检测到现有 Python 与 WebView2。独立 30 秒 HTTP/SQLite 烟测产生 427 个唯一合成事件，427 个回执、零错误，SQLite 完整性 ok；一次性批准及重试包括在脚本内，没有执行真实工具或模型。测试后重新核对全部打包源文件哈希，保持不变。

证据 `.local/releases/v22-validation.json` 与 `.local/v22-package-http-smoke.json`。这不是全新系统安装、依赖下载、真实多客户端长任务或 GUI 长时验收。已有冻结 v15 两小时测试独立继续，不能替代 v22 的耐久证据。当前说明文档的后续更新不回写 v22 压缩包。

## 早期 v4 验收记录

候选：`.local/releases/guardian-local-preview-v4.zip`，82 个白名单源文件，加一份生成的清单。冻结内容的 SHA-256：

`82dd348304c129fedadabadc1eed7cf15cfa8d72bf449ed24aa9f8366747f6e0`

校验后解压到 `.local/package-validation/中文 preview v4`。从该目录运行测试，不使用开发目录作为 PYTHONPATH。首次启动测试使用独立端口与临时配置；未启用任何真实客户端接入。原有 Guardian 服务继续运行。

已验证白名单排除、可重复构建、篡改/额外文件拒绝、必要运行文件存在；解压后的前端与适配器 38 项通过，`setup.ps1 -CheckOnly` 通过。完整 Python 结果以 release-readiness.md 的本轮记录为准。

本包未包含 Python、WebView2、桌面依赖或模型。当前使用开发机已有运行时；不代表全新 Windows、缺依赖、下载中断、升级迁移与卸载验收已完成。包里的 `public_release_ready` 固定为 false，不能把“可生成压缩包”理解成“整体产品已完成”。

初次 v2 解压验收发现三处测试读取 UTF-8 配置时依赖系统 GBK 编码，修正为显式 UTF-8 后 v3 的 131 项 Python 测试通过。v4 额外携带根目录 .gitignore；最终冻结包的复验结果以本轮发布准备记录为准。
## v30 组合回归（2026-11-03）

候选 `.local/releases/guardian-local-preview-v30.zip`：112 个白名单文件、307622 字节，SHA-256 `414fd8524052d550aa5c75b656b32cf8d8c30daf40176bc4144da00ad661107c`。包含紧凑接口、来源恢复复制、审批状态修正、多会话验证选择、固定桌面依赖和 Python Launcher 发现及其测试。

原始解压目录 `中文 preview v30` 保留。自动审批拒绝在冻结目录内运行完整 Python 测试（测试可能写入该目录），按建议另建可写 `v30-test-run-01` 副本运行，未尝试绕过。清除 PYTHONPATH 后验证 guardian 实际从副本导入：207 项 Python 回归通过，178.165 秒。65 项独立 Node 测试通过；安装只读前置检查通过，部分注册表读取受限已显示提示。

30.14 秒隔离 HTTP/SQLite 烟测生成 431 条唯一事件、431 条回执、72 条审批记录，errors 为空、SQLite 完整性 ok；p50/p95/p99=16/31/32 ms，最大 47 ms。测试后两个解压目录中全部打包源码哈希均与清单一致。记录 `.local/releases/v30-validation.json` 和 `.local/v30-package-http-smoke.json`。

本轮未重复完整依赖安装、未操作真实 Agent 或执行模型，不是全新 Windows、GUI 长时或来源窗口验收。冻结包不包含本段后写入的报告文字，public_release_ready 仍为 false；用户运行中的后台没有被该测试替换。

## v28 独立目录验收（2026-11-03）

后续完整安装补测：同一独立目录从无 .venv 开始执行 setup.ps1 -NoOpen 成功；再次执行显示复用环境、无需网络安装，二者 exit 0。源文件哈希保持一致。安装依赖版本记录于 v28-validation.json；本次 pythonnet 3.2.1 等间接依赖与当前桌面使用的 3.0.5 不同，现有要求只固定 pywebview 6.2.1，完整可复现依赖仍需处理。没有启动新桌面窗口，未接入 Agent。仍是已有 Python/WebView2 的 Windows 开发机，不是全新操作系统验收。

候选 `.local/releases/guardian-local-preview-v28.zip`：111 个白名单文件，295835 字节，SHA-256 `7cf599e0b70435eb370c175266ce436dd30dfb95c9e727fafabc6ee06b61cba7`。解压到新的 `中文 preview v28` 目录，清除 PYTHONPATH 后确认 guardian 从该目录导入。202 项 Python 回归通过（143.634 秒）、61 项独立 Node 测试通过、setup.ps1 -CheckOnly 通过。30 秒 HTTP/SQLite 合成烟测 425 条唯一事件均有回执，零错误、完整性 ok。测试前后包内源文件哈希一致。

OpenCode opencode-contract.mjs 初次被错误地单独启动，没有 Python 夹具提供的临时服务和令牌而失败；它通过 test_guardian.py 中的正确夹具运行，并包含在上述 202 项结果中。独立 Node 只运行 dashboard、viz、opencode-navigation、opencode-failures。

证据 `.local/releases/v28-validation.json`、`.local/v28-package-http-smoke.json`。这是已有 Windows 和运行时上的解压验收，不是干净系统安装、GUI 耐久或真实 Agent 长任务。包保持 public_release_ready=false。此条记录为包构建后的补充，不回写冻结文件。


## v31 / v32 独立交付验收（2026-11-04）

v31 包含本轮适配器注册、配置范围、端点刷新、单实例锁、Qoder 实验接入及 Hook 配置语义校验。141 个白名单文件，380075 字节，SHA-256 `244a1b84dba7c1ac74dd2691fc072266de33cb6147d01ceebf2e763f0876b8f4`。新建可写解压副本 `v31-test-run-01`，清空 PYTHONPATH 后运行 270 项 Python 测试（293.167 秒）及 90 项 Node 测试，全部通过。独立虚拟环境导入 guardian 的实际路径属于该副本。

从无虚拟环境开始运行 setup.ps1 -NoOpen，创建副本内环境并安装 8 个固定依赖成功。重复运行使用该虚拟环境，报告依赖就绪、无需网络安装。没有打开桌面、启用真实客户端或更改日常 Agent 配置。CheckOnly 通过，但部分注册表位置不可读，诊断已如实提示；使用的是现有开发机 Python/WebView2 与 pip 缓存，不是全新 Windows 安装证明。

30.03 秒隔离 HTTP/SQLite 合成烟测：422 个唯一事件、422 个回执、70 条审批记录，零错误，数据库完整性 ok；p95 31 ms，p99 32 ms。未执行真实工具或模型。测试和安装后，全部打包源文件哈希不变。

v32 新增静态 Python 本地导入依赖检查：若包内代码引用本仓库模块、而该模块遗漏白名单，构建拒绝继续；检查不导入或执行模块。支持相对导入、包导入和脚本同目录导入，仍不覆盖动态导入、非 Python 资源或第三方依赖，需保留解压烟测。141 文件，380865 字节，SHA-256 `86e8149e3faff477f84f12246026fb1bd854988afdff6b04ed68dfcb3e100b3c`。逐文件核对，仅打包器、其测试及生成清单不同于 v31；运行代码完全一致。v32 单独解压后的 5 项打包测试通过，未声称对 v32 重跑全部 360 项。

记录 `.local/releases/v32-validation.json`。两个 ZIP 均为本地候选，未上传，public_release_ready=false。本段为验收后记录，不回写已冻结的 ZIP；当前运行的日常 Guardian 未因这次测试重启。


## v33 / v34 独立交付验收（2026-11-05）

开发目录完整回归 291 项 Python（292.335 秒）和 99 项 Node 通过。v33 解包后，99 项 Node 与 61 项关键后端/HTTP/打包测试通过，独立虚拟环境首装八个固定依赖成功；但完整交付验收发现 Windows venv 的启动器 PID 与真正提供 HTTP 的子进程不同，原启动记录不能用于新增的正常关闭身份核验。v33 不标为交付通过。

启动脚本现从认证健康响应取得实际服务 PID，并核对它是本次创建的 Python 进程或直接子进程，保存其创建时间与可执行路径。记录失败时清理已核验的实际服务和启动器。新增 venv 回归，加上原身份防护和记录失败恢复，共三项启动器测试通过（105.347 秒）。验收辅助程序也改用临时文件收集后台启动输出，避免 Windows 后代进程继承 pipe 导致等待不结束；这不是产品协议修改。

v34 ZIP 包含 151 个白名单文件，409556 字节，SHA-256 `6dcb5891493928ecdcc85ccc02b628dd038e1e738c4412257c76b3f43c03efb7`。与冻结 v33 逐文件比较，仅启动脚本、启动器测试和生成清单变化；不是把旧包覆盖成新包。

独立副本 v34-test-run-01 从无 .venv 完成 setup.ps1 -NoOpen，重复安装复用已就绪环境。经独立端口启动实际服务，四条合成检查验证通过、拒绝、待审批与单次授权重试，四条均有回执；随后 stop-background.ps1 正常退出，未用 Force。SQLite 完整性 ok，全部包内源码哈希未改变。报告位于 `.local/releases/v33-validation.json`、`.local/releases/v34-validation.json`；未上传，public_release_ready 仍为 false。

这是有既存 Python/WebView2 和依赖缓存的 Windows 主机验收。未声称全新操作系统、实际 Agent 动作、GUI 长时或检测准确率验收。完整 291/99 回归发生在 v33 对应源码，v34 对启动器变更做定向回归及独立安装/启停验证；其余运行代码与 v33 相同。
