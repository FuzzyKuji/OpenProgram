import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "esbuild";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { scratchDir } from "../../scratch-dir.mjs";

// The task list drawn under a turn's reply (components/chat/messages/cards/
// todo-plan-card.tsx), rendered with the store it reads stubbed.
const web = dirname(fileURLToPath(new URL("../../../package.json", import.meta.url)));
const dir = scratchDir(web, "todo-plan-card");
const file = join(dir, "card.mjs");
await build({
  absWorkingDir: web, entryPoints: ["components/chat/messages/cards/todo-plan-card.tsx"],
  external: ["react"], bundle: true, platform: "node", format: "esm", packages: "external", jsx: "automatic", outfile: file,
  plugins: [{ name: "card-services", setup(b) {
    b.onResolve({ filter: /^@\/lib\/session-store$|^@\/lib\/i18n$|^@\/components\/solar-icons$|\.module\.css$/ }, (a) => ({ path: a.path, namespace: "stub" }));
    b.onResolve({ filter: /^@\/lib\/chat\/transcript\/todo-plan$/ }, () => ({ path: join(web, "lib/chat/transcript/todo-plan.ts") }));
    b.onLoad({ filter: /.*/, namespace: "stub" }, (a) => ({ resolveDir: web, contents:
      a.path.endsWith(".module.css") ? "export default new Proxy({}, { get: (_, key) => String(key) });"
        : a.path.includes("session-store") ? "export const useSessionStore = (selector) => selector(globalThis.cardState);"
          : a.path.includes("i18n") ? "export const useTranslation = () => ({ text: (en) => en });"
            : 'import { createElement } from "react"; export const SolarIcon = ({ name, motionPreset, size, ...rest }) => createElement("i", { "data-glyph": name, ...rest });',
    }));
  } }],
});
const { TodoPlans } = await import(pathToFileURL(file));
const { normalizePlans } = await import("../../../lib/chat/transcript/todo-plan.ts");

const plan = (statuses) => normalizePlans([{
  anchor_id: "t1_reply", plan_id: "1",
  todos: statuses.map((status, i) => ({ id: String(i + 1), subject: `step ${i + 1}`, status })),
}]);

function render(status, statuses, { terminal = false } = {}) {
  globalThis.cardState = {
    messagesById: { t1_reply: { id: "t1_reply", role: "assistant", content: "", status } },
    executionUpdateOrders: terminal ? { e1: { sessionId: "s1", messageIds: ["t1_reply"], terminal: true } } : {},
  };
  return renderToStaticMarkup(createElement(TodoPlans, { sessionId: "s1", rowId: "t1_reply", plans: plan(statuses) }));
}

test("while its turn runs the list is open, with no header line, and the current step turns", () => {
  const html = render("running", ["completed", "in_progress", "pending"]);
  assert.match(html, /data-live=""/);
  assert.match(html, /data-open="1"/);
  assert.doesNotMatch(html, /<button/, "no folded line while live");
  assert.doesNotMatch(html, /Tasks \d/, "no small header");
  assert.match(html, /data-status="in_progress" data-live=""/, "the in-progress step spins");
  assert.match(html, /step 1.*step 2.*step 3/s);
});

test("a stopped turn folds its list to one line that says so", () => {
  for (const status of ["cancelled", "interrupted"]) {
    const html = render(status, ["completed", "completed", "in_progress", "pending", "pending"]);
    assert.match(html, /<button[^>]*aria-expanded="false"/);
    assert.match(html, /Tasks 2\/5 · Stopped/);
    assert.match(html, /data-open="0"/);
    assert.doesNotMatch(html, /data-live/, "nothing spins once the turn stopped");
  }
});

test("a finished plan reads Done, an error reads Failed, an ended turn with work left only counts", () => {
  assert.match(render("done", ["completed", "completed"]), /Tasks 2\/2 · Done/);
  assert.match(render("error", ["completed", "pending"]), /Tasks 1\/2 · Failed/);
  const ended = render("done", ["completed", "pending"]);
  assert.match(ended, /Tasks 1\/2<\/span>/);
  assert.doesNotMatch(ended, /data-live/);
});

test("a reply still marked running whose execution already ended does not spin", () => {
  const html = render("running", ["in_progress"], { terminal: true });
  assert.doesNotMatch(html, /data-live/);
  assert.match(html, /<button/);
});

test("the folded list keeps every item for opening, with done items marked", () => {
  const html = render("done", ["completed", "in_progress", "pending"]);
  assert.match(html, /data-glyph="checklist"/);
  assert.match(html, /data-status="completed"[^>]*data-glyph="check-circle"|data-glyph="check-circle"[^>]*data-status="completed"/);
  assert.match(html, /data-status="pending"/);
  assert.equal([...html.matchAll(/<li /g)].length, 3);
});

test("the list has no native title and no hover tip", () => {
  const html = render("done", ["completed"]);
  assert.doesNotMatch(html, /\stitle=/);
  assert.doesNotMatch(readFileSync(join(web, "components/chat/messages/cards/todo-plan-card.tsx"), "utf8"), /Tooltip|title=/);
});

test("the transcript places lists per reply, never as one trailing card", () => {
  const list = readFileSync(join(web, "components/chat/messages/list/message-list.tsx"), "utf8");
  assert.doesNotMatch(list, /<TodoPlanCard/);
  assert.match(list, /addTodoPlans\(\[id\]\)/);
  assert.match(list, /addTodoPlans\(run\)/, "a compacted turn's list follows its fold");
  const sub = readFileSync(join(web, "components/chat/messages/cards/sub-agent-transcript.tsx"), "utf8");
  assert.match(sub, /<TodoPlans sessionId=\{sessionId\} rowId=\{id\} \/>/, "a sub-agent's own plan sits in its own conversation");
});

test("only a live step animates, and reduced motion stops it", () => {
  const css = readFileSync(join(web, "components/chat/messages/cards/todo-plan-card.module.css"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "");
  const animated = [...css.matchAll(/([^{}]+)\{[^{}]*animation:\s*todo-orbit/g)].map((m) => m[1].trim());
  assert.deepEqual(animated, [".icon[data-live]::after"]);
  assert.match(css, /prefers-reduced-motion[\s\S]*\.icon\[data-live\]::after \{ animation: none; \}/);
  assert.doesNotMatch(css, /box-shadow/);
});
