# 在另一台机器上运行会话

运行环境决定会话在哪里执行命令、读写文件。OpenProgram 有三种：

| 类型 | 命令在哪里执行 | 文件在哪里读写 |
| --- | --- | --- |
| 本地 | 这台电脑 | 这台电脑 |
| SSH | 远程主机，从它的远程文件夹开始 | 远程主机 |
| Docker | 这个会话专属的容器 | 这台电脑；会话的文件夹以相同路径挂载进容器 |

本地始终存在。SSH 主机和 Docker 容器需要自己添加。

运行环境不是渠道。[渠道](../integrations/channels.zh.md) 决定会话的消息同步到哪里，例如微信或 Telegram 账号。绑定渠道不会改变工具在哪里运行。

## 为新会话选择环境

输入框上方第一个 chip 显示运行环境。在新会话里点它选择。发出第一条消息时环境被固定，之后 chip 只显示、不能再改。要换到别处，新建会话。

新会话使用默认环境。环境功能上线前创建的会话也使用默认环境。

chip 图标的颜色表示与后台的连接：黄色是连接中或已暂停，红色是已断开。

## 添加环境

在 Web 或 App 里打开 **设置 → 运行环境**：

- **SSH 主机**：填 ID、主机（`user@host` 或 `~/.ssh/config` 里的主机名），远程文件夹可选。文件夹留空则从远程家目录开始。
- **Docker 容器**：填 ID 和镜像，默认镜像是 `ubuntu:24.04`。

同一页面可以 **测试**、**设为默认** 或 **删除** 环境。

在终端里：

```bash
openprogram environments add ssh devbox --target me@devbox --workdir ~/work
```

```bash
openprogram environments add docker sandbox --image python:3.12 --default
```

```bash
openprogram environments list
```

```bash
openprogram environments test devbox
```

`openprogram environments default <id>` 设置默认，`openprogram environments rm <id>` 删除。`openprogram setup` 里也有 **Default environment** 一步。

## SSH 要求

OpenProgram 用系统的 `ssh` 并开启 `BatchMode=yes`，所以登录过程不能有任何交互。请使用 SSH agent 或 `~/.ssh/config` 已经提供的密钥。新主机的指纹第一次自动接受，之后会校验。连接会复用五分钟，让工具调用更快。

远程主机需要 POSIX shell、`find` 和 `grep`；装了 `rg` 时会优先用它。

## Docker 要求

`docker` 命令要在 PATH 里，Docker 守护进程要在运行。每个会话一个常驻容器，名字是 `openprogram-<环境>-<会话>`。第一条命令启动它，之后的命令复用它，所以装过的软件包在这个会话里一直保留。会话的文件夹变化时容器会重建。删除会话时容器随之删除。

## 限制

- SSH 主机上改动的文件不在一轮的撤销范围内。这台电脑上的文件照常可以撤销。
- 在 SSH 里，文件要先读再改。如果上次读取后主机上的文件变了，编辑会被拒绝，需要重新读取。
- 本地沙箱只作用于本地环境。SSH 和 Docker 以远程账号或容器的权限运行。
- 如果会话的环境被删除，它的工具会报错停止，绝不会退回到这台电脑上执行。用同样的 ID 把环境加回来，或者新建会话。
