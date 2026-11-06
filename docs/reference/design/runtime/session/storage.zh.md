<div id="session-数据模型"></div>

# 数据模型

## 磁盘布局

会话存放在所属项目的文件夹里。每个项目（包括 id 为 `default` 的主目录项目）
各有一个文件夹：

```
<state>/projects/
├── projects.json                      # 项目注册表
├── <project_id>/                      # 每个项目一个文件夹；`default` 是主目录项目
│   ├── settings.json                  # 项目默认设置
│   ├── memory/                        # 项目的记忆工作区
│   └── chats/
│       ├── <session_id>/              # 会话 Git 仓库
│       │   ├── .git/                  # 会话仓库元数据
│       │   ├── meta.json              # 会话元数据和 DAG 当前 head
│       │   ├── history/               # 每个 DAG 节点一个 JSON 文件
│       │   ├── context/               # 持久化上下文产物
│       │   └── workdir/attachments/   # 该会话上传的文件
│       └── .file-recovery/<session_id>/<turn>/ # 每轮的文件撤销恢复
├── .chats-index.json                  # 注册表（摘要缓存）
├── .chats-locations.json              # session id → 仓库路径的持久映射
├── .migration/                        # 迁移日志和 staging 状态
├── .deleted/                          # 持久化删除意图
└── .locks/ / .session-locks/          # 进程间协调
```

存储根目录是 `<state>/projects`，其中 `<state>` 是 OpenProgram 状态目录。
会话放在 `<project_id>/chats/<session_id>`；不属于任何项目的会话归主目录项目，
落在 `default/chats/`。存储自己的簿记文件以隐藏条目放在同一个文件夹里，
所以列目录只看到注册表和各项目文件夹。在其他根目录上打开的存储（应用运行
记录、嵌入宿主）也用同样的 `<project_id>/chats/<session_id>` 放置方式。

把会话分配到另一个项目时，会在注册表里重新绑定并更新 `meta.json`；还没有
历史的会话会连文件夹一起移动。已有历史的会话保留原文件夹，由
`.chats-locations.json` 记录位置。迁移或重定位期间，`.chats-locations.json`
是持久路径权威来源。工作目录不会作为主要会话仓库；旧的
`<project>/.openprogram/sessions/<id>/` 只作为 legacy 迁移源读取。

## 持久字段（meta.json）

| 字段 | 类型 | 注册表 | 说明 |
|------|------|--------|------|
| `id` | str | 是 | session 唯一标识 |
| `agent_id` | str | 是 | 绑定的 agent |
| `title` | str | 是 | 显示名称 |
| `created_at` | float | 是 | 创建时间戳 |
| `updated_at` | float | 是 | 最后活动时间戳 |
| `project_id` | str? | 否 | 绑定的项目（列举时由 project_map 补充为 `project` 名称） |
| `source` | str? | 是 | 来源："tui" / "web" / "wechat" / ... |
| `channel` | str? | 是 | 渠道类型 |
| `account_id` | str? | 是 | 渠道账号 |
| `peer_display` | str? | 是 | 对方显示名 |
| `peer_id` | str? | 是 | 对方 ID |
| `pinned` | bool | 是 | 置顶 |
| `archived` | bool | 是 | 归档 |
| `group` | str? | 是 | 分组标签 |
| `status` | str | 是 | 生命周期状态（见下方） |
| `unread` | bool | 是 | 未读标记 |
| `sort_at` | float | 是 | 在项目列表里的位置，表示为排序用的时间；0 = 没有（见 operations.zh.md“项目列表里的位置”） |
| `sort_since` | float | 是 | 摆放时的 `updated_at`；活动超过它，位置失效 |
| `_auto_titled` | bool | 否 | 自动命名幂等标记（内部控制，不进注册表、不返回前端） |

"注册表"列标记该字段是否缓存到 `.chats-index.json`。`_auto_titled` 和 `project_id` 不进注册表：前者是内部标记，后者在列举时由项目目录映射补充。

## 注册表独有字段

以下字段只在注册表中，不在 meta.json 中：

| 字段 | 说明 |
|------|------|
| `preview` | 最后一条用户消息前 80 字符，由写消息时截取维护 |

## status 枚举

| 值 | 含义 | 前端显示 |
|----|------|----------|
| `idle` | 空闲，无 turn 在执行 | 灰点 |
| `running` | 有 turn 正在执行 | 绿色转圈 |
| `needs_input` | agent 等待用户输入 | 琥珀点 |
| `done` | 后台任务完成 | 配合 `unread` 显示蓝点 |
| `failed` | turn 执行失败 | 配合 `unread` 显示红点，打开后变灰点 |
| `interrupted` | worker 在 turn 中途死掉 | 灰点（不算 run-active） |

`running` 由 dispatcher 在 turn 开始时写入、结束时清除。worker 中途被杀
（SIGKILL、崩溃）就跑不到清除那一步，会话行会永远停在 `running`，把聊天容器
钉在 `data-run-active="true"` 上，除非手改磁盘状态否则出不来。因此
`reconcile_interrupted_runs()` 在 worker 启动时把仍是 `running` 的行重置为
`interrupted`——新起的 worker 按定义没有任何东西在跑。这一步与同一函数里的 DAG
节点扫描相互独立：worker 若在写 status 和插入 placeholder 之间被杀，就会留下一
个 running 的**行**却没有 running 的**节点**。

## 移动 HEAD：`_set_active_head`

`webui/server.py` 按会话持有一份内存镜像 `_sessions[sid]`，含 `head_id` 与
`messages`，而 `_save_session` 会把两者原样写回 SessionStore。所以只改 store
的 HEAD、不同步镜像的路径不只是"数据过期"——**下一次保存会主动把这次移动撤销。**

`_set_active_head(session_id, head_id)` 是移动 HEAD 的唯一正确入口。它依次完成：
写 SessionStore、把新分支读回镜像的 `head_id` 与 `messages`、清消息缓存。所有会
改动的路径都走它：retry、edit、兄弟节点 checkout、deepest-leaf 跳转、分支
checkout、删分支、attach、rewind。

有 turn 在运行时（`_is_run_active`），所有移动 HEAD 的操作一律拒绝，返回
`RUN_ACTIVE_ERROR` 并带 `code: "run_active"`。没有这道保护，在飞的回复落地时
predecessor 会指向用户已经离开的分支；删分支更糟——要删的那条尾巴可能正是当前
turn 正在写入的。

## 进程内缓存（`_sessions` dict）

`SessionStore` 缓存延迟加载的 `(GitSession,
SessionMemoryIndex)` 对。`GitSession` 负责文件和 Git 操作；内存索引从
`history/` 与 `meta.json` 重建，记录 DAG 节点、边和活动 head。索引采用有上限
的 LRU 缓存，也可以在子进程写入仓库后主动失效并重建。

浏览器上传的附件在 dispatch 前复制到
`<session repository>/workdir/attachments/`。消息标记保留保存后的绝对路径，
该副本在 turn 结束时与会话仓库一起提交。渠道入站文件使用
`<state>/channels/*/accounts/*/attachments` 下的渠道附件根目录，由附件路径
策略单独允许读取。`.file-recovery/<session_id>/<turn>/` 是普通的每轮文件撤销
恢复目录，位于会话 Git 仓库之外。legacy 项目迁移时，会话数据和已有恢复目录
先暂存到 `<state>/projects/.migration/staging/` 并校验，再发布到中央目标路径的
`.file-recovery` 兄弟目录；发布完成后才更新 `.chats-locations.json`。

历史附件标记会保留原始绝对路径。附件界面、文件读取和 `send_file` 的路径解析
只允许把精确的旧路径形式
`<project>/.openprogram/sessions/<session_id>/workdir/attachments/<relative>`
按同一个 session id 重新定位到唯一的当前仓库。重新定位后的路径必须仍在允许的
附件根目录内，不能通过 `..` 或符号链接越界；系统不会任意重映射旧路径。

## 接口

```python
class SessionStore:
    def create_session(session_id, agent_id, *, title="", source=None, **meta) -> None
    def get_session(session_id) -> dict | None
    def update_session(session_id, **fields) -> None
    def delete_session(session_id) -> None
    def list_sessions(*, limit=100, offset=0, **filters) -> list[dict]
    def get_branch(session_id, head_id=None) -> list[dict]
    def append_message(session_id, msg) -> None
    def latest_user_text(session_id) -> str | None
```

每个方法的完整行为见 [operations.md](operations.zh.md)。
