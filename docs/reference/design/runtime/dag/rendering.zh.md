<div id="dag-渲染规范布局-连线-图例-默认可见性"></div>

# 渲染规范

> 会话图怎么画：每个节点放哪、每条线什么样、默认给用户看什么。**本文是权威
> 实现标准**——布局代码照此写，出问题对照本文查。数据语义（节点、两条边）见
> `dag/overview.md`；本文只管画。
>
> 每条规则配示例。**SVG 场景图以 `layout.html` 为权威**（共 13 个
> 场景：1–7 基础布局，8 merge，9 分支间通信，10 spawn 派活回流，11 执行子树
> 聚合，12 状态与徽标图例，13 badge 锚定与碰撞）。本文的 ASCII 图是文字版
> 速览，与 html 等价；冲突时以 html 为准。

---

## 图在哪：中央的一个视角

图是聊天面板两个**视角**之一，不是侧面板。每个中央 tab 要么在会话记录视角、
要么在上下文图视角，面板右上角那对控件负责切换——一个视角切换按钮加一个 `…`
会话操作菜单，照 Obsidian 的面板控件做。视角按 tab 记忆，把一个会话停在图上
不影响其他会话。

给图整列宽度是关键：分支多的会话要摆开 lane、tier 和分支名 badge，288px 的
侧栏装不下。

| 部件 | 位置 |
|---|---|
| 视角状态 | `CenterTab.dagView`（`apps/web/lib/tabs/center-tabs-store.ts`）——不持久化，刷新后回到会话记录 |
| 控件 | `apps/web/components/chat/pane/view-controls.tsx` |
| 图的宿主 | `apps/web/components/chat/dag/dag-view.tsx`——渲染 `#historyPanel` + `.history-body`，即 `apps/web/lib/runtime-bridge/dag/pipeline.ts` 与 `apps/web/lib/runtime-bridge/dag/render/visibility.ts` 选取的元素 |
| 视角切换 | `apps/web/app/styles/dag/view-host.css` 的 `.center-pane-chat[data-center-view]` |

两个界面同时挂载，靠 `display` 互换：无论当前显示哪个视角，渲染器每次 capture
都往宿主里画，卸载会让图空到下一次 capture。宿主不随尺寸重排——它是一块无限
画布，面板变宽只是露出更多（见下）。

点击图上的节点填充右侧栏的详情 / 上下文视图；这两个视图留在侧栏，因为它们读
的是选中的单个节点，不是整个会话。

### 画布是无限的

没有滚动容器，也没有按内容定尺寸的 SVG。SVG 铺满面板，一切绘制物都在一个
`<g>` 里，这个 `<g>` 带着用户直接操控的 translate + scale。

| 手势 | 效果 |
|---|---|
| 鼠标滚轮或触控板捏合 | 以光标为锚缩放，限 25%–300%——指针下的节点缩放前后都在指针下 |
| 触控板双指滑动 | 平移 |
| 右键（或中键）拖动 | 平移，在图上任何地方都行 |
| 在空白处左键拖动 | 选择框（第十三节） |
| 在节点上左键按下 | 归节点——单击、双击照常生效 |

**滚轮**（`apps/web/lib/runtime-bridge/dag/interaction/view/gestures.ts`、
`interaction/view/wheel.ts`）：鼠标滚轮缩放，和地图一样；触控板双指滑动平移，和设计画布
一样；捏合缩放。三者都是 `wheel` 事件，所以从事件本身判断：捏合带 `ctrlKey`（⌘ + 滚轮
也缩放）；有横向 delta 的是双指；App 所用的 Chromium 把触控板的旧字段 `wheelDeltaY`
报成恰好 `-3 × deltaY`，而滚轮按格报 120 的倍数。以前按 delta 大小去猜，把真实鼠标当成
触控板，滚轮就变成了滚动；`wheelDeltaY` 判据不看大小。一次手势按第一个事件定性，事件
停顿（180 ms）前不改，所以触控板的惯性尾巴不会翻成缩放。捏合用自己更快的速率；line、
page 模式的 delta（部分鼠标）先换算成像素。驱动发出像素级平滑 delta 且
`wheelDeltaY = -3 × deltaY` 的鼠标会被当成触控板而平移。

按内容定尺寸的容器替用户决定了两件不该它决定的事：图能画多大才需要滚动条，
以及"中间"在哪。宽会话给一条横滚动条，深会话给一条竖滚动条，看全貌要在两个轴
上滚，还没有缩小的办法。

**点阵就是坐标系。** 面板背景按布局自己的步长（`COL_W`）每格画一个点，跟着
同一组平移缩放变换，并按布局的原点偏移（`PAD_X` / `PAD_Y`，点阵自内边距再退
半格）对位，让每个节点锚点下面正好是一颗点——偏离格点是任何人不看布局代码也
能发现的 bug。fit 把平移量吸到整像素，正是为此。点的半径也跟着缩放走（收在
1–3px）：定死 1.2px 在放大后的大格子里会细到看不见。

**视角状态跨重绘保持。** 图每次 capture 都重绘，每次都动镜头会在用户读图时把
视野拖走。平移与缩放按会话存在 `apps/web/lib/runtime-bridge/dag/store/globals.ts` 里，只有进入另一个会话才重新
fit。改面板尺寸永不重新 fit——用户看图的角度是他自己的。

**进入会话时可读，Shift+1 才看全图。** 打开时的视野就是 fit，但下限 80%：长会话
整张塞进来会缩成一根细线上的小点（40 轮的聊天打开时是 37%）。图在这个下限下
仍比可视条带大时，溢出的那个方向跟着 HEAD——放在条带靠下处，就像会话记录打开
时停在最新一条。“显示整张图”（Shift+1）保持原来的 fit，最低到 25%：要求看全图就是要的
这个（`apps/web/lib/runtime-bridge/dag/interaction/view/canvas.ts` 的 `fitCanvas(opening)`）。

**缩放竖列。** 在画布右上角，紧接在窗格视角切换那一条下面，所有看图的控件都在这一角的一列里：一条凸起竖条放 + · 读数 · −，
隔一道发丝线是**找到正在工作的 agent**（F）；
下面第二条竖条开关小地图，再隔一道发丝线是两份指南——图例（各种标记是什么意思）和操作说明面板（画布认哪些操作），每个点一下一直开着，再点按钮才关，几个可以同时开着。缩放竖列左边从顶部起是一条和小地图同宽的侧栏，像 macOS 的小组件侧栏：依次是小地图、停靠在这里的本会话浮动网页小窗、图例、操作说明，间隔 16px，每块都是完整高度。侧栏底部停在输入框上方 16px，整条一起滚动——在任何一块上（包括小地图）滚滚轮都是滚整条侧栏，单块面板自己不滚。关掉的面板不占位置。会话视角有同样的停靠位：窗格视图按钮左边一条只放小窗占位的侧栏（`components/chat/pane/view-controls.tsx`），所以两个视角里小窗都在右上角，切换视角时在两个停靠位之间换过去。小窗默认停靠（`apps/web/lib/browser/web-tab/web-tab-pip-dock.ts`；`PipDockSlot` 在侧栏里占位，小窗浮在这个位置上，随侧栏滚动裁切，部分滚出时用一张静止画面代替原生网页）。拖小窗标题栏时，指针移动不到 36px 小窗保持不动；超过后它恢复自由尺寸、以弹簧动画跟到指针下，之后可以放到任何地方，两个视角都保持这个位置。松手前侧栏一直留着它的位置。拖回到侧栏顶部 56px 以内会以弹簧吸进去——靠近时侧栏先让出位置——要再拖开 88px 才会脱开，所以在边界上不会来回闪；松手就重新停靠。每次进出都是一段弹簧动画（framer-motion），从小窗当前画的位置走到它现在该在的位置，而这个位置一直跟着指针。展开的小窗始终浮动。三块面板出现和收起都和应用里的弹层一样：100ms 内淡入、从 95% 放大、从竖列那一侧滑进 8px，收起时原样倒放（`components/chat/dag/dag-key-sheet.tsx` 的 `PANEL_MOTION`；小地图是 `app/styles/dag/panels/tools.css` 里的 `.is-hidden`）。进入图视角时，先把小地图无动画地收起（`stowMinimap`）——上次离开时它可能还开着，最初几帧画的又是清空的缓存——这样它只在第一次画出图时出现一次，不会先缩回去再弹出来。竖列里的几条按钮从上到下依次淡入并从右侧滑进 8px，每条 150ms、间隔 40ms；离开图视角仍是瞬间切换。
**全屏**属于会话面板，不属于图：按钮在竖列上方的视角切换那一条里（对话视图控件里的专注模式），所以切换视角不会退出。它把窗口让给会话面板：中间的主体（画布或对话，连同输入框）脱离布局，从原来的位置向外长大，盖在应用的左侧栏、右侧栏和中间的标签栏上面——它们留在原地不动——直到四边都离窗口 `--canvas-fullscreen-inset`（8px），和侧栏卡片离窗口边的距离一样，标签栏在它下面淡出，连带它的底色变成其他几道缝露出的页面色；画布里的其他面板在全屏期间让开。长大时移动的是主体真实的四条边，和画布移动面板、macOS 缩放窗口一样：四条边各自从会话面板原来的框连续走到窗口内缩的位置，内容每一帧都按当前框的大小排版——不会先跳到最终尺寸再缩放。动画用 Web Animations API，从第一帧画出来时才开始计时，400ms，用对称的缓入缓出曲线（内容长到对话栏的最大宽度就不再变，这发生在展开的前段，前快后慢的曲线会让它一下子跳到位）；退出用 320ms 把四条边收回面板原来的框，再落回布局。过渡开始前绝不按全屏尺寸排版内容：那样对话的滚动位置会被压到更短的文字上而跳动，所以终点是写明的内缩值而不是量出来的，起点也同时写进主体自己的样式——Chromium 按元素自身样式排新动画的第一帧。过渡期间画布算作“在移动”（`lib/tabs/canvas/canvas-motion.ts`）：对话只重排可见的几行，用浏览器的滚动锚定固定住第一行可见内容，消息行到静止后才重渲染一次。期间外壳不会因为主体尺寸变化而重渲染。动画中途再切换会从当前位置原路返回；系统开了“减少动态效果”时不做动画。这是应用内的模式，不是浏览器全屏，窗口大小不变；全屏盖住原生网页视图期间，它们会隐藏。再点一次、按 Esc（没有选中节点时）、切到别的类型的标签或刷新都会退出（`lib/tabs/canvas/canvas-fullscreen.ts` 管状态、Esc 和过渡；样式靠 `app/styles/chat/pane/center-pane.css` 里的 `html[data-canvas-fullscreen]`）。这个位置以前是“显示整张图”：图小的时候它和点读数回到 100% 看起来一样，所以现在只留 Shift+1。
开着的开关保持悬停时的灰色底，不用强调色。竖列和窗格视角切换那一条里的图标都是 Solar Bold Duotone，悬停时和输入框按钮一样弹一下（`docs/reference/design/ui/visual-system/icons.zh.md`）。
−/+ 每次步进恰好一个滚轮格（`ZOOM_STEP`），点读数本身重置 100%——按钮没有光标可锚，
两者都以面板中心为锚。按钮和 + / −、Shift+0 这几个键都用 0.22 秒平滑过渡过去，缩放比例按对数均匀变化，放大和缩小快慢一样；过渡中再按，从目标比例接着走一步。滚轮和捏合仍是即时的——手势本身就是连续的——滚轮或平移会接管正在进行的过渡（`canvas.ts` 的 `glideZoom`）。读数由 `apps/web/lib/runtime-bridge/dag/interaction/view/canvas.ts` 在每次视角变化时命令式写入——把
一次手势的每个 wheel 事件走 React state 会让整棵树每秒重绘六十次。这些控件以前分散在
输入框的 env chip 行和左侧竖条上，现在合成右缘这一列，左侧竖条已经去掉。

竖列的几条共用同一套材质和按钮（`apps/web/app/styles/dag/panels/tools.css`）。图例面板和操作说明面板的内边距来自 `MENU_PANEL`
（`components/chat/top-bar/menu-styles`），外框却和小地图一致——同样的底色、浮起阴影、10px 圆角、没有外圈描边——因为三者叠成一列 280px，带描边会比小地图左右各宽出 1px；
`apps/web/app/styles/dag/panels/legend.css` 只留图例的锚位和行。

| 部件 | 位置 |
|---|---|
| 平移 / 缩放 / fit | `apps/web/lib/runtime-bridge/dag/interaction/view/canvas.ts`（缩放竖列走 `zoomStep` / `resetZoom`） |
| 视角状态 | `apps/web/lib/runtime-bridge/dag/store/globals.ts` 的 `_viewTx` / `_viewTy` / `_viewScale` / `_viewSession` |
| 画布与点阵 | `apps/web/app/styles/dag/graph/canvas.css` 的 `.history-body` |
| 缩放竖列 | `apps/web/components/chat/dag/dag-view.tsx` 的 `DagZoomColumn`；竖条样式在 `apps/web/app/styles/dag/panels/tools.css`，图例和操作说明的内边距来自 `MENU_PANEL`、外框和小地图共用，图例的行在 `apps/web/app/styles/dag/panels/legend.css` |

### 输入框属于面板，不属于会话记录

**视角切换隐藏的是会话记录滚动区 `#chatArea`，绝不是 `#chatView`。** 输入框
是单例，portal 进 `#chatView` 里的 `#composer-mount`，并以 `bottom: 0` 锚在
它身上——隐藏这个祖先就会把输入框跟着会话记录一起带走，而挂第二个实例会把
草稿、运行状态、模型行分叉成两份，用户读作一个输入框的东西就有了两套状态。
因此两个视角共用同一个输入框实例，图只替换它上方的滚动区。

在图视角能直接发消息，发出的节点在下一次 capture 出现在图上——发送走的就是
会话记录那条路径，没有改动，图视角不需要知道自己正在显示。

图是**盖住面板**来取代会话记录的，不是去占列里的那个位置：`#chatView` 保持
`flex: 1` 和满高，输入框的 `bottom: 0` 因此仍然落在面板底边，剩下的交给层叠
顺序——图压在输入框 `z-index: 5` 之下。反过来把 `#chatView` 压扁，只会把输入
框拽到面板中间。

画布在输入框底下一直铺到边——从输入框后面平移过去只是一个手势，fit 会把图
居中在输入框上方的空间里（`apps/web/lib/runtime-bridge/dag/interaction/view/canvas.ts::fitCanvas`），所以不需要预留 padding。

### 分支切换在图里

画布上方没有分支条。每条分支的名字是画在图里的按钮，锚在该分支最后一个对话层
节点下方（`apps/web/lib/runtime-bridge/dag/render/labels/badges.ts`，第五节）：活跃分支的标签是 lane 色的扁平色块，点
其他标签即 checkout。图本身已经画出分支结构，再来一条横条是重复信息，还会横穿
面板右上角的悬浮视角按钮。重命名、删除、merge、attach 留在右侧栏的分支列表里，
那里有这些流程需要的纵向空间。

---

## 〇、先回答"画什么"：两层粒度，默认只画对话层

一张会话图里有两类节点，量级差一个数量级：

| 层 | 节点 | 回答的问题 | 量级 |
|---|---|---|---|
| **对话层** | ROOT、user、llm 回复、spawn 分支根、merge、**手动调用的顶层函数节点**（用户的显式动作，fn-form/run 卡对应的 code 节点本体） | 会话什么形状：几轮、几支、谁开的谁 | 个位数~几十 |
| **执行层** | code（tool call）及其内部子调用 | 某一轮内部干了什么 | 一轮可达几十 |

**默认可见性规则：Viewport 只布局对话层。** 一轮干过的一切——每次函数调用、
每个派出去的 agent——是这一轮的**调用线程**（第十二节）：默认折叠成节点肩上
的一个数字，点节点才展开成旁边的一列真节点。

两条归并让链保持在用户可见的粒度——**一个三角形 = 一次回复到下一条用户消息
之前的全部模型活动**：

* 运行时通知的回复不是链节点：agent 返回触发的那一轮（`source="job_followup"`），
  以及后台命令结束触发的那一轮（`source="process_exit"`）。函数返回后模型
  接着说话不画新节点，这些返回是同一件事的另一个尺度——回复归并进它的
  **锚轮**：沿 `predecessor` 爬过所有 followup 找到的那一轮。通知的合成用户
  消息是 `display=runtime`，从不画出；`graph_layout/filter.py` 先把回复改挂到
  通知的上家，回复就不会指向 payload 里不存在的节点（否则它会画成悬空孤点，
  之后每一轮都另起一列往右错开）。同一步（`bridge_hidden`）覆盖所有被剥掉的
  `display=runtime` 行，不只是通知：恢复被中断的运行会写一条合成的「继续被中断
  的任务」用户轮，它的续答改挂到被重启切断的那条回复上，分支在原列里接着走，
  而不是脱离整张图漂在下方。这条续答被标上 `resumed`：它是被切断回复的后半截
  （聊天里本来就画成同一条回复），所以和通知回复一样归并进同一个锚轮，画成一个
  节点，线程里装着前后两半的调用。一个值得点名的
  副作用：老回卷 bug 弄脏过 followup predecessor 的旧数据也解析到同一个锚，
  疤痕从此不再画成幻影分叉。
* spawn 的 agent 内部轮同样不上链。spawn 头就是那个 agent（第十二节），
  它 lane 里的一切归并进它。

```
默认（对话层）:                  点击回复展开它的线程:
◇ROOT                          ◇ROOT
├ ○你好                        ├ ○你好
│ └ △回复                      │ └ △回复
├ ○查天气                      ├ ○查天气
│ └ △回复 ⁹                    │ └ △回复┄┐
                               │        ■ bash
                               │        ■ web_fetch
                               │        ■ 子 agent ⁵
                               │        ■ …(共9行)
```

理由：执行层信息在聊天流里已有更好的呈现（每轮的执行树卡片、Executions 页）。
Viewport 的职责是让人一眼看清会话结构；50 个工具方块平铺会把 8 个结构节点
淹没——一个真实的天气会话（66 节点，50+ 是 code）就是这个样子。

> 聊天流与调用树两种视图不受影响：聊天流按 seq 铺顶层、函数嵌套折叠；
> Executions/执行树卡片沿 caller 全展开。同一份数据，三种投影。

---

## 一、一个节点的位置 = (列, 行)

- **列（横向）= lane 起始列 + tier 缩进**
- **行（纵向）= depth**

两轴步长相同（`COL_W == ROW_H`，`apps/web/lib/runtime-bridge/dag/types.ts`），整体自原点偏移
`PAD_X` / `PAD_Y`——这就是画布点阵所画的那张方格。

### lane —— 属于第几条分支

**数分支，按出现顺序发列号 0,1,2…，不跳号，不判断"主干"。**

一条分支 = 一条对话链（user → llm → user → …）。三种事件产生新分支：

| 事件 | 新分支的根 | 挂接 |
|---|---|---|
| retry / 改写某轮 | 分叉出的 user / llm 节点 | 与被替换节点共享 predecessor |
| spawn（agent / send_message 派活） | source=agent_spawn 的 user 节点 | caller=发起节点，predecessor 空 |
| merge 出的新主线 | merge 节点本身 | 落 base 分支 lane（见场景 8），不新开 |

**分支按实际占用列紧贴排**：一条分支占用的列 = 起始列到其可见**链**节点的最深
一格；下一条分支从上一条实际占用的最右列 +1 开始，互不重叠。以 fork 根开头的
lane 与它分叉出来的 lane 之间**多留一个空列**——分支是平行版本，两格的空气就是
这句话。tier 按 lane 内归零（后端给 fork 根的 tier 带着旧位置的偏移，不归零会让
单节点分支凭空右移好几列）。**fork lane 内部复刻主干**：lane 的第一列是一根
空的脊线——桥的虚线落在脊线上，线从 fork 根所在行起往下走，每一轮（含 fork
根自己）向右错一列、从脊线上伸出来，和主干轮次从 ROOT 的线上伸出完全同构。
分支以一条线开始，不以节点开始。只有胶囊和被取代的旧摘要——lane 里没有自己
的用户轮次——桥才直接连到字形本身。
线程条目（第十二节）不占 lane 宽度：它的列在 lane
落定之后再选，取锚点右侧最近的、在插入行处没有连线竖着穿过的列（这一列在插入行
以上和以下都有东西才算穿过）。完全在上方的不挡路，下方的会被整体推到线程下面，所以
不同行上的线程可以共用一列——两条打开的线程仍不共享格子，横线也不会为了绕开根本
碰不到这一行的 lane 而拉得很长。

### tier —— 分支内往右缩进几格

**对话层按 role 固定。** 执行层不再按 caller 深度缩进——展开的线程是一列扁平
的时间序（第十二节），因为图要回答的是"这一轮干了什么、按什么顺序"；逐调用
的嵌套是聊天流和 Executions 页的职责。

| 节点 | 层 | 列 |
|---|---|---|
| ROOT | 对话层 | tier 0 |
| user | 对话层 | tier 1 |
| llm 回复、merge | 对话层 | tier 2 |
| 线程条目（调用方块、spawn 头） | 执行层 | 锚点列 +1；嵌套展开的 agent 线程再 +1 |

### depth —— 第几行

链的行号按**结构父树的前序遍历**分配：每个可见链节点独占一行，子树占多少行就
把下方兄弟推多少行。行号**不是**"到根跳数"——那会把同一父的所有孩子叠在一行。

一个"横着长"的例外：fork 根与它平行的那条链兄弟**同一行**（场景 3），同一分叉
点的所有分支共享这一行——它们本就是同一轮的平行版本。每条分支桥接到紧邻左侧
的那条分支，而不是跨回主干，虚线桥因此是一段两格长的同行横线。

线程的行号**递归**分配（第十二节）：锚点的条目从它的下一行起（让开挂在它名下
的分支行）逐行往下；展开的 spawn 自己的线程接着它的行继续，它占的行把父线程
后面的条目往下推。链上锚点的线程落座后，它后面的对话层节点（以及已经落在插入
位置下方的线程行）按占用行数下移——展开是插入，不是覆盖。跨会话 spawn 落到目标会话时是该会话
自己的对话链（lane 0），不是侧枝（场景 12）。

---

## 二、三条全局排版规则

**① 方格网**：`COL_W == ROW_H`，子节点严格落在父节点右下角（45°）。画布的点阵
背景画的就是这张网（见上文"画布是无限的"），于是这一条是眼睛能验的性质，不是
代码作的承诺。

**② 严格对齐 + 紧凑化**：节点落在格点上；**空行上移补齐、空列左移补齐，不保留
空行空列**。本条适用于一切显隐变化：执行子树收起/展开、分支折叠、visibility
过滤——收起后它占的行列立刻腾出。**推论：任何"占位框"都违反本条**——running
状态用节点自身的色块表达（见图例），不画虚线占位节点。

**③ 字形占格，文字是注文**：一个节点占它那个格点；计数用注文灰挂在旁边，绝不
装进按自身文字定尺寸的形状里。跟着标签长的字形，是每个邻居都得拿它量一遍的
字形——这场谈判正是第十二节早先那颗药丸做错的事。所有字形（含第九节的压缩
胶囊）都是同一种圆角图块（第四节），各占恰好一格；网格在相邻图块之间留出一格
图块宽的空隙，图块间的传送带始终看得见。调用和你的消息在图标
右边带一行注文灰的说明（"Ran npm test""Read a.ts"、你写的开头；
`render/labels/captions.ts`）。注文只占没人用的地方：沿本行一直写到下一个图块、分支标签
或横穿的连线为止；正好从它起点竖着走过的分叉线，它会让到线的右边；地方不够就不画，
所以它从不挤动布局。agent 站着的那个图块改显示 agent 的气
泡；缩得很远时注文隐藏。

---

## 三、连线：颜色 = 分支，线型 = 类型（正交）

每条 lane 一个颜色（`LANE_COLORS`，即 `apps/web/app/styles/design/color.css` 里 `--lane-*` token 的 `var(--lane-N)` 引用；小地图经计算样式解析）。任何线用它所属/指向分支的
lane 色；**绝不给某类线固定颜色**。类型只靠线型：

**通往 HEAD 的路穿 HEAD 的颜色。** 几条分支共享的轮次（从 ROOT 到分叉处）属于你当前
所在的分支，所以它们、它们发起的调用以及它们的线都用 HEAD 的 lane 色
（`layout/assign-lanes.ts` 的 `_stampPathLanes` 戳上 `_pathLane`，`_branchColor` 优先读
它）。切到另一条分支，共享段就改画成那条分支的颜色；你离开的分支从分叉处往后保持自己
的颜色。每个轮次的线都从 ROOT 沿主干往下画，线会重叠：`render/edges.ts` 最后画这条
路，否则后画的分支会盖在它上面。

| 连线类型 | 线型 | 颜色 | 默认 |
|---|---|---|---|
| 同分支父→子 | 实线 | 本分支色 | 显示 |
| retry 分叉桥（起点 → 分支 lane 的脊线顶端，同行） | 虚线 `6 4` 横线；行错开时才走肘线 | 本分支色 | 显示 |
| 调用线程（锚点 → 它的条目，第十二节） | 1.4px 实线——主干模式下探一层：锚点自己的列一根竖线，每个条目一根右伸横杆（先下后右，和链上连线同构） | 锚点的分支色 | 展开时显示 |
| merge 汇入（peer tip → merge 节点） | 粗实线 2.4px | peer 分支色 | 显示 |
| attach 回流（源 tip → 嵌入位置） | 长虚线 `4 4` | 源分支色 | 两端都可见才画——agent 内部 tip 归并进三角形后不画线，spawn 头在线程上的位置就是返回关系 |
| 分支间通信（send_message） | 点线 `1 5` | 目标分支色 | **hover 才显示**（量大，常驻会糊） |

**链上连线和线程连线是传送带**：一条 8px 的中性底轨（`.dag-belt`，单独一层压在
所有线下面；不透明，共用主干或在路口相交的底轨叠在一起也不会变深），上面是 2px
的分支色线。通向工作的传送带会运货：分支色的小珠沿底轨朝工作中的节点移动，压
在实线下面，所以运行中的传送带不会被读成 ghost 虚线。链上的传送带在它通向的节点
自己运行时转动；线程的传送带在它通向的条目之下有任何东西运行时转动——正在进行的
调用，或 spawn 背后子 agent 的轮次——线程主干只转到那个条目为止。`paintBelts`
通过每条传送带的 `data-to` 从图数据算出这一点，所以原地状态补丁也会重画它。ghost
线保留虚线、不铺底轨：它不是下一次请求携带的内容。

**所有线一律画到节点中心**，由图块的底色填充盖住线头，不用量偏移，每种图块都
严丝合缝。

---

## 四、节点图例：图标图块 = 角色，色调 = 种类，状态 = CSS

**每个节点都是同一种圆形色块**（`apps/web/lib/runtime-bridge/dag/render/tiles.ts`）：
28px 的圆，底色是节点自己颜色的浅色（色调 18% 混进画布色，所以不透明，能盖住下面
的传送带线头），图标用全色。你的消息、回复和调用是同一家族；早先的版本把你的消息
画成灰色凸起按钮、其余是黑色方底板加 38% 的图标，整张图读起来是一堆互不相干的灰色
零件。每种状态都改变色块本身，像游戏里按下的按钮会亮起来——不在外面画任何东西：

| 状态 | 色块 |
|---|---|
| 普通 | 18% 底色，图标全色 |
| 悬停 | 30% 底色 |
| 选中（第十三节） | 填满自己的颜色，图标变成画布色，放大 8% |
| HEAD | 24% 底色，加一圈自己颜色的慢呼吸光晕 |
| 不在下次请求里（第八节） | 10% 底色，图标 60% |
| 报错 | 右上边缘的红色 `!` 角标 |

调用沿用 `presentTool` 在会话
记录里给它的图标和色调，"运行了 npm test"在两处长得一样；色调是共享 CSS 变量
（`apps/web/app/styles/tool-tones.css`）。对话节点有自己的：

| 节点 | 图标 | 色调 |
|---|---|---|
| ROOT | 房子 | 次级墨色 |
| user | 人像 | 所在分支的颜色，分支既能从线也能从消息认出 |
| agent 回复 | agent 的角色：主 agent 是会话所用 Agent 的角色，子 agent 运行里是子 agent 的角色 | 所在分支的颜色 |
| 调用 | 按工具（`presentTool`） | 按工具（shell、edit、read、search、web……） |
| 子 agent spawn | 子 agent 的角色 | 所在分支的颜色——派发 agent 就是一次调用；展开进入 agent 的活动（第十二节） |
| 压缩摘要 | 归档盒 | memory（第九节） |
| merge / attach | 合并请求 / 链接 | plan |

agent 的角色就是它头像的形状（[Agent 头像](../../ui/visual-system/agent-avatars.zh.md)），像图标一样平面绘制：身体用圆片的颜色，眼睛挖空、露出后面的圆片（`components/avatar/bot/glyph.ts`）。颜色取分支色而不是角色自己的颜色，所以分支仍能按颜色区分，圆片的所有状态（浅色、HEAD、选中、缩远）照旧适用。主 agent 穿会话所用 Agent 的角色：图的节点不带 Agent id，所以由 `components/chat/dag/dag-view.tsx` 报给 `render/agent-look.ts`，变化时重画整张图。子 agent 穿它名字（标签上显示的名字）对应的角色，规则和没设头像的 Agent 一样，所以两个子 agent 长得不一样，同一个子 agent 在各处长得一样。图例和运行记录面板的 agent 行画的是同样的图案。

**agent 站在它正在做的那一步上**（`render/agents.ts`）。每个正在工作的 agent
在它所在图块的左上角放一个分支色的状态圆点——就是 Activity 面板的 `indicator-dot`，工作时同样呼吸；同一图块上的第二个 agent 排在旁边；图块旁边一个气泡
写着"名字 · 在做什么"（图块的活动文字，英文用进行时："思考中…""运行 npm
test"）。agent 从整张图读出：一个节点属于它的链能追溯到的那个 spawn 根对应的子
agent，否则属于主 agent；每个 agent 显示它最新的运行中节点。那个节点被折进计数时，
圆点放在最近的已绘制图块上，气泡仍然说出那次调用；同一图块上的几个 agent 气泡上
下堆叠。

早先的版本在图块角上放一个写着 agent 首字母（"M"）的圆形令牌；没人看得懂这个字母，
而气泡本来就写着 agent 的名字；之后换成套在图块外的一圈环，又太抢眼。现在圆点标出*在哪*，气泡说出*是谁*。

**语义缩放。** 缩小时圆点和气泡保持屏幕上的大小，像地图上的单位标记
（`--dag-marker-scale`，由 `interaction/view/canvas.ts` 设置；标记以世界坐标钉在图块上，
只缩放它的本体）。agent 的圆点钉在图块的角本身，而不是这个角在 100% 时的屏幕偏移，
所以它跟着缩小的图块走，不会漂出去。低于 55% 时图标只剩几个像素的噪点，所以每个图块变成自己色调的
实心块（`is-far`）：地图靠颜色读，被覆盖的图块仍比其余的亮。图块自己已经是个 7px 的点，
旁边再放一个状态点就像两个节点，所以角上的圆点随图标一起隐藏；气泡自带的圆点仍标着在干活的 agent。

缩到这么小时，画布像地图一样读：地图缩小时地名保持可读、显示得更少；以前所有标签跟着
图一起缩成灰色小点。所以低于 55% 时：

- 圆点在屏幕上固定约 7px，相隔 14px 的相邻点不会粘在一起；线不细于 1.5px；点击范围保持约 10px；
- **选中的节点始终醒目**：有选中时，图的其余部分（点、线、文字）淡到 25%，选中的点保持
  本色（画布上的 `has-selection`，由 `interaction/selection/selection.ts` 设置）。不放大也不加
  描边：放大的点会和相邻的点糊在一起，墨色在浅色主题下是黑的，选中会变成一团黑。
  小地图用强调色把选中的节点画得更大，选中的东西在屏幕外也能在小地图上找到；
- 分支名和你的消息开头（`is-turn` 注文，`render/labels/captions.ts`）保持可读。实际上所有
  标签——注文、分支名、折叠数——在缩放低于 100% 时都走同一条平缓的曲线
  （`--dag-label-scale`）：100% 时 12px，最小缩放时约 8.5px。字先跟着图缩小、到 55%
  又跳回原大，看起来像故障；一路保持 12px，又挤成一堵字墙。从 100% 往下，
  `interaction/view/far-labels.ts` 把离已显示标签不足 8px 的隐藏——先分支名（当前分支优先），
  再按离 HEAD 由近到远排你的消息，最后是调用；
- 调用注文、折叠数和角标属于细节，隐藏；放大回来再看。

什么都没在运行时，主 agent 的圆点停在 HEAD
上，不呼吸，不带气泡。这一层从节点 DOM 重建，所以原地的状态补丁也会重画它。

**HEAD 是色块自己身上的呼吸光晕**：一圈色块颜色的 `drop-shadow`，以 2.4 秒的
慢周期胀起又落下，直接盖在形状上（`data-head`）。光贴着字形轮廓走，任何缩放
都跟随——不像画出来的光环圈，那读起来像旁边多了一个更糊的节点；也不像实心
填充，填充改掉了形状词汇本身，而光晕下 HEAD 仍然一眼是和邻居一样的图块，只是亮着。
`prefers-reduced-motion` 下脉动凝固成恒定光晕。HEAD 不带自己的覆盖标记：它是
唯一不可能离开上下文窗口的节点——下一次请求就落在它上面。

**status 映射**——状态画在节点自己身上，不画独立的虚线占位框：

| status | 画法 |
|---|---|
| success | 普通色块 |
| running | `is-running`：图标呼吸，它的 agent 的圆点和气泡出现 |
| error | `is-error`：右上角是 Activity 面板的红色角标，计数换成 `!`；色调不变，失败的 agent 回复仍是它自己颜色的角色 |
| cancelled | `is-faded`：色调变成 ghost 灰 |

**徽标**（附着在节点上，不占格）：

| 徽标 | 含义 |
|---|---|
| 折叠数（右上肩，注文灰） | 节点折叠的调用线程的大小——第十二节，写作 `+N`（"里面还有 N 个"）。贴着字形，没有任何包裹形状：带轮廓的东西会被读成节点。展开后消失——调用都在屏上，数得出来 |
| `↗`（右上角） | 跨会话 spawn 的**两侧都标**：目标 session 的第一个 user 节点标 `spawn_remote`，源 session 的发起节点标 `spawn_out`。目标投影把外部 caller 归到 ROOT；源 attach 卡片保留目标 session 和分支 head。跨会话 attach 的终点属于另一个图，因此不生成本图内 `attach_returns` 边。当前字形只标识跨会话关系，点击不会跳转。**只在跨会话时出现**：同会话 spawn 的两端在同一个图内，保留普通回流边，不加 ↗ |

---

## 五、分支名 badge

- **锚定**：分支**当前可见的最深节点**那一行，图块右侧，和消息旁的注记一样。默认（折叠）视图下就是
  最后一个对话层节点；调用线程展开时徽章跟到线程最底下的条目，收起时自动回去。
  分支归属按 lane（线程条目与锚轮同 lane），但只跟到本分支自己的后代：同 lane 的
  兄弟分支（从某一轮挂出去的定时任务回复）保留自己的末端。以前放在图块下方，名字
  会压到下一行；居中时长名字还会伸到左边的泳道，再被碰撞规则推到别的分支末端
  下面。图块上有 agent 气泡时名字让开，和注记一样。
- **spawn 的 agent 分支不立徽章**：agent 就是线程上的那个三角形（第十二节），
  再立分支药丸是同一事实的第二种画法。从分支行的 head 爬链撞到 spawn 根就
  直接不放。
- **避让**：名字在图块右侧，碰不到本列的下行竖线；沿行向右的线从字后穿过时被
  画布色光晕断开。
- **碰撞**：按**实测像素盒**判定（badge 底宽＝名字实测宽度 + 内边距，不是按格子）。
  短名字在方格间距下几乎碰不上；分支名自动取自消息/任务描述时很长，同行锚位的
  盒子会叠——后到者（按分支序）向下顺延一行，直至无碰撞。
- **来源**：badge 只来自 `list_branches` 的**活跃分支**（亮色、可点击 checkout）。
  **合并即消名**（git 语义）：被合并的分支不再画 badge；它的名字进 ◉ merge 节点
  的 tooltip（像 merge commit message 记录来源），session meta 里的名字数据保留。
- 样式沿用 HEAD 标签（`--bg-hover` 圆角底、9px 文字、实测文字宽度撑底）。

---

## 六、场景（SVG 权威在 spec.html，共 13 个）

| # | 场景 | 要点 |
|---|---|---|
| 1–7 | 基础布局（单轮/多轮/retry/工具缩进/手动函数/综合/收起左移） | 场景 4 的工具调用在默认视图下先表现为肩上折叠数（场景 11），展开后才是线程方块 |
| 8 | merge 多父汇聚 | ◉ 实心带孔圆、落 base 分支 lane、peer 汇入粗实线（peer lane 色）；attach pointer 节点不画，只画线 |
| 9 | 分支间通信（send_message） | 点线 `1 5`、目标分支色、默认隐藏 hover 显示；目标分支末尾加 from_branch user 节点 |
| 10 | spawn 派活 → 返回 | 子 agent 头是发起轮线程上的一个条目（第十二节）：落在派活实际发生的序列位置，前后是它前后的调用。返回不需要额外的线——它触发的 followup 回复归并进同一个锚轮（第〇节），派活、干活、返回从上到下读一列（聊天流仍渲染 Spawned 卡片，显示序提前——见 `ui/invariants.md` 规则 9） |
| 11 | 调用线程默认聚合 | 见第〇节/第十二节：默认收成肩上折叠数，点击展开进布局，收起按规则② 即时回收；各节点展开状态互不影响、可递归 |
| 12 | 状态与徽标图例 | 见第四节：status 画在节点色块上，不画占位框；跨会话 spawn 两侧都标 ↗ |
| 13 | badge 锚定·避让·碰撞·已合并 | 见第五节：名字放在本分支可见末节点那一行、图块右侧、碰撞下移一行、合并即消名（来源进 merge tooltip） |

**回送节点与切换器（语义补充，无独立布局场景）**：send_message 的回送
（子分支答复作为 user 节点回到发起方 lane，`predecessor=发起点`）若与用户等待
期间自己发的消息共享 predecessor，即构成 fork——**回送节点参与 `< N/M >`
切换器**（它是发起方对话的真实延续替代；`source=from_branch` 不做
agent_spawn 那样的隔离，隔离规则见 `ui/invariants.md` 规则 7）。回送节点是
接收方链上的一轮，不看它的 `caller`：`caller` 只记录发出它的那轮，所以它按
user 层（tier 1）排，回复在它右边一格，也从不算发送方的内部节点。它的标签是
发送方名字加正文：图数据从 `preview` 去掉 `[message from …]` 回执行，发送方
放在 `message_from`。

**子代理再 spawn**：默认派生预算下数据语义已禁止（`agent.max_spawn_depth=1`，
只有主 agent 能 agent()，被 spawn 的 agent 自己干活，见 `ui/invariants.md`
规则 6；调大预算就能再开代）。
渲染层本来就递归（第十二节——agent 线程上的 spawn 是一个普通三角形），历史
数据里的多代委托链照样画得出来。

## 七、渲染管线（代码地图）

```
apps/web/lib/runtime-bridge/dag/
  pipeline.ts        调度：passes → layout → edges → nodes → badges → visibility
  interaction/view/canvas.ts    无限画布：视角（平移 / 缩放 / fit）和显出网格的点阵
  interaction/view/gestures.ts  滚轮、捏合与拖动，它们移动视角
  render/seat.ts           读回已画元素的 translate(x,y)，给画完之后才跑的步骤用
  passes/            数据变换，按顺序：
    merge-runs.ts               合并同一节点的连续 run
    collapse-runtime-pairs.ts   把老式 display=runtime 的 user/assistant 包装对折成
                                一行（`caller` 边 schema 之前，包装行自身没有聊天内容，
                                单独画就是重复一列）
    demote-decoration-cards.ts  把 LLM 触发的 runtime 卡片改挂，避免"一条回复既有卡片
                                子节点又有后续 user 轮"被误判成 fork（那会把图劈成两条 lane）
    fold-summaries.ts           折叠压缩胶囊覆盖的区间（第九节）
    thread.ts                   调用线程模型（第〇节/第十二节）：followup 轮与
                                agent 内部轮归并进锚、事件按时间归入锚的线程、
                                按展开集算可见性
  apps/web/lib/runtime-bridge/dag/layout/geometry.ts 第一节的实现：链节点按 lane/tier/depth 打包成格点
                     （分支 lane 隔一空列、fork 根落兄弟行），再把每条展开
                     的线程递归安放在锚点旁边，按插入行数下移后续链行，并占用
                     每条线程列。
                     **tier 不在这里算**——由后端
                     `openprogram/state/store/session/graph/layout/tier.py` 算好随节点下发，
                     前端只消费。
  apps/web/lib/runtime-bridge/dag/render/edges.ts    第三节的线型表
  apps/web/lib/runtime-bridge/dag/render/nodes.ts    第四节的图块 + 状态 + 徽标
  apps/web/lib/runtime-bridge/dag/render/labels/badges.ts   第五节的分支名 badge
  apps/web/lib/runtime-bridge/dag/store/globals.ts   展开状态、lastGraph、签名
```

**一次绘制的开销。** 每次 capture 都整张重画 SVG，所以绘制器把两次 capture 之间不变的
东西留着：每个图标只解析一次、克隆进各个图块；工具的展示按名字、参数和语言缓存；文字宽度
按字体和字符串缓存。挂上新 SVG 时立刻设好它的 transform，需要面板尺寸的事都留到下一帧，
所以一次 capture 不会自己强制一次布局。手势只改 store 里的视角，`applyView` 每帧画一次。
平移只改两个平移量和点阵偏移；跟缩放比例绑定的工作——语义缩放变量、标签剔除、点阵间距——
只在比例或画出的图变化时才做。150 个节点的会话，一次重绘约占主线程 5ms。

后端 `openprogram/state/store/session/graph/builder.py` 产出节点数组（含 `branch_name` stamp、
caller/predecessor），`graph_layout/` 做 lane/tier/depth 标注——**tier 具体在
`graph_layout/tier.py`**。验证工具：
`python scripts/dag_dump.py <session_id>` 打印 lane/tier/depth + ASCII 网格。

## 八、填充 = 上下文覆盖

节点的填充表示它**属于下一次 LLM 调用会携带的内容**。被覆盖的图块
（`is-covered`，由 `apps/web/lib/runtime-bridge/dag/render/visibility.ts` 设置）图标
在带底色的色块上满墨；未覆盖的退后一步——底色降到 10%、图标 60%——快老化出窗口的
图标 75%。两者都看得清：38% 的图标会让长会话的大半张图都发灰。气泡、
注文和分支标签都是没有底块的文字，带一圈画布色光晕，线从后面穿过时在字周围断开。
两种主题同一条规则，图例色块就是一个被覆盖的图块。下文
的"白色填充""白点"都指这个填充。没有模式可选，也没
有开关要找：只要图在显示，它就独占面板。单个会话 tab 得到聊天外壳加这张图；
两个会话 tab 分屏时两侧都是 `PeerSessionPane`，外壳——以及这张图——根本不
渲染。所以图旁边永远不会有会话记录，"哪些气泡在视口内"给不出任何读数，白点
就只是覆盖这一个意思。

覆盖集由 `GET /api/sessions/{id}/context-range` 提供：从 head 回溯活跃分支，
止于最近一次压缩摘要，再加上每个被覆盖的轮做过的调用。前驱回溯只看得到轮——
调用是通过 `caller` 挂在它的回复下面的——所以路由补上 `render_context` 会读、
且对话层归属在集合里的 code 节点，每个紧跟在它的归属轮后面
（`openprogram/interfaces/server/routes/files/tree.py` 的 `_with_code_nodes`）。
没有这一步，每个展开的调用都画成"不在下一次请求里"，而 `aged` 这个 code 节点
才有的事实永远不会被置上。集合外的节点变暗。宿主调
`enterExclusiveCoverageMode`（`apps/web/lib/runtime-bridge/dag/index.ts`）拉取并
应用它。

### 覆盖数据形状

同一个响应逐节点带上上下文管线对"仍在携带的内容"施加的两级衰减：

```json
{
  "session_id": "…",
  "node_ids": ["…"],
  "count": 12,
  "nodes": [
    { "node_id": "…", "in_context": true, "aged": false, "spilled": true }
  ]
}
```

| 字段 | 含义 | 后端来源 |
|---|---|---|
| `in_context` | 节点在覆盖集内——每行恒为 true，因为这个列表**就是**覆盖集 | `get_branch` |
| `aged` | 老到结果被折成一行残根的 code 节点 | `openprogram/runtime/context/render.py::_aged_code_ids`，边界来自 `context/aging.py` |
| `spilled` | 结果已写入 `large_nodes/`，正文只留引用 | `metadata.spilled`，由 `state/store/session/spill.py::spill_if_large` 写入 |

两个标志都取自真实渲染路径调用的那几个函数，而不是平行的另一套实现——
**图永远不自己推导上下文语义**，它问后端，然后把答案画出来。

### 两级衰减怎么画

| 状态 | 画法 |
|---|---|
| 在上下文中 | 白色填充（基线） |
| `aged` | 被覆盖的色块淡一档（20% 色调）——读作"还在，但只剩梗概" |
| `spilled` | 节点**左**上角加 `▤` |

`aged` 压的是 **色块的色调，绝不是 `opacity`**：填充是覆盖信号，整体
变淡会把图标和徽标一起淡掉，两件独立的事就塌成一件。`▤` 占左上角是因为右上角已被
占用（`!` 报错、`↗` 跨会话 spawn），右下角是折叠徽标；用 `<text>` 画，免得
`_applyVisibility` 找"第一个形状子元素"时把它当成节点本体。

压缩会用一个摘要覆盖一段节点；被覆盖的节点直接落出 `node_ids`，所以白点只落
在摘要上，覆盖区间里一个都没有。图接下来拿这段区间做什么，见第九节。

刷新时机：`context_stats` 或 `compaction_finished` 到达即重拉覆盖
（`chat-handlers.ts`），所以白点跟着真实上下文走，前端从不自行计算。注意
`aged` 和 `spilled` **不进**渲染签名，所以应用新覆盖时要打掉签名
（`setLastSignature(null)`），否则重绘会静默 no-op，图会一直画着上一份答案。

与压缩的联动：

- `insert_summary_node` 不复制任何东西（dag/overview.md §8）：summary 是带
  `metadata.covers` 的普通 `role=llm` 链上成员，保留尾部保持自己的 id 与
  predecessor。因此分支 id **就是**图上画的 id，`/context-range` 直接返回
  它们——没有翻译层，也没有第二套 id 空间。
- summary 节点在数据关心的每一方面都和其他对话节点一样绘制；只有真正的合成
  桥会被过滤（`graph_layout/filter.py`）。它的胶囊是形状，不是 role——见第
  九节。
- 压缩后被覆盖的前缀落出集合，白点落在 summary 与保留尾部上。
- `compaction_finished` 必须触发 context range 刷新（`chat-handlers.ts`）；
  覆盖和其他一切一样事件驱动——前端永不自行计算上下文成员关系。
- 集合中没有对应图节点的 id（如 `display=runtime` 的 task-followup 行）
  静默忽略：它们在上下文里，但不在图上。

## 九、压缩读作一个胶囊，不是十四个变暗的轮次

把覆盖区间画成变暗，对每个节点说的都对，对整个会话说的却是错的：十四个浅色
圆圈照样占十四行，眼睛照样要走完它们才够得着活的对话。摘要是一个替所有这些
说话的节点，图就该这么画它。

**胶囊**。摘要节点在主线上画成双圈圆：基准圆内套一道细一号的同心内圈。
和其他字形同尺寸、占一格——内圈就是"这一轮装着比它显出来更多的东西"这句话。
内圈跟随外圈的颜色态（inert / superseded 时同为灰）。它仍然是
普通的 `role=llm` 链上成员（dag/overview.md §8）：形状就是形状，不是第四种
role。

**折叠数**。折叠的胶囊在右肩戴着被覆盖节点数的数字——与轮次调用线程的折叠数
（第十二节）同一套词汇，展开即消失，因为那时这摞被画出来了。没有文字注记：
字形（双圈）说明它是什么，数字说明收了多少，幽灵说明它开着，详情在
tooltip 和检查器里。

**折叠按分支生效**。摘要属于上下文携带它的那条分支——活跃链完整包含覆盖链段
的分支（context/compaction.md 第三节）。只有在这条分支上胶囊才折叠：覆盖区间
默认省略，点胶囊以幽灵态放回，再点收起（仅视图状态、永不落盘，新开会话一律
从折叠态起步）。展开态在切分支之间是黏性的：在某条分支上被覆盖轮次按原文
画过，摘要就记为已展开，切回携带分支时区间保持打开而不是重新收拢——看过就是
看过。在其他任何分支上——从覆盖范围内部分出去的、同时代的姐妹——
那些轮次就是活的上下文：按原文、按分支本色渲染，胶囊仍在屏上但呈惰性：保持
本色、无折叠交互、无角标、无白底——节点集合在每条分支上完全一致，变的只是
读法。切换分支时两种读法互换；存储的图分毫不动。

**幽灵态**。展开的区间保持分支本色；"不属于下一次请求"由入边虚线和白底的
缺席来说（白填充只落在上下文集合里的节点上），绝不靠把颜色抽成灰——灰色留给
死历史（失败废弃线、被取代的旧摘要），它们在任何分支上都永远回不了上下文。
可读、可点、明显不是活的："摘要到底有没有抓住我说的话"这个问题能被回答，
而答案永远不会被误当成上下文。

**滚动摘要**。压缩是接力式的：第二次压缩把第一份摘要的文本喂回 summarizer，
`extra_meta._last_summary_id` 指向替代者——下一次请求永远只带一份摘要，不会
叠加。图说同一件事：只有现役摘要拿到 `covers_ids`（胶囊 + 折叠）；被取代的
摘要保留行和胶囊轮廓，但带 `superseded_summary` 标记下发，画成幽灵灰，不折叠
任何东西。

**胶囊的位置**。一个槽位，在所有状态、所有分支上完全一致：覆盖链段的末尾。
展开时它跟在自己的幽灵后面（幽灵 → 胶囊 → 尾巴）；在不携带它的分支上它跟在
同样那几轮的原文后面（白底原文 → 镂空胶囊 → 其余）；折叠就是同一槽位把链段收
起，胶囊因此顶到主干最前。切分支、开合折叠都不改变位置——变的只有颜色和折
叠。所有摆位都是 `fold-summaries.ts` 里仅视图层的克隆改写；存储行在任何状态
下都保留真实的 `predecessor`（区间起点，即 ROOT）。

两种状态下白点都不会落在被覆盖的节点上，因为 `/context-range` 根本不列它。
一件事，一个来源（第八节）。

### 覆盖从哪来

持久化器写的是 `metadata.covers_ids`——摘要所替代的那些链节点的确切 id
（context/persistence.py）。是 id 而不是 seq 区间：在 DAG 里 seq 区间会横跨
姐妹分支，seq 恰好落进 `[first_seq, last_seq]` 的死分叉会被折进一个从未总结
过它的胶囊，而且 HEAD 一动答案就变。`openprogram/state/store/session/graph/builder.py` 把这份列表原样
下发，加上被覆盖轮次挂着的 caller 子树（被覆盖的轮连同它的调用一起折叠），
丢掉已不存在的 id，结果作为 `covers_ids` 放在摘要行上。

一个字段驱动全部：胶囊形状、折叠、褶皱数量、幽灵标记、检查器的覆盖行。前端不做
任何 seq 运算，也不调第二个接口。

## 十、失败轮以留档存在，不以警报存在

以 `status = error` 收尾的轮是终态节点；重试从它的前驱分叉，对话在新线上继续
（dag/overview.md）。失败线被保留——这正是选择分叉而不是回退的意义——但它永远
不可能重新进入上下文。

所以这样的节点一旦**离开 HEAD 链**，就画成和被覆盖轮同一种灰，检查器标注
`失败轮 · 已留档`。两种状态长得像，是因为在图唯一关心的那根轴上它们**就是**
一样的：在盘上、可读、永不进下一次请求。

这层灰有意覆盖图块的色调。红色 `!` 的意思是"这件事现在需要你"，
留档的线不是——重试已经发生过了。`!` 字形本身保留，所以这条线为什么终止仍然
一眼可读。

判定的两半缺一不可。只看 `status` 会把你正盯着的、还没重试的错误也刷灰；只看
离开 HEAD 会把每一条兄弟分支都刷灰。节点必须**既是失败、又已被放弃**。

`status` 是存储自己的终态标记，由轮次机制写入（取消的情形见
[统一运行控制](../execution/control.zh.html)，它保持 `cancelled`、沿用自己的 50%
灰化）。图读它，从不自己判定它。

## 十一、悬停、单击、右键、双击

一个问题一个面。信息窗曾经有三个——悬停卡片、停留后的二段展开、点击弹出的检
查器——单击因此同时干两件事：弹窗又切换线程，弹窗还正好盖在它刚触发的展开
上面。

**悬停 → 简略卡**。快速一瞥：角色（spawn 头标题写 `子 agent · <名字>`——
名字就住在这里，第十二节）、model/tokens、一段短内容预览、折叠调用数，节点在
运行中、已取消或失败时再加一行状态（完成是默认状态，不占一行）。token
数字在节点带实测值时用 `llm.output_tokens`，没有时用 `chars/4`；卡片明说是
哪一种（`tokens` / `tokens（估）`），没有文字的节点不给估算。键名共用一列固定
宽度，值因此对齐。悬停稍候出现、移开即走。展开后的卡片显示节点完整 id：派生
id（`<回复>_t_<调用>`）前十几个字符都一样。

**单击 → 节点自己的动作**。折叠/展开它的调用线程（第十二节）。没有别的——
没有窗口和展开抢画面。右栏 Details 仍然静默填充，用户想看随时打开。

**右键 → 同一张卡原地展开**。不是第二个窗口：就是那一个卡片元素在原地加深
（`apps/web/lib/runtime-bridge/dag/interaction/node/tooltip.ts expandTooltip`）——所有字段、更长的预览、覆盖状态、上下文站
位、id——动词接在卡底：checkout 到此分支 · 从此节点 fork · fork 并编辑此消
息（仅用户轮）· 复制节点 id · 查看原始 JSON。两个状态共用一个行构建器
（`renderNodeInfo`），不可能各说各话；覆盖行读的是节点绘制时已经戳好的 DOM
标记（`data-ghost`、`data-failed`、`.out-of-context`），卡片和它旁边那张图
也不可能各说各话。展开后卡片变成可交互并停驻——移开鼠标不再收卡、悬停不会
把它刷回简版，点击别处（或执行动词）才收。原始 JSON 复用检查器壳而不是弹模
态——模态会为了给你看图里的一个节点，把图整个拿走。

**双击用户轮 → fork 并编辑**。消息文本落进输入框，HEAD 已经退回它的分叉点。
其他节点保持 checkout 行为——回复和工具结果没有什么可编辑的。

### 每个动作都是既有操作

这里没有给协议添任何新动词：

| 动作 | 路由 | 为什么这就是全部实现 |
|---|---|---|
| checkout | `POST /api/chat/checkout` | 纯 HEAD 移动，和会话记录里的兄弟版本导航发的是同一个 |
| 从节点 fork | `POST /api/chat/checkout` | fork **就是** checkout 加上意图——从一个已经有子节点的 HEAD 发出的轮，定义上就是它们的兄弟，会话记录里的"从此分支"按钮也是这么做的 |
| fork 并编辑 | `POST /api/chat/checkout` 到该节点的**前驱**，再把文本填进输入框 | 用户改完发送；这个发送就是针对新 HEAD 的普通发送，于是分叉发生，协议不变，也不用维护"从节点 X 发"这个概念。选前驱做分叉点，正是因为编辑后的消息必须站在原消息**旁边**而不是后面——和 `POST /api/chat/edit` 产生的形状一致 |

检查器与菜单用命令式方式构建（`apps/web/lib/runtime-bridge/dag/interaction/node/inspector.ts`），因为图本身就是：它们浮
在渲染器自己拥有的 SVG 之上、锚在节点几何上，在 React 树之外。

**图例**。一张卡片，说明各形状与两种灰，由缩放竖列的图例按钮开关
（`apps/web/components/chat/dag/dag-view.tsx`），点画布不会关掉。默认关着——这套词汇很小、可学会，所以图例
是给最初几次会话用的，不是画布上的常驻件。

## 十二、调用线程：一轮干的事是一个序列，折叠成一个数

一轮干过的一切——每次函数调用、每个派出去的 agent——是一个按时间排序的事件
序列，这一轮的**线程**。调用和 spawn 是同一类事件的两个尺度，所以共用一条线、
一个顺序、一个折叠。一次回复调了 41 个函数、派了两个 agent 的会话，默认是三个
链节点加数字 `43`；展开是 43 个真节点，按实际发生顺序排一列。

**折叠就是折叠**。唯一的标记是节点右上肩的数字：注文灰的数字，贴着字形。不是
徽标形状、不是药丸、不是线上的小方块——任何带轮廓的东西都会被读成节点，而幻影
节点正是折叠最不能引发的误读。没有线程线、没有条目、没有别的。

**展开就是纯展开**。点节点把线程插进布局：一根锚点分支色的实线沿锚点自己的列竖直
向下，每个事件用一根右伸横杆挂在线上——先下后右，主干模式下探一层。每个事件
都是线上的真节点——每次调用一个方块（锚轮 lane 色），spawn
的 agent 也是方块——一行一个事件，从上到下按调用顺序。后面的 user / assistant
节点按插入的行数下移，锚点列上的线程竖线在下一颗三角形之前结束。每条打开的
线程占用自己的列。收起按规则②
回收行。

**头就是 agent，spawn 就是调用**。spawn 根画成方块——派发 agent 就是一次
函数调用，方块就是调用词汇。派发调用节点（`agent` / `send_message`）归并进
它：一次 spawn 一颗字形（没开出 spawn 的派发调用保留自己的方块——那次失败值得
一颗节点）。agent 的内部轮不上链——归并进它（第〇节），展开后回复画三角形、
调用画方块——它自己的线程再右移一列，点方块展开。spawn 方块在屏上期间（即所属轮次
的线程已展开——这层选择已经保证默认画布干净），它右侧贴一枚徽章药丸（与分支
徽章同款，apps/web/lib/runtime-bridge/dag/render/labels/badges.ts），作方块的名牌；点击把 agent 链的末端
checkout 成活动分支——接管这个 agent 的对话。徽章永不压住节点：所有可见字形
都预置进徽章碰撞盒，会压住节点的徽章自动下移一行。模型是递归的，画面也是：每一层都按同样的两
条规则读，折叠数在肩上、展开成一列。嵌套展开的线程把父线程后面的条目往下推；
链上锚点的线程同样插入后面的对话轮。展开是插入，不是覆盖。

**没有注文**。agent 的名字住在 tooltip 和 inspector 里（inspector 把节点标题
写作 `子 agent · <名字>`，而不是 role 字段所说的 `user`）；画布只有字形和折叠
数。名字在线上来自 runner 戳的 label（`spawned_from.label`），没有时回落到记录
下来的分支名。

**没有回流线**。agent 的返回触发一轮 followup 回复，而那轮回复归并进线程所属的
同一个锚（第〇节）——派活、干活、返回从上到下读一列。旧的 attach 回流虚线只在
两端都是链上可见节点时才画，而 agent 内部 tip 从此不可见。

**视图状态**。`apps/web/lib/runtime-bridge/dag/store/globals.ts` 的 `_threadOpen`，按锚点 id 记（链轮或 spawn
头——同一套词汇）。从不持久化，切会话清空，和第九节完全一致。spawn 头只在它
上方整条线程链都展开时可见；它的条目同理——可见性属于整条祖先链，不属于节点
自己的开关。

## 十三、鼠标、操作说明、选择与删除节点

画布只有一个鼠标，没有可切换的工具。以前把浏览、框选、套索拆成三个工具，每次拖动前
都得先想手里拿的是哪个。现在一个鼠标全包：左键选择，右键移动镜头。

| 手势 | 做什么 |
|---|---|
| 单击节点 | 选中它，再执行节点自己的动作（第十一、十二节） |
| 在空白处拖动 | 画框，碰到的节点全部选中 |
| Shift/⌘ + 单击或拖动 | 加入选择，或把节点从选择中去掉 |
| 单击空白处 | 清空选择 |
| 右键拖动 | 平移，在图上任何地方都行（鼠标中键也平移） |
| 右键单击节点 | 它的菜单（第十一节） |
| 滚轮或捏合 | 以光标为中心缩放 |
| 触控板双指滑动 | 平移 |
| 双击节点 | fork 并编辑（第十一节） |

鼠标滚轮像地图一样缩放；触控板双指滑动平移；捏合用自己的、更快的速率缩放。macOS 在右键按下时
就触发菜单事件，那时还不知道会不会拖动，所以画布先拦下它，松开时指针没动才打开菜单。
这些是设计定死的，不是设置项：碰到即选（没有"必须全包住"模式）（`apps/web/lib/runtime-bridge/dag/interaction/view/gestures.ts`、
`interaction/node/nodes.ts`、`interaction/selection/selection.ts`）。

画布上的控件都是应用按钮材质的凸起条（输入框底色加 composer 阴影，鼠标放上去阴影变深，和输入框那些按钮一样）：缩放竖列、操作条、小地图和窗格右上角的按钮。画布左缘没有竖条。
**找到正在工作的 agent**（F，在缩放竖列里）保持缩放，把视图平滑移到正在工作的 agent 站着的图块；再按
换到下一个正在工作的 agent，没人工作时移到 HEAD（`interaction/view/canvas.ts` 的
`focusAgent`）。缩放在右缘的缩放竖列里（见“画布是无限的”）。竖列最后一个按钮（notes 图标——面板里一半是鼠标手势，不只是按键）打开**操作说明面板**：画布认的所有手势和按键，按鼠标、
镜头、选择分组，显示在竖列左边、从顶部展开的面板里（`components/chat/dag/dag-key-sheet.tsx`）。按 `?`
也能打开。它和图例一样是指南，行为也一样：一直开着，直到再点它的按钮、再按 `?`，或者打开图例把位置换掉；点画布、按 Esc 都不会关掉它。Esc 一次只退一层：先取消选择，再退出全屏。视图快捷键沿用设计工具的习惯：Shift+1
缩放到全图，Shift+0 回到 100%，+ / − 按一档放大缩小，和缩放竖列的按钮同一步长
（`interaction/selection/keys.ts`）。

**选择。** 选择是当前会话画布的视图状态。被选节点原地亮起（`is-selected`）：色块填满自己的颜色，图标变成画布色，像按下的按钮。外面不画任何东西——虚线圈、套在方块外的圈、图块后面的灰色亮盘都试过，都让边缘更难看清。框选的选择框是强调色描边加 8% 的强调色底。
每次重绘后重新套用，并裁剪到画布仍画着的节点，所以被删除或被折叠掉的节点会自动离开
选择；切会话时清空。在画布上做选择会把键盘焦点从输入框拿走，于是 Delete 和 Esc 作用
于选择，不作用于草稿。

**操作条。** 有选择时，画布左上角出现一条操作条：`已选 N | ⌖ · 复制 ID · 删除 · ✕`，
"删除"用危险色。⌖ 把视图缩放到正好装下所选节点，和设计工具的 Shift+2 一样（`interaction/view/canvas.ts` 的 `frameSelection`）。删除后几秒内它显示 `已删除 N 个节点 | 撤销`。它在左上角，
不放右上角——那里是窗格的视角切换按钮。操作条和竖列是同一种凸起材质。

**删除。** Delete 或 ⌫ 立即删除选择，不弹确认，⌘Z 撤销。store
（`openprogram/state/store/session/session_store/node_deletion.py`）按以下规则执行：

- 只删被选节点，以及它们经 `caller` 拥有的东西：回复的工具调用、调用的子调用、调用
  派生的 agent 分支。只是在对话里排在后面的节点保留。前驱被删的存活节点改指向最近的
  存活前驱，所以删一个节点会把缺口接上，就像在流程图里删一个方框。
- 一个字形代表它显示的所有行。归并进锚点的 followup 回复（第十二节）随锚点一起删；
  选中 spawn 方块删的是派生它的调度调用，agent 分支随之一起删。
- 结构节点不能删：根节点、单独的 spawn 分支根、压缩摘要、attach/merge 机制节点。
  画布不把它们放进请求，store 也会拒绝。
- HEAD 被删时移到最近的存活前驱。被删分支尖上的分支名也随之移过去。
- 不直接删除文件。节点文件移到 `<sessions 根>/.deleted-nodes/<session>/<op_id>/`
  （在会话 git 仓库之外），同时写一份日志，记下每条边、HEAD 和分支名的变化。超过
  24 小时的回收内容在下次删除时清理。
- 撤销按日志倒放。此后被别的操作改动过的边或 HEAD 保留新值。
- 有轮次在运行时两个动作都拒绝执行：正在跑的轮次可能正往要删的节点下面写。

线上格式：`delete_nodes {session_id, node_ids}` → `nodes_deleted
{ok, op_id, deleted, error}`；`restore_deleted_nodes {session_id, op_id}` →
`nodes_restored`（`openprogram/interfaces/server/ws_actions/dag_nodes.py`）。
成功时还会广播 `session_reload`，聊天记录和图一起重绘。撤销栈按会话分开，页面存在期间
一直有效。

### 小地图

长会话会超出屏幕，所以画布有一张小地图，放在画布右上角、缩放竖列左边，材质与竖列相同。每个
节点是一个其色调的点，点下面画着图里原有的连线（细、淡、用分支颜色，主干和分支一眼可辨），屏幕上看到的部分是一个强调色的框。在地图上按下或拖动，镜头就以当前
缩放移到那里。地图框住的是整张图加上当前视野，所以视野框不会被裁掉；拖动期间地图保持不动。HEAD 画成带强调色描边的大点，就是地图上的"你在这里"；在地图上滚动滚轮，画布以视野中心缩放。默认隐藏，点竖列里的小地图按钮或按 M 显示、再按一次隐藏，选择保存在浏览器里。显示之后它一直在屏幕上：以前整张图装得下时地图会淡出，
随着缩放时有时无，看起来像出错
（`apps/web/lib/runtime-bridge/dag/interaction/view/minimap.ts`，随视图每帧重绘一次；点、线和
颜色每张图只读一次）。

## 附录：实现状态

本规范已全部实现。各部分的落点：

| 规范条目 | 实现 |
|---|---|
| 无限画布（平移 / 缩放 / fit / 点阵） | `apps/web/lib/runtime-bridge/dag/interaction/view/canvas.ts` 与 `apps/web/app/styles/dag/graph/canvas.css` 的 `.history-body`；视角状态在 `apps/web/lib/runtime-bridge/dag/store/globals.ts`；缩放竖列在 `apps/web/components/chat/dag/dag-view.tsx` |
| 第一节 lane / tier / depth 布局 | `apps/web/lib/runtime-bridge/dag/layout/geometry.ts::computeGeometry`（链 lane 按 tier 打包并 lane 内归零、前序分行、场景3分叉行+间隔列、线程递归安放并下移后续链行、占用线程列）；格点性、无重叠、线程列行、分叉几何均由 `apps/web/tests/dag/dag-subagent-thread.test.mjs` 真实执行并断言 |
| 第二节 规则③ 字形占格 | 没有任何形状按文字定尺寸；注文只占空格子，不挤动布局（`render/labels/captions.ts`） |
| 第四节 HEAD 呼吸光晕 | `apps/web/lib/runtime-bridge/dag/render/nodes.ts` 戳 `data-head` 并把分支色写进 `color`；`dag-head-glow` 关键帧在 `apps/web/app/styles/dag/graph/nodes.css`（reduced-motion → 恒定光）；所有字形保持空心（`apps/web/lib/runtime-bridge/dag/render/shapes.ts`）；HEAD 指向已归并回复时落到锚上（`apps/web/lib/runtime-bridge/dag/pipeline.ts` 经 `threadModel.anchorOf`） |
| 第〇节/第十二节 调用线程聚合 | `apps/web/lib/runtime-bridge/dag/passes/thread.ts`（`buildThreadModel`：锚归并、事件归属、递归可见性）；`apps/web/lib/runtime-bridge/dag/render/nodes.ts` 画肩上折叠数（`history-thread-count`）；`apps/web/lib/runtime-bridge/dag/store/globals.ts` 的 `_threadOpen` |
| 规则②推论（不画占位框） | `apps/web/lib/runtime-bridge/dag/render/shapes.ts`：无 `square_outline`；task 渲染为普通方块 |
| 第四节 状态画在描边上 | `graph_builder` 下发 status；`nodes.ts` 把它设成图块的 CSS 状态（running 呼吸 / error 红色 ! / cancelled 灰化） |
| 第五节 badge 锚定 | `apps/web/lib/runtime-bridge/dag/render/labels/badges.ts`：名字放在本分支可见末节点那一行、图块右侧、实测像素盒碰撞下移一行 |
| 场景 8 merge 形状与连线 | `apps/web/lib/runtime-bridge/dag/render/shapes.ts` `merge_dot`（◉）；`edges.ts` 汇入线 peer 色 2.4px 实线 |
| 场景 8/10 attach 指针 | 后端 display=runtime 过滤 + `graph_builder` 把 ref 戳到嵌入位置（`attach_returns`），`edges.ts` 画回流长虚线 |
| 第四节 跨会话 ↗ | `graph_builder` 根据目标根 provenance 打 `spawn_remote`，根据源 attach 的目标 session 打 `spawn_out`；`nodes.ts` 在两侧画 ↗。跨会话徽标点击跳转尚未实现 |
| 第一节 spawn 根 tier | `graph_layout`：tier=1 / depth 同行 / lane 开新分支；`job_followup` / `process_exit` 回复挂回接收轮（`filter.py` 兜底） |
| 两个视角共用输入框 | `apps/web/app/styles/chat/pane/center-pane.css` 隐藏 `#chatArea` 而非 `#chatView`；由 `apps/web/tests/tabs/center-perspective.test.mjs` 断言 |
| 图内分支标签（checkout 按钮） | `apps/web/lib/runtime-bridge/dag/render/labels/badges.ts`；hover 样式在 `apps/web/app/styles/dag/graph/badges.css` 的 `.history-branch-tag` |
| 第八节 覆盖查询 | `routes/tree.py::_coverage_nodes` 填 `/context-range` 的 `nodes`；测试见 `tests/unit/context/test_context_range_coverage.py` |
| 第八节 aged / spilled 绘制 | `apps/web/lib/runtime-bridge/dag/render/nodes.ts`（淡一档的色块 + `▤`），数据来自 `apps/web/lib/runtime-bridge/dag/store/globals.ts` 的 `_coverageSet` |
| 第九节 `covers_ids` 下发 | `openprogram/state/store/session/graph/builder.py` 把 `metadata.covers` 解析成 id；测试见 `tests/unit/dag/test_graph_builder_covers.py` |
| 第九节 胶囊形状 | `apps/web/lib/runtime-bridge/dag/render/shapes.ts` 的 `capsule`（按 `covers_ids` 判定，打 `data-shape` 标让 `_applyShapeSize` 别改它的几何） |
| 第九节 折叠 / 褶皱 / 幽灵 | `apps/web/lib/runtime-bridge/dag/passes/fold-summaries.ts`（折叠）、`apps/web/lib/runtime-bridge/dag/render/nodes.ts`（褶皱、`已压缩 · N 轮` 注记、幽灵描边）、`apps/web/lib/runtime-bridge/dag/render/edges.ts`（幽灵虚线边）、`apps/web/lib/runtime-bridge/dag/store/globals.ts` 的 `_summaryExpanded`；由 `apps/web/tests/dag/fold-summaries.test.mjs` 实跑 |
| 第十节 失败留档 | `apps/web/lib/runtime-bridge/dag/render/nodes.ts::_isArchivedFailure`——`status=error` **且**离开 HEAD 链；灰覆盖色调，`!` 保留 |
| 第十一节 一张卡两个状态 / fork 并编辑 | `apps/web/lib/runtime-bridge/dag/interaction/node/tooltip.ts`：`renderNodeInfo` 喂两个状态，`expandTooltip` 原地加深；`apps/web/lib/runtime-bridge/dag/interaction/node/inspector.ts` 只构建动词列表（+ 原始 JSON 层），`apps/web/lib/runtime-bridge/dag/interaction/node/nodes.ts` 接线；动作走 `POST /api/chat/checkout` |
| 第十一节 图例 | `apps/web/components/chat/dag/dag-view.tsx` 的 `DagLegend`（挂在缩放竖列里），`apps/web/app/styles/dag/panels/legend.css` 的 `.dag-legend` |
| 第十二节 调用线程 + agent spawn | `apps/web/lib/runtime-bridge/dag/render/shapes.ts`（spawn → 方块）、`apps/web/lib/runtime-bridge/dag/passes/thread.ts`（模型）、`apps/web/lib/runtime-bridge/dag/layout/geometry.ts`（递归安放）、`apps/web/lib/runtime-bridge/dag/render/edges.ts`（线程点线、中心连线、场景3横桥）、`apps/web/lib/runtime-bridge/dag/render/nodes.ts`（`data-thread*`、肩上折叠数）、`apps/web/lib/runtime-bridge/dag/interaction/node/nodes.ts`（`toggleThreadOpen`）；由 `apps/web/tests/dag/dag-subagent-thread.test.mjs` 实跑 |
| 第十二节 名字上线 | `task/runner.py::_update_attach_card` 从 task 戳出 `attach.label`；`ws_actions/session/transcript.py::_annotate_spawn_origin` 把它带到 spawn 根的 `spawned_from.label`；测试见 `tests/unit/test_task_attach_integration.py` |
| 第十三节 鼠标、操作说明、选择、删除 / 撤销 | 选择状态、命中判定和选择框在 `apps/web/lib/runtime-bridge/dag/interaction/selection/selection.ts`；拖动在 `gestures.ts`，单击在 `nodes.ts`，快捷键在 `keys.ts`；扩展选择与撤销栈在 `node-delete.ts`；操作条在 `apps/web/components/chat/dag/dag-tools.tsx`，缩放竖列在 `dag-view.tsx`，操作说明面板在 `dag-key-sheet.tsx`，小地图在 `interaction/view/minimap.ts`，+ `apps/web/app/styles/dag/panels/tools.css`；store 拼接与日志在 `openprogram/state/store/session/session_store/node_deletion.py`；测试见 `tests/component/store/test_node_deletion.py` 与 `apps/web/tests/dag/dag-selection.test.mjs` |
