# AGENTS.md

## Anthropic 接入与合规要求

本项目要求安全、合法、合规地使用 Anthropic 服务。Anthropic 集成仅使用官方 API 和合法获取的 API key，按 API 账户计费；所有调用必须遵守 Anthropic 的服务条款与使用政策。维护相关代码和文档时，应保持这一接入方式与要求。

## 本地运行实例

本机有两个实例，从同一个仓库构建（关系见 `openprogram/operations/worker/dev_instance.py`）：

| | 稳定版 | 开发版 |
| --- | --- | --- |
| 代码 | `stable` 分支，只靠晋升移动 | `dev` 上部署过去的提交 |
| 运行 | `/Applications/OpenProgram.app`，端口 `18100` | `/Applications/OpenProgram Dev.app`，端口 `18200`，运行时在 `~/.openprogram-dev/runtime` |
| 数据 | `~/.openprogram` | `~/.openprogram-dev`（`dev` profile） |

- 一个功能完成并提交后运行 `scripts/refresh-dev-instance.sh`（或 `openprogram dev deploy`），只更新开发版（运行时和 `OpenProgram Dev.app`）；它不碰稳定版的 App、运行时和 worker，可以在稳定版的对话里运行。
- 稳定版只通过晋升更新：`openprogram dev promote` 要求提交正是开发版正在服务、且健康的那个，只做 fast-forward，先备份 `~/.openprogram`，再移动 `stable` 并运行 `scripts/refresh-local-app.sh`。
- `scripts/refresh-local-app.sh` 只安装 `refs/heads/stable`；从 `dev` 或其他提交运行会被拒绝。禁止手动移动 `stable` 绕过晋升。
- 用户可见的 App 只有 `/Applications/OpenProgram.app`（稳定版）和 `/Applications/OpenProgram Dev.app`（开发版，由开发版部署安装，见 `scripts/install-dev-app.sh`）；日常测试和可视验收用开发版 App 或浏览器（`openprogram --profile dev web auth-url --base-url http://127.0.0.1:18200` 取登录链接），不占用稳定版。禁止运行 `node_modules/electron`、`npm run dev --workspace apps/desktop` 或临时 E2E Electron 作为用户可见 App。
- 禁止在 `post-commit` 中自动刷新任一实例；禁止从旧 worktree 或旧环境单独执行 `openprogram worker restart`。
- 本地只保留这两份可见 App；更新时覆盖现有内容，不创建按 commit 命名的 App 副本。
- CLI 的 profile 功能属于产品能力；本仓库的本地运行只用默认 profile（稳定版）和 `dev` profile（开发版），不再起其他 profile 或端口。

## 共享工作区

多个会话同时在主检出的 `dev` 分支上工作，共用一个 index。

- 提交只带自己的路径：`git commit -- <paths>`，提交前看 `git diff --cached`，不要用裸 `git commit` 或 `git add -A`。
- 移动、重命名、拆分文件这类结构改动在自己的 worktree 里做完，测试通过后一次合入 `dev`；不要在共享 index 里长期留着暂存的重命名或半成品。
- worktree 的分支合入后就删掉 worktree（`git worktree remove`）；被放弃的也一样，分支可以留着。

## 分支与 GitHub 发布

本地只有三条线，设计见 `docs/reference/design/distribution/github-publishing.md`：

| 分支 | 作用 | 谁移动它 |
| --- | --- | --- |
| `dev` | 开发线，所有会话往这里提交，开发版从它部署 | `git commit` |
| `stable` | 晋升线，稳定版 App 运行它 | 只有 `openprogram dev promote` |
| `main` | 慢线，GitHub 上唯一的分支，积累很多次晋升后才出一个版本，一个版本一个提交 | 只有 `scripts/publish-github.sh` |

- 日常提交只进 `dev`。禁止在 `main` 上提交（`pre-commit` 会拒绝），禁止把 `main` 合进 `dev` 或 `stable`，两边历史本来就不同。
- 发布只用 `scripts/publish-github.sh -m "版本摘要"`：它把 `stable` 的文件树压成一个提交接到 `main` 上，在 `refs/publish/last` 记下来源，再推送 `main`。先加 `--dry-run` 看提交说明；`--no-push` 只更新本地 `main`。
- 禁止手动 `git push`；`.git/hooks/pre-push` 只放行脚本推送的 `main`，其他分支一律拒绝。不要从本地分支向 GitHub 开 PR。
- worktree 分支合入 `dev` 或放弃后删除，想留着的放到 `refs/archive/`。

## 文档管理规则

`docs/` 是**产品文档站**（http://localhost:18100/docs），按用户问题组织成九个 Tab：
start / install / capabilities / interfaces / models / integrations / server / reference / design。
design 是虚拟 Tab——没有 docs/design/ 目录，nav.py 的 tab_of() 把 reference/design/ 下的
工程记录归档路由到它。
两类文字，去处不同：

1. **产品文档**（写给读者）：落到对应 Tab 目录。每一页因为"用户会问这个问题"而存在，
   不因为"仓库里有这块代码"。所有命令、参数、路径必须对着当前代码或 CLI `-h` 核实。
   功能改动时同步更新涉及的产品文档页——它和测试一样跟代码一起维护。
   新页要在 `scripts/docs_site/nav.py` 的 `PAGE_ORDER` 里登记侧栏顺序。
2. **工程记录**（设计稿、方案对比、实施计划、研究笔记，写给开发者自己）：
   放在 `docs/reference/design/`，按子系统组织，**持续维护、与代码同步**：
   一个主题只有一份文档，用现在时正面陈述当前设计；修订设计就改写文档本体
   （演变历史看 git），禁止 v2 副本、"Decision N/裁决"式变更记录、日期与
   commit sha。未实现的设计写进正文，在文末"实现状态"附录集中标注。
   不要把工程记录写进产品 Tab。
3. **站点根静态文件**（`docs/_static_root/`）：原样拷到站点根，不进导航、不进
   sitemap。放搜索引擎所有权验证文件、`robots.txt` 这类必须能从确切根 URL
   取到的文件。
4. **生成参考页**（`docs/reference/cli/`、`config-keys.md`、`provider-registry.md`）：
   构建时由 `scripts/docs_site/generate_reference.py` 从代码（argparse 树、
   state.settings.SETTINGS、provider.json）重新生成，已 gitignore，禁止手改——
   要改内容就改代码里的 help/说明文字。

双语约定：`xxx.md` 是**英文默认版**（站点主体，必须 100% 英文，不掺任何中文），
`xxx.zh.md` 是中文对照版（语言切换按钮跳转）。英文版为准；改内容先改英文版，再同步中文版。

硬性约束：
- 禁止把同一份文档复制到第二个位置（历史上因此产生过两份同名文档各自分叉）。
- 站内链接用相对路径指向 `.md`；指向 docs/ 之外仓库文件的链接一律写 GitHub URL
  （`https://github.com/FuzzyKuji/OpenProgram/blob/main/...`），站上解析不了相对上跳。
- 改完文档跑 `python -m scripts.docs_site.checklinks`，保持 0 死链。
- `docs/_site/` 是构建产物，已 gitignore，不要提交。
