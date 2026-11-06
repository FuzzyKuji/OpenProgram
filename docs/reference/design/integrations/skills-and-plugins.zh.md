<div id="skills-plugins"></div>

# 技能与插件

技能和插件在不改 OpenProgram 本身的前提下，扩展 agent 知道的东西和能调用的东西。**技能**是一个带 `SKILL.md` 的目录：它的一行描述列在 system prompt 里，任务需要时模型用 `skill` 工具加载完整正文。**插件**是声明式的包——一份 manifest，贡献技能、slash 命令、agent、hook、MCP 服务器和 provider 目录，本身不带代码，所以启用插件不会在 worker 里运行任何东西。Claude Code、Codex、opencode 和 hermes 的 manifest 都按原样读取；插件可以从 npm、git、本地路径或兼容 Claude Code 的 marketplace 安装；不受信任的插件永远不会被启用。两者在 Web UI 的能力页面（Skills、Plugins）和 `openprogram skills` / `openprogram plugins` 中管理；技能文件改动无需重启即可重新加载。

这套系统覆盖 claude-code、opencode、hermes 三家的能力，遇到栈不同就换等价物，并在 OpenProgram 自身的宿主界面上补充能力。

参考实现：
- `references/claude-code-leaked/src/{skills,plugins,commands/{skills,plugin}}`
- `references/opencode/packages/opencode/src/{skill,plugin}`、`packages/plugin`、`.opencode/{skills,plugins}`
- `references/hermes-agent/{skills,plugins,optional-skills}`、`web/src/plugins`

---

## 1. 概念与文件约定

<div id="skill"></div>

### 技能
单位：一个目录，含 `SKILL.md` + 可选 `references/`、`templates/`、其它资源。

`SKILL.md` frontmatter（claude-code 标准 + opencode/hermes 增量）：

```yaml
---
name: my-skill
description: One-line trigger description (LLM reads this to decide invocation)
category: devops              # hermes 风格分组
optional: false               # hermes optional-skills 取代目录区分
allowed-tools: [Read, Edit]   # claude-code: 限定可用工具
triggers:                     # 显式触发条件（我们的扩展，三家都未真用）
  keywords: ["deploy", "ci"]
  file_patterns: ["*.yml"]
  slash: "/deploy"
version: 1.0.0
author: ...
---
```

来源按优先级从低到高合并显示，冲突时后者覆盖前者：
1. **Remote-pulled** — `~/.openprogram/cache/skills/<name>/`（对标 opencode discovery，按 index 远端拉取）
2. **Plugin-provided** — 已启用 plugin 贡献
3. **User** — `~/.openprogram/skills/<name>/`
4. **Project** — `<project>/skills/<name>/`

OpenProgram 不随安装包提供默认 skill。产品工作流归 Programs；skill 保留为用户或插件控制的扩展机制。

技能的名字取自目录相对来源根的路径，所以嵌套目录给出层级名（`anthropic-skills/docx`），重名意味着同一份技能来自两个来源，而不是两份不同技能。

资源布局（hermes 约定）：`SKILL.md` + `references/` + `templates/`。

<div id="plugin"></div>

### 插件
单位：一个声明式包——一份 manifest，列出 skills、commands、agents、hooks、MCP server 和 provider 目录；不含代码。各种 manifest 形式统一解析：
- `.claude-plugin/plugin.json`（claude-code）、`.codex-plugin/plugin.json`（codex）或根目录的 `plugin.json`
- `pyproject.toml` 内 `[tool.openprogram.plugin]`
- `package.json` 内 `openprogram`、`opencode` 或 `hermes` 字段
- `plugin.yaml` / `plugin.yml`（hermes）

manifest 里写了代码（`python`、`module`、`setup`、`main`、`tools`、`client`、`web`、`sidebar`、写成 `module:name` 的 hook 映射、hermes 的 `__init__.py`）的会被拒绝；添加工具或 UI 的代码是应用（[Program 模型](../function/program-model.zh.md)、[插件运行时](plugin-runtime.zh.md)）。

manifest 字段：
```jsonc
{
  "name": "...",
  "version": "...",
  "description": "...",
  "deprecated": false,            // opencode 风格
  "compatibility": ">=0.1.0",     // opencode 风格 minVersion 检查
  "trust": "community",           // community | verified
  "entrypoints": {
    "commands":   "...",
    "skills":     "./skills",
    "agents":     "...",
    "hooks":      "./hooks/hooks.json",  // 事件上的 shell 命令，claude-code 或 openprogram 形状
    "mcpServers": "...",
    "providers":  "..."           // opencode 风格：LLM provider 注入
  },
  "options": { /* JSON Schema, 对照 PluginOptionsDialog.tsx */ }
}
```

来源：
1. **Installed via npm** — `~/.openprogram/plugins/node_modules/<name>/`（opencode 风格 PluginLoader）
2. **本地路径或 git 克隆** — `~/.openprogram/plugins/<name>/`（本地路径以链接形式）
3. **Project-pinned** — `<project>/.openprogram/plugins.json`（声明启用、版本、来源）

---

## 2. 后端

### 目录
```
openprogram/
  extensions/
    skills/
      loader.py           # 四来源合并加载、prompt 列表
      tool.py             # `skill` 工具及其调用记录
      discovery.py        # 远端 index 按需 pull（对标 opencode discovery.ts）
      watcher.py          # watchdog 文件监听，热重载 + WS 广播
    plugins/
      manifest.py         # 多 manifest 解析、代码拒绝
      loader.py           # 发现，经 ProgramContext load / unload
      installer.py        # npm / git / path 安装、卸载
      hooks.py            # manifest hooks 作为事件总线上的 shell 命令
      marketplace.py      # 多 marketplace、claude-code schema 适配
      trust.py            # 信任策略 + 持久化
      autoupdate.py       # 已装插件的更新检查
  interfaces/server/routes/catalog/
    skills.py
    plugins.py
  state/
    frontmatter.py        # SKILL.md frontmatter 解析（输出风格和 CLI 共用）
```

### Skills API（`routes/catalog/skills.py`）
| Method | Path | 说明 |
|---|---|---|
| GET | `/api/skills` | 四来源合并列表，含 source / enabled / category / optional |
| GET | `/api/skills/_complete`、`/_search`、`/_resolve` | 供输入框和 `skill` 工具用的名字补全、搜索与解析 |
| GET | `/api/skills/{name}` | SKILL.md 全文 + frontmatter + 资源文件树 |
| GET | `/api/skills/{name}/file` | 技能的单个资源文件 |
| POST / PUT | `/api/skills`、`/api/skills/{name}` | 新建到 project / user；编辑 |
| DELETE | `/api/skills/{name}` | 仅删 project / user / remote-cache |
| POST | `/api/skills/{name}/toggle` | enable/disable |
| POST | `/api/skills/{name}/invoke-trace` | 返回上次 LLM 调用本 skill 的注入记录（独有） |
| GET | `/api/skills/discovery/sources` | 列已注册的远端 index |
| POST | `/api/skills/discovery/sources` | 添加远端 index |
| POST | `/api/skills/discovery/pull` | 按 index 拉单个 skill 到 cache |
| GET | `/api/skills/discovery/suggested`、`/browse`、`/diff` | 推荐的 index、浏览 index、比较已拉取技能与来源 |
| POST | `/api/skills/discovery/install` | 从 index 安装技能 |
| WS | `skills:changed` | watcher 触发 |

### Plugins API（`routes/catalog/plugins.py`）
| Method | Path | 说明 |
|---|---|---|
| GET | `/api/plugins` | 已装列表 + 状态 + 错误 |
| GET | `/api/plugins/inspect` | 安装前读取插件来源 |
| GET | `/api/plugins/updates` | 已装插件的可用更新 |
| GET | `/api/plugins/commands`、`/api/plugins/builtin` | 插件贡献的 slash 命令；内置条目 |
| GET | `/api/plugins/{name}` | 详情 + manifest + entrypoints 加载状态 |
| POST | `/api/plugins/install` | `{source: npm|git|path, spec, ref}`；manifest 写了代码的会被拒绝 |
| POST | `/api/plugins/{name}/uninstall` | |
| POST | `/api/plugins/{name}/toggle` | |
| POST | `/api/plugins/{name}/reload` | 对标 claude-code `/reload-plugins` |
| POST | `/api/plugins/{name}/validate` | 对标 `ValidatePlugin.tsx`，dry-run 检查 |
| GET / POST | `/api/plugins/{name}/options` | options JSON Schema 读写 |
| POST | `/api/plugins/{name}/trust` | 设置 trust 等级；`untrusted` 的插件不会被启用 |
| GET | `/api/plugins/marketplaces` | 列 marketplace |
| POST | `/api/plugins/marketplaces` | 添加（兼容 claude-code marketplace schema） |
| DELETE | `/api/plugins/marketplaces/{id}` | 移除 marketplace |
| GET | `/api/plugins/marketplace/{id}/index` | 浏览，搜索 / 分类 / 分页 |
| WS | `plugins:changed` | |
| WS | `plugins:error` | 加载失败实时推送 |

### Plugin 贡献入口的接合点
| 入口类型 | 注入到 |
|---|---|
| skills | skill 注册表（与文件系统 skills 合流） |
| commands | `availableFunctions`，附 `source=plugin:<name>` tag |
| mcpServers | 现有 `openprogram/extensions/mcp/` registry，`/mcp` 页面零改动 |
| providers | provider 注册表（对应 openprogram provider 体系，opencode 风格） |
| agents | subagent 注册表 |
| hooks | 事件总线，作为 shell 命令（PreToolUse / PostToolUse / UserPromptSubmit / Stop / SessionStart 映射到 `tool.before` / `tool.after` / `chat.before_send` / `turn.stop` / `session.start`） |

### 信任
| trust | 加载 |
|---|---|
| `verified`、`community` | 挂载 manifest 内容；hooks 和 MCP server 作为各自的进程运行 |
| `untrusted` | 拒绝，UI 弹 trust 确认 |

worker 里不运行插件代码，所以没有 in-process 或 RPC 加载方式：hooks 是子进程，MCP server 是单独的 server。

---

## 3. 前端

### 导航

技能和插件位于主侧栏的 **能力** 下，与 Programs 和 MCP 服务器并列；在 `/skills`、`/plugins`、`/mcp`、`/programs` 上能力入口处于激活状态。

### 路由
- `/skills` —— 列表（按 category 分组，optional 折叠）、带调用记录的详情、新建、远端 index 管理
- `/plugins` —— 三个 tab：Installed / Marketplace / Errors
  - Installed：`UnifiedInstalledCell` 风格的行
  - Marketplace：marketplace 选择器 + 卡片浏览 + 安装（移植 `BrowseMarketplace / AddMarketplace / DiscoverPlugins`）
  - Errors：移植 `PluginErrors`

### 组件
```
apps/web/components/skills/
  skills-page.tsx, skills-list.tsx, skill-detail-page.tsx,
  new-skill-dialog.tsx, discovery/
apps/web/components/plugins/
  plugins-page.tsx,
  views/      installed-list.tsx, marketplace-browser.tsx, plugin-errors.tsx
  dialogs/    plugin-detail.tsx, add-marketplace-dialog.tsx, plugin-options-dialog.tsx,
              plugin-trust-warning.tsx, validate-plugin.tsx
```

两个技能详情视图均将 SKILL.md 正文作为不可信 Markdown 渲染。原始 HTML 及数学内容中的 HTML 文本按字面显示。详情视图不添加本地资源读取解析器，技能链接不授予文件系统访问权限。

### 存储
`apps/web/lib/abilities/skills-store.ts`、`apps/web/lib/abilities/plugins-store.ts`，WS 订阅 `skills:changed` / `plugins:changed` / `plugins:error`。

---

## 4. 超出三家参考实现的能力

1. **声明式插件**：插件不带代码，启用插件不会在 worker 里运行任何东西；代码以应用形式发布
2. **Skill 调用 trace**：每次 SkillTool 调用记录 `{ skill, injected_md_hash, accessed_refs, ts }`，显示在技能详情页
3. **Skill 热重载**：watchdog 监听四来源任一变动 → 重新解析 → WS 广播，无需 `/reload`
4. **多 manifest 统一**：`.claude-plugin/plugin.json` / `.codex-plugin/plugin.json` / `plugin.json` / `pyproject.toml` / `package.json` / `plugin.yaml` 任一形式都能识别，迁移零成本
5. **跨生态 marketplace 互通**：claude-code marketplace schema 适配层，能直接添加其官方 / 第三方 marketplace
6. **包来源**：npm、git 和本地路径（链接）
7. **显式 triggers**：`triggers.{keywords, file_patterns, slash}`，对话/文件/命令任一命中即激活提示
8. **Provider 也是插件可分发的贡献类型**：从 opencode 引入，LLM provider 同样能以 plugin 形式分发
9. **信任闸门**：hooks 和 MCP server 会执行命令，所以 `untrusted` 的插件不会被启用
10. **Validate dry-run**：安装前 `POST /validate` 检查 manifest / 入口 / 依赖 / 兼容性，对标 `ValidatePlugin.tsx`

---

## 5. 对三家参考实现的覆盖

**claude-code**：bundled skills ✓、SKILL.md frontmatter ✓、SkillTool 工具调用 ✓、Marketplace / AddMarketplace / BrowseMarketplace / ManageMarketplaces ✓、ManagePlugins / DiscoverPlugins / ValidatePlugin / PluginErrors / PluginOptionsDialog / PluginTrustWarning / UnifiedInstalledCell ✓、ReloadPlugins ✓、commands/skills/agents/hooks/mcpServers 五入口 ✓

**opencode**：远端 skill discovery（IndexSkill schema）✓、npm 包形态 plugin ✓、Provider plugin ✓、PluginPackage / resolvePluginTarget / compatibility / deprecated 字段 ✓、Effect-style 并发与重试（换 httpx+tenacity）✓

**hermes**：按领域分组 skills ✓（category）、optional 区分 ✓（optional 字段）、`SKILL.md` + `references/` + `templates/` 资源布局 ✓、`plugin.yaml` manifest ✓（带 Python `plugin_api.py` / `dashboard/dist/` 的包是应用，不是插件）

---

## 附录：实现状态

- **Skills** —— 已实现：四来源 loader、watchdog 与 WS 广播、SKILL.md 解析（triggers / category / optional）、`/skills` 页面、带调用记录的 `skill` 工具、远端 discovery。安装包不提供默认 skill。
- **Plugins，本地** —— 已实现：多 manifest 统一解析与代码拒绝；npm / git / path 安装；信任；commands / skills / mcpServers / providers / hooks / agents 入口的挂载；带 Validate / Options / Reload 的 Installed 与 Errors 页面；更新检查。
- **Marketplace** —— 已实现：多 marketplace 与 claude-code schema 适配，以及从中浏览和安装。
- 技能和插件放在 `~/.openprogram/` 下（`skills/`、`cache/skills/`、`plugins/`）。插件的 `providers` 入口通过它的 `ProgramContext` 增加一个 provider 目录；其中的 provider 遵守与内置适配器相同的 `provider.json` 契约。
