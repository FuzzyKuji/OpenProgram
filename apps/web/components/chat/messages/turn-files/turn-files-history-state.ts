export type TurnHistoryOperation = "undo" | "revert" | "redo" | "reapply";

/** Why the history action is withheld, as reported by ``turn_history_state``. */
export type TurnHistoryReason =
  | "files_changed"
  | "not_recoverable"
  | "inactive_branch"
  | "agent_running"
  | "run_active"
  | "in_progress";

export interface TurnHistoryState {
  status: string;
  operation: TurnHistoryOperation | null;
  reason?: string;
  error?: string;
}

/** Notices keyed by reason; ``fallback`` covers states with no known reason. */
export type TurnHistoryNotices = Partial<Record<TurnHistoryReason, string>> & { fallback: string };

/**
 * Why the card's history action is withheld, shown in the hover tip of the
 * greyed action. A failed action reports its own error; otherwise the reason
 * picks the copy. Engine error text is never shown as the explanation.
 */
export function historyPresentation(
  state: TurnHistoryState | null,
  transientError: string,
  notices: TurnHistoryNotices,
) {
  if (transientError) return { notice: transientError, operation: null };
  if (state && state.status !== "ready") {
    const known = state.reason ? notices[state.reason as TurnHistoryReason] : undefined;
    return { notice: known || notices.fallback, operation: null };
  }
  return { notice: "", operation: state?.operation ?? null };
}
