<div id="ui-unification-work"></div>

# UI 统一工作

本文记录 OpenProgram 各界面的 UI 不一致，并按优先级列出统一视觉风格的工作。

<div id="context"></div>

## 背景

OpenProgram 包含多个 UI 界面：
- **Web 应用** (`apps/web/`) — 主要浏览器界面
- **CLI/TUI** (`apps/cli/`) — 终端界面
- **文档站** (`scripts/docs_site/`) — 文档网站
- **宣传页** (`website/index.html`) — 落地页
- **桌面窗口框架** (`apps/desktop/main.js`) — Electron 窗口框架

各界面独立演化，导致配色、排版和设计 token 出现差异。

<div id="current-appearance"></div>

## 当前外观

设置默认打开常规页。外观采用类似 Obsidian 的分层结构，保留 schema 3（模式 × 命名主题包）：

- **模式**：自动 / 浅色 / 深色。自动跟随系统；它属于模式，不是主题。
- **主题包**：仅 Beige / Neutral / Aurora / Vivid。每个包都有浅色和深色 `data-theme`。Custom 不作为单独的皮肤。Vivid（彩色）沿用 Beige 的面板，顶部标签栏是彩色的。标签栏颜色是单独的设置，从 Chrome 深色模式的同款颜色里选（存在 `agentic_tabrow_color`，以 `--tabrow-seed` 生效）；浅色模式用同一色相的淡色。Vivid 的所有面板、文字层级和默认强调色都是该色相的 `oklch(from var(--tabrow-seed) …)` 色调，和 Chrome 彩色主题一样。
- **强调色**：颜色输入框、取自各主题包默认 `--accent-orange` 的预设，以及恢复主题默认值。空值/默认值使用当前主题包的强调色。覆盖设置写入 `--accent-orange`、`--accent-fill` 及派生的 `--accent-orange-hover`。
- **CSS 叠加层**：用户 CSS 叠加在所选主题包之上，由“启用自定义 CSS”控制。“插入模板”写入以 `html` / 当前 `data-theme` 值为目标的初始模板。“清空”清除片段。旧 `[data-theme="custom"]` / `[data-theme="custom-light"]` 选择器改写为 `data-custom-css`，以继续生效。

存储保持 schema 3（`agentic_theme_style` + `agentic_theme_mode`）。强调色使用 `agentic_theme_accent`。叠加层开关使用 `agentic_custom_css_enabled`。合并的 `agentic_theme` 值仍执行迁移：

- `auto` → beige + auto
- `beige-dark` / `beige-light` → beige + dark/light
- `dark` / `light` （schema 2） → neutral + dark/light
- `aurora` / `aurora-light` → aurora + dark/light
- `vivid` / `vivid-light` → vivid + dark/light
- `custom` / `custom-light` → beige + 已保存模式；存在已保存自定义 CSS 时启用叠加层

`custom` / `custom-light` 保留为旧片段的回退主题 ID 和 CSS 文件，不显示为样式卡片。主题约定继续验证六个内置主题包 token 文件；默认强调色继续取自这些 CSS 文件。

<div id="later-work-prioritized-todo"></div>

## 后续工作（按优先级排序）

以下不一致仍然存在，应在后续 PR 中处理。

<div id="1-web-token-cleanup-high-priority"></div>

### 1. Web token 清理（高优先级）

**问题：** `base.css` 中的 `:root` 回退混用了 beige 表面色和 neutral 蓝色强调色。

```css
/* base.css :root claims to be beige-dark but has: */
--accent-orange: #6ea8fe;  /* This is neutral blue, not beige coral */
```

**文件：**
- `apps/web/app/styles/base.css` — 回退配色应统一为 beige-dark

**操作：** 决定 `:root` 回退使用 beige 还是 neutral，再统一强调色。

---

<div id="2-docs-site-palette-drift-high-priority"></div>

### 2. 文档站配色偏差（高优先级）

**问题：** 文档站（`scripts/docs_site/assets/site.css`）声称跟随 `base.css`，但数值存在差异：

| Token | 文档浅色 | Web beige-light | 文档深色 | Web beige-dark |
|-------|------------|-----------------|-----------|----------------|
| `--acc` / `--accent-orange` | `#b8651f` | `#c15f3c` | `#d19a66` | `#d97757` |
| `--bg` / `--bg-primary` | — | — | `#1f1f1e` | `#191918` |

**文件：**
- `scripts/docs_site/assets/site.css`
- 存储键为 `op-docs-theme`（仅 light/dark），独立于应用主题

**其他偏差：**
- 文档正文字号为 15.5px，应用为 `--fs-base: 14px`

**操作：** 将文档配色与 Web 的 beige 主题对齐，或明确记录文档站独立。

---

<div id="3-clitui-theme-mismatch-medium-priority"></div>

### 3. CLI/TUI 主题不一致（中优先级）

**问题：** CLI/TUI 始终使用 Claude 橙色 `#d97757`，不受 Web 主题影响。Python/Rich 设置向导不读取 Web token。

**文件：**
- `apps/cli/src/theme/themes.ts` — TypeScript 主题定义
- `openprogram/interfaces/cli/repl/banner.py` — Rich 颜色（bright_blue、rainbow）
- 设置向导注释提到“OpenClaw-style”

**操作：** 二选一：
- 让 CLI/TUI 读取 Web 主题偏好并应用一致颜色，或
- 明确记录 CLI 有意采用独立品牌风格

---

<div id="4-marketing-page-independent-brand-low-priority"></div>

### 4. 宣传页独立品牌风格（低优先级）

**问题：** 宣传页（`website/index.html`）采用第三套品牌风格：

```css
--bg: #07080a
--teal: #5eead4
--violet: #a78bfa
```

桌面图标 SVG 使用蓝色/紫色（`#4A9FE1` / `#915FD5`）。

**操作：** 决定宣传页与 Web beige/neutral 对齐还是保持独立。

---

<div id="5-desktop-chrome-follows-the-resolved-theme"></div>

### 5. 桌面窗口框架跟随已解析主题

Electron 窗口首次显示的像素与已解析的 Web 主题一致。创建 `BrowserWindow` 时使用该主题的 `--bg-primary`，不使用 `#141416`。

解析使用 Web 应用写入的相同 schema-3 键（`agentic_theme_style` + `agentic_theme_mode`，以及旧 `agentic_theme`）。桌面端先读取 userData 下的 Chromium localStorage，再读取主题更改时写入的 `theme-prefs.json` 缓存。`auto` 跟随 `nativeTheme.shouldUseDarkColors`。

`apps/desktop/main/windows/theme-chrome.js` 保存从 `apps/web/app/styles/themes/*.css` 复制的 `--bg-primary` / `--accent-orange` 映射。存储的 `custom` / `custom-light` 解析为 beige 配色对（`#191918` / `#faf9f5`）。Worker 错误页和目录列表 HTML 使用相同窗口框架 token；设置强调色覆盖时，列表/错误链接使用该强调色，而窗口 `backgroundColor` 保持主题包的 `--bg-primary`。主题更改后，渲染器调用 `theme.setChrome`，更新每个 `BrowserWindow` 的背景，避免下次显示/重新加载时闪现旧颜色。

窗口状态持久化（普通边界与最大化/全屏、显示器回退、标题栏缩放命中测试）保持不变；参见 [window-state.md](../desktop/window-state.zh.md)。

---

<div id="6-ghost-tokens-spec-drift-low-priority"></div>

### 6. 缺失约定的 token / 规格偏差（低优先级）

**问题：** 代码使用但未纳入 58-token 约定，或已写入规格但未实现的 token：

**已使用但未纳入约定：**
- `--text-dim` （用于 manage-page、files-panel、plugins、skills；约定中为 `--text-muted`）

**已记录但未实现：**
- `--bg-surface` （在 `surface-system.md` 中提及）
- `--text-on-accent` （在规格中提及）

**文件：**
- `docs/reference/design/ui/visual-system/surface-system.md`

**操作：** 将缺失 token 加入约定，或移除引用。

---

<div id="7-button-spec-drift-low-priority"></div>

### 7. 按钮规格偏差（低优先级）

**问题：** 管理页标签使用 `border-radius: 6px`，并且仍从 `--ui-button-h` / `--ui-button-radius` 取尺寸；而 `button.tsx` 现在是官方 shadcn radix-nova Button（`rounded-lg`，官方 `xs`–`lg` 尺寸，见 `surface-system.zh.md`）。

**操作：** 把剩下手写尺寸的按钮和标签换成官方 Button 尺寸，然后删掉 `--ui-button-h` / `--ui-button-radius`。

---

<div id="8-naming-debt-low-priority"></div>

### 8. 命名待改进项（低优先级）

**问题：**
- `--accent-orange` 用于蓝色/青色主题（命名易混淆）
- shadcn `--accent` 表示 `--bg-hover`，而非主色
- `dark.css` / `aurora.css` 中过时注释仍提到“coral”

**操作：** 将 `--accent-orange` 重命名为 `--accent-primary` 或类似名称，并更新过时注释。

---

<div id="9-mixed-component-kits-low-priority"></div>

### 9. 混用组件库（低优先级）

**问题：**
- 输入框菜单使用 Base UI
- 应用其余部分使用 Radix/shadcn
- 强度颜色逻辑（`effort-color.ts`）使用独立 HSL，而非主题强调色
- 浏览器图形（`center-tabs.module.css`）硬编码 `#8b5cf6`

**操作：** 统一为一个组件库（Radix）。Tailwind 只用 v4：主题写在 `app/globals.css` 的 `@theme` 里。

---

<div id="stale-branch-note"></div>

## 过时分支说明

`origin/codex/theme-style-mode` 在旧 `web/` 目录下开始分离模式 × 样式。本 PR 取代该分支，可以将其归档。

---

<div id="prioritized-roadmap"></div>

## 按优先级排序的规划

1. **Web token 清理** — 修复 `:root` 回退，确保默认值统一为 beige-dark
2. **文档配色** — 与 Web beige 对齐或记录独立性
3. **CLI/TUI 颜色** — 集成 Web 主题或记录独立品牌风格
4. **缺失约定的 token** — 加入约定或从代码/规格移除
5. **宣传页/图标** — 决定对齐还是保持独立
6. **按钮/命名待改进项** — 统一高度、圆角和 token 名称
7. **组件库** — 统一为 Radix + Tailwind v4

---

<div id="implementation-status"></div>

## 实现状态

- **设置外观**：✅ 已完成（模式 × Beige/Neutral/Aurora/Vivid × 强调色选择器 × CSS 叠加层；存储的 Custom 迁移为 beige）
- **Web token 清理**：❌ 未开始
- **文档配色**：❌ 未开始
- **桌面窗口状态**：✅ 已完成
- **桌面窗口框架颜色闪烁**：✅ 已完成（首次显示像素和窗口框架 HTML 跟随已解析的 `--bg-primary`）
- **CLI/TUI 颜色**：❌ 未开始
- **缺失约定的 token**：❌ 未开始
- **宣传页/图标**：❌ 未开始
- **按钮/命名待改进项**：🟡 进行中——`Button` 已换成官方 radix-nova 组件；手写尺寸的标签和 `--ui-button-*` 还在
- **组件库**：❌ 未开始
