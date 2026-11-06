/**
 * Messages agents pass to each other, read back for the chat to draw as
 * one-line rows instead of bubbles the user never typed:
 *
 *  - a background-agent notice (``source: "job_followup"``): its
 *    ``notice`` items name each agent that finished, and each item's part
 *    of the notice text (agent/job/notices.py ``notice_text``) holds the
 *    reply to show when the row opens;
 *  - a message delivered to a branch: it starts with the receipt line
 *    ``[message|task from SID:HEAD (sender)]`` (send_message/delivery.py).
 */
import type { NoticeItem } from "../../session-store/types";

const KINDS = new Set(["report", "reply", "idle"]);

export function readNotice(raw: unknown): NoticeItem[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const items = raw.flatMap((r): NoticeItem[] => {
    if (!r || typeof r !== "object") return [];
    const o = r as Record<string, unknown>;
    if (typeof o.kind !== "string" || !KINDS.has(o.kind) || typeof o.line !== "string") return [];
    return [{
      kind: o.kind as NoticeItem["kind"],
      name: typeof o.name === "string" ? o.name : "",
      failed: o.failed === true,
      address: typeof o.address === "string" ? o.address : "",
      line: o.line,
    }];
  });
  return items.length ? items : undefined;
}

const FOOTER = "Carry on with the user's request from here";
const CONTINUE = "To continue with it, use send_message(";

/** What the row for ``items[index]`` shows when it opens: the branch's
 *  reply for a reply or idle item, the task it was given for a report
 *  (the report itself is in the agent's context, not the notice). */
export function noticeDetail(content: string, items: NoticeItem[], index: number): string {
  const lines = content.split("\n");
  const starts = new Set(items.map((it) => it.line));
  const from = lines.indexOf(items[index].line);
  if (from < 0) return "";
  let to = from + 1;
  while (to < lines.length && !starts.has(lines[to]) && !lines[to].startsWith(FOOTER)) to++;
  const block = lines.slice(from + 1, to);
  while (block.length && !block[block.length - 1].trim()) block.pop();
  if (block.length && block[block.length - 1].startsWith(CONTINUE)) block.pop();
  const item = items[index];
  if (item.kind === "report") {
    const task = block.find((l) => l.startsWith("Task: "));
    return task ? task.slice("Task: ".length) : "";
  }
  const marker = item.kind === "idle" ? "Its latest reply:" : `Reply from branch ${item.address}:`;
  const at = block.indexOf(marker);
  return (at >= 0 ? block.slice(at + 1) : block).join("\n").trim();
}

export interface Receipt {
  kind: "task" | "message";
  /** Who sent it (``main conversation``, an agent, another conversation's
   *  title); empty for a message written before senders were named. */
  from: string;
  address: string;
  body: string;
}

const RECEIPT = /^\[(task|message) from (\S+?)(?: \((.*?)\))?\][^\n]*\n+/;

export function readReceipt(content: string): Receipt | null {
  const m = RECEIPT.exec(content);
  if (!m) return null;
  return {
    kind: m[1] as Receipt["kind"],
    address: m[2],
    from: m[3] ?? "",
    body: content.slice(m[0].length),
  };
}

/** The sender name send_message gives the main conversation. */
export const MAIN_CONVERSATION = "main conversation";
