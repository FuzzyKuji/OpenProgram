# 用户输入请求

运行中的 Python Workflow 可以调用 `ask_user(question)` 或 `runtime.ask(...)` 显示问题，并在原进程中等待回答。这不保存或恢复 Workflow 调用栈。重启 worker 会中断此次执行，不会重放前面的操作；只刷新浏览器时，只要执行进程仍然有效，待答问题就会重新显示。

## API 与结果

```python
from openprogram.programs.tools.interaction.ask_user import ask_user
answer = ask_user("这份材料的作者是谁？")
```

`runtime.ask(prompt, options=None, multi=False, allow_custom=True, timeout=300.0, default=None)` 返回回答；拒绝抛出 `UserDeclined`；没有默认值时，超时抛出 `AskTimeout`。`runtime.confirm` 和 `runtime.form` 使用相同的提问通道。取消执行会抛出执行取消异常。

`ask_user` 保留 CLI handler 和终端输入兼容行为。有提问通道的 runtime 使用 `runtime.ask`。用户拒绝或超时仍映射为 `None`；其他 runtime、存储或传输异常正常传播，不能伪装成用户未回答。没有 handler 或可交互 runtime 的无界面调用仍返回 `None`。

## 运行中 Workflow 的归属

子进程执行器在调用期间绑定 execution ID、attempt ID、generation 和进程实例身份。没有该绑定的 runtime 不能创建运行中问题。创建与回答事务检查 execution 为运行状态、attempt 仍是当前有效执行者，并且租约尚未过期。此类问题不能用于批准工具权限。

问题存储仅记录问题、处理策略和回答，不保存 Workflow 检查点。回答命令不会创建新 attempt；原函数在原调用位置收到回答，不会重新调用模型或已完成的工具。

子进程通过 `QueueTransport` 发布问题。父进程从已保存的问题记录生成前端事件，并转发正式回答通知。registry 只负责唤醒本地等待，SQLite 记录是回答状态的唯一依据。重复回答与其他 execution 的回答由命令协议拒绝。

## 界面与进程生命周期

现有问题卡片显示提问。刷新后加载会话会重新显示未解决的问题。问题接口和 execution 回答命令使用同一记录和鉴权。

停止任务会取消该执行的待答问题。子进程退出时只取消该进程的运行中问题；执行者失效时清理遗留问题，迟到回答不能继续已结束的函数。重启 worker 不恢复 Python Workflow 调用栈。Agent 的持久化问题仍按独立检查点契约处理。

## Agent 预声明问题

预声明的 Agent 工具问题继续使用原检查点事务：暂停执行、结束旧 attempt，回答后从检查点继续。preapproved wait 优先于运行中绑定，必须与提问内容完全一致。此次修复不放宽这项校验，也不改变权限批准机制。

## 验证与范围

自动测试使用真实 Runtime 和公开 `ask_user`、正式回答命令，检查原调用继续、取消、归属与会话校验、传输失败和进程清理。本机验收要求安装版 App 中看到问题、刷新后仍存在、回答后 Workflow 完成。单纯返回 `WAITING_USER` 不算交互验收通过。

Workflow 重启恢复不在此次范围内。运行中问题只记录问题和回答，不保存 Workflow 执行状态。
