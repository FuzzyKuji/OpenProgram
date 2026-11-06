import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import test from "node:test";

const stub = (source) => `data:text/javascript,${encodeURIComponent(source)}`;
const requests = [];
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "@/lib/net/fetch-client") {
      return { url: stub(`export const jsonFetch = (url, init) => { globalThis.__alwaysOnRequests.push([url, init?.method ?? "GET"]); return Promise.resolve({}); };`), shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
});
globalThis.__alwaysOnRequests = requests;

const alwaysOn = await import("../../lib/agents/always-on.ts");

test("wake intervals follow the server's range", () => {
  assert.equal(alwaysOn.wakeMinutesValid(5), true);
  assert.equal(alwaysOn.wakeMinutesValid(10080), true);
  assert.equal(alwaysOn.wakeMinutesValid(4), false);
  assert.equal(alwaysOn.wakeMinutesValid(10081), false);
  assert.equal(alwaysOn.wakeMinutesValid(7.5), false);
  assert.equal(alwaysOn.wakeMinutesValid(Number.NaN), false);
});

test("the Agent's always-on endpoint is configuration only", async () => {
  await alwaysOn.fetchAlwaysOn("a b");
  assert.deepEqual(requests, [["/api/agents/a%20b/always-on", "GET"]]);
  assert.equal("wakeAlwaysOn" in alwaysOn, false);
});

test("channel choices keep picked targets first and toggle by conversation", () => {
  const bob = { channel: "telegram", account_id: "default", peer_id: "42", label: "Bob" };
  const ops = { channel: "slack", account_id: "work", peer_id: "C1_U1", label: "#ops" };
  const gone = { channel: "wechat", account_id: "default", peer_id: "wx1", label: "Old" };
  assert.deepEqual(alwaysOn.channelChoices([gone], [bob, { ...gone, label: "renamed" }, ops]), [gone, bob, ops]);
  const picked = alwaysOn.toggleChannelTarget([bob], ops, true);
  assert.deepEqual(picked, [bob, ops]);
  assert.deepEqual(alwaysOn.toggleChannelTarget(picked, { ...bob, label: "x" }, false), [ops]);
  assert.deepEqual(alwaysOn.toggleChannelTarget([bob], bob, true), [bob]);
  assert.equal(alwaysOn.ALWAYS_ON_DEFAULTS.channels.length, 0);
});

test("quiet hours and wake days follow the server's rules", () => {
  const everyDay = alwaysOn.ALWAYS_ON_DEFAULTS.wake_days;
  assert.deepEqual(everyDay, [0, 1, 2, 3, 4, 5, 6]);
  assert.equal(alwaysOn.ALWAYS_ON_DEFAULTS.quiet_hours, null);
  assert.equal(alwaysOn.scheduleValid({ quiet_hours: null, wake_days: everyDay }), true);
  assert.equal(alwaysOn.scheduleValid({ quiet_hours: { start: "22:00", end: "08:00" }, wake_days: [0] }), true);
  assert.equal(alwaysOn.scheduleValid({ quiet_hours: { start: "22:00", end: "22:00" }, wake_days: everyDay }), false);
  assert.equal(alwaysOn.scheduleValid({ quiet_hours: { start: "24:00", end: "08:00" }, wake_days: everyDay }), false);
  assert.equal(alwaysOn.scheduleValid({ quiet_hours: { start: "", end: "08:00" }, wake_days: everyDay }), false);
  assert.equal(alwaysOn.scheduleValid({ quiet_hours: null, wake_days: [] }), false);
});
