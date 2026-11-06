export type SandboxEscalation = { from: string; to: string; path?: string; rule?: string; justification?: string };

export function readSandboxEscalation(args?: Record<string, unknown>): SandboxEscalation | undefined {
  const raw = args?._sandbox_escalation;
  if (!raw || typeof raw !== "object") return undefined;
  const o = raw as Record<string, unknown>;
  return {
    from: typeof o.from === "string" ? o.from : "",
    to: typeof o.to === "string" ? o.to : "",
    path: typeof o.path === "string" ? o.path : undefined,
    rule: typeof o.rule === "string" ? o.rule : undefined,
    justification: typeof o.justification === "string" ? o.justification : undefined,
  };
}

/** Text shared by the approval card and its editable discussion draft. */
export function approvalDisplayText(
  prompt: string, detail: string | undefined, escalation: SandboxEscalation | undefined,
  text: (en: string, zh: string) => string,
): { prompt: string; summary: string } {
  if (!escalation) return { prompt, summary: detail ?? "" };
  return {
    prompt: text("Run this command outside the sandbox?", "允许这条命令在沙箱外执行？"),
    summary: [
      escalation.justification ?? "",
      escalation.path ? `${text("Blocked path", "被拦路径")}: ${escalation.path}` : "",
      escalation.rule ? `${text("Matched rule", "命中规则")}: ${escalation.rule}` : "",
    ].filter(Boolean).join("\n"),
  };
}
