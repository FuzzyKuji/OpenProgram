"use client";

/**
 * Activity: what the conversation runs and keeps doing. Agents holds the
 * main agent, one per branch the reader made, with its sub-agents summed up
 * and a red count for what waits on the reader. Programs and commands holds
 * the shell calls and background programs. Then what the conversation does
 * on its own: its open work and the Scheduler tasks set from it. Always-on
 * is a setting of the conversation's Agent, not an agent of its own: the
 * main agent's row says when it wakes next. Above all of them, when there
 * are any, the reports from every always-on conversation still waiting for
 * the reader (the pending inbox); each opens its conversation. Every other
 * row opens one page (activity-page.tsx). Each overview section folds to its
 * header, like the sidebar's, and stays folded in this browser.
 */
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "@/lib/i18n";
import { useSessionStore } from "@/lib/session-store";
import { useExecutionDebugger } from "@/lib/execution/use-execution-debugger";
import { useManagedProcesses } from "@/lib/execution/use-managed-processes";
import { processIsActive, type ActiveToolCall, type AgentCall, type ManagedProcess } from "@/lib/net/execution/process-client";
import { type ExecutionSnapshot } from "@/lib/execution/execution-debugger";
import { activityModel, agentBranches, pruneBranches, spawnedBy, startedAt, type ActivityIssue, type BranchRow } from "@/lib/execution/activity-model";
import { toggleActivitySection, useActivityView } from "@/lib/prefs/activity-view";
import { loadSubAgentTranscript } from "@/lib/chat/transcript/sub-agent-transcripts";
import { sendRuntimeCommand } from "@/lib/runtime-bridge/session/session-load";
import { presentTool } from "@/components/chat/messages/execution/tool-presentation";
import { SectionHeader } from "@/components/sidebar/sessions/section-header";
import { Button } from "@/components/ui/button";
import { SidebarNotice } from "../sidebar-notice";
import { useConversationBranches } from "../use-conversation-branches";
import { useSessionWorktrees } from "@/lib/worktrees/session-worktrees";
import { branchWorktree, changedFiles, isOpen } from "@/lib/worktrees/worktree-model";
import { useConversationWork, type OpenWorkItem, type Routine } from "@/lib/chat/conversation-work";
import { AgentAvatarById, useConversationAgentShape } from "@/components/agents/agent-avatar";
import { goalStatusLabel, outcomeLabel, reportKindTag } from "@/components/agents/always-on-labels";
import { copyText } from "@/lib/clipboard";
import { openPendingItem, pendingInOrder, usePendingInbox, type PendingItem } from "@/lib/agents/pending-inbox";
import { clock, ProgressBar, progressLook } from "./program-progress";
import styles from "./running-panel.module.css";
import { ActivityPage } from "./activity-page";
import { usePageSlide } from "./use-page-slide";
import type { ActivityPageTarget, ActivityPanelContext } from "./activity-page-types";
import { Glyph, AgentGlyph, Status, Row, type Tone } from "./running-rows";
import { LIVE, duration, when, callKind, executionTone, executionState, programTone, programTitle, commandLine, programStatus, programBarTone, routineSchedule, routineRunLabel } from "./running-format";

type View = { kind: "main" | "call" | "program" | "work" | "routine"; id: string };

const PAGE = 20;

/** What a level-1 row opens. */
function pageFor(view: View): ActivityPageTarget {
  switch (view.kind) {
    case "main": return { kind: "agent", scopeKey: view.id };
    case "program": return { kind: "program", processId: view.id };
    case "call": return { kind: "command", callId: view.id };
    case "routine": return { kind: "routine", taskId: view.id };
    case "work": return { kind: "work", workId: view.id };
  }
}

export function RunningPanel({ active, sessionId, resetSignal }: { active: boolean; sessionId: string | null; resetSignal?: number }) {
  const { text } = useTranslation();
  // One page at a time, opened from level 1 and tied to its conversation.
  const [opened, setOpened] = useState<{ sessionId: string | null; target: ActivityPageTarget } | null>(null);
  const page = opened && opened.sessionId === sessionId ? opened.target : null;
  // Each open run reads its own record, so the shared inspector stays off.
  const state = useExecutionDebugger(active, sessionId, undefined, false);
  const processes = useManagedProcesses(active, sessionId, page?.kind === "program" ? page.processId : null);
  const { work: ongoing, refresh: refreshOngoing } = useConversationWork(active, sessionId);
  // Reports from every always-on conversation still waiting for the user.
  const pendingInbox = usePendingInbox();
  const [copied, setCopied] = useState<string | null>(null);
  const conversationTitle = useSessionStore(s => (sessionId ? s.conversations[sessionId]?.title : undefined) || "");
  // A conversation whose turns left no execution record still has its main
  // agent: resting, its row reads the conversation's last activity.
  const conversationUpdatedAt = useSessionStore(s => (sessionId ? s.conversations[sessionId]?.updated_at : undefined) ?? null);
  // The main agent's rows wear the conversation Agent's character.
  const mainShape = useConversationAgentShape(sessionId);
  // Questions and approvals are answered in the chat's input box, which
  // shows each one with its choices; Activity says what is asked and goes there.
  const allDecisions = useSessionStore(s => s.pendingDecisions);
  const listView = useActivityView();
  const conversationBranches = useConversationBranches(sessionId);
  // A branch running in its own git worktree wears a Worktree tag.
  const worktrees = useSessionWorktrees(sessionId);
  const selectedBranchId = useSessionStore(s => (sessionId ? s.composerSettingsBySession[sessionId]?.active_branch_id ?? null : null));
  const [programsShown, setProgramsShown] = useState(PAGE);
  const [pending, setPending] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // Level 1 leaves the document while a page rests over it; its scroll and
  // opener come back with it. A page slides in over it and off again.
  const levelOneScroll = useRef<HTMLDivElement>(null);
  const levelOneReturn = useRef({ scrollTop: 0, opener: -1, focus: false });
  const slide = usePageSlide(() => setOpened(null));
  const { cut: cutSlide, leave: leaveSlide } = slide;
  const overviewShown = !page || slide.beneath;
  useEffect(() => { cutSlide(); setOpened(null); setProgramsShown(PAGE); }, [sessionId, cutSlide]);
  useLayoutEffect(() => {
    const element = levelOneScroll.current;
    if (overviewShown && element) element.scrollTop = levelOneReturn.current.scrollTop;
  }, [overviewShown]);
  useLayoutEffect(() => {
    const element = levelOneScroll.current;
    const saved = levelOneReturn.current;
    if (page || !element || !saved.focus) return;
    saved.focus = false;
    const buttons = element.querySelectorAll<HTMLElement>("button");
    (buttons[saved.opener] ?? buttons[0])?.focus({ preventScroll: true });
  }, [page]);
  // Clicking Activity in the rail while already on it returns to level 1.
  useEffect(() => {
    if (!resetSignal) return;
    levelOneReturn.current.focus = false;
    leaveSlide();
  }, [resetSignal, leaveSlide]);
  useEffect(() => { setActionError(null); }, [page]);
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
  const open = (next: View) => {
    const target = pageFor(next);
    const element = levelOneScroll.current;
    if (element) levelOneReturn.current = { scrollTop: element.scrollTop, opener: [...element.querySelectorAll("button")].indexOf(document.activeElement as HTMLButtonElement), focus: false };
    slide.enter();
    setOpened({ sessionId, target });
  };
  const execution = (id: string) => executions.find(item => item.execution_id === id) ?? null;
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
  type Scope = { key: string; branchId?: string; head: string | null; name: string; active: boolean; color: string | null; updatedAt: number | null; members: Set<string> | null };
  const scopes: Scope[] = conversationBranches.length > 1
    ? conversationBranches.map(branch => ({ key: branch.branchId || branch.head, branchId: branch.branchId, head: branch.head, active: branch.active, color: branch.color, updatedAt: branch.updatedAt,
      name: branch.name || text("Unnamed branch", "未命名分支"), members: memberships.get(branch.head) ?? new Set<string>() }))
    : [{ key: "main", head: null, name: mainName, active: true, color: null, updatedAt: conversationUpdatedAt, members: null }];
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
  function switchTo(head: string, branchId?: string) {
    sendRuntimeCommand({ action: "checkout_branch", session_id: sessionId, head_msg_id: head, branch_id: branchId });
    sendRuntimeCommand({ action: "load_session", session_id: sessionId });
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
    const currentTag = scope.head && scope.active ? <span className={styles.current}>{text("Current", "当前")}</span> : null;
    const tree = branchWorktree(worktrees.rows, scope.branchId ?? (scope.active ? selectedBranchId : null));
    const isolated = tree && isOpen(tree) ? tree : null;
    const current = currentTag || isolated ? <>{currentTag}{isolated && <span className={styles.current}>{text("Worktree", "Worktree")}</span>}</> : null;
    const isolatedFiles = isolated ? changedFiles(isolated) : 0;
    const worktreeNote = isolated ? text(`${isolatedFiles} ${isolatedFiles === 1 ? "file" : "files"} in worktree`, `worktree 中 ${isolatedFiles} 个文件`) : "";
    // Always-on belongs to the checked-out branch: check-ins start from it.
    const always = alwaysOn && scope.active ? alwaysStatus() : null;
    return <Row key={scope.key} glyph={<AgentGlyph shape={mainShape} color={scope.color} />} title={scope.name} badge={current} count={waiting}
      status={[look.label, subs, worktreeNote].filter(Boolean).join(" · ")} tone={look.tone === "warn" ? "muted" : look.tone}
      extra={always && <Status tone={always.tone} dot={false}>{`${text("Always-on", "常驻")} · ${always.label}`}</Status>}
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
    // A paused budget or an interrupted check-in is what the reader needs to see first.
    const held = alwaysOn.last_wake?.outcome === "budget" || alwaysOn.last_wake?.outcome === "interrupted"
      ? outcomeLabel(alwaysOn.last_wake.outcome, text) : "";
    return { label: [held || goal, next].filter(Boolean).join(" · "), tone: alwaysOn.last_wake?.outcome === "interrupted" ? "warn" : "muted" };
  }
  function pendingRow(item: PendingItem): ReactNode {
    return <Row key={`pending:${item.session_id}:${item.report_id}`}
      glyph={<span className="grid size-[22px] flex-none place-items-center"><AgentAvatarById agentId={item.agent_id} size={20} /></span>}
      title={item.title} status={[reportKindTag(item.kind, text), item.agent_name, when(item.at, text)].join(" · ")}
      tone={item.kind === "approval" ? "warn" : "muted"} onOpen={() => openPendingItem(item)} />;
  }
  function openWorkRow(item: OpenWorkItem): ReactNode {
    return <Row key={`work:${item.id}`} glyph={<Glyph name="checklist" tone="plan" large />} title={item.text}
      status={[item.status === "done" ? text("Done", "已完成") : text("Open", "未完成"), when(item.updated_at, text)].join(" · ")}
      tone={item.status === "done" ? "ok" : "muted"} onOpen={() => open({ kind: "work", id: item.id })} />;
  }
  function routineRow(task: Routine): ReactNode {
    return <Row key={`routine:${task.id}`} glyph={<Glyph name={task.type === "webhook" ? "link" : "calendar"} tone="plan" large />}
      title={task.title} sub={task.watch} tone={task.runs?.[0]?.status === "failed" ? "warn" : "muted"}
      status={[routineSchedule(task, text), task.runs?.[0] && routineRunLabel(task.runs[0], text)].filter(Boolean).join(" · ")}
      onOpen={() => open({ kind: "routine", id: task.id })} />;
  }
  async function act(run: () => Promise<unknown>, failed: string, key?: string) {
    setPending(key ?? "act"); setActionError(null);
    try { await run(); refreshOngoing(); return true; }
    catch (cause) { setActionError(`${failed} ${cause instanceof Error ? cause.message : ""}`.trim()); return false; }
    finally { setPending(null); }
  }
  async function copy(key: string, value: string) {
    if (await copyText(value)) { setCopied(key); setTimeout(() => setCopied(current => current === key ? null : current), 1500); }
  }

  // ---- the sub-agent tree ------------------------------------------------------
  const rowKey = (row: BranchRow<AgentCall>) => row.kind === "agent" ? row.item.execution_id : `spawn:${row.leaf.id}`;
  const looks = new Map(fullTree.map(row => [rowKey(row), row.kind === "agent" ? agentLook(row.item) : { tone: (row.leaf.failed ? "err" : "muted") as Tone, at: row.leaf.at }]));
  const lookOf = (row: BranchRow<AgentCall>) => looks.get(rowKey(row)) ?? { tone: "muted" as Tone, at: 0 };
  // ---- second-level pages -------------------------------------------------------
  let pageLayer: ReactNode = null;
  if (page) {
    const scopeHeadText: ActivityPanelContext["scopeHeadText"] = scope => {
      const { label, tone } = scopeStatus(scopeFacts(scope), scope);
      return {
        kind: scope.head ? (scope.active ? `${text("Branch", "分支")} · ${text("Current", "当前")}` : text("Branch", "分支")) : mainName,
        title: scope.head ? scope.name : conversationTitle || mainName,
        status: label, tone,
      };
    };
    const waitingFor: ActivityPanelContext["waitingFor"] = item => {
      const decision = item.status === "paused" ? decisionFor(item.execution_id) : undefined;
      if (decision) {
        const approval = decision.kind === "approval";
        return {
          answerLabel: approval ? text("Review in chat", "去聊天里授权") : text("Answer in chat", "去聊天里回答"),
          question: decision.prompt || decision.questions?.[0]?.prompt || "",
          choices: decision.options?.length ? decision.options : decision.questions?.[0]?.options ?? [],
          waitLabel: approval ? text("Waiting for approval", "等你授权") : text("Waiting for your answer", "等你回答"),
        };
      }
      if (item.status === "paused" && item.reason_code === "wait_open") return { answerLabel: "", question: "", choices: [], waitLabel: text("Waiting for your answer", "等你回答") };
      return null;
    };
    const context: ActivityPanelContext = {
      sessionId, text, now, active,
      connected: state.connection.state === "connected",
      controller: state, processes, work: ongoing, refreshWork: refreshOngoing,
      scopes, scopeOf, scopeHeadText, waitingFor,
      answerInChat: item => {
        const decision = decisionFor(item.execution_id);
        if (decision) answerInChat(decision.id); else useSessionStore.getState().focusComposer();
      },
      switchTo: scope => { if (scope.head) switchTo(scope.head, scope.branchId); },
      openAgentConversation: jobId => {
        const job = execution(jobId);
        void (async () => {
          const target = await loadSubAgentTranscript(sessionId, jobId, { jobId, headId: job?.display?.assistant_message_id }) || job?.display?.assistant_message_id;
          if (!target) return;
          sendRuntimeCommand({ action: "checkout_branch", session_id: sessionId, head_msg_id: target });
          sendRuntimeCommand({ action: "load_session", session_id: sessionId });
        })();
      },
      alwaysStatus, act, pendingKey: pending, actionError, copy: (key, value) => void copy(key, value), copiedKey: copied,
      close: () => { levelOneReturn.current.focus = true; slide.leave(); },
      pull: slide.pull,
    };
    pageLayer = <div ref={slide.layer} className={styles.page}><ActivityPage key={JSON.stringify(page)} target={page} context={context} /></div>;
  }

  // ---- overview ----------------------------------------------------------------
  // Messages live in the chat. Agents is the main agent alone: the
  // sub-agents it starts are summed up under it and listed on its page.
  // Every conversation has its main agent, so its row is always there; its
  // page reads the runs from the transcript, with or without execution
  // records. Programs and commands lists what they run in a shell.
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
  // Agents is always listed; every other group, header included, appears
  // only when it has something in it.
  const agentsReady = Boolean(state.fetchedAt);
  const programsReady = agentsReady && processes.loaded;
  const scheduledReady = ongoing != null;
  return <>{overviewShown ? <section ref={slide.under} className={styles.panel} aria-label={text("Conversation activity", "会话运行记录")} inert={Boolean(page)}>
    {readFailed && readNotice?.sessionId === sessionId && (hasRead || readNotice.persistent) && <p role="status" className={`${styles.notice} ${readNotice.persistent && !hasRead ? styles.error : ""}`}>{hasRead
      ? text("Updating status… Showing saved records.", "正在更新状态，当前显示上次记录。")
      : text("Activity is still unavailable. Retrying automatically.", "运行记录暂时无法读取，正在自动重试。")}</p>}
    <div ref={levelOneScroll} className={`${styles.scroll} min-h-0 overflow-y-auto p-[0_8px_16px]`}>
      {pendingInbox.items.length > 0 && section("pending",
        text(`Waiting for you · ${pendingInbox.items.length}`, `等你处理 · ${pendingInbox.items.length}`),
        pendingInOrder(pendingInbox.items).map(pendingRow))}
      {section("agents", text("Agents", "Agents"), scopes.map(scopeRow), agentsReady)}
      {work.length > 0 && section("programs", text("Programs and commands", "程序和命令"), <>
        {work.slice(0, programsShown).map(entry => entry.node)}
        {work.length > programsShown && <Button type="button" variant="link" size="xs" onClick={() => setProgramsShown(value => value + 50)}>
          {text(`Show ${Math.min(50, work.length - programsShown)} earlier`, `显示更早的 ${Math.min(50, work.length - programsShown)} 个`)}
        </Button>}
      </>, programsReady)}
      {openItems.length > 0 && section("open-work", text("Open work", "未完成事项"), openItems.map(openWorkRow))}
      {routines.length > 0 && section("scheduled", text("Scheduled tasks", "定时任务"), routines.map(routineRow), scheduledReady)}
    </div>
  </section> : null}{pageLayer}</>;
}
