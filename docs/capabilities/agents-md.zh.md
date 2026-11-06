# 用 AGENTS.md 写指令

给 agent 的长期指令写在名为 `AGENTS.md` 的文件里。所有 Agent 都读这些文件，没有按 Agent 区分的副本。要给某一个 Agent 单独的指令，用它 **Advanced** 标签页里的 **System prompt**（见[配置 Agent](agents.zh.md)）。

## 文件放在哪里

| 文件 | 作用范围 |
| --- | --- |
| `~/.openprogram/AGENTS.md` | 所有项目 |
| 项目根（包含 `.git` 的文件夹）的 `AGENTS.md` | 这个项目 |
| 项目里任意子文件夹的 `AGENTS.md` | 这个文件夹及其下所有内容 |

每轮开始时，agent 先读全局文件，再从项目根到工作目录逐级读取每个 `AGENTS.md`。项目根以上的文件夹不读。没有 `.git` 文件夹时，只读工作目录自身的 `AGENTS.md`。

比工作目录更深、或在另一个项目里的文件，在 agent 第一次读、写或编辑那个文件夹里的文件时读取；它的内容附在那次工具结果后面，每个对话只附一次。

工作目录是对话的项目文件夹或 worktree，否则是默认工作目录（`OPENPROGRAM_WORKDIR`，或 `~/.openprogram/config.json` 里的 `default_workdir`）。

## 冲突怎么处理

文件按从通用到具体的顺序拼接。离正在处理的文件越近的文件排得越后，冲突时以它为准，所以子文件夹的 `AGENTS.md` 可以收窄或覆盖项目根的规则。

## 限制

全局文件和项目文件每轮共用 32 KB。总量超出时，最深的文件被截断，提示词里会标出截断处。看起来像提示词注入的文件仍会被加入，但前面带一条警告。

## 查看哪些文件生效

**Agents → Advanced → AGENTS.md** 显示工作目录、全局文件路径（尚未创建时也显示），以及下一轮会读取的每个项目文件。用 **复制路径** 在编辑器里打开。

## 以前的工作区文件

Agent 以前在 `~/.openprogram/agents/<id>/workspace/` 下各有 `AGENTS.md`、`SOUL.md`、`USER.md` 和 `TOOLS.md`，现在不再读取。worker 启动时，未改过的模板被删除；改过的文件追加到该 Agent 的系统指令里（标题为 `## From workspace <文件名>`），原文件移到 `workspace/.retired/`。
