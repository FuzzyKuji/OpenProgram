type HydrationMessage = {
  role?: string;
  display?: string;
  status?: string;
};

export interface TreeUpdateHydrationState {
  currentSessionId: string | null;
  sessionId?: string;
  path?: string;
  messageId?: string;
  messagesById: Record<string, HydrationMessage>;
  messageOrder: Record<string, string[]>;
  hydratedPaths: Set<string>;
}

/** Decide whether a persisted tree update needs one transcript reload. */
export function shouldHydrateTranscriptForTreeUpdate(
  state: TreeUpdateHydrationState,
): boolean {
  const { currentSessionId, sessionId, path } = state;
  if (!sessionId || !path || sessionId !== currentSessionId) return false;

  // The reducer already attached this tree to a known assistant reply.
  // Its terminal update is not a newly discovered standalone function.
  const owner = state.messageId && (state.messageOrder[sessionId] ?? []).includes(state.messageId)
    ? state.messagesById[state.messageId] : undefined;
  if (owner?.role === "assistant" && owner.display !== "runtime") return false;

  const hasLiveChatReply = (state.messageOrder[sessionId] ?? []).some((id) => {
    const message = state.messagesById[id];
    return (
      message?.role === "assistant" &&
      message.display !== "runtime" &&
      (message.status === "streaming" ||
        message.status === "running" ||
        message.status === "cancelling" ||
        message.status === "pending")
    );
  });
  if (hasLiveChatReply) return false;

  if (state.hydratedPaths.has(path)) return false;
  state.hydratedPaths.add(path);
  return !state.messagesById[path];
}
