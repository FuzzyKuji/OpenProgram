import assert from "node:assert/strict";
import { afterEach, describe, test } from "node:test";
import { installLoader, STUBS } from "../_support/load.mjs";
import { installDom, render } from "../_support/dom.mjs";

const SWITCH = "import { createElement as h } from 'react'; export const Switch = ({ checked, onCheckedChange, disabled, size, className, title, ...rest }) => h('button', { type: 'button', role: 'switch', 'aria-checked': String(Boolean(checked)), disabled, onClick: () => onCheckedChange?.(!checked), ...rest });";

installLoader({
  stubs: { "@/lib/i18n": STUBS.i18n },
  replace: {
    "/components/settings/providers/icons/provider-icon.tsx": "export const ProviderIcon = () => { globalThis.iconRenders++; return null; };",
    // Radix Switch needs HTMLFormElement, which linkedom lacks; this keeps its role and ARIA contract.
    "/components/ui/switch.tsx": SWITCH,
    "/components/ui/checkbox.tsx": "export const Checkbox = () => null;",
    "/lib/prefs/settings-cache.ts": [
      "export const readCachedSettings = () => undefined;",
      "export const cachedFetch = async () => ({ providers: globalThis.providerList });",
      "export const invalidate = () => {};",
    ].join("\n"),
    "/lib/nav/shallow-nav.ts": "export const pushPath = (path) => globalThis.providerPaths.push(path);",
    "/@tanstack/react-query/": "export const useQueryClient = () => ({ invalidateQueries() {} });",
    "/components/settings/providers/routing-overview.tsx": "export const RoutingOverview = () => null;",
    "/components/settings/providers/auth/account-manager.tsx": "export const AccountManager = () => null;",
    "/components/settings/providers/auth/base-url.tsx": "export const BaseUrl = () => null;",
    "/components/settings/providers/auth/connectivity.tsx": "export const Connectivity = () => null;",
    "/components/settings/providers/auth/api-key.tsx": "export const ApiKey = () => null;",
    "/components/settings/providers/auth/setup-hint.tsx": "export const SetupHint = () => null; export const CliInfo = () => null;",
    "/components/settings/providers/model-list.tsx": "export const ModelList = () => null;",
    "/components/ui/confirm-dialog.tsx": "export const confirmAction = async () => true;",
    "/lib/desktop/desktop-bridge.ts": "export const desktopBridge = () => globalThis.browserBridge ?? null;",
    "/components/center-tabs/browser/browser-home-page.tsx": "export const BrowserImportDialog = () => null;",
  },
});
installDom();
globalThis.iconRenders = 0;

const { createElement: h, act } = await import("react");
const { createRoot } = await import("react-dom/client");
const { ProviderItem } = await import("../../components/settings/providers/provider-item.tsx");
const { ProvidersSection } = await import("../../components/settings/providers/index.tsx");
const { Detail } = await import("../../components/settings/providers/detail.tsx");
const { BrowserSettings } = await import("../../components/settings/sections/browser-settings.tsx");

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

afterEach(() => { document.body.innerHTML = ""; });

test("changing selected provider redraws only the two changed rows", async () => {
  const providers = Array.from({ length: 239 }, (_, i) => ({ id: String(i), label: String(i), enabled: true }));
  let selected;
  const onSelect = (id) => { selected = id; };
  const rows = (active) => providers.map((p) => h(ProviderItem, { key: p.id, p, active: p.id === active, onSelect }));
  const host = document.body.appendChild(document.createElement("div"));
  const root = createRoot(host);
  globalThis.iconRenders = 0;
  await act(async () => root.render(rows("0")));
  assert.equal(globalThis.iconRenders, 239);
  globalThis.iconRenders = 0;
  await act(async () => root.render(rows("1")));
  assert.equal(globalThis.iconRenders, 2);
  host.querySelectorAll("button")[1].click();
  assert.equal(selected, "1");
  await act(async () => root.unmount());
});

describe("provider list", () => {
  const PROVIDERS = [
    { id: "openai", label: "OpenAI", enabled: true },
    { id: "anthropic", label: "Anthropic", enabled: false },
    { id: "groq", label: "Groq", enabled: false },
  ];
  const groups = (container) => {
    const out = [];
    for (const el of container.querySelectorAll(".providersGroupLabel, button.providerItem")) {
      if (el.classList.contains("providersGroupLabel")) out.push([el.textContent, []]);
      else if (out.length) out.at(-1)[1].push(el.textContent.trim());
    }
    return out;
  };

  test("lists enabled and not-enabled providers in separate groups, and search hides an emptied group", async () => {
    globalThis.providerList = PROVIDERS;
    globalThis.providerPaths = [];
    const view = await render(h(ProvidersSection));
    await view.act(settle);
    assert.deepEqual(groups(view.container), [["Enabled", ["OpenAI"]], ["Not enabled", ["Anthropic", "Groq"]]]);

    const search = view.container.querySelector('input[placeholder="Search providers..."]');
    search.type = "text";
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(search), "value").set.call(search, "gro");
    await view.act(() => search.dispatchEvent(new Event("input", { bubbles: true })));
    assert.deepEqual(groups(view.container), [["Not enabled", ["Groq"]]]);
    await view.unmount();
  });

  test("selecting a provider puts it in the URL", async () => {
    globalThis.providerList = PROVIDERS;
    globalThis.providerPaths = [];
    const view = await render(h(ProvidersSection));
    await view.act(settle);
    const row = [...view.container.querySelectorAll("button")].find((b) => b.textContent.trim() === "Anthropic");
    await view.act(() => row.click());
    assert.deepEqual(globalThis.providerPaths, ["/settings/providers/anthropic"]);
    await view.unmount();
  });

  test("Add custom provider opens an inline form that creates the provider and selects it", async () => {
    globalThis.providerList = PROVIDERS;
    globalThis.providerPaths = [];
    const posts = [];
    globalThis.fetch = async (url, init) => { posts.push([url, JSON.parse(init.body)]); return { json: async () => ({ ok: true, id: "frontier" }) }; };
    const view = await render(h(ProvidersSection));
    await view.act(settle);
    const byText = (text) => [...view.container.querySelectorAll("button")].find((b) => b.textContent.trim() === text);
    await view.act(() => byText("Add custom provider").click());
    const [name, baseUrl] = view.container.querySelectorAll("input:not([placeholder='Search providers...'])");
    for (const [input, value] of [[name, " Frontier AI "], [baseUrl, "https://api.example.test"]]) {
      input.type = "text";
      Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value").set.call(input, value);
      await view.act(() => input.dispatchEvent(new Event("input", { bubbles: true })));
    }
    assert.match(view.container.textContent, /id: frontier-ai/);
    await view.act(async () => { byText("Add").click(); await settle(); await settle(); });
    assert.deepEqual(posts, [["/api/providers/custom", { label: "Frontier AI", base_url: "https://api.example.test", local: false }]]);
    assert.deepEqual(globalThis.providerPaths, ["/settings/providers/frontier"]);
    assert.ok(byText("Add custom provider"), "the form closes after creating");
    await view.unmount();
  });
});

describe("provider detail", () => {
  test("the header switch is named and turns the provider off", async () => {
    globalThis.fetch = async () => ({ json: async () => ({ models: [] }) });
    const toggles = [];
    const view = await render(h(Detail, { provider: { id: "openai", label: "OpenAI", enabled: true, kind: "api", api_key_env: "OPENAI_API_KEY" }, onToggle: (on) => toggles.push(on), onChanged() {} }));
    await view.act(settle);
    const toggle = view.container.querySelector('[aria-label="Enable this provider"]');
    assert.equal(toggle.getAttribute("aria-checked"), "true");
    assert.match(view.container.textContent, /Enabled/);
    toggle.click();
    assert.deepEqual(toggles, [false]);
    await view.unmount();
  });
});

describe("browser settings", () => {
  test("without the desktop bridge the clear-data switches are off limits and say why", async () => {
    globalThis.browserBridge = null;
    const view = await render(h(BrowserSettings));
    for (const label of ["Browsing history", "Cookies"]) {
      const control = view.container.querySelector(`[aria-label="${label}"]`);
      assert.equal(control.getAttribute("role"), "switch");
      assert.equal(control.disabled, true);
    }
    assert.match(view.container.textContent, /available in the desktop app/);
    assert.match(view.container.textContent, /Bookmarks are not removed\./);
    await view.unmount();
  });

  test("clearing sends only the selected kinds of data and reports the result", async () => {
    const cleared = [];
    globalThis.browserBridge = { browserData: { clear: async (what) => { cleared.push(what); return { ok: true }; } } };
    const view = await render(h(BrowserSettings));
    await view.act(() => view.container.querySelector('[aria-label="Cookies"]').click());
    const clear = [...view.container.querySelectorAll("button")].find((b) => b.textContent === "Clear data");
    await view.act(async () => { clear.click(); await settle(); });
    assert.deepEqual(cleared, [{ history: true, cookies: false }]);
    assert.equal(view.container.querySelector('[role="status"]').textContent, "Selected browsing data was cleared.");
    globalThis.browserBridge = null;
    await view.unmount();
  });
});
