# Control tool permissions

Use the permission menu in Web or the installed App, or `/permissions` in the terminal. `Shift+Tab` cycles the terminal's ordinary modes. Bypass requires its existing explicit enable action.

| Mode | What proceeds automatically |
| --- | --- |
| Auto mode | Safe tools and operations accepted by the risk classifier. |
| Ask permissions | Safe read tools; other operations ask for approval. |
| Accept edits | Safe reads and supported edits inside working directories. Commands still ask. |
| Plan mode | Operations allowed by the read-only plan tool policy. |
| Bypass permissions | Ordinary operations without approval or risk classification. |

Bypass does not override explicit deny or ask rules, mandatory plan-exit or self-update approval, [messages an Agent sends for you](#messages-an-agent-sends-for-you), plugin restrictions, identity capabilities, or Sandbox.

Questions and approvals appear as independent cards in the conversation. Each question appears above its answer control. Multiple questions and form fields are listed together; fill them in and click Submit answers once. Submitted answers remain paired with their questions. The main message box remains available for ordinary messages. The card shows the submitted answer, delivery progress and a confirmation or retry state. Confirmed receipts remain visible until the page is reloaded; pending requests are restored on reconnect.

Tool approvals show the current operation and two actions: Allow once and Deny.
Clicking either submits that decision directly. The note button beside Deny
opens **Deny with a note**: write what the agent should do instead and send it
with Ctrl+Enter. The request closes only after
server confirmation; an unconfirmed answer can retry the same decision. A
confirmed approval leaves the conversation; the tool row shows what happened.
Deny does not end the task: the model receives the refusal as that tool's
result, the operation does not run, and the model is told to stop and ask you
how to proceed. With a note, the model receives your note instead and follows
it. Skipping a question likewise tells the model it went unanswered. Persistent rules remain available in History project settings.

Human tool approvals have no default time limit. Waiting saves execution progress
and releases the active execution attempt; reopening the App restores the pending
request. Resuming uses the context saved for that turn, so later memory or date updates do not invalidate the approval. Tool, permission and working-directory checks still apply. If execution cannot resume, the conversation reports that the pending operation did not run. Cancelling the task withdraws its approval. Expired older requests are not
reactivated and cannot authorize a new operation.

For `edit`, `write`, and `apply_patch`, approval records the target files' state.
Before executing and immediately before writing, the tools check that state.
A deleted target is not recreated with the old approval. Changed files require
reading the current contents before proposing another operation. The UI shows
only the current proposal, without a before/after history. Arbitrary shell
commands do not declare all their file targets, so this file-specific check does
not cover arbitrary command side effects.

Ordinary questions retain their answer controls and Discuss entry. What you write under Discuss goes to the model in place of an answer, and it responds to it within the same turn; the card keeps your text.

A new owner turn in Auto or Bypass does not inherit approval requirements solely from an unrelated earlier interrupted turn. Nested browser and Program calls use the same scope when their owner origin is verified. Unknown outcomes within the current execution still require exact approval; old operation records remain intact. This does not change macOS access or make a read-only volume writable.

## Messages an Agent sends for you

An Agent holds what it sends for you as a draft. A connected-service tool that sends, posts or replies (for example `send_email`, `chat.postMessage` or `create_comment` from an MCP server) asks for approval in every mode, Bypass included, and even when an allow rule names it. The approval card shows the full message. Allow once sends it; **Deny with a note** returns your changes, and the Agent writes a new draft that asks again. Each message is approved on its own and never becomes an allow rule. A background run, such as a scheduled prompt, has no one to ask, so it cannot send.

A tool counts as sending when its name starts with or contains a sending verb (send, reply, post, publish, forward, invite, share, comment) or creates a message, email, comment or post, and the server does not mark it read-only. Reads (`list_messages`, `get_posts`) and drafts (`create_draft`) do not ask.

The hold is on for every Agent. To let an Agent send under its ordinary permission mode, set `hold_outbound` to `false` in its configuration (`PATCH /api/agents/<id>` with `{"hold_outbound": false}`).

## Change permissions during a task

An existing session's selection is sent to the server and confirmed before the interface displays it as effective. The interface sends the change immediately when it already knows the confirmed session version. Once the server confirms Bypass, subsequent ordinary tool calls do not ask for approval, even if the model is still reasoning, streaming text or generating tool arguments. This also applies to later tools in the same response. You do not need to stop generation or send another message. The new mode is included in subsequent model requests; text already being generated is not rewritten. A tool already authorized for execution keeps that authorization. Switching into Plan mode prevents pending write calls from being authorized.

An ordinary approval that is no longer required is automatically resolved through the execution's durable wait and the task continues. Explicit ask rules, mandatory approvals, user questions, forms, and Sandbox escalation are not answered by changing the mode. Repeated answers, cancellation, timeout, and recovery cannot execute an already completed call again.

Changes are session-specific. Other windows receive the confirmed mode; stale updates are rejected rather than overwriting a newer choice. A failed or disconnected update remains unconfirmed. Reconnect and review the current mode before retrying. An unsent draft stores its mode locally and sends it with the first message.

The effective default is the session override, then the project default, then Auto mode. A sub-agent created by an authenticated owner Agent inherits the parent’s effective permission mode and explicit rules at creation. For example, a parent using Bypass can create a sub-agent that runs ordinary commands without approval. The sub-agent keeps its own identity and non-interactive restrictions; explicit ask rules and mandatory approvals still prevent operations that require an approver. Later mode changes do not rewrite already admitted sub-agents. Independent scheduled tasks do not acquire owner permissions or Bypass from a local session. A chat channel account acts as the owner by default (setting `sender_access`, see [Chat channels](../integrations/channels.md)): its turns use the chat session's own permission mode and rules, approvals arrive in the chat and are answered with `/answer`, and group chats run sandboxed.

## Manage project rules in History

Open History → Projects, select the project, and open Settings → Permission Rules. The three lists contain that project's Deny, Ask and Allow rules. Add a rule with `ToolName` or `ToolName(pattern)` syntax; remove an existing rule to revoke it. To change a rule, remove the old entry and add its replacement. Deny takes precedence over Ask, which takes precedence over Allow. Session and global rules can still affect the result even when the project list is empty.

The interface waits for a project-specific server confirmation before clearing a submitted rule. Failed or unconfirmed saves preserve the input and show a status message. Successful changes update other open views of that project. The next operation in an authenticated interactive owner session reads the current rules, including changes made during a running turn. Already authorized operations retain their authorization; existing approval waits still require their own answer. Already admitted sub-agents retain their captured policy.

Allow once and Deny answer only the current request; they do not create project rules. Removing a saved project rule affects future authorization, not the historical result of an operation that already ran.

## Understand a refusal

For Windows path rules, forward slashes avoid escaping ambiguity: for example,
`read(C:/Users/me/project/**)`. Ordinary backslashes in drive paths are preserved;
the rule syntax still uses `\\`, `\(`, and `\)` to escape its own special characters.
JSON configuration additionally requires JSON's normal backslash escaping.

A tool result identifies whether the refusal came from authority, a permission rule, Plan mode, Auto classification, or Sandbox. `AUTHORITY_TIER_MISSING` means the execution request lacks an authenticated authority tier. It is not resolved by Bypass. New authenticated chat submissions carry that identity; old admitted executions missing identity must be resubmitted through an authenticated interface.

Sandbox is off by default and is turned on per conversation in the composer Plus menu; `sandbox.mode` set to `auto` turns it on in every conversation where its backend is available, and `workspace-write` requires it. Changing Sandbox affects subsequent turns. A sandboxed command has no network unless `sandbox.network` is on, and writes only the workspace.

When a command needs more, such as `git push`, `gh`, a package install or a write outside the workspace, the Agent calls `bash` with `sandbox_permissions="require_escalated"` and a one-sentence justification. Before the command runs, an approval card shows the command and the reason. **Allow** runs it once outside the sandbox; protected application paths and credential filtering still apply. **Allow this conversation** lets the same command leave the sandbox again in this conversation without asking. A command that the sandbox blocks after it ran, including a failed name lookup, returns that explanation to the Agent so it can ask this way instead of retrying. Bypass keeps the sandbox and refuses these requests, and an ordinary tool approval never authorizes one.

See [tools](tools.md), [Web](../interfaces/web.md), [terminal](../interfaces/tui.md), and the [engineering contract](../reference/design/runtime/security/sandbox-architecture.html).

## macOS asks for access again after an update

File-folder access, Photos, screen recording, and Accessibility are macOS permissions. Bypass controls tool approval and cannot grant these permissions. The desktop App and its named backend are signed applications. macOS can maintain separate permission records for them; enabling a similarly named entry does not prove that the executing backend has access.

Local App refresh, local package installation, and conversational self-update reuse a private signing identity stored under `~/Library/Application Support/OpenProgram/local-signing`. This keeps subsequent local builds under the same certificate identity instead of changing it with every build. Keep this directory when cleaning build artifacts; it contains the local signing keychain. Missing or damaged signing state stops the build rather than silently creating a replacement identity.

The first migration from an older ad hoc build may require consent again in macOS. An old permission can still appear enabled while macOS rejects the updated signature. System access checks the current executor rather than trusting the Settings toggle. Use Request authorization to invoke native consent. Opening System Settings is a separate action; Accessibility and previously denied permissions may require that interface. When a recorded successful grant belongs to an older verified signing identity, explicit authorization setup renews only that OpenProgram capability once. Startup and ordinary checks never reset grants or accept system dialogs. Local signing is for this computer's development builds; publicly distributed apps still need Developer ID signing and notarization.

Auto mode reviews the complete operation before dispatch, including shell commands. Review input is bounded to 64 KiB; oversized input or an unavailable classifier fails closed rather than approving a truncated prefix. Each model candidate has a 30-second timeout. A review is invalidated when its arguments or live permission policy change. Explicit deny rules and mandatory approvals retain precedence.

Repeated Auto risk refusals use the existing approval flow for an authenticated interactive owner: three consecutive or twenty cumulative refusals offer approval for that exact operation. Explicit deny rules and hard restrictions still apply. Counts belong to the session and permission version; changing the permission version starts a fresh count. An allowed or approved operation resets the consecutive count; approval after the cumulative threshold also resets the total. Classifier outages, invalid responses and cancellation are not risk refusals. Durable operation identities prevent double counting after resume; concurrent updates use the execution database transaction. Noninteractive tasks receive a refusal and may continue other allowed work. Fallback approval is one operation only, with the original arguments, working directory, permission version and file preconditions.

Automatic risk refusals do not consume the repeated execution-failure limit, so repeating the same refused operation can still reach manual approval. Approval after the cumulative threshold resets that total. Completed and refused operations retain their host-recorded outcome when a checkpoint must be recovered.

## Host capabilities use one setup path

The execution host exposes one registry of capabilities. It currently describes screen recording, Accessibility, Automation, Calendar, Reminders, file read/write, microphone, and camera. Each row includes its status, the identity being checked, the operation that needs it, and whether the platform can request it. Settings, the CLI/TUI doctor, GUI preflight, durable system-access waits, and the HTTP endpoint read this same registry.

`GET /api/system/access` only performs non-prompting checks. In the installed App, open Settings → System access to review the grouped rows. `Set up all OpenProgram access` is the one explicit first-run action for the registered native runtime capabilities; it returns one consolidated report. `Request authorization` and `Open System Settings` remain available for an individual row. These actions require an explicit click from the local owner. Reconnects, polling, history replay, model output, startup checks, and ordinary retries never open a native prompt. A missing capability pauses only the operation that declares it; browser, VM, headless and ordinary chat operations do not inherit the desktop requirement.

The status values have different meanings: `granted` is a fresh check by the current named executor; `not_granted` is a confirmed missing grant; `unknown` means the host could not prove the state; `unavailable` means the native dependency is missing; and `unsupported` means that backend has no implementation. `unknown` and `unavailable` are not treated as permission denials.

Automation is target-specific, and file access is scoped to the selected path. Calendar, Reminders, microphone, and camera can require their own macOS consent. The product cannot pre-authorize an application it has not targeted or a path the user has not selected. Enabling a similarly named `python3`, `node`, or cached application entry is not evidence that the managed OpenProgram executor is authorized. All native checks and requests from an installed product use the signed runtime bundle identity `ai.openprogram.runtime`; the outer App is not a second native executor. Ordinary checks never reset TCC records or modify another application.

## Explain and test permission rules

`openprogram permissions check` evaluates a supplied JSON rule file without executing the proposed tool:

```sh
openprogram permissions check --rules rules.json --tool bash --args '{"command":"git status"}' --expect allow
openprogram permissions test --rules rules.json --cases cases.json
```

The rule file contains `allow`, `ask`, and `deny` arrays, for example:

```json
{"allow":["bash(git:*)"],"ask":[],"deny":["bash(rm:*)"]}
```

A cases file is a nonempty array of objects containing `tool`, `args`, and `expected`:

```json
[{"tool":"bash","args":{"command":"git status"},"expected":"allow"}]
```

JSON output lists matching rules in enforcement order: deny, ask, then allow. `unmatched` means no supplied rule applies. Exit status is 0 for a matching expectation, 1 for a mismatch, and 2 for invalid input. Without `--expect`, `check` reports any valid decision with status 0. These commands inspect only the supplied rules: they do not merge live session configuration, run the risk classifier, approve a tool, or bypass hard restrictions and the OS sandbox.

## Restrict sandbox commands to public network domains

On macOS, set `sandbox.network` to `true` and `sandbox.network_domains` to a JSON map:

```json
{"example.com":"allow","*.example.org":"allow","blocked.example.org":"deny"}
```

Exact hosts and `*.example.org` (subdomains at any depth, excluding the root) are supported. Deny wins. An empty map blocks every destination; `null` preserves the existing network switch. Private, local, multicast, and reserved IP addresses stay blocked, even when a hostname is allowed. All DNS answers are checked, and the connection uses a checked address directly.

Each command receives an authenticated local proxy. The macOS sandbox prevents direct connections, including clients that ignore proxy settings. HTTP on port 80 and HTTPS CONNECT on port 443 are supported; clients must support ordinary HTTP proxy settings. Domain rules authorize destination connections, not encrypted HTTPS methods or contents. There is no TLS interception, SOCKS/UDP, arbitrary-port forwarding, local-network access, or upstream proxy chaining. Chunked HTTP uploads and plain HTTP Upgrade are unsupported; HTTPS tunnels carry ordinary HTTPS and WSS traffic.

The proxy and active connections close when the command ends or is cancelled. Linux and Windows/WSL currently reject a configured active domain policy instead of running with unrestricted networking. A missing sandbox also rejects domain-restricted execution even when the ordinary unavailable policy is `warn`. Turning Sandbox off explicitly still disables its restrictions. These settings affect sandboxed commands, not the host's model-provider requests or every other tool transport.

## Interrupted operations

A new interactive owner turn uses its selected Auto or Bypass mode even when an older turn has an unknown external result. Old effects remain recorded as unknown and are not replayed. Resuming the same interrupted execution still requires reconciliation or exact approval. Explicit deny/ask rules and mandatory approvals continue to apply.

When offered, **Always allow** saves the exact supported operation rule in the current project. **Allow this conversation** saves the same rule in the current session only, so later calls in this conversation run without asking while other sessions still ask; today it is offered for [`computer_use_agent`](computer-use.md#approval), where the rule names the application or the virtual machine. One-shot-only requests do not offer persistent approval; a browser [`evaluate`](computer-use.md#web-pages) call is one, and it asks in every mode, Bypass included.

Stop interrupts pending model and asynchronous tool work. Once the producer exits, the turn is stopped even if an external operation has an unknown outcome; that outcome remains visible in Activity. Pause instead waits for the current operation to reach a resumable boundary. The interface reports the pending request; use Stop when an immediate interruption is needed.
