<div id="session-操作流程"></div>

# 操作流程

每个操作从触发到磁盘到前端，完整写一遍。

---

## 启动

进程启动时 SessionStore 做一次初始化：

1. 读取 `index.json` 到内存 `_index`。
2. 文件不存在或 JSON parse 失败时，扫描默认布局、嵌套项目布局和持久
   location，依据 `meta.json` 重建 `_index`，再写回 `index.json`。
3. 把所有 `status=running` 重置为 `idle`；这是修复死亡 worker 留下的
   session 列表状态。执行恢复是另一条路径：执行子系统可以通过自己的恢复流程
   继续持久化的 checkpoint 操作。
4. 清理但不丢数据。第一次写 meta 就会建 `history/`，所以没有它的目录是
   损坏或外来的，不会是被丢下的草稿。对未归档、超过 1 小时的摘要行：
   - 目录里有 `history/` → 保留；
   - 默认位置没有目录，且任何布局里都找不到该 session → 只删摘要行，
     项目绑定和 location 映射不动；
   - 目录里有 `meta.json`、`.git` 或 `events.jsonl` 但没有 `history/`
     → 原地保留并记 warning；
   - 其余（空壳）→ 在 session 锁下移到
     `.quarantine/<session_id>-<时间>/session/`，附 `reason.json`，并删摘要行。
     store 根目录之外的目录一律不移动。

   拿不准的一律保留：没有 `created_at` 的行、已归档或有删除记录的 session、
   不可达的非默认位置、迁移日志里阶段不是 `done` / `deleted` 的行、读不出的
   迁移日志（整轮跳过）、session 锁被占用、文件系统报错。这一步从不删除文件；
   `.quarantine` 保留到有人手动清理。

启动时不会按时间删除归档 session，也没有 session 数量容量上限。显式归档的
session 会一直保留，直到所有者删除。

半残 session 的处理：
- 有 `meta.json` 没 `history/` → 保留并列出（显示为空对话），只有显式删除才会移除。
- 有 `history/` 没 `meta.json` → 无法重建注册表，不对外暴露为 session。

---

## 创建 session

3 个入口可以触发创建：

| 入口 | 场景 |
|------|------|
| `dispatcher.process_user_turn` | 用户发消息时，session 不存在则创建 |
| `channel handler` | 渠道消息到达时创建 |
| `session_context` | CLI / harness 进入上下文时，session 不存在则创建 |

其他地方不创建 session。

### 完整流程

```
调用方调 create_session(session_id, agent_id, source=..., ...)
  → 解析位置：<state>/projects/<project_id>/chats/<session_id>；
    没有绑定项目时 project_id 为 `default`（主目录项目）
  → 写 meta.json（id, agent_id, title, created_at, updated_at, source, status="idle", ...）
  → 写注册表：_index[session_id] = 摘要条目
  → 注册表原子写磁盘（临时文件 → os.rename）
  → 不广播（前端通过 list_sessions 发现新 session）
```

### 原子性

dispatcher 和 channel handler 的创建与写入第一条消息是原子的——创建后立即 `append_message`，不会产生空壳。

`session_context` 在 `__enter__` 时创建（因为后续 ContextVar 装载需要有效的 session），如果后续没写消息就异常退出，session 会作为空对话留下（它已有 `meta.json` 和 `history/`），直到有人删除。

---

## 主项目绑定

会话的**主工作目录**就是它所绑定项目的路径。草稿阶段可以自由选择，**第一条真实消息提交时定格**。此后不能再从 composer 把 session 绑定到另一个项目；唯一能改变它的是下面的显式**移动**，它连同仓库一起搬走，并在图上留下记录。会话仓库已经位于应用状态目录下，并按稳定 project id 分组；项目路径变化不会改变 session→project 绑定或仓库 id。

追加工作目录是相反的设计，也应该如此：会话生命周期内随时增删。见 [additional-working-directories.zh.md](additional-working-directories.zh.md)。

### 选择发生在哪里

```
草稿会话，在 composer chip 里选了项目
  → pendingProjectsByChat[chatKey]（前端 store，尚未发送）
  → 第一条 chat 帧带上 project_id
  → handle_chat 用该项目建会话 → 仓库落在应用状态目录的
    projects/<project_id>/<session_id>
  → chat_ack 再补一次幂等的 set_session_project（标签 + 反向索引）
```

草稿阶段选的设置（比如模型）会在会话创建前就落盘，所以会话仓库可能已经以无 `id` 的形式存在于默认位置。因此 `handle_chat` 判断的是 `is_created`（meta 有 `id`，或仓库已有历史），而不是仓库目录是否存在；`create_session` 会把这种只有设置的仓库挪到项目对应的位置，并保留这些设置。

`set_session_project` 在任何时候都接受"绑到会话已有的那个项目"——上面那条 ack 后的幂等 bind 走的就是这条路，它到达时第一轮已经提交。而在已有轮次的会话上绑**另一个**项目会被拒，理由为 `project is frozen after the first turn`（`ws_actions/project.py:FROZEN_ERROR`）。composer chip 与之对齐：已有 session id 的会话只读展示已绑项目，不再给选择器。

### 把会话移到另一个项目

移动是用户在侧栏里的主动操作：把聊天行拖到另一个项目上，或在它的菜单里选**移动到项目**。对应 `move_session_to_project` ws action：

```
move_session_to_project {session_id, project_id}
  → 会话上有轮次在跑时拒绝（RUNNING_ERROR）：那一轮正在旧文件夹里工作
  → SessionStore.move_session：持会话锁，丢掉缓存的仓库，把
    projects/<old>/chats/<id> 连同旁边的 .file-recovery/<id> 重命名到
    projects/<new>/chats/<id>，记录新位置，改注册表绑定，写 meta.project_id；
    离开的项目追加到 meta.project_history
  → record_move：下面的 `project/move` 节点
  → session_moved {ok, from_project_id, project_id, node_id} +
    向所有客户端广播 projects_changed + 一份新的 projects_list
```

从下一轮起，主工作目录就是新项目的路径（`project_workdir_for` 每次都重新解析）；项目记忆层打开时，记忆写入落到新项目的工作区。`project_history` 维持"一轮只写一层"：`project_layer.left_workspace_ids` 把会话离开过的项目换算成它们的记忆工作区 id，`write_target` 把这些工作区标记过的轮次当作已写，所以新项目的记忆只收移动之后说的话，旧项目的记忆保留它已有的内容。移到主目录项目同理，目标换成个人工作区。会话自己的设置（模型、权限模式）随 meta 一起走；项目默认值（`settings.json`）从此读新项目的。

### 附件与恢复

浏览器上传的文件在 dispatch 前解码并保存到
`<session repository>/workdir/attachments/`。保存后的路径写入 user message
标记，并在 turn 结束时随会话仓库提交。浏览器 IndexedDB 只保存尚未发送的
composer 草稿；发布后会清理，因此不是持久的 session 附件存储。渠道附件仍
位于 `<state>/channels/*/accounts/*/attachments` 的渠道根目录。

旧项目迁移时，迁移日志会清点外部恢复目录，将会话和恢复数据一起复制到
`<state>/projects/.migration/staging/` 并校验，再把会话发布到
`projects/<project_id>/<session_id>/`，把恢复数据发布到旁边的
`.file-recovery/<session_id>/<turn>/`，随后才更新 location 权威记录。发布缺失或
失败时，项目保持不可用状态，新的项目绑定任务会被阻止。

历史标记兼容性遵循 [storage.zh.md](storage.zh.md) 的存储规则：只有精确的旧
session 附件路径形式，才能按同一个 session id 解析到唯一的当前仓库，并执行
附件根目录包含检查以及符号链接和路径穿越检查。系统不会任意重映射旧绝对路径。

### 修复缺失的目录

定格后的主目录仍可**重定位**，且只为修复：目录在磁盘上被移动或改名，项目指向了不存在的位置。这种状态下 `project_workdir_for` 返回 `None`，绝不悄悄替换成默认项目家目录。项目缺失、被替换、pending、迁移中或其他不可用状态时，新的项目绑定任务会被阻止；界面收到 location state 和缺失路径后提供修复入口。修复期间会话仓库仍可读取。

修复动作是 `relocate_project` ws action：

```
relocate_project {session_id, project_id, path}
  → project_store.relocate_project：校验新目录、改写项目 path、**保留 id**
    （会话反向索引、项目设置、定格的绑定全挂在 id 上）
  → record_relocate：追加下面的记录节点
  → project_relocated {ok, old_path, path, node_id} + 一份新的 projects_list
```

它改的是**项目的路径**，而非会话→项目的绑定，所以定格之后依然合法。绑定到该项目的 session 保持同一个稳定 project id 和应用状态目录下的会话仓库。旧工作目录副本通过迁移日志和持久 location index 处理。默认项目拒绝重定位：它的显示路径是家目录，每次 `get_default_project` 读取都会恢复；它没有独立的项目 Git 仓库。每轮文件撤销恢复仍位于目标仓库旁的 `.file-recovery/<session_id>/<turn>/`，在会话 Git 仓库之外。定位到已属于另一个项目的目录会被拒绝，只有一个例外：被定位的项目目录已缺失且没有对话时，它是这个目录过期的第二份登记，于是并入拥有该目录的项目，选择器随即选中那个项目。

### relocate 记录节点

这次移动改变了此后每一轮的运行位置，所以记进会话图，而不是无声改注册表（`openprogram/state/store/project/relocate_node.py`）：

| 字段 | 值 |
|---|---|
| `role` | `code` |
| `name` | `project/relocate` |
| `caller` | `ROOT` |
| `predecessor` | `None` |
| `output` | `<旧路径> → <新路径>` |
| `metadata` | `{display: "runtime", project_id, old_path, new_path}` |

移动用同样的方式记录（`record_move`）：`name` 为 `project/move`，`output` 为 `<旧项目名> → <新项目名>`，`metadata` 带 `old_project_id` 和 `new_project_id`。

形状照搬 `context/system_prompt`（dag/overview.md §3、§7）：写入不变式只约束对话节点；`caller` 已设，store 便不推进 head——记录重定位不动分支尖端。名字刻意**不放在** `context/` 下：那是隐藏于对话流的管线机器，而重定位是值得看见的用户动作。

---

## 写消息

```
调用方调 append_message(session_id, msg)
  → 把 JSON 节点追加到 history/ 中的对话 DAG
  → 写入 meta.json；对话链增长时同时写入 DAG head
  → 如果 msg.role == "user"：
      → preview = 截取 msg.content 前 80 字符
      → _index[session_id]["preview"] = preview
      → _index[session_id]["updated_at"] = time.time()
      → 标记注册表脏（5 秒 debounce 写磁盘）
  → 不广播 session 列表（消息内容通过独立的 streaming 通道推送）
```

原始节点和 `meta.json` 会在 turn 结束的 Git 提交之前写入。turn 成功后，
`GitSession.commit_all` 提交会话仓库；`session_commits()` 读取这些 Git 提交，
形成独立的每轮时间轴。因此 Git `HEAD` 与对话 DAG 的 head 不是同一个指针。

### preview 截取

```python
def _truncate(text: str | None, max_len: int = 80) -> str | None:
    if not text:
        return None
    t = text.strip().replace("\n", " ")
    return t[:77] + "…" if len(t) > max_len else t
```

### 注册表写磁盘节流

`append_message` 更新注册表时，内存立即更新，磁盘写入 debounce（5 秒内最多写一次）。进程退出时 flush。如果进程被 SIGKILL 导致 flush 失败，启动时从 meta.json 重建即可恢复，最多丢失 5 秒的 preview 更新。

其他操作（create、update、delete）立即原子写磁盘。

---

## 更新字段

标题、状态、置顶、归档、未读等字段的更新都走同一条路径：

```
调用方调 update_session(session_id, title="新标题", pinned=True, ...)
  → 写 meta.json（只更新传入的字段）
  → 更新 _index[session_id] 中对应字段（不改变 updated_at）
  → 注册表原子写磁盘

updated_at 只在追加消息路径推进；rename、pin、archive 和 read/unread 等元数据更新保留原有 recency。
```

广播由 WebSocket handler 层在调用 `update_session` 之后通过 `_broadcast` 发起，rename 与 flags 均走广播：

```
→ 广播 session_updated：
  {"type": "session_updated", "data": {"id": "<session_id>", "title": "新标题", "pinned": true}}
→ 前端 handleSessionUpdated 收到后 patch 对应 session 并重渲染
```

`data` 只包含变更的字段，前端做增量 patch。

### 项目列表里的位置

侧栏按最后活跃时间列出项目里的对话。把对话拖到列表里的另一个位置，给它的是一个时间而不是序号：`update_session_flags` 带 `sort_at`（秒）把它写进 meta，同时写 `sort_since`——对话当时的 `updated_at`。客户端在 `updated_at` 没超过 `sort_since` 时按 `sort_at` 排序，所以别的对话有新活动仍会排到它前面，它自己的下一轮就结束这次摆放（服务端不清理；`sort_at` 为 0 清掉两者）。客户端把 `sort_at` 取在前后邻居的时间之间，放到顶部时取当前时间。两个字段都是索引字段，会话列表带着它们。

### status 的写入时机

dispatcher 在 turn 生命周期中写 status：

| 时机 | 写入值 |
|------|--------|
| turn 开始 | `update_session(session_id, status="running")` |
| turn 正常结束（前台） | `update_session(session_id, status="idle")` |
| turn 正常结束（后台） | `update_session(session_id, status="done", unread=True)` |
| turn 失败 | `update_session(session_id, status="failed")` |
| 等待用户输入 | `update_session(session_id, status="needs_input")` |

---

## 命名

命名只有**一套权威实现**：`openprogram/runtime/conversation/turn_runtime/titles.py`。所有入口（WS / fn-form / channel / CLI / spawn）的命名都汇到 `finalize_turn 末尾 → _maybe_auto_title`，没有第二套截断/锁死逻辑。标题写入都通过 `update_session(session_id, title=...)`，走上面"更新字段"的完整流程。

### 锁标记（权威，仅两把 + 一个内部计数）

| 标记 | 类型 | 含义 | 谁来设 |
|------|------|------|--------|
| `_user_titled` | bool | 标题是用户输入的 → 永久锁，自动命名永不再跑 | **只有** rename 操作：用户输入名字时设，用户要求生成名字时清除 |
| `_auto_titled` | bool | 已有自动标题（首轮截断、任意 LLM 写入或生成的名字）→ "别重复截断"去重位 | `_maybe_auto_title`，以及 rename 操作写入生成的名字时 |
| `_title_gen_count` | int | 渐进式重命名内部计数（命中到 `_RETITLE_AT_TURNS` 第几个）| `_maybe_auto_title` 内部，非入口锁 |

不存在既表示"已截断"又表示"永久锁"的单一标记：一个标记兼做两件事会与两阶段流程冲突——阶段 1 的截断本就应当被 LLM 标题取代。因此各入口不自己做截断、也不设自己的锁，统一由 `_maybe_auto_title` 完成阶段 1（截断）和阶段 2（LLM）。入口唯一可设的锁是 `_user_titled`，由 rename 操作在用户输入名字时设置。

### 自动命名（渐进式，两阶段）

自动命名在对话演进过程中多次触发，随着上下文增多生成更精确的标题。
触发阈值：第 1、6、16、40 轮 assistant 回复时（`_RETITLE_AT_TURNS`）。首条用户消息是寒暄（问候、致谢、应答，或 `hl` 这样一两个字符）的会话，在第 2、3 轮回复时也重新命名（`_EARLY_RETITLE_TURNS`），因为第 1 轮的标题命名的是那句寒暄。

所有 LLM 标题，无论后台还是用户要求，都由 `build_title_context(get_branch(session_id))` 生成输入：当前分支，即 HEAD 的链。它保留用户文本和每轮最后的 assistant 文本，去掉工具调用、工具结果和运行时记录、附件标记和 `<think>` 块。开场的寒暄轮连同回复一起去掉；之后内容很少的用户消息（"ok"、"继续"）去掉，但保留它的回复。第一个有实际内容的轮次和最新一轮总在其中；中间的轮次从新到旧填满剩余预算，跳过的部分用 `…` 标出。摘录不超过 1,000 字符（`2 × _MAX_INPUT_CHARS`）。整段都是寒暄的会话保留全部内容。

```
finalize_turn 末尾 → _maybe_auto_title：
  1. 检查 _user_titled → 用户手动改过名则永不自动重命名
  2. 统计当前 assistant 消息数 → 未命中阈值则跳过
     （首条用户消息是寒暄时，2 和 3 也算阈值）
  3. 首次（turn 1，阶段 1 立即截断）：
     a. title = _title_from_text(用户首条消息)
        （剥 [attachment:]/<attachment-preview>/<file> 标记 → 取首行 → 截 50 字，超出加 …）
        → update_session(session_id, title=截取值, _auto_titled=True, _title_gen_count=1)
     b. 启动后台 daemon 线程调 LLM（阶段 2）
  4. 后续阈值（寒暄开场后的 turn 2/3，以及 6/16/40）：
     a. 记下当前标题，启动后台 daemon 线程
     b. LLM 输入是当前分支的 build_title_context
  5. 后台线程（阶段 2）：
     → 竞态检查：_user_titled 则放弃
     → 检查 title 是否仍是本次开始时的标题：首次是阶段 1 截取值，之后是记下的标题（被改过就放弃写入）
     → 写入 update_session(session_id, title=LLM结果, _auto_titled=True, _title_gen_count=N+1)
     → 广播 session_updated
```

### channel（微信 / Discord 等）

channel 会话命名与普通会话**完全一样**，走同一套两阶段 LLM 命名，channel 端**不**对标题内容做任何额外操作 / 锁定 / 干预（不设 `_user_titled`、不设 `_auto_titled`、不预截断）。来源标识只在前端显示层加方括号品牌前缀（如 `[WeChat] 周末计划讨论`），不进 title 本体。

### 空会话

创建即写第一条消息是原子的，正常不产生空会话；万一产生则保留到手动删除；启动清理因为它有 `meta.json` 和 `history/` 而保留它。命名层不对空会话做特殊过滤。

### 用户主动重命名

- 手动输入新名字 → `update_session(session_id, title=新名字, _user_titled=True)`
  设 `_user_titled` 后自动命名永久停止。
- 让 LLM 生成名字（**自动命名**，title 为空）→ `_llm_rename()` 用同一个 `build_title_context` 为当前分支命名 → `update_session(session_id, title=LLM结果, _user_titled=False, _auto_titled=True, _title_gen_count=max(1, N))`
  生成的名字不是锁：它清除之前输入名字的锁，之后的重新命名可以继续改进它。模型运行期间标题或锁变了，结果报告为 `superseded`，不写入。

LLM 标题生成的细节（prompt、参数、后处理）见 [name.md](name.zh.md)。

---

## 列举

```
前端发送 WebSocket 消息 {"action": "list_sessions"}
  → handle_list_sessions：
      → session_store.list_sessions()：
          → 遍历内存 _index.values()
          → 除非 include_archived=True，否则丢掉已归档的行
          → 按 filters 过滤
          → 按 updated_at 降序排序
          → 返回 rows[offset:offset+limit]
      → 补充 project 字段（从项目目录映射）
      → 发送 {"type": "sessions_list", "data": rows}
  → 前端渲染侧边栏和 Chats 页面
```

纯内存操作，不碰磁盘。

### 已归档的行

`list_sessions` 默认隐藏已归档会话：只有默认列举遵守归档，归档才真的能约束列表
长度。两种方式看到它们：

- `include_archived=True` 同时返回已归档和活跃的行
- `archived=True` 只返回已归档的

那些必须遍历每个会话、不管标志的维护流程（记忆扫描、运行态修复、"清空全部"、
渠道绑定查找、agent 寻址）显式传 `include_archived=True`。侧边栏 payload 也发送
全部行，前端在活跃/已归档/全部三个视图之间切换无需再请求一次。

### 每条 session 返回的字段

注册表中的 17 个字段 + preview + project（列举时补充），共 19 个。完整列表见 [storage.md](storage.zh.md)。

---

## 删除

```
调用方调 delete_session(session_id)
  → 删除 <state>/projects/<project_id>/chats/<session_id>/ 整个目录
  → 删除 _index[session_id]
  → 注册表原子写磁盘
  → 广播 session_deleted：
    {"type": "session_deleted", "session_id": "<session_id>"}
  → 前端收到后从列表中移除
```

注册表操作在 `delete_session` 内部完成。广播由 WebSocket handler 层通过 `_broadcast` 发起。

---

## 归档

归档让会话列表不再无限增长。它只是 session meta 上的一个布尔标志：不删数据、
不搬目录，随时可逆。

```
调用方调 set_archived(session_id, True)
  → update_session(session_id, archived=True)
  → 走"更新字段"的完整流程
  → 前端收到广播后过滤显示
```

`set_archived` 对不存在的 session id 返回 `False`，CLI 和 REST 端点据此报告
会话不存在，而不是静默成功。

### 归档不动的东西

`updated_at` 记录的是最后一次追加消息的时间，归档不追加任何消息，因此不碰这个
时间戳。这是[索引一致性契约](storage-consistency.zh.html)：取消归档后会话回到列表
里原来的位置，不会被顶到最上面。消息、分支、history 文件都不动，归档期间
`get_messages` 照常可读。

### 入口

| 界面 | 操作 |
|------|------|
| WebSocket | `{"action": "update_session_flags", "session_id": ..., "archived": true}` |
| REST | `POST /api/sessions/archive` / `POST /api/sessions/unarchive`，body `{"session_id": ...}` |
| CLI | `openprogram sessions archive <id>` / `openprogram sessions unarchive <id>` |

三个入口都经 `set_archived` 写同一个标志并广播 `session_updated`，所以每个
打开的标签页看到的状态一致。

已归档的 session 会被启动维护保留。它们默认不出现在列表中，直到显式删除前仍可访问。

---

## 注册表写磁盘（通用）

所有注册表写磁盘操作都用原子写：

```
写入临时文件 index.json.tmp
  → os.rename(index.json.tmp, index.json)
```

防止崩溃导致文件损坏。
