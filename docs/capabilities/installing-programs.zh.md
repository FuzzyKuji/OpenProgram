<div id="harness"></div>

# 安装程序

`openprogram programs install` 从本地目录、git URL 或 GitHub `owner/repo`
把一个程序包加入 OpenProgram。已安装的程序显示在 **能力 → Programs →
Applications** 下，是一个以目录名命名的文件夹，里面列出它注册的 Agent 入口。
release 本身不捆绑任何程序：除内置工具和应用外，你使用的每个程序都是用这种方式安装的。

新克隆放进你的 Programs 目录 `~/.openprogram/programs/<name>/`
（命名 profile 下为 `~/.openprogram-<profile>/programs/<name>/`）。
早期安装器克隆进源码树（`openprogram/programs/packages/` 或
`openprogram/programs/applications/`）的检出，会在 worker 第一次以新版本启动时
移进 Programs 目录，名字和登记的来源保持不变。

> **agent 在哪里读取本文档：** 本文件是规范流程。
> 当用户要求安装某个 agent 尚未拥有的程序时，请遵循
> 下面的步骤——它们被写成可逐步执行的形式。

<div id="tldr"></div>

## 主要行为

```bash
openprogram programs install https://github.com/<owner>/<repo>   # git URL
openprogram programs install <owner>/<repo>                      # GitHub 简写
openprogram programs install ~/work/my-program                   # 本地目录
openprogram programs install file:///path/to/checkout            # 本地 git 来源

openprogram programs list                          # 每个 Program 及其状态
openprogram programs install <source> --upgrade    # 拉取最新提交
openprogram programs uninstall <name>              # 把克隆移到 .removed/

# 运行中的 worker 会拾取克隆；新进程在启动时加载它。
```

这些命令需要可变环境：source-development checkout 或 CLI/server 安装。
packaged desktop runtime 是 immutable 的，会拒绝 `programs install` 和
`programs uninstall`。

---

# 第一部分 —— 安装程序

## 来源可以是什么

| 来源 | 会发生什么 |
|---|---|
| git URL（`https://`、`ssh://`、`git@`、`file://`） | 浅克隆到 `~/.openprogram/programs/<name>/`，然后检查其内容（见下文）。 |
| GitHub `owner/repo` | 展开为 `https://github.com/owner/repo`，按同样方式克隆。 |
| 本地应用目录（`application.json`） | 登记进目录文件，从原处加载，不复制任何文件。 |
| 本地包仓库（`__init__.py` 和 `.git`） | 像 git URL 一样克隆进 Programs 目录。需要先提交；不是 Git 仓库的目录会被拒绝。 |
| 已在 `~/.openprogram/programs/` 中的包 | 无需安装；`openprogram programs check <directory>` 让它可调用。 |

## 克隆会成为什么

克隆之后，OpenProgram 检查检出内容，并按它包含的东西登记。一个仓库可以同时包含其中几种。

1. **包（package）**——克隆根目录有 `__init__.py`。克隆按仓库名取一个合法的导入名
   （`My-Tools` → `my_tools`）。检出干净且已提交时，它作为你的包加载；
   `PROGRAM_ENTRIES` 与 `openprogram programs check` 见[自编程工作流](workflows/README.zh.md#self-programming-workflows)。
2. **应用（application）**——克隆中有 `application.json`。应用会登记进目录文件
   （见[应用](applications.zh.md)）。`--trust` 授权运行已审查的 Python 后端，
   `--replace` 接受已登记应用变化后的 digest。
3. **harness**——克隆中有 `<package>/agentics/__init__.py`（见第二部分）。
   OpenProgram 从它的 `pyproject.toml`/`setup.py`（优先）或 `requirements.txt`
   安装 harness 自身声明的依赖，然后把该目录登记为 owner 批准的来源。下次扫描时，
   registry 只导入已登记的 `<package>.agentics`，它们的 `PROGRAM_ENTRIES` 出现在
   chat、Programs 页面和 `openprogram programs run` 中。

三种都不是的克隆会被报告，不会从中加载任何东西；它绝不会破坏其他程序的加载。

防护机制：对于已存在的同名 **dev symlink**，`install` 会校验 harness 契约并登记该链接，
但不修改链接目标；同名且不是 Git 克隆的目录会被拒绝。对 symlink 执行 `uninstall`
只把链接移到 `.removed/`，不动它指向的检出。

## 升级与卸载

```bash
openprogram programs install <source> --upgrade   # git pull --ff-only，重新解析依赖
openprogram programs uninstall <name>             # 目录名或应用 id
```

用目录名执行 `uninstall` 会把克隆从 `~/.openprogram/programs/` 移到
`~/.openprogram/programs/.removed/`，需要时可以手动移回；它从不删除。用应用 id
执行时会注销该应用并保留数据，兼容的重新安装会恢复它。

<details>
<summary>手动等价方式（镜像 / 无法访问 GitHub）</summary>

```bash
git clone <repo-url> /path/to/Program-Name
openprogram programs install file:///path/to/Program-Name
```

安装命令把来源克隆进 Programs 目录并登记；自动发现只加载已登记且满足契约的目录。

</details>

## 开发者配置（开发你正在编写的程序）

从你的工作检出安装，再把它设为克隆的远程：

```bash
openprogram programs install file:///path/to/your/Program-Checkout
cd ~/.openprogram/programs/Program-Checkout && git remote add work /path/to/your/Program-Checkout
```

安装得到的是你检出的克隆；把提交拉进来（`git pull work main`），下次重启时生效。

## 校验一次安装

```bash
openprogram programs list          # 每个 Program（含 harness）及其状态
openprogram programs list --json   # 同样的行，JSON 格式
```

要查看一个存在但损坏的 harness 为何未加载：

```bash
OPENPROGRAM_DEBUG_REGISTRY=1 openprogram programs list
```
（Windows PowerShell：`$env:OPENPROGRAM_DEBUG_REGISTRY=1; openprogram programs list`）

然后就可以使用它——程序的函数像任何内置函数一样可调用
（在 chat 中，或 `openprogram programs run <fn> -a key=value`）。

## 平台说明

- **受支持的 CLI/server release 主机包括 macOS、Linux 和 Windows x86_64/arm64。**
  Windows Desktop 同时支持两种架构；Windows 沙箱命令执行使用可选的 WSL2 与 bubblewrap。
- **这些 Program 命令需要可变环境。** source-development checkout 可以使用；
  CLI release 仅在对应 release notes 明确支持 Program mutation 时使用。
  packaged desktop 在 Program 拥有隔离的外部环境前会拒绝这些修改命令。
- **受支持的可变环境无需 symlink**——安装器会把真实 checkout 登记到 Programs 目录。
- **程序在自身代码中仍可以是平台相关的**（例如，桌面自动化
  harness 可能只实现 macOS / Linux 后端）。
  在受支持主机上能否安装、每个函数能否运行，取决于程序声明的依赖和
  平台支持；需要检查它的 README。
- **编码 / 路径：** OpenProgram 自身的工具链全程基于 UTF-8 和
  `os.path`；一个表现良好的程序也应如此。

## 故障排查

| 现象 | 原因 / 修复 |
|---|---|
| 重启后 harness 函数没有出现 | 文件夹不匹配契约——确认 `<pkg>/agentics/__init__.py` 存在并导出 `PROGRAM_ENTRIES`。用 `OPENPROGRAM_DEBUG_REGISTRY=1` 运行。 |
| 安装时出现 `[!] … neither a package (__init__.py), an application (application.json) nor a harness` | 仓库三种形态都不是，不会从中加载任何东西。 |
| harness 自身依赖出现 `ModuleNotFoundError` | 安装其声明的依赖失败——重新执行 `openprogram programs install <source> --upgrade` 并检查错误。 |
| harness 内部的导入失败（`from <pkg>.x import y`） | package 目录的命名与导入根不一致，或缺少 `__init__.py`。package 文件夹名必须等于导入名。 |
| 现有 dev symlink 没有加载 | 运行一次 `openprogram programs install <Git来源>` 完成校验与登记；安装器不会修改链接目标。 |
| 程序在 Windows 上无法安装或运行 | 检查程序的 README 与 dependency marker。OpenProgram CLI/server 受支持，但单个程序仍可能只提供 macOS/Linux backend。 |

---

# 第二部分 —— 编写你自己的可安装 harness

任何满足某一布局契约的仓库，都会成为每个 OpenProgram 用户的
一键安装项。

## 契约

```
<Harness-Name>/                      ← 仓库（任意名称）
├── pyproject.toml                   ← 只声明 harness 自身的依赖
└── <package>/                       ← 一个可导入的 package（ascii 名称）
    ├── __init__.py                  ← 保持依赖轻量
    └── agentics/
        └── __init__.py              ← 暴露 PROGRAM_ENTRIES = [...]
```

注册的入口点是 **`agentics` 子 package**——在启动时
OpenProgram 导入 `<package>.agentics`，并注册它的 `PROGRAM_ENTRIES`
列出的可调用对象。harness 根目录也可以附带（vendor）其他 package——
发现机制会找到带有 `agentics/` 子 package 的那一个，并将 harness 根
放到 `sys.path` 上，于是 harness 自身的绝对导入
（`from <package>.foo import bar`）就能解析。

## 最小可用模板

```python
# <package>/agentics/__init__.py
from openprogram import Agent


class ExampleAgent(Agent):
    method_options = {
        'my_tool': {'tool': True},
    }

    def my_tool(self, text: str = "") -> str:
        "一行：说明它做什么（会显示在目录中）。"
        return text.upper()


_example_agent = ExampleAgent()
my_tool = _example_agent.my_tool

PROGRAM_ENTRIES = [my_tool]
```

```python
# <package>/__init__.py
"""我的 harness —— 保持本导入轻量（见硬性规则 2）。"""
```

```toml
# pyproject.toml
[project]
name = "my-harness"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = []          # harness 自身的依赖——绝不要写 openprogram
```

这就是一个完整的可安装 harness。

## 两条硬性规则

1. **绝不要把 `openprogram` 声明为依赖**（无论在 `pyproject.toml`
   *还是* `requirements.txt` 中）。harness 在一个已存在的
   OpenProgram 安装内运行；一条声明的 `openprogram @ git+…` 会让 pip
   从 git 重新安装 host，从而覆盖用户本地的（通常是可编辑的）安装。
2. **保持顶层 `<package>/__init__.py` 依赖轻量，并在
   `agentics/__init__.py` 中为重量级导入做保护。** 发现机制在每次启动
   时都会导入 `<package>.agentics`，包括在那些尚未安装你的可选/重量级
   依赖的机器上——顶层导入 cv2/torch/等会破坏整个 registry 的加载。
   把重量级模块在函数体内做惰性导入，并为入口导入做保护：

   ```python
   # agentics/__init__.py —— 缺少依赖的机器不能破坏加载
   try:
       from my_package.main import my_tool
       PROGRAM_ENTRIES = [my_tool]
   except ImportError:
       PROGRAM_ENTRIES = []
   ```

## 发布前在本地测试

安装命令接受 `file://` 来源，因此可以针对你的本地检出测试完整的
用户流程：

```bash
cd /path/to/My-Harness && git add -A && git commit -m wip
openprogram programs install file:///path/to/My-Harness
openprogram programs list             # 应在 Harnesses 下列出 My-Harness
OPENPROGRAM_DEBUG_REGISTRY=1 openprogram programs list   # 函数是否出现？
openprogram programs run my_tool -a text=hello           # 冒烟测试
openprogram programs uninstall My-Harness                # 移到 .removed/
```

发布前的检查清单：

- [ ] `<package>/agentics/__init__.py` 暴露了 `PROGRAM_ENTRIES`
- [ ] pyproject/requirements 中没有 `openprogram`（硬性规则 1）
- [ ] 在只安装了 OpenProgram 的纯净 venv 中
      `python -c "import <package>.agentics"` 成功（硬性规则 2）
- [ ] 上面的 `file://` 安装往返测试通过

## 发布

推送到 GitHub。用户用以下命令安装：

```bash
openprogram programs install <owner>/<Harness-Name>
```

任何地方都无需注册——仓库 URL *就是*分发形式。
