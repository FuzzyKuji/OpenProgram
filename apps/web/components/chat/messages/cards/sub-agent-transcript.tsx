"use client";

/**
 * A sub-agent's own conversation (its prompts, steps and replies, live
 * while it runs), drawn under its step row in the turn's timeline when the
 * row opens. The turn's transcript keeps only its own reply, and the step
 * row is the one place a spawned agent shows (styles in
 * sub-agent-transcript.css).
 */
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  agentJobFor,
  loadSubAgentTranscript,
  promptBody,
  subAgentChatKey,
} from "@/lib/chat/transcript/sub-agent-transcripts";
import { useTranslation } from "@/lib/i18n";
import { useSessionStore, type ChatMsg } from "@/lib/session-store";

import { AssistantBubble } from "../bubbles/assistant-bubble";
import { TodoPlans } from "./todo-plan-card";

export const LIVE_STATUSES = new Set(["running", "pending", "queued"]);
const TERMINAL = new Set(["completed", "errored", "failed", "cancelled"]);

/** The store key of a spawn card's agent: its first Job, else its branch head. */
export function subAgentKey(card: ChatMsg): string {
  const attach = card.attach || {};
  return attach.job_id || attach.head_id || card.id;
}

function PromptTurn({ msg }: { msg: ChatMsg }) {
  const { text } = useTranslation();
  const [open, setOpen] = useState(false);
  const prompt = promptBody(msg.content || "");
  if (!prompt.text) return null;
  return (
    <button
      type="button"
      className="sub-agent-prompt"
      data-open={open ? "1" : "0"}
      aria-expanded={open}
      onClick={() => setOpen((value) => !value)}
    >
      <span className="sub-agent-prompt-label">
        {prompt.message ? text("Message", "消息") : text("Task", "任务")}
      </span>
      <span className="sub-agent-prompt-text">{prompt.text}</span>
    </button>
  );
}

function Turn({ id, sessionId }: { id: string; sessionId: string }) {
  const msg = useSessionStore((s) => s.messagesById[id]);
  if (!msg) return null;
  if (msg.role === "user") return <PromptTurn msg={msg} />;
  return (
    <>
      <AssistantBubble msg={msg} sessionIdOverride={sessionId} embedded />
      {/* The sub-agent's own plan sits under its own reply. */}
      <TodoPlans sessionId={sessionId} rowId={id} />
    </>
  );
}

export function SubAgentTranscript({ card, sessionId, onTip }: {
  card: ChatMsg;
  sessionId: string;
  /** The agent's newest reply, once its branch is loaded. */
  onTip?: (tip: string) => void;
}) {
  const { text } = useTranslation();
  const attach = card.attach || {};
  const key = subAgentKey(card);
  const jobId = attach.job_id || undefined;
  const headId = attach.head_id || undefined;
  const status = attach.status || "completed";
  const chatKey = subAgentChatKey(sessionId, key);
  const order = useSessionStore((s) => s.messageOrder[chatKey]);
  const [loading, setLoading] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  // A running agent opens at its newest output; a finished one at its task.
  const followRef = useRef(LIVE_STATUSES.has(status));
  const tipRef = useRef(onTip);
  tipRef.current = onTip;

  useEffect(() => {
    let live = true;
    const load = () => {
      setLoading(true);
      void loadSubAgentTranscript(sessionId, key, { jobId, headId })
        .then((tip) => { if (live && tip) tipRef.current?.(tip); })
        .finally(() => { if (live) setLoading(false); });
    };
    load();
    // A finished turn of this agent (its first one, or a later message sent
    // to it) is now on the server; read the branch again.
    const onStatus = (event: WindowEventMap["op:job-status"]) => {
      const detail = event.detail;
      if (!detail?.job_id || detail.session_id !== sessionId) return;
      if (!TERMINAL.has(detail.status || "")) return;
      if (agentJobFor(detail.job_id) === key) load();
    };
    window.addEventListener("op:job-status", onStatus);
    return () => {
      live = false;
      window.removeEventListener("op:job-status", onStatus);
    };
  }, [sessionId, key, jobId, headId]);

  // Stay at the newest output while it streams, unless the reader scrolled up.
  useLayoutEffect(() => {
    const body = bodyRef.current;
    if (!body || typeof ResizeObserver === "undefined") return;
    const content = body.firstElementChild;
    if (!content) return;
    const observer = new ResizeObserver(() => {
      if (followRef.current) body.scrollTop = body.scrollHeight;
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [chatKey]);

  const ids = order ?? [];
  return (
    <div
      ref={bodyRef}
      className="sub-agent-body"
      onScroll={(event) => {
        const body = event.currentTarget;
        followRef.current = body.scrollHeight - body.scrollTop - body.clientHeight < 24;
      }}
    >
      <div className="sub-agent-turns">
        {ids.length === 0 && attach.prompt ? (
          <PromptTurn msg={{ id: `${card.id}_prompt`, role: "user", content: attach.prompt }} />
        ) : null}
        {ids.map((id) => <Turn key={id} id={id} sessionId={sessionId} />)}
        {ids.length === 0 ? (
          <div className="sub-agent-empty" role="status">
            {loading
              ? text("Loading…", "加载中…")
              : LIVE_STATUSES.has(status)
                ? text("Waiting for output…", "等待输出…")
                : text("No output.", "没有输出。")}
          </div>
        ) : null}
      </div>
    </div>
  );
}
