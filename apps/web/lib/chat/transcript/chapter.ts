/**
 * Chapter pins: a turn the user pinned as a chapter of its conversation.
 *
 * The pin lives on the turn's USER message node (server
 * ``metadata.chapter = {"pinned_at": <epoch seconds>}``, None when
 * unpinned; ws_actions/session/chapter.py). The message rail tints a
 * pinned turn's tick in the theme accent, and a reply's action row pins or
 * unpins the turn above it. Pure helpers only; the WS action is in
 * ./chapter-pin.ts.
 */

/** The wire ``chapter`` pin as its pin time; undefined when unpinned. */
export function chapterPinnedAt(chapter: unknown): number | undefined {
  if (!chapter || typeof chapter !== "object") return undefined;
  const at = (chapter as { pinned_at?: unknown }).pinned_at;
  return typeof at === "number" && Number.isFinite(at) && at > 0 ? at : undefined;
}

type RoleRow = { role?: string; display?: string } | undefined;

// One pass per order array: every row maps to the user message that opened
// its turn. The order array is replaced whenever rows are added, removed or
// moved, and streaming deltas leave it alone, so a reply's action row reads
// its turn in O(1) on every store update.
const turnStarts = new WeakMap<readonly string[], Map<string, string>>();

/** The user message that starts the turn `msgId` belongs to: the nearest
 *  user message above it in the session's order, skipping runtime rows
 *  (the same rows the message rail draws ticks for). */
export function turnUserMessageId(
  order: readonly string[] | undefined,
  messagesById: Record<string, RoleRow>,
  msgId: string,
): string | undefined {
  if (!order || !order.length) return undefined;
  let starts = turnStarts.get(order);
  if (!starts) {
    starts = new Map();
    let current: string | undefined;
    for (const id of order) {
      const m = messagesById[id];
      if (m && m.role === "user" && m.display !== "runtime") current = id;
      if (current) starts.set(id, current);
    }
    turnStarts.set(order, starts);
  }
  return starts.get(msgId);
}
