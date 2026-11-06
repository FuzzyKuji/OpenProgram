/** A worker restart cuts a reply off, and a new turn carries the work on
 *  (runtime/conversation/restart_turn.py). Its prompt is an instruction to
 *  the model, stamped ``trigger: "restart"`` and drawn as nothing, and the
 *  chat draws the two replies as one: the cut-off reply hides, and the
 *  reply that continues it opens with its steps and a "restarted" step
 *  where the restart fell. Collapsed, the reply reads as if never cut. */
import type { AssistantBlock, ChatMsg } from "../../session-store/types.ts";

/** The user message a reply answers: its recorded predecessor, else the
 *  ``<user>_reply`` naming a live placeholder carries. */
function promptOf(byId: Record<string, ChatMsg>, reply: ChatMsg): ChatMsg | undefined {
  const id = reply.calledBy ?? (reply.id.endsWith("_reply") ? reply.id.slice(0, -"_reply".length) : undefined);
  return id ? byId[id] : undefined;
}

/** The replies ``reply`` continues, oldest first; empty for a reply no
 *  restart cut short. */
export function restartPredecessors(byId: Record<string, ChatMsg>, reply: ChatMsg): ChatMsg[] {
  const chain: ChatMsg[] = [];
  const seen = new Set<string>([reply.id]);
  let prompt = promptOf(byId, reply);
  while (prompt?.trigger === "restart" && prompt.calledBy && !seen.has(prompt.calledBy)) {
    const cut = byId[prompt.calledBy];
    if (!cut || cut.role !== "assistant") break;
    seen.add(cut.id);
    chain.unshift(cut);
    prompt = promptOf(byId, cut);
  }
  return chain;
}

/** A reply's ordered blocks, adapting records that kept only the flat
 *  thinking/tools fields. */
export function fallbackBlocks(msg: ChatMsg): AssistantBlock[] {
  return [
    ...(msg.thinking ? [{ type: "thinking" as const, text: msg.thinking }] : []),
    ...(msg.tools ?? []).map((tool): AssistantBlock => ({
      type: "tool", tool: tool.tool, tool_call_id: tool.id,
      input: tool.input, result: tool.result,
      is_error: tool.isError || tool.status === "error" || tool.status === "cancelled",
      outcome: tool.status === "cancelled" ? "cancelled" : undefined,
      truncated: tool.truncated, total_bytes: tool.totalBytes,
      message_id: tool.messageId, node_id: tool.nodeId,
      ...(tool.providerExecuted ? { provider_executed: true } : {}),
    })),
  ];
}

/** Everything one reply draws, its final text included. ``prose`` strips
 *  what the bubble draws apart from the text (attachment markers). */
function partBlocks(msg: ChatMsg, prose: (content: string) => string): AssistantBlock[] {
  const blocks = msg.blocks?.length ? msg.blocks : fallbackBlocks(msg);
  const text = msg.content ? prose(msg.content) : "";
  return text && !blocks.some((b) => b.type === "text") ? [...blocks, { type: "text", text }] : blocks;
}

/** ``reply`` drawn with the replies it continues in front of it. */
export function joinedReply(
  cut: ChatMsg[], reply: ChatMsg, prose: (content: string) => string,
): ChatMsg {
  if (!cut.length) return reply;
  const parts = [...cut, reply];
  const blocks: AssistantBlock[] = [];
  parts.forEach((part, i) => {
    if (i > 0) blocks.push({ type: "restart" });
    blocks.push(...partBlocks(part, prose));
  });
  const all = <T,>(pick: (m: ChatMsg) => T[] | undefined) => parts.flatMap((m) => pick(m) ?? []);
  return {
    ...reply,
    blocks,
    tools: all((m) => m.tools),
    attachCards: all((m) => m.attachCards),
    callRoots: all((m) => m.callRoots),
    runtimeChildren: all((m) => m.runtimeChildren),
  };
}

/** Mark each cut-off reply with the reply that continues it, so its own
 *  row draws nothing (history load). */
export function markRestartContinuations(msgs: ChatMsg[]): void {
  const byId = new Map(msgs.map((m) => [m.id, m]));
  for (const reply of msgs) {
    if (reply.role !== "assistant" || !reply.calledBy) continue;
    const prompt = byId.get(reply.calledBy);
    const cut = prompt?.trigger === "restart" && prompt.calledBy ? byId.get(prompt.calledBy) : undefined;
    if (cut?.role === "assistant") cut.continuedBy = reply.id;
  }
}
