# Web 样式组织

Web 端 CSS 按组件树组织：一个组件（或一个紧致的关注点）一个文件，目录与
UI 自身结构对齐。调某个组件的样式，就打开以它命名的那一个文件。

## 布局

```
apps/web/app/
  globals.css       入口：tailwindcss → design → themes → styles
  styles/
    index.css       按层叠顺序引入全局样式层
    design/         设计 token，以及给 Tailwind 的工具类名
    themes/         各主题的颜色取值，一个主题一个文件（含 fallback.css）
    base/           文档、焦点、列表行、外壳布局、滚动条、侧栏、
                    桌面窗口外框、动效、画布拖拽
    chat/           每个聊天组件一个文件，按区域分目录
      pane/ messages/ cards/ execution/ composer/ welcome/
    dag/            DAG 渲染器每个关注点一个文件
      graph/ panels/
    right-dock/     右侧栏各面板
```

`app/styles/index.css` 按层叠顺序（base → chat → right-dock → dag）导入整棵树。token 本身，以及哪个组件用哪一档，见[设计 token](design-tokens.zh.md)。

## 规则

- **一个组件一个文件。** 文件只写它命名的那个组件的样式。每个文件开头
  一段注释：这是哪个组件、对应的 tsx/ts 源路径。
- **归属跟着组件树走。** DAG 节点样式属于 `dag/graph/nodes.css`，因为绘制器在
  `lib/runtime-bridge/dag/render/nodes.ts`；聊天气泡样式属于
  `chat/bubbles.css`。新组件开新文件，不往旧文件里追加段落。
- **真正全局的留在全局。** token 在 `design/`，主题取值在 `themes/`，外壳在 `base/`；聊天列
  骨架（`.main`、`#chatView`）是 `chat/layout.css`——唯一有意跨组件的
  文件，名字点名了用途。
- **module CSS 保持 module CSS。** 已用 `*.module.css` 的组件（输入框）
  维持原样；本树只覆盖全局样式层。
- 对样式源做断言的测试通过 postcss 读对应的组件文件
  （`tests/tabs/canvas-css-geometry.test.mjs` 读 center-tabs 的样式模块校验标签条尺寸）。
- **不用原生滚动条。** `base/scrollbar.css` 以零优先级在所有元素上隐藏
  原生滚动条：macOS 的 Chromium 在指针进入可滚动区域时会闪出原生滚动条，
  静止的面板只因鼠标停在上面就亮起来。`lib/runtime-bridge/dom/scrollbar.ts`
  在一个区域第一次滚动时给它装上细的悬浮滑块（竖向；横向溢出时还有横向）。
  滑块只在区域滚动或被按住时显示，900ms 后淡出，不占布局宽度。悬停、改
  尺寸和内容变化只移动它，不显示它；淡出的滑块不接收指针事件，鼠标划过区域
  边缘不会把它点亮。shadow root 里的滚动区域样式表和文档
  的滚动监听都够不着，由它自己隐藏原生滚动条并调用 `attachOverlayScrollbar`。

## 文字

所有字号和字体都出自同一处，所以从一个页面切到另一个页面，文字不会变样。

- **字号只有九档。** `design/type.css` 定义了 `--fs-2xs`（11px）到
  `--fs-display`（30px）；哪段文字用哪一档，见[字号](design-tokens.zh.md#字号)。
  `scripts/ui/check-design-tokens.mjs`（`npm run check` 运行）拒绝其他任何字号。
- **字体在首帧前加载。** Inter 和 JetBrains Mono 的拉丁字形走 `next/font`
  （`app/fonts.ts`）：随 HTML 预加载，`display: block`，文字不会先用备用字体
  画出再重排。其他文种用 `@fontsource` 的字体。
- **首帧就是正确的语言。** 导出的 HTML 是英文。其他语言时 head 脚本给
  `<html>` 打上 `data-locale-pending` 把 body 藏起来；`useTranslation` 在
  layout effect 里、浏览器绘制前切好语言并去掉标记。脚本没跑起来的页面
  1.5 秒后自动显示。
