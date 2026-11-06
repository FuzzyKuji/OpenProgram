"use client";

/** One transcript row: picks the bubble, card or event a message renders
 *  as, with the recyclable wrapper the virtualized list mounts. */
import { TranscriptSessionContext } from "../transcript-view-scope";
import { memo, useLayoutEffect, useRef, useState } from "react";
import { useMessageById, useSessionStore, type ChatMsg } from "@/lib/session-store";
import { messageArrivedWithin } from "@/lib/session-store/messages/message-arrivals";
import { getRowHeight, setRowHeight } from "@/lib/chat/history/message-window";
import { AgentNoticeRows, ReceivedMessageRow } from "../../cards/agent-event-row";
import { AssistantBubble } from "../../bubbles/assistant-bubble";
import { AttachCard } from "../../cards/attach-card";
import { RuntimeBlock } from "../../runtime/runtime-block";
import { SpawnedFromCard } from "../../cards/spawned-from-card";
import { UserBubble } from "../../bubbles/user-bubble";
import { MessageTimestamp } from "../../bubbles/message-actions";
import { readReceipt } from "@/lib/chat/transcript/agent-notices";
import { SYSTEM_EVENT_KINDS, SystemEventRow, CompactionCard } from "./system-event-rows";

/** A row mounted this soon after its message arrived still plays msgAppear. */
const APPEAR_WINDOW_MS = 1000;

/** goal 循环的内部 spawn 轮 label（openprogram/programs/workflow/goal/
 *  __init__.py 的 run_agent_turn(label=...)，经 spawnedFrom.label 到达）。
 *  只有这些轮才做 JSON 尾巴折叠——绝不按"内容长得像 JSON"匹配普通消息。 */
const GOAL_SPAWN_LABELS = new Set(["goal 判定", "goal 完善"]);

/** Internal verifier output stays in durable execution history, not chat. */
export function AssistantMessage({ msg, sessionIdOverride }: {
  msg: ChatMsg; sessionIdOverride?: string;
}) {
  const spawnLabel = useSessionStore((s) =>
    msg.calledBy ? s.messagesById[msg.calledBy]?.spawnedFrom?.label : undefined);
  if (msg.goalVerification || (spawnLabel && GOAL_SPAWN_LABELS.has(spawnLabel))) return null;
  return <AssistantBubble msg={msg} sessionIdOverride={sessionIdOverride} />;
}

function dispatch(msg: ChatMsg, sessionIdOverride?: string) {
  if (msg.role === "system") {
    if (msg.kind === "compaction" && msg.slot === "card") {
      return <CompactionCard msg={msg} />;
    }
    if (msg.kind && SYSTEM_EVENT_KINDS.has(msg.kind)) {
      return <SystemEventRow msg={msg} />;
    }
    return (
      <div className="message system" data-msg-id={msg.id}>
        {msg.content}
        <div className="message-actions-footer">
          <div className="message-actions">
            <MessageTimestamp timestamp={msg.timestamp} />
          </div>
        </div>
      </div>
    );
  }
  if (msg.role === "assistant" && msg.function === "attach") {
    return (
      <div className="attach-row" data-msg-id={msg.id}>
        <AttachCard msg={msg} />
      </div>
    );
  }
  if (msg.role === "user" && msg.source === "job_followup" && msg.notice) {
    return <AgentNoticeRows msg={msg} items={msg.notice} />;
  }
  const receipt = msg.role === "user" && msg.display !== "runtime" && !msg.spawnedFrom
    ? readReceipt(msg.content || "")
    : null;
  if (receipt) return <ReceivedMessageRow msg={msg} receipt={receipt} />;
  if (msg.role === "user" && msg.spawnedFrom) {
    return (
      <>
        <SpawnedFromCard msg={msg} />
        <UserBubble msg={msg} sessionIdOverride={sessionIdOverride} />
      </>
    );
  }
  if (msg.display === "runtime") {
    if (msg.role === "user") return null;
    // 手动函数运行（fn-form / /run）：RuntimeBlock 内部已统一为
    // 时间线组件（根行 + 递归子树，子节点逐层展开）。
    return (
      <div className="runtime-card-host">
        <RuntimeBlock msg={msg} sessionIdOverride={sessionIdOverride} />
      </div>
    );
  }
  if (msg.role === "user") {
    return <UserBubble msg={msg} sessionIdOverride={sessionIdOverride} />;
  }
  return <AssistantMessage msg={msg} sessionIdOverride={sessionIdOverride} />;
}

export const MessageRow = memo(function MessageRow({
  id,
  sessionIdOverride,
}: {
  id: string;
  sessionIdOverride?: string;
}) {
  const msg = useMessageById(id);
  // A reply a restart cut off is drawn by the reply that continues it.
  const continued = useSessionStore((s) => !!msg?.continuedBy && !!s.messagesById[msg.continuedBy]);
  if (!msg || msg.steeringReplyId || continued) return null;
  return (
    <TranscriptSessionContext.Provider value={sessionIdOverride}>
      {dispatch(msg, sessionIdOverride)}
    </TranscriptSessionContext.Provider>
  );
});

/** A row outside the recycling window (short transcripts). Like a slot, it
 *  plays msgAppear only when its message has just arrived. */
export const PlainRow = memo(function PlainRow({
  id,
  sessionIdOverride,
}: {
  id: string;
  sessionIdOverride?: string;
}) {
  const [appear] = useState(() => messageArrivedWithin(id, APPEAR_WINDOW_MS));
  return (
    <div className="msg-row" data-appear={appear ? "" : undefined} style={{ display: "contents" }}>
      <MessageRow id={id} sessionIdOverride={sessionIdOverride} />
    </div>
  );
});

export const RecyclableRow = memo(function RecyclableRow({
  id,
  chatKey,
  live,
  onMeasured,
  sessionIdOverride,
}: {
  id: string;
  chatKey: string;
  live: boolean;
  onMeasured: () => void;
  sessionIdOverride?: string;
}) {
  const slotRef = useRef<HTMLDivElement>(null);
  // Only a message that just arrived plays msgAppear; the same row mounted
  // again (a split, the shell coming back into view) shows as it is.
  const [appear] = useState(() => messageArrivedWithin(id, APPEAR_WINDOW_MS));
  const height = getRowHeight(chatKey, id);
  const show = live || height == null;
  // The height a placeholder stood at before this row rendered. It may be
  // an estimate from another width, see noteChatWidth.
  const placeholderRef = useRef<number | null>(null);
  useLayoutEffect(() => {
    const el = slotRef.current;
    if (!el) return;
    if (!show) {
      el.dataset.seen = "1";
      placeholderRef.current = getRowHeight(chatKey, id) ?? null;
      return;
    }
    const estimate = placeholderRef.current;
    placeholderRef.current = null;
    if (estimate != null) {
      // A row coming in above the view: the chat area has no native scroll
      // anchoring, so take up the estimate's error here or the visible
      // rows jump by it.
      const next = el.offsetHeight;
      const area = el.closest<HTMLElement>(".chat-area");
      if (area && next > 0 && next !== estimate
        && el.getBoundingClientRect().top + estimate <= area.getBoundingClientRect().top) {
        area.scrollTop += next - estimate;
      }
    }
    const write = () => {
      const next = el.offsetHeight;
      if (next > 0 && setRowHeight(chatKey, id, next) === "first") onMeasured();
    };
    write();
    const ro = new ResizeObserver(write);
    ro.observe(el);
    return () => ro.disconnect();
  }, [show, id, chatKey, onMeasured]);
  return (
    <div
      ref={slotRef}
      data-msg-slot={id}
      data-appear={appear ? "" : undefined}
      className="msg-slot"
      style={!show && height != null ? { height } : undefined}
    >
      {show ? (
        <div style={{ display: "contents" }}>
          <MessageRow id={id} sessionIdOverride={sessionIdOverride} />
        </div>
      ) : null}
    </div>
  );
});
