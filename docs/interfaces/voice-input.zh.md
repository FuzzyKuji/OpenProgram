# 语音输入

聊天输入框左下角的圆形麦克风按钮把说话转成文字。点一下开始说，再点一下停止。打字时也可以按住 ⌥空格（Alt+空格）说话，松开即停止。

录音时，发送按钮前面有一条指示：安静时显示一个点，说话时显示随音量变化的竖条。每说完一句停顿一下，这一句就会被转写并插入到光标处，所以文字是一句一句出现，而不是一个词一个词出现。不会自动发送：文字留在输入框里，改完再发。按 Esc 放弃这段录音，并删除它插入的文字。停止后，最后一句转写完成，按钮才恢复可用。

浏览器或桌面 App 第一次使用时会请求麦克风权限。

## 选择语音识别服务

打开 **设置 → 语音**。麦克风本身没有选项，都在这里设置。

| 设置 | 取值 | 含义 |
|---|---|---|
| 识别服务（`voice.engine`） | `auto`、`openai`、`groq`、`local` | 用哪个服务转写音频。 |
| 说话语言（`voice.language`） | `auto`、`zh`、`en`、`ja`、`ko`、`fr`、`de`、`es` | 提示你说的语言；`auto` 自动识别。选 `zh` 时输出简体中文。 |
| 模型（`voice.model`） | 文本 | 所选服务的模型名；留空用该服务的默认模型。识别服务为 `auto` 时不生效。 |

各识别服务：

- **openai**：把每句话发给 OpenAI 转写 API，默认模型 `gpt-4o-mini-transcribe`，使用 设置 → 模型服务 里的 OpenAI API key。
- **groq**：把每句话发给 Groq，默认模型 `whisper-large-v3-turbo`，使用 设置 → 模型服务 里的 Groq API key。
- **local**：在本机运行 [whisper.cpp](https://github.com/ggml-org/whisper.cpp)，音频不离开这台电脑。用 `brew install whisper-cpp` 安装。第一次使用时把 `large-v3-turbo-q5_0` 模型（约 570 MB）下载到状态目录；在 Apple 芯片上每句话需要一到两秒。

选 `auto` 时，OpenProgram 依次选择：已安装且模型已下载的本机 whisper.cpp、OpenAI、Groq、本机 whisper.cpp（第一次使用时下载模型）。设置页会显示当前使用的服务，以及这台电脑上哪些服务可用。

这些设置也可以在命令行修改，例如：

```bash
openprogram config set voice.engine local
```

[`computer_use_agent`](../capabilities/computer-use.zh.md#录音) 从应用录下的声音也由同一个引擎转写。

## 限制

- 音频按 16 kHz 单声道录制，一句一句上传；超过 25 秒没有停顿的一句会在那里切开。
- 单次上传最多 20 MB。
- 没有可用的识别服务时，点麦克风不会录音，而是提示去 设置 → 语音。
