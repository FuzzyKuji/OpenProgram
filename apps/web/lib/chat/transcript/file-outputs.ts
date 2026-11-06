import { marked } from "marked";
import { fileCapabilities } from "../../documents/file-formats.ts";
import { isArchivePath } from "../../files/archive.ts";

export interface FileOutput { path: string; name: string; }
/** Only explicit local links/attachments, never paths inferred from prose or code. */
export function collectFileOutputs(content: string, attachments: { path: string; filename: string }[] = []): FileOutput[] {
  const files = new Map<string, FileOutput>();
  const add = (path: string, name?: string) => {
    if (!path || path.startsWith("//") || (!path.startsWith("/") && !/^[A-Za-z]:[\\/]/.test(path))) return;
    if (path.includes("\0") || files.size >= 20) return;
    files.set(path, { path, name: name || path.replace(/\\/g, "/").split("/").pop() || path });
  };
  for (const item of attachments) add(item.path, item.filename);
  marked.walkTokens(marked.lexer(content), token => {
    if (token.type !== "link" && token.type !== "image") return;
    let path = token.href;
    if (path.startsWith("file:///")) path = path.slice(7);
    else if (/^[a-z][a-z0-9+.-]*:/i.test(path) && !/^[A-Za-z]:[\\/]/.test(path)) return;
    try { path = decodeURIComponent(path); } catch { return; }
    path = path.replace(/:\d+(?::\d+)?$/, "");
    if (fileCapabilities(path).preview !== "download" || isArchivePath(path)) add(path);
  });
  return [...files.values()];
}

export function previewTarget(path: string, project?: { id: string; path: string } | null) {
  const root = project?.path.replace(/\\/g, "/").replace(/\/$/, "");
  const normalized = path.replace(/\\/g, "/");
  if (root && normalized.startsWith(root + "/")) {
    const relative = normalized.slice(root.length + 1);
    if (!relative.split("/").some(part => !part || part === "." || part === ".."))
      return { projectId: project!.id, path: relative, readOnly: false };
  }
  return { projectId: "", path, readOnly: true };
}

export type InlineMediaKind = "image" | "video" | "audio";
/** Media the agent sent with ``send_file`` plays in the reply itself; a file
 *  only linked from the prose keeps its row, so a link never turns into a
 *  large embed the agent did not ask for. */
export function inlineMediaKind(file: FileOutput, attachments: { path: string }[] = []): InlineMediaKind | null {
  if (!attachments.some(item => item.path === file.path)) return null;
  const kind = fileCapabilities(file.path).preview;
  return kind === "image" || kind === "video" || kind === "audio" ? kind : null;
}
