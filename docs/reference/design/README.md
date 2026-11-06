# Design documentation

Find designs and implementation boundaries by subsystem. Start with the entries below, then expand the matching sidebar category for detailed designs, comparisons and related notes.


The sidebar starts with seven areas. Expand an area, choose a module, then open a page. Navigation expands the complete current path; filtering matches both page and category names.

## Reading order

1. Understand the system: [framework overview](framework-overview.md) → [repository structure](repository-structure.html).
2. Trace an execution: [call flow](runtime/execution/agent-call-flow.md) → [execution control](runtime/execution/control.html) → [session storage](runtime/session/storage.md).
3. Change a subsystem: choose a topic below, read its design and implementation-status appendix, then verify source ownership and acceptance requirements.

## Architecture

Understand the whole system, source ownership and implementation boundaries.

[Framework overview](framework-overview.md) · [Repository structure](repository-structure.html) · [Implementation navigation](implementation-status.html)

## Agents and workflows

Follow execution, session persistence, branching and recovery in that order.

[Execution control](runtime/execution/control.html) · [Session storage](runtime/session/storage.md) · [Session DAG](runtime/dag/overview.md) · [Goals and restart recovery](runtime/reliability/goal-and-recovery.html) · [Agent configuration](runtime/agent-configuration/agent-configuration-ui.html)

Understand function calls, workflow composition and application execution before the report examples.

[Function calling](function/calling-unification.md) · [Workflows](runtime/workflows/workflow.md) · [Program model](function/agentic-program.html) · [Application runtime](runtime/programs/application-runtime.html) · [Report workflows](runtime/workflows/report-suite.html)

Read the event contract before policies, proactive actions and scheduling.

[Event layer](proactive/event-layer.md) · [Rule execution](proactive/execution-model.md) · [Scheduling and memory](scheduler/memory-integration.html)

## Context and memory

Separate per-request context assembly from persistent memory and attribution.

[Context overview](context/overview.md) · [Context composition](context/composition.md) · [Compaction](context/compaction.md) · [Memory overview](memory/overview.md) · [Entity memory](memory/entity-memory-proposal.md)

## Interfaces

Start with state and interaction rules; then choose chat, browser, workspace, settings or terminal.

[UI overview](ui/README.md) · [State layer](ui/state-layer.md) · [Chat and composer](ui/composer/composer-interaction-modes.md) · [Built-in browser](ui/browser/built-in-browser.html) · [Project workspace](ui/workspace/project-workspace.md) · [CLI and TUI](cli/README.md)

## Models and connections

Keep request construction, model options, account resolution and failure handling distinct.

[Model catalog](providers/models/overview.md) · [Request building](providers/request-build.md) · [Account management](providers/auth/unified-account-management.md) · [Retry behavior](providers/reliability/error-retry.md) · [Usage metering](usage-metering.md)

Find harness, MCP, skills, plugin and channel contracts.

[Harness standard](integrations/harness-standard.md) · [MCP integration](integrations/mcp-integration.html) · [MCP server](integrations/mcp-server.html) · [Extension gating](extension-gating/README.md) · [Channels](channels/design.md)

## Security and engineering

Read execution authority separately from installation, updates and platform support.

[Authority and sandbox](runtime/security/sandbox-architecture.html) · [System access](runtime/security/system-access.html) · [Dependency security](security/dependency-security.html) · [Installation and packaging](distribution/installation-packaging.html) · [Automatic updates](distribution/automatic-updates.html)

Find shared verification rules, error handling and documentation maintenance.

[Test system](testing/test-system.html) · [Error handling](error-handling.md) · [Documentation structure and rendering](docs-site.html) · [Site discoverability](site-discoverability-performance.html)

## Supporting material

- **Prototypes**: layout and interaction experiments, not evidence of implemented behavior. They have their own sidebar category.
- **Implementation records**: migration steps, plans and discrepancies to verify. Read the corresponding current design first; historical records do not establish current implementation status.
- **Research**: exploratory proposals, threat analysis and evaluation notes, not product commitments.

## Maintenance rules

Every page has one sidebar category. Register new pages and their reading order in `scripts/docs_site/nav.py`; unclassified pages remain visible in an Uncategorized group. Category changes preserve page URLs.

Maintain one current design per topic. Diagrams, comparisons and implementation records should explain their relationship to that design without copying its body. Default sources are English with synchronized Chinese counterparts. See [documentation conventions](docs-site.html).

Documentation claims, source presence, passing tests, publication and installed-App acceptance are separate states. Categories do not indicate implementation completeness.
