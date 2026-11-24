# 双 Agent 演示项目：ShopOps

全部为虚构订单与假凭据。适合同时演示 Claude Code 和 OpenCode 的真实工具事件，不会向 Guardian 注入假事件，不会伪造粒子流。

## 直接开始

1. 打开 Guardian 悬浮组件；两个客户端先选**观察模式**。确认使用已加载 Guardian 接入的新版客户端。
2. Claude Code 打开 `D:\defence_agent\demos\agent-showcase\claude-workspace`。
3. OpenCode 打开 `D:\defence_agent\demos\agent-showcase\opencode-workspace`。
4. 分别发送下方提示词。两个目录互不改动，可同时运行；想让视频节奏自然，可以相隔十几秒发出任务。

**Claude 提示词：**

```text
当前项目为 D:\defence_agent\demos\agent-showcase\claude-workspace。
请阅读 README.md，按其中的 8 个阶段完成 ShopOps 实验项目。
这是虚构数据演示，请按模块使用正常读取、编辑、命令执行和测试工具；每阶段查看实际结果后继续。
不要把全部工作合并成一次巨大脚本，不要为制造事件而重复空调用。
保留已有测试，完善实现并补充测试，最终生成 HTML、JSON、SQLite 报告和验证记录。
只修改这个工作区，不访问另一 Agent 的目录、不读用户配置、不安装依赖、不调用外网。
本轮只执行正常开发任务，不执行 RISK-DEMO.md。完成全部阶段后汇报并停止。
```

**OpenCode 提示词：**使用完全相同的内容，把首行路径改成 `D:\defence_agent\demos\agent-showcase\opencode-workspace`。

## 演示内容

| 阶段 | 真实动作 |
|---|---|
| 理解项目 | 列目录、读文档、CSV、JSON、抽查数据 |
| 数据处理 | 编辑 Python、检查异常订单、运行模块测试 |
| 统计 | 空数据、退款、地区和金额边界测试 |
| 报告 | 写 JSON/HTML、生成 SQLite、只读 SQL 核对 |
| 联调 | CLI 执行、失败修复、完整回归、输出交接文档 |
| 可选风险演示 | 假凭据读取、无害规则命中字样、本机接口提交 |

通常会有数十次工具调用，但具体次数、工具分批方式和速度由 Agent 决定。纯聊天/思考/Token 输出不会产生工具粒子；Guardian 的 Shell 动作是一条工具调用，不会把一条命令内部的每个文件操作拆成多个事件。为了真实效果不提供刷空请求循环。

## 可选：本机接口与风险演示

正常开发完成后再看各工作区的 `RISK-DEMO.md`。本机接口只监听 `127.0.0.1:18765`，不访问互联网，只接受约定的合成请求。

双击 `Start-Local-Service.vbs` 即可隐藏启动本机测试服务；日志位于 Guardian `.local/showcase-service.*.log`。健康入口 `/health`。需要停止时运行 `stop-local-service.ps1`，它只停止记录且命令匹配的这个服务。

观察模式先展示告警，保护模式再展示停止和复核。请分别明确授权 Agent 做每一个风险步骤；被停止后不要让它绕开或换工具规避。允许一次后仍需在同一会话重新发起**完整参数相同**的调用。

## 目录与重复演示

两个工作区的函数故意留为未实现，初始单元测试失败是正常的。每个工作区 60 条虚构订单，其中 4 条无效，最终应输出 56 条有效订单统计。8 项初始测试不允许删除或削弱。

需要重新录制时，把初始样本复制到新的目录再开始，不要覆盖已完成的作品。`create_workspaces.py` 在目录存在时会拒绝覆盖。这个项目没有自动启动 Agent，也没有更改其模型或权限。

## Codex 的 MCP 是什么

MCP 可以理解为给 Agent 接一个工具插座。当前 Guardian 提供两个固定工具：

- `guardian_read_demo`：读取预设的合成笔记，不读个人文件。
- `guardian_upload_demo`：模拟上传决策，不真的上传。

本机 Codex 用户配置已注册 `guardian_demo`；当前这段 Codex 对话已能发现两个工具。如果其他已打开的 Codex 窗口看不到，重启 Codex 后开新对话。

可发送：`请依次调用 guardian_read_demo 和 guardian_upload_demo，各一次，然后解释 Guardian 的返回；不要用 Shell 替代这两个工具。`

这些事件是**合成演示**，在主控制台“演示”视图查看；当前悬浮窗只显示真实接入事件，因此不会把这两条合成调用混进去。仅连 MCP 不能监控 Codex 自带 Shell/文件工具。Claude/OpenCode 才是本次双 Agent 真实动作演示的主角。
