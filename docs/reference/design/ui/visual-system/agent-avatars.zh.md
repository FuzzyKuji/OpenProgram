# Agent 头像

每个 Agent 都有一个头像，界面上凡是出现它的名字，头像就在名字旁边。从未设置过头像的 Agent 显示一个由它的 id 推导出的角色，所以没有任何位置会退回通用图标，已有的 Agent 数据也不需要迁移。

Agent 使用和用户头像相同的 `Avatar` 组件与 `AvatarConfig`（`apps/web/components/avatar/`）。角色只是这份配置里多出的一种 `kind`，与 `dicebear`、`upload`、`letter` 并列；没有第二套头像系统。

## 角色

一个角色是一个带两只眼睛的纯色形状：对话气泡、杯子、火箭、幽灵。活动时它会眨眼、晃动、自己东张西望，用动作表达自己在做什么。它不跟随鼠标。

| 组成 | 取值 |
|---|---|
| 形状 | 22 种：`chat`、`controller`、`mug`、`lightbulb`、`sprout`、`watering-can`、`barbell`、`book`、`brain`、`bull`、`bunny`、`camera`、`cat`、`cloud`、`ghost`、`magnifier`、`paint-brush`、`palette`、`rocket`、`shield`、`star`、`witch-hat` |
| 颜色 | 8 种具名颜色：`blue`、`orange`、`green`、`violet`、`pink`、`teal`、`yellow`、`red` |
| 眼睛 | 白色 |
| 状态 | `idle`、`thinking`、`happy` |

目录在 `components/avatar/bot/catalog.ts`。颜色按名字保存，绘制时对应一个固定的十六进制值。角色图案是唯一不从主题取色的地方：颜色是角色身份的一部分，和 DiceBear 生成的图案在任何主题下保持原色是同一个道理。角色周围的东西（底板、描边、文字）仍然只用主题变量。

## 一个 id 得到哪个角色

`components/avatar/bot/identity.ts` 里的 `botLookFor(id)` 为每个 id 给出形状和颜色。对 id 做 32 位 FNV-1a 哈希，低位选形状，高位选颜色，两者不会同步变化。内置 Agent 则查表：每个都有一个符合其工作的角色（PR Verifier 是盾牌，Research Desk 是大脑，Knowledge Keeper 是嫩芽），彼此形状不重复。

`lib/agents/agent-avatar.ts` 里的 `agentAvatarConfig(agent)` 是“一个 Agent 显示什么”的唯一规则：有保存的头像就用它；没有（或者是上传类型但图片缺失）就用 id 对应的角色。

## 存储

头像是 Agent 记录的一个字段（`AgentSpec.avatar`，`<state>/agents/<id>/agent.json`），随每次 Agent 列表一起返回。

| 字段 | 使用者 | 规则 |
|---|---|---|
| `kind` | 全部 | `bot`、`dicebear`、`upload` 或 `letter`；头像非空时必填 |
| `shape`、`color` | `bot` | 短标识；有哪些由前端目录决定，未知值按 id 的角色绘制 |
| `style`、`seed` | `dicebear` | 标识；最多 120 个字符 |
| `file` | `upload` | `data:image/` 开头的 URL，最多 350,000 个字符 |
| `letter`、`bg` | `letter` | 最多 2 个和 40 个字符 |

- `{}` 表示“没有自己的头像”，是默认值。
- 一次修改整体替换头像。从上传图片换成角色后，不会留下图片的任何内容。
- 接口严格校验，其他内容一律以 400 拒绝（`openprogram/runtime/agent_registry/manager.py` 的 `validate_avatar`）。读取则是宽容的：已保存但不再合法的头像读作 `{}`，坏掉的头像不会让 Agent 消失。
- 选择器里上传的图片上限是 256 KB，因为每次列表都会带上它。
- 试运行对话的配置快照不含头像；头像是 Agent 的样子，不影响它如何运行。

## 渲染

渲染器是 `open-bot-avatar` 包。`components/avatar/bot/runtime.ts` 在第一次用到时才加载它，和可选的 DiceBear 风格一样，没有角色的页面不为它付出代价。`BotAvatar` 挂载到指定尺寸的宿主元素上，随组件更新或销毁。

| 模式 | 绘制内容 | 何时 |
|---|---|---|
| 静止 | 一张静态 SVG | `Avatar` 的默认 |
| 活动 | 一个会眨眼、晃动、东张西望的 canvas | `live`；`AgentAvatar` 的默认 |

渲染器第一次画某个形状时要先准备它：从轮廓推算形状的立体体积，每个形状 25 到 90 毫秒，算完在页面生命周期内保留。像 Agent 菜单那样第一次同时显示十七个 Agent，就要在一帧里做半秒多这样的计算。所以 `components/avatar/bot/warm.ts` 每个任务只准备一个形状：页面上有角色在等的形状放在下一个任务，其余形状在渲染器加载后利用空闲时间准备，列表打开时通常所有形状都已就绪。形状就绪之前（以及服务端渲染的标记里），角色显示为它的平面图案（身体和白眼睛，用它自己的颜色），位置和渲染器将要绘制的框相同；渲染器在同一次提交里替换它，不会闪。静止的图案也需要同样的准备，所以把角色改成静止并不能解决问题。

页面上所有活动的角色共用一个动画循环，离开视口时暂停。系统要求减少动态效果时，活动的角色就是那张静止图案。

空闲的活动角色会自己东张西望。渲染器自带的空闲漫游在图标尺寸下只让眼睛挪动约一个像素，同一种形状的角色还同步移动，看上去就是一直盯着前方。所以由 `components/avatar/bot/wander.ts` 给每个角色各自的视线：一个注视目标（`lookAt`），渲染器把眼睛和身体转过去，停留 0.9 到 2.6 秒，再换下一个。每次至少往一侧看出三分之一（横向最多 0.95，纵向最多 0.6），四次里有一次回到正前方。每个角色各自抽取目标和停顿，开始前也随机等一会儿，所以并排的角色会看向不同的方向。每个角色只有一个计时器，每次扫视触发一次，没有逐帧的工作。思考中或高兴的角色保持各自情绪的姿态。它不看向鼠标。角色盯着光标会显得在盯着用户，这不是 Agent 头像该做的事；而且渲染器的鼠标跟随（`followPointer`）会在每一帧里用 `getBoundingClientRect` 测量角色，让浏览器在这一帧里提前重算样式。`followPointer` 保持关闭，所以动画循环从不读取布局。页面隐藏时浏览器会停掉这个循环的帧。

角色的轮廓就是图案本身，所以不裁成圆形，背后也没有底板。上传和生成的 Agent 头像保留圆角方形的外框。

角色是插图，不是图标。开关、菜单行和按钮会把内部的 svg 当作图标定尺寸；`app/styles/design/icons.css` 里的一条规则让角色的图案保持其身体框的尺寸。

### 视觉尺寸

各个图案在 100 单位的画框里留的边距不同：Main 的云朵又宽又矮（82 x 52 单位），幽灵又窄又高（54 x 76）。按画框大小绘制时，16px 的角色身体只有 13 x 8px，旁边图标的笔画约 14 x 13.5px，看起来比邻居小。所以 `BotAvatar` 有两层框：参与布局的槽位，就是要求的尺寸；槽位里的身体框，渲染器画在它里面。`components/avatar/bot/catalog.ts` 的 `botFit` 按身体的范围（`BOT_EXTENTS`，有测试对照图案核对）缩放并摆放身体框：身体边长的几何平均为槽位的 0.8，任一边不超过槽位的 0.94，并且居中。16px 的云朵约 15 x 9.5px，幽灵约 10.7 x 15px。活动的 canvas 按身体框定尺寸，以实际显示的大小绘制，而不是放大。

### 悬停

槽位在所在控件悬停时放大，和图标完全一样（见[图标](icons.zh.md)的动效约定）：`components/ui/hover-pop.ts` 保存可点击宿主的选择器、1.12 的放大倍数和弹簧参数，`SolarIcon` 和 `BotAvatar` 都用它。输入框的 Agent 按钮、Agent 菜单的各行，以及其他显示角色的控件，都和旁边的图标一样放大；不在控件里的角色跟随自己的悬停。减少动态效果时关闭。

## 出现的位置

| 位置 | 尺寸 | 模式 |
|---|---|---|
| Agents 页：卡片、快速设置标题 | 32 | 活动 |
| Agents 页：编辑区标题 | 40 | 活动 |
| Agents 页：左侧列表 | 16 | 活动 |
| 头像选择器的形状格 | 34 | 静止 |
| 输入框的 Agent 按钮 | 16 | 活动 |
| Agent 菜单的每一行 | 16 | 活动 |
| 非默认 Agent 回复上方的名字 | 18 | 活动 |
| 运行记录面板：常驻行 | 22 | 活动，Agent 工作时为 `thinking` |
| 运行记录面板：常驻详情标题 | 16 | 活动 |
| 设置：频道绑定 | 16 | 活动 |
| 图：agent 回复和子 agent 起点节点、图例 | 16 | 分支色的平面图案 |
| 运行记录面板：agent 和子 agent 行 | 22（详情标题里 16） | 分支色的平面图案 |

代表某个 Agent 的角色在每个位置都是活的，不论多小；`AgentAvatar` 默认活动，除非调用方关掉。选择器的形状格是形状的样例，不是某个 Agent，保持静止。

只有 Agent id 的位置使用 `AgentAvatarById`，它读取共享的 Agent 列表（`useAgents`），列表加载完之前显示 id 对应的角色。Agents 页会把自己的列表写进同一份缓存，所以保存头像后各处无需刷新即可看到。

角色在有颜色的圆片或行里代替图标时（图、运行记录面板），画成平面图案（`components/avatar/bot/glyph.ts`，React 里是 `BotGlyph`）：身体路径用当前颜色，眼睛挖空。轮廓是顺时针绕行，眼睛下面身体的绕数都是 1，所以每只眼睛画成逆时针的药丸形，nonzero 填充规则就把它挖掉；测试对每个形状都检查这一点。它的取景框和活动角色用同一个 `botFit`，像图标一样填满。平面图案不动：它像 Solar 图标一样克隆进图的 SVG，颜色取分支色（见图的[渲染记录](../../runtime/dag/rendering.zh.md)）。主 agent 的图案是会话所用 Agent 的角色（`useConversationAgentShape`；用上传图片或生成头像的 Agent 在这里用 id 对应的角色），子 agent 的图案按名字分配。

Agents 的页面图标（导航入口、中间标签页）和对话里子代理工具调用的 `ghost` 表示的是一类东西，不是某一个 Agent 的头像；它们仍然是图标。

## 选择器

Agent 编辑区的常规分区使用和个人资料设置相同的 `AvatarPicker`，来源设为角色、生成和上传。角色一栏显示形状格和颜色色块；形状格用当前颜色预览。选择器修改的是 Agent 的草稿，头像和其余配置一起保存或丢弃。

## 来源与许可

| 来源 | 提供的内容 | 许可 |
|---|---|---|
| `open-bot-avatar`（npm，锁定版本） | 渲染器和 7 个形状 | MIT，Copyright Dominik Scholz |
| 同一项目仓库里的 gallery | 另外 15 个形状，原样复制到 `components/avatar/bot/gallery.ts`，带许可声明 | MIT，Copyright Dominik Scholz |

这些形状是该项目自己的设计。权衡过但没有采用的方案：

| 方案 | 不采用的原因 |
|---|---|
| 从 Grok Bot 客户端取出的渲染器，以及对其角色的复刻 | 无论仓库标注什么许可，代码或角色设计属于 xAI |
| `@aora-bot/react` | 许可不是开源许可（有署名和团队规模条款），并且要求 React 19 |
| `agent-robot-avatar` | 只有一个机器人形象，角色身份由作者保留 |
| DiceBear Bottts、Facehash、动态表情集 | 和选定的样子不同：生成的机器人、字母脸，或者看起来不成一家的表情 |

## 实现状态

以上内容均已实现。`happy` 状态可供调用方使用，目前没有位置设置它。
