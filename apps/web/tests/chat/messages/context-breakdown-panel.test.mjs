// The /context panel paints its cached snapshot on the first frame, never
// fetches or shows a loading state itself, and offers Compact only for a
// session that has something new to compact.
import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, test } from "node:test";
import { installLoader } from "../../_support/load.mjs";
import { installDom, render } from "../../_support/dom.mjs";

installLoader();
// The real i18n module answers in English through the stored locale.
installDom({ pathname: "/chat" });
// linkedom computes no styles; Radix Popover's presence and placement read some.
globalThis.getComputedStyle = window.getComputedStyle = () => new Proxy({}, {
  get: (_target, key) => (key === "getPropertyValue" ? () => "" : ""),
});
globalThis.WebSocket ??= { OPEN: 1 };
// linkedom has no layout: an element has boxes unless it, or an ancestor, is
// display:none or it is out of the document, as getClientRects() in a browser.
const rendered = (node) => node?.nodeType !== 1
  || (node.style?.display !== "none" && rendered(node.parentNode));
window.Element.prototype.getClientRects = function getClientRects() {
  return this.isConnected && rendered(this) ? [this.getBoundingClientRect()] : [];
};
const { createElement: h } = await import("react");
const { renderToStaticMarkup } = await import("react-dom/server");
const { ContextBreakdownPanel } = await import("../../../components/chat/badges/context-breakdown-panel.tsx");
const { ContextBadge } = await import("../../../components/chat/badges/context-badge.tsx");
const cache = await import("../../../lib/chat/context-breakdown-cache.ts");
const { setSocket } = await import("../../../lib/runtime-bridge/state.ts");
const { SessionScopeProvider } = await import("../../../lib/session-store/session-scope.tsx");
const { useSessionStore } = await import("../../../lib/session-store/index.ts");

let fetches;
let view;
beforeEach(() => {
  fetches = [];
  globalThis.fetch = async (url) => {
    fetches.push(String(url));
    return { json: async () => ({ total_used: 1, window: 10 }) };
  };
  useSessionStore.setState({ messagesById: {}, messageOrder: {}, compactionUi: {}, tokens: {}, contextWindow: {}, heads: {} });
});
afterEach(async () => { await view?.unmount(); view = undefined; setSocket(null); });

const compactButton = () => [...document.querySelectorAll("button")]
  .find((button) => /Compact conversation|Compacting…/.test(button.textContent));
function seedEvents(sessionId, rows) {
  useSessionStore.setState({
    messagesById: Object.fromEntries(rows.map((row) => [row.id, row])),
    messageOrder: { [sessionId]: rows.map((row) => row.id) },
  });
}

describe("ContextBreakdownPanel", () => {
  test("the first paint shows the session snapshot without a fetch or a loading state", () => {
    cache.writeContextBreakdownCache("panel-a", "head-a", { total_used: 12_345, window: 200_000 });
    const html = renderToStaticMarkup(h(ContextBreakdownPanel, { sessionId: "panel-a", headId: "head-a" }));
    assert.match(html, /12\.3k \/ 200\.0k/);
    assert.doesNotMatch(html, /Loading|加载中/);
    assert.deepEqual(fetches, []);
  });

  test("a chat with no session paints the draft estimate and has no compact row", async () => {
    useSessionStore.setState({ agentSettings: { ...useSessionStore.getState().agentSettings, chat: { provider: "p", model: "m" } }, activeChatKey: null });
    globalThis.fetch = async () => ({ json: async () => ({ total_used: 3_000, window: 100_000 }) });
    cache.warmDraftContextBreakdown("p", "m", null);
    await new Promise((resolve) => setTimeout(resolve, 0));
    view = await render(h(ContextBreakdownPanel, { sessionId: null }));
    assert.match(view.container.textContent, /3\.0k \/ 100\.0k/);
    assert.equal(compactButton(), undefined);
  });

  test("a snapshot written while open replaces the shown value", async () => {
    cache.writeContextBreakdownCache("panel-b", null, { total_used: 1_000, window: 10_000 });
    view = await render(h(ContextBreakdownPanel, { sessionId: "panel-b", headId: null }));
    assert.match(view.container.textContent, /1\.0k \/ 10\.0k/);
    await view.act(() => cache.writeContextBreakdownCache("panel-b", null, { total_used: 2_000, window: 10_000 }));
    assert.match(view.container.textContent, /2\.0k \/ 10\.0k/);
    assert.deepEqual(fetches, []);
  });

  test("Compact sends the compact action for the session", async () => {
    const sent = [];
    setSocket({ readyState: 1, send: (frame) => sent.push(JSON.parse(frame)) });
    seedEvents("panel-c", [{ id: "u1", role: "user", content: "hi" }]);
    view = await render(h(ContextBreakdownPanel, { sessionId: "panel-c" }));
    assert.equal(compactButton().getAttribute("aria-disabled"), "false");
    await view.act(() => compactButton().click());
    assert.deepEqual(sent, [{ action: "compact", session_id: "panel-c" }]);
  });

  test("while compacting the row says so and sends nothing", async () => {
    const sent = [];
    setSocket({ readyState: 1, send: (frame) => sent.push(frame) });
    useSessionStore.setState({ compactionUi: { "panel-d": { running: true } } });
    view = await render(h(ContextBreakdownPanel, { sessionId: "panel-d" }));
    const button = compactButton();
    assert.equal(button.textContent, "Compacting…");
    assert.equal(button.getAttribute("aria-busy"), "true");
    await view.act(() => button.click());
    assert.deepEqual(sent, []);
  });

  test("right after a compaction event, and until a new message, Compact is disabled", async () => {
    seedEvents("panel-e", [
      { id: "u1", role: "user", content: "hi" },
      { id: "c1", role: "system", kind: "compaction", slot: "event", content: "" },
    ]);
    view = await render(h(ContextBreakdownPanel, { sessionId: "panel-e" }));
    assert.equal(compactButton().getAttribute("aria-disabled"), "true");
    await view.unmount();
    seedEvents("panel-e", [
      { id: "c1", role: "system", kind: "compaction", slot: "event", content: "" },
      { id: "u2", role: "user", content: "again" },
    ]);
    view = await render(h(ContextBreakdownPanel, { sessionId: "panel-e" }));
    assert.equal(compactButton().getAttribute("aria-disabled"), "false");
  });
});

describe("ContextBadge", () => {
  test("focusing a session warms its snapshot in the background", async () => {
    useSessionStore.setState({ currentSessionId: "badge-a", heads: { "badge-a": "head-1" } });
    view = await render(h(SessionScopeProvider, { sid: "badge-a" }, h(ContextBadge, { sessionId: "badge-a" })));
    assert.deepEqual(fetches, ["/api/sessions/badge-a/context?head_id=head-1"]);
  });

  test("switching the branch head under an open panel shows that head's snapshot at once", async () => {
    cache.writeContextBreakdownCache("badge-b", "h1", { total_used: 1_000, window: 10_000, tools: [] });
    cache.writeContextBreakdownCache("badge-b", "h2", { total_used: 5_000, window: 10_000, tools: [] });
    useSessionStore.setState({ currentSessionId: "badge-b", heads: { "badge-b": "h1" } });
    view = await render(h(SessionScopeProvider, { sid: "badge-b" }, h(ContextBadge, { sessionId: "badge-b" })));
    await view.act(() => view.container.querySelector(".context-ring-badge").click());
    assert.match(document.querySelector(".context-breakdown-panel").textContent, /1\.0k \/ 10\.0k/);
    await view.act(() => useSessionStore.setState({ heads: { "badge-b": "h2" } }));
    assert.match(document.querySelector(".context-breakdown-panel").textContent, /5\.0k \/ 10\.0k/);
  });
});
