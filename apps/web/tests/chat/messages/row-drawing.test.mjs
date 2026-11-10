// How transcript rows draw from what they own: open steps survive a rebuild,
// a finished run shows no spinner, and a sub-agent's component does not depend
// on how it was started.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import { installLoader } from "../../_support/load.mjs";
import { installDom, render } from "../../_support/dom.mjs";

installLoader({
  replace: {
    "/components/chat/messages/turn-files/turn-files-chips.tsx": "export const TurnFilesChips = () => null;",
  },
});
installDom({ pathname: "/chat" });
const { act, createElement: h } = await import("react");
const { selectRow, useSessionStore } = await import("../../../lib/session-store/index.ts");
const { transcriptRows } = await import("../../_support/transcript-rows.mjs");
const rows = transcriptRows(useSessionStore, selectRow);
const { MessageRow } = await import("../../../components/chat/messages/list/rows/message-rows.tsx");
const { RuntimeBlock } = await import("../../../components/chat/messages/runtime/runtime-block.tsx");

const SID = "s1";
const seed = (...seeded) => useSessionStore.setState({
  currentSessionId: SID,
  rowsByView: { [SID]: Object.fromEntries(seeded.map((row) => [row.id, row])) },
  messageOrder: { [SID]: seeded.map((row) => row.id) },
  stepExpansion: {},
});
const row = (id, fields) => ({ id, role: "assistant", rowKind: "assistant", content: "", status: "done", timestamp: 1, ...fields });
const tool = (id, name = "lookup") => ({ type: "tool", tool: name, tool_call_id: id, input: "{}", result: "ok" });
const draw = (id) => render(h(MessageRow, { id, sessionIdOverride: SID }));
const update = (id, fields) => act(async () => {
  rows.patchRow(SID, id, fields);
});
const click = (element) => act(async () => { element.click(); });
const strip = (view) => view.container.querySelector(".tl");

beforeEach(() => seed());

test("an open strip stays open when the final write rebuilds the blocks in front of it", async () => {
  seed(row("r", { status: "streaming", blocks: [{ type: "text", text: "a" }, { type: "thinking", text: "t" }, tool("c1")] }));
  const view = await draw("r");
  await click(view.container.querySelector(".tl-toggle"));
  assert.equal(strip(view).getAttribute("data-open"), "1");
  const before = strip(view);
  await update("r", { status: "done", blocks: [{ type: "text", text: "a" }, { type: "text", text: "a2" }, { type: "thinking", text: "t" }, tool("c1"), { type: "text", text: "b" }] });
  assert.equal(strip(view), before, "the strip keeps its element");
  assert.equal(strip(view).getAttribute("data-open"), "1");
  await view.unmount();
});

test("an open step stays open across a rebuild and when its row is drawn again", async () => {
  seed(row("r", { blocks: [{ type: "thinking", text: "deep thought" }, tool("c1")] }));
  let view = await draw("r");
  await click(view.container.querySelector(".tl-toggle"));
  await click(view.container.querySelector(".tl-step-head"));
  const stepOpen = () => view.container.querySelector(".tl-step").classList.contains("open");
  assert.equal(stepOpen(), true);
  await update("r", { blocks: [{ type: "thinking", text: "deep thought" }, tool("c1"), { type: "text", text: "end" }] });
  assert.equal(stepOpen(), true);
  await view.unmount();
  view = await draw("r");
  assert.equal(strip(view).getAttribute("data-open"), "1");
  assert.equal(stepOpen(), true);
  await view.unmount();
});

test("a step opened before its card arrives stays open as the sub-agent step", async () => {
  seed(row("r", { status: "streaming", blocks: [tool("c1", "agent")] }));
  useSessionStore.getState().setStepExpansion(SID, "r\u0000c1", true);
  useSessionStore.getState().setStepExpansion(SID, "r\u0000exec:c1", true);
  const view = await draw("r");
  await update("r", { attachCards: [row("card", { rowKind: "sub_agent_step", blockId: "c1", function: "attach", display: "runtime", attach: { label: "x", status: "running", tool_call_id: "c1" } })] });
  const step = view.container.querySelector('.tl-step[data-msg-id="card"]');
  assert.ok(step, "the card draws on its block");
  assert.equal(step.classList.contains("open"), true);
  await view.unmount();
});

test("the same row id in two views keeps two choices", () => {
  const state = useSessionStore.getState();
  state.setStepExpansion("a", "k", true);
  state.setStepExpansion("b", "k", false);
  const { stepExpansion } = useSessionStore.getState();
  assert.equal(stepExpansion.a.k, true);
  assert.equal(stepExpansion.b.k, false);
});

test("removing a conversation forgets its choices and its sub-agent views' choices", () => {
  const state = useSessionStore.getState();
  state.setStepExpansion("gone", "k", true);
  state.setStepExpansion("gone#sub-agent:job", "k", true);
  state.setStepExpansion("kept", "k", true);
  state.removeConversation("gone");
  assert.deepEqual(Object.keys(useSessionStore.getState().stepExpansion), ["kept"]);
});

const runtime = (fields) => render(h(RuntimeBlock, { msg: row("run", { rowKind: "function_run", display: "runtime", function: "demo", ...fields }), sessionIdOverride: SID }));
const openRun = async (view) => { await click(view.container.querySelector(".tl-toggle")); };

test("a finished runtime row with no tree shows no spinner", async () => {
  const view = await runtime({ status: "done" });
  await openRun(view);
  assert.ok(view.container.querySelector(".tl-step"), "the step is drawn");
  assert.equal(view.container.querySelector(".tl-step .is-running"), null);
  assert.equal(view.container.textContent.includes("Running"), false);
  await view.unmount();
});

test("a runtime row with no status and no tree shows no spinner", async () => {
  const view = await runtime({ status: undefined });
  await openRun(view);
  assert.equal(view.container.querySelector(".tl-step .is-running"), null);
  await view.unmount();
});

test("a running row with no tree yet still shows it is running", async () => {
  const view = await runtime({ status: "running" });
  await openRun(view);
  assert.ok(view.container.querySelector(".tl-step .is-running"));
  await view.unmount();
});

const attach = (id, fields = {}, rowKind = "sub_agent_step") => row(id, { rowKind, blockId: "c1", function: "attach", display: "runtime",
  attach: { session_id: SID, head_id: "h1", label: "helper", status: "completed", ...fields } });
const stepsOf = async (id) => {
  const view = await draw(id);
  await click(view.container.querySelector(".tl-toggle"));
  const steps = [...view.container.querySelectorAll(".tl-step")];
  const shape = steps.map((step) => [step.getAttribute("data-msg-id"), step.querySelector(".tl-step-icon").className]);
  const hasCard = !!view.container.querySelector(".attach-card");
  await view.unmount();
  return { shape, hasCard };
};

test("a /task agent and a tool-started agent draw the same component", async () => {
  seed(attach("card"), row("r", { blocks: [tool("c1", "agent")], attachCards: [attach("card")] }));
  const started = await stepsOf("card");
  const tooled = await stepsOf("r");
  assert.equal(started.hasCard, false);
  assert.deepEqual(started, tooled);
  assert.equal(started.shape[0][0], "card");
});

test("a manual attach and a cross-session attach keep their card", async () => {
  seed(attach("manual", { manual: true }, "external_reference"), attach("foreign", { session_id: "other" }, "external_reference"));
  for (const id of ["manual", "foreign"]) {
    const view = await draw(id);
    assert.ok(view.container.querySelector(".attach-card"), id);
    assert.equal(view.container.querySelector(".tl"), null, id);
    await view.unmount();
  }
});
