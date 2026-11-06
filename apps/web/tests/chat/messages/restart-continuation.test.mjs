// A worker restart cuts a reply off; the resume turn (prompt stamped
// trigger "restart") continues it, and the chat draws both as one reply.
import assert from "node:assert/strict";
import { test } from "node:test";

import { convToChatMsgs } from "../../../lib/chat/transcript/conv-mapper.ts";
import { joinedReply, restartPredecessors } from "../../../lib/chat/transcript/restart-continuation.ts";

function restartedTranscript() {
  const msgs = convToChatMsgs([
    { id: "u1", role: "user", content: "run sleep 40" },
    { id: "u1_reply", role: "assistant", content: "", predecessor: "u1",
      blocks: [{ type: "tool", tool: "bash", tool_call_id: "t1", is_error: true }] },
    { id: "r_user", role: "user", content: "Continue the interrupted task", display: "runtime",
      trigger: "restart", predecessor: "u1_reply" },
    { id: "r_user_reply", role: "assistant", content: "done", predecessor: "r_user",
      blocks: [{ type: "tool", tool: "bash", tool_call_id: "t2" }, { type: "text", text: "done" }] },
  ]);
  return Object.fromEntries(msgs.map((m) => [m.id, m]));
}

test("a reply a restart cut off names the reply that continues it", () => {
  const byId = restartedTranscript();
  assert.equal(byId.u1_reply.continuedBy, "r_user_reply");
  assert.equal(byId.r_user.trigger, "restart");
});

test("the continuing reply opens with the cut-off steps and a restart step where it fell", () => {
  const byId = restartedTranscript();
  const cutOff = restartPredecessors(byId, byId.r_user_reply);
  assert.deepEqual(cutOff.map((m) => m.id), ["u1_reply"]);
  assert.deepEqual(
    joinedReply(cutOff, byId.r_user_reply, (en) => en).blocks.map((b) => b.type),
    ["tool", "restart", "tool", "text"],
  );
});

test("a reply nothing cut off continues nothing", () => {
  const byId = restartedTranscript();
  assert.deepEqual(restartPredecessors(byId, byId.u1_reply), []);
});
