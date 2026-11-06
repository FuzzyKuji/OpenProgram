"use client";

import { createContext, useContext } from "react";
import { useSessionStore } from "@/lib/session-store";
import { useTranscriptView, type TranscriptView } from "@/lib/prefs/transcript-view";

/** The conversation a transcript row belongs to, when it is not the open one (a split pane). */
export const TranscriptSessionContext = createContext<string | undefined>(undefined);

export function useTranscriptViewHere(): TranscriptView {
  const override = useContext(TranscriptSessionContext);
  const current = useSessionStore((s) => s.currentSessionId);
  return useTranscriptView(override ?? current);
}
