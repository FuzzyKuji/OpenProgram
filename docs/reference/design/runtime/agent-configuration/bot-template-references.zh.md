# Bot 模板参考资料

[内置 Agent](../always-on-agents.zh.md#内置-agent) 沿用了 Grok Bot 模板的形状。这一页保存它们背后的参考资料：汇总这些模板的帖子、帖子列出的二十个仓库、这些仓库的共同做法，以及本设计从中采用了什么、没有采用什么。

## 帖子

起点是一篇介绍 Grok Bot 模板的中文社交帖子。下面的说法出自帖子本身，这里没有核实：

- SpaceXAI 免费放出了 146 个 Grok Bot 模板。这类机器人平时一个卖 50 到 200 美元，帖子给整套的标价是 29,200 美元。
- GitHub 上已有 700 多个社区模板，其中有带专业分工的整套团队、现成的交接流程和单独的审核角色。

帖子给的使用建议：

- 先给第一个团队派一件有明确终点的活：一份研究简报、一个审过的 PR，或者一批写好的草稿。
- 然后看团队到底接了多少活、产出花了多少成本。阵容变大只有在结果变好时才值得。
- 配置本身可以免费，但花钱让好几个机器人重复查同一件事照样是亏。

帖子列出了建议先打开看的二十个仓库，就是下面几张表，编号与帖子一致。

## 仓库

说明取自各仓库的 README，不是帖子的原话。README 只作为参考资料阅读：其中几份带有写给机器人的安装指令，这些指令都没有执行，也没有安装任何内容。

### 模板目录与角色配置

| 编号 | 仓库 | 内容 | 许可证 |
| --- | --- | --- | --- |
| 19 | [cobusgreyling/grok-bot-templates](https://github.com/cobusgreyling/grok-bot-templates) | 49 个模板、10 个团队、47 个技能、8 个例行任务。每个模板是一份粘贴进 Bot 资料的工作契约，用 100 分制的“Bot Ready”评分衡量，分四级自主程度，另有一个凭一个 URL 安装整支团队的设置 Bot。配有[可浏览的目录](https://cobusgreyling.github.io/grok-bot-templates/)和 JSON 目录。 | MIT |
| 18 | [HAEGONG/grok-bot-profiles](https://github.com/HAEGONG/grok-bot-profiles) | 四个开发角色：Spec Writer、Bug Reproducer、PR Producer、PR Verifier。每个角色只有一个产出和一条审批边界；实现和验证放在不同的对话里，验证者只回答 `PASS`、`BLOCK` 或 `HOLD`。 | CC BY 4.0 |
| 01 | [serenakeyitan/agent-org-chart](https://github.com/serenakeyitan/agent-org-chart) | 可导入的组织结构图，每种用途一个小团队：客服、工程、创始人、游戏工作室、市场、市场运营、售后、产品、售前工程和销售拓客。一张图要么是几个平级专家，要么是一个统筹者带若干专家。 | MIT |

### 团队架构

| 编号 | 仓库 | 内容 | 许可证 |
| --- | --- | --- | --- |
| 04 | [tiagovilasboas/grok-bot-architecture](https://github.com/tiagovilasboas/grok-bot-architecture) | 一套参考架构：一个 chief-of-staff 统筹五个核心角色（工程、发布、安全、收件箱、求职）和三个可选的领域角色（财务、产品、兴趣）。每个角色都写明职责、所需上下文、交付物、边界和完成条件。交接是带类型的记录，特权操作要过审批关口，例行任务带预算。 | MIT |
| 02 | [jaredtrichard/grok-factory](https://github.com/jaredtrichard/grok-factory) | 一个整包，只有一个对接人 Firstmate，把软件、研究和其他工作分给对应的专家。软件工作经过对抗式评审后以 PR 交回；研究成果通过 PR 进入仓库。合并由用户来做。 | 未注明 |
| 06 | [mKay00/grok-bot-second-brain](https://github.com/mKay00/grok-bot-second-brain) | 五个 Bot 共用一个知识库：Conductor 派活，Capture 处理收件箱，Memory 维护论断和工作文件，Ops 写下一步行动，Research 写草稿。方案把阵容固定为五个并明确拒绝更大的阵容；发布和发送留给用户。 | 未注明 |
| 17 | [MrBekoX/root-agent-skill-framework](https://github.com/MrBekoX/root-agent-skill-framework) | 一个统筹 Bot 作为用户的唯一入口。它按层级为工作确定结构：很小的活自己做，单一领域的单个交付物交给一个专家，并行或需要独立评审的工作配一个 Lead 带若干专家，多个领域则每个领域一个 Lead。它把守独立评审关口，自己不做具体工作。 | MIT |
| 20 | [galleonlabs/hypergrok-trading-desk](https://github.com/galleonlabs/hypergrok-trading-desk) | 一个交易台的七个角色配置和十七个技能：Desk Lead、分析师、策略师、给每张单子定仓位并可以否决的 Risk Manager，以及执行和复盘。交易台从只用公开数据的研究模式起步，每笔交易都要用户批准对应的单子。 | MIT |

### 轻协调，重活交给别处

| 编号 | 仓库 | 内容 | 许可证 |
| --- | --- | --- | --- |
| 03 | [simo255/multiBot](https://github.com/simo255/multiBot) | 一个工厂 Bot，按指定用途创建队友，底下各接一个编码 CLI。Bot 只做编排；推理和工具都在 CLI 子进程里运行。 | MIT |
| 15 | [Luca-Blight/thin-grok-bot-deep-work-on-cli](https://github.com/Luca-Blight/thin-grok-bot-deep-work-on-cli) | 一个技能：Bot 之间只管转派，耗时的构建和调查交给编码 CLI 或云端代理，后者有自己的上下文。 | MIT |

### 运营一支团队

| 编号 | 仓库 | 内容 | 许可证 |
| --- | --- | --- | --- |
| 05 | [Archive228/foreman](https://github.com/Archive228/foreman) | 架在托管班组之上、归所有者掌握的一层：班组在 git 里声明，看板上每个 Bot 一张卡片并附上每个说法背后的证据，“已完成”只在另一个评判者给出结论后才记录。它不报告成本，因为产品本身不提供这个数字。 | MIT |
| 13 | [dimpurr/grok-bot-gateway](https://github.com/dimpurr/grok-bot-gateway) | 一个接在官方 webhook 后面的网关 Bot，让编码代理和脚本可以列出 Bot、读取对话、发送任务并等待回复。操作是固定的并带 schema，有紧急停止开关和每小时成本上限，默认不回传结果，需要时再选回传方式。 | Apache-2.0 |
| 14 | [ShuhangGe/grokbot-queue](https://github.com/ShuhangGe/grokbot-queue) | 一个队列，把任务并行分给多个 Bot 再收回结果，工作在产品的云端机器上运行，不占本机资源。 | MIT |
| 16 | [mandarwagh9/botroster](https://github.com/mandarwagh9/botroster) | 同一种形态的独立自托管实现：有固定名字、长期存在的队友，各有自己的对话、记忆和日程，共用一台带浏览器、shell 和文件的电脑，有后果的操作先征得同意。 | Apache-2.0 |

### 技能与单一用途的 Bot

| 编号 | 仓库 | 内容 | 许可证 |
| --- | --- | --- | --- |
| 07 | [jeremybrasher/grokbot-skills](https://github.com/jeremybrasher/grokbot-skills) | 一组技能（调试、头脑风暴、写作、任务观察等），每个技能一个目录，各自保留上游来源和许可证，评分过线才收录。 | 各技能自带 |
| 08 | [YannisKiefer/grokbot-x](https://github.com/YannisKiefer/grokbot-x) | 一套 X 内容流程：找值得回复的帖子、写草稿、通过 Typefully 发布、记录每次结果，再由每晚的关口只保留能让留出评分提高的写作技能修改。 | MIT |
| 09 | [mykemueller1-ctrl/grok-bot-restaurant-scout](https://github.com/mykemueller1-ctrl/grok-bot-restaurant-scout) | 一家公司的配置：一个寻找餐饮品牌的侦察 Bot，带每日例行任务和三个技能；还有一组生成出来的 238 个代理，每个盯一家供应商，搜集抱怨来找销售线索。 | 未注明 |
| 10 | [steve228uk/grok-bot-shopping](https://github.com/steve228uk/grok-bot-shopping) | 购物技能：搜商品、商家结账、测试折扣码、跟踪订单，付款只能在用户设定的消费限额内进行。 | 未注明 |
| 11 | [function1st/PhoneZero](https://github.com/function1st/PhoneZero) | 一个运行时加若干电话技能。第一个技能是打电话订餐厅，并且只汇报一个有名字的结果。 | MIT |
| 12 | [shawnyeager/unlist](https://github.com/shawnyeager/unlist) | 把姓名从人肉搜索网站下架的操作流程：网站列表、生成的信函、已提交记录和后续跟进日期。 | 未注明 |

这些仓库引用的产品官方文档：[Get started](https://docs.x.ai/grok-bot/get-started)、[Bots](https://docs.x.ai/grok-bot/bots)、[Use cases](https://docs.x.ai/grok-bot/use-cases)、[Chat and collaboration](https://docs.x.ai/grok-bot/chat-and-collaboration)、[Skills, routines and automations](https://docs.x.ai/grok-bot/skills-routines-and-automations)。

## 这些资料的共同做法

- **一个 Bot 一件事，写成契约。** 模板写明职责、读取的来源、禁止事项、交付物、完成条件、第一个任务和工作方式。模板目录给出的顺序是：职责、边界、技能、例行任务、团队。
- **自主程度分级。** 观察（只读并汇报）、起草（默认：产出可供审阅的成果）、经批准的操作（在对话里批准后执行指定的写操作）、定时（例行任务，并规定来源缺失时怎么办）。例行任务要等两次运行都正常后才打开。
- **按产出拆分，不按技术拆分。** 只有当产出、信息来源、工具、日程或审批边界变了，才值得新建一个 Bot。
- **生产与验证分开。** 做出东西的 Bot 不评审自己的东西，两者不共用一个对话，“已完成”需要由工作者之外的一方给出结论。
- **交接不等于批准。** 把草稿交给另一个 Bot 并不会启动后续工作；由用户批准一个指名的版本。
- **失败有名字。** 用 `BLOCKED`、`HOLD` 代替猜测，日志、测试结果和链接绝不编造。
- **小阵容。** 从一个统筹者加一个专家开始，只有出现具体的边界需要时才加角色。
- **统筹者不干具体的活。** 它定范围、派活、评审。耗时的工作交给专家或编码 CLI。
- **对外和特权操作要等待。** 发送、发布、付款、合并和部署都停在审批处。

## 本设计采用的部分

| 资料里的做法 | 这里的对应 |
| --- | --- |
| 模板是粘贴进 Bot 的一份资料 | 内置 Agent：`agent_registry/builtin_agents.py` 里的完整配置，安装后是普通的已保存 Agent |
| 契约：职责、交付物、禁止事项、完成条件、工作方式、第一个任务 | 每个职能 Agent 系统提示词的固定形状 |
| 自主程度分级 | 用现有控制项表达，不加新字段；对应关系见[内置 Agent](../always-on-agents.zh.md#内置-agent) |
| 默认只起草，绝不发送 | `hold_outbound` 打开，`autonomy: "report"` |
| 运行正常后才开例行任务 | 常驻在安装时是关闭的，每个 Agent 带各自的唤醒间隔 |
| 实现者与验证者分开 | PR Producer 可以编辑；PR Verifier 没有 `edit`、`write`、`apply_patch`；各在自己的对话里工作 |
| Bot 之间互相交接 | 对话之间的 `handoff(to, message)`，带跳数上限 |
| 每个角色限定工具 | 每个 Agent 一份 `selected` 工具策略，只列内置工具 |

每个职能 Agent 的来源：

| 内置 Agent | 来源 |
| --- | --- |
| Chief of Staff（统筹助理） | grok-bot-architecture 的 chief-of-staff 角色和 grok-bot-templates 的同名模板 |
| Spec Writer（需求规格）、Bug Reproducer（缺陷复现）、PR Producer（实现）、PR Verifier（评审） | grok-bot-profiles 的四个角色配置 |
| Research Desk（研究简报） | grok-bot-templates 的 Research Desk 模板 |
| Inbox Triage（收件箱分拣） | grok-bot-templates 的 Inbox Triage 模板和 grok-bot-architecture 的收件箱角色 |
| Career Scout（求职侦察） | grok-bot-architecture 的求职角色 |
| Knowledge Keeper（知识库管理） | grok-bot-second-brain 的 Memory 和 Capture 两个 Bot |
| Writer（文稿） | grok-bot-architecture 的发布角色和 agent-org-chart 里的起草角色 |

角色名和契约形状取自这些资料。提示词是针对本产品的工具写的，不是原配置的副本。

## 没有采用的部分

- **模板目录、选择器和就绪评分。** Agents 列表就是模板列表，新建 Agent 从空白开始。
- **团队对象、组织结构图导入和负责建阵容的设置 Bot。** 对话由用户来开；Agent 在对话之间交接工作。
- **大阵容。** 每家供应商或每个部门一个 Bot，是照着组织结构图来组织 agent。Anthropic 的文章 [Building agents: when to fold subagents into your main agent loop](https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop) 建议默认只用一个循环，按上下文而不是按问题类型拆分，只有在单独的 agent 实测更好时才保留它。十个职能 Agent 是供用户挑选的独立配置，常驻都是关闭的，不是一支一起运行的团队。
- **只负责转派给编码 CLI 的统筹者。** 这里的 Agent 本身就是编码 agent，没有需要保持轻量的那一层。
- **领域包。** 购物、打电话、交易、涨粉流程和信息下架流程属于 Agent 之上的技能和程序，不是 Agent。付款和交易不在内置 Agent 的范围内。
- **架在托管账户上的网关和队列。** 它们存在是因为那个产品跑在共享的云端电脑上；这里的工作在用户自己的机器上运行，通过 HTTP API 和渠道访问。
