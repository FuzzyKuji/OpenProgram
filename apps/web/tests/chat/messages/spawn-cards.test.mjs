// Live spawn cards: the `sub_agent` stream event must build the same
// `attachCards` shape the reload path (conv-mapper) builds from the DAG's
// `function === "attach"` rows, runtime rows keep their first visible time,
// and the reply draws same-session spawns as timeline rows.
import assert from "node:assert/strict";
import { after, describe, test } from "node:test";
import { installLoader } from "../../_support/load.mjs";
import { installDom, render } from "../../_support/dom.mjs";

installLoader({
  replace: {
    "/components/chat/messages/turn-files/turn-files-chips.tsx": "export const TurnFilesChips = () => null;",
  },
});
// The real i18n module answers in English through the stored locale.
installDom({ pathname: "/chat" });
const { createElement: h } = await import("react");
const { useSessionStore } = await import("../../../lib/session-store/index.ts");
const { applyChatWsMessage } = await import("../../../lib/net/ws/chat-stream.ts");
const pending = await import("../../../lib/chat/send/pending-user-text.ts");
const { AssistantBubble } = await import("../../../components/chat/messages/bubbles/assistant-bubble.tsx");

const SID = "s1";
// Envelopes key off the USER turn id; the reply bubble is `${msg_id}_reply`.
const UID = "u1";
const RID = `${UID}_reply`;
const realNow = Date.now;
after(() => { Date.now = realNow; });

const reply = () => useSessionStore.getState().messagesById[RID];
const response = (data) => applyChatWsMessage({ type: "chat_response", data: { session_id: SID, ...data } });
const send = (event) => response({ type: "stream_event", msg_id: UID, event });
/** Run `fn` with Date.now() reading `at`. */
function at(now, fn) {
  Date.now = () => now;
  try { return fn(); } finally { Date.now = realNow; }
}

describe("live spawn cards and runtime rows", () => {
  // The steps build on each other in order, as a stream does.
  test("an agent-owned function tree enriches the reply timeline instead of adding a row", () => {
    useSessionStore.setState({ messagesById: {}, messageOrder: {} });
    applyChatWsMessage({ type: "chat_ack", data: { session_id: SID, msg_id: UID } });
    send({ type: "tool_use", tool: "web_use", tool_call_id: "tc_web_use", input: '{"command":"list_pages"}' });
    const tree = (status) => response({ type: "tree_update", msg_id: RID, function: "web_use",
      tree: { path: "web-use-node-1", name: "web_use", status } });
    tree("running");
    assert.equal(useSessionStore.getState().messagesById[`${RID}_reply`], undefined);
    assert.deepEqual(reply().callRoots, [{ path: "web-use-node-1", name: "web_use", status: "running" }]);
    tree("completed");
    assert.deepEqual(reply().callRoots, [{ path: "web-use-node-1", name: "web_use", status: "completed" }]);
  });

  let runStartedAt;
  test("a running spawn creates one card at once, anchored to the caller turn", () => {
    send({ type: "tool_use", tool: "task", tool_call_id: "tc_1", input: "{}" });
    runStartedAt = reply().timestamp;
    assert.ok(Number.isFinite(runStartedAt));
    at(5_000, () => send({ type: "sub_agent", card_id: "card_a", tool_call_id: "tc_1", agent_id: "worker", content: "",
      attach: { session_id: SID, head_id: null, label: "probe", prompt: "do the thing", status: "running" } }));
    const cards = reply().attachCards;
    assert.equal(cards.length, 1);
    assert.equal(cards[0].id, "card_a");
    assert.equal(cards[0].function, "attach");
    assert.equal(cards[0].display, "runtime");
    assert.equal(cards[0].status, "running");
    assert.equal(cards[0].attach.status, "running");
    assert.equal(cards[0].attach.label, "probe");
    assert.equal(cards[0].calledBy, RID);
    assert.equal(cards[0].timestamp, 5_000);
  });

  test("the terminal event for the same spawn patches it in place and keeps its first time", () => {
    at(9_000, () => send({ type: "sub_agent", card_id: "card_a", tool_call_id: "tc_1", agent_id: "worker",
      content: "the answer",
      attach: { session_id: SID, head_id: "head_9", label: "probe", prompt: "do the thing", status: "completed" } }));
    const cards = reply().attachCards;
    assert.equal(cards.length, 1);
    assert.equal(cards[0].status, "done");
    assert.equal(cards[0].attach.status, "completed");
    assert.equal(cards[0].attach.head_id, "head_9");
    assert.equal(cards[0].content, "the answer");
    assert.equal(cards[0].timestamp, 5_000);
  });

  test("a distinct spawn is a second card, and an errored spawn leaves the running state", () => {
    send({ type: "sub_agent", card_id: "card_b", tool_call_id: "tc_2",
      attach: { session_id: SID, label: "second", status: "running" } });
    assert.equal(reply().attachCards.length, 2);
    send({ type: "sub_agent", card_id: "card_b", tool_call_id: "tc_2", content: "RuntimeError: boom",
      attach: { session_id: SID, label: "second", status: "errored" } });
    const errored = reply().attachCards.find((card) => card.id === "card_b");
    assert.equal(errored.status, "error");
    assert.equal(errored.attach.status, "errored");
  });

  test("an event without a card_id is ignored", () => {
    send({ type: "sub_agent", attach: { status: "running" } });
    assert.equal(reply().attachCards.length, 2);
  });

  test("the final result keeps live cards and the reply's start time", () => {
    response({ type: "result", msg_id: UID, content: "done", blocks: [{ type: "text", text: "done" }] });
    assert.equal(reply().attachCards.length, 2);
    assert.equal(reply().status, "done");
    assert.equal(reply().timestamp, runStartedAt);
  });

  test("a dispatcher-owned runtime result does not replace its status time", () => {
    const run = { msg_id: "runtime_timestamp", display: "runtime", function: "web_use" };
    at(1_700_000_001_000, () => response({ type: "status", ...run, status: "running" }));
    const startedAt = useSessionStore.getState().messagesById.runtime_timestamp.timestamp;
    at(1_700_000_002_000, () => response({ type: "result", ...run, content: "done" }));
    assert.equal(useSessionStore.getState().messagesById.runtime_timestamp.timestamp, startedAt);
  });

  test("a duplicate nested status keeps the first time", () => {
    const run = { msg_id: "nested_runtime_timestamp", predecessor: RID, display: "runtime", function: "web_use", status: "running" };
    const child = () => reply().runtimeChildren.find((c) => c.id === "nested_runtime_timestamp");
    at(1_700_000_003_000, () => response({ type: "status", ...run }));
    const startedAt = child().timestamp;
    at(1_700_000_008_000, () => response({ type: "status", ...run }));
    assert.equal(child().timestamp, startedAt);
  });

  test("a runtime row moved under its later-arriving assistant keeps its time and leaves the top level", () => {
    const parentId = "runtime_future_parent_reply";
    const run = { msg_id: "migrating_runtime_timestamp", predecessor: parentId, display: "runtime", function: "web_use" };
    at(1_700_000_009_000, () => response({ type: "status", ...run, status: "running" }));
    const startedAt = useSessionStore.getState().messagesById.migrating_runtime_timestamp.timestamp;
    response({ type: "stream_event", msg_id: "runtime_future_parent", event: { type: "text", text: "parent" } });
    at(1_700_000_014_000, () => response({ type: "result", ...run, content: "done" }));
    const state = useSessionStore.getState();
    const migrated = state.messagesById[parentId].runtimeChildren.find((c) => c.id === "migrating_runtime_timestamp");
    assert.equal(migrated.timestamp, startedAt);
    assert.equal(state.messagesById.migrating_runtime_timestamp, undefined);
  });

  test("a Job's ack leaves the composer's pending text and the transcript alone", () => {
    pending.setPendingUserText("s_job", "my draft");
    applyChatWsMessage({ type: "chat_ack", data: { session_id: "s_job", msg_id: "j_1_user", job_id: "j_1" } });
    assert.equal(pending.getPendingUserText("s_job"), "my draft");
    assert.equal(useSessionStore.getState().messagesById.j_1_user, undefined);
  });
});

describe("spawns in the assistant reply", () => {
  const card = (id, attach) => ({ id, role: "assistant", content: "", function: "attach", display: "runtime",
    status: "done", timestamp: 1_700_000_000_000, attach: { status: "completed", ...attach } });
  const msg = {
    id: "a1", role: "assistant", content: "", status: "done", timestamp: 1_700_000_000_000,
    attachCards: [
      card("spawn", { session_id: SID, head_id: "head-spawn", label: "worker" }),
      card("manual", { session_id: SID, head_id: "head-manual", label: "attached", manual: true }),
      card("elsewhere", { session_id: "other", head_id: "head-other", label: "remote" }),
    ],
  };

  test("same-session spawns are timeline rows; manual and cross-session attaches keep their cards", async () => {
    useSessionStore.setState({ currentSessionId: SID, messagesById: { a1: msg }, messageOrder: { [SID]: ["a1"] } });
    const view = await render(h(AssistantBubble, { msg }));
    try {
      const strip = view.container.querySelector(".tl");
      assert.equal(strip.getAttribute("data-subagent-heads"), "head-spawn");
      await view.act(() => strip.querySelector(".tl-toggle").click());
      assert.deepEqual([...view.container.querySelectorAll(".tl-step[data-head-id]")].map((row) => row.getAttribute("data-head-id")),
        ["head-spawn"]);
      assert.deepEqual([...view.container.querySelectorAll(".attach-row")].map((row) => row.getAttribute("data-msg-id")),
        ["manual", "elsewhere"]);
      assert.equal(view.container.querySelector(".tl .attach-card"), null);
      assert.ok(view.container.querySelector('.attach-row[data-msg-id="manual"] .attach-card-time .message-timestamp'));
    } finally { await view.unmount(); }
  });

  test("a message added to the running turn is drawn inside the reply where it landed", async () => {
    const reply = { id: "a3", role: "assistant", content: "", status: "done", timestamp: 1_700_000_000_000,
      blocks: [{ type: "text", text: "before" }, { type: "steering", text: "also check the tests", message_id: "st1" },
        { type: "text", text: "after" }] };
    useSessionStore.setState({ messagesById: { a3: reply }, messageOrder: { [SID]: ["a3"] } });
    const view = await render(h(AssistantBubble, { msg: reply }));
    try {
      const steering = view.container.querySelector(".steering-input");
      assert.match(steering.textContent, /also check the tests/);
      const text = view.container.textContent;
      assert.ok(text.indexOf("before") < text.indexOf("also check the tests"));
      assert.ok(text.indexOf("also check the tests") < text.indexOf("after"));
    } finally { await view.unmount(); }
  });

  test("a streaming reply shows its start timestamp before any content", async () => {
    const live = { id: "a2", role: "assistant", content: "", status: "streaming", timestamp: 1_700_000_000_000 };
    useSessionStore.setState({ messagesById: { a2: live }, messageOrder: { [SID]: ["a2"] } });
    const view = await render(h(AssistantBubble, { msg: live }));
    try {
      assert.ok(view.container.querySelector(".message-actions-footer .message-timestamp"));
    } finally { await view.unmount(); }
  });
});
