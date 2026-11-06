<div id="agentic-workflows"></div>

# 智能体工作流

这一页介绍 agentic workflow：如何安装、聊天 Agent 如何替你编写，以及如何管理和触发。如果你想直接用而不是自己写函数，从这里开始。

## 是什么

Agentic Workflow 是用 [Agentic Programming](../agentic-programming/README.zh.md) 写成的成品工作流——代码里叫 **harness** 或 **agentic program**：一个自包含的 git 仓库，里面是一组 `Agent` method。release 不捆绑任何 workflow；用 `openprogram programs install` 安装你需要的。安装后的 workflow 注册进 OpenProgram，像内置函数一样出现在聊天、Web UI 的 Programs 页和 `openprogram programs run` 里。

## 管理命令

```bash
openprogram programs list          # 每个 Program：工具、应用、你的包、harness
openprogram programs install <owner>/<repo>   # 任意 harness（git URL 或目录亦可）
openprogram programs install <ref> --upgrade  # 重装 / 升级
openprogram programs uninstall <Harness-Name> # 移开一个 harness
openprogram programs run <name> -a key=value  # 直接运行一个 program
```

`programs run` 还接受 `--provider`（openai-codex / gemini-cli / anthropic / openai / gemini，默认自动探测）和 `--model` 覆盖模型。

在可变环境（源码检出或 CLI/server 安装）中，`programs install` 会克隆 harness、安装其声明的依赖并登记批准的来源。packaged desktop runtime 拒绝安装 Program。

`openprogram programs list` 把 `~/.openprogram/programs` 中的每个 Workflow 显示为一行 `package`，附入口和加载状态：`loaded`（已加载）、`error`（加载失败）或 `pending`（暂不可调用，例如有未提交改动）。

<div id="self-programming-workflows"></div>

## Agent 替你编写的 Workflow

聊天 Agent 可以为你编写可复用的 Workflow。当任务需要稳定的多阶段结构、会被反复使用或需要可审阅的版本历史时，才值得写成 Workflow。Agent 能直接完成的一次性任务不需要。

没有专门的编写工具。Agent 使用普通的文件工具和命令行：

1. 把 `~/.openprogram/programs/<name>/` 建成 Git 仓库并写好包：角色、函数、`PROGRAM_ENTRIES`、`README.md` 和行为测试。
2. 运行 `openprogram programs check ~/.openprogram/programs/<name>`。检查会导入包、在操作系统沙箱中运行测试，通过后提交。
3. 失败时读报告、修改包，然后再次检查。

运行中的 worker 会在几秒内加载已提交的 Workflow，它的入口随即作为工具出现在所有聊天和 Programs 页面中，无需重启。修改 Workflow 也一样：改文件，再检查。早期版本保留在 Workflow 的 Git 历史中。

## 用哪种方式触发

- **Web 参数表单**：点击 Programs 中的 **Use** 或侧栏收藏。新标签页变成草稿聊天；已有聊天保留草稿和执行中的任务。填写任务要求后明确发送。打开或关闭表单不会执行 Workflow。
- **聊天里**：入口函数以 `as_tool=True` 注册为工具，直接用自然语言描述任务，模型会调用它（如已安装的 `owner/paper-harness` 中的 `paper_agent`）。操作应用、内置浏览器 Page 和虚拟机用的是 [`computer_use_agent`](../computer-use.zh.md) 工具，不是 workflow。
- **命令行**：`openprogram programs run paper_agent -a task="调研 agent 记忆的近期工作"`。
- **Python 里**：harness 的函数就是普通可 import 的 Python 函数。

## 模型选择

正文不调用模型的 Program 可以在未配置模型时执行。模型或凭据不可用时，在正文调用 Runtime 才报错；不调用模型的步骤可以执行，也不会自动选择其他 provider。

直接运行工具时，内部模型调用同样需要明确的 provider 和 model。缺失或不完整的选择不会使用全局 provider 检测或 provider 的默认模型。

从聊天执行时，Workflow 的内部模型调用继承当前轮次的 provider 和 model。请求 override 优先于会话选择，再使用 agent profile。该选择同样传入工具子进程。所选模型的 provider 认证仍需有效；初始化失败时保留所选模型的错误，不自动改用其他 provider。

浏览器 workflow 在选择 backend 时保留明确传入的初始 URL。官方 MCP backend 支持受取消检查约束的等待，并传递 snapshot 失败。页面恢复保留当前窗口范围，不重复执行失败的动作；确认完成的结果保留实际证据和观察到的目标。

## 编写你自己的

任何满足目录契约（`<package>/agentics/__init__.py` 暴露 `PROGRAM_ENTRIES`）的仓库都能被同一条 `programs install` 命令安装。契约、最小模板和发布流程见[安装程序](../installing-programs.zh.md)。

Harness 契约与 `~/.openprogram/programs` 中的单个 Workflow 包不同。包结构、完整测试示例和 `programs check` 命令见[编写和检查 Workflow](authoring.zh.md)。聊天 Agent 编写的 Workflow 经过同样的检查。想把一件事演示给 agent 看而不是用文字描述，可以[录制 Workflow](recording.zh.md)。

Workflow 表单只询问任务信息，不要求配置执行设置。文本润色在同一次模型请求中根据文本判断风格，不强制用户选择。浏览器 backend 和会话标识保留为内部参数。文档页码和输出位置属于可选的任务要求。显式 Python 调用仍支持受支持的覆盖值。

## 周报

如果 Workflow 目录已安装 `weekly_report`，可以直接提供周报内容或修改要求。例如：“提交本周周报：……”；“只修改本周周报的下周计划，其他字段不变”；“只查看本周提交记录”；“不要提交，把草稿写到 reports/weekly_report.md”。

它先读取配置的飞书表单，核对姓名和年份、周次。没有记录时新建提交一次；已有可编辑记录时，从提交历史打开并保存。部分修改保留未指定的字段。明确要求草稿或只读检查时不会提交。检查结果不明确、登录失败或记录无法唯一确认时停止；达到提交次数上限不等于已有记录不能编辑。

只有观察到新的成功提示并核对保存内容后才报告完成。写入结果不明确时直接说明，不自动重试。浏览器原有授权要求保持不变。流程使用有次数与时间限制的浏览器步骤，不使用 `goal()` 循环，也不编造进展、指标或论文名称。

### 组长周报草稿

`group_weekly_report(task)` 主动从记忆、相关本地文件和微信查找范围、材料与作者证据，生成未发送草稿。缺字段不再提问，未核实作者与不可用来源写入限制。显式 `source: "supplied"` 只使用所给材料。来源选项见[每周报告](reports.zh.md)。

完整且显式只用输入材料的结构化核对由代码完成，不调用模型。汇总按成员限制模型上下文，核验来源引用并保留不确定项。本地文件保存到 `reports/group-weekly/<week>/<unique-run>/`（或 `output_dir`）。未找到材料不等于未提交。请核对草稿后自行发送。
