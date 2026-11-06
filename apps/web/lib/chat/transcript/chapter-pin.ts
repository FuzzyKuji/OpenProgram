/**
 * Pin or unpin a turn as a chapter over the shared WebSocket.
 *
 *   send:  {action: "set_message_chapter", session_id, message_id, pinned, request_id}
 *   reply: the broadcast {type: "message_chapter_updated",
 *          data: {session_id, message_id, chapter: {pinned_at} | null, request_id, action}}
 *
 * The broadcast reaches every open window (lib/net/ws/use-ws.ts applies it
 * through `applyChapterFrame`); the requesting one also takes it as its
 * reply. The store changes at once and goes back if the server refuses.
 */
import { useSessionStore } from "@/lib/session-store";
import { wsRequest } from "@/lib/net/ws/ws-request";

import { chapterPinnedAt } from "./chapter.ts";

export type ChapterFrame = {
  session_id?: unknown;
  message_id?: unknown;
  chapter?: unknown;
  status?: string;
};

/** Apply one `message_chapter_updated` frame to the store. */
export function applyChapterFrame(data: ChapterFrame | null | undefined): void {
  if (!data || typeof data.message_id !== "string" || typeof data.session_id !== "string") return;
  useSessionStore.getState().updateMessage(data.session_id, data.message_id, {
    chapterPinnedAt: chapterPinnedAt(data.chapter),
  });
}

/** Pin (`pinned` true) or unpin the turn `messageId` (a user message)
 *  starts. Resolves true when the server stored it. */
export async function setTurnChapter(
  sessionId: string,
  messageId: string,
  pinned: boolean,
): Promise<boolean> {
  const store = useSessionStore.getState();
  const before = store.messagesById[messageId]?.chapterPinnedAt;
  store.updateMessage(sessionId, messageId, {
    chapterPinnedAt: pinned ? Date.now() / 1000 : undefined,
  });
  const reply = await wsRequest<ChapterFrame>(
    "set_message_chapter",
    { session_id: sessionId, message_id: messageId, pinned },
    "message_chapter_updated",
    { requestId: true },
  );
  if (!reply || reply.status === "error") {
    useSessionStore.getState().updateMessage(sessionId, messageId, { chapterPinnedAt: before });
    return false;
  }
  applyChapterFrame(reply);
  return true;
}
