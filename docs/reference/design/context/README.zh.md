<div id="context"></div>

# 阅读指南

上下文引擎 —— 工作上下文如何在多轮之间被组装、提交、合并与老化。

- [`overview.md`](overview.zh.md) — 上下文层：pipeline + DAG 存储 + ContextCommit + 压缩/渲染 + attach/merge + 跨轮工具
- [`composition.md`](composition.zh.md) — 按调用分层（L0/L1/L2）+ 情境上下文
- [`comparison.md`](comparison.zh.md) — 与其它框架的上下文方案对比
- [`claude-code-compaction.md`](claude-code-compaction.zh.md) — 调研笔记：官方 API 文档与第三方逆向分析所描述的 Claude Code 压缩层级
- [`compaction-diagram.html`](compaction-diagram.zh.html) — 上下文压缩（可视化）
- [`memory-introspection.html`](memory-introspection.zh.html) — agent 怎么知道自己记得什么：记忆块的界碑、默认给不给记忆工具、记忆空或坏时模型看到什么（可视化）
