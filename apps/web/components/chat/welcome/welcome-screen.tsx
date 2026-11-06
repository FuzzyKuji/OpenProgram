/**
 * WelcomeScreen — the empty chat.
 *
 * No mark, tagline or starter buttons: the composer floats over an empty
 * area, or over the code rain when the "Code rain style" setting is on.
 * Visible whenever the session store says so; mounted as a portal inside
 * the #welcome-mount placeholder that PageShell leaves in the chat area.
 * When the chat sends its first message the rain is kept a moment longer
 * so it can stop and fade instead of vanishing; when another chat opens
 * instead, the rain goes at once rather than falling over its messages.
 */
"use client";

import { useEffect, useState } from "react";

import { useSessionStore } from "@/lib/session-store";

import { WelcomeBackdrop } from "./welcome-backdrop";

const STOP_MS = 1200;

export function WelcomeScreen() {
  const visible = useSessionStore((s) => s.welcomeVisible);
  const fade = useSessionStore((s) => s.welcomeFade);
  const [stopping, setStopping] = useState(false);
  const [wasVisible, setWasVisible] = useState(visible);
  if (visible !== wasVisible) {
    setWasVisible(visible);
    setStopping(!visible && fade);
  }
  useEffect(() => {
    if (!stopping) return;
    const timer = setTimeout(() => setStopping(false), STOP_MS);
    return () => clearTimeout(timer);
  }, [stopping]);

  // The canvas is absolutely placed in .chat-area, so without the
  // flex-filling .welcome wrapper it takes no room from the messages.
  if (!visible) return stopping ? <WelcomeBackdrop stopping /> : null;

  return (
    <div className="flex-1 w-full">
      <WelcomeBackdrop />
    </div>
  );
}
