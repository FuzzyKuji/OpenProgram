/**
 * Map a legacy conversation payload (`conversations[id].messages`, the
 * shape `conversations.js` / `chat-ws.js` build) into the normalized
 * `ChatMsg[]` the React message store consumes.
 *
 * `renderSessionMessages` in `runtime-bridge/session/conversations.ts` feeds the
 * result into the store so it mirrors the loaded conversation.
 */
import { readPastedElements } from "../send/paste-elements.ts";
import { readNotice } from "./agent-notices.ts";
import { markRestartContinuations } from "./restart-continuation.ts";
import { normalizeCitations } from "./web-sources.ts";
import { chapterPinnedAt } from "./chapter.ts";
import type {
  AssistantBlock,
  ChatMsg,
  ChatToolCall,
} from "../../session-store";
import type { TurnFileSummary } from "../../session-store/types";

/** Same allowlist as the one in ``chat-stream.ts``. Hides any persisted
 *  agentic tool block on history reload so we don't show both the
 *  folded chat-tool card AND the standalone RuntimeBlock for one call. */
const AGENTIC_TOOL_NAMES: ReadonlySet<string> = new Set([
  "gui_agent",
]);

interface LegacyBlock {
  timestamp?: number;
  type?: string;
  text?: string;
  tool?: string;
  input?: string;
  result?: unknown;
  is_error?: boolean;
  outcome?: AssistantBlock["outcome"];
  tool_call_id?: string;
  truncated?: boolean;
  total_bytes?: number;
  message_id?: string;
  node_id?: string;
  /** tool: the model's provider ran the call (provider web search). */
  provider_executed?: boolean;
  /** text: the provider's citations for this text. */
  citations?: unknown;
}

interface LegacyAttempt {
  content?: string;
  timestamp?: number;
  tree?: unknown;
  usage?: unknown;
}

interface LegacyMsg {
  error_detail?: string;
  error_reason?: string;
  error_retryable?: boolean;
  error_retry_after_s?: number;
  /** Live reply rows: the stream position the row's content reflects. */
  stream_seq?: number;
  role?: string;
  content?: string;
  type?: string;
  function?: string | null;
  display?: string;
  blocks?: LegacyBlock[];
  id?: string;
  timestamp?: number;
  created_at?: number;
  kind?: string;
  slot?: string;
  summarised_count?: number;
  covers_ids?: string[];
  tokens_before?: number;
  tokens_after?: number;
  context_tree?: unknown;
  usage?: unknown;
  attempts?: LegacyAttempt[];
  current_attempt?: number;
  tool_calls?: LegacyBlock[];
  sibling_index?: number;
  sibling_total?: number;
  prev_sibling_id?: string;
  next_sibling_id?: string;
  /** Top-level field hoisted by ``_msg_adapter`` for assistant rows
   *  whose ``extra`` carried an ``attach`` blob. */
  attach?: AttachMeta;
  extra?: string | { attach?: AttachMeta; [k: string]: unknown };
  /** Which agent produced this turn — stamped by the dispatcher on
   *  both user and assistant rows. Same-session multi-agent uses
   *  this to colour / label each row by author. */
  agent_id?: string;
  goal_verification?: import("../decisions/goal-verification").GoalVerification;
  /** streaming-resume: lifecycle status persisted on the node.
   *  ``running`` means a producer is still writing this msg — render
   *  the runtime block in its in-progress state and (if the worker
   *  is reachable) subscribe for live updates. Missing == ``done``
   *  for backward compat with pre-streaming-resume sessions. */
  status?: "pending" | "running" | "streaming" | "done"
    | "completed" | "error" | "cancelled" | "cancelling" | "interrupted"
    | "paused";
  /** streaming-resume: when the placeholder reply was first written.
   *  Used by sweep to detect orphaned ``running`` rows. */
  started_at?: number;
  last_update_at?: number;
  /** Runtime ownership edge. Empty/ROOT means a top-level conversation
   *  run; an assistant id means the runtime belongs inside that reply. */
  caller?: string;
  /** Conversation-order edge only; it must not decide runtime ownership. */
  predecessor?: string;
  source?: string;
  steering?: boolean;
  turn_files?: TurnFileSummary;
  reverted?: boolean;
  /** User rows: the turn's chapter pin (``metadata.chapter``); null or
   *  absent when the turn is not pinned. */
  chapter?: { pinned_at?: number } | null;
}

export interface AttachMeta {
  session_id?: string;
  head_id?: string;
  commit_id?: string;
  label?: string;
  prompt?: string;
  /** True when the attach pointer was written by the user via the
   *  Branches → Attach to flow (rather than a /task spawn). The card
   *  uses this to surface the staged-reference UI. */
  manual?: boolean;
  /** Pinned source ContextCommit id — the snapshot the generator
   *  will expand into the next turn. Absent on legacy attach rows
   *  written before the expansion refactor. */
  source_commit_id?: string;
  /** Count of items in the pinned source commit (frontend renders
   *  this in the embed preview). Computed server-side. */
  embed_count?: number;
  /** Token sum across the source commit's items. */
  embed_tokens?: number;
  /** Async-job lifecycle status, written by the runner as the
   *  spawned sub-agent moves through pending → running →
   *  completed / errored / cancelled. The card uses it to show a
   *  live status pill so the user can tell whether the embedded
   *  content is still being filled in. */
  status?: "pending" | "queued" | "running" | "cancelling" | "completed"
    | "errored" | "cancelled";
  /** Cross-reference to the Job entity that produced this attach
   *  (when one exists — manual attaches don't have a job). */
  job_id?: string;
  execution_id?: string;
  status_version?: number;
}

function _readAttach(m: LegacyMsg): AttachMeta | undefined {
  if (m.attach && typeof m.attach === "object") return m.attach;
  const e = m.extra;
  if (e && typeof e === "object" && !Array.isArray(e)) {
    const a = (e as { attach?: AttachMeta }).attach;
    if (a && typeof a === "object") return a;
  }
  if (typeof e === "string" && e) {
    try {
      const parsed = JSON.parse(e);
      if (parsed && typeof parsed === "object" && parsed.attach) {
        return parsed.attach as AttachMeta;
      }
    } catch {
      /* ignore */
    }
  }
  return undefined;
}

/** One key of the message's ``extra`` blob (object or JSON string). */
/** The human sender a channel turn carries beside its text. */
function readSpeaker(m: LegacyMsg): ChatMsg["speaker"] {
  const row = m as { speaker_kind?: unknown; speaker_id?: unknown; speaker_display?: unknown };
  if (row.speaker_kind !== "human") return undefined;
  const id = typeof row.speaker_id === "string" && row.speaker_id ? row.speaker_id : undefined;
  const display = typeof row.speaker_display === "string" && row.speaker_display ? row.speaker_display : undefined;
  return id || display ? { id, display } : undefined;
}

function _readExtraField(m: LegacyMsg, key: string): unknown {
  const e = m.extra;
  if (e && typeof e === "object" && !Array.isArray(e)) return (e as Record<string, unknown>)[key];
  if (typeof e === "string" && e) {
    try {
      const parsed = JSON.parse(e);
      return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>)[key] : undefined;
    } catch {
      return undefined;
    }
  }
  return undefined;
}

/** Sibling-version fields shared by user + assistant turns. */
function siblingFields(m: LegacyMsg) {
  return {
    siblingIndex: m.sibling_index,
    siblingTotal: m.sibling_total,
    prevSiblingId: m.prev_sibling_id,
    nextSiblingId: m.next_sibling_id,
  };
}

export function convToChatMsgs(messages: LegacyMsg[]): ChatMsg[] {
  const out: ChatMsg[] = [];
  // Index assistant rows already emitted so we can attach LLM-issued
  // runtime-block children INSIDE the owning assistant bubble instead
  // of pushing them as standalone top-level rows. Built incrementally
  // as we walk `messages` in order — the backend splices the runtime
  // child immediately after its parent assistant in the chain, so by
  // the time we see the child, the parent is already in `out`.
  const assistantById = new Map<string, ChatMsg>();
  // ── caller 链 → 调用树（agent 调函数的层级结构） ──
  // agent 调用的函数执行持久化为一串 role=tool 行（gui_agent →
  // gui_step → … → LLM leaf），靠 caller 挂在发起回复上。把它们折成
  // TNode 形状的树喂给时间线（FunctionStep 递归渲染），这些行本身
  // 不再作为顶层消息渲染。
  const rawById = new Map<string, LegacyMsg>();
  messages.forEach((m) => { if (m.id) rawById.set(m.id, m); });
  const callerKids = new Map<string, LegacyMsg[]>();
  const inCallTree = new Set<string>();
  messages.forEach((m) => {
    const caller = (m as { caller?: string }).caller;
    if (!caller || caller === "ROOT" || !m.id) return;
    const parent = rawById.get(caller);
    if (!parent) return;
    const isToolRow = m.role === "tool" && !!m.function;
    const isLlmLeaf = m.role === "assistant" && parent.role === "tool";
    if (!isToolRow && !isLlmLeaf) return;
    const arr = callerKids.get(caller);
    if (arr) arr.push(m); else callerKids.set(caller, [m]);
    inCallTree.add(m.id);
  });
  function toCallNode(m: LegacyMsg): Record<string, unknown> {
    const kids = (callerKids.get(m.id || "") || []).map(toCallNode);
    const content = typeof m.content === "string" ? m.content : undefined;
    const isErr = m.status === "error"
      || (m as { is_error?: boolean }).is_error === true;
    return {
      path: m.id,
      name: m.role === "assistant" ? "LLM" : (m.function || "call"),
      status: m.status,
      output: content,
      error: isErr ? (content || "error") : undefined,
      duration_ms: (m as { duration_ms?: number }).duration_ms,
      children: kids.length ? kids : undefined,
    };
  }
  messages.forEach((m, i) => {
    // caller 链上的执行行已折进所属回复的调用树，不再顶层渲染。
    if (m.id && inCallTree.has(m.id)) return;
    // streaming-resume: a ``type: "status"`` row with display=runtime
    // is the runner's persisted reply (placeholder when running,
    // finalized when done). Either way it must render — the status
    // field drives the visual state (running spinner vs static
    // tree). Legacy non-runtime ``status`` rows (transient "Running
    // foo..." pings) are still hidden.
    const _isRuntimePlaceholder =
      m.type === "status" && m.display === "runtime";
    const _isRunningPlaceholder =
      _isRuntimePlaceholder && m.status === "running";
    if (m.type === "status" && !_isRuntimePlaceholder) return;
    const id = m.id || `hist_${i}`;
    const ts = m.timestamp || m.created_at;

    if (m.role === "user") {
      const sf = (m as { spawned_from?: { caller_id?: string; label?: string | null } }).spawned_from;
      out.push({
        id,
        role: "user",
        content: m.content || "",
        display: m.display === "runtime" ? "runtime" : undefined,
        status: "done",
        timestamp: ts,
        agentId: m.agent_id || undefined,
        source: typeof m.source === "string" ? m.source : undefined,
        notice: readNotice((m as { notice?: unknown }).notice),
        trigger: (m as { trigger?: unknown }).trigger === "restart" ? "restart" : undefined,
        speaker: readSpeaker(m),
        steering: m.steering === true,
        calledBy: typeof m.predecessor === "string" ? m.predecessor : undefined,
        pastedElements: readPastedElements(_readExtraField(m, "text_elements")),
        spawnedFrom: sf && sf.caller_id
          ? { callerId: sf.caller_id, label: sf.label || undefined }
          : undefined,
        chapterPinnedAt: chapterPinnedAt(m.chapter),
        ...siblingFields(m),
      });
      return;
    }

    // LLM-issued Agent method runtime-block placeholder: only `caller`
    // expresses ownership. `predecessor` is the conversation-order edge, so
    // a direct run may legitimately follow an assistant while staying top-level.
    if (_isRuntimePlaceholder && m.role === "assistant") {
      const calledBy = typeof m.caller === "string" && m.caller && m.caller !== "ROOT"
        ? m.caller
        : undefined;
      const parent = calledBy ? assistantById.get(calledBy) : undefined;
      if (parent) {
        const child: ChatMsg = {
          id,
          role: "assistant",
          content: m.content || "",
          function: m.function || undefined,
          display: "runtime",
          status: (() => {
            const _s = m.status;
            if (_s === "running" || _isRunningPlaceholder) return "running";
            // 持久化的 cancelling（取消宽限期中被 reload）等价 cancelled，
            // 落进 done 会把"正在取消"画成已完成。
            if (_s === "cancelled" || _s === "cancelling") return "cancelled";
            if (_s === "interrupted") return "interrupted";
            if (_s === "paused") return "paused";
            if (_s === "error") return "error";
            if (_s === "streaming") return "streaming";
            return m.type === "error" ? "error" : "done";
          })(),
          rawType: m.type,
          timestamp: ts,
          contextTree: (m.context_tree as never) || undefined,
          usage: m.usage,
          calledBy,
          agentId: m.agent_id || undefined,
        };
        parent.runtimeChildren = [...(parent.runtimeChildren ?? []), child];
        return;
      }
    }

    if (m.role === "assistant") {
      let thinking: string | undefined;
      const tools: ChatToolCall[] = [];
      // Backfill: pre-`blocks` messages only carry slim `tool_calls`.
      const rawBlocks =
        m.blocks && m.blocks.length
          ? m.blocks
          : (m.tool_calls || []).map((tc) => ({ type: "tool", ...tc }));
      // Ordered passthrough — the bubble renders block-by-block to
      // keep tool cards / agentic RuntimeBlocks at the spot in the
      // LLM output where they were called, instead of stacking all
      // tool cards at the bottom of the bubble.
      const orderedBlocks: AssistantBlock[] = [];
      rawBlocks.forEach((b, bi) => {
        if (b.type === "thinking" && b.text) {
          thinking = (thinking ?? "") + b.text;
          orderedBlocks.push({ type: "thinking", text: b.text });
        } else if (b.type === "text" && b.text) {
          const citations = normalizeCitations(b.citations);
          orderedBlocks.push(citations ? { type: "text", text: b.text, citations } : { type: "text", text: b.text });
        } else if (b.type === "steering" && b.message_id) {
          orderedBlocks.push({type: "steering", message_id: b.message_id, text: b.text, timestamp: b.timestamp});
        } else if (b.type === "tool") {
          const tid = b.tool_call_id || `${id}_t${bi}`;
          orderedBlocks.push({
            type: "tool",
            tool: b.tool || "?",
            tool_call_id: tid,
            input: b.input || "",
            result:
              b.result === undefined || b.result === null
                ? undefined
                : String(b.result),
            truncated: b.truncated === true,
            total_bytes: b.total_bytes,
            message_id: b.message_id,
            node_id: b.node_id,
            is_error: !!b.is_error,
            outcome: b.outcome,
            ...(b.provider_executed === true ? { provider_executed: true } : {}),
          });
          if (b.tool && AGENTIC_TOOL_NAMES.has(b.tool)) return;
          tools.push({
            id: tid,
            tool: b.tool || "?",
            input: b.input || "",
            result:
              b.result === undefined || b.result === null
                ? undefined
                : String(b.result),
            truncated: b.truncated === true,
            totalBytes: b.total_bytes,
            messageId: b.message_id,
            nodeId: b.node_id,
            isError: !!b.is_error,
            ...(b.provider_executed === true ? { providerExecuted: true } : {}),
            status: b.outcome === "cancelled"
              ? "cancelled"
              : b.outcome === "not_started" || b.outcome === "unknown" || b.is_error
                ? "error" : "done",
          });
        }
      });
      const failed = m.status === "error" || m.type === "error";
      // Older failed replies stored the error in content; their partial answer
      // survives in ordered text blocks. No history rewrite is needed.
      const errorDetail = m.error_detail ?? (failed ? m.content : undefined);
      const replyContent = failed && (!m.error_detail || m.content === m.error_detail)
        ? orderedBlocks.filter(b => b.type === "text").map(b => b.text || "").join("")
        : m.content || "";
      const asstMsg: ChatMsg = {
        id,
        role: "assistant",
        content: replyContent,
        errorDetail,
        errorReason: m.error_reason,
        errorRetryable: m.error_retryable,
        errorRetryAfterS: m.error_retry_after_s,
        ...(typeof m.stream_seq === "number" ? { streamSeq: m.stream_seq } : {}),
        thinking,
        tools: tools.length ? tools : undefined,
        blocks: orderedBlocks.length ? orderedBlocks : undefined,
        function: m.function || undefined,
        display: m.display === "runtime" ? "runtime" : undefined,
        status: (() => {
          // streaming-resume: respect the persisted status when it's
          // a recognised lifecycle value. Fall back to the legacy
          // type-derived rule so older rows (without a status meta
          // field) still render correctly.
          const _s = m.status;
          if (_s === "running" || _isRunningPlaceholder) return "running";
          // cancelling 在 reload 语义下就是 cancelled（见上）。
          if (_s === "cancelled" || _s === "cancelling") return "cancelled";
          if (_s === "interrupted") return "interrupted";
          if (_s === "paused") return "paused";
          if (_s === "error") return "error";
          if (_s === "streaming") return "streaming";
          return m.type === "error" ? "error" : "done";
        })(),
        rawType: m.type,
        goalVerification: m.goal_verification,
        timestamp: ts,
        contextTree: (m.context_tree as never) || undefined,
        usage: m.usage,
        turnFiles: m.turn_files,
        reverted: Boolean(m.reverted),
        attempts: m.attempts as never[] | undefined,
        current_attempt: m.current_attempt,
        attach: _readAttach(m),
        calledBy: typeof m.predecessor === "string" ? m.predecessor : undefined,
        agentId: m.agent_id || undefined,
        ...siblingFields(m),
      };
      // Spawned/attach 卡：锚定的调用轮是已输出的 assistant → 收进它的
      // attachCards，气泡内部按"工具调用之后"的位置渲染（在哪调用就画
      // 在哪）。锚不是 assistant（如 /task 斜杠路径锚在用户消息）时保持
      // 顶层行，由尾部调序放到锚后面。
      if (m.function === "attach" && asstMsg.calledBy) {
        const parent = assistantById.get(asstMsg.calledBy);
        if (parent) {
          parent.attachCards = [...(parent.attachCards ?? []), asstMsg];
          return;
        }
      }
      const callRootRows = (callerKids.get(id) || [])
        .filter((k) => k.role === "tool" && !!k.function);
      if (callRootRows.length) {
        asstMsg.callRoots = callRootRows.map(toCallNode);
      }
      out.push(asstMsg);
      assistantById.set(id, asstMsg);
      return;
    }

    if (m.role === "tool" && m.function) {
      out.push({
        id,
        role: "assistant",
        content: typeof m.content === "string" ? m.content : JSON.stringify(m.content),
        function: m.function || undefined,
        display: "runtime",
        status: m.status === "error"
          ? "error"
          : m.status === "paused" ? "paused" : "done",
        rawType: m.type,
        timestamp: ts,
        contextTree: (m.context_tree as never) || undefined,
        agentId: m.agent_id || undefined,
        ...siblingFields(m),
      });
      return;
    }
    const kind = m.kind === "compaction" || m.kind === "snip" || m.kind === "event"
      ? m.kind
      : undefined;
    out.push({
      id,
      role: "system",
      content: m.content || "",
      status: "done",
      timestamp: ts,
      kind,
      slot: m.slot === "card" || m.slot === "event" ? m.slot : undefined,
      summarisedCount: typeof m.summarised_count === "number"
        ? m.summarised_count
        : undefined,
      coversIds: Array.isArray(m.covers_ids) ? m.covers_ids.map(String) : undefined,
      tokensBefore: typeof m.tokens_before === "number" ? m.tokens_before : undefined,
      tokensAfter: typeof m.tokens_after === "number" ? m.tokens_after : undefined,
    });
  });
  // 顶层剩余的 attach 卡（锚在用户消息上的 /task 斜杠路径等）：搬到
  // 锚（调用点）的**紧后面**——命令在哪发出，卡就跟在哪。assistant 锚
  // 的卡已在上面收进气泡内部，不会走到这里。数据链不动（invariants
  // 规则 9），只调显示序。
  for (let i = 0; i < out.length; i++) {
    const card = out[i];
    if (card.role !== "assistant" || card.function !== "attach" || !card.calledBy) {
      continue;
    }
    const anchorIdx = out.findIndex((m) => m.id === card.calledBy);
    if (anchorIdx < 0) continue;
    if (anchorIdx === i - 1) continue; // 已经紧跟在调用点后面
    if (anchorIdx < i) {
      // 调用点在前 → 搬到它后面。移除后 anchorIdx 不变，插到 anchorIdx+1。
      out.splice(i, 1);
      out.splice(anchorIdx + 1, 0, card);
    } else {
      // 调用点在后（极少见）：先插到调用点后，再移除原位置。
      out.splice(anchorIdx + 1, 0, card);
      out.splice(i, 1);
      i--; // out[i] 现在是原 i+1，回退让循环重新检查
    }
  }
  // A steer is still an independent user node. Its presentation belongs at
  // the owning reply boundary; legacy records only identify the owner.
  const byId = new Map(out.map(m => [m.id, m]));
  for (const reply of out) {
    if (reply.role !== "assistant") continue;
    const marked = new Set((reply.blocks ?? []).filter(b => b.type === "steering").map(b => b.message_id));
    for (const id of marked) {
      const user = id ? byId.get(id) : undefined;
      if (user?.steering) user.steeringReplyId = reply.id;
    }
    const legacy: AssistantBlock[] = [];
    let predecessor = rawById.get(reply.id)?.predecessor;
    const visited = new Set<string>();
    while (predecessor && !visited.has(predecessor)) {
      visited.add(predecessor);
      const user = byId.get(predecessor);
      if (!user?.steering) break;
      user.steeringReplyId = reply.id;
      if (!marked.has(user.id)) legacy.unshift({type:"steering",message_id:user.id,text:user.content,timestamp:user.timestamp});
      predecessor = user.calledBy;
    }
    if (legacy.length) reply.blocks = [...legacy, ...(reply.blocks?.length ? reply.blocks : reply.content ? [{type:"text" as const,text:reply.content}] : [])];
  }
  markRestartContinuations(out);
  return out;
}
