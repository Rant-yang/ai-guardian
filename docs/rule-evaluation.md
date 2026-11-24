# 规则开发评测（2026-11-03）

这是 36 条人工编写的开发样本，包含正常/风险操作对照，不是独立留出集，也不代表真实用户数据分布。只把命令作为字符串传入规则引擎，不运行命令、不读取目标文件、不联网发送样本。

运行方式：

```powershell
python scripts/evaluate_rules.py --output .local/rules-evaluation.json
```

| 指标 | 0.2 基线 | 0.3 本轮 |
| --- | ---: | ---: |
| 样本数 | 36 | 36 |
| 决策与标注完全一致 | 23 | 32 |
| 14 条正常样本被标记 | 6 | 2 |
| 22 条风险样本完全未命中 | 7 | 2 |

原始样本及前后报告位于 `evals/rules-development.json`、`evals/rules-baseline-20261103.json`、`evals/rules-current-20261103.json`。报告保留每条的预期/实际决定、命中规则与策略版本，不通过隐藏失败样本提高分数。报告中的计时只测规则函数，不代表 Hook 全链路延迟。

本轮修改：凭据访问只匹配结构化目标路径，不再因普通文档正文提及私钥名称而触发；区分私钥与 `.pub` 公钥、普通说明文件；补充 `.npmrc`、`.pypirc`、相对 AWS 凭据路径；递归删除规则支持拆开的短参数。缺少可识别文件路径的文件工具标记为专用规则覆盖不足。策略版本包含路径规范化契约，旧单次授权不能匹配新规则版本。

## 尚未通过的样本

- `printf 'rm -rf fixture'`：仅打印示例仍被拒绝。
- `Remove-Item ... -WhatIf`：PowerShell 试运行仍被拒绝。
- `cat fixture/.ssh/id_ed25519`：通过 Shell 读凭据尚未命中。
- Python 中通过 `shutil.rmtree` 间接删除：尚未命中。

后续需要命令结构与解释器语义分析，不能仅删除引用字符串或看到 `-WhatIf` 就整条放行，否则会漏掉命令替换、串联命令等实际执行行为。还需要独立标注、未见变体、真实客户端端到端与语义模型对照评估；上述样本改进不构成发布安全效果验收。

## 使用体验反馈

真实事件详情新增“我的判断”：疑似误报、确有风险、疑似漏报、暂不能判断；可以撤回。只存分类、时间和该事件原规则版本，不收集补充文本或完整命令。反馈属于用户意见，显示为未经验证，不自动生成规则例外、不授权重试、不解除拒绝、不重放动作。演示记录不提供反馈入口，避免混入真实使用反馈。

可在事件筛选中选“已标记反馈”（仍是最近 200 条窗口），或者在本机记录管理中导出保留历史中的反馈。导出不自动上传。清理事件会一并移除反馈；已导出的副本需自行管理。并发窗口使用版本校验，过期页面不能覆盖新判断，需要刷新后重新提交。


## 2026-11-03：规则 0.4

新增直接 Shell 读取凭据的审批信号：识别起始 cat/Get-Content/gc/type/head/tail 命令的字面量路径，保留 Windows 反斜杠与带空格路径。仅增加匹配，不通过解析器消除已有拒绝。文档打印、公钥与普通 README 不触发新规则。规则语义版本随之变更，旧版本授权不能用于新规则的动作。

同一 36 条开发样本变为 33 条完全匹配，正常样本标记仍 2/14，风险完全漏检 1/22。仍有引用删除命令与 WhatIf 误报、Python 间接删除漏检。变量展开、命令包装、别名重定义、复合 Shell 及脚本内容不由此字面量提取器完整理解；不得声称覆盖全部凭据读取。报告在 .local/rules-evaluation-v04.json。


## 2026-11-03：规则 0.5

补齐有限 python -c 直接调用 shutil.rmtree 的静态识别，支持标准导入与别名。只检查外层双引号、无 Shell 展开/反斜杠的有界字面量代码及顶层直接调用；不执行代码、不遍历未调用函数体，也不把字符串示例当成删除调用。复杂控制流、包装命令、文件脚本、动态路径和其他解释器仍不完整覆盖。

原 36 条开发样例变为 34 条匹配，正常样例误报仍 2/14，风险完全漏检为 0/22。这不是独立准确率；仍存在未知变体与有限解析的边界。剩余两条正常样例误报为引用删除命令及 PowerShell WhatIf，未自动豁免不理解的复合命令。报告在 .local/rules-evaluation-v05.json。

## 2026-11-03：规则 0.6 / tools5

新增两种完整命令的有界识别：`printf '字面量文本'`（不含格式串、展开或控制符），以及单一字面量路径、已知参数集合中的 `Remove-Item ... -WhatIf`。仅消除这些形式命中的 destructive_command，通用注入等其他信号继续检查；不删除引号内容后再盲目判断整条命令。

复合命令、管道、重定向、变量/命令替换、脚本包装、额外未知参数、重复开关、通配路径和带值 WhatIf 均不豁免，包括 `-WhatIf:$false`。运行时函数、别名或同名程序可能改变标准命令语义，当前不会检查其定义；该边界在事件 rule_coverage.note 中明确记录。其他普通命令也没有完整语义保证。

36 条原开发样本为 36 条匹配，14 条正常样本被标记数为 0，22 条风险样本完全漏检数为 0；样本和标注未变。不能称为独立准确率，更不能推导未知变体没有漏检。报告：`.local/rules-evaluation-v06.json`。新增测试保留实际删除、假 WhatIf、复合/展开等边界；所有危险命令仅为字符串，从未执行。

语义依据为 [GNU Bash printf 文档](https://www.gnu.org/s/bash/manual/html_node/Bash-Builtins.html) 与 [Microsoft Remove-Item 文档](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/remove-item?view=powershell-7.5)。实现为项目自写的有限识别器，不是完整 Shell 解析器。策略版本随识别语义更新，旧单次授权不能匹配新版本动作。
## 2026-11-03：tools6 补丁目标规则

新增 apply_patch 有界结构提取：最多 65536 UTF-8 字节、64 个目标，必须有 Begin/End 包络。提取 Add/Update/Delete File 与 Move to 路径，用于原敏感文件规则；只保存有界文件名，不把补丁正文中示例路径或网址当成实际文件/网络目标。声明删除文件进入 review，无法解析、多个正文键、超预算或缺包络进入 patch_unparsed_review。规则目录同时列出这两项结构检查。

参数依据：[OpenCode apply-patch.ts](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/tool/apply-patch.ts) 使用 patchText；[Codex apply_patch.rs](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/handlers/apply_patch.rs) 的执行前/后钩子使用 command。兼容单一 patch/input 字段，但不猜测多个字段的优先级。上游主分支可能变化，这不是所有已安装版本的实测证明。

此解析器仅识别头部路径与删除声明，不验证补丁能否应用、编辑内容是否安全、符号链接最终目标或项目根目录边界；未知结构进入人工确认，不执行补丁。内容行的 +*** Delete File 示例不当作删除头。授权仍绑定完整原工具参数，任何补丁变化须重新检查；版本升级为 0.6-44ea66b46d4c-tools6，使旧版本单次授权不能匹配新动作。

原 36 条开发样例保持 36/36 匹配（.local/rule-evaluation-patch.json），不代表新增补丁规则的独立准确率。新增 5 项专测覆盖多文件敏感目标、移动目的地、正文例子、删除、格式/预算拒绝、两类上游字段及原参数一次性绑定。实际本机各客户端版本的补丁回调与恢复尚需专门验收。

随后完成本机 OpenCode 1.19.0 的真实进程验证（docs/opencode-patch-verification.json）：本地合成模型明确提供 apply_patch，实际临时文件证明普通新增成功；.env 新增因 sensitive_file_access 在执行前被阻止；普通文件删除因 patch_delete_review 被阻止且原文件保持完整。三例各一条事件和对应回执，分别 tool_returned、blocked、blocked。测试没有为规则注入替代判定，也没有使用真实凭据或用户项目。此结果不覆盖 Codex 补丁、用户批准后的实际重试、移动文件或所有 OpenCode 版本。

开发者可在已安装 OpenCode 的 Windows 本机运行 `python scripts/verify_opencode_patch.py`；它使用项目测试临时目录、独立客户端配置、回环模型端点和内存守卫。没有修改全局 Agent 配置；测试会在临时目录创建一个普通文件，敏感文件与删除案例均应被阻止。仅用于接入验证，不是日常启动方式。
# Windows 敏感路径变体（tools7）

敏感文件规则对工具路径、补丁目标和已提取的 Shell 字面量读取目标追加 Windows 检查表示：去除路径组件末尾空格/句点，并检查最后文件组件的流名称之前的部分。原表示始终保留，检查不会改写工具参数、执行路径解析或读取文件。只用于 Windows 主机或明确的盘符/UNC 路径。不会折叠 `..`、解析符号链接或保证覆盖所有 Windows 命名空间；特殊 API 对尾随字符的处理可能不同，因此只请求复核，不据此断言实际访问了凭据。

审批摘要仍绑定完整原始参数。合成文件实测 `.env`、`.env::$DATA`、末尾空格及句点在本机读取相同内容，四种均命中；公共密钥 `.pub` 和普通文件流不因这个规则被当作敏感凭据。依据：[Windows 命名规则](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)、[文件流](https://learn.microsoft.com/en-us/windows/win32/fileio/file-streams)。

## 规则 0.7：Git 与 Docker 默认凭据路径

文件工具、补丁目标与已支持的 Shell 字面量读取补充 `.git-credentials`、`.config/git/credentials` 和 `.docker/config.json`，沿用 review，要求核对任务范围。普通 `config.json`、相似说明文件、`.example` 后缀及文档正文提及不因新增模式触发；没有实际读取这些配置或凭据。

依据 [Git credential-store](https://git-scm.com/docs/git-credential-store) 和 [Docker login](https://docs.docker.com/reference/cli/docker/login/)。这些是可能含凭据或控制认证的路径，并不证明某一文件包含密钥；Docker 也可以使用外部 credential helper。未解析自定义 XDG_CONFIG_HOME、DOCKER_CONFIG、Git --file、变量或符号链接，因此不是所有凭据存储覆盖。

新增成对路径/文档测试，6 项工具覆盖、4 项 Shell 目标测试通过；原 36 条开发样本保持 36 条匹配，报告 .local/rule-evaluation-v07.json。开发样本不能当成独立准确率。版本为 0.7-9da6a3dde06a-tools7，版本变化使旧绑定不能匹配新审批。本轮后台尚未重载，新规则待统一更新服务后生效；不改变用户各客户端的观察/保护选择。

后续部署核对：2026-11-03 已统一重载日常后台，认证 API 实测规则版本为上述 0.7，存储 ready。更新前完整保留数据库没有有效待审批或单次授权；详见 release-readiness.md 的统一加载记录。开发测试与实际运行版本已对齐，但不等于所有真实客户端和未知变体验收通过。

## 2026-11-05：规则 0.8 / tools11 编码执行线索

对照 [PowerShell 官方参数解析器](https://github.com/PowerShell/PowerShell/blob/master/src/Microsoft.PowerShell.ConsoleHost/host/msh/CommandLineParameterParser.cs) 的 MatchSwitch、GetSwitchKey 与 EncodedCommand 分支，补齐 e、ec 和 encodedcommand 各前缀，以及 ASCII 单横线、双横线、斜线开关。本次读取文件 blob SHA 为 f58866123627f135542ad82d2f1daf500848a429；它是文件标识，不是版本兼容性保证。实现为自写词法规则，没有复制上游实现。

命中仍为 review，不因编码形式直接 deny；不解码、不执行内容。收紧程序名和参数边界，ExecutionPolicy、EncodedArguments、相似程序名不因新增模式命中。仅完整受限 literal_printf 可以消除该编码信号；管道、组合命令不享受豁免。普通引用、嵌套解释器仍可能误报；Unicode 横线、动态拼接、变量和完整 Shell 语义尚未覆盖，不能宣称全部变体已经拦截。

8 项工具覆盖、4 项字面量、19 项审批流程、46 项本机 HTTP 回归通过（共 77 项）。原 36 条开发样例保持 36/36，报告 .local/rule-evaluation-v08.json；不是独立准确率。策略版本 0.8-26b57465d9e5-tools11，旧版本授权不能匹配更新后动作。测试中的编码与命令均作为数据，没有执行其内容。
