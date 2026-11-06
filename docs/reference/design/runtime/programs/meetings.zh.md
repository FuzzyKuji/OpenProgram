# 会议

用户在这台电脑上开会时把通话录下来；OpenProgram 转写它，并在一个新对话里写出摘要。设计只复用已有部件：语音输入的识别引擎、录制 Workflow 的长时会话形态、提醒和常驻 Agent 用来发起的 owner turn、浏览器的麦克风 API，以及电脑操作录制应用声音时已经在用的 ScreenCaptureKit 音频流。不新增基础设施。

## 结构

| 部分 | 位置 | 作用 |
|---|---|---|
| 麦克风 | 页面（`apps/web/lib/meetings/meeting-recorder.ts`） | `getUserMedia`，一个 `MediaRecorder`，30 秒一段按顺序上传 |
| 电脑声音 | 服务器（`meeting/system_audio.py`，基于 `openprogram/host/_platform/screen_capture_audio.py`） | 随会议开始的整屏、只录音频的 ScreenCaptureKit 流，切成 30 秒一段的 WAV |
| 路由 | `openprogram/interfaces/server/routes/execution/meetings.py` | `/api/meetings`：列表、开始、上传音频、停止、状态、转写稿、摘要、重新总结、删除 |
| 应用 | `openprogram/programs/applications/meeting/` | `meeting` 服务：存储、转换、转写队列、合并、摘要 |
| 语音 | `openprogram/runtime/speech_link.py` → `openprogram/interfaces/speech/stt.py` | `transcribe_segments`：用“设置 → 语音”里的引擎、按会议的语言（默认自动识别）得到带时间的片段 |
| 说话人 | `meeting/diarize.py`（可选的 `sherpa-onnx`） | 停止时对 system 轨做一次说话人分离，给它的片段标上 `others:<n>` |
| 摘要 | `openprogram/runtime/conversation/owner_turn.py` | 在新对话里发起一轮不带工具的 owner turn |
| 窗口 | `apps/web/components/applications/windows/meeting-window.tsx` | 开始/停止、实时进度、过往会议的摘要与转写稿 |

核心从不导入这个应用。路由按名字查找服务，应用关闭期间一律返回 404（`meeting_not_enabled`）；销毁它的 context 会停止正在进行的录制。

## 采集：两路声音，再对其中一路做说话人分离

“我”和其他人的区分来自声音从哪里录到，而不是模型；区分其他人是停止时对 system 轨做的说话人分离（见下文）：

- **mic**：页面的 `getUserMedia({audio})`，开启回声消除、降噪和自动增益：用户本人，“我”。
- **system**：服务器的 ScreenCaptureKit 流：电脑的声音输出，也就是通话里的其他人，“对方”。

### 电脑声音，在服务器上录

`POST /api/meetings` 开始会议，并在 `Meeting.begin` 里开始它的系统声音采集。来源（`ScreenCaptureSource`）读取可共享内容，为第一块显示器构造 `SCContentFilter.initWithDisplay_excludingWindows_(display, [])`（它播放的一切，不排除任何窗口），再通过 `screen_capture_audio.open_audio` 打开只录音频的流：`capturesAudio`、16 kHz、单声道、`excludesCurrentProcessAudio`、每秒一帧 2×2 的画面且不挂画面输出。电脑操作按应用录音（`desktop/audio.py`）也用同一个模块，只是过滤器不同。macOS 第一次会询问“录屏与系统录音”；worker 运行在 App 的运行时 bundle 里（`openprogram/host/system_access` 的 `screen_recording` 能力），所以弹窗和系统设置里的条目都是这个 App。不需要别的声明：ScreenCaptureKit 的音频包含在这项授权里。

`SystemAudio` 与 ScreenCaptureKit 无关。来源从流的队列把 float32 缓冲推给它；它按采样数切成 30 秒一段，每段的 `t_ms` 是它第一个采样被录下时的会议时钟（开启这一段的缓冲到达的时间，减去该缓冲剩余部分的时长）。它自己的线程把每段转成 16 位 WAV，交给 `Meeting.append("system", seq, t_ms, wav, "wav")`，也就是音频路由所用的入口。`Meeting.finish` 先停流，并在会议仍处于 `recording` 时交出最后不满 30 秒的一段，然后照常停止；删除会议则取消采集，不交出剩余部分。

来源无法开始时，这场会议只录麦克风，状态（以及 `meta.json`）写明 `system_audio: "unavailable"` 和 `system_audio_reason`：`unsupported`（不是 macOS，或 PyObjC 的 ScreenCaptureKit 无法导入）、`permission`（ScreenCaptureKit 拒绝，错误 -3801 “declined TCCs”，或 `CGPreflightScreenCaptureAccess` 报告没有授权）或 `error`，文字放在 `system_audio_message`。正常采集时为 `recording`。更早的会议没有这个字段。

### 麦克风，在页面上录

页面只申请麦克风，然后开始会议。它从开始请求的响应里取服务器的 `elapsed_ms`，从服务器的会议开始时刻计算分段偏移，两路因此共用一个时钟。它的 `MediaRecorder` 每 30 秒停止并重新开始。用 timeslice 时第一段之后的块没有 WebM 头；重新开始让每一段都是服务器能单独转换的完整文件，代价是每段之间几毫秒的间隙。每段带着它的轨道、序号和偏移（`t_ms`），上传乱序完成也能放回原位。开始后不到 100 毫秒就停止的分段（刚轮换完就按了停止）只是一个没有声音的 WebM 文件头，不上传。上传按顺序进行，网络错误或 5xx 时重试三次。录制器放在模块级 store 里，离开窗口不会停止录制，只有停止按钮会。

被拒绝的麦克风在页面上表现为 `NotAllowedError`，窗口会说明去系统设置的哪一页。录制卡片根据开始请求的响应说明是否也在录电脑声音；没有时说明这场会议只录麦克风，原因是 `permission` 时指明“隐私与安全性 → 录屏与系统录音”，并提示重新打开 App。

## 服务器：存储、转换、转写、合并

```
<state>/meetings/<id>/
  meta.json                   名称、语言、时间、状态、分段计数、错误、引擎、session_id、
                              system_audio、diarization、speakers
  tracks/<track>/<seq>.webm   收到的分段（system 分段是 .wav）
  tracks/<track>/<seq>.json   它带时间的片段（或静音 / 错误）；system 片段会加上 `speaker`
  transcript.json             合并后的转写稿
  summary.md                  摘要，转写稿放在 <details> 块里
```

同一时间只录一场会议，最长 4 小时。每个分段先写盘，再排进这场会议唯一的工作线程，所以无论会议多长，内存里只有一个分段：

1. **转换**：用 `ffmpeg`（先找 `PATH`，再找 `/opt/homebrew/bin`、`/usr/local/bin`、`/usr/bin`）转成 16 kHz 单声道 16 位 WAV；ffmpeg 从数据本身识别格式。已经是这种格式的 WAV 分段（所有 system 分段）直接使用。没有 ffmpeg 时拒绝开始会议，返回 `ffmpeg_missing` 和安装提示。
2. **跳过静音**：峰值低于 300/32767 的分段不转写；Whisper 会给静音编出文字。
3. **转写**：通过 `speech_link.transcribe_segments(wav, duration_ms, language)`。语言是会议自己的，绝不取“设置 → 语音”：`POST /api/meetings` 接受可选的 ISO `language`（存进 `meta.json`；会议窗口传会议名称旁选定的语言，选“自动识别”时不传），为空就是自动识别（whisper.cpp 用 `-l auto`，OpenAI 和 Groq 不带 `language` 字段）。把语音输入的语言强加到另一种语言的通话上，会让 Whisper 用那种语言编造文字。语音接口保留每句的时间：whisper.cpp 输出 `[from --> to]` 行（不加 `-nt`）；Groq 和 OpenAI 的 Whisper 模型用 `verbose_json` 返回分段；`gpt-4o-*-transcribe` 只返回文字，作为覆盖整段的一个片段。没有这个方法的 link 也按同样方式退回 `transcribe`。
4. **合并**（`transcript.py`）：片段按分段偏移放到会议时间轴上，按开始时间排序。与 4 秒内开始的某个 system 片段文字相似度达到 75% 的麦克风片段视为回声（没戴耳机），丢弃。同一说话人间隔小于 1.5 秒的连续片段合成一段发言。每行带 `speaker`（`me`、`others`、`others:<n>`）和英文的 `label`（“Me”“Others”“Speaker n”）；窗口按 `speaker` 本地化显示。每个分段处理完都会重写 `transcript.json`，所以窗口里转写稿是逐渐增长的。

无法转换或转写的分段会连同错误记录并计数；会议继续进行。重复的 `(track, seq)` 会被忽略，所以客户端重试是安全的。

## 摘要

停止后状态依次是 `recording` → `transcribing`（队列处理完，再对 system 轨做说话人分离）→ `summarizing` → `done`。转写稿为空时不开新对话，`summary.md` 写明没有转写出内容。

否则应用新建一个对话（`meeting_<hex>`，来源 `web`，以会议名为标题，用默认 Agent 和新对话的模型），把它的 id 记进 `meta.json`，再用 `start_owner_turn(..., tools=[], untrusted=True)` 发起一轮。消息是固定提示词，后接放在 `<meeting-transcript>` 里的转写稿；提示词要求用会议的语言写出 `## Summary`、`## Decisions`、`## Action items`（负责人、截止时间）和 `## Open questions`，并说明转写稿是数据，绝不是指令。没有工具加上 untrusted 标记，意味着会上任何人说的话都无法让 agent 执行操作。这一轮结束后，它的回答、带日期和时长的标题，以及折叠起来的完整转写稿合成 `summary.md`。对话保留，可以继续追问。

进程结束时仍处于进行状态的会议列为 `interrupted`；**重新总结** 从各分段的 JSON 文件重建它，再跑一次摘要步骤。

## 访问

每个路由都要求 owner 登录（`require_owner`）。麦克风在页面所在的电脑上录；电脑声音始终是运行服务器的那台电脑的声音，所以在另一台电脑上登录的 owner 录到的是自己的麦克风和服务器那台电脑的声音。会议留在状态目录里；使用云端语音引擎时，每个分段会发给该服务商。

## 说话人分离

每场会议只做一次，在会议的工作线程里、转写队列处理完之后、写摘要之前，对整条 system 轨进行。逐段做需要跨分段保存并匹配声纹；对整条轨做一次，聚类能同时看到所有声音，而且很快（四线程下每分钟音频约 4 秒）。

1. **音频**：system 分段按序号依次转换（它们本来就是 16 kHz 单声道 WAV）并拼接。`concatenate` 记下每个分段的位置 `(concat_ms, t_ms, duration_ms)`，拼接音频里找到的发言段就能映射回会议时间轴；跨分段边界的发言段在边界处切开（`to_meeting_clock`）。
2. **分离**（`run`）：sherpa-onnx 的 `OfflineSpeakerDiarization`，用 pyannote segmentation-3.0 分割模型和 3D-Speaker 的中英双语 CAM++ 声纹模型（`3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx`），最多四个 ONNX 线程，`min_duration_on` 0.3 秒、`min_duration_off` 0.5 秒，与 sherpa-onnx 的示例一致。人数未知，所以 `FastClusteringConfig(num_clusters=-1, threshold=0.75)` 按距离聚类。模型和阈值用四段已知人数的录音定下：pyannote 的 AMI 会议片段（两人互相插话，按参考标注打分）、sherpa-onnx 的四人测试录音、一段两人录音和四个合成人声。CAM++ 在 0.6 到 0.75 之间对四段都分出正确人数，AMI 片段 91% 的语音标对，0.8 会把中文四人里的两人并成一人；取这个区间的上端，是因为在经会议软件通话和直接播放两种方式听到的 AMI 四人会议上，它最少把一个人拆成两个编号（0.65 时七个编号，0.75 时五个）；sherpa-onnx 示例用的 ERes2Net 中文模型在每段录音上需要不同的阈值，凡是让四人录音保持四人的值都会把 AMI 的两个人并成一个。
3. **标注**（`assign`）：每个 system 片段放到会议时间轴上，取与它重叠最长的发言人（相同时取 sherpa 编号较小的）；按在转写稿里首次出现的顺序重新编号为 `others:1`、`others:2`……。没有任何发言段与之重叠的片段不带说话人，显示为“对方”；整场会议里只被听到不足 `MIN_SPEAKER_MS`（3 秒）的声音也一样：在真实的四人会议上，聚类会在四个真实发言人之外留下几个一两秒的零碎簇，不这样处理它们就会变成“发言人 5”到“发言人 7”。标注后的记录写回各分段的 JSON 文件并重新合并，所以 `transcript.json`、`summary.md` 和摘要提示词里都是“Speaker n”。提示词说明编号代表声音，不是名字。

`sherpa-onnx` 是可选的 `meetings` 扩展（连同 `numpy`），只在 `run` 里导入。模型在第一次使用时从 sherpa-onnx 的 GitHub release 下载到 `<state>/models/diarization/`：分割模型压缩包（`speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2`，只解出其中的 `model.onnx`）和声纹模型（`speaker-recongition-models/…_16k.onnx`），都经临时文件再原子改名、在同一把锁下进行，和语音输入下载 Whisper 模型的方式一样。会议状态用 `diarization` 报告：`running`，之后是 `done`（带 `speakers`，编了号的人数）、`unavailable` 加 `diarization_reason` 为 `not_installed`（没有 `sherpa_onnx`）或 `no_model`（下载或模型文件出错），或 `failed`（`error`，详情在 `diarization_message`）。除 `done` 外转写稿都不变。没录到电脑声音、或电脑声音什么也没转写出来的会议跳过这一步，`diarization` 留空。

## 替代方案

与本设计比较过的开源会议记录工具有 meetscribe-offline（Python，pyannote 说话人分离，Ollama 或云端总结，需要 HuggingFace token，偏好 NVIDIA GPU）、HushScribe（macOS 26、Apple Silicon，WhisperKit 和 Parakeet 本地运行，说话人标签在结束后才有）和 AI-Meeting-Bot（围绕本地 Whisper 的开发者流水线）。ChatGPT 桌面端通过连接会议软件的伴侣程序记录会议并列出即将开始的会议；Claude 桌面端没有会议功能。它们都没有被整个复用：每个都是独立应用，有自己的采集、模型和存储，而本设计只是建立在 OpenProgram 已有能力（语音输入的语音引擎、computer use 的 ScreenCaptureKit 音频流、写总结的对话）之上的三个模块。从它们复用的是组件选择：Whisper 做语音识别，pyannote 分割加声纹模型判断谁在说，经 sherpa-onnx 运行，不需要 PyTorch 和 token。

对照的桌面 agent 产品，在这里要回答的问题（通话里谁说了什么，加一份总结）上：

| | Claude（桌面端） | Codex / ChatGPT（桌面端） | DeepSeek Harness | OpenProgram |
| --- | --- | --- | --- | --- |
| 会议 | 没有会议功能 | ChatGPT 的录制模式：伴侣程序接入会议软件，列出即将开始的会议，转写并总结；Codex 没有 | 只有一个语音输入插件（实验性）；没有录制或会议功能 | 录下麦克风和电脑任何应用的声音输出，两路都转写，在本机区分其他人的声音，在对话里写总结 |

三者在这个问题上都没有本设计缺少的东西，所以采集、说话人分离和总结保持原设计。ChatGPT 从日历列出即将开始的会议，是 OpenProgram 没有的那一项相邻功能。

## 实现状态

- 已实现：页面的麦克风采集与分段上传、服务器的 ScreenCaptureKit 采集与切段及 `system_audio` 状态、`meeting` 应用与路由、三种引擎的带时间转写、合并与去回声、摘要轮和 `summary.md`、会议窗口、重新总结和删除。
- 已实现：停止时用 sherpa-onnx 对 system 轨做说话人分离（`meetings` 扩展，同时也在 `all` 里，所以打包 App 的运行时自带；模型首次使用时下载）、`diarization` 状态，以及转写稿、窗口和摘要提示词里的“Speaker n”标签；会议转写按自动识别或单场会议指定的语言，不再沿用语音输入的语言；会议窗口里的语言选择（按查看者记住，显示在录制卡片和过往会议上）。
- 由测试验证（采样来源、ffmpeg、语音、说话人分离和摘要轮都是假的）；真实流程（稳定版 App 里的 ScreenCaptureKit 采集、分段、转写、说话人分离）用经电脑声音输出播放的录音核对过：sherpa-onnx 的四人测试录音、AMI 两人片段（两人都找到）和 AMI 四人片段（四人全找到，每一行的编号都与参考一致）；也在一场真实的会议通话上核对过：两个参会者进入同一个 Jitsi Meet 会议室，第二个以 AMI 四人片段作为自己的音轨发言，第一个在这台电脑上播放，稳定版 App 录下并总结了这场通话，编号恰好四个，每一行的编号都与参考一致。通话声音到达录制器走的是与 Zoom 或任何其他应用相同的系统声音路径。麦克风轨在会议窗口里核对过，浏览器的麦克风就是 AMI 片段：上传七段，六行标为“Me”，摘要已写出；唯一的失败是末尾那个只有文件头的分段，页面现在会跳过它。新安装 App 里的“录屏与系统录音”弹窗和权限分类仍需核对。
