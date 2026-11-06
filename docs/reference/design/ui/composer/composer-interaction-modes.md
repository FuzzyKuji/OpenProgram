# Composer and user decision output

The composer edits ordinary messages and user-opened function forms. Pending runtime questions, confirmations, forms and approvals are separate session panels above the composer. Completed receipts appear in the conversation. A pending decision never replaces the composer, clears its draft, closes its function form, changes its send action, or takes its focus.

## Ordinary messages and function forms

The composer has two modes: `idle` and `fn-form`. Selecting a registered function opens `FunctionForm`; required fields and validation remain inside that form. Its transition, close action and outgoing-form animation belong to the composer. A pending decision does not cancel a function form.

A complete registered `name(parameter=literal, ...)` expression in ordinary input uses the same invocation dispatcher and schema validation as the form. Explanatory text, partial expressions and fenced code remain ordinary chat text. While execution is running, Enter and the send button add a normal message to the current turn (steer), and Cmd/Ctrl+Enter queues it for the next turn. Empty input retains the stop action.

## Decision output cards

`PendingDecisionPanels` renders session-scoped `PendingDecision` requests above each composer, including split panes. `DecisionOutputs` renders terminal receipts in the message stream. Each keyed card reuses `QuestionMode` for `ask`, `confirm`, `ask_many`, `form` and `approval`. Answer fields and submission controls are local to the card. New questions do not autofocus. Multiple questions remain independently addressable in stable presentation order.

Questions use the screenshot-defined current-question panel: progress, full-width option rows, descriptions and numeric shortcuts, visible Other input, Back, Next and final Submit. Next sends no command; Back preserves draft answers; final Submit sends the complete ordered answer list once. Forms retain their vertical field layout. Collapse and close only hide the body and retain the request. Skip declines the entire question request through the existing command. Forms submit field objects. Submitted receipts retain this question-and-answer layout, use field titles, and display readable values instead of JSON. Approval cards retain the available scopes, operation details and explicit allow/deny actions. Asking a question does not authorize an operation.

Submission immediately displays the actual answer and a sending state inside the card. Only a matching applied command confirms delivery. Unknown outcomes retain the original command identifier and payload for retry, show the available error code, and never imply success. Explicit rejections reconcile the current request before another answer. A closed request is not displayed as an accepted answer. Confirmed answers and declines remain as session UI receipts; the normal composer draft is unaffected.

Receipts are in-memory presentation state, not Workflow checkpoints. Refresh reloads canonical pending questions; this change does not add historical receipt persistence. Requests remain bound to their original session, execution, generation and version even when the user changes tabs.

## Discussion and events

An explicit discussion action retains its own feedback input. It sends the feedback as the reason on the exact canonical decline command. The model receives it within the same turn; no separate ordinary chat message is queued. Only a matching applied receipt confirms delivery, and an unconfirmed decline never authorizes execution. Ordinary composer messages do not implicitly decline a question or become its answer.

UI-only settings use direct store updates. A one-shot user action uses a correlated request and response. Runtime questions are broadcast events projected into the pending-decision store; command acknowledgement remains authoritative. Event arrival alone is not a receipt for the user's answer.

`question.asked` and reconnect snapshots supply canonical targets. `useWaitAnswer` submits execution commands and owns acknowledgement state; `QuestionMode` owns answer fields and navigation, with request-scoped in-memory drafts; `PendingDecisionPanels` owns pending placement and `DecisionOutputs` owns terminal receipts. Backend live Workflow questions continue in the original process. Existing predeclared Agent waits retain their continuation contract.

## Acceptance

Verify a pending question alongside a populated composer: the question is outside the composer, the draft and focus remain, and normal Send remains ordinary message submission. Click the card's submit button and verify immediate answer feedback, matching acknowledgement, retained receipt, unchanged composer draft, session isolation, retry identity and native App behavior.

See [user input requests](../../runtime/operations/user-input-requests.md) and [execution control](../../runtime/execution/control.html#decision-output).
