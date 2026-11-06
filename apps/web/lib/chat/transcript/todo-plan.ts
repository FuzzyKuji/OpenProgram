// The agent's task list in the transcript. The backend records, for each
// turn that changed the session's todo board, the plan as that turn left it
// (openprogram/programs/tools/planning/todo/shared.py place_plan). Each of
// those placed plans is drawn under the reply of its turn: open and live
// while the turn runs, one line once it has ended.

import { create } from "zustand";
import type { ChatMsg } from "@/lib/session-store";

export type TodoStatus = "pending" | "in_progress" | "completed";

export interface TodoItem {
  id: string;
  subject: string;
  status: TodoStatus;
}

/** One plan as one turn left it. */
export interface PlacedPlan {
  /** The assistant reply of the turn that last changed this plan. */
  anchorId: string;
  /** The plan's first todo id: the same plan across turns. */
  planId: string;
  /** "" for the conversation's own agent, `agent:<id>` for a sub-agent. */
  scope: string;
  updatedAt: number;
  todos: TodoItem[];
}

function normalizeTodo(raw: unknown): TodoItem | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  const id = typeof row.id === "string" ? row.id : String(row.id ?? "");
  const subject = typeof row.subject === "string" ? row.subject.trim() : "";
  if (!id || !subject) return null;
  const status: TodoStatus = row.status === "in_progress" || row.status === "completed" ? row.status : "pending";
  return { id, subject, status };
}

function normalizePlan(raw: unknown): PlacedPlan | null {
  if (!raw || typeof raw !== "object") return null;
  const row = raw as Record<string, unknown>;
  const anchorId = typeof row.anchor_id === "string" ? row.anchor_id : "";
  const todos = Array.isArray(row.todos)
    ? row.todos.map(normalizeTodo).filter((todo): todo is TodoItem => todo !== null)
    : [];
  if (!anchorId || todos.length === 0) return null;
  return {
    anchorId,
    planId: typeof row.plan_id === "string" ? row.plan_id : String(row.plan_id ?? todos[0].id),
    scope: typeof row.scope === "string" ? row.scope : "",
    updatedAt: typeof row.updated_at === "number" ? row.updated_at : 0,
    todos,
  };
}

export function normalizePlans(raw: unknown): PlacedPlan[] {
  if (!Array.isArray(raw)) return [];
  return raw.map(normalizePlan).filter((plan): plan is PlacedPlan => plan !== null);
}

/** A reply a worker restart cut off is drawn by the reply that carries it
 *  on, so its plan goes there too. */
export function placedAnchor(anchorId: string, messagesById: Readonly<Record<string, ChatMsg | undefined>>): string {
  let id = anchorId;
  const seen = new Set<string>();
  for (;;) {
    const next = messagesById[id]?.continuedBy;
    if (!next || seen.has(next) || !messagesById[next]) return id;
    seen.add(id);
    id = next;
  }
}

/** The plans to draw under each transcript row, in the order they were
 *  first placed. Plans whose turn is not in the transcript (another
 *  branch, a sub-agent's own conversation, a page not loaded) are left out. */
export function plansByRow(
  plans: readonly PlacedPlan[],
  rowIds: readonly string[],
  messagesById: Readonly<Record<string, ChatMsg | undefined>>,
): Map<string, PlacedPlan[]> {
  const rows = new Set(rowIds);
  const out = new Map<string, PlacedPlan[]>();
  for (const plan of plans) {
    const row = placedAnchor(plan.anchorId, messagesById);
    if (!rows.has(row)) continue;
    const list = out.get(row);
    if (list) list.push(plan);
    else out.set(row, [plan]);
  }
  return out;
}

/** How the turn that placed a plan stands. */
export type TurnState = "running" | "ended" | "stopped" | "failed";

// The same statuses the reply bubble draws as streaming.
const LIVE = new Set(["pending", "streaming", "running", "cancelling"]);

/** `settled`: the turn's execution is already terminal although the reply
 *  has not caught up (the bubble reads it the same way). */
export function turnState(msg: ChatMsg | undefined, settled: boolean): TurnState {
  const status = msg?.status;
  if (status === "cancelled" || status === "interrupted" || status === "paused") return "stopped";
  if (status === "error") return "failed";
  if (status && LIVE.has(status) && !settled) return "running";
  return "ended";
}

export interface PlanSummary {
  done: number;
  total: number;
  /** Shown after the count on the one-line form, if anything. */
  outcome: "done" | "stopped" | "failed" | null;
}

export function planSummary(plan: PlacedPlan, state: TurnState): PlanSummary {
  const done = plan.todos.filter((todo) => todo.status === "completed").length;
  const total = plan.todos.length;
  const outcome = done === total ? "done" : state === "stopped" ? "stopped" : state === "failed" ? "failed" : null;
  return { done, total, outcome };
}

interface TodoState {
  plansBySession: Record<string, PlacedPlan[]>;
  setPlans(sessionId: string, plans: unknown): void;
}

export const useTodoStore = create<TodoState>((set) => ({
  plansBySession: {},
  setPlans: (sessionId, plans) => set((state) => ({
    plansBySession: { ...state.plansBySession, [sessionId]: normalizePlans(plans) },
  })),
}));
