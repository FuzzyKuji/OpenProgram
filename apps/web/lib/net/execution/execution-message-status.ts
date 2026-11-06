/** How an execution's status reaches the transcript rows of its turn. */

type Row = { role?: string; status?: string };

const TERMINAL = new Set(["cancelled", "completed", "failed", "interrupted", "error", "done"]);
const SETTLED_REPLY = new Set(["done", "completed", "error", "cancelled", "interrupted"]);

/** The message status a turn's row takes for its execution's status. */
export function messageStatusForExecution(status: string): string {
  switch (status) {
    case "completed":
    case "done":
      return "done";
    case "failed":
    case "error":
      return "error";
    case "cancelled":
    case "interrupted":
    case "cancelling":
    case "paused":
      return status;
    default:
      return "running";
  }
}

/**
 * The rows an execution update restyles, with the status each takes. A run
 * row keyed by the execution id takes the status as it is. A pause for
 * system access marks the turn's own rows, and every later status moves
 * those rows back out of it. Rows of the turn that are not paused keep their
 * status: the stream and its result frame settle them. A settled row never
 * goes back to a live status.
 */
export function executionStatusUpdates(
  rows: Record<string, Row | undefined>,
  executionId: string,
  messageIds: string[],
  status: string,
  reasonCode?: string,
): Array<[string, string]> {
  const display = status === "paused" && reasonCode === "system_access_required" ? "paused" : status;
  const updates: Array<[string, string]> = [];
  for (const id of new Set([executionId, ...messageIds])) {
    const row = rows[id];
    if (!row || (TERMINAL.has(String(row.status)) && !TERMINAL.has(status))) continue;
    const ownsTurn = messageIds.includes(id);
    if (display === "paused" ? ownsTurn : id === executionId) updates.push([id, display]);
    else if (ownsTurn && row.status === "paused") updates.push([id, messageStatusForExecution(status)]);
  }
  return updates;
}

/** Whether a finished execution's reply still needs the persisted transcript:
 *  its row is missing or the stream never settled it. A reload resets the
 *  history window and drops client-only rows, so a settled reply skips it. */
export function turnReplyUnsettled(
  rows: Record<string, Row | undefined>,
  executionId: string,
  messageIds: string[],
): boolean {
  const ids = new Set([executionId, ...messageIds, ...messageIds.map((id) => `${id}_reply`)]);
  const replies = [...ids].map((id) => rows[id]).filter((row) => row?.role === "assistant");
  return !replies.length || replies.some((row) => !SETTLED_REPLY.has(String(row?.status)));
}
