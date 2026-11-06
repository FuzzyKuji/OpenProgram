# Overview

Each Markdown documentation page advertises its original source through a `text/markdown` alternate link. The documentation index is available at [index.html.md](https://openprogram.io/docs/index.html.md); [llms.txt](https://openprogram.io/llms.txt) lists entry points for automated readers.

<!-- Compatibility anchors for existing incoming links. -->
<a id="1-dag-context-for-native-multi-agent-systems"></a>
<a id="2-agentic-workflow-for-trustworthy-self-evolving-agents"></a>
<a id="3-event-infrastructure-for-proactive-agents"></a>

<a id="install"></a>
<a id="quick-start"></a>
<a id="news"></a>
<a id="why-openprogram"></a>
<a id="1-dag-context--for-native-multi-agent-systems"></a>
<a id="2-agentic-workflow--for-trustworthy--self-evolving-agents"></a>
<a id="3-event-infrastructure--for-proactive-agents"></a>
<a id="also-in-the-product"></a>
<a id="citation"></a>
<a id="license"></a>


<b>OpenProgram: Self-Programming AI Agent Framework</b>

Use this documentation to install OpenProgram, work with agents, configure services, or extend the framework. Choose a task below; each page has a Chinese counterpart in the language menu.

[English](README.md) · [Chinese](README.zh.md) · [Project introduction](https://github.com/FuzzyKuji/OpenProgram/blob/main/README.md) · [Releases](https://github.com/FuzzyKuji/OpenProgram/releases)

## First steps

1. [Install](install/install.md) the desktop app or CLI for your platform.
2. [Get started](start/GETTING_STARTED.md) with provider setup and a first conversation.
3. Learn [daily operations](start/daily-use.md) or consult [troubleshooting](start/faq.md).

## Documentation sections

| Section | What you can find |
|---|---|
| [Get started](start/GETTING_STARTED.md) | First conversation, daily use and common questions. |
| [Install](install/install.md) | Platform requirements, updates and removal. |
| [Capabilities](capabilities/README.md) | Tools, memory, goals, applications and reusable workflows. |
| [Interfaces](interfaces/README.md) | Desktop, browser and terminal interfaces. |
| [Models](models/README.md) | Providers, accounts, model selection and configuration. |
| [Integrations](integrations/anthropic.md) | External clients and chat channels. |
| [Server & Ops](server/README.md) | Remote access, deployment and service operations. |
| [Reference](reference/README.md) | Python APIs, CLI arguments, configuration keys and provider facts. |
| [Design](reference/design/README.md) | Current subsystem designs, constraints and implementation status. |

## Common tasks

- [Install programs](capabilities/installing-programs.md) from a directory, a git URL or GitHub `owner/repo`.
- [Write functions](capabilities/agentic-programming/writing-functions/agent.md) or [author workflows](capabilities/workflows/authoring.md).
- [Configure models](models/README.md) and [connect channels](integrations/channels.md).
- [Use memory](capabilities/memory.md) and [manage goals](capabilities/goal.md).
- Look up [global CLI flags](reference/cli/README.md), [configuration keys](reference/config-keys.md) or [provider settings](reference/provider-registry.md).

## Reading conventions

Navigation names are short topic labels. A page's full heading and introduction provide any additional scope. English and Chinese pages share the same topic and command identifiers. Generated references are rebuilt from the current parser, configuration schema and provider manifests.

Design pages explain engineering decisions and are maintained alongside code. Planned behavior is identified in their implementation-status sections. For procedures and supported commands, use the product guides and generated reference pages.

## Project information

See [related projects](reference/comparisons/related-projects.md), [framework comparison](reference/comparisons/ai-agent-frameworks.md), [programming principles](capabilities/agentic-programming/philosophy.md), and the [repository README](https://github.com/FuzzyKuji/OpenProgram/blob/main/README.md) for project background, examples, news, citation and license information.
