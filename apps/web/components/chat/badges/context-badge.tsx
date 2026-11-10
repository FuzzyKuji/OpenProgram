"use client";

/**
 * Per-conversation token-usage badge for the Composer's bottom row.
 *
 * Replaces the legacy `#tokenBadge` DOM node (defined in
 * `public/html/index.html`) and the imperative render code in
 * `public/js/shared/providers.js` (`_renderTokenBadge` /
 * `refreshTokenBadge`). Both legacy paths now push the latest
 * `{input, output, cache_read}` tuple into the Zustand store via
 * `setContextStats`; this component is the sole renderer.
 *
 * Visual: a small progress ring (Claude Code style — 12px svg in a
 * 20px button, var(--border) track, var(--accent-orange) arc starting
 * at 12 o'clock). ALWAYS renders: a session with no usage yet (or no
 * session at all) shows the empty ring at 0 progress instead of
 * vanishing from the controls row. Tooltip carries the
 * "Context used / window (pct)" breakdown.
 */
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { useSessionStore } from "@/lib/session-store";
import { useSessionScope } from "@/lib/session-store/session-scope";
import { HoverTip } from "@/components/ui/tooltip";
import { FillIcon } from "@/components/ui/fill-icon";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { translateText } from "@/lib/i18n";
import { ContextBreakdownPanel } from "./context-breakdown-panel";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  readContextBreakdownCache,
  readDraftContextBreakdown,
  subscribeContextBreakdownCache,
  warmContextBreakdown,
  warmDraftContextBreakdown,
  writeContextBreakdownCache,
} from "@/lib/chat/context-breakdown-cache";

interface ContextBadgeProps {
  /** Active conversation id. The component is keyed on this so a
   *  session switch immediately drops to "no data" until the new
   *  session's usage arrives. Accepts ``string | null`` (no session) and
   *  the legacy ``sessionId`` prop name preserved for the unmigrated
   *  `<ChatView>` call site. */
  sessionId?: string | null;
}

/** Whether `ref`'s element is laid out (not inside a display:none shell).
 *  A ResizeObserver reports the change both ways: an element that stops
 *  being rendered shrinks to 0×0, one that comes back grows again. */
function useLaidOut(ref: RefObject<HTMLElement | null>): boolean {
  const [laidOut, setLaidOut] = useState(false);
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    const update = () => setLaidOut(node.getClientRects().length > 0);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, [ref]);
  return laidOut;
}

export function ContextBadge({ sessionId }: ContextBadgeProps) {
  // Resolve session: caller may pass `sessionId` (legacy ChatView path)
  // or omit it (Composer path) — in the latter case we fall back to the
  // store's current conversation id.
  const currentSessionId = useSessionStore((s) => s.currentSessionId);
  const sid = sessionId ?? currentSessionId;

  // 点 badge 弹出 /context 分类分解面板（随时看当前会话 context 构成）。
  // open 状态放本会话的 scope store —— /context slash 命令也能切它，而分屏
  // 时两个 badge 各读各的，点一个不会两边同时弹。
  const scopeOpen = useSessionScope((s) => s.contextPanelOpen);
  const setPanelOpen = useSessionScope((s) => s.setContextPanelOpen);
  // The same conversation can have a second, hidden composer (the
  // single-pane shell stays mounted under display:none in a split view)
  // reading the same scope; only a ring that is laid out opens its card,
  // or the hidden one's card would portal out to the window's corner.
  const ringRef = useRef<HTMLButtonElement>(null);
  const panelOpen = useLaidOut(ringRef) && scopeOpen;
  // 当前分支头：切分支时 store.heads 会更新，弹窗据此重取该分支的上下文。
  const headId = useSessionStore((s) => (sid ? s.heads[sid] : undefined));

  const ringUsed = useSessionStore((s) => (sid ? s.tokens[sid]?.total_used : undefined));
  const ringBasis = useSessionStore((s) => (sid ? s.tokens[sid]?.basis : undefined));
  const ringWindow = useSessionStore((s) => (sid ? s.contextWindow[sid] : undefined));
  const compacting = useSessionStore((s) =>
    Boolean(sid && s.compactionUi[sid]?.running),
  );

  // Paint from the ring the moment this session is focused. GET /context
  // only fills category detail, and never blocks the click.
  useEffect(() => {
    if (!sid) return;
    if (!readContextBreakdownCache(sid, headId ?? null)
        && (ringUsed != null || ringWindow)) {
      writeContextBreakdownCache(sid, headId ?? null, {
        total_used: ringUsed,
        window: ringWindow,
        context_window: ringWindow,
        basis: ringBasis ?? undefined,
      });
    }
    if (!readContextBreakdownCache(sid, headId ?? null)
        || readContextBreakdownCache(sid, headId ?? null)?.tools == null) {
      warmContextBreakdown(sid, headId ?? null, { focus: true });
    }
  }, [sid, headId, ringUsed, ringWindow, ringBasis]);

  // The shared Popover owns placement (above the ring, right edges aligned,
  // lifted 9px: the row's 10px band gap minus the 1px ring, so it sits on
  // the input box like the other bottom-row popovers), Escape and a press
  // or focus outside; a press on the ring itself is never "outside". A
  // press on a native page (a web tab, the floating preview) never reaches
  // this document, it only takes the window's focus away, so blur closes
  // too.
  useEffect(() => {
    if (!panelOpen) return;
    const onBlur = () => setPanelOpen(false);
    window.addEventListener("blur", onBlur);
    return () => window.removeEventListener("blur", onBlur);
  }, [panelOpen, setPanelOpen]);
  // A click on the ring toggles from the state the press found. Anything
  // that closes the card during the press (the window blurring as focus
  // comes back from a native page) must not let the click read "closed"
  // and open it again: that was the close-then-reopen flash. A keyboard
  // click has no press and toggles the current state.
  const openAtPress = useRef<boolean | null>(null);

  const fallbackProvider = useSessionStore((s) => s.agentSettings.chat?.provider);
  const fallbackModel = useSessionStore((s) => s.agentSettings.chat?.model);
  const draftProjectId = useSessionStore((s) =>
    s.activeChatKey ? s.pendingProjectsByChat[s.activeChatKey] ?? null : null);
  // No session yet: the ring and panel show what the first message would
  // carry (system prompt, tools, memory) against the selected model.
  const [draft, setDraft] = useState(() =>
    sid ? null : readDraftContextBreakdown(fallbackProvider, fallbackModel, draftProjectId));
  useEffect(() => {
    if (sid) return;
    const sync = () => setDraft(readDraftContextBreakdown(fallbackProvider, fallbackModel, draftProjectId));
    sync();
    warmDraftContextBreakdown(fallbackProvider, fallbackModel, draftProjectId);
    return subscribeContextBreakdownCache(sync);
  }, [sid, fallbackProvider, fallbackModel, draftProjectId]);
  const sessionUsage = useSessionStore((s) => (sid ? s.tokens[sid] : undefined));
  const sessionWindow = useSessionStore((s) => (sid ? s.contextWindow[sid] : undefined));
  const usage = sid ? sessionUsage
    : draft ? { total_used: draft.total_used, basis: "estimated" as const } : undefined;
  const ctxWindow = sid ? sessionWindow : draft?.window || draft?.context_window;

  // 永远渲染圆环：还没有 usage 的会话（或还没有会话）显示 0 进度的空环，
  // 而不是整个消失（“圆环不见了”就是以前 return null 造成的）。
  // tooltip: 详细 breakdown + 模型/provider 元信息. usage 里的 model 来自
  // backend context_stats 事件, 比 agentSettings 更精确 (单 turn 内可能
  // 切了 provider, agentSettings 是最终值).
  const modelLabel = usage?.model || fallbackModel || "";
  const providerLabel = usage?.provider || fallbackProvider || "";
  const metaLine = [providerLabel, modelLabel].filter(Boolean).join(" · ");

  // 窗口和用量都取服务端算好的那一份（context_stats 的 window/total_used），
  // 和 /context 面板同源 —— 两处永远显示同一个数。服务端在真实请求完成
  // （measured）和图变化（compaction / 切模型 / 切分支，estimated）时各广播
  // 一次，所以这个数始终描述"此刻"。窗口未知时退 200k 保守默认。
  const win = ctxWindow && ctxWindow > 0 ? ctxWindow : 200_000;

  // 旧事件（重连回放的历史 context_stats）没有 total_used，退回最后一次
  // API 调用的 prompt 体积（input+cache_read）作近似。
  const used =
    usage?.total_used ??
    (usage?.context || (usage?.input || 0) + (usage?.cache_read || 0));
  const pct = Math.max(0, Math.min(1, used / win));

  // 占用越高颜色越警示：<50% 绿，50–80% 黄，≥80% 红。
  const arcColor = pct >= 0.8 ? "var(--danger-soft)" : pct >= 0.5 ? "var(--warning-soft)" : "var(--success-soft)";

  // tooltip 用 Claude Code 那种「Context 用了多少/共多少 (百分比)」格式
  const fmtNum = (n: number) =>
    n >= 1_000_000 ? (n / 1_000_000).toFixed(1) + "M" : n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n);
  // basis 说明这个数从哪来：measured = 上一次真实请求实测，estimated =
  // 那之后图变了（压缩/切模型/切分支）按当前图重估。
  const basisLabel = usage?.basis === "estimated" ? " · est." : "";
  const ringTooltip = compacting
    ? translateText("Compacting context…", "正在压缩上下文…")
    : `Context ${fmtNum(used)} / ${fmtNum(win)} (${(pct * 100).toFixed(0)}%)${basisLabel}` +
      (metaLine ? ` · ${metaLine}` : "");

  // 环形进度（Claude Code 实测：12px svg、描边 2、轨道 var(--border)、
  // 进度 var(--accent-orange)、-90° 起点）
  const R = 5;               // 半径 — 12px viewBox 里留 1px 描边余量
  const SW = 2;              // 描边宽度
  const C = 2 * Math.PI * R; // 周长

  return (
    <Popover open={panelOpen} onOpenChange={setPanelOpen}>
      {/* HoverTip = 全站统一黑提示（原生 title 又慢又不是黑卡）；
          aria-expanded（PopoverTrigger 标的）让面板开着时不冒提示。 */}
      <HoverTip label={ringTooltip}>
      <PopoverTrigger asChild>
      <button
        ref={ringRef}
        type="button"
        className={
          cn(buttonVariants({ variant: "elevated", size: "icon-sm" }))
          + " context-ring-badge"
          + (compacting ? " is-busy" : "")
        }
        onPointerDown={() => { openAtPress.current = panelOpen; }}
        onClick={(event) => {
          const wasOpen = openAtPress.current ?? panelOpen;
          openAtPress.current = null;
          // Skips the trigger's own toggle, which reads the current state.
          event.preventDefault();
          setPanelOpen(!wasOpen);
        }}
        aria-label="Context usage"
      >
        {/* The ring already fills its 16 px box (CSS sizes the svg); the
            box grows to 18 px on hover like every composer icon. */}
        <FillIcon crop={false}>
        <svg width="12" height="12" viewBox="0 0 12 12">
          <circle
            cx="6"
            cy="6"
            r={R}
            fill="none"
            stroke="var(--border)"
            strokeWidth={SW}
          />
          <circle
            cx="6"
            cy="6"
            r={R}
            fill="none"
            stroke={arcColor}
            strokeWidth={SW}
            strokeLinecap="round"
            style={{ transition: "stroke 400ms ease, stroke-dashoffset 400ms ease" }}
            strokeDasharray={C}
            strokeDashoffset={C * (1 - pct)}
            transform="rotate(-90 6 6)"
          />
        </svg>
        </FillIcon>
      </button>
      </PopoverTrigger>
      </HoverTip>
      {/* The card alone takes down a native page (a web tab, the floating
          preview) it overlaps; one elsewhere stays live. Focus stays where
          it was (the composer when /context opened it). */}
      <PopoverContent
        data-native-view-occluder="true"
        side="top"
        align="end"
        sideOffset={9}
        className="w-auto border-0 bg-transparent p-0 shadow-none"
        onOpenAutoFocus={(event) => event.preventDefault()}
        onCloseAutoFocus={(event) => event.preventDefault()}
      >
        <ContextBreakdownPanel
          key={JSON.stringify([sid, headId ?? null])}
          sessionId={sid}
          headId={headId ?? null}
          onClose={() => setPanelOpen(false)}
        />
      </PopoverContent>
    </Popover>
  );
}
