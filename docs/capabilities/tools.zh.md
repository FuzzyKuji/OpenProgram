# 内置工具

工具审批行为及运行中切换请参见[工具权限模式](permissions.zh.md)。

OpenProgram 自带一批注册为工具的函数，模型在聊天里直接调用。这一页按 `openprogram/programs/tools/` 目录逐个列出：每个工具做什么、需要什么 key 或本地依赖。大多数工具零配置；需要 key 的集中在网络检索和图像两类。

## 文件与代码

| 工具 | 做什么 | 需要什么 |
|---|---|---|
| `read` | 读文件内容 | 无 |
| `write` | 新建或整体覆盖文件 | 无 |
| `edit` | 文件内字符串替换 | 无 |
| `apply_patch` | Codex / OpenClaw 格式的多文件结构化 patch | 无 |
| `list` | 列目录内容 | 无 |
| `glob` | 按文件名模式找文件 | 无 |
| `grep` | 内容搜索，优先 ripgrep，缺 rg 回退 Python re | 无（装 `rg` 更快） |
| `semble_search` / `semble_find_related` | 语义 + 词法代码搜索，返回排好序的代码块 | 每个受支持的 release 已包含；source developer 通过锁定的项目环境安装 `search` extra |
| `lsp_diagnostics` / `lsp_references` / `lsp_definition` | 从 language server 拿类型检查错误、真实调用点、真实定义位置，见[Language server 工具](lsp.zh.md) | Python 装 `pyright`，TypeScript 装 `typescript-language-server`（缺哪个工具就报哪条安装命令） |

### 文档版本

对于 Word、PowerPoint、PDF、图片等二进制文件，模型可以先生成独立的临时结果，再调用 `write(file_path="/absolute/final.docx", source_path="/absolute/staged.docx")` 写入最终文件。`source_path` 与文本 `content` 只能指定一个。来源必须是本地普通文件，最大 64 MiB。覆盖已有目标前须先读取；二进制读取返回文件信息，并建立与文本读取相同的内容变更检查。

在会话中写入时，系统将修改前后的完整字节保存到这一轮的文件历史。重新打开会话或重启应用后，记录仍然存在。撤销和重新应用使用保存的版本；文件后来被修改且发生冲突时，不会覆盖后续内容。新建文件也能撤销，不要求项目文件夹是 Git 仓库。

完整版本保留格式和嵌入媒体，但当前 Review 不比较文档排版，也不显示 Word 修订标记。直接覆盖最终文件的普通 shell 命令不会成为本轮精确修改记录。过去未记录的版本无法根据文件卡片或命令输出补建；脚本应生成独立结果，再通过 `write` 写入最终文件。

后续历史提交失败时，之前已发布的版本仍完整保留。写入后尚未记录结果就中断时，文件历史显示结果未确认，并禁止精确恢复；不推断成功，也不把它当作没有修改。历史损坏会阻止继续记录写入，不会覆盖为空记录。首次尝试失败后，重新读取当前文件再重试。版本随所属轮次保留，并沿用现有历史保留策略。新增本地文档生成器复用 `source_path` 发布接口，无需另建版本存储。

通过项目文件编辑器进行的手动修改也会保留修改前后的完整字节，独立于会话历史。每次成功写入立即发布；同一编辑器的连续修改最多合并为五分钟的一条版本，结束分组或发现外部修改时另建版本。恢复历史版本会新增记录，并检查当前文件版本后再覆盖。项目磁盘断开时仍可读取已保存的历史；写入和恢复需要项目位置可用。项目位置变化后，恢复使用登记的新位置。文档 API 接受不超过 64 MiB 的二进制内容，但这并不代表每种二进制格式都已提供编辑界面。


项目文件默认打开预览。加载时居中显示资源准备和文档打开状态；加载期间关闭文件会取消待加载的编辑器，初始化失败后可以重试。支持的 UTF-8 文本文件可以选择“编辑”，修改会自动保存，也可以按 Ctrl/Cmd+S 立即保存。预览与编辑之间切换会保留编辑器的撤销记录。“历史”可查看保留版本修改前后的内容，并恢复选定版本。保存失败或磁盘文件被其他程序修改时，草稿会保留，可以重试、导出或明确选择丢弃。关闭文件会等待待保存修改完成；保存失败时标签保持打开。聊天附件使用同一预览窗口，以只读方式打开。

PDF 预览支持翻页、缩放和文本搜索；搜索前 500 页，更长的文档会明确显示这个范围。PSD 预览显示 8 位 RGB 文件保存的合成图和图层名称，TIFF 预览显示首页。这些解码器最多接收 64 MiB，并限制渲染图像大小。常见图片默认打开预览，音频和视频使用浏览器播放控件，编解码器支持取决于浏览器。损坏或不支持的文件仍可下载原文件。查看历史版本时使用该版本保留的字节。解码器资源保存在本地，打开对应格式时才加载。这些预览模式不编辑 PDF、PSD、TIFF、音频或视频文件。

Office 支持是内置应用 **ONLYOFFICE**（`office_editor`），也是演示文稿、文档和表格共用的可选本地组件，默认 App 和运行环境不附带它。在**应用**页面停用这个应用后，打开 Office 文件会说明编辑器已关闭，只提供原文件下载，不会安装或下载任何内容。未安装时打开 Office 文件会显示“安装”和“取消”，只有选择“安装”才开始下载。下载约 699 MiB，包含 ONLYOFFICE 资源、字体、许可证和源码材料，文件在本机处理。安装先校验固定版本压缩包和全部资源，再选择完整版本；失败可以重试，已有安装保留。安装成功后自动打开当前文档，无需重启 App。取消后仍可下载原文件，也可通过“安装选项”重新选择。通过远端访问应用时，本地 Office 编辑器不可用。PDF 预览不依赖这个组件。DOCX、PPTX、XLSX、ODT、ODP 和 ODS 在文件窗口中直接以可编辑状态打开，没有单独的预览/编辑切换；原生编辑器进入可写状态后即可修改，修改自动保存。切换标签、分栏或历史时保留当前编辑器及其原生撤销记录。关闭前会等待尚未提交的输入和文件写入；写入失败时保留文档供重试。历史版本只读预览，恢复版本会新建一条保留记录。旧 DOC、PPT、XLS 可以明确转换为新路径下的 DOCX、PPTX、XLSX，原文件保留，已有目标不会被覆盖。附件保持只读，编辑器无法加载时仍可下载原文件。这些窗口不提供 Office 内容修订差异视图。

静态 PNG、JPEG 和 WebP 支持编辑，可裁剪、旋转、绘图、添加形状和文字。修改通过文档历史控制器自动保存；切换预览、历史、标签或页面时保留原生撤销与重做记录。写入失败会保留可编辑草稿供重试，关闭前等待导出完成。转换为 PNG 会创建独立文件，已有目标不会被覆盖。动画 PNG/WebP 和 16 位 PNG 保持只读。编辑最多接收 64 MiB、1600 万像素，单边不超过 16384 像素；不支持或损坏的文件仍可下载原文件。图片编辑导出渲染后的像素，不承诺保留嵌入元数据。附件和历史预览保持只读。

同一个“历史”界面汇总该项目相对路径下的手动修改和已确认的模型修改。模型版本直接读取原会话 checkpoint 保留的修改前后字节，不另建会话副本。恢复所选版本只修改这一个文件，检查当前版本后新建一条手动历史记录。归档会话保留文件历史；彻底删除会话后，其模型版本不再可读。手动历史独立保留。旧会话历史分批索引，点击“继续加载历史”处理下一批；尚未完成或无法核实的历史会明确标注。旧路径只有能够确认项目归属时才会汇总。项目移动不改变新记录的文件历史身份；磁盘离线时可读取保留版本，恢复需要项目位置可用。

## 执行

| 工具 | 做什么 | 需要什么 |
|---|---|---|
| `bash` | 执行 shell 命令，返回输出和退出码；等待时间到了还没跑完的命令会作为会话继续运行 | 无 |
| `write_stdin` | 对 `bash` 留在后台的会话：等待更多输出、中断它，或往里输入 | 无 |
| `execute_code` | 在独立子进程里跑 Python 片段 | 无 |

`execute_code` 返回 stdout、stderr 和已观察到的退出码。非零退出或超时返回错误结果，部分输出仍可用于检查失败原因。只有零退出码表示成功。每次调用使用新的 Python 子进程。

### 继续运行的命令

`bash` 最多等 `yield_time_ms`（默认和上限都是 30000 毫秒，下限 250 毫秒）让命令跑完。按时跑完的命令返回输出（stdout 和 stderr 合在一起）和 `Process exited with code N`。到时还在运行的命令转到后台继续运行，结果写明 `Process running with session ID <id>`，并带上到目前为止的输出。开发服务器、监听任务和耗时的构建都这样运行，不需要单独的启动步骤。

`write_stdin(session_id, chars, yield_time_ms)` 操作这个会话：

| `chars` | 作用 | 等待时间 |
|---|---|---|
| 空 | 不输入，返回新输出；命令结束后返回退出码 | 5000–300000 毫秒，默认 5000 |
| `"\u0003"` | 中断命令，相当于 Ctrl-C | 默认 250 毫秒 |
| 其他内容 | 原样输入给命令；一行结束要带 `"\n"` | 250–30000 毫秒，默认 250 |

要往命令里输入，会话必须用 `bash(..., tty=true)` 启动，命令会在伪终端里运行（本地 backend，macOS 或 Linux）。不带 `tty` 时命令的 stdin 是关闭的，等待输入的命令会直接结束而不是卡住，此时只接受中断。每次调用最多保留 1 MiB 输出，超出时保留开头一半和结尾一半。

后台命令自己结束、而且没有任何 `bash` 或 `write_stdin` 结果让 agent 看到这次退出时，对话会收到一轮通知，写明哪条命令结束了、退出码和最后的输出。对话正在进行一轮时，等这一轮结束再通知；你自己停止的命令不发通知。后台命令在 Resources 的 Terminal 分组里显示为“后台终端”，可以查看输出和停止，Activity 里也能看到。命令结束一天后，它的记录和输出会被删除；状态变为未知的命令，从那时起一天后删除。

一个对话最多同时运行 64 条命令。再启动一条时，会停止最久没用过的那条，但不会停最近用过的 8 条，结果里会写明停了哪条命令。取消一轮时，还在首次等待中的命令会被停止；已经在后台的命令继续运行。

等待会话输出或中断会话从不询问，因为命令已经由 `bash` 运行过了。往会话里输入按权限模式处理，和 `bash` 一样。

### 独立命令的执行目录

`bash` 每次调用都启动新的 shell。可通过可选参数 `workdir` 指定本次调用的起始目录，例如 `bash(command="npm test", workdir="apps/web")`。这是工具调用写法；普通 Python 导出的对象是 AgentTool，而不是直接执行 shell 的函数。

本地相对路径从当前绑定的 worktree 解析；未绑定时使用宿主进程目录，也支持绝对路径。路径按字面值处理，不展开 `~`、环境变量或 shell 表达式。省略 `workdir` 保留原来的 worktree／后端默认目录。某次命令里的 `cd` 或 `export` 不影响下一次调用；`workdir` 也不改变 worktree 绑定或文件工具的路径基准。

目录不存在、不是目录或未获授权时，不执行请求的命令，不自动创建目录，也不回退到其他位置。指定目录本身不授予访问权限。启用本地沙箱策略时，显式目录须符合原工作区的读写策略，包括符号链接和已有额外授权目录；执行仍受原沙箱边界约束。配置的沙箱不可用时，显式 `workdir` 不会绕过它继续执行。

SSH 和 Docker 在后端文件系统中按 POSIX 路径解释显式目录，不使用宿主文件系统解析远端路径。远端相对路径需要绝对 POSIX worktree 绑定。受保护的目录切换在目录不可用时阻止后续整个命令列表，Docker 不会通过 `-w` 自动创建指定目录。启用宿主沙箱策略时，在后端原生路径授权可用之前，显式远端 `workdir` 会被拒绝。省略该参数保留现有后端行为。

结果包含选择的本地起始 `cwd`；对于未独立观测规范位置的远端路径，显示 `requested_cwd`。这不是命令结束后的目录，也不表示 shell 状态持续。`bash` 不操作桌面集成终端，那是 `terminal_use` 的事。

## 网络

| 工具 | 做什么 | 需要什么 |
|---|---|---|
| `web_search` | 关键词 → 相关 URL 列表，多后端可选 | 见下方后端表 |
| `web_fetch` | 拉取 URL 并转成可读文本 | 无（装 `trafilatura` 抽取更干净） |

`web_search` 后端与 key（arXiv 与 DuckDuckGo 免 key，始终可用）：

| 后端 | 环境变量 |
|---|---|
| DuckDuckGo / arXiv | 无 |
| Brave | `BRAVE_API_KEY` |
| Exa | `EXA_API_KEY` |
| Firecrawl | `FIRECRAWL_API_KEY` |
| Google PSE | `GOOGLE_PSE_API_KEY` + `GOOGLE_PSE_CX` |
| Jina | `JINA_API_KEY` |
| Kagi | `KAGI_API_KEY` |
| MiniMax | `MINIMAX_CODE_PLAN_KEY`、`MINIMAX_CODING_API_KEY` 或 `MINIMAX_API_KEY` |
| Moonshot (Kimi) | `KIMI_API_KEY` 或 `MOONSHOT_API_KEY` |
| Perplexity | `PERPLEXITY_API_KEY` |
| SearXNG | `SEARXNG_URL`（自托管实例地址） |
| Serper | `SERPER_API_KEY` |
| Tavily | `TAVILY_API_KEY` |
| You.com | `YDC_API_KEY` 或 `YOU_API_KEY` |
| Ollama | 本地 Ollama（需 `ollama signin`），或用 `OLLAMA_API_KEY` 走 Ollama Cloud |

聊天中的 Web Search 开关控制本条消息能否联网搜索。模型提供商自带网页搜索时（ChatGPT 订阅与 OpenAI Responses API、Anthropic），模型直接通过提供商搜索：查询由提供商执行，对话里每次搜索显示一条"Searched the web"步骤和提供商报告的来源，回答下方附引用的页面；此时不提供本地 `web_search` 工具。其他提供商（包括 Gemini，它的搜索 grounding 不能和函数工具并用）则提供本地 `web_search` 工具，使用下表的后端。关闭开关后两者都不提供，自动工具模式也一样。开启后直接提供搜索工具定义，Tools 关闭时也可调用。开启仍遵守 Agent 禁用工具和权限设置。Tool profile 按会话保存，切换标签和刷新后保留。

新增搜索 key 在后续调用中生效，无需重启。默认后端不可用时使用其他可用后端；显式指定不可用后端则报错，错误说明原因（例如缺少的 key）并列出当前可用的后端。Jina 搜索需要 `JINA_API_KEY`。DuckDuckGo 读取其无 JavaScript 结果页，返回第一页结果（约十条）；遇到机器人验证或无法解析的页面时报错，而不是返回空结果。未指定提供商的搜索先试保存的默认后端，再依次试其他可用的网页后端（arXiv 只在指名时使用）；全部失败且没有配置任何 key 后端时，错误会说明在 Settings > Search 配一个搜索 key 即可解决。`combine="race"` 返回首个非空成功结果；`providers` 中无法运行的后端会被跳过，全部无法运行时错误逐个列出原因；`combine="rrf"` 保留截止时间前完成的结果。全部失败返回错误，与成功但无结果区分；已开始的请求按各自传输超时结束。

## 桌面

| 工具 | 做什么 | 需要什么 |
|---|---|---|
| `computer_use_agent` | 操作屏幕：在后台操作应用窗口（截图 + Accessibility 树）、内置浏览器的 Page，或已配置的虚拟机。可单步、批量、写 Python 代码，或交给按简报工作的新 agent；每个应用审批一次 | 应用：macOS（运行时需有辅助功能与屏幕录制权限），X11 下装有 AT-SPI 和 xdotool 的 Linux，或带 UI Automation 的 Windows。虚拟机：`computer_use.vm_url` |

[操控电脑](computer-use.zh.md)列出了全部目标、动作和审批范围。

## 图像与 PDF

| 工具 | 做什么 | 需要什么 |
|---|---|---|
| `image_generate` | prompt → PNG 存盘 | 任一后端：OpenAI（`OPENAI_API_KEY`）、Gemini（`GEMINI_API_KEY` 或 `GOOGLE_API_KEY`）、fal（`FAL_KEY`） |
| `image_analyze` | 描述图片 / 回答关于图片的问题（本地路径或 URL） | 任一视觉模型 key：OpenAI / Anthropic / Gemini（复用已配置的 provider key） |
| `pdf` | 从 PDF 抽取文本，支持 offset / limit 翻页 | 完整 release 已内置（`pypdf`） |

图像工具在所选 Provider 不可用、调用失败或图片无法保存时返回错误结果。`mixture_of_agents` 在模型引用未知、所有参考调用失败或汇总失败时也返回错误结果。部分参考调用失败但得到有效回答，或成功回答的文本包含 Error 字样时，结果仍然是成功。普通 Python 的 `execute(...)` 调用保持字符串返回值。

## 会话与协作

协作分四个域，一词一义，见
[agent 协作](../reference/design/runtime/collaboration/agent-collaboration.zh.md) §1。

| 域 | 工具 | 做什么 | 需要什么 |
|---|---|---|---|
| 未完成事项 | `open_work` | 这个对话里 Agent 仍欠你的事，每一轮都显示在指令中（[未完成事项](agents.zh.md#未完成事项)） | 无 |
| 计划 | `todo_create` / `todo_update` / `todo_list` | 会话规划清单：手写的计划清单（建条目、设状态/负责人/依赖、按状态分组列出）。写一条不会启动任何东西；网页界面把计划显示为[任务清单](../interfaces/web.zh.md#任务清单)，位于修改它的那一轮回复下方 | 无 |
| 执行 | `list_jobs` / `job_output` | 列出本会话的后台任务，等待或查看结果。结果读取检查派发会话和祖先任务的所有权 | 无 |
| 实体 | `agent` | 新建一个 agent 并取回回复，或用 `to=` 给已存在的 agent 派受管任务。`run_in_background=true` 不阻塞、直接返回 job_id；`start_from` 决定新 agent 从哪起（`clean` / `inherit` / `SID:MSG_ID`）；`archive_when_done=true` 让它在任务结束、结果回流之后自动归档 | 无 |
| 实体 | `list_agents` | agent 列表：有哪些 agent、它们的名字、地址、体量和忙闲（`scope="archived"` 看已归档的） | 无 |
| 实体 | `archive_agent` | 把活干完的 agent 归档：它从 `list_agents` 消失，并拒收后续 `send_message` / `agent(to=)` 投递；`read_conversation` 照读它的历史，`agent(start_from="SID:MSG_ID")` 照 fork。归档不中断在跑的工作、不删数据，所以任何会话都能归档任何 agent；归档单向，没有反归档 | 无 |
| 通讯 | `send_message` | 跟已存在的 agent 说话，按 `"SID:HEAD"` 或名字寻址。不产生任务、不产生 job_id、没有东西可取消，所以任何 agent 都能发。`message` 留空并设 `notify_when_idle=true` 时什么都不发，等这个 agent 下次空闲时收到一条带它最新回复的通知 | 无 |
| 通讯 | `read_conversation` | 把任意 agent 的历史读成纯文本（含工具调用），可指定轮次范围和字数预算 | 无 |

后台 agent（`run_in_background=true`、`agent(to=)` 或 `send_message`）结束或失败时，派它出去的会话会收到一个通知回合，标明这是自动通知，不是你发的消息。会话正在跑回合时，通知等那个回合结束再到；这期间结束的所有 agent 合在同一条通知里。已经用 `job_output` 读过的结果（它也能按 `delivery_id` 等 `send_message` 的回复），或空闲的 `notify_when_idle` watch 已经交回的回复，不再通知；被取消的 agent 也不通知。通知和调用方的上下文里只带 agent 的任务和最终回复，不带它的完整记录；需要看过程时，调用方用 `read_conversation` 去读。发给仍在忙的 agent 的消息先排队，等它空下来再执行。

协作消息额度耗尽后，`job_output` 仍可用；读取已有结果不消耗该额度。新的 Agent 投递仍须遵守相应上限。取消任务使用它的执行控制；API 取消使用 `execution.command`，设置 `action="execution.cancel"` 并传入当前执行版本。当前工具目录没有 `job_stop`。

| 工具 | 做什么 | 需要什么 |
|---|---|---|
| `program` | 调用任意已注册的 `Agent` method | 无 |
| `mixture_of_agents` | 并行问N个模型再综合;默认从模型注册表选,每个provider取一个 | 模型注册表里至少2个provider |
| `ask_user_question` | 向用户提 1–N 个带选项的问题 | 需要交互前端；输入基础设施不可用、问题数组无效或无交互上下文时返回工具错误 |
| `chat_send` | 往这通对话所在的聊天里发一条消息。在 [ambient 群](../integrations/channels.zh.md#群聊行为)里，这是 agent 开口的唯一方式；其他时候用来在长时间干活前发一句短话，最终回复照常发出。一轮最多 5 条 | 聊天渠道的对话（Telegram、Discord、Slack 或微信）；其他地方不提供 |
| `enter_plan_mode` / `exit_plan_mode` | 进入 / 退出计划模式 | 无 |
| `canvas` | 往 markdown 文件的具名块里增量写入；`set` 的 `content=""` 清空正文，省略内容则返回错误 | 无 |
| `memory_*` | 读取持久记忆工作区——`memory_search`（按语义或确切字符串找）、`memory_get`（看有什么；读一个文件、章节或段落；或读脚注引用的那条聊天消息），以及 `memory_update` 用来新增或更正记录。没有记录对话的工具：那件事在后台完成。每个实例只有一份工作区，所有agent、所有对话（含聊天渠道）共用（见[聊天渠道](../integrations/channels.zh.md#谁能和你的机器人说话)）。 | 无 |
| `worktree_*` | git worktree：`worktree_create`（也可直接从 PR 开 worktree，传 `pr="123"` / `"#123"` / GitHub PR 链接，走 `gh`）/ `merge` / `discard` / `list` / `keep` | git |
| `cron` | 登记周期性 agent 任务 | 无 |
| `list_mcp_resources` / `read_mcp_resource` / `list_mcp_prompts` / `get_mcp_prompt` | 把 MCP 的 resources / prompts 原语暴露给模型（`mcp_meta` 目录） | 已配置的 MCP server（见 [MCP](mcp.zh.md)） |
| `tool_search` | 按需加载延迟工具；下一次模型请求包含其完整 schema | 无 |
| `help` | 按名字读取工具指南（`help("self_update.prepare")`），传工具名时读取该工具的概览 | 无 |
| `self_update` | 从隔离 worktree 安装对 OpenProgram 自身的已提交修改，并跟进构建、验收、回退和修正。动作：`status`（默认）、`prepare`、`retry`、`cancel`；`prepare` 和 `retry` 总是请 owner 审批。见[升级](../install/upgrade.zh.md#恢复对话内自更新) | macOS 上的 OpenProgram 源码 checkout |

规则较多的工具保持 schema 简短，在调用需要时把其余说明作为*工具指南*交给模型。`computer_use_agent` 对某个目标的第一次结果、`self_update` 的第一次结果，开头就是该工具的指南，并按名字列出更多指南。需要某份尚未看过的指南的调用——例如第一次 `self_update(action="prepare")`，或第一次带 `code` 的 `computer_use_agent` 调用——会被拒绝一次，拒绝结果里附上指南，下一次调用即可执行。指南只在仍处于对话上下文中时才算看过，所以压缩之后需要时会重新送达。

已注册的 `canvas` 对明确的校验、依赖和进程失败设置错误标记。成功的 Canvas 正文即使以 `Error:` 开头也保持成功。普通 Python `execute()` 调用仍返回字符串。
