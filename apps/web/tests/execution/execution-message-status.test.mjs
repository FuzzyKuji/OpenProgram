import assert from "node:assert/strict";
import test from "node:test";
import { executionStatusUpdates, turnReplyUnsettled } from "../../lib/net/execution/execution-message-status.ts";

const turn = ["u1", "u1_reply"];

test("a pause for system access marks the turn's rows, and every later status moves them out", () => {
  const rows = { u1: { role: "user", status: "done" }, u1_reply: { role: "assistant", status: "streaming" } };
  // The user row is settled; a pause never reopens it.
  assert.deepEqual(executionStatusUpdates(rows, "e1", turn, "paused", "system_access_required"), [["u1_reply", "paused"]]);
  const paused = { u1: { role: "user", status: "done" }, u1_reply: { role: "assistant", status: "paused" } };
  assert.deepEqual(executionStatusUpdates(paused, "e1", turn, "running"), [["u1_reply", "running"]]);
  assert.deepEqual(executionStatusUpdates(paused, "e1", turn, "completed"), [["u1_reply", "done"]]);
  assert.deepEqual(executionStatusUpdates(paused, "e1", turn, "failed"), [["u1_reply", "error"]]);
  assert.deepEqual(executionStatusUpdates(paused, "e1", turn, "cancelled"), [["u1_reply", "cancelled"]]);
});

test("rows of a turn that is not paused keep the status their stream gives them", () => {
  const rows = { u1_reply: { role: "assistant", status: "streaming" }, e1: { role: "assistant", status: "running" } };
  assert.deepEqual(executionStatusUpdates(rows, "e1", turn, "completed"), [["e1", "completed"]]);
  const settled = { u1_reply: { role: "assistant", status: "cancelled" } };
  assert.deepEqual(executionStatusUpdates(settled, "u1_reply", turn, "cancelling"), []);
});

test("a finished execution reloads the transcript only for a reply the stream never settled", () => {
  assert.equal(turnReplyUnsettled({ u1_reply: { role: "assistant", status: "done" } }, "e1", turn), false);
  assert.equal(turnReplyUnsettled({ u1_reply: { role: "assistant", status: "streaming" } }, "e1", turn), true);
  assert.equal(turnReplyUnsettled({ u1: { role: "user", status: "done" } }, "e1", ["u1"]), true);
  assert.equal(turnReplyUnsettled({ u1_reply: { role: "assistant", status: "error" } }, "e1", ["u1"]), false);
  assert.equal(turnReplyUnsettled({}, "e1", []), true);
});
