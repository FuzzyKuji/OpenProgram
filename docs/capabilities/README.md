# Overview

This page answers one question: what OpenProgram can do, and which page covers each capability. Capabilities come in three layers: the programming paradigm, ready-made workflows, and extension mechanisms.

## The Agentic Programming paradigm

OpenProgram is built on Agentic Programming: **Python controls the flow, the LLM provides the reasoning**. You decompose a task into a function call graph — nodes that need no reasoning are plain Python, nodes that need understanding / generation / judgment are defined as an ordinary Agent method and call the model via `llm(...)` inside the function body. Execution order, state, and retries are ordinary code you can unit-test.

- [Agentic Programming guide](agentic-programming/README.md) — the learning path for writing functions and the three "choose the next step" mechanisms
- [Design philosophy](agentic-programming/philosophy.md) — what problem the paradigm solves and why it inverts control

## Agentic workflows: ready-made agents

Complete workflows written on top of the paradigm (called harnesses / agentic programs in the code), each a git repository you install with `openprogram programs install <source>`. Inspect their status and registered functions with `openprogram programs list`; the functions can be triggered as tools in chat or run directly with `openprogram programs run`.

- [Agentic workflows overview](workflows/README.md)
- [Installing programs](installing-programs.md) — installing a program from a directory, a git URL or GitHub `owner/repo`, and the directory contract for harnesses

## Extension mechanisms

Ways to extend the agent's capabilities without writing a harness:

- [Skills](skills.md) — the `SKILL.md` registry: domain knowledge and playbooks the model loads on demand
- [Commit, push, PR](commit-push-pr.md) — take finished work from the working tree to a reviewable pull request, with AI co-author attribution in `git log`
- [Plugins](plugins.md) — install plugins from pip / npm / git / local paths that contribute commands, skills, MCP servers, and more to the host
- [MCP](mcp.md) — connect any MCP server; its tools appear directly in chat
- [Built-in tools](tools.md) — the tools that ship with the framework (shell, files, web search, images, PDF, etc.) and the keys each one needs

- [Configure an Agent](agents.md) — models, instructions, capabilities, memory and independent trial conversations
