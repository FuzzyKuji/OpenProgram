# Use locally deployed models

OpenProgram connects to an inference server you operate. Start the server and load a model using that server's own tools before configuring OpenProgram. Model downloads, GPU allocation and server lifecycle are managed by the inference server.

In **Settings → Providers**, choose a preset:

| Provider | Default API Base URL |
| --- | --- |
| Ollama | `http://localhost:11434/v1` |
| LM Studio | `http://localhost:1234/v1` |
| vLLM | `http://localhost:8000/v1` |
| llama.cpp | `http://localhost:8080/v1` |
| Local OpenAI-compatible server | `http://localhost:8000/v1` |

Enable the provider, save its API Base URL, click **Fetch models**, and enable the desired model. Select that model in the chat composer. `localhost` means the machine running the OpenProgram worker; for a remote worker, enter the address reachable from that worker. A URL containing only a host and port gets `/v1` appended. An explicit path is preserved.

API keys are optional for local providers. If your server requires a key, add it through the provider account panel. Without a local key, discovery, connectivity checks and streaming inference omit the Authorization header. OpenProgram does not send a cloud OpenAI key to a local provider. For several servers, use **Add custom provider**, enter a name and URL, and select **Local server (API key optional)**. Ordinary custom cloud providers retain their credential requirements.

Use **Connectivity** to check the server. A successful model listing confirms that the API endpoint responds; testing a named model additionally checks inference. An unavailable server, rejected key or invalid response is reported as a failure.

If discovery is unavailable, use **Add model by id** with the exact identifier accepted by the server. This also updates an existing model's limits. Enter context and output token limits that match your deployment, including the configured server context size. Unknown local limits use conservative defaults of 4,096 context tokens and 1,024 output tokens. An upstream model's advertised training context does not establish the context configured on your server.

Local models use OpenAI Chat Completions. Streaming, cancellation and tool-call processing use the same transport as other compatible providers. Tool use, images, reasoning and strict JSON output depend on the model and server. OpenProgram cannot add a capability absent from the deployment. Enablement and token limits persist in the standard configuration. Saving a new server URL changes subsequent discovery and inference for existing enabled models.

See the official [Ollama compatibility documentation](https://docs.ollama.com/api/openai-compatibility), [LM Studio server documentation](https://lmstudio.ai/docs/developer/core/server) and [vLLM serving documentation](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/) for server configuration.
