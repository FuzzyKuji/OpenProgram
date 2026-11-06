"use client";
import { useActionIconAnimation } from "./use-action-icon-animation";

/**
 * Per-message hover action bar — React port of the legacy
 * `message-actions.js` / `-edit.js` / `-nav.js` trio.
 *
 * Sits in the message's `.message-actions-footer`, revealed on hover
 * (`.message:hover .message-actions`). Holds a timestamp badge and Copy,
 * then per role: a user message has Edit and Rewind to here, a reply has
 * Regenerate and Pin as chapter (which pins the turn above it: the pin is
 * stored on that turn's user message, lib/chat/transcript/chapter-pin.ts);
 * last the `< N/M >` sibling-version navigator. Quoting is the
 * text selection's (editing/quote-to-chat.tsx); copying the conversation
 * is in the conversation's ⋯ menu (pane/view-controls.tsx).
 *
 * Regenerate / Edit / checkout hit the REST endpoints and then re-request
 * the conversation over the shared WS — the server moves HEAD and
 * `load_session` re-feeds the React store.
 */
import {
  cloneElement,
  isValidElement,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";

import { useSessionStore, type ChatMsg } from "@/lib/session-store";
import { useTranslation } from "@/lib/i18n";
import { showToast } from "@/lib/format-utils/toast";
import { copyText } from "@/lib/clipboard";
import { setRunActive } from "@/lib/runtime-bridge/session/chat-handlers";
import { getSocket, runtimeState } from "@/lib/runtime-bridge/state";
import { sendRuntimeCommand } from "@/lib/runtime-bridge/session/session-load";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";
import { HoverTip, TipBody } from "@/components/ui/tooltip";
import { formatMessageTime } from "@/lib/chat/transcript/message-time";
import { turnUserMessageId } from "@/lib/chat/transcript/chapter";
import { setTurnChapter } from "@/lib/chat/transcript/chapter-pin";
import {
  BookmarkIcon,
  CheckIcon,
  CopyIcon,
  RefreshCwIcon,
  SquarePenIcon,
  UndoIcon,
} from "@/components/animated-icons";

/** Commands go out as they are; a `load_session` goes through the managed
 *  session read, since the transcript applies only the reply to a read it
 *  registered. */
function wsSend(payload: unknown): boolean {
  return sendRuntimeCommand(payload);
}

// Tools / action glyphs are the animated line icons (pqoqubbw, in
// ../../animated-icons). ActionButton drives the entire hover/focus target.
// chevL/chevR stay static (tiny ‹ › nav carets — not worth animating).
export const SVG = {
  copy: <CopyIcon />,
  check: <CheckIcon />,
  retry: <RefreshCwIcon />,
  pencil: <SquarePenIcon />,
  undo: <UndoIcon />,
  pin: <BookmarkIcon />,
  chevL: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="15 18 9 12 15 6" />
    </svg>
  ),
  chevR: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="9 18 15 12 9 6" />
    </svg>
  ),
};

function postJson(url: string, body: unknown): Promise<unknown> {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => {
    if (!r.ok) {
      return r.json().then((e) => {
        throw new Error(e.error || r.statusText);
      });
    }
    return r.json();
  });
}

/** Official ghost round icon button at the size closest to the 26px
 *  design (icon-xs, 24px); the glyph keeps its 16px size through
 *  message-actions.css. */
const ACTION_BUTTON_CLASS = buttonVariants({ variant: "ghost", size: "icon-xs" });

/** A message action whose whole button controls its shared animated icon.
 *  The label shows as a HoverTip (never a native title) and stays the
 *  button's aria-label. */
export function ActionButton({
  icon,
  title,
  onClick,
  disabled,
  extraClass,
  pressed,
}: {
  icon: ReactNode;
  title: string;
  onClick: () => void;
  disabled?: boolean;
  extraClass?: string;
  /** A toggle's state, exposed as aria-pressed. */
  pressed?: boolean;
}) {
  const { ref, handlers } = useActionIconAnimation(disabled);
  const node = isValidElement(icon)
    ? cloneElement(icon as ReactElement, { ref } as Record<string, unknown>)
    : icon;
  return (
    <HoverTip label={<TipBody title={title} />}>
      <button
        type="button"
        className={cn(ACTION_BUTTON_CLASS, "message-action-btn", extraClass)}
        aria-label={title}
        aria-pressed={pressed}
        disabled={disabled}
        onClick={onClick}
        {...handlers}
      >
        {node}
      </button>
    </HoverTip>
  );
}

/** The < > sibling-version arrow: the same ghost round button as
 *  ActionButton, with a HoverTip instead of a native title. */
export function NavButton({
  dir,
  label,
  disabled,
  onClick,
}: {
  dir: "prev" | "next";
  label: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <HoverTip label={<TipBody title={label} />}>
      <button
        type="button"
        className={cn(ACTION_BUTTON_CLASS, "message-nav-btn")}
        data-nav={dir}
        aria-label={label}
        disabled={disabled}
        onClick={onClick}
      >
        {dir === "prev" ? SVG.chevL : SVG.chevR}
      </button>
    </HoverTip>
  );
}

export function MessageTimestamp({ timestamp }: { timestamp?: number }) {
  if (
    typeof timestamp !== "number"
    || !Number.isFinite(timestamp)
    || timestamp <= 0
  ) return null;
  const value = new Date(timestamp > 1e12 ? timestamp : timestamp * 1000);
  const fullTime = value.toLocaleString();
  return (
    <span
      className="message-timestamp"
      data-tip={fullTime}
      aria-label={fullTime}
      tabIndex={0}
    >
      {formatMessageTime(value)}
    </span>
  );
}

export function MessageActions({
  msg,
  onEdit,
  sessionIdOverride,
}: {
  msg: ChatMsg;
  onEdit?: () => void;
  sessionIdOverride?: string;
}) {
  const { text: tr } = useTranslation();
  const focusedSessionId = useSessionStore((s) => s.currentSessionId);
  const sessionId = sessionIdOverride ?? focusedSessionId;
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  // One pin request at a time; the store already shows the new state, so
  // the button does not grey out while the server answers.
  const pinBusy = useRef(false);
  // A reply pins the turn above it: the user message that opened the turn.
  // Both reads are scalars, so streaming deltas elsewhere do not re-render.
  const turnUserId = useSessionStore((s) =>
    msg.role === "assistant" && sessionId
      ? turnUserMessageId(s.messageOrder?.[sessionId], s.messagesById ?? {}, msg.id)
      : undefined,
  );
  const chapterPinned = useSessionStore((s) =>
    Boolean(turnUserId && s.messagesById?.[turnUserId]?.chapterPinnedAt),
  );

  function copy() {
    const text = msg.content || "";
    if (!text) return;
    void copyText(text).then((ok) => {
      if (!ok) {
        showToast(tr("Could not copy the message", "未能复制消息"), { tone: "error" });
        return;
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    });
  }

  function retry() {
    if (!sessionId || !msg.id || busy) return;
    setBusy(true);
    postJson("/api/chat/retry", { session_id: sessionId, msg_id: msg.id })
      .then(() => {
        if (useSessionStore.getState().currentSessionId === sessionId) setRunActive(true);
        // The turn result must NOT be pushed onto the pre-fork mirror:
        // flag the session so the result handler reloads wholesale
        // (chat-handlers self-heal) — this load and the stream race.
        runtimeState._pendingBranchReload[sessionId] = true;
        wsSend({ action: "load_session", session_id: sessionId });
      })
      .catch((err) => {
        console.error("[message-actions] retry failed:", err);
        setBusy(false);
      });
  }

  function toggleChapter() {
    if (!sessionId || !turnUserId || pinBusy.current) return;
    const pin = !chapterPinned;
    pinBusy.current = true;
    void setTurnChapter(sessionId, turnUserId, pin).then((ok) => {
      pinBusy.current = false;
      if (!ok) {
        showToast(
          pin
            ? tr("Could not pin the chapter", "未能钉为章节")
            : tr("Could not unpin the chapter", "未能取消章节"),
          { tone: "error" },
        );
      }
    });
  }

  function rewindToHere() {
    if (!sessionId || !msg.id || busy) return;
    setBusy(true);
    const ok = wsSend({
      action: "rewind",
      session_id: sessionId,
      target_msg_id: msg.id,
    });
    if (!ok) {
      setBusy(false);
      return;
    }
    const ws = getSocket();
    if (!ws) {
      setBusy(false);
      return;
    }
    // Every exit path — reply, wrong session, timeout — runs through
    // `finish` so the listener is always detached and `busy` always
    // clears. A rewind that errors server-side without ever emitting a
    // frame used to leave this row's buttons disabled until a reload.
    let timer: ReturnType<typeof setTimeout> | undefined;
    const finish = () => {
      ws.removeEventListener("message", onMsg);
      if (timer) clearTimeout(timer);
      setBusy(false);
    };
    function onMsg(ev: MessageEvent) {
      try {
        const data = JSON.parse(ev.data);
        if (data?.type !== "rewind_result") return;
        const d = data?.data ?? {};
        // Match on the session the frame belongs to: a rewind running in
        // another conversation emits the same frame type, and answering
        // to it here would reload + prefill the wrong chat.
        if (d.session_id && d.session_id !== sessionId) return;
        finish();
        const errors: string[] = d.errors ?? [];
        // `new_head_id` decides success: the backend moves HEAD whenever
        // it is set, and a non-empty `errors` then only means some files
        // failed to restore. Treating that as overall failure would leave
        // the transcript on a head the server no longer has.
        if (d.new_head_id) {
          const n = d.turns_reverted ?? 0;
          if (errors.length) {
            showToast(
              tr(
                `Rewound ${n} turn${n === 1 ? "" : "s"}, but ${errors.length} file${errors.length === 1 ? "" : "s"} failed to restore: ${errors[0]}`,
                `已回退 ${n} 轮，但 ${errors.length} 个文件恢复失败：${errors[0]}`,
              ),
              { tone: "warn" },
            );
          } else {
            showToast(tr(`Rewound ${n} turn${n === 1 ? "" : "s"}`, `已回退 ${n} 轮对话`));
          }
          // Prefill composer with the rewound user message
          if (d.user_text) {
            useSessionStore.getState().setComposerInputFor(sessionId!, d.user_text);
          }
          // Reload session so rewound messages disappear
          wsSend({ action: "load_session", session_id: sessionId });
        } else {
          const err = d.error ?? (errors.length ? errors.join("; ") : "unknown error");
          showToast(tr(`Rewind failed: ${err}`, `回退失败：${err}`));
        }
      } catch {
        /* ignore */
      }
    }
    ws.addEventListener("message", onMsg);
    // ponytail: fixed 30s ceiling. A rewind touching thousands of backed-up
    // files could in principle outrun it; make it adaptive if that shows up.
    timer = setTimeout(() => {
      finish();
      showToast(tr("Rewind timed out", "回退超时，未收到结果"), { tone: "error" });
    }, 30_000);
  }

  function checkout(targetId: string | undefined, dir: -1 | 1) {
    if (!sessionId || !targetId || busy) return;
    setBusy(true);
    // 0ms feedback (interaction-feedback policy): advance the < N/M >
    // label to the target version immediately so the click registers,
    // rather than waiting the checkout POST + load_session round-trip that
    // swaps the whole transcript. The reload rebuilds this row from the
    // target branch (its content backfills); on failure we revert the
    // label + re-enable the nav.
    const store = useSessionStore.getState();
    const prevIdx = msg.siblingIndex;
    store.updateMessage(sessionId, msg.id, {
      siblingIndex: (msg.siblingIndex ?? 0) + dir,
    });
    postJson("/api/chat/checkout", { session_id: sessionId, msg_id: targetId })
      .then(() => {
        runtimeState._postCheckoutScrollTo = targetId;
        wsSend({ action: "load_session", session_id: sessionId });
      })
      .catch((err) => {
        console.error("[message-actions] checkout failed:", err);
        if (useSessionStore.getState().messagesById[msg.id]) {
          useSessionStore
            .getState()
            .updateMessage(sessionId, msg.id, { siblingIndex: prevIdx });
        }
        showToast(tr("Version switch failed.", "版本切换失败。"), { tone: "error" });
        setBusy(false);
      });
  }

  const total = msg.siblingTotal ?? 0;
  const idx = msg.siblingIndex ?? 0;

  return (
    <div className={cn("message-actions", chapterPinned && "is-chapter-pinned")}>
      <MessageTimestamp timestamp={msg.timestamp} />
      <ActionButton
        icon={copied ? SVG.check : SVG.copy}
        title={tr("Copy", "复制")}
        extraClass={copied ? "is-copied" : undefined}
        onClick={copy}
      />
      {msg.role === "assistant" ? (
        <ActionButton
          icon={SVG.retry}
          title={tr("Regenerate", "重新生成")}
          disabled={busy}
          onClick={retry}
        />
      ) : null}
      {turnUserId ? (
        <ActionButton
          icon={SVG.pin}
          title={chapterPinned ? tr("Unpin chapter", "取消章节") : tr("Pin as chapter", "钉为章节")}
          pressed={chapterPinned}
          extraClass={chapterPinned ? "is-chapter" : undefined}
          onClick={toggleChapter}
        />
      ) : null}
      {onEdit ? (
        <ActionButton
          icon={SVG.pencil}
          title={tr("Edit message", "编辑消息")}
          onClick={onEdit}
        />
      ) : null}
      {msg.role === "user" ? (
        <ActionButton
          icon={SVG.undo}
          title={tr("Rewind to here", "回退到这里")}
          disabled={busy}
          onClick={rewindToHere}
        />
      ) : null}
      {total > 1 ? (
        <div className="message-nav">
          <NavButton
            dir="prev"
            label={tr("Previous version", "上一个版本")}
            disabled={busy || idx <= 1}
            onClick={() => checkout(msg.prevSiblingId, -1)}
          />
          <span className="message-nav-label">
            {idx} / {total}
          </span>
          <NavButton
            dir="next"
            label={tr("Next version", "下一个版本")}
            disabled={busy || idx >= total}
            onClick={() => checkout(msg.nextSiblingId, 1)}
          />
        </div>
      ) : null}
    </div>
  );
}
