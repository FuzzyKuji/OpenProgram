// A persisted tree_update for a Function run the transcript does not show yet
// reloads the session once per tree path; live chat replies and runs already
// on screen never trigger a reload.
import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, mock, test } from "node:test";
import { installLoader } from "../_support/load.mjs";
import { installDom } from "../_support/dom.mjs";

installLoader();
installDom({ pathname: "/s/session-a" });
globalThis.WebSocket ??= { OPEN: 1 };
const { shouldHydrateTranscriptForTreeUpdate } = await import("../../lib/runtime-bridge/session/transcript-hydration.ts");
const { clearHydratedTreePaths, handleChatResponse } = await import("../../lib/runtime-bridge/session/chat-handlers.ts");
const { runtimeState, setSocket } = await import("../../lib/runtime-bridge/state.ts");
const { useSessionStore } = await import("../../lib/session-store/index.ts");

function decision(messagesById, order, extra = {}) {
  return {
    currentSessionId: "session-a", sessionId: "session-a", path: "tool-node",
    messagesById, messageOrder: { "session-a": order }, hydratedPaths: new Set(), ...extra,
  };
}

describe("shouldHydrateTranscriptForTreeUpdate", () => {
  test("a live normal chat reply suppresses hydration without consuming the path", () => {
    const state = decision({ reply: { role: "assistant", display: "normal", status: "running" } }, ["reply"]);
    assert.equal(shouldHydrateTranscriptForTreeUpdate(state), false);
    assert.equal(state.hydratedPaths.size, 0);
  });

  test("a standalone runtime run hydrates exactly once per path", () => {
    const state = decision({ runtime: { role: "assistant", display: "runtime", status: "running" } }, ["runtime"]);
    assert.equal(shouldHydrateTranscriptForTreeUpdate(state), true);
    assert.equal(shouldHydrateTranscriptForTreeUpdate(state), false);
  });

  test("a runtime card already in the transcript does not reload it", () => {
    const state = decision({ "tool-node": { role: "assistant", display: "runtime", status: "running" } }, ["tool-node"]);
    assert.equal(shouldHydrateTranscriptForTreeUpdate(state), false);
  });

  test("a tree owned by a known assistant reply never reloads", () => {
    const state = decision({ reply: { role: "assistant", status: "done" } }, ["reply"], { messageId: "reply" });
    assert.equal(shouldHydrateTranscriptForTreeUpdate(state), false);
  });

  test("an update for another session or without a path is ignored", () => {
    assert.equal(shouldHydrateTranscriptForTreeUpdate(decision({}, [], { sessionId: "session-b" })), false);
    assert.equal(shouldHydrateTranscriptForTreeUpdate(decision({}, [], { path: undefined })), false);
  });
});

describe("tree_update handling", () => {
  let sent;
  // A load request arms a 15 s reply timeout; fake timers keep it from holding the run open.
  beforeEach(() => {
    mock.timers.enable({ apis: ["setTimeout"] });
    sent = [];
    clearHydratedTreePaths();
    runtimeState.currentSessionId = "session-a";
    setSocket({ readyState: 1, send: (frame) => sent.push(JSON.parse(frame)), addEventListener() {}, removeEventListener() {} });
  });
  afterEach(() => mock.timers.reset());
  const loads = () => sent.filter((frame) => frame.action === "load_session");
  const treeUpdate = (path) => handleChatResponse({
    type: "tree_update", session_id: "session-a", function: "web_use", tree: { path, name: "web_use", status: "running" },
  });

  test("sends load_session once for a newly discovered standalone run", () => {
    useSessionStore.setState({ messagesById: {}, messageOrder: { "session-a": [] } });
    treeUpdate("run-1");
    treeUpdate("run-1");
    assert.deepEqual(loads().map((frame) => frame.session_id), ["session-a"]);
  });

  test("sends nothing while a normal chat reply is streaming", () => {
    useSessionStore.setState({
      messagesById: { reply: { id: "reply", role: "assistant", status: "streaming", content: "" } },
      messageOrder: { "session-a": ["reply"] },
    });
    treeUpdate("run-2");
    assert.equal(loads().length, 0);
  });
});
