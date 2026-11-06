<span id="cli"></span>
# 使用 CLI

在脚本或其他程序里调用 OpenProgram，一条命令拿到一次回复。

## 单发

```bash
openprogram --print "总结这个目录里的 python 文件都做什么"
```

发送 prompt、打印回复、退出。不进入 TUI。对话会写入会话存储，事后可在 Web UI 或 TUI 里翻看、续聊。

这个 profile 有 worker 在跑时（桌面 App、`openprogram worker start` 或前台的 `openprogram web`），这一轮就在那个 worker 上执行，和在 Web UI 里输入一条消息完全一样：agent 能用 App 的内置浏览器、频道桥接和会话自己的设置，这一轮也会实时出现在它所属的 Web UI 会话里。agent 追问时，命令把问题打印到 stderr 并从终端读取回答；没有终端（管道、cron）时问题不作答，这一轮继续跑。Ctrl-C 会取消 worker 上的执行。worker 侧出错时错误打印到 stderr，命令以 1 退出。这一轮跑到一半时 worker 重启（刷新、晋升）不会把它打断：命令会重新连上回来的 worker，跟完同一轮并打印回复；三分钟内没有 worker 回来，或这一轮在此期间被中断，命令会说明，Web UI 的会话里能看到它停在哪。

没有 worker 时这一轮在当前进程里用 CLI 自己的运行时执行，没有浏览器和频道。设置 `OPENPROGRAM_PRINT_IN_PROCESS=1` 可以在 worker 运行时也强制走进程内。

注意：`--print` 只接受参数里的字符串，不读 stdin。要把文件内容塞进 prompt，用 shell 替换：

```bash
openprogram --print "review 这段代码：$(cat main.py)"
```

## 续接指定会话

```bash
openprogram sessions list                 # 找会话 id
openprogram --resume <session-id> --print "接着上次的结论，下一步怎么做"
```

`--resume` 与 `--print` 搭配才生效。交互式续聊请在 TUI 里用 `/resume` 挑选会话（该参数目前在启动交互式 TUI 时被忽略），见[终端 TUI](tui.zh.md)。

## 隔离环境

```bash
openprogram --profile ci --print "..."
```

`--profile <name>` 把配置、会话、凭据整体切换到 `~/.openprogram-<name>/`，脚本环境不污染日常环境。也可以用环境变量 `OPENPROGRAM_PROFILE` 设置。

## 其他脚本化入口

聊天之外的子命令都可直接脚本化，多数支持 `--json` 输出，例如：

```bash
openprogram sessions list
openprogram providers list --json
openprogram providers discover --json
openprogram status
openprogram programs run <name> --arg key=value   # 运行一个 agentic 程序
```

完整命令清单见 `openprogram -h`，每个子命令有自己的 `-h`。
