/**
 * A reply frame without session_id belongs to the run that owns its msg_id,
 * never to the conversation on screen: after a reload, a run started earlier
 * must not stream into a new chat or another conversation the user opened.
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import test from "node:test";
import { fileURLToPath } from "node:url";

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith("@/")) {
      const base = new URL(`../../../${specifier.slice(2)}`, import.meta.url).href;
      const file = `${base}.ts`;
      const url = existsSync(fileURLToPath(file)) ? file : `${base}/index.ts`;
      return { url, shortCircuit: true };
    }
    if (specifier.startsWith(".") && !/\.[a-z]+$/.test(specifier)) {
      const base = new URL(specifier, context.parentURL).href;
      const file = `${base}.ts`;
      const url = existsSync(fileURLToPath(file)) ? file : `${base}/index.ts`;
      return { url, shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
});

const values = new Map();
globalThis.window = {
  addEventListener: () => {},
  dispatchEvent: () => {},
  location: { pathname: "/chat" },
};
globalThis.localStorage = {
  getItem: (key) => values.get(key) ?? null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: (key) => values.delete(key),
};
globalThis.requestAnimationFrame = undefined;

const { useSessionStore } = await import("../../../lib/session-store/index.ts");
const { applyChatWsMessage } = await import("../../../lib/net/ws/chat-stream.ts");

const frame = (data) => applyChatWsMessage({ type: "chat_response", data });

test("a frame without session_id goes to the run that owns its msg_id", () => {
  const store = useSessionStore.getState();
  store.setMessages("s_run", [{ id: "m1", role: "user", content: "apply", status: "done" }]);
  store.setMessages("s_open", [{ id: "o1", role: "user", content: "hello", status: "done" }]);
  store.setRunningTaskFor("s_run", { session_id: "s_run", msg_id: "m1" }, "never");
  store.setCurrentConv("s_open");

  frame({ type: "stream_event", msg_id: "m1", event: { type: "text", text: "Applying" } });

  const s = useSessionStore.getState();
  assert.deepEqual(s.messageOrder.s_open, ["o1"], "the open conversation gains no rows");
  assert.ok(s.messageOrder.s_run.includes("m1_reply"));
});

test("a frame no run owns is dropped instead of landing in a new chat", () => {
  const store = useSessionStore.getState();
  store.setCurrentDraft("draft_new");
  frame({ type: "stream_event", msg_id: "lost", event: { type: "text", text: "stray" } });
  const s = useSessionStore.getState();
  assert.equal(s.messageOrder.draft_new, undefined);
  assert.equal(s.messagesById.lost_reply, undefined);
});

test("a first message starting with Fix/Run is a chat turn, not a function run", async () => {
  const { setPendingUserText } = await import("../../../lib/chat/send/pending-user-text.ts");
  const store = useSessionStore.getState();
  store.setMessages("s_fix", []);
  setPendingUserText("s_fix", "Fix the date bug in app.js");
  applyChatWsMessage({ type: "chat_ack", data: { session_id: "s_fix", msg_id: "f1" } });
  const s = useSessionStore.getState();
  assert.equal(s.messagesById.f1.role, "user");
  assert.equal(s.messagesById.f1.display, undefined);
  assert.equal(s.messagesById.f1_reply.role, "assistant");
  assert.equal(s.messagesById.f1_reply.display, undefined);
});
