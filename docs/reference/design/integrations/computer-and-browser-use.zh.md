# 操控电脑与浏览器

OpenProgram 给模型一个处理屏幕上所有事情的工具：`computer_use_agent`。它操作 macOS、Linux 和 Windows 上的应用，App 内置浏览器和无头 Chromium 里的网页，以及远程虚拟机。这份记录说明工具的形态、它如何只把需要的说明交给模型、点击目标如何变成屏幕位置、模型如何选择在当前上下文里做还是交给新 agent，以及底下的应用和浏览器后端如何实现。

## 给模型一块屏幕的三种做法

**Codex**（ChatGPT.app）只有一个执行工具，`cua_repl` MCP 服务里的 `js`：模型针对 `sky`（Mac 应用）和 `agent.browsers`（App 内浏览器、Chrome）写 JavaScript。知识放在三个 skill 里，`computer-use`、`control-in-app-browser` 和 `control-chrome`，每个约 3,200–3,400 token。上下文里每个 skill 只有一行；任务需要时模型自己去读 `SKILL.md`，浏览器 skill 还要它在 `js` 里运行 `documentation()` 取浏览器 API 参考。加载要花两三次模型调用，跳过阅读的模型就不知道 API。

**Claude Code** 有许多小工具：内置浏览器的 `navigate`、`read_page`、`find`、`computer`、`form_input` 等二十个左右，完整 schema 常驻上下文；用户自己的 Chrome 另有一组，以名字形式延迟加载，直到 `ToolSearch` 载入。每个参数都有 schema 校验，但两组同名动词容易选错，常驻的一组在每个对话里都占上下文。

**OpenProgram** 取 Codex 的单一入口和 Claude Code 的结构化参数：

- **一个工具。** `computer_use_agent` 是模型看到的唯一屏幕工具。它的 schema 很小，对每个目标都一样；动作及其参数放在各目标的指南里。
- **指南随第一次调用到达。** 工具说明只是目标清单。对某个目标的第一次调用返回该目标的指南和它当前的状态（已安装和运行中的应用、打开的网页），所以指南不需要额外调用，也不依赖模型记得去读。这些指南是[工具指南](../function/tool-guides.zh.md)，由 agent loop 而不是工具本身送达。
- **参数或代码。** 简单的步骤是结构化调用（`action` + `args`，或至多 20 个 `actions`）。带循环、条件或数据处理的步骤是一段 Python（`code`），在隔离解释器里运行，变量在调用之间保留。
- **由模型选择上下文。** `context: "inherit"`（默认）在当前对话里执行；`context: "fresh"` 启动一个干净上下文、带书面简报的 agent，只返回它的结果。
- **定位是显式的。** 点击目标是元素序号、网页 ref，或上一张截图的像素。

## `computer_use_agent`

### 形态

```
computer_use_agent(target, action?, args?, actions?, code?, timeout?, context?, brief?)
```

| 参数 | 含义 |
|---|---|
| `target` | `app`、`browser` 或 `vm`；三者总在 schema 里，本机到不了的目标会回答如何配置 |
| `action`、`args` | 一个步骤及其参数；省略时打开该目标 |
| `actions` | 同一目标上至多 20 个 `{action, args}` 步骤，遇到第一个错误即停止；状态只返回一次 |
| `code` | 在隔离解释器里运行的 Python（见“代码”） |
| `timeout` | 代码调用可运行的秒数，至多 120（默认 60） |
| `context` | `inherit`（默认）或 `fresh` |
| `brief` | 配合 `fresh`：目标、已知事实、限制和要交回什么 |

`action`、`actions` 和 `code` 互斥。参数由目标校验，出错时指出正确写法，因为 schema 不列出每个动作的参数。

### 目标与指南

| 目标 | 后端 | 打开时返回 |
|---|---|---|
| `app` | `openprogram/programs/tools/computer_use/computer_use_agent/desktop/`（macOS、Linux X11、Windows） | 给了 `args.app`：它的状态（树和截图）；否则应用列表 |
| `browser` | 操作 App 内置标签页的标签页驱动（见下文）；`args.browser` 为 `chrome` 或 `edge` 时，是连接到用户浏览器的扩展模式 Playwright MCP | 标签页列表 |
| `vm` | `computer_use.vm_url` 指向的 OSWorld 兼容服务 | 一张截图 |

每个目标有一份指南（`guides/<target>.md`；app 指南按 macOS、Linux、Windows 改写）：它的动作、参数、结果长什么样，以及确认策略。`tool.py` 把它们注册为工具指南：`computer_use_agent.<target>` 附在第一次操作该目标的调用结果里（`context` 不是 `fresh`）；`computer_use_agent.code` 是查阅型指南，带 `code` 的调用需要它，这样的调用先被拒绝一次并附上指南。指南是否已知取决于 agent loop 最近一次发出的请求，所以上下文压缩、工具结果被清理和 worker 重启都会让指南重新送达；fresh agent 的提示里已经带着带标记的指南，不会再收到第二遍。`action: "guide"` 和 `help("computer_use_agent.<target>")` 按需返回它们。

`app` 的动作就是下文应用后端的动作，参数相同；`browser` 的动作是标签页驱动的动作（`tabs`、`open`、`read`、`click`、`type`……，见[浏览器目标：标签页驱动](#浏览器目标标签页驱动)）。与 Codex 一样，先选浏览器，动作不随浏览器改变。不写 `args.browser` 是经由标签页驱动的内置浏览器；`chrome` 或 `edge` 是用户自己的浏览器，标签页驱动到达不了它。对这两者，`targets/browser.py` 把每一步交给 `workflow/browser/extension_browser.py`，它通过 `_SyncMCPClient` 运行 `@playwright/mcp --extension --browser chrome|msedge`（与 `web_use` 固定的版本相同），每个会话、每个浏览器一个服务器，在调用之间保持。服务器在该浏览器里打开带有其中继地址的 `chrome-extension://<id>/connect.html`，Playwright Extension 回连，并为用户共享的标签页中继 CDP；设置了 `computer_use.chrome_extension_token` 时，服务器传入 `PLAYWRIGHT_MCP_EXTENSION_TOKEN`，扩展不再询问直接连接。`tabs`、`read`（`tab` 为序号时会选中那个标签页）、`open`、`close`、`screenshot`、`upload`、`evaluate` 和日志映射到服务器的标签页、快照、截图、文件、evaluate 和日志工具；所有元素和指针动作都经过 `OfficialMCPPageBackend._action_call`，即 `playwright_mcp` 后端对 App Page 使用的同一套翻译。ref 是服务器快照里的 ref。代码模式不为用户的浏览器注册资源。

### 定位

步骤用两种方式之一指向目标，都原样交给后端：

| 给出 | 含义 |
|---|---|
| `element_index`（app）/ `ref`（browser） | 后端作用在元素上 |
| `x`、`y` | 该目标上一张截图的像素 |

虚拟机没有元素树，所以它的指针动作只接受 `x`、`y`。

### 代码

`code` 在 `computer_use_agent/sandbox/runner.py` 的常驻沙箱解释器里运行（macOS 上用 seatbelt，没有文件、网络和进程权限）。命名空间里有 `cu.app`、`cu.browser` 和 `cu.vm`；`await cu.app.click(app="Numbers", element_index=3)` 就是带这些参数的结构化步骤 `click`，由宿主经同样的目标代码和检查派发，每一步一条 effect 回执（`computer_use_agent/sandbox/broker.py`）。前导代码把每个动作在指南里的那一行作为对应 `cu` 方法的 docstring，所以解释器里可以用 `dir(cu.app)` 和 `help(cu.app.click)`。代码调用要指定 `target`，对 `app` 还要指定 `args.app`；审批覆盖这个应用，作用于其他应用的步骤会被拒绝。代码里不能用 `evaluate`，因为每段页面脚本都需要单独审批。一个解释器服务一次执行尝试，所以变量在本轮剩余时间里保留；失败或超时后解释器会被替换。每次调用最多运行 120 秒、100 步。代码模式需要 macOS 沙箱；在其他系统上代码调用会报告沙箱不可用。

### 上下文

`context: "fresh"` 通过通用的 `agent` 派生（`_agent_impl`，`start_from="clean"`）把任务交给一个干净上下文的 agent：同一会话、同样的模型和思考设置，结果作为这次调用的结果返回。它的提示是简报、一行指明目标（及 `args.app`）和该目标的指南。截图留在它自己的上下文里。派生深度限制让它不能再启动另一个。

派生出的 agent 无法请求审批，所以 `fresh` 调用替它带上：调用指定目标，对 `app` 还指定 `args.app`，并与直接调用走同样的审批。agent 运行期间，这次调用的确切规则被写成会话规则（已有时不重复写），agent 返回后删除，所以 agent 自己的调用能匹配它，而调用结束后不留下任何东西。

### 审批与访问

| 调用 | 审批 |
|---|---|
| `app`（`list_apps` 除外） | 按应用：规则 `computer_use_agent(<app>)`，在会询问的模式下必须；旧的 `computer_use(<app>)` 规则仍然匹配 |
| `browser` | 对话有 Page 时用本轮的 Page 授权；否则按权限模式；`evaluate` 在 bypass 下直接运行；其他模式询问，可选仅此一次或本对话 |
| 带 `args.browser` 的 `browser` | 用户的 Chrome 或 Edge，每个会话一次：规则 `computer_use_agent(browser:chrome)`（或 `browser:edge`），从不使用 Page 授权；`evaluate` 不随这项授权放行（规则 `computer_use_agent(browser:chrome:evaluate)`） |
| `vm` | 按服务地址：规则 `computer_use_agent(vm:<url>)` |
| `fresh` | 与它指定的目标相同 |

系统访问（辅助功能、屏幕录制）照常约束除 `list_apps` 之外的 `app` 调用。

### 模块布局

| 模块 | 作用 |
|---|---|
| `openprogram/programs/tools/computer_use/computer_use_agent/tool.py` | 注册的工具：schema、目标清单、路由、指南注册、审批原因 |
| `…/computer_use_agent/guides/` | 各目标的指南 |
| `…/computer_use_agent/targets/app.py` | 基于 `openprogram/programs/tools/computer_use/computer_use_agent/desktop/` 的应用动作 |
| `…/computer_use_agent/targets/browser.py` | 浏览器动作：标签页驱动（`browser` 服务的 `tabs`），或用户的浏览器（它的 `extension`） |
| `…/computer_use_agent/targets/vm.py` | 经虚拟机服务 HTTP API 的截图和 pyautogui 输入 |
| `…/computer_use_agent/code.py` | 基于 `computer_use_agent/sandbox/runner.py` 和 `sandbox/broker.py` 的代码模式 |
| `…/computer_use_agent/fresh.py` | 干净上下文的 agent |

没有单独的“规划 → 决策 → 执行 → 验证”循环：长任务交给使用同一工具的 `fresh` agent。

## 应用后端

### 形态

```
computer_use_agent(target="app", action, args={app, element_index | x,y, …})
```

动作分三组：

- **读取：**`list_apps`、`list_windows`、`get_app_state`（`include` = all / tree / screenshot，`window` 或 `window_id`）、`zoom`（以完整像素密度查看上一张截图的一块区域）、`find`（在上一棵树里按文字和角色查找）。
- **执行**，即 Codex 的目标 API：`click`（按钮、次数、按住的修饰键、按住时长）、`type_text`、`press_key`、`set_value`、`scroll`（按页或按像素）、`drag`、`perform_secondary_action`、`select_text`、`paste`；以及来自 Claude App `app_*` 一组的 `copy`、`focus`、`menu`、`show_window`；还有 `open_file`（macOS）。
- **多个步骤**（`actions`）：对同一个应用按顺序执行至多 20 个执行类步骤，遇到第一个错误即停止；最后只等待稳定一次、只返回一次状态。

只有 `list_apps` 免审批。`actions` 里的步骤不能指定别的应用，因为这次调用携带的审批只点名调用本身的应用。

每个执行动作的调用返回 `Done: <摘要>`，后面跟 Accessibility 树相对模型上次所见状态的 **diff**：`- 行` 是消失的元素，`+ 序号 行` 是新增或变化的。变化行数超过一半（且至少十二行）时改为返回整棵树，因为重建后视图的 diff 比视图本身还长。`get_app_state(full=true)` 按需返回全树。树上限 1500 个节点，每元素一行：序号、角色（`AXTextField` → `text field`，子角色放括号里）、标签、值、占位符、标记（`focused`、`selected`、`checked`、`disabled`、`secure`、`settable`……）以及除主按压之外的次级动作。有些应用给数字包上的双向文字标记会从渲染和 `find` 中去掉。

树覆盖窗口、它旁边的菜单、弹出框和对话框，以及只展开已打开菜单的菜单栏。未打开的菜单由 `menu` 动作读取，所以每次读取的范围一致，diff 里不会出现整条菜单栏凭空出现或消失。

没有改变任何东西的结果会被标记：`menu` 的列表、`copy` 和窗口本已可见时的 `show_window` 返回 `Report`，工具直接返回它，不等待稳定，也不再读取状态。

### 稳定序号

`tree.number` 参照窗口上一次的 `Snapshot`（不含序号的各行、它们的序号和下一个未用序号）分配序号。相同的行，或被同深度同角色的行替换（值变了、按钮改名），保留原序号；其他新行取下一个未用序号。被移除元素释放的序号永不复用。因此模型先前拿到的序号在其上方插入新元素后也不会指向别的元素——Codex 按位置编号做不到这一点。

### 等待稳定

动作之后，工具从 0.3 秒起每 0.2 秒对前 400 个元素取一次轻量指纹，两次指纹一致即停止；最多 1.5 秒，存在忙碌指示器或未完成的进度指示器时最多 5 秒——对应 Codex 的"约一秒，加载时最多五秒"。

### 菜单栏

`menu` 按标题遍历 `AXMenuBar`，不分大小写，忽略末尾的 `…` 或 `...`。路径停在子菜单时列出其菜单项，带快捷键符号（由 `AXMenuItemCmdModifiers` 得到 `⌃⌥⇧⌘`）、`[checked]` 和 `[disabled]`；末端项用 `AXPress` 按下。经 Accessibility 读菜单树不会在屏幕上打开任何东西。`copy` 按下应用自己快捷键为 ⌘C 的菜单项——按快捷键而非本地化标题查找——找不到时退回发送 ⌘C；该菜单项存在但被禁用（没有选区，或焦点在控件上）时立即如实报告。否则它等待粘贴板的 change count 变化，读出字符串，再恢复先前的粘贴板。

不带 `element_index` 的 `copy`、`press_key`、`type_text` 和 `paste` 作用于应用当前的焦点，不需要先 `get_app_state`；`menu`、`show_window` 和 `wait` 从不需要。来自 Claude computer-use 工具的有 `hover`（向进程投递三个逐步接近目标点的 `mouseMoved` 事件，再停留 0.8 秒；真实光标不动）和 `wait`（最多 10 秒，可取消，之后照常等待稳定并返回树 diff）。`focus` 设置 `AXFocused` 并最多等半秒让应用报告它，因为应用会在之后的 run loop 轮次才应用焦点。

截图是经 ScreenCaptureKit 抓取的窗口自身图像，缩放到长边至多 1568 像素；模型发来的坐标是这张图上的像素。每一步用生成截图的比例（Retina 屏为 2，大窗口按更小比例抓取时更小）和窗口服务器此刻报告的窗口原点把它换算成屏幕点（先 `_follow_window`，再 `screen_point`），所以用户在读取之后移动过窗口，点击仍落在模型指的位置。

### 截图上的文字

窗口自身遍历出的元素少于 12 个（窗框、标题栏按钮之外几乎没有）时，说明它绕开了辅助功能自行绘制。对这样的窗口，每次完整读取或仅截图读取都会对刚拍下的截图运行 Vision 的精确文字识别，把每行列成 `"text" at (cx, cy), WxH`，单位是截图像素，按从上到下、从左到右排列，最多 150 行。识别语言列表的第一项决定 Vision 用哪个模型，所以语言只作提示（用户首选语言，然后是中文、日文、韩文和英文），由语言检测按每张图选择。`find` 带 `text` 时，若没有元素匹配就退回到这些文字行；对不稀疏的窗口，它会以相同比例重新抓取并识别一次，因此位置对动作仍然有效。OCR 文字没有序号，也不进入树的 diff：它是坐标动作的依据，识别器失败时读取结果里就不带它。同样的读取还会列出不带文字的图标和控件（`ocr.detect_shapes`）：Vision 的轮廓检测跑两遍，一遍找浅色窗口上的深色图形，一遍找深色上的浅色，长边最多 1024 像素。相距 3 点以内的顶层轮廓合并成一个形状；形状盖住两个字符以上的识别文字行、短边小于 8 点、长边大于 80 点、长宽比超过 4:1，或贴着截图边缘（窗口的圆角和边框）时丢弃。单字符的文字行不排除形状，因为识别器常把图标读成一个字。两遍都找到的形状只保留一次，按 16 点一行、从左到右排序，最多 60 个。形状没有名字：模型对照截图分辨齿轮和垃圾桶。

### 音频

Codex 用 `start_audio_recording` / `stop_audio_recording` 录电脑声音（默认 60 秒，最多 300 秒），并把录音作为音频输入交给模型。OpenProgram 保留这两个动作及其上限。录音落成磁盘上的 WAV，再加上设置 → 语音引擎给出的转写文字，任何模型都能读。`ToolReturn.audio` 还把 WAV 作为 `AudioContent` 块带上：模型的输入模态里有 `audio` 时，Gemini 转换器把它作为内联音频、Chat Completions 转换器把它作为 `input_audio`，放在那组工具结果之后的用户轮里（工具结果必须连在一起）。由于 `tool` 消息只能放文字，Chat Completions 的这个用户轮也为视觉模型带上那组结果里的截图。Responses 和 Anthropic 转换器跳过音频块，工具结果里的媒体也不写进对话历史，所以对听不了音频的模型没有额外开销。`audio.py` 打开一个 `SCStream`，过滤器是只包含目标应用的显示器，要求 16 kHz 单声道 float 采样，排除 OpenProgram 自身进程，并只挂音频输出：2×2、每秒一帧的视频那一侧从不被消费。超过上限的采样被丢弃，计时器在上限后半秒停掉流，所以忘了停止的录音也会释放采集。每个对话同时只有一段录音；停止时转成 16 位 PCM 并保存在状态目录下，保留最新的 20 个。这个动作沿用按应用的审批：录音里只有所指定应用的声音。峰值始终低于 1e-4 的录音报告为静音，不做转写。没有窗口的应用没有 `SCRunningApplication`，无法录音。

### 模块布局

| 模块 | 职责 |
|---|---|
| `openprogram/programs/tools/computer_use/computer_use_agent/desktop/base.py` | 各后端共用的部分：`ComputerUseError`、`Report`、`Observation`、`AudioClip`、参数检查、录音保存 |
| `openprogram/programs/tools/computer_use/computer_use_agent/desktop/backends.py` | 按主机给出 `support()` 和 `backend()`：Darwin 用 `macos`，Linux 用 `linux`，Windows 用 `windows` |
| `openprogram/programs/tools/computer_use/computer_use_agent/desktop/keys.py` | xdotool 组合键解析为 macOS 键码和修饰键标志（`super+shift+z`、`ctrl++`、`KP_0`、单独修饰键） |
| `openprogram/programs/tools/computer_use/computer_use_agent/desktop/tree.py` | `Node`、渲染、签名、稳定编号（`Snapshot`、`number`）和 diff |
| `openprogram/programs/tools/computer_use/computer_use_agent/desktop/audio.py` | 单个应用的 ScreenCaptureKit 音频采集、采样上限、WAV 编码 |
| `openprogram/programs/tools/computer_use/computer_use_agent/desktop/ocr.py` | Vision 文字识别（Linux 上为 tesseract TSV）、识别框换算为截图像素、阅读顺序、语言提示、轮廓形状 |
| `openprogram/programs/tools/computer_use/computer_use_agent/desktop/skylight.py` | SkyLight 的 ctypes 绑定，用于后台指针和键盘路由 |
| `openprogram/programs/tools/computer_use/computer_use_agent/desktop/macos.py` | `MacComputer`：应用解析、窗口选择、抓图、树遍历、全部动作 |
| `openprogram/programs/tools/computer_use/computer_use_agent/desktop/linux.py` | `LinuxComputer`：同一接口，基于 AT-SPI、xdotool、Gdk 抓图和 PipeWire/PulseAudio |
| `openprogram/programs/tools/computer_use/computer_use_agent/desktop/windows.py` | `WindowsComputer`：同一接口，基于 UI Automation（comtypes）、窗口消息、`SendInput` 和 `PrintWindow` |
| `openprogram/programs/tools/computer_use/computer_use_agent/desktop/windows_audio.py` | 用 WASAPI 进程回环采集一个进程树的声音 |
| `openprogram/programs/tools/computer_use/computer_use_agent/targets/app.py` | `app` 目标：步骤校验、多个步骤、结果拼装 |

### 后台投递

元素动作走 Accessibility：`AXPress` / `AXConfirm` / `AXPick`，然后 `AXSelected`，然后聚焦，最后才在元素中心做一次指针点击；右键用 `AXShowMenu`；`set_value` 用 `AXValue`；`select_text` 用 `AXSelectedTextRange`（UTF-16 偏移）；`scroll` 先用翻页动作，再用滚动条的值，再用滚轮事件。

必须真实发生的指针事件（坐标点击、拖拽、滚轮）按开源 cua-driver 确立的配方投递：向目标进程序列号发一条不提升窗口的聚焦记录、一个 `mouseMoved` 预热事件、给事件打上点击状态、按钮、子类型 3、目标 pid、窗口 id 和点击组，`CGEventSetWindowLocation` 设定相对窗口左上角的位置（`window_location`：屏幕点减去窗口原点，单位为点，与 KWWK computer-use-core 和 cua-driver 的设法一致；AppKit 按事件的屏幕位置确定点击在窗口里的位置，测试窗口在这一项填相对窗口的点或屏幕点时，点击都落在同一处），`SLEventPostToPid` 送达。键盘事件附带 `SLSEventAuthenticationMessage` 以便接收进程接受；没有 SkyLight 时回退到 `CGEventPostToPid`。结果是应用把这次点击当成用户点击来处理，而真实光标留在原地、前台应用不变。

应用处理 mouse-down 时 AppKit 仍会把被点的窗口排到同层最前，所以坐标点击和拖拽之前先记下压在目标上方且与之重叠的其他应用窗口（前台应用自己的窗口除外），结束后按从深到浅的顺序对它们 `AXRaise`，窗口叠放顺序因此还原。

窗口由 `window`（标题子串或序号）或 `window_id` 选定；两者都不给时，模型上次读过的窗口只要还开着就保持选中，否则取焦点窗口或主窗口。每次状态都记下应用的窗口（窗口 id，没有 id 时用标题）；如果焦点窗口或主窗口是上次读取时还没有的，就改读它，并说明它盖在哪个窗口上，这样某一步弹出的对话框或文档就是后面步骤的操作对象。新出现的对话框类窗口（子角色 `AXDialog`、`AXSystemDialog`）或新的文件对话框，即使焦点仍留在它下面的窗口上也会被跟随；后台应用打开进程外的文件对话框时就是这样。

系统的打开/存储对话框带 `AXIdentifier` `open-panel` 或 `save-panel`，可能是窗口、`AXSheet`，或它下面那个窗口的子窗口。沙盒应用的对话框由 `com.apple.appkit.xpc.openAndSavePanelService` 绘制，窗口服务器把它列两次、边界相同：一次是服务进程在屏幕外的第 0 层窗口，辅助功能树在它那里；一次是应用在屏幕上显示它的窗口（`panel_hosts`）。应用里边界与之相同的窗口不论标识符如何都算文件对话框，服务那边的窗口报告应用窗口的 id，所以截图、`list_windows` 和 `window_id` 指的都是屏幕上的那个窗口。对话框和应用的连接还在时，应用把它列在自己的窗口里；应用不再列出一个仍在屏幕上的对话框时，按窗口 id 从服务进程的 `AXWindows` 取它的窗口，所以 `list_windows`、`window=<标题>` 和状态仍然能读到它。它的辅助功能元素可以访问，`AXPress` 和 `AXValue` 有效，SkyLight 路由的点击能送达，但发给应用 pid、发给服务 pid、或先无提升聚焦再发的按键事件都送不到，设置搜索框的 `AXValue` 也不会触发搜索。文件对话框是焦点窗口或在焦点窗口里、作为独立窗口存在、或在屏幕上而辅助功能够不到它时，`press_key`、`type_text` 和 `paste` 带着这个说明报错并指向 `open_file`，而不是把按键发给它下面的窗口；挂在另一个文档窗口上的 sheet 不影响发给焦点窗口的按键。读到对话框的状态会写明它是文件对话框、指向 `open_file`，并且总是附上 OCR 文字，因为文件浏览区不暴露行；读应用的其他窗口时，状态会说明有文件对话框开着。`open_file` 取代对话框：模态对话框会扣住打开文档的请求，所以它先按下已打开对话框的取消按钮（`AXCancelButton`，没有时找标题为取消的按钮）并等对话框关闭，辅助功能够不到对话框时报错并说明该点哪里；然后用关闭 `activates` 的 `NSWorkspace openURLs:withApplicationAtURL:configuration:` 让应用打开文档（需要时在后台启动应用），前台应用和它的窗口保持原位，然后等到一个 `AXDocument` 是该文件 URL、或标题含文件名的窗口出现。相对路径、不存在的路径、程序包和启动器（`.app`、`.command`、shell 脚本、`.workflow`、安装包、位置文件）、带可执行位的文件，以及终端应用（它们会运行打开的东西）都会被拒绝。最小化的窗口或被隐藏的应用仍然给出树；截图要等 `show_window` 取消最小化（`AXMinimized`）或取消隐藏应用后才有，这两者都不会激活应用。在另一个桌面空间的窗口就地读取和操作。`AXWindows` 只列当前桌面空间的窗口，所以应用里不在屏幕上、又没有被已列出窗口对应上的普通窗口（第 0 层，至少 80×60），用 SkyLight 的远程令牌查找：以 pid、`0`、`'coco'` 和元素 id 调用 `_AXUIElementCreateWithRemoteToken`，元素 id 从零开始试（最多 4000），直到每个窗口 id 都找到元素，做法同 AltTab；结果按应用缓存，直到这组窗口 id 变化。ScreenCaptureKit 能截这样的窗口，SkyLight 的指针通道也能送达，但不论走哪条通道，窗口服务器都会丢掉发给它的按键，所以在那里 `type_text` 和 `paste` 改为设置焦点元素的 `AXSelectedText`，`press_key` 报告按键送不到，`show_window` 说明窗口留在原桌面空间。窗口无法移动：macOS 14.5 起只有 Dock 能移动窗口（其他进程调用 `SLSMoveWindowsToManagedSpace` 需要放宽系统完整性保护，yabai 的文档写明了这一点）。

`paste` 写入粘贴板（纯文本，或用 `markdown-it` 从 Markdown 渲染出的 HTML），向目标进程发 Cmd+V，并在 change count 表明期间没有别人写入时恢复先前的粘贴板内容。

### Agent 光标

在一个点名元素或坐标的步骤执行前，`MacOSComputer.act` 先算出它落在哪里（元素的中心取自它的 `AXFrame`，截图坐标则按窗口原点和缩放换算），调用 `native_window_resources.note_action_point`，再等待 `CUE_LEAD_SECONDS`（0.15 秒），让光标先到。这个点以屏幕点为单位、原点在主显示器左上角，与 Electron 的坐标空间相同。worker 把它作为 `native.action` 帧广播（`session_id`、`x`、`y`、`sequence`、`at`、`action`、`app_name`）；agentic 子进程通过与被操作窗口相同的父进程通道转发（`kind: "action"`）。Web 客户端里 `native-window-store.ts` 在**显示操作**没有关闭时把帧交给 `openprogramDesktop.nativeActionCue`。桌面主进程（`main/worker/agent-control.js`）把它画进这个对话的控制提示层（见下）：光标滑过去并停在那里。每个 App 窗口都会收到这一帧，所以主进程按 `session_id`、`sequence` 和 `at` 丢掉已显示过的步骤。Linux 和 Windows 还不发出这些点。

### 窗口标识

被操作的窗口带有 macOS 的屏幕共享标识，与 Codex Computer Use 下一样：标题栏按钮上的徽标和菜单栏的共享图标。macOS 会给任何处在 ScreenCaptureKit 实时流下的窗口画这两样，所以 `window_watch.WindowWatch` 在它上面保持一个流。`MacOSComputer` 在每次 `act` 和每次指明窗口的 `get_state` 时，用窗口 id、应用名和标题栏按钮的位置（通过辅助功能读取）触碰它。流只过滤这一个窗口（`SCContentFilter.initWithDesktopIndependentWindow`），请求每秒一帧的 2x2 画面且不挂任何输出，因此不录下任何内容。每个会话最多监视一个窗口：转到另一个窗口会释放前一个，`IDLE_SECONDS`（20 秒）内没有步骤的窗口由清理定时器释放。打开流在单独线程上进行，失败被忽略，所以步骤不会因标识而等待或失败。

窗口被监视期间，另一个线程每 `REPORT_SECONDS`（0.12 秒）在有变化时上报它的位置：`window_place` 读取屏幕窗口列表，得到窗口的位置和 `GLOW_MARGIN`（32pt）范围内挡在它前面的窗口，标题为 `OVERLAY_TITLE` 的窗口（App 自己的提示层）不计入。上报经 `native_window_resources.note_control` 发出，归属取触碰窗口时记下的对话，帧类型为 `native.control`（`session_id`、`window_id`、`active`、`app_name`、`frame`、`buttons`、`occluders`）；子进程以 `kind: "control"` 转发。释放窗口时发出 `active: false`。Web 客户端在**显示操作**打开时把上报交给 `openprogramDesktop.nativeControl`，控制结束的上报总会交过去。桌面主进程为每个对话在窗口加边距的范围上放一个透明、点击穿透、不可聚焦的窗口，加载 `/menu-overlay/agent-control`，画出向内发光、按钮上的强调色红绿灯和光标。提示层在窗口层叠里紧贴在被控窗口之上（用窗口 id 调 `moveAbove`，每次上报都重新排一次，因为用户切换应用时层叠会变），所以挡在被控窗口前面的窗口也会挡住提示层；只有窗口服务器拒绝这样排序时，它才浮在所有窗口之上。两种情况下发光和红绿灯都会挖掉挡在前面的窗口，光标的落点在这些窗口下面时光标隐藏。外观见 [Agent 控制提示层](../ui/browser/agent-control-overlay.zh.html)。

### 拒绝

工具从不向 `AXSecureTextField` 元素输入，macOS 报告安全键盘输入（`kCGSSessionSecureInputPID`）期间也不输入，并拒绝以钥匙串访问、密码、loginwindow、SecurityAgent 和 OpenProgram 自身的 bundle 为目标。拒绝以错误返回并请用户来做这一步；任何审批范围都不能覆盖它。

### Linux 后端

`LinuxComputer` 保持 `MacComputer` 的接口，工具、服务端的应用查询和测试都通过 `backends.backend()` 驱动任一后端。它只在 X11 会话里运行：Wayland 下任何客户端都不能读取别的客户端的画面或向其注入输入，`support()` 会如实说明。

- **应用。** AT-SPI 桌面下拥有窗口的子节点，加上所属进程不接入无障碍总线的顶层 X 窗口。X 窗口的所属进程取 `_NET_WM_PID`；Xt、Motif 客户端不设置它时，取名称或可执行文件名以窗口 WM_CLASS 实例名开头的最新进程。每个应用按可执行文件或名称匹配桌面条目（`Gio.AppInfo`），由此得到标识（`org.gnome.Calculator`）、显示名，以及在 hicolor 主题里查到的图标。启动通过 `Gio.DesktopAppInfo.launch`，之后既等窗口也等应用的 AT-SPI 根节点，因为 GTK 4 应用在窗口映射之后才加入总线。
- **窗口。** 顶层窗口取窗口管理器的 `_NET_CLIENT_LIST`（用 `xprop` 读取），这样排除了 GTK 10×10 的 client-leader 窗口；没有客户端列表时，跳过 10×10 及更小的窗口。AT-SPI 的 frame 先按标题、再按尺寸与 X 窗口配对。不在已映射集合里的窗口报告为最小化；`show_window` 重新映射它。
- **树。** 角色是 AT-SPI 角色名（`push button`、`text`、`check box`），`role_name` 原样打印。子树在屏幕上时才读：GTK 3 设置 SHOWING，GTK 4 在窗口以下只设置 VISIBLE，所以窗口的子节点只要有一个报告 SHOWING 就按 SHOWING 遍历，否则按 VISIBLE。未展开组合框的弹出项和 GTK 的提示窗口跳过。无名的 filler、panel、section 是透明的。GTK 4 用类名给无名控件命名（`AdwGizmo`、`GtkMenuButton`），这类名字不当作标签。标志来自状态（CHECKED 或 PRESSED、FOCUSED、SELECTED、EXPANDED、非 ENABLED/SENSITIVE），`settable` 来自 EditableText 或 Value，`secure` 来自 `password text` 角色。次要动作是元素的 Action 名称中除 click、press、activate、toggle、jump、open、select 以外的部分。
- **后台的元素动作。** 点击执行元素的主动作；`set_value` 用 `EditableText.set_text_contents`、`Value.set_current_value`，复选框状态不一致时执行切换；`type_text` 和 `paste` 用 `EditableText.insert_text`（UTF-8 字节长度）在光标处插入并替换选区，换行执行输入框的 `activate` 动作；对输入框 `press_key Return` 执行 `activate`；`select_text` 用 `Text.set_selection` 或光标偏移（字符偏移，不是 UTF-16）；`copy` 读取 `Text.get_selection`，不经过剪贴板；按元素 `scroll` 把最近的滚动条的 Value 每页移动其长度的 90%；`menu` 遍历窗口的 `menu bar` 并执行叶子项的动作。`Component.grab_focus` 会让 GTK 把窗口提到前台，所以凡是必须移动焦点的地方，都会把焦点还给原先活动的窗口。
- **前台输入。** GTK 和 Qt 通过 XInput 2 读取指针和按键，会忽略用 `XSendEvent` 发给未聚焦窗口的核心事件，所以按坐标点击、拖拽、滚轮、悬停和按键都通过 XTEST 发送：先激活窗口（`windowactivate`；没有 EWMH 窗口管理器时用 `windowraise` 加 `windowfocus`），执行输入，再恢复指针位置和原先活动的窗口；`hover` 让指针留在原处。组合键用 xdotool 名称，`cmd`、`command`、`meta`、`win` 映射为 `super`，`option` 映射为 `alt`。
- **截图。** 对外部 X 窗口调用 `Gdk.pixbuf_get_from_window`，得到窗口自身按 X 分辨率的像素，长边缩到 1568 像素以内；最小化的窗口没有截图。截图像素通过 `xdotool getwindowgeometry` 给出的窗口位置换算为屏幕像素，与 AT-SPI 屏幕坐标用的是同一个参照系。
- **OCR。** 稀疏窗口（以及 `find` 的回退）用 `tesseract --psm 11 tsv`，语言取 eng、chi_sim、chi_tra、jpn、kor 中已安装的；置信度 30 以上的词拼成行。Linux 上不检测轮廓形状。
- **音频。** `pactl list sink-inputs` 给出每个音频流的 `application.process.id`；录音器轮询，直到出现该应用或其任一子孙进程的音频流（每次轮询都重新读取子孙进程，因为播放器通常是开始录音之后才启动的子进程），然后用 `parec --monitor-stream=<index>` 以 16 kHz 单声道浮点读取。读取持续到 parec 结束，所以停止时它还缓冲着的样本也会保留。PipeWire 下四分之一秒内就收到第一批样本；PulseAudio 的定时调度下，对一个音频流的首次监听会晚 1.2–1.7 秒开始，这段会丢失。
- **拒绝。** `password text` 元素、Seahorse、KWallet、gcr 弹窗、polkit 代理以及 OpenProgram 自身的条目。

app 指南在发送时按 Linux 改写（`targets/app.py` 的 `_LINUX_GUIDE`）：哪些步骤会把窗口切到前台、纯文本 `paste`、不经剪贴板的 `copy`、Linux 上的拒绝列表。`computer_use_apps` 的 WebSocket 回复带上 worker 的 `platform`；在 Linux 上，审批卡片对按坐标输入、拖拽、悬停和回车以外的按键（`needsForeground`）说明这一步会把窗口切到前台。

### Windows 后端

`WindowsComputer` 保持同一个接口。进程设为按显示器感知 DPI（`SetProcessDpiAwarenessContext(-4)`），所以窗口框、UI Automation 的边界和输入坐标都是物理屏幕像素。它调用的每个 Win32 函数都声明了 `restype` 和 `argtypes`，64 位句柄不会被截断。

- **应用。** `EnumWindows` 给出的可见、无所有者、非工具窗口且有标题的顶层窗口，按进程分组。UWP 外框（`ApplicationFrameWindow`）属于 ApplicationFrameHost，它的应用是子窗口 `Windows.UI.Core.CoreWindow` 所在的进程。已安装应用来自 `Get-StartApps`（桌面应用和应用商店应用都在，缓存一分钟）；运行中的进程按可执行文件或名称对应到一行，启动时运行 `explorer.exe shell:AppsFolder\<AppID>`，再等新窗口出现。
- **树。** 对窗口调用 `IUIAutomation.ElementFromHandle`，用控件视图遍历器遍历；屏幕外的子树跳过，菜单项除外。角色是控件类型（50000–50040）的小写名称（`button`、`edit`、`check box`）。没有名字、没有动作的 pane、group 和 custom 是透明的。标志来自模式：Toggle 状态、`IsEnabled`、`HasKeyboardFocus`、SelectionItem、ExpandCollapse、可写的 Value 或 RangeValue（`settable`）、`IsPassword`（`secure`）。值取自 RangeValue、Value 或 Text 模式的文档范围。次要动作是 expand、collapse、scroll、select，以及 LegacyIAccessible 里不是 press、click、invoke、jump 的默认动作。
- **后台元素动作。** 点击依次尝试 Invoke、Toggle、SelectionItem.Select、ExpandCollapse 和 LegacyIAccessible.DoDefaultAction，对输入框则是聚焦；`set_value` 用 Toggle、RangeValue、Value 或 LegacyIAccessible；`select_text` 按字符移动 Text 模式的范围；`copy` 读取 Text 模式的选区；按元素 `scroll` 用最近的 Scroll 模式按大步滚动；`menu` 遍历传统 `HMENU`（`GetMenu`）并投递 `WM_COMMAND`，或展开并调用 UI Automation 菜单项。
- **投递输入。** 按坐标的点击、拖拽、滚轮和悬停，以鼠标消息投递给该点下最深的子窗口（`ChildWindowFromPointEx`），用它的客户区坐标；第二次点击是 `WM_LBUTTONDBLCLK`。不带命名修饰键的按键，以 `WM_KEYDOWN`/`WM_CHAR`/`WM_KEYUP` 发给该线程的焦点窗口（`GetGUIThreadInfo`）；`type_text` 每个 UTF-16 单元投递一个 `WM_CHAR`。向传统 edit 或 rich edit 控件 `paste` 时发送 `WM_PASTE`。
- **前台输入。** 快捷键读的是 `GetKeyState`，投递消息改变不了它；UWP 外框、Chromium 和 Firefox 窗口读取原始输入。所以带修饰键的组合键、对这些窗口类的指针输入，以及其他情况下的 `paste`，都在 `_Forward` 里用 `SendInput`：它先接入前台线程的输入队列（`AttachThreadInput`）以便调用 `SetForegroundWindow`，执行输入，再把光标和原来的前台窗口还回去。
- **截图。** `PrintWindow` 加 `PW_RENDERFULLCONTENT` 把窗口（无论是否被挡住）画进一张外框大小的位图；从中裁出可见框（`DWMWA_EXTENDED_FRAME_BOUNDS`），用 HALFTONE 模式的 `StretchBlt` 缩到长边 1568 像素，再由 `GetDIBits` 取出 BGRA 行，`png_encode` 不借助任何图像库写成 PNG。最小化的窗口没有截图；`show_window` 用 `SW_SHOWNOACTIVATE` 还原它。
- **剪贴板。** `paste` 写入 `CF_UNICODETEXT`，md 和 html 还写入 "HTML Format"（头部偏移由 `cf_html` 计算），之后恢复原来的文字。
- **OCR。** 与 Linux 相同，装了 tesseract 时使用。
- **音频。** 对 `VAD\Process_Loopback` 调用 `ActivateAudioInterfaceAsync`，参数为 `PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE`，得到一个 `IAudioClient`，以共享回环模式初始化并自动转换为 16 kHz 单声道 float，在独立的 COM 线程上由事件驱动经 `IAudioCaptureClient` 读取。完成回调是 agile COM 对象，因为 Windows 在工作线程上调用它。
- **拒绝。** `IsPassword` 元素、CredentialUIBroker、consent（UAC）、LogonUI、LockApp、credwiz、keymgr 和 OpenProgram。

app 指南在发送时按 Windows 改写（`_WINDOWS_GUIDE`）；对组合键和粘贴（`needsForeground(args, "windows")`），审批卡片说明这一步会把窗口切到前台。

### 权限与审批

对 `app` 目标，`requires_approval` 对除 `list_apps` 外的每个动作返回 `computer_use_agent controls <app>`；带 `code`、`fresh` 或不带动作的调用按读取该应用审批。`parse_command` 把一次调用归约为规范化的应用名（虚拟机为 `vm:<url>`，浏览器没有），于是 `exact_rule_for_call` 得到 `computer_use_agent(calculator)`，`rule_to_string` 以常规形式打印。审批卡片提供四个范围：

| 范围 | 规则保存在哪 |
|---|---|
| once | 不保存 |
| session | 会话的 run config（`permission_rules.allow`）——`computer_use_agent` 在 `_SESSION_SCOPE_TOOLS` 里 |
| always | 项目规则 |
| deny | 不保存 |

这项授权只在会询问的模式下生效；Bypass 直接放行，Auto 交给自动审查。`permission_decision` 对 `app` 和 `vm` 目标把 `computer_use_agent` 当作按应用授权的工具（`_APP_GRANT_TOOLS`）：当工具自身的 `requires_approval` 表明这次调用需要审批、且没有允许规则点名该应用时，决定是 `ask`，理由 `APP_GRANT_REQUIRED`，因此在 Bypass 之外，无人值守的来源会拒绝这类调用；在会询问的模式下，允许规则是越过卡片的唯一途径。`_RULE_ALIASES` 让以旧名 `computer_use(<app>)` 保存的规则匹配 `computer_use_agent` 调用。`browser` 目标没有自己的规则：有 Page 的对话得到本轮的 `SURFACE_GRANT`，上传文件或打开本机之外的网站会询问。

权限规则在每个操作边界重新加载（全局 < 项目 < 会话），所以会话规则对下一次调用立即生效，无需重启。

系统访问：`computer_use:desktop` 同时是 `accessibility` 和 `screen_recording` 两项能力的操作；`_desktop_operation` 把除 `list_apps` 和 `guide` 外的每次 `app` 调用映射到它，于是缺少授权时调用进入标准的"等待"状态并走设置 → 系统访问流程；等待请求写明 `computer_use_agent`。

工具在 `DEFAULT_TOOLS` 里且常驻：schema 很短，不延迟加载。对话有 Page 时，`_configure_web_use_tools` 保留它并移除独立的浏览器工具；`web_use` 从不提供给模型。`unsafe_in` 在微信、Telegram 渠道和规划模式下隐藏它。

### Web 展示

`lib/computer-use/computer-use-agent-call.ts` 解读 `computer_use_agent` 调用：`appStepArgs` 把 `app` 调用变成应用渲染器接受的扁平步骤（`{action, app, …}`；多个步骤成为 batch，代码和 fresh agent 各成一个动作），`screenStep` 给出浏览器或虚拟机调用的动作。`tool-presentation.ts` 用显示器图标和 system 色调渲染 `app` 步骤；标题写动作和应用（"在 Calculator 中点击"），目标行在给了按键、文本、动作名或窗口时显示它们。浏览器调用显示动作和 URL，虚拟机调用显示动作，代码显示"在 <app> 中运行代码"，fresh agent 显示"交给新代理"及简报首行。审批卡片的范围按钮在"允许一次"和"始终允许"之间加入"允许此对话"，答案摘要打印"允许此对话"。早先工具（`computer_use`、`web_use`、`gui_agent`）记录的调用保留各自的渲染器，旧对话照常可读。

## 浏览器应用

内置浏览器是应用 `openprogram/programs/applications/browser/`。核心从不 import 它：应用的 `setup(ctx)` 提供服务 `browser`，核心里每个调用方都用 `_services.lookup("browser")` 查找它，查找返回 `None` 时就在没有浏览器的情况下运行。

| 模块 | 作用 |
|---|---|
| `__init__.py` | `PROGRAM_ENTRIES`（`web_use`）和 `setup`：提供服务，注册 L2 上下文段 `pages` 和资源 provider `web` |
| `service.py` | `BrowserService`，即服务的成员（见下） |
| `pages.py` | `BrowserResourceStore`、按对话的 Page 投影、资源控制、人的页面输入 |
| `tabs.py` | `computer_use_agent(target="browser")` 的标签页驱动 |
| `extension.py` | 经 Playwright Extension 操作用户的 Chrome 或 Edge |
| `chrome.py`、`privacy.py` | `openprogram browser` 维护的 Chrome 引导；隐私过滤 |
| `contract.py` | agent 和 MCP 共用的 `web_use` 参数契约 |
| `prompt.py` | 一次调用的 prompt 里关于已打开 Page 的段落 |
| `resource.py` | 资源 provider `web`，以及原生展示命令用的 Page 租约 |
| `web_use/` | `web_use` 运行时：页面控制器、会话及其注册表、恢复、精确页面 MCP 后端 |
| `engine/` | 页面控制器驱动的 Playwright 动作引擎 |

服务的成员是 `pages`、`tabs`、`chrome`、`extension`、`user_browser_names`、`web_use_parameters()`、`normalize_web_use_arguments()`、`execute_direct_web_use(arguments, owner_id=)`、`registry()`、`release_owner()`、`park_owner()`、`authorized_page()` 和 `browser_of()`。

没有这个服务时，每个调用方各自降级：调用的 prompt 里没有 Page 段落，turn 不会拿到 `web_use`；`web_use` 参数校验失败，报 "the browser is not enabled"；MCP 不列出 `web_use`，并拒绝对它的调用；`/api/web-use` 返回 `browser_not_enabled`；进程路由不列浏览器资源，浏览器控制返回 404；web tab 桥跳过 Page 记账；`computer_use_agent(target="browser")` 报告该目标不可用，桌面目标照常工作；权限策略看不到用户浏览器。

## `web_use` 运行时

`web_use` 是这个应用唯一注册的入口。程序和 MCP 客户端直接调用它；`computer_use_agent` 的 `browser` 目标则改用下面的标签页驱动。运行时位于应用的 `web_use/`，`contract.py` 里的参数契约由 agent 和 MCP 共用。

**名字。** agent 和 MCP 只看到一个工具 `web_use`；会话是 `WebUseSessionRegistry` 里的 `web_session_id`。HTTP 路由是 `/api/web-use`；`/api/computer-use` 作为隐藏的兼容路由保留，共用同一个处理函数，不出现在 OpenAPI 里，旧的 `computer_session_id` 请求字段会被换成新字段。

**五个命令。**

| 命令 | 作用 |
|---|---|
| `list_pages` | 列出所有已注册 OpenProgram 窗口的 Page，每个 Page 带一个一次性的 `page_context_token` |
| `observe` | 按 token 选中 Page、打开 WebSession，返回有界的文本、ARIA 和元素 ref |
| `act` | 针对最新的 `expected_frame_id` 执行一次 `navigate`、`click`、`type`、`press`、`scroll`、`hover` 或 `select` |
| `verify` | 执行运行时断言（`text_contains`、`title_contains`、`url_contains` 等）；模型声称完成永远不会让结果变成 `succeeded` |
| `close` | 关闭所观察 Page 的标签页，释放它的 WebSession、Page 绑定和持有的能力 |

```
web_use({ command: "list_pages" })
web_use({ command: "observe", page_context_token: "pct_…", arguments: { detail: "interactive" } })
web_use({ command: "act", web_session_id: "cs_…", arguments: { action: "click", expected_frame_id: "f_…", ref: "e1" } })
web_use({ command: "verify", web_session_id: "cs_…", arguments: { action: "verify", expected_frame_id: "f_…", assertion: "text_contains", value: "Saved" } })
web_use({ command: "close", web_session_id: "cs_…" })
```

**Page 清单。** `list_pages` 返回 `windows[]`（每个已注册窗口一份快照，含 `window_id`、`inventory_revision`、`active_tab_entry_id`、`focused_page` 和 `tab_entries`）以及展平的 `pages` 列表。tab entry 是顶部标签栏里的一项：`single` 含一个 Page，`split` 含两个有序 pane（`tab:<tab_id>` 与 `group:<CenterTabGroup.id>`）。每个 Page 带 `window_id`、`tab_id`、`tab_entry_id`、`placement`、标题、origin、`visible`、`focused`、可选的 `opener_tab_id` 和它的 token。pane 顺序跟随实际渲染顺序；左右由实际几何推出，从不是 Page 身份。分组、重排或调整大小会递增 `inventory_revision`，不改变 Page。弹窗成为独立的标签页和 Page，带 `opener_tab_id`；它从不重绑 opener 的会话，调用方在下一次 `list_pages` 时发现它。没有已注册的 Desktop 窗口时（例如 worker 或 App 重启后），发现过程最多等待 `DESKTOP_RECONNECT_WAIT_SECONDS`（20 秒），然后返回 `desktop_unavailable` 和 `retry_command=list_pages`。

**绑定与修订号。** token 绑定调用方 owner、窗口、精确的 CDP target 以及服务端的 page 与 access 修订号；缺失、重放、跨 owner 或 target 已替换的 token 在调用任何后端之前就被拒绝。每个可见的网页标签页还带一个由 renderer 维护的 `geometry_revision`，随它在 App 内的边界或可见性变化（不随焦点变化，也不随 macOS 的层叠、遮挡或最小化变化）。WebSession 保存这三个修订号，worker 比较 page 与 access，精确的 renderer 在原生激活前比较 geometry；任何不一致都返回 `page_context_stale`，不触碰后端。对同一 Page 的写入持有独占租约；不同 Page 可以并发。后台 Page 直接解析 target，不切换标签页、不聚焦窗口、不调用 `bringToFront()`、不产生 OS 输入。清单、WebSession 注册表和 renderer WebSocket 注册表运行在 worker 主进程；workflow 子进程经父进程桥访问同一个 WebSession，修订号原样转发。

**Owner 与清理。** 对话 turn 的 owner 是它的会话和 assistant turn。正常返回、重试、取消和异常都会释放该 owner 持有的所有 WebSession、Page 租约和绑定，无论模型有没有调用 `close`。owner 的 WebSocket 断开会立即撤销它的所有绑定。显式 `close` 先检查 owner 和存活绑定，请 App 关闭标签页，再释放会话；别的 owner 什么也关不掉。

**Token 与恢复。** 带 token 而没有存活 `web_session_id` 的 `act` 或 `verify` 复用该 token 打开过的 WebSession；token 未用过时，运行时先做一次只读 observe，`navigate`、`screenshot`、`wait` 和不带 ref 的 `verify` 在这个 frame 上继续，而 ref 或坐标动作返回观察结果和 `action_performed=false`。注册表在内存里有界地记住已结束 WebSession 的标签页和已过期 token 的标签页。之后同一 owner 范围里出现的 `page_context_not_found`、`page_context_consumed` 或 `web_session_not_found` 会带上 `recovery_tab_id`、`recovery_window_id` 和 `recovery_command=observe`；agent 工具随后用新 token 观察那个标签页，返回 `recovered_page=true`、`previous_action_replayed=false`。不重放任何操作。每个可恢复的失败都恰好指明下一步调用。

**后端。** `observe` 从三个后端中选一个，并在该 WebSession 内固定：`playwright_mcp`（默认，固定版本的 `@playwright/mcp`）、`chrome_devtools_mcp`（固定版本的 `chrome-devtools-mcp`）或 `open_claude_chrome`（OpenProgram 自己的 Electron/CDP 控制器，遵循 Open Claude in Chrome 的工具契约，不运行扩展或 native host）。之后请求别的后端返回 `backend_mismatch`；失败、超时和过期 frame 从不回退到另一个后端，因此一个动作最多写一次。每个官方 MCP 的 WebSession 拥有一个用 `npx --prefer-offline` 启动的私有 MCP 进程，绑定到精确 target，禁用标签页选择。这个进程停止后，下一次 `observe` 以只读方式重启它；`act` 从不经重启过的进程写入，而是返回 `computer_use_backend_unavailable` 和 `observe_required=true`。三个后端经 `WebUseSessionRegistry.execute()` 跑同一张一致性矩阵：结果、frame 失效、reason code 与验证语义都相同。

**Frame 与失败。** 每次成功写入都会让 frame 失效并设置 `observe_required=true`。缺参数返回 `invalid_arguments` 和完整的 `missing_arguments`，保留仍有效的观察；旧 frame 返回 `stale_observation`；未知动作返回 `unsupported_action`；后端错误返回 `backend_action_failed`。reason code（包括 `invalid_capability`、`ambiguous_page`、`page_context_stale`、`page_access_disabled`、`target_lost`、`needs_user`、`timeout`、`cancelled`、`verification_failed`）由运行时产生，后端文本从不覆盖它们。

**成本。** 观察以 DOM 和 ARIA 为先：URL、标题、文本、快照和 ref，不截图。`screenshot` 从精确 Page 的 CDP 会话取一张当前视口 PNG，用于 canvas 页面或语义定位失败时。图像只进入下一次 provider 请求；工具文本、DAG 和最终结果只保留 `frame_id`、视口和 `image_attached`，正常返回、provider 错误、超时和取消都会清除图像并撤销坐标权限。不运行 OCR、目标检测、裁剪放大、视觉记忆或 workflow 回放。登录、CAPTCHA、敏感提交和不可逆操作返回 `needs_user`；页面内容是不可信数据，不能改变目标或权限。

**Agent 光标。** agent 点击期间，三个后端只在精确 Page 里挂一个捕获监听；真实的指针事件会在视口坐标处显示一个无文字、`aria-hidden`、`pointer-events: none` 的光标和波纹，随后淡出。用户点击、其他 Page 和 OS 鼠标不受影响，反馈失败也不会改变点击结果。

## 浏览器目标：标签页驱动

浏览器应用的 `tabs.py` 为 `browser` 目标驱动 App 的内置标签页。对这个目标而言，它取代了 `web_use` 运行时的 page context token、会话、frame、租约和修订号校验，这些都不再出现在模型面前。`web_use` 运行时仍保留，供仍直接调用它的程序和 MCP 客户端使用；它是应用注册的唯一页面入口。

**标签页。** 一个标签页就是渲染进程列出的 `(window_id, tab_id)`（`surface_context.capture_pages_for_listing`，现在也带上每个标签页的 CDP `target_id`）。驱动给它起名为 `t` 加上 `window_id` 与 `tab_id` 的 SHA-1 的前四个 base32 字母（冲突时多取一个），所以每个进程——worker 和 fork 出的工作流子进程一样——在每个轮次、每个对话、每个子 agent 里都给同一个标签页同一个 id，按任何顺序重新列出也不会改名。移到另一个窗口的标签页保留它的 id：列出的标签页的 `target_id` 属于某个已知标签页时，就接管那个标签页。`target_id` 变了的标签页（App 重启过）会忘掉它的 ref、文档基线和截图。每次列出都会重新绑定每个页面，所以新绑定替换旧绑定时旧绑定会被释放。不带 `tab` 的动作发往其 agent 最近用过的标签页（见下），否则发往获得焦点的标签页，再否则发往唯一可见的标签页。`open` 请渲染进程新开一个后台标签页（`surface_context.open_page`）并把它设为当前标签页；`close` 和 `screenshot` 经过标签页的绑定（`request_close_tab`、`request_bound_screenshot`），绑定过期时重新列出一次即可续上。

**连接。** Playwright 的同步 API 属于单个线程，所以由一个所有者线程持有到 App 的 `connect_over_cdp`（`desktop_app_ws_url`），并执行所有页面调用；调用方带着自己的上下文变量等待它。页面通过 `Target.getTargetInfo` 与标签页的 `target_id` 匹配来找到。一个连接不一定能得知 App 在它之后打开的标签页，所以找不到目标时驱动会重新连接再找一次；断开的连接在下一次调用时重连。第一次接上页面监听时，驱动开始记录它的控制台、页面错误和请求（各保留最近 300 条），并统计文档导航次数和进行中的 fetch/XHR 请求。

**多个 agent。** 同一对话的 agent 共用会话 id，子 agent 可以并行运行，所以标签页被一个 agent 占用的时间不超过一个动作或一组动作：之前的运行时会拒绝自己对话的轮次，正是跨轮次持有的租约和它的交接造成的。每个 `Tab` 有一把锁。动作在第一次页面调用前拿到它，并一直持有到等待结束、结果读出，所以别的 agent 的输入不会落在一个动作和它报告的状态之间。一组动作（`targets/browser.run` 带多个步骤，在 `tabs.batch()` 里）持有它拿到的所有锁直到结束，所以一组动作里填写的表单不会被插入。等锁时轮询并检查取消，超过 `TAB_WAIT_SECONDS`（60 秒）以 `tab_busy` 失败；两组动作互相等对方的标签页时也这样结束，而不会死锁。一次调用代表的 agent 是 `<session>/<execution>`（`_VIEWER` 上下文变量，随调用带进所有者线程）。每个 agent 记住自己的当前标签页；还没有的 agent 从它所在对话最近用过的标签页开始。快照按 agent 跟踪（`track` = `openprogram:<agent>`，以及每个 agent 自己的文档基线），所以一个 agent 看到的变化涵盖它上次查看之后的一切，包括其他 agent 做的。每个标签页记录写操作及其执行者；自本 agent 上次结果以来有别的 agent 操作过该标签页时，结果会附上 `note`。只有单个页面调用在所有者线程上执行。`wait` 和动作后的等待在调用方线程上轮询，每次只占用所有者线程很短的时间（`_shows`、`_activity`、`_loaded`），所以一个 agent 的等待不会挡住另一个 agent 在另一个标签页上的点击。

**写操作只发送一次。** 只有 `_page` 在任何输入之前抛出的 `tab_gone` 会让驱动重新列出标签页并再试一次。在 Playwright 可能已经发出输入之后失败的动作算作一次写操作；超时时错误会说明它可能已经生效，并附上页面当前状态；动作期间标签页关闭为 `tab_closed`。动作成功之后，等待或读取页面时的任何失败都作为带 `note` 的成功结果返回，绝不成为调用方会重试的错误。`close` 把渲染进程的响应超时视为 `close_uncertain`，把过期绑定视为 `tab_gone`（什么都没发出），其他失败视为 `close_failed`。`evaluate` 算作写操作。

**动作打开的标签页。** 连接会发现目标（`Target.setDiscoverTargets`）并为每个新页面目标计数。动作期间计数变化时，驱动列出标签页，结果的 `opened` 给出 `opener_tab_id` 是被操作标签页或未知的新标签页。agent 的当前标签页保持不变。

**坐标。** 截图按 agent 记下 CSS 像素与图像像素之比、标签页最后一次写操作、URL 和滚动位置。按 `x`,`y` 点击需要该 agent 的截图；截图之后有任何 agent 写过这个标签页、它跳转过或滚动过时，以 `screenshot_stale` 失败。

**预览跟随。** 对话的页面预览跟随驱动报告的操作，与 `web_use` 运行时一样：前端只跟随实时的 `browser.resource` 事件，且其中的 `last_operation` 是新的、阶段为 `dispatched` 或 `acknowledged`，快照从不触发跟随。每个写动作（`read`、`console`、`network`、`wait`、`screenshot`、`tabs` 和 `close` 以外的动作）先为当前 execution 保留标签页的资源行（`publish_bound_page`），再带 `follow` 报告 `dispatched`（`pages.report_browser_operation`），在输入发出之前记下操作，并把资源的控制状态设为 `active`。动作之后以同一个操作 id 报告 `acknowledged`，或带原因码报告 `failed`；失败的报告不会再设置控制状态。页面只在设置它的 execution 运行期间显示为操作中：那个 execution 结束后，资源投影会把 `active` 投成 `idle`，与 `web_use` 相同。点击的结果带标记点：点击前，`_aim` 把元素滚动到视口内并记下其包围盒的中心，按 `x`,`y` 点击时记下换算出的 CSS 坐标，同时记下视口的 `innerWidth` 和 `innerHeight`；`sanitize_operation` 把它们变成 `point`，以视口尺寸作 `width` 和 `height`，由 `browser-marker-geometry` 映射到截图上。读取（`read`、`console`、`network`、`wait`、`screenshot`）报告一个不带 `follow` 的 `acknowledged` 操作，所以预览会跟随，页面却不会被标为操作中；`open` 在发布新标签页之后为它报告同样的操作，使它成为被跟随的标签页。一组动作的每一步各自报告。报告从不让动作失败：出错只在 debug 级别记日志。

**工作流子进程。** fork 出的子进程丢弃父进程的驱动（`os.register_at_fork`），因为它的所有者线程和连接属于父进程，然后启动自己的驱动。它的渲染进程调用（`capture_pages_for_listing`、`open_page`、`request_close_tab`、`request_bound_screenshot`）经过父进程的 webtab 桥，桥把它们限制在发起的窗口内、只认可它发出的绑定，并在子进程结束时关闭子进程打开的标签页。子进程不持有 App 连接，所以它的操作报告也交给 worker：`pages.forward_operations_to_parent` 把每个报告作为 `__op_browser_operation__` 放进子进程的事件队列，worker 用 `report_forwarded_operation` 报告它，只保留操作本身的字段，没有指明 execution 时用它启动的那个。标签页锁和写记录是按进程的，所以子进程和 worker 在同一个标签页上会在单次页面调用的粒度上交错。

**访问与取消。** 本轮的页面关闭了 agent 访问（`preview_status` 为 `disabled`）时，内置浏览器的所有动作都以 `page_access_disabled` 被拒绝。等锁、`wait`、动作后的等待和一组动作的每一步都会检查取消。

**读取。** `read` 返回 Playwright 的 AI 快照：ARIA 树，每个元素带一个 ref（`e12`，框架内为 `f1e3`）。Playwright 1.60 以 `Frame.ariaSnapshot(mode="ai", track)` 提供它，返回一段文本：同一文档已有被跟踪的快照时是增量；更早的版本以 `Page.snapshotForAI` 提供，两者一并返回。文档是新的或需要整页时，驱动请求整页，否则只请求变化。变化的行标为 `<changed>`，`[unchanged]` 代表已经发送过的部分。两者都会遮盖密码字段的值，整页截断在 40,000 字符。

**ref。** Playwright 按最近一次快照解析 `aria-ref=<ref>`，只要元素还在，它的 ref 就不变，所以 ref 能跨任意多个动作和轮次。驱动从快照里记下每个 ref 的角色和名称。解析不到的 ref 按这对角色和名称重新查找，直接用 `role` 和 `name` 指定的元素也这样找。仍然找不到时，动作以 `element_gone` 失败，并附上页面的当前状态。

**操作。** 点击、悬停、按键、输入（`fill`，或 `clear: false` 时用 `insert_text`）、`select_option`、`drag_to` 和 `set_input_files` 都是 Playwright 自己的可信输入。它们送达后台标签页时不会把它调到前台，这一点在 App 上核实过：后台标签页收到的指针、鼠标和点击事件都是 `isTrusted`。滚动用 `page_actions.SCROLL_SCRIPT`，`paste` 用 `PASTE_SCRIPT`。按 `x`、`y` 点击时，用截图时测得的比例把截图像素换算成 CSS 像素，前提是截图仍然有效（见上）。点击前会激活 App 的 agent 光标并把它放到元素上。动作之后，驱动最多等 0.3 秒看是否开始导航；开始了就等 `domcontentloaded`。之后再最多等 2 秒，让动作发起的 fetch/XHR 请求完成。然后返回变化；URL 变了或文档是新的时，返回整页。异常会变成带原因码和页面当前状态的结果，从不以原始错误返回。

**审批。** App 的标签页不需要审批。`open` 和 `navigate` 到本机之外的源会询问；`upload` 会询问；`evaluate` 在 bypass 以外询问，见下文。代码模式的校验器拒绝这三者，它的只读动作（`tabs`、`read`、`wait`、`screenshot`、`console`、`network`）对代理标记为读取。

**文件上传。** 页面很少直接显示文件框：它常以 `display: none` 藏在样式化的上传按钮后面，大纲里只有按钮；有的页面在点按钮时才创建文件框。所以驱动像人一样上传，做法与 Playwright MCP 相同。每个写动作执行期间页面上都挂着 `filechooser` 监听（`_catch_choosers`），Chromium 因此把文件选择交给驱动，而不在用户屏幕上弹出窗口；动作稳定后监听移除，用户自己点击时照常弹出窗口。这样拦下的选择器保存在标签页上，结果带 `file_chooser`（`multiple`、`accept`）；不带 ref 的 `upload(path)` 回应它，路径有误时它继续等待，其他写动作会丢弃它。`upload(ref, path)` 是一步完成的形式。ref 是文件框或它的标签时（`FILE_INPUT_SCRIPT`），文件直接设到这个文件框上，隐藏与否都可以；其他元素在 `expect_file_chooser` 中点击，由它打开的选择器接收文件，3 秒内没打开则报 `no_file_chooser`。驱动从不猜测按钮附近的文件框：页面上另有一个隐藏文件框时，文件会进错字段却报告成功，这也是 Codex 只通过选择器提供上传的原因。按钮点了没打开选择器时，也不是走投无路。页面可能卡在上一次上传里，也可能在 `await` 之后才打开文件框，那时点击带来的用户激活已经用掉了。所以错误里会写出按钮当前显示的文字以及它是否被禁用（`ELEMENT_STATE_SCRIPT`），并给页面上所有可用的文件框编号列出（`FILE_FIELDS_SCRIPT`）。每一项写明 id 或 name、`accept`、`multiple`、它所在的文字，以及它是不是按钮所在区域里唯一的一个。模型用 `upload(field=n, path)` 选定一个，文件直接设到那个文件框上（`Tab.file_fields`）。其他写动作或换页都会丢弃这份列表，用户自己的浏览器不支持 `field`。文本结果会写明拦下的选择器及其 `accept`，模型据此知道要回应它。用户的 Chrome 或 Edge 通过 Playwright MCP 自己的文件选择状态遵循同一模型：带 ref 的 `upload` 先点击它，不带 ref 时回应上一次点击打开的选择器。完全没有文件框的拖放区不在覆盖范围内。

`evaluate` 能读到已登录页面持有的一切，包括快照遮盖掉的内容，所以由权限策略而不是工具来把关。`page_script` 标出带 `evaluate` 步骤（单步或在 `actions` 里）的 `computer_use_agent` 浏览器调用，以及 `web_use` 的 evaluate。这类调用在 bypass 下和其他调用一样直接运行；其他模式下询问（`PAGE_SCRIPT_APPROVAL`，先于 Page 授权判断），除非有允许规则覆盖。卡片提供“仅此一次”和“本对话”，后者在会话层保存 `computer_use_agent(browser:evaluate)`（或 `browser:chrome:evaluate`）；从不提供项目规则，因为一次批准不该覆盖以后所有对话里的所有网站；参数完整展示。操作某个浏览器的授权（`browser:chrome`）不放行它的页面脚本。非交互来源会被拒绝，bypass 下也一样。结果经过同样的密码遮盖。表达式包成 `() => (expr)`；脚本上限 8000 字符，结果上限 20,000 字符。

## 界面工作

`app` 调用的审批卡片（`computer-use-approval.tsx`）先展示应用本身：图标、显示名和 bundle id 来自 `computer_use_apps` WebSocket 动作，它调用后端的 `app_info`，不启动任何东西，Web 按名字缓存结果（`lib/net/computer-use-apps.ts`）。其下一个标签用文字说明这一步（`computer-use-step.ts`），两行分别说明这一步在后台进行（录音则说明只录该应用的声音）以及可选范围的含义，去掉空值的参数折叠在"查看执行详情"里。

项目设置页在默认设置和权限规则之间有一个"操控电脑"分区（`computer-use-apps-section.tsx`）。它把项目的 `computer_use_agent(<app>)` 允许规则（以及以 `computer_use(<app>)` 保存的规则）列成每个应用一行，带图标、名字、bundle id 和移除按钮，通用规则列表不再重复这些规则。移除一行即删除该规则。对话级授权是随对话结束的会话规则，所以这里不列出。

人可以像在 Codex 里那样给 agent 指东西：

- 在网页标签里，**评论页面元素…** 选中一个元素，把它的选择器、文字和评论加进草稿；**区域截图…** 让人拖出一个矩形，把这块像素作为 PNG 附件加入。两者运行在同一个隔离脚本环境里（`apps/desktop/main/web-views/web-views.js` 的 `PICKER_WORLD`），共用一个取消钩子，开启一种会结束另一种。区域遮罩先被移除、再画两帧，`capturePage` 才按页面缩放截取那个矩形。文件经 `lib/chat/composer-inbox.ts` 送到目标对话：显示这个对话的输入框把它当作拖进来的文件收下，在那之前它一直在收件箱里等。
- 输入框的 `@` 菜单在文件之前列出已打开的网页标签和正在运行的应用（`attach/mention/mention-sources.ts`）。标签页写成指向其地址的 markdown 链接，应用写成名称加 bundle id，所以「这个标签页」不用模型去猜。正在运行的应用来自带 `running: true` 的 `computer_use_apps`，它列出被拒应用之外的常规应用，页面里缓存十秒。

## 实现状态

- 已实现：`computer_use_agent` 及 `app`、`browser`、`vm` 三个目标，首次使用时的目标指南，多个步骤，代码模式，带临时会话规则的 `fresh` agent，经 OSWorld HTTP API 的虚拟机目标（作为 `computer_use.vm` consumer 走出站策略），以及 Web 展示；单元测试覆盖路由、指南、虚拟机脚本和审批，沙箱测试用替身目标运行代码。尚未连接真实虚拟机服务运行。
- 已实现：macOS 上 `app` 目标的上述读取与执行动作，稳定序号，自适应等待，后台指针与键盘投递，树 diff，四个范围的按应用审批，系统访问门控，Web 展示，按键/树编号/菜单匹配/多个步骤/规则/审批接线的单元测试。
- 已实现：内置浏览器成为应用 `programs/applications/browser/`，只经 `browser` 服务访问；每个调用方在没有它时的运行都有测试。
- 已实现：`web_use` 运行时，含跨窗口 Page 清单、page/access/geometry 修订号、owner 清理、恢复提示、三个后端及其一致性矩阵、单张视口截图的释放流程和 agent 光标。
- 已实现：`browser` 目标的标签页驱动，选择标签页、ref 恢复、两种快照协议和结果形状有单元测试；并在 App 里做了两次端到端运行：agent 通过后台标签页填写并提交了一份本地两页表单（文本、邮箱、单选、复选、下拉、多行文本、确认框）。
- 已实现：为树稀疏的窗口提供 OCR 文字，并作为 `find` 的回退，附带一个经 Vision 识别渲染图像的测试。
- 已实现：按应用录音，输出 WAV，并用语音引擎转写。
- 已实现：可见标签页，以及原生后端上的 `changes_only` 观察。
- 已实现：对 Gemini 和 Chat Completions 的音频模型，把录音作为音频输入；Chat Completions 视觉模型能看到工具结果里的截图。
- 已实现：网页标签里的元素评论和区域截图；对已打开标签页和正在运行应用的 `@` 提及。
- 已实现：稀疏窗口里不带文字的图标和控件的轮廓。
- 已实现：上文所述的 Linux（X11）后端。测试在 Debian 12 容器里进行，环境是 Xvfb、Openbox、AT-SPI 总线和 PipeWire，对象是一个 GTK 3 窗口（菜单栏、输入框、密码框、复选框、滑块、带滚动的文本视图、绘图区、一个由子进程放声音的按钮）、GNOME 计算器（GTK 4 加 libadwaita，从桌面条目启动，靠元素点击算出 7×6）以及 ImageMagick 的 `display`（不接入 AT-SPI 的 Xt 客户端，靠 OCR 读取）。与主机无关的部分有单元测试。
- 已实现：另一个桌面空间里的窗口。测试时从桌面 1 操作桌面 2 上的计算器（列出窗口、截图、按元素算出 7×6、坐标点击、滚动、按键报错），鼠标指针和前台应用都没变，窗口留在原桌面空间；向那里的输入框插入文字没有测到，因为计算器没有输入框。
- 已实现、尚未在 Windows 上运行：上文所述的 Windows 后端。构建它的 macOS 机器没有 Windows 客户机，所以只有与主机无关的部分（PNG 编码、按键映射、HTML 剪贴板内容、开始菜单解析、控件类型表、拒绝列表、录音格式）有单元测试。
- macOS 上已实现：桌面应用上的控制提示层（向内发光、强调色红绿灯和 agent 光标），窗口位置帧、步骤坐标帧和桌面提示层窗口有单元测试。未实现：Linux 和 Windows 后端不上报窗口位置和步骤坐标，那里不会显示提示层。
- 已实现：`browser` 目标里经 Playwright MCP 扩展模式接入的用户 Chrome 和 Edge，动作映射、Edge、遇错停止、标签页列表和审批主体有单元测试。尚未在真实浏览器中配合 Playwright Extension 运行过。
- macOS 上已实现：窗口标识，监视、切换和空闲释放有单元测试。Linux 和 Windows 上未实现。
- macOS 上已实现：跟随新打开的窗口、识别文件对话框并拒绝按键、`open_file`，在预览和 PDF Expert 上实测（跟随打开对话框、拒绝按键、按下取消、打开一个 PDF 并读出文字），全程前台应用不变，另有单元测试。跟随不夺焦点的对话框、凭窗口列表识别进程外对话框、从服务进程读取它、它开在焦点窗口旁边时拒绝按键、`open_file` 先取消它，这些有单元测试；其中只有窗口列表识别实际运行过，对象是 PDF Expert 的打开对话框。Linux 和 Windows 未实现。
- 未实现：经 Responses 和 Anthropic API 的音频输入（这两个接口的模型不收音频）；把窗口从另一个桌面空间移过来，以及用按键向它输入（见上文）；从轮廓直接认出图标的名字（模型看截图分辨）。
