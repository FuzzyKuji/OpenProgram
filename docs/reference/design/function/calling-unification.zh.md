# 函数调用

Agent 方法通过 `method_options["method"]["tool"] = True` 显式登记工具。受管 Program 包通过 `PROGRAM_ENTRIES` 明确公开入口。确定性 `function()` 工具与旧 `Agent` 适配器继续可用。

所有形式复用现有 AgentTool registry 与授权规则。自动作用域采集不自行暴露工具。[统一 Agent 与 Context 契约](../integrations/nooa.zh.html#contract) 定义类式编写与执行生命周期。

Provider 将已授权工具转换为 Tool schema。模型返回 ToolCall 后，dispatcher 按注册身份调用工具，并将结果返回当前模型循环。工具可见性与 DAG 历史可见性分别处理。
