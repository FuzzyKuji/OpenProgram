import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const { HOVER_HOST, HOVER_POP, HOVER_POP_SCALE, followHostHover, hoverHostOf } = await import("../../components/ui/hover-pop.ts");

const source = (path) => readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");

function element(matches, parent = null) {
  const listeners = new Map();
  const node = {
    parentElement: parent,
    closest(selector) {
      assert.equal(selector, HOVER_HOST);
      for (let at = node; at; at = at.parentElement) if (at.isHost) return at;
      return null;
    },
    isHost: matches,
    addEventListener: (type, fn) => listeners.set(type, fn),
    removeEventListener: (type, fn) => { if (listeners.get(type) === fn) listeners.delete(type); },
    listeners,
  };
  return node;
}

test("an icon follows the hover of its nearest control, or its own outside one", () => {
  const page = element(false);
  const button = element(true, page);
  const label = element(false, button);
  const icon = element(false, label);
  assert.equal(hoverHostOf(icon), button);
  const loose = element(false, page);
  assert.equal(hoverHostOf(loose), loose);

  const seen = [];
  const stop = followHostHover(icon, () => seen.push("enter"), () => seen.push("leave"));
  button.listeners.get("mouseenter")();
  button.listeners.get("mouseleave")();
  assert.deepEqual(seen, ["enter", "leave"]);
  stop();
  assert.equal(button.listeners.size, 0);
});

test("menu rows of every kind are controls", () => {
  for (const role of ["menuitem", "menuitemradio", "menuitemcheckbox", "option"]) assert.ok(HOVER_HOST.includes(`[role="${role}"]`), role);
  assert.deepEqual(HOVER_POP, { normal: { scale: 1 }, animate: { scale: HOVER_POP_SCALE } });
});

test("Solar glyphs and Agent characters pop with the one shared motion", () => {
  for (const path of ["components/solar-icons/solar-icon.tsx", "components/avatar/bot/bot-avatar.ts"]) {
    const text = source(path);
    assert.match(text, /from "(@\/components|\.\.\/\.\.)\/ui\/hover-pop"/, path);
    assert.match(text, /followHostHover\(/, path);
    assert.doesNotMatch(text, /scale: 1\.12|stiffness: 420/, path);
  }
});
