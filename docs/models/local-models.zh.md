# 使用本地部署的模型

OpenProgram 连接你管理的推理服务。配置前，使用服务自身的工具启动服务并加载模型。模型下载、GPU 分配和服务启动停止由推理服务管理。

在 **设置 → Providers** 中选择预设：

| Provider | 默认 API Base URL |
| --- | --- |
| Ollama | `http://localhost:11434/v1` |
| LM Studio | `http://localhost:1234/v1` |
| vLLM | `http://localhost:8000/v1` |
| llama.cpp | `http://localhost:8080/v1` |
| Local OpenAI-compatible server | `http://localhost:8000/v1` |

启用 Provider，保存 API Base URL，点击**获取模型**，启用所需模型，然后在聊天输入区域选择模型。`localhost` 指运行 OpenProgram worker 的机器；远程 worker 应使用该机器能够访问的地址。只包含主机和端口的 URL 自动补充 `/v1`，显式路径保持不变。

本地 Provider 的 API key 可选。服务要求鉴权时，在账户面板中添加 key。未配置本地 key 时，模型发现、连接检查和流式推理均省略 Authorization header。OpenProgram 不会把云端 OpenAI key 发送给本地 Provider。需要连接多个服务时，点击**添加自定义 Provider**，填写名称和 URL，勾选**本地服务（API key 可选）**。普通自定义云端 Provider 保留鉴权要求。

使用**连接检查**验证服务。成功获取模型列表说明 API 可以响应；指定模型的检查还会验证推理。服务不可用、key 被拒绝或响应无效时会显示失败。

发现模型不可用时，使用**手动添加模型**，填写服务接受的精确模型 ID。此功能也可以更新已有模型的限制。上下文和输出 token 限制应与实际部署配置一致，包括服务配置的上下文大小。未知限制采用保守默认值：上下文 4,096 token、最大输出 1,024 token。模型宣称的训练上下文不代表服务器实际配置的上下文。

本地模型使用 OpenAI Chat Completions。流式输出、取消和工具调用处理复用兼容 Provider 的传输实现。工具、图像、推理和严格 JSON 输出取决于模型与服务，OpenProgram 无法补充部署本身不支持的能力。启用状态和 token 限制保存在标准配置中。修改服务地址后，已有启用模型的后续发现和推理使用新地址。

服务配置请参阅官方 [Ollama 兼容接口文档](https://docs.ollama.com/api/openai-compatibility)、[LM Studio 服务文档](https://lmstudio.ai/docs/developer/core/server) 和 [vLLM 部署文档](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/)。
