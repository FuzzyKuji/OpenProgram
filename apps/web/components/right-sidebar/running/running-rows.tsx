"use client";

/** The Running panel's building blocks: status glyphs, the status pill, one
 *  row, and the expandable long-text block. */
import { type CSSProperties, type ReactNode } from "react";
import { ChevronRight, MessageSquareText } from "lucide-react";
import { SolarIcon, type SolarIconName } from "@/components/solar-icons";
import { BotGlyph } from "@/components/avatar/bot/bot-glyph";
import { type ToolTone } from "@/components/chat/messages/execution/tool-presentation";
import { Button } from "@/components/ui/button";
import styles from "./running-panel.module.css";

export type Text = (en: string, zh: string) => string;

export type Tone = "warn" | "run" | "ok" | "err" | "muted";

const DOT: Record<Tone, string> = {
  warn: "--warn", run: "--neutral pulse-opacity", ok: "--ok", err: "--err", muted: "is-muted",
};

export function Glyph({ name, tone, large }: { name: SolarIconName; tone: ToolTone | "run"; large?: boolean }) {
  return <span className={styles.glyph} data-tone={tone} data-large={large ? "1" : undefined} aria-hidden="true">
    <SolarIcon name={name} size={large ? 22 : 16} motionPreset="none" />
  </span>;
}

/** An agent: its character, flat, in the folder colour (a branch's own:
 *  its lane colour), a size up from the other rows. The main agent wears
 *  the conversation Agent's character, a sub-agent the one its name gives,
 *  as on the graph. */
export function AgentGlyph({ shape, small, color }: { shape: string; small?: boolean; color?: string | null }) {
  return <span className={styles.agentGlyph} data-small={small ? "1" : undefined} style={color ? { color } : undefined} aria-hidden="true">
    <BotGlyph shape={shape} size={small ? 16 : 22} />
  </span>;
}

/** A conversation or a run: a line glyph in the text colour. */
export function RunGlyph() {
  return <span className={styles.glyph} data-tone="run" aria-hidden="true"><MessageSquareText size={16} strokeWidth={1.8} /></span>;
}

export function Status({ tone, children, dot = true }: { tone: Tone; children: ReactNode; dot?: boolean }) {
  return <span className={styles.status} data-tone={tone}>
    {dot && <span className={`indicator-dot sm ${DOT[tone]}`} aria-hidden="true" />}
    <span className={styles.statusText}>{children}</span>
  </span>;
}

/** `first`: the first row under its parent, whose elbow reaches up into
 *  the parent's row; later siblings continue the run from the row above. */
export type Line = { depth: number; last: boolean; first: boolean; guides: number[] };

/** ``sub``: a monospace line under the title (a program's command);
 *  ``extra``: what goes under the status (a program's progress bar). */
/** A row: its glyph, with a red count on the corner when something
 *  waits for the reader (the Dock's badge), the name, and one line of
 *  status coloured by its tone (running blue, failed red, else muted). */
export function Row({ glyph, title, badge, sub, status, tone, onOpen, line, extra, count = 0 }: {
  glyph: ReactNode; title: string; badge?: ReactNode; sub?: string; status: ReactNode; tone: Tone; onOpen: () => void; line?: Line; extra?: ReactNode;
  /** How many things wait for the reader here. */
  count?: number;
}) {
  const row = <Button variant="ghost" className={styles.row} onClick={onOpen}>
    <span className="relative flex-none grid place-items-center">
      {glyph}
      {count > 0 && <span className={styles.countBadge}>{count > 99 ? "99+" : count}</span>}
    </span>
    <span className="grid gap-[1px] min-w-0 flex-1">
      {badge ? <span className="flex items-center gap-[6px] min-w-0"><span className={styles.name}>{title}</span>{badge}</span> : <span className={styles.name}>{title}</span>}
      {sub && <span className={styles.sub}>{sub}</span>}
      {status ? <Status tone={tone} dot={false}>{status}</Status> : null}
      {extra}
    </span>
    <ChevronRight size={14} className={styles.chevron} aria-hidden="true" />
  </Button>;
  // A sub-agent sits under the branch that started it: an elbow from that
  // branch's glyph, the line running on to its later siblings, and the
  // lines of the rows above that still have siblings to reach.
  if (!line) return row;
  const depth = Math.min(line.depth, 4);
  return <div className={`${styles.branch} relative ml-[calc(var(--depth,_1)_*_var(--branch-indent))]`} data-last={line.last ? "1" : "0"} data-first={line.first ? "1" : "0"} style={{ "--depth": depth } as CSSProperties}>
    {line.guides.filter(level => level < depth).map(level => <span key={level} className={styles.guide} aria-hidden="true" style={{ "--up": depth - level } as CSSProperties} />)}
    {row}
  </div>;
}

/** A task or command: five lines, then the whole text on request. */
export function Long({ label, body, mono, open, onToggle, text }: {
  label: string; body: string; mono: boolean; open: boolean; onToggle: () => void; text: Text;
}) {
  const long = body.length > 280 || body.split("\n").length > 5;
  return <>
    <h4 className={styles.section}>{label}</h4>
    <p className={mono ? styles.code : styles.prose} data-open={open || !long ? "1" : "0"}>{body}</p>
    {long && <Button type="button" variant="link" size="xs" onClick={onToggle}>{open ? text("Show less", "收起") : text("Show all", "展开全文")}</Button>}
  </>;
}
