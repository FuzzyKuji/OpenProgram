"use client";

// The agent's task list, drawn under the reply of the turn that last
// changed it (lib/chat/transcript/todo-plan.ts). While that turn runs the
// list is open and follows the agent; once the turn ends it folds to one
// line, "Tasks 2/5 · Stopped", that opens on click. A later turn that
// changes the plan draws its own copy under itself, so earlier turns keep
// theirs as they left it.

import { useEffect, useId, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import { SolarIcon } from "@/components/solar-icons";
import { useSessionStore } from "@/lib/session-store";
import {
  planSummary,
  turnState,
  useTodoStore,
  type PlacedPlan,
  type TodoStatus,
  type TurnState,
} from "@/lib/chat/transcript/todo-plan";
import { useTranslation } from "@/lib/i18n";
import styles from "./todo-plan-card.module.css";

const EMPTY: PlacedPlan[] = [];

// Lists the reader opened stay open when the transcript draws them again
// (a session switch, a split pane).
const opened = new Set<string>();

/** How the turn whose reply `rowId` is stands, read the way the reply
 *  bubble reads it. */
function useTurnState(sessionId: string, rowId: string): TurnState {
  return useSessionStore((s) => turnState(
    s.messagesById[rowId],
    Object.values(s.executionUpdateOrders).some((order) =>
      order.terminal && order.sessionId === sessionId && order.messageIds.includes(rowId)),
  ));
}

function StatusIcon({ status, live }: { status: TodoStatus; live: boolean }) {
  if (status === "completed") {
    return <SolarIcon name="check-circle" size={16} motionPreset="none" className={styles.icon} data-status="completed" aria-hidden="true" />;
  }
  if (status === "in_progress") {
    return (
      <span className={`${styles.icon} relative inline-flex size-4 shrink-0`} data-status="in_progress" data-live={live ? "" : undefined} aria-hidden="true">
        <SolarIcon name="record" size={16} motionPreset="none" />
      </span>
    );
  }
  return <span className={`${styles.icon} ${styles.ring} inline-flex size-4 shrink-0`} data-status="pending" aria-hidden="true" />;
}

function PlanItems({ plan, live, id }: { plan: PlacedPlan; live: boolean; id?: string }) {
  const { text } = useTranslation();
  const statusLabel: Record<TodoStatus, string> = {
    completed: text("Done", "已完成"),
    in_progress: text("In progress", "进行中"),
    pending: text("To do", "待办"),
  };
  return (
    <ol id={id} className="m-0 flex list-none flex-col gap-[6px] px-[12px] py-[10px]">
      {plan.todos.map((item) => (
        <li key={item.id} className={`${styles.item} flex min-w-0 items-start gap-[10px]`} data-status={item.status}>
          <StatusIcon status={item.status} live={live} />
          <span className="sr-only">{statusLabel[item.status]}: </span>
          <span className={`${styles.subject} min-w-0`}>{item.subject}</span>
        </li>
      ))}
    </ol>
  );
}

function TodoPlan({ sessionId, rowId, plan }: { sessionId: string; rowId: string; plan: PlacedPlan }) {
  const { text } = useTranslation();
  const listId = useId();
  const state = useTurnState(sessionId, rowId);
  const key = `${sessionId}\n${plan.anchorId}\n${plan.planId}`;
  const [open, setOpen] = useState(() => opened.has(key));
  const foldRef = useRef<HTMLDivElement>(null);
  const live = state === "running";
  // A folded list keeps its rows for the open animation; focus and
  // reading skip them.
  useEffect(() => { foldRef.current?.toggleAttribute("inert", !open); }, [open, live]);
  const { done, total, outcome } = planSummary(plan, state);
  const outcomeLabel = outcome === "done" ? text("Done", "已完成")
    : outcome === "stopped" ? text("Stopped", "已停止")
      : outcome === "failed" ? text("Failed", "出错")
        : null;
  const toggle = () => {
    const next = !open;
    if (next) opened.add(key);
    else opened.delete(key);
    setOpen(next);
  };
  return (
    <section
      className={`${styles.card} w-full min-w-0 shrink-0`}
      data-todo-plan={plan.planId}
      data-anchor={rowId}
      data-live={live ? "" : undefined}
      data-open={live || open ? "1" : "0"}
      aria-label={text("Task list", "任务清单")}
    >
      {live ? <PlanItems plan={plan} live /> : (
        <>
          <button
            type="button"
            className={`${styles.line} flex w-full min-w-0 items-center gap-[8px] px-[12px]`}
            aria-expanded={open}
            aria-controls={listId}
            onClick={toggle}
          >
            <SolarIcon name="checklist" size={16} motionPreset="none" className={styles.lineIcon} aria-hidden="true" />
            <span className="min-w-0 truncate">
              {`${text("Tasks", "任务")} ${done}/${total}${outcomeLabel ? ` · ${outcomeLabel}` : ""}`}
            </span>
            <ChevronRight size={14} className={styles.chevron} aria-hidden="true" />
          </button>
          <div ref={foldRef} className={styles.fold}>
            <div className="min-h-0 overflow-hidden">
              <PlanItems plan={plan} live={false} id={listId} />
            </div>
          </div>
        </>
      )}
    </section>
  );
}

/** The plans placed under the reply `rowId`, given or looked up. */
export function TodoPlans({ sessionId, rowId, plans }: {
  sessionId: string | null;
  rowId: string;
  plans?: readonly PlacedPlan[];
}) {
  const stored = useTodoStore((s) => (sessionId && !plans ? s.plansBySession[sessionId] : undefined) ?? EMPTY);
  if (!sessionId) return null;
  const list = plans ?? stored.filter((plan) => plan.anchorId === rowId);
  if (!list.length) return null;
  return <>{list.map((plan) => <TodoPlan key={`${plan.anchorId}:${plan.planId}`} sessionId={sessionId} rowId={rowId} plan={plan} />)}</>;
}

/** Every session's placed plans, for the transcript to look up by row. */
export function useSessionPlans(sessionId: string | null): readonly PlacedPlan[] {
  return useTodoStore((s) => (sessionId ? s.plansBySession[sessionId] : undefined) ?? EMPTY);
}
