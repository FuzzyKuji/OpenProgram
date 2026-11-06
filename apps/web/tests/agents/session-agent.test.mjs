import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import test from "node:test";

const stub = (source) => `data:text/javascript,${encodeURIComponent(source)}`;
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "@/lib/net/fetch-client") {
      return { url: stub(`export const jsonFetch = (url, init) => { globalThis.__sessionAgent.requests.push([url, init?.method, init?.body]); return Promise.resolve({ session_id: "c1", agent_id: "watcher", model: { provider: "anthropic", id: "opus" } }); };`), shortCircuit: true };
    }
    if (specifier === "@/lib/session-store") {
      return { url: stub(`export const useSessionStore = { getState: () => globalThis.__sessionAgent.store };`), shortCircuit: true };
    }
    if (specifier === "@/lib/runtime-bridge/state") {
      return { url: stub(`export const runtimeState = globalThis.__sessionAgent.runtime;`), shortCircuit: true };
    }
    if (specifier === "@/lib/runtime-bridge/providers") {
      return { url: stub(`export const loadAgentSettings = async () => { globalThis.__sessionAgent.reloaded += 1; };`), shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
});

const upserts = [];
globalThis.__sessionAgent = {
  requests: [],
  reloaded: 0,
  runtime: { conversations: { c1: { id: "c1", agent_id: "main" } } },
  store: {
    conversations: { c1: { id: "c1", title: "Docs", agent_id: "main" } },
    upsertConversation: (summary) => upserts.push(summary),
  },
};

const { switchSessionAgent } = await import("../../lib/agents/session-agent.ts");

test("an existing conversation switches Agent on the server and takes its model", async () => {
  await switchSessionAgent("c1", "watcher");
  const state = globalThis.__sessionAgent;
  assert.deepEqual(state.requests, [["/api/sessions/c1/agent", "POST", JSON.stringify({ agent_id: "watcher" })]]);
  assert.deepEqual(upserts, [{ id: "c1", title: "Docs", agent_id: "watcher" }]);
  assert.equal(state.runtime.conversations.c1.agent_id, "watcher");
  assert.equal(state.reloaded, 1, "the model chip reloads the Agent's model");
});
