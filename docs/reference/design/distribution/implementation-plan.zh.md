<div id="installation-and-distribution-implementation-plan"></div>

# 安装与分发实施计划

本工程记录与权威 HTML 设计刻意分开，记录当前分发工作的限定实施范围、验证和审查证据。

正式发布的更新架构、实现状态、验证证据和发布可见验收统一维护在 `docs/reference/design/distribution/automatic-updates.html`，不在这份历史分发台账中重复。

<div id="remove-python-package-product-installation"></div>

## 移除通过 Python 包安装产品的入口

- 产品合同：普通用户安装完整的 GitHub Release 产物；`pip install openprogram`、`pipx install openprogram`、`uv tool install openprogram` 和 PyPI 项目页都不是受支持的产品入口。
- 公开界面：站点首页、引导与故障排查页、示例和运行时依赖错误均指向正式安装器或完整重装，不要求用户修改 Python 包。
- 保留开发边界：发布运行时组装、源码开发、测试，以及明确由开发者管理的第三方扩展环境，仍可在内部构建或安装 wheel。
- 公开入口 RED：分发合同扫描公开文档和产品修复提示中的 Python 包安装说明，同时保留运行时构建器仍使用已验证 wheel 的断言。
- RED 证据：两个针对性用例均失败：公开界面仍宣传 Python 包安装，打包后的 `openprogram browser install` 仍调用 Python 安装器。
- GREEN 证据：两个针对性用例均通过。受影响的分发、Browser、Channels、Providers、OAuth、配置、PDF 和 embedding 测试共 1,330 项通过、5 项跳过、1 项预期失败；正式发布测试 21 项通过。文档构建 529 页，落地页检查通过，链接验证为零死链。
- 排除项：不重写为无 Python 产品，不删除 `pyproject.toml`，不改变插件或第三方 Program 格式，不修改远端 PyPI。
- `9e50cebc` 的规格审查要求修改：六处第一方 PDF Agentic Function 错误仍建议 `pip install pymupdf`，而公开界面回归排除了整个 Agentic Functions 目录树。
- 修复：这些内建错误改为指引用户完整重装；回归扫描将第一方 Agentic Functions 与其他产品运行时代码一并纳入。明确由开发者管理的扩展安装器仍排除。
- `d9047511` 的规格复审通过。剩余 Python 包操作限于发布组装、源码开发、测试和开发者管理的扩展环境。
- `d9047511` 的质量审查要求修改：OpenClaw 源码集成准备了锁定的 uv 环境，但示例 skill 仍用无关的系统 Python；公开内建 PDF 能力依赖 `pypdf`，完整运行时却既未安装也未验证它。PDF 失败提示缺少必要修复操作，源码故障排查错误暗示 checkout 安装器会改变 shell 的活动 Python。此外，缺少 Node 或 `apps/cli/dist` 的受管运行时会在现有 Rich 终端回退之前退出，违反发布合同的终端 UI 要求。
- 修复：OpenClaw skill 改用克隆 checkout 的 `uv run --project`，回归覆盖中英文说明。`pypdf` 成为锁定的基础依赖；运行时验证器导入它，并用生成的 PDF 执行两条内建提取路径。缺少 PDF 依赖时提示完整重装；故障排查区分受管私有运行时与 `uv run` 或 `.venv` 源码开发。Ink 启动失败进入内置 Rich REPL；`rich` 成为直接锁定依赖，并增加运行时渲染探测和回退回归。
- `8c6b2f0c` 的最终限定审查：规格和质量均通过。分发、正式发布、Browser 和结构化输出覆盖共 123 项通过；包含独立运行覆盖的发布审查 120 项通过；真实 PDF 样例 6 项通过。文档构建 529 页、落地页验证通过、零死链。更广泛的不带额外依赖测试在 793 项通过后因开发环境缺少 Playwright 停止；该失败用例在发布运行时的 `--extra all --extra search` 配置下通过。
- 状态：完成。

<div id="local-app-version-coherence"></div>

## 本地 App 版本一致性

- 公开边界：`scripts/refresh-local-app.sh` 仅刷新 bundle、运行时 manifest、Python 分发元数据、Python 源码版本和 Desktop 源码版本全部一致的已安装 App。`apps/desktop/scripts/install-app.sh` 在获取锁前拒绝低于当前规范 App 的候选版本；在锁内复制并验证候选，再于停止 worker 或修改文件系统前比较不可变暂存版本与已安装 App。数字版本段使用十进制任意精度比较。现有规范路径若未通过 bundle、manifest 或嵌入元数据验证，必须保留并拒绝操作，不能当作不存在。同版本刷新将 Desktop updater 实现复制到重建的 App archive，核对 wheel 元数据，然后重新获取安装目标锁，在修改 worker 或 App 前再次核对源码、wheel 和已安装 App。
- RED：公开安装器接受用 0.6.1 候选覆盖已安装 0.6.2 App；发布版本入口不识别已安装 App 与源码匹配请求。
- GREEN：两个公开入口用例均通过。真实刷新命令在创建构建产物前拒绝用 0.6.6 checkout 刷新当时的 0.6.1 App；App 文件和健康 worker 保持不变。
- 受影响检查：正式发布与分发测试 74 项通过；发布版本、Ruff、shell 语法和 diff 检查通过。
- 排除项：无降级覆盖选项、预发布排序、新版本来源、用户状态迁移、Windows 包或远端发布修改。
- 状态：实现已提交；独立规格审查待完成。

<div id="local-canonical-app-and-apple-icon-batch"></div>

## 本地规范 App 与 Apple 图标批次

- 基线提交：`9477273e`。
- 公开入口：`npm --prefix apps/desktop run dist` 构建并验证一个完整的临时 `OpenProgram.app`，只替换 `/Applications/OpenProgram.app`。
- 图标合同：`apps/desktop/build/AppIcon.icon` 是 Apple 分层设计源，其四个 1024 x 1024 SVG 图层不预先裁剪系统轮廓，并保留已批准的细胞与三个扁平圆片。受支持的 macOS 15 构建机缺少完整 Xcode `actool` 流程，因此已审查的 `apps/desktop/build/icon.icns` 提交为 Electron 打包输入。检查同时验证两个资产、全部旧格式表示及安装后的系统轮廓；已删除的手绘外形 SVG 不得恢复。
- 事务合同：激活失败不得删除旧 App 唯一可恢复副本。真实 launchd 卸载失败在修改 App 前停止；已经卸载的过期 plist 可替换。Launch Services 注册后的失败恢复并重新注册旧规范 App，且不覆盖最初安装错误。组装后的 App 在安装前通过现有完整打包运行时冒烟检查。
- 并发合同：跨 worktree 打包共用一个稳定的用户级锁；安装在目标 Applications 目录使用覆盖完整事务的原子锁。竞争安装器在 App 或服务修改前失败，不能创建嵌套 bundle。
- 清理边界：打包清理随机 App 目录、暂存运行时、Python wheel 构建、生成的 Web 构建/输出、复制的 Web 前端和锁。不删除已安装 App 数据、源码、包依赖或用户状态。
- 生产文件：`apps/desktop/build/AppIcon.icon`、`apps/desktop/build/icon.icns`、`apps/desktop/scripts/check-icon.sh`、`apps/desktop/scripts/package-and-install-app.sh`、`apps/desktop/scripts/install-app.sh` 和 `openprogram/operations/worker/services/launchd.py`。
- 验收：图标检查要求 1024 x 1024 源、透明角、824 x 824 不透明主体边界、与 macOS 内建 App 对齐的 256 px 栅格轮廓和实心区域、十种旧格式表示，以及 ICNS 往返验证。事务故障注入保留 `previous.app`；launchd 测试覆盖已加载、过期和卸载失败状态；损坏的组装运行时在安装前拒绝。运行时验证器还要求已安装 OpenProgram 包元数据等于 manifest 版本。审查后用一次真实 `npm run dist` 替换已安装 App，刷新 Launch Services，并检查 Finder/Launchpad 显示。
- 排除项：无 Developer ID 签名、公证、Windows 包、新图标依赖、第二份安装 App 或图像生成模型。
- 检查清单：针对性分发测试、Desktop 检查、图标生成与往返、打包运行时冒烟、文档构建/链接、Ruff、shell 语法、diff、独立规格审查及新的独立质量审查。
- 安装验收（2026-08-16）：一次完整 `npm run dist` 通过运行时和打包 App 冒烟后，原子替换 `/Applications/OpenProgram.app`。已安装 bundle 版本为 0.6.6、标识为 `ai.openprogram.desktop`；运行时 manifest、CLI 和 Python 分发元数据均为 0.6.6，ICNS SHA-256 与生成的源资产一致。默认 worker 使用 bundle 的 CPython 3.12.10，`/healthz` 为 `ok`。Launch Services 返回规范 0.6.6 App，Launchpad 数据库包含其应用项，Dock 可见图标大小和圆角轮廓与相邻 macOS App 一致。
- 清理验收：仅保留 `/Applications/OpenProgram.app`；安装后随机打包目录、暂存运行时、Python wheel 构建、Web `.next`/`out` 和复制的前端均不存在。
- 状态：已实现、独立审查、安装并通过可视验收。

<div id="release-gate-repair-for-v061"></div>

## v0.6.1 发布检查修复

- 实现移至 `openprogram/interfaces/channels/implementations/` 后，删除四个无引用旧 Channel 模块；运行时 HTTP 清单仅扫描活动 Channel 代码。
- 将 Research writer 被丢弃的 `context` 参数改名为运行时支持的 `project_context`。
- 将 Browser Agent 明确记录为延后的内部工具循环，不改变其行为。
- 本地验收：原四个失败测试通过；受影响测试 461 项通过；完整非集成测试 5274 项通过、11 项跳过、1 项预期失败。Desktop、Web、发布脚本、运行时 HTTP、Ruff 和文档检查通过。
- 此修复早于原生 Windows 产物。当前 Windows 发布路径见 [Windows 支持](windows-support.zh.md)。

<div id="native-release-result-and-v062-correction"></div>

### 原生发布结果与 v0.6.2 修正

- `v0.6.1` 在发布运行 `31820999574` 解析完整 macOS x86_64 运行时失败后保持不可变；该标签未发布 GitHub Release。
- 根因：`semble 0.2.0` 将 `tree-sitter-language-pack` 约束为低于 1.8，锁定的 1.6.2 没有 macOS x86_64 wheel。
- 修正：要求 `semble>=0.5.3`，其语法依赖改为 `semble-grammars`；锁定语法包提供 macOS x86_64/arm64 与 Linux x86_64/arm64 原生 wheel，并保留搜索能力。
- 回归检查：为 macOS x86_64 上 CPython 3.12 解析完整锁定产品依赖，并断言锁定语法产物覆盖该平台。发布重试使用更高补丁版本 `v0.6.2`。
- `v0.6.2` 在运行 `31822787529` 通过搜索依赖步骤、但发现 `torch 2.13.0` 不再提供 macOS x86_64 wheel 后保持不可变；该标签未发布 GitHub Release。
- `v0.6.3` 重试使用上游最后兼容 macOS x86_64 的 `torch 2.2.2` 和 `torchvision 0.17.2`，搭配 `numpy 1.26.4` 维持 NumPy ABI 兼容。四个发布目标必须解析同一 GUI 依赖组合；Linux 继续使用官方 CPU wheel 索引。
- `v0.6.3` 在运行 `31823941178` 发现未约束的 harness 安装经当前 OpenCV 依赖把 NumPy 升回 2.x、破坏 Torch 2.2.2 NumPy ABI 后保持不可变；该标签未发布 GitHub Release。
- `v0.6.4` 重试固定 `opencv-python 4.11.0.86`，并对所有第一方 Program 安装应用同一约束文件，防止后续解析替换已验证的 NumPy、OpenCV、Torch 或 Torchvision。
- `v0.6.4` 在运行 `31824996497` 构建并安装四个完整运行时、但暴露 Intel macOS Desktop 架构名称不一致后保持不可变：发布 archive 使用 `x86_64`，electron-builder 接受 `x64`。该标签未发布 GitHub Release。
- `v0.6.5` 保留运行时产物名称，将 Intel Desktop 构建参数映射为 `x64`；发布 workflow 回归强制两个 macOS 架构的显式映射。
- `v0.6.5` 在运行 `31827207974` 构建两个 macOS Desktop 产物、但暴露冒烟脚本仅能解析紧凑 JSON 而 manifest 为格式化 JSON 后保持不可变。四个完整运行时和 CLI 安装器任务均通过；该标签未发布 GitHub Release。
- `v0.6.6` 重试采用运行时归档和 Desktop 准备已有的空白容错 manifest 解析器，提供可操作错误，并增加格式化 manifest 回归。

<div id="v066-formal-release-acceptance"></div>

### v0.6.6 正式发布验收

- `v0.6.6` 指向 `d08486953e19cf168fd8aba0704fe968b2a7f3a8`；发布运行 `31829278086` 成功完成，未移动任何旧标签。
- 稳定 GitHub Release 在 `https://github.com/FuzzyKuji/OpenProgram/releases/tag/v0.6.6` 发布，非草稿、非预发布。包含四个完整运行时 archive 及校验和、未签名 macOS arm64/x64 DMG 与 ZIP 及校验和、开发者 wheel/sdist 和 `release-manifest.json`。
- macOS arm64/x86_64 与 Linux arm64/x86_64 原生验收通过。每个运行时在原生 runner 上组装归档；四个 CLI 安装器任务均验证校验和、解压、完整产品能力、worker 冷启动、原子激活和启动器版本。两个 macOS Desktop 任务在上传前验证相同嵌入运行时。
- main CI `31828655714` 通过 Python 3.11/3.12/3.13、Web 和文档/示例任务；文档发布 `31828655717` 也通过。
- 发布后公开入口验收将 `https://openprogram.io/install` 经 GitHub `latest` 解析到 `v0.6.6`，把 macOS arm64 archive 安装到隔离状态和启动器目录，返回 `openprogram 0.6.6`，通过安装器完整运行时、`/healthz` 和 `openprogram doctor` 检查。

<div id="v070-browser-focused-release-acceptance"></div>

### v0.7.0 浏览器发布验收

- `v0.7.0` 解析到 `c7f5916b2b3acb67b936081763945ee080f81b9a`；在 main CI `31973024049` 和文档发布 `31973024046` 成功后一次创建。
- 发布运行 `31973458867` 成功。四个原生产品运行时、四个 CLI 安装器、两个 macOS Desktop、Python 分发及最终发布任务均通过。
- 稳定 [OpenProgram 0.7.0 Release](https://github.com/FuzzyKuji/OpenProgram/releases/tag/v0.7.0) 非草稿、非预发布。该验收点 GitHub `latest` 为 `v0.7.0`。17 个资产包含四个运行时及校验和、arm64/x64 未签名 DMG 与 ZIP 及校验和清单、开发者 wheel/sdist 和 `release-manifest.json`。
- 已发布 manifest 版本为 `0.7.0`；两个 macOS Desktop 架构和四个运行时的字节数及 SHA-256 与 GitHub 资产元数据一致。
- 发布验收使用 CI 包/运行时冒烟和只读发布元数据检查，未安装、替换、激活或重启用户当前 `/Applications/OpenProgram.app`，所以前台更新器 UI、长期调度与睡眠恢复明确仍未验证。
- 发布范围包括内建 Browser、profile 导入、书签/历史和 Agent 绑定 WebTab 控制。Chrome/Edge 扩展安装刻意排除，已在权威内建浏览器设计及产品 FAQ 说明。

<div id="current-v098-release-acceptance"></div>

### 当前 v1.0.0 发布验收

- 候选整合持久函数代码选择和重启恢复、模块组织及可恢复文件操作。现有本地签名、权限、取消和未知效果边界仍为准。
- 源码、锁文件、Desktop 与安装器版本一致。发布验收要求组合 Python 回归清单、Desktop、文档及独立规格/质量审查。
- 发布要求原生运行时、Desktop 和 CLI 安装器任务成功，再验证 manifest 和资产。
- 公开 macOS 桌面包使用 Developer ID 签名及 Apple 公证。本地刷新和自更新使用本地开发证书，不保留生产签名。
- 运行时能力验证和校验和要求不变。Windows Desktop 发布要求已配置签名凭据。

<div id="short-public-installer-batch"></div>

## 简短公开安装命令批次

- 基线提交：`c1886a3fdf7ba196c42ec9a2c19dca7fe86c12e7`。
- 公开命令：普通 macOS/Linux CLI 和服务端安装使用 `curl -fsSL https://openprogram.io/install | sh`。
- 边界：根脚本解析最新稳定 GitHub Release，校验三段数字版本，下载不可变标签下的安装器并传入版本。不组装第二套安装器，不削弱运行时校验和、能力 manifest 或 worker 冷启动验证。
- 可复现性：高级用户和 CI 可向 `sh` 进程传入 `OPENPROGRAM_VERSION=X.Y.Z`。标签中的 `scripts/install-release.sh` 保留为公开兼容 URL，并从相同不可变标签下载权威 `scripts/release/install-release.sh`。
- 发布：`docs/_static_root/install.sh` 在部署站点根目录重命名为 `/install`；`/docs/install/` 保留为安装文档目录。
- 测试：用模拟 `curl` 执行公开根脚本，覆盖自动最新版本解析和显式固定，断言标签安装器转交，构建文档并检查组装后的根文件，运行现有分发发布测试。
- RED：两个公开入口测试最初失败，因为根引导脚本不存在且 Pages workflow 未发布 `/install`。
- GREEN：分发发布文件 25 项通过；文档 509 页；落地页通过；零死链；组装站点探测保留 `/docs/install/` 并验证根 `/install` 脚本。
- 2026-08-15 发布前证据：GitHub `latest` 最初为 `v0.6.0`，既无资产，标签也无 `scripts/install-release.sh`。安装器正确失败而非安装缩水产品。上面的 `v0.6.6` 正式验收取代这一已观察发布状态。

<div id="unified-complete-product-batch"></div>

## 统一完整产品批次

- 基线提交：`e6ec8694977080153a3c94e50a5080d2ff43b69b`。
- 产品合同：每个受支持的非开发安装在对应平台/架构包含相同完整能力。Desktop 使用与 CLI/服务端相同的运行时 archive，只允许 Electron 外层不同。若完整打包入口未通过，不提供该 Desktop 产物，而不是削减能力。
- 必须能力：Web、providers、MCP、memory、channels、search、Ink TUI、Playwright Chromium。运行时不捆绑任何 Program。Computer use 是内置工具，不需要捆绑模型。产品运行时明确排除 PyTorch、torchvision、OpenCV、EasyOCR、sentence-transformers、triton 和 NVIDIA/CUDA 分发包。
- 开发安装增加可编辑源码、测试、诊断、本地前端构建和显式配置的感知/OCR/浏览器 overlay。需要被排除感知依赖的路径不是产品 manifest 能力。产品运行时不隐式安装这些依赖；显式 overlay 所需模型资产由其自身配置负责。
- 普通用户从 GitHub Release 安装。PyPI wheel 仅为内部构建输入和开发者产物，不是产品安装路径。
- macOS 产物明确为未签名 DMG/ZIP；Apple Developer ID 签名和公证不是该发布要求。Linux 发布完整 x86_64/arm64 CLI/服务端运行时；完整 AppImage 未通过打包检查后不再发布 Linux Desktop。
- 本批最初没有 Windows 产物。现在相同运行时/Desktop 分离方式生成原生 Windows x64/arm64 运行时、安装器和 Desktop，见 [Windows 支持](windows-support.zh.md)。仍排除 OS 凭据存储集成。

<div id="current-batch-files"></div>

### 当前批次文件

- 产品合同：`docs/reference/design/distribution/installation-packaging.html` 及本记录。
- 运行时组装：已提交产品 manifest、构建/归档脚本、Desktop 运行时暂存及 CLI 发布安装器。
- 启动器：Electron 和 CLI 启动路径设置内置 Playwright Chromium 位置并验证能力 manifest。Session/Memory Git 历史使用宿主系统 Git；两个启动器均不捆绑 Git。
- 发布：`.github/workflows/release.yml`、Desktop 命名、运行时 archive、校验和和公开入口冒烟。
- 产品文档：安装、桌面、服务端、升级、Programs 和 README 入口描述一个完整产品，而非可选第一方组件。
- 测试：`tests/unit/test_distribution_release.py` 及针对性 Program/运行时与打包入口探测。

<div id="current-batch-public-entry-acceptance"></div>

### 当前批次公开入口验收

1. 每个平台 archive 含 manifest，为 `web`、`providers`、`mcp`、`memory`、`channels`、`search`、`tui.ink`、`browser.playwright` 提供 `present` 和 `verified`。不安装 PyTorch、torchvision、OpenCV、EasyOCR、sentence-transformers、triton 或 NVIDIA/CUDA 分发包。
2. 受支持 Desktop 打包使用已构建 archive；CLI 安装器使用 GitHub Release 中字节相同的 archive。两者不独立解析产品依赖。
3. 普通安装不进行 PyPI 依赖解析、仓库克隆、npm 构建，或首次使用时下载 Playwright Chromium，也不安装任何 Program；也不隐式下载被排除的感知依赖，相关路径需显式开发或 backend overlay。
4. 发布产物或切换 CLI `current` 前，公开入口探测验证 worker、Web 资产、channel/search 导入、和 Playwright Chromium 可执行文件。
5. macOS 产物名称和文档注明 `unsigned`；发布 workflow 不要求 Apple/PyPI 凭据，也不执行签名、公证或 PyPI 发布。
6. 文档不把 `pip install openprogram`、组件选择提示或未验证 Linux Desktop 包作为普通产品安装方式。

<div id="current-batch-gate-manifest"></div>

### 当前批次检查清单

```text
python -m pytest tests/unit/test_distribution_release.py tests/unit/test_desktop_packaged_files.py tests/unit/test_webui_frontend.py
python -m scripts.docs_site.checklinks
python -m scripts.docs_site.build
python -m pytest tests/ --ignore=tests/integration
npm run check --prefix desktop
npm run check --prefix web
bash -n scripts/release/build-product-runtime.sh scripts/install-release.sh scripts/release/prepare-desktop-runtime.sh
git diff --check
git status --short
```

平台运行时和公开 Desktop 产物探测在原生发布 runner 上执行。平台产物宁可不提供，也不发布削减能力的 manifest。

<div id="current-batch-evidence"></div>

### 当前批次证据

| 字段 | 证据 |
|---|---|
| RED | 初次针对性分发运行有 6 项预期失败：无产品 manifest、无统一构建器、CLI 仍解析 wheel、Desktop/CLI 分别组装依赖、workflow 仍要求 Apple/PyPI 发布路径。 |
| 静态 GREEN | 移除未验证 Linux Desktop 目标后，分发、打包文件和 Web 前端共 35 项通过。Desktop/Web、shell 语法、Ruff、文档 507 页、零死链和 diff 均通过。 |
| 当前 macOS arm64 运行时边界 | 打包 CPython 3.12.10、锁定 OpenProgram 依赖、Playwright Chromium 及全部 8 项能力，不含任何 Program；被排除的感知依赖不属于产品运行时。 |
| 运行时验证 | schema 2 验证器打开真实无头 Chromium 页面，导入 channels/search/PDF，检查 Web 资产，并拒绝 PyTorch、torchvision、OpenCV、EasyOCR、sentence-transformers、triton 和 NVIDIA/CUDA。记录产品 manifest 哈希、`uv.lock` 哈希、准确安装分发包、平台和架构。 |
| Archive 与 CLI 入口 | macOS arm64 archive 经校验和验证，解压到新 CLI 版本目录，再验证、冷启动和停止 worker、切换 `current`，得到可用的 `openprogram 0.6.1` 启动器。 |
| 原生 Linux 运行 | `c49596ef` 上 GitHub Actions `31809407776` 构建验证完整 Linux x86_64/arm64。两项 CLI 安装器通过校验和、解压、能力、冷启动、原子激活和版本检查。完整运行时通过后 AppImage 在 electron-builder 嵌入 block-map 阶段失败，未进入公开入口或 Debian 11 验证。 |
| 打包决定 | 移除 Linux AppImage 构建发布。Linux 继续通过含 Web UI/TUI 的完整 x86_64/arm64 CLI/服务端 archive 支持，不提供缩水 Desktop。 |
| 最终 Linux 检查 | `08a9a19a` 上 Actions `31811091609` 的四项任务全部通过：x86_64/arm64 完整运行时构建归档及两架构 CLI 公开入口安装。workflow 无 Linux Desktop 打包任务。 |
| 完整本地检查 | `tests/ --ignore=tests/integration`：5285 通过、11 跳过、1 预期失败、5 失败。四个确定性失败不属于本批：两个既有 channel HTTP 清单、一个 Research `context` 参数、一个 browser-agent 迁移清单。第五个多进程超时隔离后立即通过。 |
| 审查 | Ponytail 全面审查删除第一方组件选择菜单，简化为一个 manifest、一个构建器、一个验证器及已有脚本/workflow。人工规格审查修复未锁定依赖解析、非规范 archive 根、缺少校验和/路径验证、Playwright 清理警告及 Research PDF extra。 |
| 增量提交 | 设计 `e2a1b691`、实现 `c75099d2`、完整安装后续 `685833cc` 逐步合并推送；后续以 `c49596ef` 进入 `main`。 |

<div id="prior-packaging-batch-historical-evidence"></div>

## 先前打包批次（历史证据）

- 基线：`717d4e176307e08cc4ae4facd3c484511684746c`。
- 公开行为：发布 wheel 无需 Node.js 即提供预构建 Web；打包 Electron 启动嵌入 CPython；macOS 构建 DMG/ZIP，Linux 构建 AppImage；发布 CI 验证版本和校验和。
- 产品文档只描述验收通过的行为。
- 此历史批次未实现 Windows 原生打包；它是延后产品决定，不是拒绝方向。
- 排除 OS 凭据存储集成。

<div id="prior-batch-files"></div>

### 先前批次文件

- 生产：`openprogram/interfaces/server/frontend.py`、`pyproject.toml`、`apps/desktop/main.js`、`apps/desktop/package.json`、发布暂存脚本及 workflow。
- 测试：前端包资源、Desktop 打包运行时及发布配置检查。
- 文档：分发 HTML 设计、相关设计链接，以及安装/升级/桌面/服务端产品页。

<div id="prior-batch-public-entry-acceptance"></div>

### 先前批次公开入口验收

1. 发布资产暂存后构建的 wheel 包含 `openprogram/interfaces/server/_frontend/index.html` 和带哈希的 Next.js 资产；隔离安装不依赖仓库源码或 Node.js 即提供 `/chat`。
2. 打包 Electron 仅从 `process.resourcesPath` 解析 Python，执行 `-I -B -m openprogram worker start`，不回退 `PATH`，不向签名应用写字节码。
3. `electron-builder` 声明 macOS DMG/ZIP 和 Linux AppImage，将暂存运行时作为不可变资源。
4. 标签触发 workflow 在各平台原生 runner 构建，执行针对性验收，只在产物存在后发布校验和。

<div id="prior-batch-full-gate-manifest"></div>

### 先前批次完整检查清单

```text
python -m pytest tests/component/webui/runtime/test_webui_frontend.py tests/unit/webui/test_desktop_packaged_files.py tests/component/config/test_distribution_release.py
python -m scripts.docs_site.checklinks
python -m scripts.docs_site.build
python -m pytest tests/ --ignore=tests/integration
npm run check --prefix desktop
npm run check --prefix web
git diff --check
git status --short
```

平台产物在发布 workflow 构建，因为 macOS 不能验证 Linux CPython/AppImage，Linux 不能签名或公证 macOS App。

<div id="prior-linux-completion-batch"></div>

### 先前 Linux 完成批次

- 基线：`540591e9f628498dee87a1c2ebb30ab4c5e757f6`。
- 生产文件：`apps/desktop/package.json`、`scripts/release/smoke-packaged-runtime.sh`、`scripts/install-release.sh`、`.github/workflows/release.yml`、`.github/workflows/linux-release-smoke.yml`。
- 测试文件：`tests/unit/test_distribution_release.py`。
- Linux x86_64 验收：原生 runner 构建 AppImage，在 Xvfb 下执行公开入口，由 Electron 启动嵌入 worker，验证 `/healthz`、`/chat`、不可变 Program 行为及一致的 freedesktop 文件名/`StartupWMClass` 元数据。
- Linux CLI 验收：原生 x86_64/arm64 runner 用固定 uv 和受管 CPython 安装发布 wheel，切换 `current` 前冷启动 worker，并验证启动器版本。
- 发布前执行：手动 Linux 冒烟 workflow 无需 Apple/PyPI 凭据，仅上传验证后的 wheel/AppImage 为 CI 资产，不创建稳定发布。
- 此历史批次早于 Windows 实现，没有增加 Linux arm64 Desktop、发行版原生 deb/rpm 或 OS 凭据存储。当前 Windows 发布路径见 [Windows 支持](windows-support.zh.md)。

<div id="prior-batch-ledger"></div>

### 先前批次台账

| 字段 | 证据 |
|---|---|
| 基线 | `717d4e176307e08cc4ae4facd3c484511684746c` |
| CodeGraph | 初始探索在共享 checkout 可用仓库索引；隔离 worktree 无 `.codegraph/`，所以实现定位使用针对性 `rg` 和直接读取。 |
| RED | 初次针对性运行 5 失败、10 通过，覆盖缺少包资源前端选择、Desktop 目标/运行时解析、发布安装器及 workflow。 |
| GREEN | 分发/Desktop 25 通过；文档 503 页、零死链；Desktop/Web npm 检查通过；干净 wheel 导入、受管 CLI 安装及重建 macOS arm64 worker 冒烟通过。 |
| 规格审查 | 增加最终 DMG 公证/stapling、运行时 manifest schema/版本验证，并移除残留公开 Windows-native/any-platform 声明后，本地设计-实现审查通过。两次限定 CodeBuddy 审查无输出而终止，不声称外部通过。 |
| 质量审查 | Ponytail 全面审计未发现可删除的新依赖或打包抽象。shell/YAML、diff、针对性测试、重建 App 冒烟和运行时签名稳定性通过。workflow 以仅所有者权限写 App Store Connect key，并使用受保护 `release` 环境。 |
| 完整检查 | `tests/ --ignore=tests/integration`：5254 通过、11 跳过、1 预期失败、3 失败。失败不属于分发：两项 HTTP 清单报告未注册 channel transport，一项 agent-tool 报告 research program 丢弃 `context`。改动相关 Python、文档、Desktop、Web、shell、YAML、wheel、CLI 安装器和打包运行时检查均通过。 |
| 依赖审计 | 无新增依赖。既有锁文件报告 Desktop npm 7 项公告（2 中、5 高）和 Web npm 8 项高危公告；修复属于独立依赖维护。 |
| 仅发布证据 | Developer ID、Apple 公证、macOS x64、GitHub Release 创建和 PyPI 发布仍需标签 workflow 及受保护凭据。Linux x86_64 AppImage 启动和 x86_64/arm64 CLI 安装已有独立原生 runner 证据。 |
| 实现提交 | 初始 `714981e1`、`9e1e5e0a`、`dddea787`；Linux 完成 `a170ca65`、`78e78921`、`41b39e86`、`63f15e65`、`b7220c89`；均逐步合并推送至 `main`。 |

<div id="prior-linux-completion-evidence"></div>

### 先前 Linux 完成证据

| 字段 | 证据 |
|---|---|
| RED | 旧 Linux 冒烟解压 AppImage 后直接启动嵌入 Python，未测试公开 Electron 入口。首次原生 workflow 暴露 electron-builder 隐式 CI 发布；干净 arm64 容器暴露 worker stop 的僵尸 PID；运行中升级探测暴露共享用户状态干扰。 |
| GREEN | 分发 18 项通过；Desktop/Web 通过；零死链；静态构建 503 页。 |
| 原生 Linux | 已推送 `main` 提交 `17db67dc` 的 Actions `31798379681` 通过 x86_64 AppImage、x86_64 CLI 和 arm64 CLI。历史 AppImage 冒烟使用 Debian 11/glibc 2.31，无系统 Python、Node.js、Git 或外网，但未测试 Session/Memory Git 历史，不能证明当前产品可省略系统 Git。 |
| CLI 隔离 | 历史原生 arm64 Debian 12 探测在无系统 Python/Node.js/Git 环境安装 uv 0.11.16、受管 CPython 3.12.10 和 0.6.1 wheel，仅测试安装器隔离与 worker 保留；当前 Session/Memory 历史仍需宿主 Git。 |
| 规格审查 | 人工审查修复公开入口覆盖、freedesktop 窗口关联、隐式发布、探测状态隔离和全新安装 doctor 文案。限定 CodeBuddy 尝试耗尽轮数而未给结论，不声称外部规格通过。 |
| 质量审查 | Ponytail 全面审查保留现有 shell/workflow 实现，无运行时新依赖，拒绝独立 doctor 模式。限定 CodeBuddy 审查只返回工具调用文本，无结论，不声称外部质量通过。 |
| 稳定发布 | 未创建 `v0.6.1` 标签。GitHub `release` 环境及 Apple 签名 secrets 不存在，外部 PyPI trusted-publisher 配置无法从仓库验证，因此签名 macOS 产物和原子 GitHub/PyPI 稳定发布仍受阻。 |
