// A chapter pin rides on the turn's user message: the history mapper reads
// the wire `chapter` into `chapterPinnedAt`, and a reply finds the user
// message that opened its turn to pin it.
import assert from "node:assert/strict";
import test from "node:test";
import { installLoader } from "../../_support/load.mjs";

installLoader();
const { chapterPinnedAt, turnUserMessageId } = await import("../../../lib/chat/transcript/chapter.ts");
const { convToChatMsgs } = await import("../../../lib/chat/transcript/conv-mapper.ts");

test("the wire chapter becomes its pin time; null, missing or bad values are unpinned", () => {
  assert.equal(chapterPinnedAt({ pinned_at: 1_700_000_000.5 }), 1_700_000_000.5);
  for (const value of [null, undefined, {}, { pinned_at: "x" }, { pinned_at: 0 }, 5]) {
    assert.equal(chapterPinnedAt(value), undefined);
  }
});

test("a loaded user row carries its pin; an unpinned one does not", () => {
  const msgs = convToChatMsgs([
    { id: "u1", role: "user", content: "first", chapter: { pinned_at: 1_700_000_000 } },
    { id: "a1", role: "assistant", content: "answer", predecessor: "u1" },
    { id: "u2", role: "user", content: "second", chapter: null },
  ]);
  const byId = Object.fromEntries(msgs.map((m) => [m.id, m]));
  assert.equal(byId.u1.chapterPinnedAt, 1_700_000_000);
  assert.equal(byId.u2.chapterPinnedAt, undefined);
});

test("a reply's turn is the nearest user message above it, past runtime rows", () => {
  const byId = {
    u1: { role: "user" }, a1: { role: "assistant" },
    u2: { role: "user" }, rt: { role: "user", display: "runtime" }, a2: { role: "assistant" },
  };
  const order = ["u1", "a1", "u2", "rt", "a2"];
  assert.equal(turnUserMessageId(order, byId, "a1"), "u1");
  assert.equal(turnUserMessageId(order, byId, "a2"), "u2");
  assert.equal(turnUserMessageId(["a0", ...order], byId, "a0"), undefined);
  assert.equal(turnUserMessageId(undefined, byId, "a1"), undefined);
});
