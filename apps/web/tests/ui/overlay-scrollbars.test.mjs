import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";
import { createRequire } from "node:module";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseHTML } from "linkedom";

const require = createRequire(import.meta.url);
const bundle = await build({
  entryPoints: [fileURLToPath(new URL("../../lib/runtime-bridge/dom/scrollbar.ts", import.meta.url))],
  bundle: true, write: false, format: "cjs", platform: "node",
});
const temporary = mkdtempSync(join(tmpdir(), "op-scrollbar-"));
let api;
try {
  const output = join(temporary, "module.cjs");
  writeFileSync(output, bundle.outputFiles[0].text);
  api = require(output);
} finally { rmSync(temporary, { recursive: true, force: true }); }

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test("a box gets its thumb on its first scroll, never on hover", async () => {
  const { window, document } = parseHTML("<html><body><div id=box></div></body></html>");
  Object.assign(globalThis, { window, document, HTMLElement: window.HTMLElement, Event: window.Event, MutationObserver: window.MutationObserver,
    requestAnimationFrame: (cb) => setTimeout(cb, 0), cancelAnimationFrame: clearTimeout,
    getComputedStyle: () => ({ borderTopRightRadius: "0", borderBottomRightRadius: "0" }) });
  window.innerWidth = 800;
  const box = document.getElementById("box");
  Object.assign(box, { scrollHeight: 1000, clientHeight: 200, scrollWidth: 100, clientWidth: 100, scrollTop: 0 });
  box.getBoundingClientRect = () => ({ top: 0, left: 0, right: 100, bottom: 200, width: 100, height: 200 });

  api.initOverlayScrollbars();
  box.dispatchEvent(new window.Event("mouseenter"));
  await wait(10);
  assert.equal(document.querySelectorAll(".overlay-thumb").length, 0, "hovering installs nothing");

  box.scrollTop = 300;
  // linkedom has no capture phase; a bubbling scroll reaches the
  // document's listener the way a real scroll's capture phase does.
  box.dispatchEvent(new window.Event("scroll", { bubbles: true }));
  await wait(10);
  const thumbs = document.querySelectorAll(".overlay-thumb");
  assert.equal(thumbs.length, 1, "one vertical thumb; the box does not overflow sideways");
  assert.ok(thumbs[0].classList.contains("visible"), "scrolling shows it");
  assert.ok(box.classList.contains("scroll-overlay"));

  box.remove();
  document.body.appendChild(document.createElement("i"));
  await wait(10);
  assert.equal(document.querySelectorAll(".overlay-thumb").length, 0, "a removed box takes its thumb with it");
});
