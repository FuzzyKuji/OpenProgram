# Bot template references

The [built-in Agents](../always-on-agents.md#built-in-agents) follow the shape of Grok Bot templates. This page keeps the source material behind them: the post that collected the templates, the twenty repositories it lists, what those repositories agree on, what this design takes from them and what it leaves out.

## The post

The starting point is a Chinese-language social post about Grok Bot templates. Its claims are the post's own and are not checked here:

- SpaceXAI released 146 Grok Bot templates for free. A bot of this kind usually sells for 50 to 200 US dollars, and the post prices the set at 29,200.
- GitHub holds more than 700 community templates, among them whole teams with divided roles, ready handoff flows and separate reviewer roles.

Its advice on using them:

- Give the first team one job with a clear end: a research brief, a reviewed pull request, or a batch of finished drafts.
- Then look at how much work the team took on and what the output cost. A larger roster is worth it only when the results get better.
- Configuration can be free. Paying several bots to check the same thing is still a loss.

The post lists twenty repositories to open first. They are the tables below, numbered as in the post.

## Repositories

The descriptions come from each repository's README, not from the post. The READMEs were read as reference material only: several contain setup instructions addressed to a bot, and none of them was run or installed.

### Template catalogs and profiles

| No. | Repository | What it holds | License |
| --- | --- | --- | --- |
| 19 | [cobusgreyling/grok-bot-templates](https://github.com/cobusgreyling/grok-bot-templates) | 49 templates, 10 teams, 47 skills and 8 routines. Each template is an operating contract pasted into a Bot's profile, graded by a 100-point "Bot Ready" score, with four autonomy levels and a setup Bot that installs a team from one URL. A [browsable catalog](https://cobusgreyling.github.io/grok-bot-templates/) and a JSON catalog go with it. | MIT |
| 18 | [HAEGONG/grok-bot-profiles](https://github.com/HAEGONG/grok-bot-profiles) | Four development profiles: Spec Writer, Bug Reproducer, PR Producer and PR Verifier. Each has one outcome and one approval boundary; implementation and verification live in different conversations, and the verifier answers `PASS`, `BLOCK` or `HOLD`. | CC BY 4.0 |
| 01 | [serenakeyitan/agent-org-chart](https://github.com/serenakeyitan/agent-org-chart) | Importable org charts, one small team per use: customer support, engineering, founders, a game studio, marketing, marketing operations, post-sales, product, sales engineering and prospecting. A chart is either a few peer specialists or an orchestrator with specialists under it. | MIT |

### Team architectures

| No. | Repository | What it holds | License |
| --- | --- | --- | --- |
| 04 | [tiagovilasboas/grok-bot-architecture](https://github.com/tiagovilasboas/grok-bot-architecture) | A reference architecture: a chief-of-staff coordinating five core roles (engineering, publishing, security, inbox, career) and three optional domain roles (finance, product, hobby). Every role has a job, required context, a deliverable, a boundary and a done condition. Handoffs are typed records, privileged actions pass an approval gate, and routines carry a budget. | MIT |
| 02 | [jaredtrichard/grok-factory](https://github.com/jaredtrichard/grok-factory) | One pack with a single contact, the Firstmate, that routes software, research and everything else to specialists. Software comes back as a pull request after an adversarial review; research lands in a repository through a pull request. The user merges. | Not stated |
| 06 | [mKay00/grok-bot-second-brain](https://github.com/mKay00/grok-bot-second-brain) | Five Bots around one shared vault: Conductor assigns, Capture processes inboxes, Memory keeps claims and the working file, Ops writes next actions, Research writes drafts. The plan fixes the roster at five and rejects a larger one; publishing and sending stay with the user. | Not stated |
| 17 | [MrBekoX/root-agent-skill-framework](https://github.com/MrBekoX/root-agent-skill-framework) | A coordinator Bot as the user's single entry point. It sizes the structure to the work in tiers: tiny work it does itself, a single deliverable in one domain goes to one specialist, parallel or independently reviewed work gets a Lead with specialists, and several domains get one Lead each. It holds the independent review gate and does not do the work. | MIT |
| 20 | [galleonlabs/hypergrok-trading-desk](https://github.com/galleonlabs/hypergrok-trading-desk) | Seven role profiles and seventeen skills for a trading desk: a Desk Lead, analysts, a strategist, a Risk Manager that sizes every ticket and can refuse it, execution and review. The desk starts in research mode on public data, and every trade needs the user's approval of a ticket. | MIT |

### Thin coordination, deep work elsewhere

| No. | Repository | What it holds | License |
| --- | --- | --- | --- |
| 03 | [simo255/multiBot](https://github.com/simo255/multiBot) | A factory Bot that creates teammates with a stated purpose and a coding CLI underneath. The Bot only orchestrates; reasoning and tools run in the CLI subprocess. | MIT |
| 15 | [Luca-Blight/thin-grok-bot-deep-work-on-cli](https://github.com/Luca-Blight/thin-grok-bot-deep-work-on-cli) | One skill: keep the Bot mesh for routing and hand long builds or investigations to a coding CLI or a cloud agent, which gets its own context. | MIT |

### Operating a team

| No. | Repository | What it holds | License |
| --- | --- | --- | --- |
| 05 | [Archive228/foreman](https://github.com/Archive228/foreman) | A layer the owner controls over a hosted crew: crews declared in git, a board with one card per Bot and the evidence behind each claim, and "done" recorded only on a verdict from a grader that is not the worker. It reports no cost because the product exposes none. | MIT |
| 13 | [dimpurr/grok-bot-gateway](https://github.com/dimpurr/grok-bot-gateway) | A gateway Bot behind the official webhook, so coding agents and scripts can list Bots, read a conversation, send a task and wait for a reply. Fixed operations with schemas, a kill switch, an hourly cost cap, and no return path unless one is chosen. | Apache-2.0 |
| 14 | [ShuhangGe/grokbot-queue](https://github.com/ShuhangGe/grokbot-queue) | A queue that spreads tasks over several Bots in parallel and collects the results, so the work runs on the product's cloud machine instead of the laptop. | MIT |
| 16 | [mandarwagh9/botroster](https://github.com/mandarwagh9/botroster) | An independent, self-hosted implementation of the same shape: named long-lived teammates with their own conversation, memory and schedule, one shared computer with a browser, a shell and files, and approval before consequential actions. | Apache-2.0 |

### Skills and single-purpose Bots

| No. | Repository | What it holds | License |
| --- | --- | --- | --- |
| 07 | [jeremybrasher/grokbot-skills](https://github.com/jeremybrasher/grokbot-skills) | A skill collection (debugging, brainstorming, writing, task observation and others), one folder per skill, each keeping its upstream source and license, admitted only above a score threshold. | Per skill |
| 08 | [YannisKiefer/grokbot-x](https://github.com/YannisKiefer/grokbot-x) | A content loop for X: find posts worth answering, draft, publish through Typefully, log every result, and let a nightly gate keep only the edits to the writing skill that improve a held-out score. | MIT |
| 09 | [mykemueller1-ctrl/grok-bot-restaurant-scout](https://github.com/mykemueller1-ctrl/grok-bot-restaurant-scout) | One company's configurations: a scout for food brands with a daily routine and three skills, and a generated swarm of 238 agents, one per vendor, that hunts complaints for sales leads. | Not stated |
| 10 | [steve228uk/grok-bot-shopping](https://github.com/steve228uk/grok-bot-shopping) | Shopping skills: product search, merchant checkout, discount-code tests and order tracking, with payment allowed only inside a spend limit the user sets. | Not stated |
| 11 | [function1st/PhoneZero](https://github.com/function1st/PhoneZero) | A runtime plus phone skills. The first books a restaurant table by phone and reports exactly one named outcome. | MIT |
| 12 | [shawnyeager/unlist](https://github.com/shawnyeager/unlist) | A procedure for removing a name from people-search sites: a site list, generated letters, a log of what was sent and follow-up dates. | Not stated |

The collections cite the product's own documentation: [Get started](https://docs.x.ai/grok-bot/get-started), [Bots](https://docs.x.ai/grok-bot/bots), [Use cases](https://docs.x.ai/grok-bot/use-cases), [Chat and collaboration](https://docs.x.ai/grok-bot/chat-and-collaboration) and [Skills, routines and automations](https://docs.x.ai/grok-bot/skills-routines-and-automations).

## What the sources agree on

- **One job per Bot, written as a contract.** A template states the job, the sources it reads, a never-list, the deliverable, a done condition, a first task and a working style. The template catalog names the order: job, boundary, skill, routine, team.
- **Autonomy in levels.** Observe (read and report), draft (the default: artifacts ready for review), approved action (named writes after approval in chat), scheduled (a routine, with a policy for missing sources). A routine is switched on only after two runs look right.
- **Split by outcome, not by technology.** A new Bot is justified when the outcome, the sources, the tools, the schedule or the approval boundary changes.
- **Production and verification stay apart.** The Bot that built something never reviews it, the two do not share a conversation, and "done" needs a verdict from someone other than the worker.
- **A handover is not an approval.** Passing a draft to another Bot does not start work on it; the user approves a named version.
- **Failure has a name.** `BLOCKED` and `HOLD` replace guessing, and logs, test results and links are never invented.
- **Small rosters.** Start with a coordinator and one specialist, and add a role only when a concrete boundary calls for it.
- **The coordinator does not do the work.** It scopes, assigns and reviews. Long work goes to a specialist or a coding CLI.
- **Outbound and privileged actions wait.** Sending, posting, paying, merging and deploying stop at an approval.

## What this design takes

| Source idea | Here |
| --- | --- |
| A template is a profile pasted into a Bot | A built-in Agent: a complete configuration in `agent_registry/builtin_agents.py`, installed as an ordinary saved Agent |
| The contract: job, deliverable, never-list, done condition, working style, first task | The fixed shape of each job Agent's system prompt |
| Autonomy levels | Existing controls, with no new field; the mapping is in [Built-in Agents](../always-on-agents.md#built-in-agents) |
| Draft by default, never send | `hold_outbound` on and `autonomy: "report"` |
| A routine only after good runs | Always-on installed switched off, with a wake interval per Agent |
| Producer and verifier apart | PR Producer may edit; PR Verifier has no `edit`, `write` or `apply_patch`; each works in its own conversation |
| Bots hand work to each other | `handoff(to, message)` between conversations, with a hop limit |
| Scoped tools per role | A `selected` tool policy per Agent, built-in tools only |

Where each job Agent comes from:

| Built-in Agent | Source |
| --- | --- |
| Chief of Staff | The chief-of-staff role in grok-bot-architecture and the template of that name in grok-bot-templates |
| Spec Writer, Bug Reproducer, PR Producer, PR Verifier | The four profiles in grok-bot-profiles |
| Research Desk | The Research Desk template in grok-bot-templates |
| Inbox Triage | The Inbox Triage template in grok-bot-templates and the inbox role in grok-bot-architecture |
| Career Scout | The career role in grok-bot-architecture |
| Knowledge Keeper | The Memory and Capture Bots in grok-bot-second-brain |
| Writer | The publishing role in grok-bot-architecture and the drafting roles in agent-org-chart |

The role names and the contract shape are taken from these sources. The prompts are written for this product's tools and are not copies of the source profiles.

## What it leaves out

- **A template catalog, a picker and a readiness score.** The Agents list is the list of templates, and a new Agent starts blank.
- **Team objects, org-chart import and setup Bots that create a roster.** The user opens the conversations; the Agents hand work over between them.
- **Large rosters.** One Bot per vendor or per department is organising agents around the org chart. Anthropic's article [Building agents: when to fold subagents into your main agent loop](https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop) recommends one loop by default, splitting by context and not by problem type, and keeping a separate agent only where it measurably does better. The ten job Agents are separate configurations the user picks from, each with always-on switched off, not a team that runs together.
- **Coordinators that only route to a coding CLI.** An Agent here is itself the coding agent, so there is no thin layer to keep.
- **Domain packs.** Shopping, phone calls, trading, growth loops and opt-out procedures are skills and programs on top of an Agent, not Agents. Payments and trades are out of scope for a built-in.
- **A gateway and a queue over a hosted account.** Those exist because the product runs on a shared cloud computer; work here runs on the user's machine and is reached through the HTTP API and channels.
