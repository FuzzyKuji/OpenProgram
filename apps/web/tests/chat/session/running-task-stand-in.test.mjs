import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { registerHooks } from "node:module";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";

import { parseHTML } from "linkedom";

const webRoot = new URL("../../../", import.meta.url);
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.endsWith(".module.css")) {
      return {
        url: "data:text/javascript,export default {}",
        shortCircuit: true,
      };
    }
    const resolveBase = specifier.startsWith("@/")
      ? new URL(specifier.slice(2), webRoot).href
      : specifier.startsWith(".") && !/\.[a-z]+$/i.test(specifier)
        ? new URL(specifier, context.parentURL).href
        : null;
    if (resolveBase) {
      for (const suffix of [".ts", ".tsx", "/index.ts", "/index.tsx"]) {
        const url = `${resolveBase}${suffix}`;
        if (existsSync(fileURLToPath(url))) {
          return { url, shortCircuit: true };
        }
      }
    }
    return nextResolve(specifier, context);
  },
});

const parsed = parseHTML(
  '<!doctype html><html><body><div id="root"></div></body></html>',
);
globalThis.window = parsed.window;
globalThis.document = parsed.document;
globalThis.Event = parsed.window.Event;
globalThis.CustomEvent = parsed.window.CustomEvent;
globalThis.localStorage = {
  getItem() { return null; },
  setItem() {},
  removeItem() {},
};
globalThis.WebSocket = { OPEN: 1 };
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
Object.defineProperty(window, "location", {
  value: { pathname: "/chat" },
  configurable: true,
});
window.matchMedia = () => ({
  matches: false,
  addEventListener() {},
  removeEventListener() {},
});
globalThis.history = {
  pushState() {},
  replaceState() {},
};

globalThis.fetch = async () => ({ ok: true, status: 200, async json() { return {}; } });

const { runtimeState, setSocket } = await import("../../../lib/runtime-bridge/state.ts");
setSocket({ readyState: WebSocket.OPEN, send() {} });
const { disposeSessionLoads } = await import("../../../lib/runtime-bridge/session/session-load.ts");
after(() => disposeSessionLoads(runtimeState.ws));

const { useSessionStore, selectRow } = await import("../../../lib/session-store/index.ts");
const { transcriptRows } = await import("../../_support/transcript-rows.mjs");
const rows = transcriptRows(useSessionStore, selectRow);
const { handleRunningTask, handleRunningTaskClear } = await import(
  "../../../lib/runtime-bridge/session/chat-handlers.ts"
);

test("a task restored with the reply-id stand-in takes its turn's real execution", async () => {
  const { restoreForegroundExecutionTask } = await import(
    "../../../lib/runtime-bridge/session/chat-handlers.ts"
  );
  const sid = "stand-in-session";
  rows.putRows(sid, [
    { id: "p1", role: "user", rowKind: "user", content: "D", status: "done" },
    { id: "p1_reply", role: "assistant", rowKind: "assistant", content: "", status: "done" },
  ]);
  // Restored after a reload with no ack: the reply id stands in.
  handleRunningTask({ session_id: sid, msg_id: "p1", reply_id: "p1_reply" });
  assert.equal(useSessionStore.getState().runningTasks[sid].execution_id, "p1_reply");
  restoreForegroundExecutionTask(
    { session_id: sid, msg_id: "p1", execution_id: "exec_p1", status_version: 7 },
    { session_id: sid, execution_id: "exec_p1", status: "running" },
  );
  const task = useSessionStore.getState().runningTasks[sid];
  assert.equal(task.execution_id, "exec_p1");
  assert.equal(task.status_version, 7);

  // Another turn's execution still cannot take the slot.
  restoreForegroundExecutionTask(
    { session_id: sid, msg_id: "p0", execution_id: "exec_p0", status_version: 9 },
    { session_id: sid, execution_id: "exec_p0", status: "running" },
  );
  assert.equal(useSessionStore.getState().runningTasks[sid].execution_id, "exec_p1");
});
