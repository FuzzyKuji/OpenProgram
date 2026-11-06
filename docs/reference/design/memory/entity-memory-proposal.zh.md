# 基于 Git 的实体记忆：未实现提案

> **实现状态：**本文是实体记忆的提议设计。下文的 Session-Git 和 Project-Git
> 生命周期尚未在当前 Memory runtime 实现。当前实现是
> [`overview.md`](overview.zh.md) 所述的 Source/Topic/Core workspace。

本文统一维护生命周期、回放和一致性提案。下文路径、hook 与 UI 入口均属于未实现设计，不是当前使用说明。存储草案统一使用 history/ 与 context/；旧 messages/ 与依赖 SQLite 的草图不作为当前存储合同。当前持久化见[会话存储](../runtime/session/storage.zh.md)。项目自动提交必须能识别 agent 所属改动；如果用户并发编辑，仅凭开始时工作区干净不能证明改动归属。

<span id="1-概念"></span>
<span id="实体记忆-entity-memory"></span>
<span id="实体记忆走-git-session-git-project-git"></span>
<span id="心智模型"></span>
<span id="1-跟现有-dag-的关系"></span>
<span id="2-session-git"></span>
<span id="21-文件布局"></span>
<span id="23-branch-retry"></span>
<span id="3-project-git"></span>
<span id="31-概念"></span>
<span id="33-agent-改文件触发自动-commit"></span>
<span id="34-用户手动改-vs-agent-改"></span>
<span id="35-没绑-project-的-session"></span>
<span id="4-ui-入口"></span>
<span id="41-session-历史回溯"></span>
<span id="7-跟-claude-code-对比"></span>
## 概念

实体记忆是不可变的真实历史记录，基于 git 存储。"实体"= 真实发生过的事，可逐步回溯。

两种实体：

| 类型 | 粒度 | 存储位置 |
|------|------|----------|
| **Session-Git** | 每次对话，每 turn 一 commit | `<state>/projects/<project_id>/chats/<id>/` 或 `<project>/.openprogram/sessions/<id>/` |
| **Project-Git** | 绑定的用户工作目录 | `<user-workdir>/.git/`（复用已有） |

Session-Git 记录对话过程（user → LLM → tool 调用链）。Project-Git 记录 agent 对用户代码/文档的实际修改。两者互补：session 存"说了什么"，project 存"改了什么"。

<span id="2-存储布局"></span>
## 存储布局

```
~/.openprogram/                              ← get_state_dir()
├── sessions/
│   ├── <session_id>/                        ← 一个 Session-Git repo
│   │   ├── .git/
│   │   ├── meta.json                        title, agent_id, project_id, created_at, ...
│   │   ├── history/                         DAG 节点文件
│   │   │   ├── 000001-u-<id>.json           user message
│   │   │   ├── 000002-a-<id>.json           assistant message
│   │   │   ├── 000003-t-<id>.json           tool result (called_by = assistant)
│   │   │   └── ...
│   │   ├── context/                         per-turn LLM context 物化视图
│   │   │   └── commits/<commit_id>.json
│   │   └── workdir/                         此会话的临时工作目录
│   │
│   └── locations.json                       ← 索引：项目内 session → 真实路径
│
├── projects/
│   └── projects.json                        project 注册表
│
└── memory/                                  ← 抽象记忆层（见 virtual-memory.md）

<用户工作目录>/
├── .git/                                    ← Project-Git（复用已有，或 auto-init）
└── .openprogram/sessions/<id>/              ← 绑定此项目的 session repo
```

<span id="3-session-git-生命周期"></span>
## Session-Git 生命周期

<span id="31-创建-create"></span>
### 创建 (Create)

**触发时机**：第一条消息写入时 lazy-init（`SessionStore._open(id, create_if_missing=True)`）。

**创建产物**：
- `git init` → `.git/`
- 写入 `meta.json`（title, agent_id, project_id, created_at）
- 创建 `history/`, `context/`, `workdir/` 目录

**归属**：每个 session 创建时绑定一个 project：
- 指定了工作目录 → 绑定真实 Project-Git，session repo 落在 `<project>/.openprogram/sessions/<id>/`
- 未指定 → 绑定默认项目（纯逻辑标签 `project_id="default"`），session repo 落在 home 根

<span id="32-合法性-validity"></span>
### 合法性 (Validity)

一个目录被视为有效 session，当且仅当：

1. 该目录存在
2. 目录下存在 `meta.json` 文件
3. `meta.json` 可解析为有效 JSON

不满足以上条件的目录：**跳过，不列入列表，不报错**。这涵盖了：
- 测试残留（只有 `steering/` 子目录，无 meta.json）
- 手动创建的无关目录
- 损坏的 session（meta.json 不可解析）

<span id="33-title-规则"></span>
### Title 规则

Session title 是用户在列表中识别对话的主要标识。

#### 生成策略（优先级从高到低）

1. **用户手动命名**：用户通过 `/rename` 或 UI 右键 rename 设置的 title，永远优先，不被覆盖。

2. **LLM 生成摘要（首选自动方式）**：第一轮对话结束后（assistant 回复完成），后台线程调用 LLM 生成 3-7 词的描述性标题。
   - **触发时机**：第一轮 turn 的 `finalize_turn` 之后，异步执行
   - **输入**：user message 前 500 字符 + assistant response 前 500 字符
   - **Prompt**："Generate a short, descriptive title (3-7 words) for this conversation. Return ONLY the title, no quotes, no prefix."
   - **模型选择**：当前 session 使用的模型（已建立连接，无额外开销）；如果不可用，用系统最便宜的可用模型
   - **参数**：`max_tokens=50`, `temperature=0.3`（确定性高）
   - **后处理**：去引号、去 "Title:" 前缀、截断到 80 字符
   - **非阻塞**：后台 daemon 线程执行，失败只记日志不影响用户
   - **幂等**：`meta.json` 中 `_titled=True` 标记，已生成过不再触发

3. **Fallback — 第一条消息截取**：LLM 不可用或调用失败时，取第一条 user message 的第一行，截断到 50 字符 + "…"。

4. **展示层 Fallback**：如果以上都没有触发（session 通过非 dispatcher 入口创建，如 harness），列举时 title 仍为空/"New conversation"/"Untitled" → 用 preview（第一条 user message 前 80 字符）替代显示。

5. **不过滤空占位**：所有合法 session 都显示在侧边栏，包括刚创建、title/preview 尚未就绪的会话。New chat 不建 session，会话只在发第一条消息时由后端延迟创建，所以列出来的会话必然有内容，这类过滤没有可藏的对象。

#### 时序

```
用户发送第一条消息
  → dispatcher 处理 turn
  → finalize_turn:
      1. 立即设 title = 第一行前 50 字符（Fallback, 确保侧边栏不空）
      2. 启动后台线程 → LLM 生成摘要 → 成功则覆盖 title + 标记 _titled
  → 用户看到侧边栏立即显示截取标题
  → 几秒后 LLM 标题就绪 → 广播 session_updated → 侧边栏更新为摘要标题
```

#### 设计决策

- **为什么不等 LLM 再显示？** LLM 调用需要 1-5 秒，用户切换到别的 session 时侧边栏不能是空的。先用截取占位，再异步更新。
- **为什么用当前模型？** 避免额外的 API key / 连接开销。title 生成的 prompt 很短（< 1200 tokens），对任何模型都是微不足道的开销。
- **为什么只触发一次？** 避免对话深入后标题来回变。第一轮最能代表用户意图。
- **为什么 temperature=0.3？** 稍有创意但基本确定性。同样的对话开头重跑不会得到完全不同的标题。

<span id="34-发现与列举-discovery"></span>
### 发现与列举 (Discovery)

列举所有 session 时，来源有两个：

1. **全局目录扫描**：遍历每个 `<state>/projects/<project_id>/chats/` 文件夹，逐一做合法性校验
2. **locations.json 索引**：记录了落在项目目录内的 session 路径，逐一做合法性校验

两个来源合并去重后，按 `updated_at` 降序排列。

展示规则：
- 合法性校验通过 → 显示（包括 title/preview 尚未就绪的刚创建会话；没有空占位过滤）
- 合法性校验不通过 → 跳过

侧边栏和 Chats 页面使用同一套展示规则。

<span id="35-读取与写入-readwrite"></span>
### 读取与写入 (Read/Write)

**写入**：
- `append_message(session_id, msg)` → 同步写 `history/NNNN-<role>-<id>.json` + 更新内存索引
- `commit_turn(session_id, message)` → turn 结束时一次 git commit（不是每条消息一次）

**读取**：
- `get_branch(session_id, head_id)` → 按 parent_id 边遍历 DAG，返回渲染后的消息列表
- `get_nodes(session_id)` → 原始 `Call` 对象（含工具调用细节）
- `session_commits(session_id)` → git log（turn 粒度）

**分支/重试**：
- DAG 的 retry → git branch（`retry-<assistant_id>`）
- 切换 DAG head ↔ git checkout

<span id="36-管理-management"></span>
### 管理 (Management)

**元数据更新**：`update_session(session_id, title=..., project_id=..., ...)` → 写 `meta.json` + 更新内存索引

**缓存**：
- 内存中维护 `OrderedDict[session_id → (GitSession, SessionMemoryIndex)]`
- LRU，cap=256（env `OPENPROGRAM_SESSION_CACHE_CAP` 可配）
- 驱逐无损：下次访问时从磁盘重建
- 线程安全：per-session lock + 全局 store lock

**Project 绑定**：
- `meta.json` 的 `project_id` 字段
- 绑定了真实项目的 session 落在项目目录内（`locations.json` 记录路径）

<span id="37-删除-deletion"></span>
### 删除 (Deletion)

**手动删除**：`delete_session(session_id)` →
1. 从内存缓存中移除
2. 关闭关联的 runtime（如有）
3. `shutil.rmtree()` 整个 session 目录（包括 `.git/`）
4. 如在 `locations.json` 中有记录，移除该条目

**级联影响**：
- 抽象记忆中引用该 session 的 provenance 指针变为 dangling
- 查询时通过合法性检查自动跳过（session 目录不存在 → 返回 None）
- 不需要显式清理虚拟层记录

**前端入口**：
- 侧边栏右键菜单 → Delete
- Chats 页面（待补充：右键删除功能）

<span id="38-gc-策略-garbage-collection"></span>
### GC 策略 (Garbage Collection)

| 场景 | 处理 |
|------|------|
| 无 `meta.json` 的目录 | 列举时跳过（§3.2 合法性校验） |
| 有 meta.json 但 history 为空且 title 为默认值 | 列入列表，使用标题或预览兜底，不过滤有效会话 |
| 长期不活跃的 session | **不自动删除**（用户数据，由用户决定） |

设计决策：不设自动 TTL。理由：session 是用户的对话历史，属于用户数据，不应被系统自动清理。如果未来需要空间回收，由 policy 层（用户配置）决定，不在 store 层实现。

<span id="4-project-git-生命周期"></span>
## Project-Git 生命周期

<span id="41-创建"></span>
### 创建

**触发**：`resolve_project(path, name)` — 用户在 UI 绑定工作目录时，或 session 指定 workdir 时。

**行为**：
- 目录已有 `.git/` → 复用
- 目录无 `.git/` → `git init`
- 注册到 `projects.json`

<span id="42-写入auto-commit"></span>
### 写入（Auto-commit）

Turn 结束时，如果 session 绑了真实 project 且 agent 改过文件：

```
if working_tree_clean_before_agent:
    git add -A
    git commit -c user.name="agent (<model> via OpenProgram)"
              -m "[agent <session_id>] turn <N>: <user msg first 60 chars>"
else:
    skip + UI 警告（不污染用户未提交的改动）
```

Agent commit 用覆盖的 user.name/email 标识，跟用户手动 commit 区分。

<span id="43-读取"></span>
### 读取

- `ProjectGit.log(limit)` → agent-attributed commits
- `project_commits(project_id)` → provenance 层的读原语

<span id="44-删除"></span>
### 删除

取消项目绑定 ≠ 删除 git 历史。用户的 `.git/` 里包含用户自己的 commit，不可由 OpenProgram 删除。

取消绑定时：
- 从 `projects.json` 移除注册
- 关联 session 的 `project_id` 不变（historical pointer）
- Session repo 仍在项目目录内（不搬回 home 根）

<span id="5-跟抽象记忆的关系"></span>
## 跟抽象记忆的关系

实体记忆是抽象记忆的**唯一数据源**。提炼管道读 session-git 的 DAG 节点 + project-git 的 commit 历史，从中抽取事件和关系，写入抽象记忆的 timeline/graph。

每条抽象记忆都带 `Provenance` 指针回指实体层：
```python
@dataclass
class Provenance:
    project_id: str
    session_id: str
    node_ids: tuple[str, ...]
    commit: str | None
    event_time: float
    ingestion_time: float
```

详见 [`virtual-memory.md`](virtual-memory.zh.md)。


## 轮次提交、回放与一致性

<span id="22-commit-时机"></span>
### Commit 时机

每个 **turn 结束**时一次 commit, 不是每条消息一次 —— 按消息切太碎, 没有实用价值.
turn 结束 = dispatcher.process_user_turn() 返回 TurnResult 时.

一个 turn 包含:
- 1 个 user message
- 1 个 assistant placeholder → 最终带 content
- N 个 tool result (caller = assistant)

commit message:

```
turn <N>: <first 60 chars of user msg>

assistant: <first 80 chars of reply>
tools: read, grep × 3, list

[meta: turn took 12.3s, 18 tools, 4521 tokens]
```

<span id="24-回溯-ui"></span>
### 回溯 UI

chat 顶部 / 历史区右侧的 prev / next 控件:

```
[← prev turn]  Turn 7 / 12  [next turn →]    [view full history]
```

- prev: `git checkout HEAD~1` + 重放 UI 到那时状态
- next: 反向走 reflog
- view full history: 弹一个 timeline (每个 commit 一条, 点开看 message 内容)

实现层面: WS action `git_history(session_id)` 返回 commit log, `git_checkout(session_id, commit_sha)` 切到某个状态, dispatcher 下一轮 user message 续在那个 commit 上.

<span id="25-双写一致性"></span>
### 双写一致性

**主路径**: dispatcher 写 DAG.
**镜像**: turn 完成后, 异步把这一 turn 的所有节点序列化到 session repo + commit.

异步是因为 git commit ~100-500ms, 不该卡用户. 用 `threading.Thread` 后台跑, 失败只记日志不阻塞.

冲突可能性极低 (一个 session 一个 repo, 串行 commit), 用文件锁兜底.

<span id="26-老-session-迁移"></span>
### 老 session 迁移

启动时扫现有会话存储, 给没 repo 的 session 跑一次性 backfill: 按 seq 遍历节点, 逐 turn commit 出来. 一次跑完, 之后增量.



## 项目元数据与展示

<span id="32-关联"></span>
### 关联

```python
class Project:
    id: str
    name: str
    workdir: str               # 绝对路径, 用户文件系统目录
    sessions: list[str]        # session id 列表 (谁在这 project 里干活)
    status: "active" | "paused" | "done"
    created_at: float

# 反向关联:
Session.metadata["project_id"] = "proj_xxx"   # 加到 sessions 表
```

session 可以独立存在 (没 project). 有 project 时, agent 修改文件触发的 commit 落在 project repo.

<span id="42-projects-panel"></span>
<div id="projects-panel"></div>

### 项目面板

左 sidebar 的 "Projects" section:

```
─ Projects ─────────
  ● Wiki Agent Refactor   2 sessions  ●  active
  ○ DAG Visualization    1 session   done
  ○ ...
  + New Project
```

点击 project → 进 project detail page: 名字 / workdir / 关联 sessions / 提交历史 / 抽象记忆入口.

新建 project 流程: 选个目录 → 起名 → 创建 / 复用 git repo → 把当前 session 关联进去 (可选).

<span id="43-chat-顶部-project-指示"></span>
### Chat 顶部 project 指示

如果当前 session 关联了 project, 顶部 status 区显示 project 名字 + workdir 简写, 点击进 project page.



<span id="5-关键不变式"></span>
## 关键不变式

1. **DAG 是当前真源, Git 是镜像**. Git 失败不影响 DAG. 反过来不行 — git 落盘但 DAG 没写就是脏数据.
2. **Session-git 一 turn 一 commit**, 不按消息细分.
3. **Project-git 干净优先**: 用户 working tree 不能被 agent 污染. 有未提交改动时 agent 跳过 commit.
4. **回溯不破坏 DAG**: checkout 是只读视图, 用户发新消息会基于该 commit 在 DAG 上 fork 新分支.
5. **抽象记忆建立在实体记忆之上**, 而不是反过来.
6. **项目注册表不会因读取失败或并发写入而丢失**. worker、CLI 和 agent 子进程都会读改写 `projects.json`, 所以每次修改在整个读改写期间持有跨进程文件锁 (`<state>/projects/.locks/.projects-registry.lock`). 写入先写到唯一的临时文件, 再用 rename 发布, 读的一方看到的要么是完整的旧文件, 要么是完整的新文件. 读取出错时直接报错, 不返回空注册表, 因为下一次写入会抹掉所有项目和会话绑定. 内容不是 JSON 对象的文件会被移到 `projects.json.unreadable-<时间>-<id>` 留作恢复, 注册表从空开始.



<span id="6-风险点"></span>
## 风险点

- **Git 异步 commit 失败**: 用户看不到, 静默漏数据. 缓解: 后台线程失败重试 + 启动时校验 DAG seq vs git commit 数, 不对就触发 backfill.
- **Project workdir 不是 git 仓**: agent 第一次 commit 时自动 `git init`. 用户已经有 git 的仓: 直接复用.
- **多 session 并发改同一 project**: file lock 串行化 project commit. 极端情况退化到队列.
- **回溯 + 继续聊天的语义**: 用户回到 turn 5 后发新消息, 结果是 fork 新分支, 而不是覆盖之后的内容 (DAG retry 已有这个概念), git 自然映射到 branch.



<span id="8-跟现有-commit-chain-的关系"></span>
## 跟现有 commit chain 的关系

不冲突. commit chain 是"LLM 看到的 context view", 跟 git 是"实际发生过的 history" 是两个层:

- DAG 节点 (raw 真源) → git commit (持久化镜像)
- ContextCommit chain (LLM 视角) → 不入 git (派生, 可重算)

commit 可以选择性 export 到 git (e.g. 用户想看"那时 LLM 看到啥"), 但不是强制.



## 外部比较边界

原提案比较了 Claude Code 的回退体验，但没有经过核实的实现证据，不能据此判断其会话存储与恢复方式。本提案明确使用 Git log/diff 暴露历史；外部能力比较需要在实施前另行核实。


## 附录: 提议的构建顺序

工作拆成五块, 每块独立可验证:

1. **Session-git 基础设施** — 模块 `openprogram/state/memory/session_git/`
   (init / commit / log / checkout 包装); `dispatcher.process_user_turn` 末尾 hook,
   后台线程跑 commit; backfill 脚本把老 session 转成 git repo; WS action
   `git_session_log`, `git_session_checkout`.
2. **Project schema + UI** — 项目注册表 `projects` (id, name, workdir, status, …);
   sessions 表加 `project_id`; WS `list_projects`, `create_project`,
   `add_session_to_project`; 左 sidebar 加 Projects section.
3. **Project-git auto-commit** — 已绑 `project_id` 的会话在 turn 后跑 project
   commit hook; 干净时 commit, 有 dirty 就警告; UI 警告 banner.
4. **回溯 UI** — chat 顶部 prev/next + timeline view; WS action 调 git_checkout
   重放历史.
5. **数据迁移** — 现有 session 全部跑一遍 backfill; 已有 git 项目 import 成 Project.
