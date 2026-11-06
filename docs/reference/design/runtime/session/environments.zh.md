# 运行环境

运行环境是会话执行命令和文件工具的地方：这台电脑（`local`）、SSH 主机（`ssh`）或 Docker 容器（`docker`）。渠道（微信、Telegram……）是另一条轴：它决定消息同步到哪里，从不移动工具。产品文档见[在另一台机器上运行会话](../../../../capabilities/environments.zh.md)。

## 1. 注册表

注册表存在 `config.json`：

```json
"environments": {
  "default": "local",
  "items": [
    {"id": "devbox", "name": "devbox", "kind": "ssh", "ssh_target": "me@devbox", "workdir": "~/work"},
    {"id": "sandbox", "name": "sandbox", "kind": "docker", "image": "ubuntu:24.04"}
  ]
}
```

- `local` 内置，不落盘，不能改也不能删。
- ID 匹配 `^[a-z0-9][a-z0-9_-]{0,47}$`。`ssh_target` 不含空白、不以 `-` 开头，避免被 ssh 当成选项；`workdir` 是绝对路径或以 `~` 开头；镜像名不含空白、不以 `-` 开头。
- 旧安装里配置过 `backend.terminal` / `ssh_target` / `docker_image` 的，这一项按类型名读成一个环境并作为默认；第一次写入时折进 `environments` 段。
- 删掉默认环境后，默认回到 `local`。

代码在 `openprogram/host/environments/__init__.py`。所有写入都走 `update_config`，它持有跨进程的配置锁。CLI（`openprogram environments`）、setup 向导这一步和 WebSocket 动作（`list_environments`、`save_environment`、`delete_environment`、`set_default_environment`、`test_environment`）都是它上面的薄层。每次修改都会广播一帧 `environments`，所有打开的输入框随之刷新列表。

## 2. 会话绑定

会话在 session meta 里存 `environment_id`，这个字段有索引，所以列表也能带上它。

- **草稿**：输入框把选择存在自己的 composer 设置里（`ComposerSettings.environment`），第一帧 `chat` 以 `environment_id` 带上。
- **第一条消息**：`assign_new_session_environment` 校验选择（未知 ID 返回 `unknown_environment` 错误）并写入；没选就写默认环境。`chat_ack` 回报实际生效的 ID。
- **之后**：ID 不再变化。已经存过 ID 的会话保持原样。有历史却没有 ID 的会话是环境功能上线前创建的，继续跟随默认，不会被后来的选择挪走。
- **渠道会话**创建时写入默认环境的 ID。

存的 ID 已不存在时，`resolve_for_session` 抛 `EnvironmentError`，当前后端变成 `UnavailableBackend`，每条命令都返回同一段说明。工具绝不退回到这台电脑：把会话的命令跑在用户没选的机器上，比拒绝更糟。

## 3. Turn 绑定

`TurnBindings.bind` 解析会话的环境，在本轮绑定到 ContextVar `_current_environment`。`current_environment()` 先读这个 ContextVar；不在 turn 里时退到当前会话的环境，再退到默认。

- **SSH**：本轮的 worktree ContextVar 设为远程工作文件夹的绝对路径。`remote_workdir` 在 `cd` 后执行 `pwd`，所以 `~` 在远程主机上展开；结果按环境缓存。工具的相对路径用 `posixpath` 拼接，从不碰本机文件系统。权限围栏读的也是这个 ContextVar，所以检查的是远程文件夹。
- **Docker**：worktree 留在本机，因为容器以相同路径挂载了它。
- **沙箱**：本机沙箱只作用于 `local`。SSH 和 Docker 的 turn 把沙箱策略关掉，隔离由远程账号或容器负责。
- system prompt 的工具运行块会多一行 "Environment:"，写明 SSH 主机或 Docker 镜像，让模型知道命令不在本机执行。

## 4. 后端

`openprogram/host/backend/__init__.py` 的 `get_active_backend()` 根据 `current_environment()` 和当前会话构造后端：

| 类型 | 后端 | 命令形式 |
|---|---|---|
| local | `LocalBackend` | 本机子进程 |
| ssh | `SshBackend(target, workdir)` | `ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ControlMaster=auto -o ControlPath=<state>/ssh/%C -o ControlPersist=300 <target> 'cd <dir> && <cmd>'` |
| docker | `DockerBackend(image, container, mounts)` | `docker exec -i [-w cwd] <container> sh -c <cmd>` |

SSH 连接复用让第一次之后的每次工具调用只要一个往返。`%C` 是 host、port、user 的哈希，socket 路径因此不会超过 macOS 的 `sun_path` 上限。Windows 上不启用 ControlMaster。文件夹开头的 `~` 不加引号传给远程 shell，以便在那边展开。

每个 Docker 会话一个常驻容器 `openprogram-<env>-<session>`（`[a-zA-Z0-9_.-]` 以外的字符换成 `-`），用 `docker run -d --init … tail -f /dev/null` 启动。会话的工作文件夹、项目文件夹和附加工作目录以相同路径 bind mount，所以本机路径在容器里照样有效；第一个挂载是起始文件夹。镜像加挂载的哈希存为 label `openprogram.mounts`：哈希变了就删掉重建，哈希一致而容器停着就重新启动。进程内缓存让第一条命令之后跳过 `docker inspect` 探测。删除会话时在后台线程删除它的容器。没有会话 ID（不在任何会话里）时退回一次性的 `docker run --rm`。

## 5. 文件工具

`read`、`write`、`edit`、`apply_patch`、`glob`、`grep`、`list` 先调用 `remote_target()`。SSH 环境下它返回 `RemoteFS`，工具转交给 `openprogram/programs/tools/files/_remote.py`，输出格式与本地工具一致。Docker 和本地返回 `None`，走原来的本地路径，因为 Docker 的文件夹就是本机文件夹。

`RemoteFS`（`openprogram/host/environments/remote.py`）是 `SshBackend.run_bytes` 上的薄层：

- `stat`：一条 `test` 命令报告是否存在、是否目录、大小。
- `read_bytes`：`cat`，上限 32 MiB。
- `write_bytes`：先 `mkdir -p`，在同一文件夹写临时文件，再 `mv` 覆盖目标，读者不会看到写了一半的文件。
- 退出码 255 是 ssh 自身失败，转成 `ConnectionError`，工具把它当错误报告，而不是当文件内容。

查找在远程执行：`glob` 用 `find` 列文件，再用从 glob 转出的正则过滤；GNU `find -printf` 提供修改时间，BSD 的 `stat` 写法兜底。`grep` 有 `rg` 就用 `rg`，否则 `grep -rE`，用 `head` 截断。`list` 用一段 shell 循环。读 PDF 时把字节拷到本机临时文件，复用本地 PDF 读取器。

先读后改的规则在远程照样成立。成功的读或写按（会话、主机、路径）记一个 sha256。`write`（覆盖已有文件）、`edit`、`apply_patch` 会重新读取文件，从没读过或哈希变了就拒绝。

远程文件不在本机的 turn checkpoint 里，revert / undo 不会恢复它们。本地 `write` 工具的 `source_path` 选项（拷贝本机文件）在 SSH 下被拒绝，因为它会悄悄跨机器。

## 6. 输入框

输入框上方的环境行以两个 chip 开头：

- **环境 chip**（始终显示）：图标对应类型（monitor / cpu / box），文字是环境名，图标颜色是原来状态 chip 显示的后台连接状态。草稿里点开是环境列表加一个去 设置 → 运行环境 的链接，选择写进草稿的 composer 设置。会话创建后菜单仍能打开，但其他环境变灰，并说明环境已固定。
- **渠道 chip**（始终显示）：聊天图标，绑定后颜色来自渠道健康轮询（`channelHealth`）；文字是"未接渠道"或"WeChat · 账号"。点开是渠道菜单：账号按平台名分组、已绑定的打勾，绑定时有"断开"，底部是"管理渠道"。

输入框只在这个 chip 上设置渠道，**+** 菜单里没有渠道项。渠道菜单和渠道 chip 共用 `channel-choices.ts`，它跟随输入框所在的面板（`useBoundChat`），分屏时每个面板读写自己的会话。

后台连接状态（`statusBadge`）和渠道健康（`channelHealth`）是两个独立的 store 字段，互不覆盖对方的 chip。

## 实现状态

已实现：本地 / SSH / Docker；注册表、CLI、向导步骤、设置页和 WebSocket 动作；第一条消息固定环境；SSH 文件工具；每会话一个 Docker 容器。

未实现：

- 按项目设置默认环境，目前默认是全局的。
- WSL 和云端环境。
- 密码或交互式 SSH 登录。
- 远程文件的 checkpoint / undo。
- 把已有会话迁到另一个环境。
