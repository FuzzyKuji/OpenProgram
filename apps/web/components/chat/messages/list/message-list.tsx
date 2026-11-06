"use client";
import { TranscriptReadStatus } from "./transcript-read-status";

/**
 * Message list — the React message stream.
 *
 * Portaled into `#messages-mount` (a `display:contents` host inside the
 * legacy `#chatMessages` container), so each rendered bubble becomes a
 * direct flex child of `#chatMessages` — the same layout the legacy
 * renderer produced.
 *
 * The active conversation comes from the store's `currentSessionId`,
 * kept in sync by the `chat_ack` reducer and the route effect in
 * `app-shell.tsx`. Each `MessageRow` subscribes to its own message
 * entry so a streaming delta re-renders only the affected bubble.
 */
import {
  memo,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { useMessageViewport } from "./use-message-viewport";
import { useHistoryWindow } from "./use-history-window";
import { useChatAreaStick } from "./use-chat-area-stick";
import { ArrowDown } from "lucide-react";
import { Button } from "@/components/ui/button";

import { useMessageIds, useSessionStore } from "@/lib/session-store";

import { useTranslation } from "@/lib/i18n";
import { runtimeState } from "@/lib/runtime-bridge/state";
import { RECYCLE_MIN_ROWS, collectAlwaysLive, decideLiveRows, foldKey, heightsFor, noteChatWidth, setRowHeight, type WindowNode } from "@/lib/chat/history/message-window";

import { GoalDetails, useSessionGoal } from "../../badges/goal-chip";
import { DecisionOutputs, useDecisionAnchors } from "../runtime/decision-output";
import { SystemAccessWaits } from "../runtime/system-access-waits";
import { TodoPlans, useSessionPlans } from "../cards/todo-plan-card";
import { plansByRow } from "@/lib/chat/transcript/todo-plan";
import { MessageRail } from "../navigation/message-rail";
import { ConversationFind } from "../navigation/conversation-find";
import { AgentBranchBanner } from "../cards/agent-branch-banner";
import { BranchedFromBanner } from "../cards/branched-from-banner";
import { SelectionQuote } from "../editing/quote-to-chat";
import { originalsOpen, originalsSubs } from "./rows/system-event-rows";
import { MessageRow, PlainRow, RecyclableRow } from "./rows/message-rows";
import { PendingReplyIndicator, TranscriptSkeleton, WorkspaceAlignmentBanner } from "./rows/list-states";

const JUMP_LATEST_FADE_MS = 280;

export const MessageList = memo(function MessageList({
  paintRows = true,
}: {
  paintRows?: boolean;
}) {
  const { text } = useTranslation();
  const sessionId = useSessionStore((s) => s.currentSessionId);
  const chatKey = useSessionStore((s) => s.activeChatKey);
  const goal = useSessionGoal(sessionId);
  const endRecords = goal?.end_records ?? [];
  useHistoryWindow(sessionId, paintRows);
  const ids = useMessageIds(sessionId);
  const [, setOrigTick] = useState(0);
  useEffect(() => {
    const fn = () => setOrigTick((n) => n + 1);
    originalsSubs.add(fn);
    return () => { originalsSubs.delete(fn); };
  }, []);
  const hiddenCovered = new Set<string>();
  const coveredSet = new Set<string>();
  const snap = useSessionStore.getState();
  for (const id of ids) {
    const m = snap.messagesById[id];
    if (!m) continue;
    if (m.kind !== "compaction" || m.slot !== "card" || !m.coversIds?.length) continue;
    for (const cid of m.coversIds) {
      coveredSet.add(cid);
      if (!originalsOpen.has(m.id)) hiddenCovered.add(cid);
    }
  }
  const runningTask = useSessionStore((s) =>
    sessionId ? s.runningTasks[sessionId] ?? null : null,
  );
  // Pin to #chatView (column, not the scroller). Portal into #chatArea
  // puts absolute-bottom on the scroll content, so the button is off
  // screen exactly when we want it visible.
  const jumpHost = typeof document !== "undefined"
    ? document.getElementById("chatView")
    : null;
  // Only the LAST row's role matters here (see ``showPending`` below).
  // Subscribing to the whole ``messagesById`` map would re-render this
  // component — and re-map every id — on every single streaming delta,
  // because ``updateMessage`` returns a fresh map object each time.
  const lastId = ids.length ? ids[ids.length - 1] : null;
  const pendingAnchor = runtimeState._pendingExpandAttach?.anchor;
  const lastRole = useSessionStore((s) =>
    lastId && !s.messagesById[lastId]?.steeringReplyId ? (s.messagesById[lastId]?.role ?? null) : null,
  );
  const loadingId = useSessionStore((s) => s.transcriptLoadingId);
  const readStatus = useSessionStore(s => sessionId ? s.transcriptReadStatus[sessionId] : undefined);
  const { detached, jumpToLatest } = useChatAreaStick(
    chatKey,
    lastId,
    paintRows,
  );
  const [railTarget, setRailTarget] = useState<string | null>(null);
  const [findTarget, setFindTarget] = useState<string | null>(null);
  const alwaysLive = collectAlwaysLive(
    ids,
    (id) => snap.messagesById[id],
    [pendingAnchor, railTarget, findTarget],
  );
  const {view, notifyMeasured} = useMessageViewport(chatKey, ids.length, paintRows);
  const windowNodes: WindowNode[] = [];
  {
    let i = 0;
    while (i < ids.length) {
      const id = ids[i];
      if (coveredSet.has(id)) {
        const first = id;
        while (i < ids.length && coveredSet.has(ids[i])) i += 1;
        windowNodes.push({ kind: "fold", id: first });
      } else {
        windowNodes.push({ kind: "row", id });
        i += 1;
      }
    }
  }
  if (paintRows && chatKey && typeof document !== "undefined") {
    const areaW = document.getElementById("chatArea")?.clientWidth ?? 0;
    if (areaW > 0) noteChatWidth(chatKey, areaW);
  }
  const liveSet = paintRows && chatKey
    ? decideLiveRows({
        nodes: windowNodes,
        heights: heightsFor(chatKey),
        scrollTop: view.top,
        viewH: view.h,
        overscan: view.overscan,
        always: alwaysLive,
        listLen: ids.length,
        recycleMin: RECYCLE_MIN_ROWS,
      })
    : null;
  useLayoutEffect(() => {
    if (!paintRows || !chatKey || !liveSet) return;
    const root = document.getElementById("chatMessages");
    if (!root) return;
    let changed = false;
    root.querySelectorAll<HTMLElement>("[data-fold-id]").forEach((el) => {
      const fid = el.dataset.foldId;
      if (!fid) return;
      if (setRowHeight(chatKey, foldKey(fid), el.offsetHeight) !== "same") {
        changed = true;
      }
    });
    if (changed) notifyMeasured();
  });
  const [jumpShown, setJumpShown] = useState(false);
  const [jumpLeaving, setJumpLeaving] = useState(false);
  useEffect(() => {
    const want = paintRows && detached && ids.length > 0;
    if (want) {
      setJumpLeaving(false);
      setJumpShown(true);
      return;
    }
    if (!jumpShown) return;
    setJumpLeaving(true);
    const t = window.setTimeout(() => {
      setJumpShown(false);
      setJumpLeaving(false);
    }, JUMP_LATEST_FADE_MS);
    return () => window.clearTimeout(t);
  }, [detached, ids.length, jumpShown, paintRows]);

  // Parent-return actions: once the reload has rows on screen, reveal the
  // original sub-agent timeline row. Collapsed strips unmount their children,
  // so first open the exact strip indexed by branch head, then locate the row.
  // The flag is consumed only when the reveal actually runs, so a
  // mid-hydration re-render just reschedules it.
  useEffect(() => {
    if (!paintRows || !runtimeState._pendingExpandAttach || ids.length === 0) return;
    const esc = (v: string) =>
      window.CSS && CSS.escape ? CSS.escape(v) : v;
    const t = window.setTimeout(() => {
      const pend = runtimeState._pendingExpandAttach;
      if (!pend) return;
      runtimeState._pendingExpandAttach = null;
      const anchorEl = document.querySelector(
        '[data-msg-id="' + esc(pend.anchor) + '"], [data-msg-ids~="'
        + esc(pend.anchor) + '"]',
      ) as HTMLElement | null;
      anchorEl?.scrollIntoView({ block: "center" });
      const strip = anchorEl?.querySelector(
        '.tl[data-subagent-heads~="' + esc(pend.head) + '"]',
      ) as HTMLElement | null;
      if (strip?.getAttribute("data-open") === "0") {
        (strip.querySelector('.tl-toggle') as HTMLElement | null)?.click();
      }
      window.setTimeout(() => {
        const row = document.querySelector(
          '.tl-step[data-head-id="' + esc(pend.head) + '"]',
        ) as HTMLElement | null;
        const target = row || anchorEl;
        if (!target) return;
        target.scrollIntoView({ behavior: "smooth", block: "center" });
        target.classList.add("dag-flash");
        window.setTimeout(() => target.classList.remove("dag-flash"), 1400);
      }, 280);
    }, 250);
    return () => window.clearTimeout(t);
  }, [ids, paintRows]);

  // Fade the transcript in once per session switch, and only when its rows
  // arrive after the switch (the skeleton showed first). A session already
  // in the store swaps in at once: fading cached rows up from nothing only
  // reads as a flash. The ref remembers which session already settled, so
  // streaming updates (ids.length growing) don't re-trigger the animation.
  const lastFadedSession = useRef<string | null>(null);
  const waitedSession = useRef<string | null>(null);
  if (paintRows && sessionId && ids.length === 0) waitedSession.current = sessionId;
  useEffect(() => {
    if (!paintRows || !sessionId || ids.length === 0) return;
    if (lastFadedSession.current === sessionId) return;
    lastFadedSession.current = sessionId;
    if (waitedSession.current !== sessionId) return;
    const el = document.getElementById("chatMessages");
    if (!el) return;
    el.classList.add("session-enter");
    const t = setTimeout(() => el.classList.remove("session-enter"), 220);
    return () => {
      clearTimeout(t);
      el.classList.remove("session-enter");
    };
  }, [sessionId, ids.length, paintRows]);

  // Show the standalone indicator while we're still waiting on the
  // turn — either:
  //   * the assistant placeholder hasn't landed yet (last msg is the
  //     user turn we just sent), OR
  //   * the placeholder exists but is still empty (chat_ack landed
  //     but no text/thinking/tool deltas yet)
  // Once the bubble has ANY content, that bubble's own
  // TypingIndicator / streaming text takes over and we hide.
  // Only show the STANDALONE indicator when there's no assistant
  // placeholder yet — i.e. between user send and ``chat_ack``. Once
  // the assistant bubble exists (even empty), its own
  // ``TypingIndicator`` handles the empty-streaming state. Without
  // this guard the user sees two stacked "Agentic" rows: the real
  // placeholder bubble + the standalone, double-rendering.
  const showPending = runningTask !== null && lastRole === "user";
  const decisionAnchors = useDecisionAnchors(sessionId);
  // Each task list sits under the reply of the turn that last changed it.
  const sessionPlans = useSessionPlans(sessionId);
  const plansAt = plansByRow(sessionPlans, ids, snap.messagesById);
  const placedDecisionAnchors = useMemo(
    () => new Set([...decisionAnchors].filter(anchor => ids.includes(anchor))),
    [decisionAnchors, ids],
  );

  // Session switch with nothing cached yet: skeleton placeholder
  // instead of an empty area / welcome flash. Minimap etc. wait too.
  if (sessionId && (readStatus === "loading" || (!readStatus && loadingId === sessionId)) && ids.length === 0) {
    return <TranscriptSkeleton />;
  }

  return (
    <>
      <TranscriptReadStatus sessionId={sessionId} />
      <SelectionQuote key={sessionId} sessionId={sessionId} />
      <BranchedFromBanner />
      <AgentBranchBanner />
      <WorkspaceAlignmentBanner sessionId={sessionId} />
      {paintRows ? (
        <MessageRail hiddenKey={[...hiddenCovered].join("\n")} onSeek={setRailTarget} />
      ) : null}
      {paintRows ? <ConversationFind sessionId={sessionId} onTarget={setFindTarget} /> : null}
      {paintRows ? (() => {
        const nodes: ReactNode[] = [];
        const addGoalRecords = (anchors: (string | null)[]) => {
          if (!sessionId) return;
          for (const record of endRecords) {
            if (anchors.includes(record.anchor_id)) nodes.push(
              <GoalDetails key={`goal-end-${record.goal.goal_id}`} sessionId={sessionId}
                goal={record.goal} historical />,
            );
          }
        };
        const addTodoPlans = (anchors: string[]) => {
          for (const anchor of anchors) {
            const plans = plansAt.get(anchor);
            if (plans) nodes.push(
              <TodoPlans key={`plans-${anchor}`} sessionId={sessionId} rowId={anchor} plans={plans} />,
            );
          }
        };
        const addDecisionReceipts = (anchors: string[]) => {
          for (const anchor of anchors) {
            if (decisionAnchors.has(anchor)) nodes.push(
              <DecisionOutputs key={`decisions-${anchor}`} sessionId={sessionId} anchorId={anchor} />,
            );
          }
        };
        addGoalRecords([null]);
        let i = 0;
        while (i < ids.length) {
          const id = ids[i];
          if (coveredSet.has(id)) {
            const run: string[] = [];
            while (i < ids.length && coveredSet.has(ids[i])) {
              run.push(ids[i]);
              i += 1;
            }
            nodes.push(
              <div
                key={`${run[0]}_fold`}
                className="compaction-orig-fold"
                data-fold-id={run[0]}
                data-open={hiddenCovered.has(run[0]) ? "0" : "1"}
              >
                <div className="compaction-orig-fold-inner">
                  {run.map((cid) => (
                    <div key={cid} className="covered-turn">
                      <MessageRow id={cid} />
                    </div>
                  ))}
                </div>
              </div>,
            );
            addTodoPlans(run);
            addGoalRecords(run);
            addDecisionReceipts(run);
            continue;
          }
          nodes.push(
            liveSet && chatKey ? (
              <RecyclableRow
                key={id}
                id={id}
                chatKey={chatKey}
                live={liveSet.has(id)}
                onMeasured={notifyMeasured}
              />
            ) : (
              <PlainRow key={id} id={id} />
            ),
          );
          addTodoPlans([id]);
          addGoalRecords([id]);
          addDecisionReceipts([id]);
          i += 1;
        }
        return nodes;
      })() : null}
      {paintRows && showPending ? (
        <PendingReplyIndicator timestamp={runningTask?.started_at} />
      ) : null}
      {paintRows ? <DecisionOutputs key={`decisions-${sessionId}`} sessionId={sessionId} placed={placedDecisionAnchors} /> : null}
      {paintRows ? <SystemAccessWaits key={sessionId} sessionId={sessionId} /> : null}
      {paintRows && jumpShown && jumpHost
        ? createPortal(
            <div className={[
              "jump-latest-anchor",
              runningTask ? "is-live" : "",
              jumpLeaving ? "is-leaving" : "",
            ].filter(Boolean).join(" ")}>
              <Button
                type="button"
                variant="elevated"
                className="jump-latest"
                onClick={jumpToLatest}
              >
                {runningTask ? (
                  <span className="jump-latest-live" data-icon="inline-start" aria-hidden>
                    <i />
                    <i />
                    <i />
                  </span>
                ) : (
                  <ArrowDown data-icon="inline-start" aria-hidden />
                )}
                {text("Jump to latest", "跳到最新")}
              </Button>
            </div>,
            jumpHost,
          )
        : null}
    </>
  );
});
