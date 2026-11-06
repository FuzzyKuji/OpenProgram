"use client";

/**
 * Activity: what the conversation runs and keeps doing. Agents holds the
 * main agent, one per branch the reader made, each with its sub-agents
 * summed up; a main agent's page lists those sub-agents as a tree under
 * the agent that started each or newest first, with a menu that filters
 * and arranges it, and an agent waiting for the reader stays in place with
 * a warning status. Programs and commands holds the shell calls and
 * background programs. Then what the conversation does on its own: its
 * always-on wakes (when its Agent is configured for them), its open work
 * and the Scheduler tasks set from it. Each row opens a page and the arrow
 * at the top goes back one level. Each overview section folds to its header,
 * like the sidebar's, and stays folded in this browser. Nothing else expands in place.
 */
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "@/lib/i18n";
import { useSessionStore } from "@/lib/session-store";
import { useExecutionDebugger } from "@/lib/execution/use-execution-debugger";
import { useManagedProcesses } from "@/lib/execution/use-managed-processes";
import { processIsActive, stopProcess, type ActiveToolCall, type AgentCall, type ManagedProcess } from "@/lib/net/execution/process-client";
import { type ExecutionSnapshot } from "@/lib/execution/execution-debugger";
import { activityModel, agentBranches, pruneBranches, spawnedBy, startedAt, type ActivityIssue, type BranchRow } from "@/lib/execution/activity-model";
import { toggleActivitySection, useActivityView } from "@/lib/prefs/activity-view";
import { loadSubAgentTranscript } from "@/lib/chat/transcript/sub-agent-transcripts";
import { sendRuntimeCommand } from "@/lib/runtime-bridge/session/session-load";
import { presentTool } from "@/components/chat/messages/execution/tool-presentation";
import { SectionHeader } from "@/components/sidebar/sessions/section-header";
import { Button } from "@/components/ui/button";
import { AgentsViewMenu } from "../agents-view-menu";
import { DebuggerPanel } from "../debugger/debugger-panel";
import { SidebarNotice } from "../sidebar-notice";
import { useConversationBranches } from "../use-conversation-branches";
import { executionTitle, updatedTime } from "../debugger/debugger-presentation";
import { removeOpenWork, setOpenWorkStatus, useConversationWork, wakeConversation, type OpenWorkItem, type Routine } from "@/lib/chat/conversation-work";
import { AgentAvatarById, useConversationAgentShape } from "@/components/agents/agent-avatar";
import { subAgentShape } from "@/lib/runtime-bridge/dag/render/agent-look";
import { deliveryLabel, goalStatusLabel, outcomeLabel, scheduleLabel } from "@/components/agents/always-on-labels";
import { copyText } from "@/lib/clipboard";
import { navigate } from "@/lib/nav/navigate";
import { clock, ProgramOutput, ProgressBar, progressLook } from "./program-progress";
import styles from "./running-panel.module.css";
import { Glyph, AgentGlyph, RunGlyph, Status, Row, Long, type Tone, type Line } from "./running-rows";
import { LIVE, duration, when, callKind, executionTone, executionState, programState, programTone, programName, programTitle, commandLine, programStatus, programBarTone, spawnState, routineSchedule } from "./running-format";

type View = { kind: "main" | "run" | "call" | "spawn" | "program" | "always" | "work" | "routine"; id: string };

const PAGE = 20;

export function RunningPanel({ active, sessionId }: { active: boolean; sessionId: string | null }) {
  const { text } = useTranslation();
  const [stack, setStack] = useState<View[]>([]);
  const view = stack.at(-1) ?? null;
  // A run's page carries its record (events, waits, drafts), so the
  // inspector reads them only while one is open.
  const state = useExecutionDebugger(active, sessionId, undefined, view?.kind === "run");
  const processes = useManagedProcesses(active, sessionId, view?.kind === "program" ? view.id : null);
  const { work: ongoing, refresh: refreshOngoing } = useConversationWork(active, sessionId);
  const [copied, setCopied] = useState<string | null>(null);
  const conversationTitle = useSessionStore(s => (sessionId ? s.conversations[sessionId]?.title : undefined) || "");
  // The main agent's rows wear the conversation Agent's character.
  const mainShape = useConversationAgentShape(sessionId);
  // Questions and approvals are answered in the chat's input box, which
  // shows each one with its choices; Activity says what is asked and goes there.
  const allDecisions = useSessionStore(s => s.pendingDecisions);
  const listView = useActivityView();
  const conversationBranches = useConversationBranches(sessionId);
  const [shown, setShown] = useState(PAGE);
  const [programsShown, setProgramsShown] = useState(PAGE);
  const [taskOpen, setTaskOpen] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  useEffect(() => { setStack([]); setShown(PAGE); setProgramsShown(PAGE); }, [sessionId]);
  useEffect(() => { setShown(PAGE); }, [listView.show, listView.arrange]);
  useEffect(() => { setTaskOpen(false); setActionError(null); }, [view?.kind, view?.id]);
  const selectExecution = state.selectExecution;
  const selectedExecutionId = state.selectedExecutionId;
  // Select once per run page. `selectExecution` is rebuilt on every
  // refresh, and re-selecting resets the inspector to "reconnecting"
  // and drops its events, so an unconditional call would clear the
  // progress list each time the list polled.
  useEffect(() => {
    if (view?.kind === "run" && selectedExecutionId !== view.id) selectExecution(view.id);
  }, [view?.kind, view?.id, selectedExecutionId, selectExecution]);

  const readFailed = processes.stale || (
    state.connection.errorSessionId === sessionId && Boolean(state.connection.message)
    && ["stale", "conflict"].includes(state.connection.state)
  );
  const hasRead = Boolean(state.fetchedAt) || processes.loaded;
  const [readNotice, setReadNotice] = useState<{ sessionId: string | null; persistent: boolean } | null>(null);
  useEffect(() => {
    setReadNotice(null);
    if (!active || !readFailed) return;
    const retry = setTimeout(() => setReadNotice({ sessionId, persistent: false }), 5000);
    const persistent = setTimeout(() => setReadNotice({ sessionId, persistent: true }), 30000);
    return () => { clearTimeout(retry); clearTimeout(persistent); };
  }, [active, sessionId, readFailed]);

  if (!sessionId) return <SidebarNotice>{text("Select or start a conversation to view what it runs.", "选择或开始一个会话，查看它运行的内容。")}</SidebarNotice>;

  // Until the executions are read every call and program would look unowned.
  const executions = state.fetchedAt ? state.executions : [];
  const calls = state.fetchedAt ? processes.calls || [] : [];
  const spawns = state.fetchedAt ? processes.spawns || [] : [];
  const model = activityModel(executions, processes.items, calls);
  const branches = agentBranches(executions);
  const now = Date.now() / 1000;
  const open = (next: View) => setStack(previous => [...previous, next]);
  const openRun = (executionId: string) => open({ kind: "run", id: executionId });
  const execution = (id: string) => executions.find(item => item.execution_id === id) ?? null;
  const call = (id: string) => calls.find(item => item.id === id) ?? null;
  const spawn = (id: string) => spawns.find(item => item.id === id) ?? null;
  const program = (id: string) => processes.items.find(item => item.id === id) ?? null;
  const runTitle = (item: ExecutionSnapshot) => executionTitle(item, 1, text);
  const isAgent = (item: ExecutionSnapshot) => item.display?.kind === "job_agent";
  const agentName = (item: ExecutionSnapshot) => (item.display?.label || runTitle(item)).replace(/_/g, " ");
  const mainName = text("Main agent", "主代理");
  /** Executions a branch runs itself: the agent (null: the main
   *  conversation) and the executions under it that no deeper agent owns. */
  const ownedBy = (owner: string | null) => new Set(executions.filter(item => branches.ownerOf(item) === owner).map(item => item.execution_id));
  /** The sub-agent an `agent` call started, when it is listed: the one its
   *  transcript row was paired with, else the job that began right after it. */
  const agentOf = (entry: ActiveToolCall) => {
    if (entry.name !== "agent") return null;
    const paired = entry.tool_call_id ? spawns.find(item => item.job_id && item.id.endsWith(`_t_${entry.tool_call_id}`)) : undefined;
    return (paired?.job_id ? execution(paired.job_id) : null) ?? spawnedBy(entry, model.childrenOf(entry.execution_id));
  };
  /** Everything an agent covers: itself and every execution under it. */
  const subtreeOf = (item: ExecutionSnapshot) => {
    const ids = new Set<string>();
    const walk = (entry: ExecutionSnapshot) => { if (ids.has(entry.execution_id)) return; ids.add(entry.execution_id); model.childrenOf(entry.execution_id).forEach(walk); };
    walk(item);
    return ids;
  };
  /** What waits on the reader: a run paused on a question or an approval.
   *  A call or run cut short by a restart is history, not a task. */
  const waits = model.issues.filter((issue): issue is Extract<ActivityIssue, { kind: "execution" }> =>
    issue.kind === "execution" && issue.execution.status === "paused");
  /** A run's state, read as Interrupted when the call that started a
   *  sub-agent was cut off before it finished. */
  const stateOf = (item: ExecutionSnapshot) => !["completed", "failed"].includes(item.status) && !LIVE.includes(item.status)
    && calls.some(entry => entry.status !== "running" && agentOf(entry)?.execution_id === item.execution_id)
    ? text("Interrupted", "已中断") : executionState(item, text);
  const issuesOf = (item: ExecutionSnapshot) => {
    const ids = subtreeOf(item);
    return waits.filter(issue => ids.has(issue.execution.execution_id));
  };
  const activeIn = (ids: Set<string>) => executions.some(entry => ids.has(entry.execution_id) && LIVE.includes(entry.status))
    || calls.some(entry => ids.has(entry.execution_id) && entry.status === "running")
    || processes.items.some(entry => entry.execution_id && ids.has(entry.execution_id) && processIsActive(entry));
  /** Calls that started no sub-agent, made by this branch (null: the main agent). */
  const failedSpawns = (owner: string | null) => spawns.filter(item => !item.job_id && (item.owner_job_id ?? null) === owner
    && (owner === null || executions.some(entry => entry.execution_id === owner)));

  // ---- the main agent, one per branch -------------------------------------
  // With one branch the main agent is the whole conversation. With more,
  // each branch the reader made is a main agent of its own, holding the
  // runs on that branch; calls and programs whose execution is not listed,
  // and calls that started no sub-agent, count as the checked-out branch's.
  const memberships = new Map((state.branches || []).filter(entry => entry.session_id === sessionId)
    .map(entry => [entry.head_msg_id, new Set(entry.execution_ids)]));
  const rootOf = (item: ExecutionSnapshot): ExecutionSnapshot => {
    let top = item;
    for (const seen = new Set<string>(); ; ) {
      const parent = branches.parentOf(top);
      if (!parent || seen.has(parent)) return top;
      seen.add(parent);
      const next = execution(parent);
      if (!next) return top;
      top = next;
    }
  };
  type Scope = { key: string; head: string | null; name: string; active: boolean; color: string | null; updatedAt: number | null; members: Set<string> | null };
  const scopes: Scope[] = conversationBranches.length > 1
    ? conversationBranches.map(branch => ({ key: branch.head, head: branch.head, active: branch.active, color: branch.color, updatedAt: branch.updatedAt,
      name: branch.name || text("Unnamed branch", "未命名分支"), members: memberships.get(branch.head) ?? new Set<string>() }))
    : [{ key: "main", head: null, name: mainName, active: true, color: null, updatedAt: null, members: null }];
  const inScope = (scope: Scope, item: ExecutionSnapshot) => !scope.members || scope.members.has(rootOf(item).execution_id);
  const fullTree = branches.tree<AgentCall>(owner => failedSpawns(owner).map(leaf => ({ at: leaf.at, leaf })));
  /** What one main agent holds: its runs, what it is doing, what waits on the reader, its sub-agents. */
  function scopeFacts(scope: Scope) {
    const ids = new Set([...ownedBy(null)].filter(id => inScope(scope, execution(id)!)));
    const runs = executions.filter(item => ids.has(item.execution_id) && !branches.parentOf(item)).sort((a, b) => startedAt(b) - startedAt(a));
    const unlisted = (id: string | null | undefined) => scope.active && (!id || !execution(id));
    const running = calls.filter(entry => entry.status === "running" && (ids.has(entry.execution_id) || unlisted(entry.execution_id)));
    const programs = processes.items.filter(entry => processIsActive(entry) && entry.execution_id && ids.has(entry.execution_id));
    const live = executions.some(entry => ids.has(entry.execution_id) && LIVE.includes(entry.status)) || running.length > 0 || programs.length > 0;
    const issues = waits.filter(issue => ids.has(issue.execution.execution_id));
    const tree = scope.members ? pruneBranches(fullTree, row => row.kind === "agent" ? inScope(scope, row.item) : scope.active) : fullTree;
    return { ids, latestRun: runs[0] ?? null, running, programs, live, issues, tree };
  }
  type ScopeFacts = ReturnType<typeof scopeFacts>;
  const scopeOf = (key: string) => scopes.find(scope => scope.key === key) ?? scopes.find(scope => scope.active) ?? scopes[0];
  /** A main agent's state. Resting, it is just the time of its last
   *  message (the branch's own time when no run of it is listed). */
  function scopeStatus(facts: ScopeFacts, scope?: Scope): { label: string; tone: Tone } {
    const { ids, latestRun, running, live, issues } = facts;
    if (live) {
      const step = running.at(-1);
      const since = executions.filter(entry => ids.has(entry.execution_id) && LIVE.includes(entry.status)).map(startedAt).sort((a, b) => a - b)[0]
        ?? step?.started_at ?? now;
      const doing = !step ? text("Running", "正在运行")
        : step.name === "agent" ? text("Waiting for a sub-agent", "等待子代理")
          : `${text("Running", "正在运行")} ${step.description || step.name}`;
      return { label: `${doing} · ${duration(now - since, text)}`, tone: "run" };
    }
    if (issues.length) return { label: issues.length === 1 ? waitingState(issues[0].execution) : text("Waiting for you", "等你处理"), tone: "warn" };
    if (!latestRun) return { label: scope?.updatedAt ? when(scope.updatedAt, text) : "", tone: "muted" };
    const at = when(latestRun.terminal_at ?? latestRun.updated_at ?? startedAt(latestRun), text);
    if (latestRun.status === "failed") return { label: `${text("Failed", "失败")} · ${at}`, tone: "err" };
    if (["completed", "reconciliation_required", "paused"].includes(latestRun.status)) return { label: at, tone: "muted" };
    return { label: `${executionState(latestRun, text)} · ${at}`, tone: "muted" };
  }

  function viewTitle(entry: View): string {
    if (entry.kind === "main") return scopeOf(entry.id).name;
    if (entry.kind === "call") { const item = call(entry.id); return item ? item.description || item.name : text("Call", "调用"); }
    if (entry.kind === "spawn") { const item = spawn(entry.id); return item?.description || text("Sub-agent", "子代理"); }
    if (entry.kind === "program") { const item = program(entry.id); return item ? programTitle(item, text) : text("Program", "程序"); }
    if (entry.kind === "always") return text("Always-on", "常驻");
    if (entry.kind === "work") return ongoing?.open_work.find(item => item.id === entry.id)?.text || text("Open work", "未完成事项");
    if (entry.kind === "routine") return routines.find(task => task.id === entry.id)?.title || text("Routine", "例行任务");
    const item = execution(entry.id);
    return item ? isAgent(item) ? agentName(item) : runTitle(item) : text("Run", "运行");
  }

  /** The open question or approval an execution is waiting on, if the chat has it. */
  function decisionFor(executionId: string) {
    return allDecisions.find(entry => entry.sessionId === sessionId && entry.executionId === executionId);
  }
  /** Bring the chat's card for this decision into view, with its first choice focused. */
  function answerInChat(decisionId: string) {
    const card = [...document.querySelectorAll<HTMLElement>("[data-decision-output]")]
      .find(node => node.getAttribute("data-decision-output") === decisionId);
    if (!card) { useSessionStore.getState().focusComposer(); return; }
    card.scrollIntoView({ block: "nearest", behavior: "smooth" });
    card.querySelector<HTMLElement>("button:not([disabled]), input:not([disabled]), textarea:not([disabled])")?.focus({ preventScroll: true });
  }

  /** Check out a branch, the same as clicking it in the Branches panel. */
  function switchTo(head: string) {
    sendRuntimeCommand({ action: "checkout_branch", session_id: sessionId, head_msg_id: head });
    sendRuntimeCommand({ action: "load_session", session_id: sessionId });
  }

  async function openAgentConversation(job: ExecutionSnapshot) {
    const target = await loadSubAgentTranscript(sessionId!, job.execution_id, { jobId: job.execution_id, headId: job.display?.assistant_message_id })
      || job.display?.assistant_message_id;
    if (!target) return;
    sendRuntimeCommand({ action: "checkout_branch", session_id: sessionId, head_msg_id: target });
    sendRuntimeCommand({ action: "load_session", session_id: sessionId });
  }

  /** The sub-agents a branch started and its calls that started none, newest first. */
  function startedNewestFirst(agents: ExecutionSnapshot[], failed: AgentCall[]): ReactNode[] {
    return [...agents.map(item => ({ at: startedAt(item), node: agentRow(item) })), ...failed.map(item => ({ at: item.at, node: spawnRow(item) }))]
      .sort((a, b) => b.at - a.at).map(entry => entry.node);
  }

  // ---- rows ----------------------------------------------------------------
  /** A main agent's row: its branch's colour and a tag on the checked-out one. */
  function scopeRow(scope: Scope): ReactNode {
    const facts = scopeFacts(scope);
    // What waits for the reader is the red count on the glyph, its own
    // and its sub-agents'; the line keeps what it is doing or its time.
    const waiting = facts.issues.length + facts.tree.filter(row => lookOf(row).tone === "warn").length;
    const look = facts.issues.length ? scopeStatus({ ...facts, issues: [] }, scope) : scopeStatus(facts, scope);
    const subs = facts.tree.length ? text(`${facts.tree.length} sub-agent${facts.tree.length === 1 ? "" : "s"}`, `${facts.tree.length} 个子代理`) : "";
    const current = scope.head && scope.active ? <span className={styles.current}>{text("Current", "当前")}</span> : null;
    return <Row key={scope.key} glyph={<AgentGlyph shape={mainShape} color={scope.color} />} title={scope.name} badge={current} count={waiting}
      status={[look.label, subs].filter(Boolean).join(" · ")} tone={look.tone === "warn" ? "muted" : look.tone}
      onOpen={() => open({ kind: "main", id: scope.key })} />;
  }
  /** An agent's status line: what waits on the reader first, then what runs. */
  function agentLook(item: ExecutionSnapshot): { label: string; tone: Tone; at: number } {
    const ids = subtreeOf(item);
    const issues = issuesOf(item);
    const live = activeIn(ids);
    const runningCall = calls.filter(entry => ids.has(entry.execution_id) && entry.status === "running").at(-1);
    if (issues.length) return {
      label: issues.length === 1 ? `${waitingState(issues[0].execution)} · ${when(issues[0].at, text)}` : text("Waiting for you", "等你处理"),
      tone: "warn", at: live ? now : startedAt(item),
    };
    if (live) return {
      label: `${runningCall ? `${text("Running", "正在运行")} ${runningCall.description || runningCall.name}` : text("Running", "正在运行")} · ${duration(now - startedAt(item), text)}`,
      tone: "run", at: now,
    };
    return { label: `${stateOf(item)} · ${when(startedAt(item), text)}`, tone: executionTone(item), at: startedAt(item) };
  }
  /** A paused or interrupted execution in the reader's words: what it waits on. */
  function waitingState(item: ExecutionSnapshot): string {
    const decision = item.status === "paused" ? decisionFor(item.execution_id) : undefined;
    if (decision) return decision.kind === "approval" ? text("Waiting for approval", "等你授权") : text("Waiting for your answer", "等你回答");
    return stateOf(item);
  }
  /** Who started a branch, appended when the list is not a tree. */
  const startedBy = (owner: string | null) => {
    const agent = owner ? execution(owner) : null;
    const name = agent ? agentName(agent) : mainName;
    return text(` · by ${name}`, ` · ${name}启动`);
  };
  function agentRow(item: ExecutionSnapshot, line?: Line, by = false): ReactNode {
    // Its own waits: a sub-agent below it shows its own count.
    const below = [...subtreeOf(item)].map(execution).filter((entry): entry is ExecutionSnapshot => Boolean(entry) && entry !== item && isAgent(entry!));
    const waiting = issuesOf(item).filter(issue => !below.some(agent => subtreeOf(agent).has(issue.execution.execution_id))).length;
    // Waiting, the red count says so; the line keeps the time.
    const { label, tone } = waiting ? { label: when(startedAt(item), text), tone: "muted" as Tone } : agentLook(item);
    return <Row key={`agent:${item.execution_id}`} line={line} glyph={<AgentGlyph shape={subAgentShape(agentName(item))} />} title={agentName(item)} count={waiting}
      status={by ? label + startedBy(branches.agentParentOf(item)) : label} tone={tone}
      onOpen={() => open({ kind: "run", id: item.execution_id })} />;
  }
  function spawnRow(item: AgentCall, line?: Line, by = false): ReactNode {
    const label = `${spawnState(item, text)} · ${when(item.at, text)}`;
    return <Row key={`spawn:${item.id}`} line={line} glyph={<AgentGlyph shape={subAgentShape(item.description || "")} />} title={item.description || text("Sub-agent", "子代理")}
      status={by ? label + startedBy(item.owner_job_id) : label} tone={item.failed ? "err" : "muted"}
      onOpen={() => open({ kind: "spawn", id: item.id })} />;
  }
  function callRow(item: ActiveToolCall, withKind = true): ReactNode {
    const look = presentTool(item.name, undefined, text);
    const phase = item.status === "running"
      ? `${text("Running", "正在运行")} · ${duration(now - item.started_at, text)}`
      : `${text("Interrupted", "已中断")} · ${when(item.started_at, text)}`;
    return <Row key={`call:${item.id}`} glyph={<Glyph name={look.icon} tone={look.tone} large />} title={item.description || item.name}
      status={withKind ? `${callKind(item, text)} · ${phase}` : phase} tone={item.status === "running" ? "run" : "muted"}
      onOpen={() => open({ kind: "call", id: item.id })} />;
  }
  function programRow(item: ManagedProcess): ReactNode {
    const look = progressLook(item.progress);
    const active = processIsActive(item) && item.status !== "unknown";
    // A running program always shows a bar (sweeping when the amount is
    // unknown); a finished one keeps its bar only if it reported progress.
    const bar = active || look?.fraction != null
      ? <span className="block m-[5px_0_2px]"><ProgressBar fraction={look?.fraction ?? null} tone={programBarTone(item, look)}
        note={active ? look?.eta && text(`${look.eta} left`, `剩 ${look.eta}`) : item.ended_at != null ? clock(item.ended_at - item.started_at) : null} /></span>
      : null;
    return <Row key={`program:${item.id}`} glyph={<Glyph name="code-square" tone="shell" large />} title={programTitle(item, text)}
      sub={commandLine(item)} status={programStatus(item, look, now, text)} tone={programTone(item)} extra={bar}
      onOpen={() => open({ kind: "program", id: item.id })} />;
  }
  function runRow(item: ExecutionSnapshot): ReactNode {
    return <Row key={`execution:${item.execution_id}`} glyph={<RunGlyph />} title={runTitle(item)}
      status={`${executionState(item, text)} · ${when(startedAt(item), text)}`} tone={executionTone(item)}
      onOpen={() => open({ kind: "run", id: item.execution_id })} />;
  }
  function childRow(item: ExecutionSnapshot): ReactNode {
    if (isAgent(item)) return agentRow(item);
    return <Row key={`execution:${item.execution_id}`} glyph={<RunGlyph />} title={runTitle(item)}
      status={`${text("Branch", "分支")} · ${executionState(item, text)}`} tone={executionTone(item)}
      onOpen={() => open({ kind: "run", id: item.execution_id })} />;
  }

  // ---- what the conversation does on its own ---------------------------------
  const alwaysOn = ongoing?.always_on.enabled ? ongoing.always_on : null;
  const openItems = (ongoing?.open_work ?? []).filter(item => item.status === "open");
  const routines = ongoing?.routines ?? [];
  /** The always-on row: what it is doing, else when it wakes next. */
  function alwaysStatus(): { label: string; tone: Tone } {
    if (!alwaysOn) return { label: "", tone: "muted" };
    if (alwaysOn.running) return { label: text("Working now", "正在工作"), tone: "run" };
    const next = alwaysOn.next_wake_at
      ? alwaysOn.quiet_now
        ? text(`Quiet hours · next wake ${when(alwaysOn.next_wake_at, text)}`, `安静时段 · 下次唤醒 ${when(alwaysOn.next_wake_at, text)}`)
        : text(`Next wake ${when(alwaysOn.next_wake_at, text)}`, `下次唤醒 ${when(alwaysOn.next_wake_at, text)}`)
      : text("Joins on its next use", "下次使用后加入");
    const goal = alwaysOn.goal ? goalStatusLabel(alwaysOn.goal.status, text) : "";
    return { label: [goal, next].filter(Boolean).join(" · "), tone: "muted" };
  }
  function alwaysRow(): ReactNode {
    const look = alwaysStatus();
    const glyph = alwaysOn?.agent_id
      ? <span className="grid size-[22px] flex-none place-items-center"><AgentAvatarById agentId={alwaysOn.agent_id} size={20} mood={alwaysOn.running ? "thinking" : "idle"} /></span>
      : <Glyph name="clock-circle" tone="plan" large />;
    return <Row key="always" glyph={glyph}
      title={alwaysOn?.agent_name ? text(`Always-on · ${alwaysOn.agent_name}`, `常驻 · ${alwaysOn.agent_name}`) : text("Always-on", "常驻")}
      status={look.label} tone={look.tone} onOpen={() => open({ kind: "always", id: "always" })} />;
  }
  function openWorkRow(item: OpenWorkItem): ReactNode {
    return <Row key={`work:${item.id}`} glyph={<Glyph name="checklist" tone="plan" large />} title={item.text}
      status={[item.status === "done" ? text("Done", "已完成") : text("Open", "未完成"), when(item.updated_at, text)].join(" · ")}
      tone={item.status === "done" ? "ok" : "muted"} onOpen={() => open({ kind: "work", id: item.id })} />;
  }
  function routineRow(task: Routine): ReactNode {
    return <Row key={`routine:${task.id}`} glyph={<Glyph name={task.type === "webhook" ? "link" : "calendar"} tone="plan" large />}
      title={task.title} sub={task.watch} status={routineSchedule(task, text)} tone="muted"
      onOpen={() => open({ kind: "routine", id: task.id })} />;
  }
  async function act(run: () => Promise<unknown>, failed: string) {
    setPending(view ? `${view.kind}:${view.id}` : "act"); setActionError(null);
    try { await run(); refreshOngoing(); return true; }
    catch (cause) { setActionError(`${failed} ${cause instanceof Error ? cause.message : ""}`.trim()); return false; }
    finally { setPending(null); }
  }
  async function copy(key: string, value: string) {
    if (await copyText(value)) { setCopied(key); setTimeout(() => setCopied(current => current === key ? null : current), 1500); }
  }

  /** A program page's progress: the count and bar, then time, speed and
   *  time left while it runs, or how long it took and how it ended. */
  function programProgressCard(item: ManagedProcess): ReactNode {
    const look = progressLook(item.progress);
    const active = processIsActive(item) && item.status !== "unknown";
    if (!active && !look) return null;
    const end = item.ended_at ?? now;
    const stats: [string, string][] = active
      ? [[text("Elapsed", "已用时间"), clock(now - item.started_at)],
        [text("Speed", "速度"), look?.rate ?? "—"],
        [text("Left", "剩余"), look?.eta ?? "—"]]
      : [[text("Took", "用时"), clock(end - item.started_at)],
        [text("Ended", "结束"), updatedTime(end)],
        [text("Exit code", "退出码"), item.exit_code != null ? String(item.exit_code) : "—"]];
    return <div className={styles.progress}>
      <div className="flex items-baseline justify-between gap-[12px] min-w-0">
        <span className={styles.progressCount}>
          {look?.count ?? (active ? text("Working…", "运行中…") : programState(item, text))}
        </span>
        {look?.fraction != null && <span className={styles.progressPercent}>{Math.floor(look.fraction * 100)}%</span>}
      </div>
      {look?.stage && <span className={styles.progressStage}>{look.stage}</span>}
      {(active || look?.fraction != null) && <ProgressBar size="md" fraction={look?.fraction ?? null} tone={programBarTone(item, look)} />}
      {active && !look?.count && item.last_line && <span className={styles.progressLast}>{item.last_line}</span>}
      <dl className={`${styles.stats} grid grid-cols-[repeat(3,_minmax(0,_1fr))] gap-[8px] m-[2px_0_0]`}>
        {stats.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
    </div>;
  }

  // ---- what waits on the reader -------------------------------------------------
  function waitBlock(issue: Extract<ActivityIssue, { kind: "execution" }>, here: "main" | "run" | "agent"): ReactNode {
    const decision = decisionFor(issue.execution.execution_id);
    const approval = decision?.kind === "approval";
    // The main agent's page gathers several runs, so each block names its message.
    const title = runTitle(issue.execution);
    const heading = here === "main"
      ? approval ? text(`"${title}" is waiting for approval`, `“${title}”在等你授权`) : text(`"${title}" is waiting for your answer`, `“${title}”在等你回答`)
      : approval ? text("Waiting for approval", "等你授权") : text("Waiting for your answer", "等你回答");
    const body = decision ? decision.prompt || decision.questions?.[0]?.prompt || "" : text("It paused on a question or an approval.", "它停在一个问题或授权上。");
    const choices = decision?.options?.length ? decision.options : decision?.questions?.[0]?.options ?? [];
    // Without a queued decision the run's own page holds the wait and
    // the controls; from the main page that page is one step away.
    const action = decision
      ? <Button variant="elevated" size="xs" onClick={() => answerInChat(decision.id)}>{approval ? text("Review in chat", "去聊天里授权") : text("Answer in chat", "去聊天里回答")}</Button>
      : here === "main" ? <Button variant="elevated" size="xs" onClick={() => openRun(issue.execution.execution_id)}>{text("Open", "打开")}</Button> : null;
    return <div className={styles.issue} key={issue.key}>
      <h4 className={styles.issueTitle}>{heading}</h4>
      {body && <p className={styles.issueText}>{body}</p>}
      {choices.length > 0 && <p className={styles.choices}>{text("Choices: ", "可选：")}{choices.join(text(" · ", "、"))}</p>}
      {action && <div className={`${styles.actions} flex flex-wrap gap-[8px] mt-[10px]`}>{action}</div>}
    </div>;
  }

  const backBar = (fallback: string) => <div className="flex items-center p-[0_8px_4px]">
    <Button variant="ghost" size="xs" className={styles.back} onClick={() => setStack(previous => previous.slice(0, -1))}>
      ← {stack.length > 1 ? viewTitle(stack[stack.length - 2]) : fallback}
    </Button>
  </div>;
  const toActivity = text("Activity", "运行记录");
  /** Where a branch came from: the agent that started it, or the main agent. */
  /** Who started a sub-agent: the agent above it, or the main agent of its branch. */
  const fromLink = (owner: string | null, of?: ExecutionSnapshot) => {
    const agent = owner ? execution(owner) : null;
    const main = (of && scopes.find(scope => inScope(scope, of))) || scopeOf("");
    return <button type="button" className={styles.link} onClick={() => open(agent ? { kind: "run", id: agent.execution_id } : { kind: "main", id: main.key })}>
      {agent ? agentName(agent) : main.name}</button>;
  };

  // ---- the sub-agent tree ------------------------------------------------------
  // Sub-agents the model starts live on the main agent's page, not in the
  // overview; a call that never started a sub-agent sits where that
  // sub-agent would.
  const rowKey = (row: BranchRow<AgentCall>) => row.kind === "agent" ? row.item.execution_id : `spawn:${row.leaf.id}`;
  const looks = new Map(fullTree.map(row => [rowKey(row), row.kind === "agent" ? agentLook(row.item) : { tone: (row.leaf.failed ? "err" : "muted") as Tone, at: row.leaf.at }]));
  const lookOf = (row: BranchRow<AgentCall>) => looks.get(rowKey(row)) ?? { tone: "muted" as Tone, at: 0 };
  const shows = (tone: Tone) => listView.show === "all" || (listView.show === "attention" ? tone === "warn" : tone === "run");
  /** The tree on the main agent's page: its children are the page's own
   *  list, so the lines begin one level down. By structure a filter keeps
   *  the branches above a match; by time it is one list, latest first. */
  function subAgentList(tree: BranchRow<AgentCall>[]): ReactNode {
    const rows = listView.arrange === "structure"
      ? listView.show === "all" ? tree : pruneBranches(tree, row => shows(lookOf(row).tone))
      : tree.filter(row => shows(lookOf(row).tone)).sort((a, b) => lookOf(b).at - lookOf(a).at);
    const visible = rows.slice(0, shown);
    if (rows.length === 0) return <p className={styles.empty}>{tree.length === 0
      ? text("No sub-agents yet.", "还没有启动过子代理。")
      : text(...({
        attention: ["No sub-agents waiting for you.", "没有等你处理的子代理。"],
        running: ["No sub-agent is running.", "没有正在运行的子代理。"],
        all: ["", ""],
      }[listView.show] as [string, string]))}</p>;
    const cut = rows.length > shown;
    return <>
      {listView.arrange === "structure"
        ? visible.map((entry, index) => {
          // A cut-off page keeps the line running to the paging button.
          const line = entry.depth === 1 ? undefined : {
            depth: entry.depth - 1, guides: entry.guides.filter(level => level > 1).map(level => level - 1),
            first: index === 0 || visible[index - 1].depth < entry.depth,
            last: entry.last && !(index === visible.length - 1 && cut),
          };
          return entry.kind === "agent" ? agentRow(entry.item, line) : spawnRow(entry.leaf, line);
        })
        : visible.map(row => row.kind === "agent" ? agentRow(row.item, undefined, true) : spawnRow(row.leaf, undefined, true))}
      {cut && <Button type="button" variant="link" size="xs" onClick={() => setShown(value => value + 50)}>
        {text(`Show ${Math.min(50, rows.length - shown)} earlier`, `显示更早的 ${Math.min(50, rows.length - shown)} 个`)}
      </Button>}
    </>;
  }

  // ---- pages -------------------------------------------------------------------
  if (view?.kind === "main") {
    const scope = scopeOf(view.id);
    const facts = scopeFacts(scope);
    const { latestRun, tree } = facts;
    const { label, tone } = scopeStatus(facts, scope);
    const runningHere = [...facts.running.filter(entry => !agentOf(entry)).map(entry => callRow(entry)), ...facts.programs.map(entry => programRow(entry))];
    return <div className={styles.panel}>
      {backBar(toActivity)}
      <div className={`${styles.scroll} min-h-0 overflow-y-auto p-[0_8px_16px]`}>
        <div className={`${styles.head} grid gap-[4px] p-[10px_8px_0]`}>
          <div className={styles.kind}>{scope.head ? <>{text("Branch", "分支")}{scope.active && <> · {text("Current", "当前")}</>}</> : mainName}</div>
          <h3 className={styles.title}>{scope.head ? scope.name : conversationTitle || mainName}</h3>
          <Status tone={tone}>{label}</Status>
        </div>
        {facts.issues.map(issue => waitBlock(issue, "main"))}
        {scope.head && !scope.active && <div className={`${styles.actions} flex flex-wrap gap-[8px] mt-[10px]`} data-inline="1">
          <Button variant="elevated" size="xs" onClick={() => switchTo(scope.head!)}>{text("Switch to this branch", "切换到这个分支")}</Button>
        </div>}
        {actionError && <p role="alert" className={styles.error}>{actionError}</p>}
        {runningHere.length > 0 && <><h4 className={styles.section}>{text("Running", "正在运行")}</h4>{runningHere}</>}
        {latestRun && <><h4 className={styles.section}>{text("Last message", "最后一条消息")}</h4>{runRow(latestRun)}</>}
        <div className={`${styles.sectionRow} flex items-center justify-between gap-[8px] mr-[4px]`}>
          <h4 className={styles.section}>{text("Sub-agents", "子代理")}</h4>
          {tree.length > 0 && <AgentsViewMenu />}
        </div>
        {subAgentList(tree)}
      </div>
    </div>;
  }

  if (view?.kind === "run") {
    const item = execution(view.id);
    const run = item ? model.runOf(item.execution_id) : null;
    if (!item || !run) return <div className={styles.panel}>{backBar(toActivity)}<SidebarNotice>{text("This run is no longer listed.", "这次运行已不在列表中。")}</SidebarNotice></div>;
    const isRoot = run.root.execution_id === item.execution_id;
    const issues = issuesOf(item);
    const agent = isAgent(item);
    // An agent call is reached through the sub-agent it started.
    const ownCalls = run.calls.filter(entry => entry.execution_id === item.execution_id && !agentOf(entry));
    const kids = model.childrenOf(item.execution_id);
    const nested = agent ? branches.agentsUnder(item.execution_id).filter(entry => !kids.includes(entry)) : [];
    const ownPrograms = run.programs.filter(entry => entry.execution_id === item.execution_id);
    const failed = agent ? failedSpawns(item.execution_id) : [];
    const spawning = agent ? calls.find(entry => agentOf(entry)?.execution_id === item.execution_id) : undefined;
    const task = spawning?.prompt || (agent ? spawns.find(entry => entry.job_id === item.execution_id)?.prompt : "") || "";
    const end = item.terminal_at ?? (LIVE.includes(item.status) ? now : item.updated_at);
    return <div className={styles.panel}>
      {backBar(toActivity)}
      <div className={`${styles.scroll} min-h-0 overflow-y-auto p-[0_8px_16px]`}>
        <div className={`${styles.head} grid gap-[4px] p-[10px_8px_0]`}>
          <div className={styles.kind}>{agent ? text("Sub-agent", "子代理") : isRoot ? text("Run", "一次运行") : text("Branch", "分支")} · {updatedTime(startedAt(item))} · {text("took", "用时")} {duration(end - startedAt(item), text)}</div>
          <h3 className={styles.title}>{agent ? agentName(item) : runTitle(item)}</h3>
          <Status tone={issues.length ? "warn" : executionTone(item)}>{issues.length === 1 ? waitingState(issues[0].execution)
            : issues.length ? text("Waiting for you", "等你处理") : stateOf(item)}</Status>
        </div>
        {issues.map(issue => waitBlock(issue, agent ? "agent" : "run"))}
        {agent && <div className={`${styles.actions} flex flex-wrap gap-[8px] mt-[10px]`} data-inline="1">
          <Button variant="elevated" size="xs" onClick={() => void openAgentConversation(item)}>{text("Open its conversation", "打开它的对话")}</Button>
        </div>}
        {actionError && <p role="alert" className={styles.error}>{actionError}</p>}
        {agent
          ? <dl className={styles.facts}>
            <dt>{text("Started by", "由谁启动")}</dt><dd>{fromLink(branches.agentParentOf(item), item)}</dd>
            {!isRoot && <><dt>{text("From", "来自")}</dt>
              <dd><button type="button" className={styles.link} onClick={() => open({ kind: "run", id: run.root.execution_id })}>{runTitle(run.root)}</button></dd></>}
          </dl>
          : !isRoot && <dl className={styles.facts}>
            <dt>{text("From", "来自")}</dt>
            <dd><button type="button" className={styles.link} onClick={() => open({ kind: "run", id: run.root.execution_id })}>{runTitle(run.root)}</button></dd>
          </dl>}
        {task && <Long label={text("Task", "任务")} body={task} mono={false} open={taskOpen} onToggle={() => setTaskOpen(value => !value)} text={text} />}
        <h4 className={styles.section}>{text("Steps", "步骤")}</h4>
        {kids.length + nested.length + ownCalls.length + ownPrograms.length + failed.length === 0
          ? <p className={styles.empty}>{text("No sub-agents, calls or programs.", "没有子代理、调用或程序。")}</p>
          : <>{ownCalls.map(entry => callRow(entry))}{kids.filter(entry => !isAgent(entry)).map(childRow)}
            {startedNewestFirst([...kids.filter(isAgent), ...nested], failed)}{ownPrograms.map(entry => programRow(entry))}</>}
        <h4 className={styles.section}>{text("Progress", "进展")}</h4>
        {/* The run's own record: its progress, the controls it allows, its
            open waits and, folded at the end, the raw ids and events. */}
        <DebuggerPanel key={item.execution_id} {...state} detailOnly embedded selectedExecutionId={item.execution_id}
          onSelectExecution={state.selectExecution} onCommand={state.command} onRespondWait={state.respondWait}
          onCreateDraft={async input => { await state.createDraft(input); }} onUpdateDraft={state.updateDraft}
          onDraftAction={state.draftAction} />
      </div>
    </div>;
  }

  if (view?.kind === "spawn") {
    const item = spawn(view.id);
    if (!item) return <div className={styles.panel}>{backBar(toActivity)}<SidebarNotice>{text("This call is no longer listed.", "这次调用已不在列表中。")}</SidebarNotice></div>;
    return <div className={styles.panel}>
      {backBar(toActivity)}
      <div className={`${styles.scroll} min-h-0 overflow-y-auto p-[0_8px_16px]`}>
        <div className={`${styles.head} grid gap-[4px] p-[10px_8px_0]`}>
          <div className={styles.kind}><AgentGlyph shape={subAgentShape(item.description || "")} small />{text("Sub-agent", "子代理")} · {updatedTime(item.at)}</div>
          <h3 className={styles.title}>{item.description || text("Sub-agent", "子代理")}</h3>
          <Status tone={item.failed ? "err" : "muted"}>{spawnState(item, text)}</Status>
        </div>
        <p className={styles.note}>{text("This call did not start a sub-agent, so it has no conversation of its own.", "这次调用没有建出子代理，所以没有它自己的对话。")}</p>
        <dl className={styles.facts}>
          <dt>{text("Started by", "由谁启动")}</dt><dd>{fromLink(item.owner_job_id)}</dd>
        </dl>
        {item.error && <><h4 className={styles.section}>{text("Error", "报错")}</h4><p className={styles.code} data-open="1">{item.error}</p></>}
        {item.prompt && <Long label={text("Task", "任务")} body={item.prompt} mono={false} open={taskOpen} onToggle={() => setTaskOpen(value => !value)} text={text} />}
      </div>
    </div>;
  }

  if (view?.kind === "call") {
    const item = call(view.id);
    if (!item) return <div className={styles.panel}>{backBar(toActivity)}<SidebarNotice>{text("This call has returned.", "这次调用已经返回。")}</SidebarNotice></div>;
    const look = presentTool(item.name, undefined, text);
    const owner = execution(item.execution_id);
    const run = owner ? model.runOf(owner.execution_id) : null;
    return <div className={styles.panel}>
      {backBar(toActivity)}
      <div className={`${styles.scroll} min-h-0 overflow-y-auto p-[0_8px_16px]`}>
        <div className={`${styles.head} grid gap-[4px] p-[10px_8px_0]`}>
          <div className={styles.kind}><Glyph name={look.icon} tone={look.tone} />{callKind(item, text)} · {updatedTime(item.started_at)}</div>
          <h3 className={styles.title}>{item.description || item.name}</h3>
          <Status tone={item.status === "running" ? "run" : "muted"}>{item.status === "running" ? `${text("Running", "正在运行")} · ${duration(now - item.started_at, text)}` : text("Interrupted", "已中断")}</Status>
        </div>
        {item.status !== "running" && <p className={styles.note}>{agentOf(item)
          ? text("The run was interrupted before this sub-agent finished.", "这个子代理还没做完，运行就中断了。")
          : text("The run was interrupted before this call returned.", "这次调用还没返回，运行就中断了。")}</p>}
        {actionError && <p role="alert" className={styles.error}>{actionError}</p>}
        {run && <dl className={styles.facts}>
          <dt>{text("From", "来自")}</dt>
          <dd><button type="button" className={styles.link} onClick={() => open({ kind: "run", id: run.root.execution_id })}>{runTitle(run.root)}</button></dd>
        </dl>}
        {item.prompt && <Long label={text("Task", "任务")} body={item.prompt} mono={false} open={taskOpen} onToggle={() => setTaskOpen(value => !value)} text={text} />}
        {item.command && <Long label={text("Command", "命令")} body={item.command} mono open={taskOpen} onToggle={() => setTaskOpen(value => !value)} text={text} />}
      </div>
    </div>;
  }

  if (view?.kind === "program") {
    const item = processes.detail?.process.id === view.id ? processes.detail.process : program(view.id);
    const run = item?.execution_id ? model.runOf(item.execution_id) : null;
    return <div className={styles.panel}>
      {backBar(toActivity)}
      {processes.stale && item && <SidebarNotice>{text("Program updates are unavailable. Showing saved results and retrying automatically.", "程序更新暂时不可用，保留上次记录并自动重试。")}</SidebarNotice>}
      {!item ? <SidebarNotice>{processes.stale ? text("Program details unavailable.", "暂时无法读取程序详情。") : text("Loading program…", "正在读取程序…")}</SidebarNotice> : <div className={`${styles.scroll} min-h-0 overflow-y-auto p-[0_8px_16px]`}>
        <div className={`${styles.head} grid gap-[4px] p-[10px_8px_0]`}>
          <div className={styles.kind}><Glyph name="code-square" tone="shell" />{text("Background program", "后台程序")} · {updatedTime(item.started_at)}</div>
          <h3 className={styles.title}>{programTitle(item, text)}</h3>
          <Status tone={programTone(item)}>{programState(item, text)}</Status>
        </div>
        {programProgressCard(item)}
        {["unknown", "lost"].includes(item.status) && <p className={styles.note}>{text("The program's supervisor is unavailable, so whether it is still running is not known.", "程序的监督进程不可用，不知道它是否还在运行。")}</p>}
        {processIsActive(item) && <div className={`${styles.actions} flex flex-wrap gap-[8px] mt-[10px]`} data-inline="1">
          <Button variant="elevated" size="xs" disabled={pending === item.id || processes.stale || item.can_stop === false} onClick={async () => {
            setPending(item.id); setActionError(null);
            try { await stopProcess(item.id, sessionId); processes.refresh(); }
            catch { setActionError(text("Could not stop the program. Its status will update automatically; try again once it is available.", "未能停止程序，状态将自动更新，恢复后可重试。")); }
            finally { setPending(null); }
          }}>{pending === item.id ? text("Stopping…", "正在停止…") : text("Stop program", "停止程序")}</Button>
        </div>}
        {actionError && <p role="alert" className={styles.error}>{actionError}</p>}
        <Long label={text("Command", "命令")} body={item.command} mono open={taskOpen} onToggle={() => setTaskOpen(value => !value)} text={text} />
        <h4 className={styles.section}>
          {text("Output", "输出")}
          {processIsActive(item) && item.status !== "unknown" && <span className={styles.live}>{text("Live", "实时")}</span>}
        </h4>
        {item.truncated && <p className={styles.empty}>{text("Earlier output was truncated; the process record is retained.", "较早的输出已截断，程序记录仍然保留。")}</p>}
        <ProgramOutput output={processes.detail?.output || ""} live={processIsActive(item) && item.status !== "unknown"}
          empty={processes.detail ? text("No output yet.", "还没有输出。") : text("Loading output…", "正在读取输出…")} />
        <dl className={styles.facts}>
          {run && <><dt>{text("From", "来自")}</dt><dd><button type="button" className={styles.link} onClick={() => open({ kind: "run", id: run.root.execution_id })}>{runTitle(run.root)}</button></dd></>}
          {item.title && <><dt>{text("Program", "程序")}</dt><dd>{programName(item, text)}</dd></>}
          <dt>{text("Folder", "工作目录")}</dt><dd>{item.cwd || "—"}</dd>
          <dt>{text("Environment", "运行环境")}</dt><dd>{item.backend_id}</dd>
        </dl>
      </div>}
    </div>;
  }

  if (view?.kind === "always") {
    if (!alwaysOn) return <div className={styles.panel}>{backBar(toActivity)}<SidebarNotice>{text("This conversation's Agent is no longer always-on.", "这个会话的 Agent 已不再常驻。")}</SidebarNotice></div>;
    const look = alwaysStatus();
    const config = alwaysOn.config;
    return <div className={styles.panel}>
      {backBar(toActivity)}
      <div className={`${styles.scroll} min-h-0 overflow-y-auto p-[0_8px_16px]`}>
        <div className={`${styles.head} grid gap-[4px] p-[10px_8px_0]`}>
          <div className={styles.kind}>{alwaysOn.agent_id ? <AgentAvatarById agentId={alwaysOn.agent_id} size={16} /> : <Glyph name="clock-circle" tone="plan" />}{text("Always-on", "常驻")}{alwaysOn.agent_name ? ` · ${alwaysOn.agent_name}` : ""}</div>
          <h3 className={styles.title}>{conversationTitle || text("This conversation", "这个会话")}</h3>
          <Status tone={look.tone}>{look.label}</Status>
        </div>
        <p className={styles.note}>{text(
          "This conversation's Agent is set to be always on, so the conversation wakes on its own: it works on the standing goal, or checks in with read-only tools and reports what is worth your attention. Archive the conversation to stop it; change the schedule in Agents → Always-on.",
          "这个会话的 Agent 设为常驻，所以会话会自己唤醒：推进常驻目标，或用只读工具巡检，报告值得你关注的事。归档会话即可停止；在 Agents → 常驻 里修改计划。",
        )}</p>
        <div className={`${styles.actions} flex flex-wrap gap-[8px] mt-[10px]`} data-inline="1">
          <Button variant="elevated" size="xs" disabled={pending !== null || alwaysOn.running}
            onClick={() => void act(() => wakeConversation(sessionId), text("Could not wake it.", "未能唤醒。"))}>
            {pending ? text("Waking…", "正在唤醒…") : text("Wake now", "立即唤醒")}</Button>
        </div>
        {actionError && <p role="alert" className={styles.error}>{actionError}</p>}
        <dl className={styles.facts}>
          {config?.goal && <><dt>{text("Standing goal", "常驻目标")}</dt><dd>{config.goal}</dd></>}
          {alwaysOn.goal && <><dt>{text("Goal", "目标")}</dt><dd>{goalStatusLabel(alwaysOn.goal.status, text)}</dd></>}
          {config && <><dt>{text("Wakes every", "唤醒间隔")}</dt><dd>{duration(config.wake_minutes * 60, text)}</dd></>}
          {config && scheduleLabel(config, text) && <><dt>{text("Wakes when", "唤醒时间")}</dt><dd>{scheduleLabel(config, text)}</dd></>}
          <dt>{text("Last wake", "上次唤醒")}</dt>
          <dd>{alwaysOn.last_wake ? `${outcomeLabel(alwaysOn.last_wake.outcome, text)} · ${when(alwaysOn.last_wake.at, text)}` : text("Not yet", "还没有")}</dd>
          <dt>{text("Next wake", "下次唤醒")}</dt>
          <dd>{alwaysOn.next_wake_at ? updatedTime(alwaysOn.next_wake_at) : text("After its next use", "下次使用后")}</dd>
        </dl>
        <h4 className={styles.section}>{text("Reports", "报告")}</h4>
        {alwaysOn.reports.length === 0
          ? <p className={styles.empty}>{text("No reports yet.", "还没有报告。")}</p>
          : alwaysOn.reports.map(report => <div className={styles.issue} key={report.id}>
            <h4 className={styles.issueTitle}>{report.title}</h4>
            <p className={styles.choices}>{updatedTime(report.at)}</p>
            {report.body && <p className={styles.issueText}>{report.body}</p>}
            {report.links.map(link => <p key={link} className={styles.issueText}><a className={styles.link} href={link} target="_blank" rel="noreferrer">{link}</a></p>)}
            {report.deliveries?.map(delivery => <p key={`${delivery.channel}:${delivery.account_id}:${delivery.peer_id}`}
              className={delivery.status === "failed" ? styles.error : styles.choices}>{deliveryLabel(delivery, text)}</p>)}
          </div>)}
      </div>
    </div>;
  }

  if (view?.kind === "work") {
    const item = ongoing?.open_work.find(entry => entry.id === view.id);
    if (!item) return <div className={styles.panel}>{backBar(toActivity)}<SidebarNotice>{text("This item is no longer listed.", "这一项已不在列表中。")}</SidebarNotice></div>;
    const done = item.status === "done";
    return <div className={styles.panel}>
      {backBar(toActivity)}
      <div className={`${styles.scroll} min-h-0 overflow-y-auto p-[0_8px_16px]`}>
        <div className={`${styles.head} grid gap-[4px] p-[10px_8px_0]`}>
          <div className={styles.kind}><Glyph name="checklist" tone="plan" />{text("Open work", "未完成事项")} · {updatedTime(item.created_at)}</div>
          <h3 className={styles.title}>{item.text}</h3>
          <Status tone={done ? "ok" : "muted"}>{done ? `${text("Done", "已完成")} · ${when(item.done_at ?? item.updated_at, text)}` : text("Open", "未完成")}</Status>
        </div>
        <p className={styles.note}>{text(
          "What the agent still owes you in this conversation. Open items are part of its instructions on every turn here.",
          "Agent 在这个会话里仍欠你的事。未完成的事项每一轮都写在它的指令里。",
        )}</p>
        <div className={`${styles.actions} flex flex-wrap gap-[8px] mt-[10px]`} data-inline="1">
          <Button variant="elevated" size="xs" disabled={pending !== null}
            onClick={() => void act(() => setOpenWorkStatus(sessionId, item.id, done ? "open" : "done"), text("Could not change it.", "未能修改。"))}>
            {done ? text("Reopen", "重新打开") : text("Mark done", "标为完成")}</Button>
          <Button variant="ghost" size="xs" disabled={pending !== null}
            onClick={async () => { if (await act(() => removeOpenWork(sessionId, item.id), text("Could not remove it.", "未能删除。"))) setStack(previous => previous.slice(0, -1)); }}>
            {text("Remove", "删除")}</Button>
        </div>
        {actionError && <p role="alert" className={styles.error}>{actionError}</p>}
        {item.note && <Long label={text("Note", "备注")} body={item.note} mono={false} open={taskOpen} onToggle={() => setTaskOpen(value => !value)} text={text} />}
      </div>
    </div>;
  }

  if (view?.kind === "routine") {
    const task = routines.find(entry => entry.id === view.id);
    if (!task) return <div className={styles.panel}>{backBar(toActivity)}<SidebarNotice>{text("This task is no longer listed.", "这个任务已不在列表中。")}</SidebarNotice></div>;
    const body = task.prompt || task.reminder || "";
    /** A value to paste elsewhere: Copy, then the value when it may be shown. */
    const copyRow = (key: string, label: string, value: string, shown?: string) => <>
      <dt>{label}</dt>
      <dd><button type="button" className={styles.link} onClick={() => void copy(key, value)}>{copied === key ? text("Copied", "已复制") : text("Copy", "复制")}</button>{shown ? ` · ${shown}` : ""}</dd>
    </>;
    return <div className={styles.panel}>
      {backBar(toActivity)}
      <div className={`${styles.scroll} min-h-0 overflow-y-auto p-[0_8px_16px]`}>
        <div className={`${styles.head} grid gap-[4px] p-[10px_8px_0]`}>
          <div className={styles.kind}><Glyph name={task.type === "webhook" ? "link" : "calendar"} tone="plan" />{text("Scheduled task", "定时任务")} · {updatedTime(task.created_at)}</div>
          <h3 className={styles.title}>{task.title}</h3>
          <Status tone={task.enabled === false ? "muted" : "ok"} dot={false}>{routineSchedule(task, text)}</Status>
        </div>
        <dl className={styles.facts}>
          {task.hook_url && copyRow("url", text("Address", "地址"), task.hook_url, task.hook_url)}
          {task.hook_key && copyRow("key", text("Key", "密钥"), task.hook_key)}
        </dl>
        {task.type === "webhook" && <p className={styles.note}>{text(
          "Send the key in the X-OpenProgram-Key header, or give it to GitHub as the webhook's secret. The request body reaches the run as data, never as instructions.",
          "在 X-OpenProgram-Key 请求头里带上密钥，或把它作为 GitHub webhook 的 secret。请求内容只作为数据交给这次运行，不会被当成指令。",
        )}</p>}
        {task.watch && <Long label={text("Runs when this check's output changes", "这个检查的输出变化时运行")} body={task.watch} mono open={taskOpen} onToggle={() => setTaskOpen(value => !value)} text={text} />}
        {body && <Long label={task.reminder ? text("Reminder", "提醒") : text("Task", "任务")} body={body} mono={false} open={taskOpen} onToggle={() => setTaskOpen(value => !value)} text={text} />}
        {task.command && <Long label={text("Command", "命令")} body={task.command} mono open={taskOpen} onToggle={() => setTaskOpen(value => !value)} text={text} />}
        <div className={`${styles.actions} flex flex-wrap gap-[8px] mt-[10px]`} data-inline="1">
          <Button variant="elevated" size="xs" onClick={() => navigate("/scheduler")}>{text("Open in Scheduler", "在定时任务中打开")}</Button>
        </div>
      </div>
    </div>;
  }

  // ---- overview ----------------------------------------------------------------
  // Messages live in the chat. Agents is the main agent alone: the
  // sub-agents it starts are summed up under it and listed on its page.
  // Programs and commands lists what they run in a shell.
  const showMain = scopes.length > 1 || fullTree.length > 0 || executions.some(item => !branches.parentOf(item)) || calls.some(entry => entry.status === "running");
  // Shell work: running and interrupted calls that are not sub-agents, and
  // background programs, live first, then the rest, newest first.
  const shellCalls = calls.filter(entry => presentTool(entry.name, undefined, text).tone !== "agent" && !agentOf(entry)
    && (entry.status === "running" || model.issues.some(issue => issue.kind === "call" && issue.call.id === entry.id)));
  const rank = (tone: Tone) => tone === "run" ? 0 : tone === "warn" ? 1 : 2;
  const work = [
    ...shellCalls.map(entry => ({ tone: (entry.status === "running" ? "run" : "muted") as Tone, at: entry.started_at, node: callRow(entry) })),
    ...processes.items.map(entry => ({ tone: programTone(entry), at: entry.started_at, node: programRow(entry) })),
  ].sort((a, b) => rank(a.tone) - rank(b.tone) || b.at - a.at);
  /** One overview group: its header folds the rows under it. Until its
   *  data is read it stays folded and does not open. */
  const section = (key: string, name: string, rows: ReactNode, ready = true) => {
    const collapsed = !ready || listView.collapsed.includes(key);
    return <div className="group/sec">
      <SectionHeader name={name} className={styles.sectionHeader} collapsible collapsed={collapsed}
        onToggle={() => { if (ready) toggleActivitySection(key); }} />
      {!collapsed && rows}
    </div>;
  };
  // Agents, Programs and commands and Scheduled tasks are always listed;
  // the other groups appear only when they have something in them.
  const agentsReady = Boolean(state.fetchedAt);
  const programsReady = agentsReady && processes.loaded;
  const scheduledReady = ongoing != null;
  return <section className={styles.panel} aria-label={text("Conversation activity", "会话运行记录")}>
    {readFailed && readNotice?.sessionId === sessionId && (hasRead || readNotice.persistent) && <p role="status" className={`${styles.notice} ${readNotice.persistent && !hasRead ? styles.error : ""}`}>{hasRead
      ? text("Updating status… Showing saved records.", "正在更新状态，当前显示上次记录。")
      : text("Activity is still unavailable. Retrying automatically.", "运行记录暂时无法读取，正在自动重试。")}</p>}
    <div className={`${styles.scroll} min-h-0 overflow-y-auto p-[0_8px_16px]`}>
      {section("agents", text("Agents", "Agents"), showMain ? scopes.map(scopeRow) : null, agentsReady)}
      {section("programs", text("Programs and commands", "程序和命令"), <>
        {work.slice(0, programsShown).map(entry => entry.node)}
        {work.length > programsShown && <Button type="button" variant="link" size="xs" onClick={() => setProgramsShown(value => value + 50)}>
          {text(`Show ${Math.min(50, work.length - programsShown)} earlier`, `显示更早的 ${Math.min(50, work.length - programsShown)} 个`)}
        </Button>}
      </>, programsReady)}
      {alwaysOn && section("always-on", text("Always-on", "常驻"), alwaysRow())}
      {openItems.length > 0 && section("open-work", text("Open work", "未完成事项"), openItems.map(openWorkRow))}
      {section("scheduled", text("Scheduled tasks", "定时任务"), routines.map(routineRow), scheduledReady)}
    </div>
  </section>;
}
