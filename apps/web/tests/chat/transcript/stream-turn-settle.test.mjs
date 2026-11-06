/**
 * How a chat turn's frames settle its rows: tool calls a stop or failure
 * cut off, rejections that name (or do not name) the pending send, a
 * failed function Retry, sequenced deltas around a load, and sends left
 * without an ACK when the socket closes.
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
const { applyChatWsMessage, replayStreamAfterLoad, clearSessionByMsgId } = await import("../../../lib/net/ws/chat-stream.ts");
const { settleSendsOnDisconnect } = await import("../../../lib/net/ws/unacked-sends.ts");
const pending = await import("../../../lib/chat/send/pending-user-text.ts");

const response = (sid, data) => applyChatWsMessage({ type: "chat_response", data: { session_id: sid, ...data } });
const row = (id) => useSessionStore.getState().messagesById[id];

function startTurn(sid, msgId) {
  useSessionStore.getState().setMessages(sid, [
    { id: msgId, role: "user", content: "go", status: "done" },
    { id: `${msgId}_reply`, role: "assistant", content: "", status: "streaming" },
  ]);
  response(sid, { type: "stream_event", msg_id: msgId, event: { type: "tool_use", tool: "bash", tool_call_id: "c1", input: "{}" } });
}

function stage(sid, requestId) {
  const id = `pending_${sid}`;
  pending.setPendingUserText(sid, "hello", Date.now(), { messageId: id, requestId });
  useSessionStore.getState().appendMessage(sid, { id, role: "user", content: "hello", status: "pending", timestamp: Date.now() });
  return id;
}

test("a tool call cut off by Stop reads interrupted, by a failure unknown, never done", () => {
  startTurn("st_cancel", "m1");
  response("st_cancel", { type: "cancelled", msg_id: "m1" });
  assert.equal(row("m1_reply").blocks[0].outcome, "cancelled");
  assert.equal(row("m1_reply").tools[0].status, "cancelled");

  startTurn("st_error", "m2");
  response("st_error", { type: "error", msg_id: "m2", content: "boom" });
  assert.equal(row("m2_reply").blocks[0].outcome, "unknown");
  assert.equal(row("m2_reply").tools[0].status, "error");

  startTurn("st_done", "m3");
  response("st_done", { type: "result", msg_id: "m3", content: "ok" });
  assert.equal(row("m3_reply").blocks[0].outcome, undefined);
});

test("a rejection naming another request leaves the pending send alone", () => {
  const id = stage("st_req", "req-a");
  response("st_req", { type: "error", msg_id: "x1", client_request_id: "req-b", content: "nope" });
  assert.equal(row(id).status, "pending");
  assert.equal(pending.getPendingUserText("st_req"), "hello");
  response("st_req", { type: "error", msg_id: "x2", client_request_id: "req-a", content: "nope" });
  assert.equal(row(id).status, "error");
  assert.equal(pending.getPendingUserText("st_req"), undefined);

  // A frame naming no request still answers the session's pending send.
  const legacy = stage("st_legacy", "req-c");
  response("st_legacy", { type: "error", msg_id: "x3", content: "nope" });
  assert.equal(row(legacy).status, "error");
});

test("an error of a turn already under way is not a rejection of the pending send", () => {
  startTurn("st_turn", "m4");
  const id = stage("st_turn");
  response("st_turn", { type: "error", msg_id: "m4", content: "provider failed" });
  assert.equal(row("m4_reply").status, "error");
  assert.equal(row(id).status, "pending");
  pending.clearPendingUserText("st_turn");
});

test("a failed function Retry answers its request: no row, no rejected send", () => {
  const id = stage("st_retry");
  response("st_retry", { type: "error", msg_id: "rnd", retry_request_id: "r1", content: "Retry failed", display: "runtime" });
  assert.equal(row("rnd_reply"), undefined);
  assert.equal(row(id).status, "pending");
  pending.clearPendingUserText("st_retry");
});

test("an ack naming another request does not consume the pending send", () => {
  const id = stage("st_ack", "req-a");
  applyChatWsMessage({ type: "chat_ack", data: { session_id: "st_ack", msg_id: "u9", client_request_id: "req-b" } });
  assert.equal(row("u9"), undefined);
  assert.equal(row(id).status, "pending");
  applyChatWsMessage({ type: "chat_ack", data: { session_id: "st_ack", msg_id: "u10", client_request_id: "req-a" } });
  assert.equal(row(id), undefined);
  assert.equal(row("u10").status, "done");
  pending.clearPendingUserText("st_ack");
});

test("sequenced deltas: a loaded row drops what it holds and gets what came after", () => {
  const sid = "st_seq";
  const delta = (seq, text) => response(sid, { type: "stream_event", msg_id: "m5", seq, event: { type: "text", text } });
  useSessionStore.getState().setMessages(sid, [{ id: "m5", role: "user", content: "go", status: "done" }]);
  // Reload mid-reply: the stream rebuilt the reply from the deltas it saw.
  delta(4, "D");
  delta(5, "E");
  assert.equal(row("m5_reply").content, "DE");
  assert.equal(row("m5_reply").streamSeq, 5);
  // The load's row reflects the stream up to seq 3; the live row lost to it.
  useSessionStore.getState().setMessages(sid, [
    { id: "m5", role: "user", content: "go", status: "done" },
    { id: "m5_reply", role: "assistant", content: "ABC", status: "streaming", streamSeq: 3 },
  ]);
  replayStreamAfterLoad(sid);
  clearSessionByMsgId(sid);
  assert.equal(row("m5_reply").content, "ABCDE");
  delta(5, "E");
  delta(6, "F");
  assert.equal(row("m5_reply").content, "ABCDEF");
  // The result frame's fuller text closes a hole the stream left.
  response(sid, { type: "result", msg_id: "m5", content: "ABCDEFG" });
  assert.equal(row("m5_reply").content, "ABCDEFG");
});

test("a closed socket marks sends left without an ACK as not sent", () => {
  const id = stage("st_close", "req-z");
  settleSendsOnDisconnect();
  assert.equal(row(id).status, "error");
  assert.equal(row(id).errorReason, "disconnected");
  assert.equal(pending.getPendingUserText("st_close"), undefined);
});
