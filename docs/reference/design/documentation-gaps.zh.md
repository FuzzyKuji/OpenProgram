<span id="设计文档与代码不对齐的待修项"></span>
# 文档与实现差异


本文件记录设计文档与实际代码的偏差，按优先级排列。本文件只保留尚未解决的偏差；已修复历史通过 Git 查看。

---

## 需要更新的文档（HIGH）

### providers/models/thinking-effort.md
1. **§10 待修项中 Opus 4.7 override 条目过时**: 文档把 `["low","medium","high"]` 限制当作 bug，
   但这是 Anthropic（Claude 4.6 guidance）的 deliberate design choice。应删除该待修条目或改为说明设计原因。
2. **"max" 级别映射标记错误**: 文档声称 5 个 provider 的 max 映射"未映射"，但实际代码中
   `anthropic.py` 已有 `xhigh → max` 映射，所有 provider 都支持 max level。应更新映射表。
3. **Fable 5**: 文档提到缺少 Fable 5 说明，但 `thinking_catalog.py` 中也没有 Fable 5 条目。
   需要确认：是代码缺还是文档多写了？如果该模型已经存在于 models.dev 目录但 catalog 未收录，需加上。

---

## 实施滞后（设计有效但代码未完全跟上）

---

## 内容缺失

### runtime/ 缺 process_runner 设计文档
- `conversation/process_runner.py` 是重要的子进程执行模块（spawn、stop、user-input bridge）
- 没有对应的设计文档

---

## 工具调用体系待解决问题

### 1. harness 自递归原因（✅ 已查明）
- **根因**：harness 入口的函数体裸调 `runtime.exec(content=[task])`——
  不传 toolset/tools,默认拿 `DEFAULT_TOOLSET="full"`(含该入口自身)。
  模型看到该入口的 tool description 正好匹配当前任务
  → 认为需要调它 → 调自己 →
  进去又是裸 exec 又看到自己 → 无限递归。某一层失败时,
  上层模型收到错误 → 重试又调自己。
- **遗留**（待做，见 #2）：各 harness 的 exec 限定工具集 + 跨函数环(A→B→A)识别(当前只防直接自递归)。
### 2. Harness 内部工具集是否需要限制
- 问题：paper_agent/gui_agent 这些 harness 在自己的内部 exec 里,是否应该只看到"做本职工作需要的工具",而不是 full 全集?
- 现状：默认全开(full),self-deny 只挡了自己调自己;一个 harness 仍可调另一个(research 调 gui)——可能导致"跑偏"。
- 决策待定：(a) 框架不管,各 harness 自己在 exec 里传 toolset 限制;(b) 框架自动 deny 所有 harness entry points(research/gui)当一个 harness 在跑时;(c) 保持现状只防自递归。
- 参考：Claude Code 的 subagent 用 allowlist 限工具,正是防这种跑偏。

### 4. Programs 页 Agentic/Built-in tab 分离(进行中)
- 设计：顶部 tab 栏(类似 Memory 页的 Wiki/Journal/Core),分 Agentic(函数管理+文件夹)和 Built-in Tools(profile 管理)。
- 现状：tab 栏已加、tab 状态已加、sidebar 在 builtin tab 隐藏、agentic 内容在 builtin tab 隐藏、tools 只在 builtin tab 显示。CSS 已加。
- 待做：typecheck + build + 浏览器验证,确认分 tab 渲染正确。

### 7. 断点续跑（checkpoint resume）
- **问题**：agentic function 内部 `runtime.exec` 连续 6 次重试全失败（provider 不可达）后直接抛错，函数终止，无法恢复。
- **现状**：DAG 状态完整（frame 节点标 `status="error"`，子节点全保留），`_render_history_messages` 从 DAG 加载历史，基础设施已就位。
- **方案**：提供 `resume_function(session_id, node_id)` 入口——把 frame 节点 status 改回 `running`，用同一个 frame_node_id 重新调 `runtime.exec`，DAG 历史自动接上。webui 加"重试"按钮触发。
- **核心改动**：需要一个"重入"入口 + 恢复 contextvar（_call_id 等）+ 重建 runtime/agent 上下文。
- **位置**：`openprogram/runtime/agent/call_state.py`（wrapper 层）、`openprogram/runtime/agent/runtime.py`（exec 层）

### 8. Bash 工具文件修改追踪
- 已知限制：当前只扫 cwd 顶层文件，子目录变更未覆盖（待后续改为递归扫描）。
- 另外 ④ 系统级沙箱（`cf2edde5`）也从源头限制了 bash 能碰的文件范围。

---
