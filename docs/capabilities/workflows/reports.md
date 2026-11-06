# Prepare weekly reports

Personal-chat and Feishu draft requests return the full Markdown body by default. They do not need a successful local file write. An explicitly requested Markdown output path retains file delivery; existing file-delivery resume requests remain supported. Returning text does not submit or send anything externally.

The report suite consists of four independently versioned Workflow packages and
one coordinating `weekly_report` package. They live in `~/.openprogram/programs`;
this source checkout does not include them. The suite supports independent execution and composition through the `weekly_report` entry.
Native WeChat collection depends on accessible search and conversation controls;
the group Workflow records unavailable controls and continues with local evidence, producing an explicitly partial draft.

| Entry | Purpose | External writes |
| --- | --- | --- |
| `personal_weekly_report(task)` | Personal Feishu drafts, inspection, filling, submission and record updates | Filling changes form fields without saving; submission/update requires an explicit request |
| `personal_chat_weekly_report(task)` | Owner's three-section WeChat-group copy (weekly progress, discussion topics, and next-week plans; rendered in Chinese) | Local draft only; never sends WeChat |
| `group_weekly_report(task)` | Collect group reports, track missing members, and prepare a local summary | Never sends WeChat messages |
| `tencent_weekly_report(task)` | Approximately 100 Chinese characters of Tencent progress for a leader, intended for Friday afternoon | Local draft only |
| `weekly_report(task)` | An agent selects the requested report Workflows and forwards the complete request | Preserves the requested operation; child write restrictions apply |

## Prepare a Tencent report from existing records

Select `tencent_weekly_report` in Abilities and enter `Prepare this week's Tencent
weekly_report`. The Workflow uses the current ISO week in Asia/Shanghai. It first reuses
original current-week Tencent evidence in the workspace's `reports` directory,
then considers other report sources, original owner messages from recent OpenProgram
sessions and dated OpenProgram memory. Conversation candidates retain their actual
message date and session/message reference; assistant drafts and unattributed
messages are excluded. A dated request or plan remains a candidate, not proof of
completed work. Explicit
materials take precedence. Records from other weeks, uncertain month/year-only
dates, pending memory records, untrusted raw memory sources and explicit test records are excluded. Generated memory notes can remain lookup candidates; they are not independently verified owner facts. Other audiences
require source selection with exact quotes; they are not automatically treated
as Tencent work. Conversation discovery reads at most 20 recent sessions and the last 200 messages per session; combined candidate context is limited to 30 records and 18,000 UTF-8 bytes. Unavailable or insufficient sources require clarification within that inspected scope; this does not establish that no relevant work exists elsewhere. Optional `report_roots` selects up to five source
directories.

Successful Tencent and `weekly_report` calls return the report body directly. Sources,
character count and model-call information remain in local draft files. For
programmatic composition, pass `"result_format": "structured"` in the JSON task;
this returns the status, artifact paths and recovery object. The router forwards explicitly supplied child options unchanged. Generation and verification use low reasoning effort,
a 180-second per-call limit and preserved retry budgets. Model failures do not
produce a success draft.

## Prepare several reports

Select `weekly_report` in Abilities and supply a JSON string as `task`:

```json
{
  "requests": {
    "personal": {
      "week": "2026-W37",
      "materials": [{"id": "p1", "week": "2026-W37", "text": "Experiments remain in progress; next week we will check the results."}]
    },
    "tencent": {
      "week": "2026-W37",
      "materials": [{"id": "t1", "week": "2026-W37", "text": "Tencent evaluation is still in progress. No final performance conclusion is available."}]
    }
  }
}
```

Materials are separate by audience. Personal and Tencent structured inputs require
matching ISO weeks and unique source IDs. Insufficient evidence returns a request
for input or review instead of inventing progress. Model-assisted semantic checks
can detect unsupported claims but are not a guarantee of factual correctness.

For a group report, a request such as `Prepare the group report` is enough to start discovery. The Workflow retrieves missing group identity, roster, current materials and author evidence from memory, relevant local records and the identified WeChat group. It preserves supplied report bodies and does not ask for missing fields. With no reporting period specified, it uses the current ISO week and records that assumption. Unresolved authors remain visibly unverified; unavailable or insufficient evidence produces a partial draft with source diagnostics, never invented progress.

The default source is `auto`. Explicit `source: "supplied"` restricts the run to supplied materials. Native collection verifies the group and retains source evidence; historical coverage remains partial. It cannot send messages or change system permissions. If WeChat access fails, relevant local sources remain available. Model and provider failures retain their actual execution errors rather than being classified as missing user input.

Routing, group request parsing, and personal report model calls inherit the
Runtime timeout (`OPENPROGRAM_EXEC_TIMEOUT_S`); they impose no separate 90-second
limit. External record updates are not automatically repeated after an uncertain
failure.

Natural-language requests are interpreted by a routing agent. It selects one,
two, three, or all four destinations according to meaning and negation, then code
passes the entire original request unchanged to each selected Workflow. It does
not split on punctuation, extract materials, force drafts, or assign a common
week. A generic personal progress draft without Feishu language is
`personal_chat`, not the Feishu form. An unspecified audience defaults to the unsent personal-chat draft; routing does not ask for clarification.
Single results are returned verbatim; multiple results are labeled by audience.

## Continue incomplete work

The router owns no shared checkpoint. Continue through the relevant child using
that child's recovery instructions. Old coordinator resume payloads are rejected
with guidance to use the child entry. Explicit `requests` JSON addresses children
directly and preserves their options without routing-model inference.

Local delivery failures retain prepared content for retry. Tencent model failures
retain generation and verification budgets across resumes. Checkpoints and retry
payloads contain private report content and should remain local.

## Friday afternoon Tencent report

The Tencent Workflow targets 80–120 non-whitespace characters, aiming for 100.
Its intended reporting window is Friday afternoon in `Asia/Shanghai`. It does not
create a recurring schedule or send to the leader. An exact execution time and
material source must be configured separately before enabling a scheduled run.

## Source organization

The five independent report Workflow packages live side by side in `~/.openprogram/programs/`: `personal_weekly_report` (Feishu), `personal_chat_weekly_report` (owner's WeChat-group copy), `group_weekly_report` (group collection), `tencent_weekly_report` (Tencent), and `weekly_report` (routing). Shared helpers come from `openprogram.programs._authoring.reports`. The coordinator `weekly_report` imports the other four packages directly. Configured output paths are unchanged.

Personal field generation uses a read-only Agent with `list_agents(scope="all")` and
`read_conversation` to retrieve work from other sessions, alongside memory and
original local notes. Conversation turns expose original UTC timestamps; the
default reporting period is the current ISO week in `Asia/Shanghai` when no
period is supplied. Recent session activity does not make older turns current-week
evidence. Requests, plans, generated drafts and README descriptions do not prove
completed work. The Agent must preserve failed or incomplete work and state
missing evidence rather than invent results. A JSON Schema validates complete fields or sparse edits, with prompt fallback and the existing format-repair attempt before any write. The Feishu Workflow propagates unresolved model failures as errors. An uncertain remote write is a non-retryable failure; inspect the actual record before another attempt.

Natural personal and personal-chat composition binds each retained report item to an actual original owner statement or operational tool result, with an exact source ID and visible quote. Memory, local files and assistant summaries provide search leads; their narrative alone cannot establish completed work. Current supplied owner facts must match the actual owner input. They may explicitly describe a previous period after independent temporal verification; their actual input date remains unchanged. Each audience resolves its own reporting week from the complete request, so another report's period does not override it. Structured personal-report inputs use the same original-source binding before their material-specific verification. A unique explicit ISO week in the complete request is retained; requests assigning different periods to different audiences are resolved separately. Automatic original-source discovery lists up to 100 recent sessions and reads up to 10 branches, preferring project titles mentioned in the request. The sources retain the original message date, tool operation, arguments, status and error flag. Missing originals return `NEEDS_INPUT`; unsupported references or semantic claims return `NEEDS_REVIEW` before draft delivery or form writing. Independent semantic verification checks every item and the requested reporting week; it does not guarantee factual correctness. Identity defaults, explicit clearing and absent optional content do not create research claims.

Structured Agents count normal tool rounds against `max_iterations`, not the failed-request allowance. A completed tool round preserves the remaining retry allowance; format repairs and failed requests still share it. Reaching the iteration limit stops execution without replaying completed tools.

Read-only memory search, grep, get and browse use the normal safe-tool policy; explicit deny/ask rules and `memory.read` authority still apply. Personal operation selection and evidence verification, plus every Tencent JSON-producing stage, declare output schemas and reuse Runtime format repair. Personal Feishu format failures propagate as errors; Tencent preserves the typed model failure and its resume task. Neither is treated as missing user input. Tencent request interpretation inherits the deployment timeout.

## Fill the personal Feishu form without submitting

Select `personal_weekly_report` and request `Fill the personal Feishu weekly report without submitting`. The Workflow checks the current records, prepares the six fields, fills them and obtains a fresh field-by-field readback. `FILLED` means the fields were checked and no submission or save was performed. `SUBMITTED` is a separate result that requires an explicit submission request.

Fill-only mode supports a new form only after inspection establishes that no record exists. Existing records and capped forms return `BLOCKED`; they are not duplicated. This mode permits the observed records navigation and the exact requested textbox values, and rejects submission/save clicks, keypresses, coordinates and stale observations before browser execution. Missing or ambiguous field identities, truncated or redacted values, failed actions and uncertain write outcomes cannot produce `FILLED`; uncertain writes are not automatically repeated.

Readback requires complete actual field values and compares them exactly, including line breaks and repeated spaces. ARIA text alone cannot establish successful filling; browser schemas without actual values cannot return `FILLED`. The native browser backend supports ordinary form labels and unique visible labels around contenteditable fields. Missing or ambiguous labels stop filling before a field write. Browser access and discoverable field labels remain prerequisites for filling.

## Feishu browser failures

Feishu inspection and writing expose only `web_use`, using its current `command` schema. They require real tool receipts before accepting an observation or reporting a write. Quoted tool calls in model text are not browser actions. These stages have no hard-coded aggregate timeout or tool-round limit; explicit Runtime deployment limits still apply. Browser access failures propagate through the coordinator instead of being returned as successful text. If a later child fails, the original exception retains earlier completed child results; the coordinator does not automatically rerun them.

Submission and update use the same exact field binding and fresh field readback as filling. A submit request encountering an existing record returns its inspection result; modifying it requires an explicit update request. The final submission/save attempt is recorded before dispatch, so an uncertain result cannot automatically repeat that click. Empty five-dimension placeholders are not report progress.
