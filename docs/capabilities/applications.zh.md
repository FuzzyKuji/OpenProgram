# 从新标签页打开应用

侧栏 **Applications（应用）** 页面把内置和已安装的应用列在同一张表里：图标、标题、版本和作用范围，以及一句话说明。用 **全部**、**内置**、**已安装** 筛选。应用有自己的窗口时，该行有 **打开**；每行都有启用开关和 **⋯** 菜单：**在能力中显示**、**从新标签页隐藏**（或 **在新标签页显示**）、**从来源更新**（显示来源目录）和 **卸载**（会先确认，保留应用数据）。**安装…** 打开安装表单，安装 Python 后端或声明 `files.project.write` 能力的应用需要明确勾选信任；**从来源更新** 打开同一个表单并填好来源，请审查来源后再提交。**能力 → Programs** 的 **Applications** 下也列出这些应用，连同内置应用和没有界面的已安装程序；内置工具列在 **Tools** 下。和 Tools 一样，Applications 是普通的文件夹视图：每个应用目录一个文件夹，用目录名命名（`browser`、`calculator`、`auto_research`），按字母排序。展开文件夹显示它真实的子文件夹和源码文件；位于某个已安装包内的应用就是那个包的子文件夹，例如 `auto_research/app`。应用的调用逻辑是它注册的所有 Agent 入口的并集，例如 `browser` 的 `web_use`。选中一个应用，显示与应用页相同的图标、标题和说明，以及目录名、类型和版本；有窗口时有 **打开**，只有一个 Agent 入口时有 **在对话中使用**；启用开关；Agent 可调用的入口及各自的一句话说明；位置、窗口、权限等详情。工具则列出它的参数。Agent 不能调用的应用用一行说明：仅界面的应用只作为窗口打开，只为其他 Program 导出 Python 函数的包是 Python 库。调用逻辑折叠在最下面，摘要给出简短计数，展开后是调用树和图。包里的源码文件直接显示调用逻辑。

应用也是 Program，用 `openprogram programs` 管理。应用目录可以放在你的 Programs 目录 `~/.openprogram/programs/<name>/` 里，也可以放在任何别的地方。注册保存在 `~/.openprogram/programs/catalog.json`：每条记录应用的源目录及其启停、隐藏和显示名设置；应用从源目录加载，不复制任何文件。运行时为应用保存的内容（业务数据、运行记录、Python 环境）在 `~/.openprogram/programs/.runtime/`。

安装后的应用会与文件、新建对话、浏览器、终端一起出现在新标签页。点击名称打开应用自己的界面，再次打开会选中同一个实例。关闭标签页不会取消后台操作。

应用界面使用标准 HTML、CSS 和 JavaScript，也可以提供 Python 业务操作。界面不必使用 OpenProgram 组件。前端依赖需要打包到本地，资源和 JavaScript 模块导入使用相对路径。应用运行在独立 opaque origin 的 sandbox iframe 中，不能读取宿主页面、直接调用宿主 API、加载远程脚本、嵌套其他页面或提交导航表单。资源 URL 只授权按打开时的内容摘要读取该应用的 UI 目录，不是宿主凭据。

## 安装与打开

在本地 OpenProgram worker 运行时执行：

```bash
openprogram programs install /absolute/path/to/application
openprogram programs list
```

`install` 记录这个目录，应用从这里加载，所以目录要留在原处。`list` 直接读取注册表和各个源目录，不需要 worker；每个应用一行，显示 id、状态（`enabled`、`disabled`、`error`）、加载目录和 Agent 条目及其暴露层级（应用条目为 `deferred`）。`openprogram programs list --json` 以 JSON 输出同样的行，每行带一个 `tiers` 映射。

直接放进 `~/.openprogram/programs/` 的应用目录不需要 `install`：worker 下次扫描该目录时会自动登记。需要信任的应用（见下文）在用 `--trust` 安装之前显示为 `needs trust`。`openprogram programs check DIRECTORY` 校验 manifest、包内文件和后端声明的操作，不登记任何内容。

Python 后端以当前操作系统用户执行受信代码，`files.project.write` 允许这些代码在绑定项目中创建和替换文件。检查源码和依赖后，使用 `--trust` 授权运行：

```bash
openprogram programs install /absolute/path/to/application --trust
```

`openprogram programs disable ID` 移除应用的界面、资源、服务和 Agent 条目，并取消活动操作；`openprogram programs enable ID` 重新加载它。内置应用 `browser` 同样适用：`openprogram programs disable browser` 会移除浏览器服务和 `web_use`，直到再次启用；`openprogram programs disable workflow_recording` 会移除[录制 Workflow](workflows/recording.zh.md)：输入框的 **录制 Workflow** 和录制路由。内置应用 `office_editor`（**ONLYOFFICE**）在文件窗口中打开 Word、Excel 和 PowerPoint 文档；`openprogram programs disable office_editor` 关闭它，这些文件随后只提供原文件下载。这两个应用都有自己的窗口，在它们那一行点 **打开**，或在新标签页点它们的图块即可打开。ONLYOFFICE 窗口可以在当前项目根目录新建空白文档、表格或演示文稿，并列出项目里已有的 Office 文档；Workflow Recording 窗口不经过输入框直接开始录制。内置应用 `meeting`（[会议](meetings.zh.md)）录下这台电脑上的通话，转写后在新对话里总结；`openprogram programs disable meeting` 关闭它。**应用**页面把它们列为内置应用，各自的启用开关与 `enable`、`disable` 作用相同。这个设置保存在 `catalog.json` 里，worker 重启后依然有效。工具（`bash`、`read`、`goal` 等）总是提供给 Agent，不能停用。含应用的 git URL 或 GitHub `owner/repo` 会被克隆到 `~/.openprogram/programs/<name>/` 并同样登记（`openprogram programs install owner/repo --trust`）。

插件不能带代码：添加工具或自带界面的 Claude Code、Codex、OpenCode 或 Hermes 包要作为应用安装（加一个 `application.json`），见[插件](plugins.zh.md)。

新标签页获得焦点时和每十秒刷新应用列表。项目级应用在打开时绑定当前选中的项目，之后切换对话项目不会改变已经打开的实例。没有当前项目时会复用唯一的已有绑定；首次使用或有多个绑定时提供项目选择，也可以选择新文件夹。全局应用使用当前 owner 的同一个实例；不同项目的实例独立保存业务数据。

仓库包含[计算器](https://github.com/FuzzyKuji/OpenProgram/tree/main/examples/applications/calculator)和[PDF 编辑器](https://github.com/FuzzyKuji/OpenProgram/tree/main/examples/applications/pdf_editor)样例。PDF 编辑器读取、批注和重排所绑定项目里的 PDF 文件，只在你要求生成摘要时调用配置的模型。

## 应用定义与接口

包根目录中的 `application.json` 定义稳定 `id`、`title`、`version`、`scope`（`global` 或 `project`）、`dataSchema`、`ui`、可选 `description`、`icon`、`backend` 和 `operations`。完整 JSON 示例见[英文版](applications.md)。新标签页、应用页和“能力 → Programs”都显示 `title` 和 `description`：`description` 写成一句平实的话，单行，最多 300 个字符。没有 `application.json` 的 Program 包显示其 `README.md` 第一个 `# 标题`和标题下第一段的第一句；没有 README 时显示目录名。`icon` 决定新标签页、应用页、能力页和应用标签上的图标，可选 `calculator`, `book-open`, `file-search`, `file-text`, `file-pdf`, `telescope`, `notebook-pen`, `table`, `chart-column`, `database`, `image`, `music`, `video`, `map`, `calendar`, `globe`, `code`, `terminal`, `mail`, `message-square`, `list-checks`, `languages`, `pen-tool`, `palette`, `sigma`, `flask-conical`, `briefcase`, `bot`, `sparkles`；其他名字或不填时显示通用应用图块，颜色由应用 id 决定。`ui.root` 相对包根目录，`ui.entry` 相对 UI 目录。Python 和私有配置应放在 UI 目录之外。

Python 后端的 `module:object` 入口导出操作字典。操作接收 `(input, context)`，同步或异步返回 JSON 值；输入输出使用 JSON Schema 校验。声明 `agent: true` 的操作可以由 Program 客户端调用。`backend.dependencies` 使用精确固定版本，例如 `package-name==1.2.3`。每个应用的每组固定依赖对应一个 Python 环境，首次使用时创建，同时使用已安装宿主框架及其依赖。安装时在独立进程中检查后端；列出应用不会导入代码。

支持的宿主能力：

| 能力 | 授予后端 |
|---|---|
| `storage.app` | `context.load()` 和 `context.save()`：实例自己的保存状态 |
| `model.invoke` | 供 `llm()` 和 `agent()` 使用的 ambient Runtime |
| `files.project.read` | 在绑定项目内使用 `context.read_file(relative_path)` |
| `files.project.write` | 在绑定项目内使用 `context.write_file(relative_path, content)`；需要 Python 后端，安装时需要 `--trust` |

这些声明限制宿主 bridge，不限制受信 Python 代码的操作系统权限。

页面使用 `window.openprogramApp`：

- `load()` 返回 `{value, version}`，`save(value, version)` 只在版本仍匹配时保存，并发写入冲突后需要重新读取。
- `run(operation, input, requestKey)` 返回持久任务记录。重试相同请求时复用 request key，不同输入复用同一个 key 会被拒绝。
- `runs()` 列出最近任务；`status(id, after)` 返回状态、结果、错误、待回答问题和指定序号之后的事件。
- `cancel(id)` 取消任务；`answer(id, requestId, answer)` 回答当前问题。bridge 不能操作其他实例的任务。

Python 操作使用 `context.load()`、`context.save(value, expected_version=...)`、`context.progress(value)`、`context.ask(question)`、`context.read_file(relative_path)` 和 `context.write_file(relative_path, content)`。访问项目文件需要声明能力并绑定项目。`write_file` 接受文本或字节，路径相对项目根目录；解析后落在项目之外（包括经由符号链接）或指向 `.git` 的路径会被拒绝。它先在目标旁写临时文件，再改名覆盖目标，读者不会看到写了一半的文件，返回写入的 `path` 和 `bytes`。声明模型能力的操作可直接使用现有 `llm()`、`agent()` 和 ambient Runtime，模型凭据留在后端。应用提问使用 `context.ask()`；要求预声明持久等待点的 Runtime 工作流交互仍保留原有要求。

Program 调用同一套操作：

```python
from openprogram.programs._authoring.application_client import run, status
job = run("local.notes", "summarize", {"text": "..."}, request_key="summary-1")
print(status(job["id"]))
```

CLI 对应 `openprogram programs run APP OPERATION --input JSON`，项目级应用增加 `--project ID`；查看和取消使用 `openprogram programs status RUN_ID`、`openprogram programs cancel RUN_ID`。

## 数据与生命周期

应用从源目录运行。加载时宿主计算这个目录的内容摘要（忽略 `.git`、`node_modules`、`__pycache__` 和 `.venv`），页面和资源提供者按这个摘要识别打开的版本。worker 监视源目录：修改后应用以新摘要重新加载，重新打开的页面显示修改后的界面，新操作运行修改后的后端；修改前打开的页面或资源 `open` 带着旧摘要会被拒绝，需要重新打开。正在执行的操作继续执行。如果修改改变了 `dataSchema` 或 `scope`，或者给未经信任安装的应用加入 Python 后端或 `files.project.write`，应用停止加载，直到重新安装。在应用改为从源目录加载之前做的注册仍然有效：它们从记录的源目录加载，`~/.openprogram/programs/.runtime/versions/` 下复制的版本只在源目录不存在时使用。

业务数据与代码、对话分开保存，每个实例使用自己的 SQLite 状态，JSON 值上限为 4 MiB，单个事件上限为 1 MiB。执行状态使用现有 execution store；模型调用记录通过现有 session-node writer 保存到应用运行目录。

worker 停止会中断未完成的 Python 函数，重启后显示中断状态，不会自动恢复任意 Python 调用栈。应用应逐步保存进度，用户查看中断情况后明确启动另一次操作。当前版本拒绝改变数据 schema 或 scope 的升级，不提供自动迁移。

`openprogram programs uninstall APP` 移除菜单入口并取消活动操作，保留业务数据和注册的 schema/scope 兼容身份。重新安装兼容包可以恢复数据，不兼容的重新安装会在激活前被拒绝。owner API 的 `PATCH /api/applications/{id}` 支持 `enabled`、`hidden`、`display_title`；隐藏不取消任务，停用会取消。

独立部署、非 Python 后端、MCP Apps 兼容以及原生操作系统 GUI 窗口嵌入尚未实现。

项目应用在启动操作和读取项目文件前，根据绑定的项目 ID 重新确认当前位置。移动项目不改变应用实例和已保存数据；位置缺失、被其他目录替代或尚未确认时，拒绝启动新操作，已保存的应用数据仍可读取。

## 将应用作为资源使用

已启用应用自动出现在 `resource(action="describe")` 中，名称为 `application.<id>`。安装、禁用、更新和卸载无需重启 worker 即生效。

每个标了 `agent: true` 的操作同时是一个 Agent 条目，名为 `<id>__<operation>`，字母、数字、`_` 和 `-` 以外的字符换成 `_`（`local.notes` 和 `summarize` 得到 `local_notes__summarize`）。它把操作输入作为 `input`，项目级应用另有 `project_id`，等待执行结束后返回结果。条目需要审批，与 `resource` 工具一致，并且是 deferred 的：模型看到它们的名字，需要时用 `tool_search` 加载 schema。应用在某个对话里打开期间，它的条目在该对话里是 resident 的：每次请求都带上它们的 schema。仍在等待回答问题的执行会带着 id 返回，通过资源的 `status`、`answer` 或 `cancel` 继续。标了 `agent: false` 的操作没有条目。项目级应用的 `open` 接受 `project_id`，并将实例关联调用会话；正是这个关联让应用在该对话里算作打开。owner API 对窗口做同样的事：带 `session_id` 调用 `POST /api/applications/{id}/open` 建立关联，带 `instance_id` 和 `session_id` 调用 `POST /api/applications/{id}/close` 解除关联。`observe` 返回实例数据与最近执行；`act` 接受清单中 Agent 可见的操作及稳定的 `request_key`。使用 open 返回的 `instance_id` 与 `digest`，更新应用后旧 digest 会被拒绝。

`status`、`cancel`、`answer` 只处理属于该实例的执行。声明 `storage.app` 后，`save` 要求预期的数据版本。`release` 只移除会话关联，保留实例、数据和正在执行的操作；隐藏视图也不停止操作。Resources 和顶部标签复用同一实例及现有 sandbox 应用 frame，无需另外编写前端适配器。

通过 [framework 工具](framework-control.zh.md) 调用 `POST /api/applications/scaffold`，传入 `path`、`app_id`、`title` 可生成可运行的示例包。父目录必须存在，目标目录不能已存在。包中分别放置 `backend/operations.py`、`ui/index.html` 和 `application.json`，界面与 Agent 都调用声明的 read/save 操作。审查源码后，通过 `/api/applications/install` 传入源路径及 `trust: true` 安装。增加功能时同步扩展后端和操作清单，不要仅在前端事件中实现业务修改。
