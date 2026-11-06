// A provider's account list: the add-key form is a disclosure once an account
// exists (open straight away when there is none), a closed form forgets what
// was typed, each account's status chip re-validates with a live ping, and
// every icon action has its own name.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { installLoader } from "../_support/load.mjs";
import { installDom, render } from "../_support/dom.mjs";

installLoader({
  stubs: {
    "framer-motion": [
      "import { createElement as h } from 'react';",
      "export const Reorder = {",
      "  Group: ({ children }) => h('div', { 'data-accounts': '' }, children),",
      "  Item: ({ children, value }) => h('div', { 'data-account': value.id }, children),",
      "};",
      "export const useDragControls = () => ({ start() {} });",
    ].join("\n"),
  },
  replace: {
    "/components/ui/switch.tsx": "import { createElement as h } from 'react'; export const Switch = ({ checked, onCheckedChange, disabled, size, className, ...rest }) => h('button', { type: 'button', role: 'switch', 'aria-checked': String(Boolean(checked)), disabled, onClick: () => onCheckedChange?.(!checked), ...rest });",
    "/components/ui/select.tsx": "export const SimpleSelect = () => null;",
    "/components/ui/tooltip.tsx": "export const HoverTip = ({ children }) => children; export const TipBody = () => null;",
    "/components/settings/providers/auth/provider-login.tsx": "export const ProviderLogin = () => null;",
  },
});
installDom();

const { createElement: h } = await import("react");
const { AccountManager } = await import("../../components/settings/providers/auth/account-manager.tsx");

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const ok = (body) => ({ ok: true, status: 200, json: async () => body });
const PROVIDER = { id: "openai", label: "OpenAI", enabled: true };
const ACCOUNT = { id: "acct-1", label: "Work", name: "work", kind: "api_key", is_active: true, has_value: true, masked_key: "sk-…abc4" };

function accountsFetch(accounts) {
  const posts = [];
  globalThis.fetch = async (url, init = {}) => {
    if (!init.method) return ok({ accounts, active: "", rotation: false, strategy: "fill_first", strategies: [], add_mode: "api_key" });
    posts.push([url, init.body ? JSON.parse(init.body) : null]);
    if (url.includes("/validate")) return ok({ status: "valid" });
    return ok({ ok: true });
  };
  return posts;
}

async function renderAccounts() {
  const view = await render(h(AccountManager, { provider: PROVIDER }));
  await view.act(settle);
  return view;
}
const named = (container, label) => container.querySelector(`[aria-label="${label}"]`);
const byText = (container, text) => [...container.querySelectorAll("button")].find((b) => b.textContent.trim() === text);
async function type(view, input, value) {
  input.type ||= "text"; // React tracks value changes only on typed inputs; linkedom has no default.
  Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value").set.call(input, value);
  await view.act(() => input.dispatchEvent(new Event("input", { bubbles: true })));
}

afterEach(() => { document.body.innerHTML = ""; });

test("with no account the add-key form is open, with no disclosure button", async () => {
  const posts = accountsFetch([]);
  const view = await renderAccounts();
  assert.ok(view.container.querySelector("#add-api-key-form"));
  assert.equal(view.container.querySelector("[aria-controls]"), null);
  await type(view, view.container.querySelector('input[type="password"]'), "  sk-new  ");
  await view.act(async () => { byText(view.container, "Add key").click(); await settle(); });
  assert.deepEqual(posts.at(-1), ["/api/providers/openai/accounts/keys", { name: "", api_key: "sk-new", validate: true }]);
  await view.unmount();
});

test("Add API key is a disclosure for the form, and closing it clears what was typed", async () => {
  const posts = accountsFetch([ACCOUNT]);
  const view = await renderAccounts();
  const { container } = view;
  const toggle = container.querySelector('[aria-controls="add-api-key-form"]');
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(container.querySelector("#add-api-key-form"), null);

  await view.act(() => toggle.click());
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  const form = container.querySelector("#add-api-key-form");
  await type(view, form.querySelector('input[placeholder="Account name (optional)"]'), "Personal");
  await type(view, form.querySelector('input[type="password"]'), "sk-typed");

  await view.act(() => toggle.click());
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  await view.act(() => toggle.click());
  const reopened = container.querySelector("#add-api-key-form");
  assert.equal(reopened.querySelector('input[placeholder="Account name (optional)"]').value, "");
  assert.equal(reopened.querySelector('input[type="password"]').value, "");

  await type(view, reopened.querySelector('input[placeholder="Account name (optional)"]'), "  Personal  ");
  await type(view, reopened.querySelector('input[type="password"]'), "sk-second");
  await view.act(async () => { byText(container, "Add key").click(); await settle(); });
  assert.deepEqual(posts.at(-1), ["/api/providers/openai/accounts/keys", { name: "Personal", api_key: "sk-second", validate: true }]);
  await view.unmount();
});

test("the status chip names the status, and clicking it validates with a live ping", async () => {
  const posts = accountsFetch([ACCOUNT]);
  const view = await renderAccounts();
  assert.deepEqual(posts[0], ["/api/providers/openai/accounts/acct-1/validate", null], "mount validates without spending tokens");
  const status = named(view.container, "valid. Validate account");
  assert.ok(status, "the chip's name carries its status");
  await view.act(async () => { status.click(); await settle(); });
  assert.equal(posts.at(-1)[0], "/api/providers/openai/accounts/acct-1/validate?ping=true");
  await view.unmount();
});

test("each account action is named, and Remove and the use switch post for that account", async () => {
  const posts = accountsFetch([{ ...ACCOUNT, is_active: false }]);
  const view = await renderAccounts();
  const { container } = view;
  for (const label of ["Rename account", "Replace API key", "Remove account"]) assert.ok(named(container, label), label);

  await view.act(async () => { named(container, "Use this account for requests").click(); await settle(); });
  assert.deepEqual(posts.at(-1), ["/api/providers/openai/accounts/use", { id: "acct-1" }]);

  await view.act(() => named(container, "Rename account").click());
  assert.ok(named(container, "Account name"), "rename opens a named input");

  await view.act(async () => { named(container, "Remove account").click(); await settle(); });
  assert.deepEqual(posts.at(-1), ["/api/providers/openai/accounts/remove", { id: "acct-1" }]);
  await view.unmount();
});
