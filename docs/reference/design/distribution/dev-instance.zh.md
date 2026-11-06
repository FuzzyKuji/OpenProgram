# 稳定版与开发版实例

一个源码 checkout 驱动本机的两个实例。稳定版是 owner 日常使用的那个。开发版是新提交先跑起来的地方，用来测试和展示使用案例。提交只能通过晋升进入稳定版。稳定版随时可以改动和使用开发版，而不需要重启自己。

| | 稳定版 | 开发版 |
| --- | --- | --- |
| 代码 | `stable` 分支，只靠晋升移动 | 最近一次部署过去的 `dev` 提交 |
| 运行 | `/Applications/OpenProgram.app`，端口 18100 | `/Applications/OpenProgram Dev.app`（macOS）或浏览器，端口 18200，运行时在 `~/.openprogram-dev/runtime` |
| 数据 | `~/.openprogram`（默认 profile） | `~/.openprogram-dev`（`dev` profile） |
| 更新方式 | `openprogram dev promote` → `scripts/refresh-local-app.sh` | `openprogram dev deploy` → `scripts/refresh-dev-instance.sh` |

规则在 `openprogram/operations/worker/dev_instance.py`，对应命令是 `openprogram dev`。

## 部署到开发版

`openprogram dev deploy [ref]`（默认 `dev`）把提交检出到受管的 detached worktree `~/.openprogram-dev/source`，在那里运行 `scripts/refresh-dev-instance.sh`。脚本：

1. 拒绝未提交的改动；
2. 构建 Web 资源和 OpenProgram wheel；
3. 首次在运行时里装一份完整的 CPython 3.12（`uv python install --install-dir`），同步到 release 安装的锁定依赖集，再重装 wheel；
4. 在 macOS 上构建命名的辅助程序 `OpenProgram Dev.app`（bundle id `ai.openprogram.runtime.dev`），并让 `runtime-manifest.json` 指向它。这样 worker 用自己的身份运行，屏幕录制、辅助功能等权限和稳定版运行时分开授予；
5. 把 `dev` profile 的端口设为 18200，绑定 Program 目录；
6. 只把 `dev` worker 安装或重启为登录服务（launchd 或 systemd），重启电脑后会自己起来；等 `/healthz` 通过，把提交写进 `runtime/source-revision`；
7. 在 macOS 上运行 `scripts/install-dev-app.sh`，安装下面说的开发版 App。

稳定版的任何东西都不会被停止或写入，所以稳定版 App 里的对话可以部署，然后在浏览器打开 `http://127.0.0.1:18200` 或调用它的接口查看结果。

### 开发版 App

`/Applications/OpenProgram Dev.app`（bundle id `ai.openprogram.desktop.dev`）是部署提交的桌面壳，连的是开发版实例，这样 owner 在稳定版里工作的同时，可以在另一个 App 里测试。它不带运行时：`Contents/Resources/instance.json` 写明 `dev` profile、端口 18200 和 `~/.openprogram-dev/runtime`，由 `apps/desktop/main/instance.js` 读取。有这个文件时，壳连接 18200，用开发版运行时在 `OPENPROGRAM_PROFILE=dev` 下启动 worker 和取登录令牌，Electron 数据放在 `~/Library/Application Support/OpenProgram Dev`，不看稳定版安装器的锁，也从不检查发布更新。

`scripts/install-dev-app.sh` 把它装在稳定版 App 旁边，从不写进稳定版 App。它用 `scripts/release/build-desktop-shell.sh`（electron-builder，发布配置去掉运行时）构建这个提交的完整桌面壳，所以 `apps/desktop/package.json` 固定的 Electron 先在开发版 App 里跑。然后改 bundle 名称，写 `instance.json`，再用本地身份签名（`local-macos-signing.py sign --development`：没有内置运行时，所以只签外层 App）。替换 bundle 时 App 处于关闭状态，原来开着的话装完再打开。

两个 App 各有自己的浏览器调试端口，浏览器工具从这里附着到它的网页标签：稳定版 9223，开发版 9224（`instance.json` 的 `debugPort`）。`programs/applications/browser/chrome.py` 按当前 profile 选端口，所以开发版 agent 永远不会操作稳定版 App 的标签页。

稳定版刷新只替换 `app.asar`，保留 App 原有的 Electron。当 `package.json` 固定的 Electron 和已安装的不一致时，`scripts/refresh-local-app.sh` 构建同一个外壳，在 App 关闭期间把它的 frameworks、可执行文件、`Info.plist` 和语言资源移进稳定版 App，所以晋升带来的是开发版 App 已经跑过的 Electron。

### 登录

worker 每次启动都会生成新的 owner 令牌，所以每次部署都会让已登录开发版的浏览器掉线。开发版 App 会自己取回新令牌，普通浏览器做不到。`openprogram dev open` 在默认浏览器里打开开发版并直接登录，`openprogram dev auth-url` 打印给其他浏览器用的登录链接。浏览器掉线时的提示会给出这两个命令。

### 数据与模型

开发版有自己独立的数据，凭据也在其中：凭据存储的根目录和其他路径一样是当前 profile 的状态目录，所以 `dev` profile 不会读取或刷新默认 profile 的登录。

`openprogram dev copy-models` 把稳定版的模型配置给开发版。它复制 provider 设置（`providers`、`api_keys`、`last_used_model`）、API key 凭据和委托给外部 CLI 的凭据（只引用其他工具的登录）。OAuth 登录不复制：它们的 refresh token 会轮换，两个实例刷新同一个登录会互相顶掉。开发版需要的话，在那边重新登录。会话、Agent 和记忆从不复制。

### 从对话里

有 `stable` 分支时，`self_update(action="prepare")` 照旧校验候选 worktree，但不再装进 App，而是在后台运行 `openprogram dev deploy <candidate>`，日志写到 `~/.openprogram-dev/deploy.log`，并返回开发版地址。稳定版只通过晋升改变；晋升只做 fast-forward，所以要先把候选合进 `dev`。

## 晋升到稳定版

晋升有意只做成命令，不在设置页放按钮：它是开发环节的一步，由 owner 或 owner 要求的 Agent 执行。`openprogram dev promote [revision]` 把稳定版升级到开发版正在服务的那个提交。以下条件全部满足才执行：

- 提交就是 `~/.openprogram-dev/runtime/source-revision` 里记录的那个，且不是 dirty 构建；
- 开发版的 `/healthz` 有响应；
- 提交包含当前的 `stable`，也就是只做 fast-forward。

然后先备份稳定版 profile（`openprogram backup`，标签 `pre-promote`），用 compare-and-swap 移动 `refs/heads/stable`，两次晋升不会互相覆盖。再把提交检出到 `~/.openprogram/release-source`，运行 `scripts/refresh-local-app.sh`，以事务方式安装 App 并重启稳定版 worker。备份在旧的稳定版 worker 仍在服务时进行；晋升本身不打开稳定版的数据存储。由重启后、运行新代码的 worker 迁移执行存储，并修好旧 worker 晚写入的行（见[谁来迁移执行存储](../runtime/execution/control.zh.html#store-schema-ownership)）。同一条规则也让仓库里的 `.venv/bin/openprogram` 对默认 profile 运行时，不会在运行中的 App 底下升级稳定版的存储。

`stable` 分支存在后，`scripts/refresh-local-app.sh` 只安装 `refs/heads/stable`。从 `dev` 或其他提交发起的刷新会被拒绝，并提示改用开发版。这样「每次提交都进 App」的习惯不会悄悄回来。

## 发布

两个实例都不推送任何东西。GitHub 每个版本只收一个从 `stable` 发布的压缩提交，见[向 GitHub 发布源码](github-publishing.zh.md)。

## 源码 checkout

两个命令通过 `OPENPROGRAM_SOURCE_REPO` 找到仓库，没有设置时读 `~/.openprogram/source-repo`；两个刷新脚本都会写这个文件，记录的是主 checkout，不是构建用的 worktree。

## 实现状态

- 已实现：两个刷新脚本、`stable` 门禁、`openprogram dev status|deploy|open|auth-url|copy-models|promote`、晋升前的检查和备份、开发版运行时自己的 macOS 身份和登录服务、按 profile 隔离的凭据、对话内自更新改为部署到开发版。
- 未实现：开发版只能在本机访问。
