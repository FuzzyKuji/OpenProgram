/**
 * A reply that ends in error releases the session's running task on this
 * client at once, so the next message sends instead of queueing behind a
 * turn that is over. A later error naming a settled or newer turn leaves
 * the slot alone.
 */
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { registerHooks } from "node:module";
import test from "node:test";
import { fileURLToPath } from "node:url";

registerHooks({
  resolve(specifier, context, nextResolve) {
    const base = specifier.startsWith("@/")
      ? new URL(`../../../${specifier.slice(2)}`, import.meta.url).href
      : specifier.startsWith(".") && !/\.[a-z]+$/.test(specifier)
        ? new URL(specifier, context.parentURL).href
        : null;
    if (base) {
      for (const suffix of [".ts", ".tsx", "/index.ts"]) {
        if (existsSync(fileURLToPath(base + suffix))) return { url: base + suffix, shortCircuit: true };
      }
    }
    return nextResolve(specifier, context);
  },
});

const values = new Map();
globalThis.window = { addEventListener: () => {}, dispatchEvent: () => {}, location: { pathname: "/chat" } };
globalThis.localStorage = {
  getItem: (key) => values.get(key) ?? null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: (key) => values.delete(key),
};
globalThis.requestAnimationFrame = undefined;

const { useSessionStore } = await import("../../../lib/session-store/index.ts");
const { applyChatWsMessage } = await import("../../../lib/net/ws/chat-stream.ts");

const response = (sid, data) => applyChatWsMessage({ type: "chat_response", data: { session_id: sid, ...data } });
const settle = () => new Promise((resolve) => setTimeout(resolve, 20));

function startTurn(sid, msgId, executionId) {
  const store = useSessionStore.getState();
  store.setMessages(sid, [
    { id: msgId, role: "user", content: "go", status: "done" },
    { id: `${msgId}_reply`, role: "assistant", content: "", status: "streaming" },
  ]);
  store.setRunningTaskFor(sid, { session_id: sid, msg_id: msgId, execution_id: executionId }, "never");
}

test("an error frame for the running turn frees the session", async () => {
  startTurn("s_err", "m1", "e1");
  response("s_err", { type: "error", msg_id: "m1", content: "provider failed" });
  await settle();
  assert.equal(useSessionStore.getState().messagesById.m1_reply.status, "error");
  assert.equal(useSessionStore.getState().runningTasks.s_err, undefined);
});

test("an error of an earlier turn leaves the newer running turn alone", async () => {
  startTurn("s_newer", "m2", "e2");
  useSessionStore.getState().setMessages("s_newer", [
    { id: "m1", role: "user", content: "old", status: "done" },
    { id: "m1_reply", role: "assistant", content: "", status: "streaming" },
    { id: "m2", role: "user", content: "new", status: "done" },
    { id: "m2_reply", role: "assistant", content: "", status: "streaming" },
  ]);
  response("s_newer", { type: "error", msg_id: "m1", content: "late failure" });
  await settle();
  assert.equal(useSessionStore.getState().runningTasks.s_newer?.execution_id, "e2");
});

test("a late error after the reply settled changes nothing", async () => {
  startTurn("s_done", "m3", "e3");
  response("s_done", { type: "result", msg_id: "m3", content: "ok" });
  useSessionStore.getState().setRunningTaskFor("s_done", { session_id: "s_done", msg_id: "m3", execution_id: "e3" }, "never");
  response("s_done", { type: "error", msg_id: "m3", content: "compaction failed" });
  await settle();
  assert.equal(useSessionStore.getState().messagesById.m3_reply.status, "done");
});
