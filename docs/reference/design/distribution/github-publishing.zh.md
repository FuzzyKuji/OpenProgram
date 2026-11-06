# 向 GitHub 发布源码

仓库保留三条线，各自按不同的节奏前进。`dev` 接收每一个小提交：试了又改回的视觉调整、修补上一个修复、重构的某一步。`stable` 接收在开发版上验证过并晋升的提交，稳定版 App 运行的就是它。`main` 是慢线：在 `stable` 上积累了几十上百个小改动之后才做一个版本，一个版本一个提交，所以它的历史是一份版本列表，而不是工作日志。GitHub 只有 `main`。

| | `dev` | `stable` | `main` |
| --- | --- | --- | --- |
| 提交 | 任何会话的每一个提交 | 快进到的那些 `dev` 提交 | 每个版本一个压缩提交 |
| 由谁移动 | 主检出或 worktree 里的 `git commit` | 只有 `openprogram dev promote` | 只有 `scripts/publish-github.sh` |
| 运行或供给 | 开发版（端口 18200） | 稳定版 App（端口 18100） | GitHub 的 `main`：源码安装、CI、发布标签 |

`dev` 和 `stable` 共用一条历史。`main` 有自己的历史：每个版本的提交装着 `stable` 的文件树，父提交是上一个版本，所以任何 `dev` 提交都不是它的祖先，两边永不合并。也不会把 GitHub 的 `main` 拉回 `dev` 或 `stable`。

## 分支

本地只有这三个分支。功能分支和 worktree 分支只短期存在：合入 `dev` 后删掉，放弃了也删掉。不想删又不想碍事的分支放到 `refs/archive/` 下，它不会作为分支列出，也不会被推送。

## 发布一个版本

```bash
scripts/publish-github.sh -m "Sidebar run status, Launchpad, Agent cards" --dry-run
scripts/publish-github.sh -m "Sidebar run status, Launchpad, Agent cards"
```

脚本默认压缩 `stable`，因为 `stable` 是部署到开发版、在那里验证过并晋升的提交。`--source <ref>` 可以改为压缩 `dev` 上的其他提交。

1. 把守卫（见下文）安装到共享的 `.git/hooks`，每个 worktree 都会生效。
2. 源提交不在 `dev` 上时拒绝。`main` 已经是源提交的文件树时不产生新版本，直接进入推送。
3. 扫描这个版本新增的行，查找像真实凭据的内容（GitHub token、Anthropic API key、AWS access key、私钥块），发现就拒绝发布。AWS 文档里的示例 key 和测试里写在一行的 PEM 字符串不算。
4. 生成提交说明：`-m` 给的摘要、上个版本以来的本地提交数量，以及指明来源提交的 `Local-Source:` 尾注。
5. 用 `git commit-tree` 创建提交：文件树取自源提交，唯一的父提交是上一个 `main` 提交（第一个版本没有父提交），把 `main` 移到它，并在 `refs/publish/last` 记下源提交，作为下一个版本计数的起点。
6. 确认 GitHub 的 `main` 是本地 `main` 更早的一个点后推送，所以推送总是快进。`--no-push` 在第 5 步后停下。

## 守卫

`scripts/git-hooks/pre-push` 拒绝推送 `refs/heads/main`，除非来自脚本（脚本会设置 `OPENPROGRAM_GITHUB_PUBLISH=1`）且推的是本地 `main`。推 `dev` 会上传整条工作历史，所以推送其他任何分支也会被拒绝。删除远程分支和推送标签不受限制。

`scripts/git-hooks/pre-commit` 在检出 `main` 时拒绝提交。还把 `main` 当成提交位置的会话会立刻失败，而不会把工作提交混进慢线。

本机的全局 hooks（`core.hooksPath`）会把 `pre-push` 和 `pre-commit` 转交给仓库的 `.git/hooks`，所以脚本把守卫装在那里。

## 会话规则

- `dev` 想提交多频繁都可以；部署和晋升按[稳定版与开发版](dev-instance.zh.md)的流程。
- 永远不要在 `main` 上提交，不要手动 `git push` 它，也不要把 `main` 合进 `dev` 或 `stable`。
- 不要把其他分支推到 GitHub，也不要从本地分支开 PR：它们的历史是 `dev` 那条线，PR 会列出每一个本地提交。
- 一个版本准备好时再发布，通常是多次晋升之后，不要每个功能都发。

## 实现状态

- 已实现：`scripts/publish-github.sh`（dry run、`--no-push`、凭据扫描、`refs/publish/last`）；`pre-push` 和 `pre-commit` 守卫；`AGENTS.md` 里的规则。
- 未实现：发布标签仍需手动打在发布的提交上。
