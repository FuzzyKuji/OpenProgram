# 编写和检查 Workflow

Workflow 是一个小型 Python 包。`Agent` 实例定义角色，`Context` 对象定义每次模型调用看到什么，普通函数决定调用顺序。聊天里的 Agent 用普通文件工具编写 Workflow；你也可以按同样的形式手写，或者[录制一次演示](recording.zh.md)让 agent 做成 Workflow。包通过 `openprogram programs check` 后，它的入口就成为可调用的工具。

## 编码前明确合同

在包的 `README.md` 中写明：

| 项目 | 必需信息 |
| --- | --- |
| 目的 | 具体任务以及完成任务所需的证据 |
| 输入 | 入口参数、必需上下文和非法输入的处理 |
| 输出 | 返回类型、产生的文件以及如何验证成功 |
| 副作用 | 模型、工具、文件、网络和外部提交行为 |
| 失败与取消 | 失败或中断后保留什么；重试是否安全 |
| 依赖 | 导入的 Workflow、所需工具与服务 |
| 测试 | 行为验证、脚本化的模型回复和独立的在线验证 |
| 使用 | 一个可复现的调用以及预期结果 |

每个函数保持简短。明确处理预期的非法输入，让运行时的取消正常传播。

## 包结构

用户 Workflow 放在 `~/.openprogram/programs/<name>/`。目录名就是包名：小写的 Python 标识符，且不能与标准库模块或其他可导入的包重名。每个 Workflow 是独立的 Git 仓库。

```text
~/.openprogram/programs/project_report/
├── .git/
├── README.md
├── __init__.py
├── workflow.py
├── steps/
│   └── prepare.py
└── tests/
    └── test_workflow.py
```

包以自己的名字导入（`project_report`、`project_report.steps.prepare`）。包内相对导入和对其他 Workflow 的普通导入都可用。

## 角色、Context 和函数

一个包里有三类对象：

- **角色**是模块顶层创建的 `Agent` 实例，只保存配置：`model`、`instructions`、`tools`、`effort`。没有指定模型的角色使用调用方的模型。
- **Context** 在函数内构造，显式传给角色调用。
- **函数**是普通 Python 函数，负责调用角色、转换数据、分支、循环和调用其他函数。

```python
"""Prepare a project report from verified notes."""

from openprogram import Agent, Context

writer = Agent(instructions="You write project reports.")
reviewer = Agent(instructions="You check facts.", tools=[])


def project_report(notes: str) -> str:
    """Turn this week's project notes into a report."""
    ctx = Context({"notes": notes})
    draft = write_draft(ctx)
    return check(draft, ctx)


def write_draft(ctx: Context) -> str:
    """Write three sections: progress, problems, plans. At most three items each."""
    return writer("Write this week's report", context=ctx)


def check(draft: str, ctx: Context) -> str:
    """Only check that the draft matches the notes. Do not change the style."""
    return reviewer("Fix any mismatch and return the final text",
                    context=ctx.derive({"draft": draft}))


PROGRAM_ENTRIES = [project_report]
```

规则：

- 模型调用只通过角色。`role(prompt, context=ctx)` 用角色的工具运行一轮模型；`role.choose(prompt, {id: label}, context=ctx)` 返回其中一个选项 ID。Workflow 代码不调用自由函数 `llm()` 或 `agent()`。
- `PROGRAM_ENTRIES` 列出作为工具公开的函数。每个入口都要有 docstring（作为工具描述），每个参数都要有类型注解（作为工具 schema）。
- 不用装饰器、基类或分发表。一个 Workflow 通过普通 Python import 使用另一个。

## 一次模型调用看到什么

一次 `role(prompt, context=ctx)` 调用只发送以下部分：

| 部分 | 由谁定义 |
|---|---|
| 角色的 `instructions`，作为 system prompt | `Agent(...)` 实例 |
| 历史，默认为空，作为之前的消息 | `ctx` 的 `history` 设置 |
| 发起调用的 Workflow 函数的 docstring | 该函数 |
| `ctx` 的命名块，每块为 `name:` 加其值 | 构造或派生 `ctx` 的代码 |
| `prompt` | 这次调用 |

除此之外什么都不进入请求：没有聊天历史、没有召回的记忆、没有其他角色的输出，除非代码把它们放进 `ctx` 或 `prompt`。Context 不改变工具或权限；工具属于角色。

docstring 通过沿调用栈找到最近的、定义在 Workflow 包内的函数获得，只作用于这一次请求。没有 docstring 的函数不添加任何内容，所以只做数据转换的辅助函数可以不写。

### Context

- **块：**`Context({"notes": notes})` 或 `ctx["notes"] = notes`。
- **计算块：**`Context(providers={"today": lambda c: ...})`。provider 是同步可调用对象，每次调用时求值。
- **派生：**`ctx.derive({...})` 返回独立副本，函数可以增删块而不影响调用方的 `ctx`。
- **历史：**`Context(..., history=...)` 或 `ctx.derive(history=...)`：
  - `None`：没有历史（角色调用的默认值）；
  - `"thread"`：之前用同一个 `ctx` 对象发起的调用，适合一个角色的多轮工作；
  - `"chat"`：调用这个 Workflow 的对话；
  - 可调用对象 `(node, context) -> bool`，用来挑选对话节点。

要让模型知道这次调用在程序中的位置，可以加入 `openprogram.runtime.context` 的内置 provider：

```python
from openprogram.runtime.context import call_path, workflow_source

ctx = Context(providers={"call path": call_path, "program": workflow_source})
```

`call_path` 列出调用栈上的 Workflow 函数（例如 `project_report → check`；`call_path(docs=True)` 会附上每个 docstring），`workflow_source` 返回入口函数的源码。也可以直接写普通块，例如 `{"flow": "Draft first, then review."}`。

### 入口选项

可选的 `ENTRY_OPTIONS` 字典把入口名映射到工具选项，例如每个参数的表单说明：

```python
ENTRY_OPTIONS = {
    "project_report": {
        "input": {"notes": {"description": "This week's notes", "multiline": True}},
    },
}
```

`"run_in_worker": True` 让工具在 worker 进程内运行而不是 fork 子进程，适用于使用 worker 持有的状态（如浏览器会话）的入口。

### 重启后恢复

在入口上设置 `"resumable": True`，运行就能在 worker 重启或暂停后继续。可恢复入口内，每一段工作都用 `step(name, fn, *args)` 包起来：

```python
from openprogram.runtime.agent.durable_steps import step


def project_report(notes: str) -> str:
    """Turn this week's project notes into a report."""
    draft = step("draft", write_draft, notes)
    return step("check", check, notes, draft)


ENTRY_OPTIONS = {"project_report": {"resumable": True}}
```

- 每个 step 只运行一次，结果会保存。运行继续时，入口从头再执行；已完成的 step 直接返回保存的结果而不再运行，其中的角色调用不会重复。
- step 之外的代码会再次运行。它必须是确定性的、没有副作用，step 的名字和顺序要保持稳定。
- step 的参数和结果必须是 JSON 值。`Context` 不会跨重启保留，请在用到它的 step 内构造。
- 因 worker 重启而中断的运行，会在 `execution.auto_resume_window_seconds` 时间窗内自动继续；暂停的运行在聊天中继续。
- 一次运行绑定 Workflow 的提交。如果期间 Workflow 有改动，由 `execution.code_change_policy` 决定：`keep_original`（默认）以 "Workflow code changed" 停止运行，`use_latest` 用新代码继续。用新代码时，删掉或调换已完成的 step 也会停止运行。
- 可恢复入口必须是同步函数，且不能使用 `run_in_worker`。

## 执行参数由 Workflow 负责

用户描述任务、证据和交付物，不配置模型 ID、推理强度、迭代次数、超时、token 预算或重试次数，Workflow 也不向用户索要这些值。固定值写在角色上（`Agent(model=..., effort=...)`）或代码里。

当内部参数取决于任务时，在开始工作前做一次角色调用生成完整参数计划，在代码中校验（必需键、类型、范围、各上限之间的关系），规划失败时回退到完整且已校验的默认值。用户的明确约束和应用限制始终优先于模型输出。可恢复的 Workflow 会保存计划检查点，并在恢复时复用。

## 编写行为测试

`openprogram.programs._authoring.testing.script_roles` 用脚本化回复回答每个角色的调用，并记录每次请求；请求由与真实调用相同的代码路径构造：

```python
from openprogram.programs._authoring.testing import script_roles

from project_report import workflow as wf


def test_reviewer_sees_the_draft_but_not_the_writer_prompt():
    with script_roles({wf.writer: ["Draft"], wf.reviewer: ["Final"]}) as calls:
        assert wf.project_report("Shipped the parser.") == "Final"

    request = calls[wf.reviewer][0]
    assert "Do not change the style" in request.text      # check() docstring
    assert "Draft" in request.text                        # the draft block
    assert "Write this week's report" not in request.text
    assert request.history_text == ""
```

- 回复可以是字符串，也可以是任意可 JSON 序列化的值（用于带 `response_format` 的调用）。对 `role.choose` 的回复是选项 ID。
- 脚本里的异常会由调用抛出，并且留在队列中，所以也会回答模型循环的重试。
- `request.text` 包含 instructions、docstring、块和 prompt；`request.history_text` 包含历史。

工具、文件和服务照常用 `monkeypatch` 替换。在线 provider 验证不要放进 `tests/`，检查时无法运行。

## 检查、提交和列出

```bash
openprogram programs check ~/.openprogram/programs/project_report
openprogram programs check ~/.openprogram/programs/project_report -m "Tighten the review step"
openprogram programs list
```

`check` 会：

1. 在独立进程中导入包，校验 `PROGRAM_ENTRIES` 和入口签名；
2. 用 pytest 运行 `tests/`，可用时在操作系统沙箱内运行：无网络、包目录只读、`HOME` 是空的临时目录；
3. 全部通过后把改动提交到 Workflow 的 Git 仓库。`-m` 设置提交信息；`--json` 输出完整报告。

只有已提交且干净的包会加载。有未提交改动的包继续提供上次加载的版本，所以通过检查才会让改动可调用。历史和回滚使用 Git。

worker 监视 `~/.openprogram/programs`，改动后几秒内重新加载对应 Workflow，无需重启。`programs list` 把每个 Workflow 显示为一行 `package`，附状态：`loaded`（已加载）、`error`（加载失败，附错误）、`pending`（暂不可调用，附原因，例如有未提交改动）。Programs 页面在每个 Workflow 旁显示同样的状态。

## 运行 Workflow

- **聊天中：**每个入口都是一个工具。描述任务，Agent 会调用它。
- **Programs 页面：**打开 **Abilities → Programs**，在 **Applications** 下选择 Workflow，点击 **Use** 在聊天中打开参数表单。发送表单前不会运行。
- **命令行：**`openprogram programs run <entry> -a key=value`。
- **Python：**入口是普通的可导入函数。

每次入口调用都记录在会话图中，每次角色调用是一个子节点，保存模型收到的完整请求。普通函数不记录。
