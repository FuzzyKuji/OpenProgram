# Error Handling — 纪律与门禁

> 什么可以被 catch，catch 之后必须说明什么，以及 linter 在哪些路径上强制执行。

## 1. 规则

**只 catch 你能处理的，并为你吞掉的东西留下记录。**

一个不产生日志、不带注释、也没有 fallback 的 catch，与一个尚未被发现的 bug 无法区分。
静默 handler 的大部分代价是后来才付的，由那个正在琢磨"这次写入为什么没落盘"的人来付。

三条具体义务：

1. **精确 catch。** 文件 IO 抛 `OSError`；JSON 抛 `ValueError`（以及
   `json.JSONDecodeError`）；`ContextVar.reset` 用外部 token 抛 `ValueError`、用已消费的
   token 抛 `RuntimeError`。写出这个操作实际会抛的东西，全部。
2. **绝不吞掉程序员错误。** `AttributeError`、`TypeError`、`NameError` 这类是我们自己
   代码的缺陷，不是需要容忍的状况。宽到足以掩盖它们的 handler，要么收窄到掩盖不了，
   要么打日志让缺陷可见。
3. **说明为什么。** 剩下的每一处吞掉，都要带一条含上下文的日志，或者一条说明为什么忽
   略它是正确的注释。理由不显然时两者都写。

## 2. 边界

宽泛的 `except Exception` 在边界上是正当的——在那些地方，让异常继续向上传播会拖垮比
失败操作本身大得多的东西：

- **WebSocket handler 与 HTTP 路由**，异常会断连接而不是返回一个错误。
- **线程与 worker 入口**，异常在那里无人观测地消失。
- **回调调用**，调用方提供的代码运行在我们的循环里。
- **可选子系统**（memory、项目 git、用量计量），缺席只是功能降级，而不是这一轮失败。
- **尽力而为的簿记**，下一轮反正会重新推导出来。

边界上的 catch 仍然要记录足够的上下文，能定位到会话或操作。"边界"是继续运行的理由，
绝不是保持沉默的理由。

## 3. 选日志级别

| 级别 | 何时 |
|---|---|
| `error` | 用户会察觉、而且得动手处理的失败：重试后仍没送达的渠道消息、没能启动的 MCP server、彻底停下的 adapter。 |
| `warning` | 丢了用户可能察觉的东西：一次没落盘的写入、一个留在过期状态的 status、一条将会缺失的记录。 |
| `info` | 运行中的进程走了一条预期内的降级路径：等网络、重试、切到下一个模型、重连。 |
| `debug` | 一条可选路径按设计降级了：缺席的子系统、尽力而为的缓存、生效了的 fallback。开发者追踪也用它。 |

用 `exc_info=True` 保住 traceback，并带上 session id 或等价标识——多个 agent 同时运行
时，一条无法关联到会话的日志几乎没用。

## 4. 好的 handler 长什么样

让持久写入的静默丢失变得可见：

```python
except OSError:
    _log.warning(
        "index.json not saved for session %s", session_id, exc_info=True)
```

把原先掩盖缺陷的宽 catch 收窄：

```python
except (ValueError, RuntimeError):
    # ContextVar.reset raises ValueError for a token minted in another
    # context and RuntimeError for one already spent. Narrowing to only
    # the first lets a cancelled turn's spent token escape and replace
    # the CancelledError.
    _log.debug("context var token already spent or foreign", exc_info=True)
```

只有先弄清全集，收窄才是对的。去查这个调用实际会抛什么：上面的 `ContextVar.reset` 抛
两种毫不相关的类型，只写其中一种的 handler，会把本来被吞掉的失败变成跑出去的失败。

一个可选子系统，写明理由：

```python
except Exception:
    # Memory is optional: an unavailable provider degrades to no memory
    # block, never a failed turn.
    _log.debug("memory system prompt block unavailable", exc_info=True)
```

如果被保护的操作本身已经吞掉自己的错误，或者 catch 的是代码根本抛不出来的东西，这类
handler 直接删掉，而不是加注释。

## 5. 门禁

`ruff` 强制三条规则，配置在 `pyproject.toml`：

| 规则 | 抓什么 |
|---|---|
| `E722` | 裸 `except:`，它连 `KeyboardInterrupt` 和 `SystemExit` 一起吞掉。 |
| `S110` | `try` / `except` / `pass`——异常被丢弃，没有日志、没有注释、没有 fallback。 |
| `T201` | `print` 调用：库代码通过 `logging` 输出（见第 6 节）。 |

运行方式：

```bash
.venv/bin/ruff check .
```

### 覆盖范围

门禁覆盖整个 `openprogram/` 包。只有 `tests/` 和 `scripts/` 通过 `per-file-ignores` 静
音：测试里故意吞掉异常是为了断言后面的行为，脚本是手工运行的。第 6 节列出的命令行
入口另外只静音 `T201`。

`per-file-ignores` 的 pattern 匹配的是整条路径，其中的 `*` 会跨 `/`，所以
`openprogram/*.py` 静音的会是整个包而不是顶层那几个模块。新加 pattern 之前先拿一个嵌
套文件验一下：静音过头的 pattern 会把门禁关掉，而且不会让任何检查失败。

`BLE001`（盲目 `except Exception`）刻意不启用。会打日志并降级的边界 handler 是正确设
计，把它们全标出来产出的是噪声而非信号。第 2 节改由评审来约束这类代码。

ruff 的作用域仅限这道门禁。格式化与 import 顺序刻意不管——这是一条正确性规则，不是一
套风格制度。

## 6. 用 logging，不用 print

库代码通过 `logging` 报告：每个模块一个 logger，`_log = logging.getLogger(__name__)`，
级别按第 3 节选。logger 名已经说明记录来自哪里，所以消息不再带 `[模块]` 前缀；只有带数据
的方括号标签保留，例如 `[wechat:<account>]`。参数用 `%s` 格式化而不是 f-string，输出到哪
个流由 logging 决定。

`print` 只用于三种情况，被静音路径之外的每一处都用 `# noqa: T201 - <原因>` 写明是哪一种：

- **命令输出**——命令打印出来的结果（`openprogram cron list`、sandbox 模拟的 shell 命令、
  `assets.py` 的子命令）；
- **stdout 协议**——另一个进程读取的 JSON 行或哨兵行；
- **终端提示或状态**——引导终端前的人完成二维码登录或打开 OAuth URL，或告诉他前台运行
  已上线、怎么停止。

`per-file-ignores` 对整块命令行入口静音 `T201`，这些地方的 print 全是输出：
`openprogram/interfaces/cli/**`、`openprogram worker ...` 系列命令
（`operations/worker/lifecycle.py`、`runner.py`、`startup_log.py`、`services/**`）、升级
命令（`operations/self_update/**`），以及开发者工具 `models/providers/recording/**` 和
`**/probe_thinking.py`。

库里没有任何地方配置 logging。每个进程入口调用一次
`openprogram/host/process_logging.py` 的 `configure_process_logging()`：它给 root logger
挂一个写 stderr 的 handler，格式为 `%(asctime)s %(levelname)s %(name)s: %(message)s`，
并把 `httpx`、`httpcore`、`websockets`、`asyncio`、`mcp` 这些逐请求打日志的 logger 压到
`WARNING`：

| 进程 | 默认级别 | 原因 |
|---|---|---|
| Worker（`run_foreground`） | `INFO` | 它的 stdout 和 stderr 就是 worker 日志，记录落在 `[worker +12.3s]` 状态行旁边。 |
| 独立运行的 scheduler（`run_forever`） | `INFO` | 它的终端就是运行日志。 |
| 前台 Server（`python -m openprogram.interfaces.server`） | `INFO` | 同上。 |
| CLI（`interfaces/cli/application.py` 的 `main`） | `WARNING` | 交互式对话共用这个终端，只允许警告和错误出现在那里。 |

同一进程里后来的调用只调整级别、不再加 handler，所以经 CLI 启动的 worker 以 `INFO`
记录。别人已经配置好的 root logger（嵌入宿主、pytest）保留自己的 handler。
`OPENPROGRAM_LOG_LEVEL`（级别名，大小写不限）在每个进程里覆盖默认级别；无效值被忽略。

## 附录：实现状态

已实现。整个包通过 `E722` 与 `S110`；`ruff` 在 `dev` extra 中，配置在
`pyproject.toml` 的 `[tool.ruff]` 下，CI 对 `openprogram`、`tests`、`scripts` 运行它。
原先每一处 `try`/`except`/`pass`：异常集合已知的改为点名捕获；否则保留宽捕获，加一行说
明为什么可以忽略的注释和一行日志（丢了写入或状态过期用 `warning`，按设计降级用
`debug`）；包着不可能抛错、或自己已经吞错的调用（`emit_safe`、`emit_ws_frame`）的
handler 直接删除。

`T201` 同样通过：原先在 runtime、providers、MCP、channels、Server、scheduler 和语音代码
里用 `print` 输出的诊断，都改由各自模块的 logger 记录；剩下的调用是命令输出、stdout 协议
或终端提示，要么标了 `# noqa: T201`，要么位于被静音的命令行路径。Server 自己的
runtime 日志函数（`interfaces/server/runtime_management.py`、
`server_runtime/broadcasts.py`）里的 `print` 同时写 `runtime.log`，原样保留并加了标注。

## 相关文件

- [统一运行控制](runtime/execution/control.zh.html) — 暂停、继续、单步、调整、取消，以及 `CancelledError` 继承 `BaseException` 的原因
- [`runtime/dag/overview.zh.md`](runtime/dag/overview.zh.md) — error 作为节点终态
