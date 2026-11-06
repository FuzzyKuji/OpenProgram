"use client";

import { jsonFetch } from "@/lib/net/fetch-client";
import { useSessionStore } from "@/lib/session-store";

interface SwitchResult {
  session_id: string;
  agent_id: string;
  model: { provider: string; id: string };
}

/** Switch an existing conversation to another Agent. The server answers
 *  with the Agent's model, which the conversation now uses. */
export async function switchSessionAgent(sessionId: string, agentId: string): Promise<SwitchResult> {
  const result = await jsonFetch<SwitchResult>(`/api/sessions/${encodeURIComponent(sessionId)}/agent`, {
    method: "POST",
    body: JSON.stringify({ agent_id: agentId }),
  });
  const store = useSessionStore.getState();
  const summary = store.conversations[sessionId];
  if (summary) store.upsertConversation({ ...summary, agent_id: result.agent_id });
  const [{ runtimeState }, { loadAgentSettings }] = await Promise.all([
    import("@/lib/runtime-bridge/state"), import("@/lib/runtime-bridge/providers"),
  ]);
  const conv = runtimeState.conversations[sessionId];
  if (conv) conv.agent_id = result.agent_id;
  await loadAgentSettings();
  return result;
}
