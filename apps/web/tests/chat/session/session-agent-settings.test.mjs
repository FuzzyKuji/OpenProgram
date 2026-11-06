/**
 * Each conversation keeps its own Agent and model: a draft started from an
 * Agent keeps that Agent and its model after the first ACK and the end of
 * the turn, and split panes never share a model entry.
 */
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { registerHooks } from "node:module";
import test from "node:test";
import { fileURLToPath } from "node:url";

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith("@/")) {
      const base = new URL(`../../../${specifier.slice(2)}`, import.meta.url).href;
      const file = `${base}.ts`;
      const url = existsSync(fileURLToPath(file)) ? file : `${base}/index.ts`;
      return { url, shortCircuit: true };
    }
    if (specifier.startsWith(".") && !/\.[a-z]+$/.test(specifier)) {
      const base = new URL(specifier, context.parentURL).href;
      const file = `${base}.ts`;
      const url = existsSync(fileURLToPath(file)) ? file : `${base}/index.ts`;
      return { url, shortCircuit: true };
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
const { conversationAgentId } = await import("../../../lib/agents/settle-agent-invocation.ts");

const agentOf = (sid) => conversationAgentId(useSessionStore.getState(), sid, sid);

test("a draft started from an Agent keeps that Agent and model after its ACK and turn end", () => {
  const sid = "local_researcher";
  const store = useSessionStore.getState();
  store.setCurrentDraft(sid);
  // The focused default chat runs another model on the global slot.
  store.setAgentSettings({ chat: { provider: "openai", model: "gpt-main" } });
  store.setComposerSettings({
    agentInvocation: {
      agentId: "researcher", label: "Researcher",
      resolvedModel: { provider: "openai", id: "gpt-6.1-sol" },
      thinkingLevels: ["low", "high"], defaultThinking: "high",
    },
  }, sid);
  assert.equal(agentOf(sid), "researcher");

  applyChatWsMessage({ type: "chat_ack", data: { session_id: sid, msg_id: "m1" } });
  let state = useSessionStore.getState();
  assert.equal(state.composerSettingsBySession[sid]?.agentInvocation, undefined, "the ACK consumes the pending pick");
  assert.equal(agentOf(sid), "researcher", "the Agent chip does not fall back to the default Agent");
  assert.equal(state.agentSettingsBySession[sid]?.chat?.model, "gpt-6.1-sol");
  assert.deepEqual(state.agentSettingsBySession[sid]?.chat?.thinking?.options?.map((o) => o.value), ["low", "high"]);

  // A summary written before the list knows the Agent, then the turn ends.
  state.upsertConversation({ id: sid, title: "Research", pinned: false, archived: false, unread: false });
  applyChatWsMessage({ type: "chat_response", data: { type: "result", session_id: sid, msg_id: "m1", content: "done" } });
  assert.equal(agentOf(sid), "researcher");
  assert.equal(useSessionStore.getState().agentSettingsBySession[sid]?.chat?.model, "gpt-6.1-sol");

  // The list's own value wins once it names the Agent (e.g. after a switch).
  useSessionStore.getState().upsertConversation({ id: sid, title: "Research", agent_id: "writer", pinned: false, archived: false, unread: false });
  assert.equal(agentOf(sid), "writer");
});

test("split panes keep separate model entries", () => {
  const store = useSessionStore.getState();
  store.setSessionAgentSettings("left", { chat: { provider: "openai", model: "gpt-a" } });
  store.setSessionAgentSettings("right", { chat: { provider: "anthropic", model: "model-b" } });
  store.setSessionAgentSettings("right", { chat: { provider: "openai", model: "gpt-c" } });
  const state = useSessionStore.getState();
  assert.equal(state.agentSettingsBySession.left.chat.model, "gpt-a");
  assert.equal(state.agentSettingsBySession.right.chat.model, "gpt-c");
  state.clearSessionAgentSettings();
  assert.deepEqual(useSessionStore.getState().agentSettingsBySession, {});
});
