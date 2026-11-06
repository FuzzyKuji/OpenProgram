"use client";

/**
 * This composer's model settings (chat model, Fast, effort levels).
 *
 * Each conversation keeps its own entry in `agentSettingsBySession`, so two
 * split panes show and change their own models. The focused conversation
 * also feeds the global `agentSettings` (the WS frames and older callers
 * write there); it answers only while the conversation's own entry has not
 * arrived yet, or for a draft that has none.
 */
import { useEffect } from "react";

import { useBoundChat } from "@/components/chat/top-bar/bound-chat";
import { loadSessionAgentSettings } from "@/lib/runtime-bridge/providers";
import { useSessionStore, type AgentSettingsState } from "@/lib/session-store";

const EMPTY: AgentSettingsState = {};

export function useSessionAgentSettings(): AgentSettingsState {
  const { sessionId, chatKey } = useBoundChat();
  const key = sessionId ?? chatKey;
  const own = useSessionStore((s) => (key ? s.agentSettingsBySession[key] : undefined));
  const focused = useSessionStore((s) => !key || key === (s.activeChatKey ?? s.currentSessionId));
  const global = useSessionStore((s) => s.agentSettings);
  const missing = !own && !!sessionId && !focused;
  useEffect(() => {
    if (missing && sessionId) void loadSessionAgentSettings(sessionId);
  }, [missing, sessionId]);
  return own ?? (focused || !sessionId ? global : EMPTY);
}
