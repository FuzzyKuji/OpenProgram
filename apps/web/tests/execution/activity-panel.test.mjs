import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import test from "node:test";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { parseHTML } from "linkedom";

const webRoot = new URL("../../", import.meta.url);
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "@/components/agents/agent-avatar") return { url: "data:text/javascript,export const AgentAvatarById = () => null; export const useConversationAgentShape = () => 'cloud'", shortCircuit: true };
    if (specifier === "@/lib/execution/use-execution-debugger") return { url: "data:text/javascript,export const useExecutionDebugger = () => globalThis.activityController", shortCircuit: true };
    if (specifier === "@/lib/execution/use-managed-processes") return { url: "data:text/javascript,export const useManagedProcesses = () => globalThis.activityProcesses", shortCircuit: true };
    if (specifier === "../debugger/debugger-panel") return { url: "data:text/javascript,export const DebuggerPanel = () => 'DEBUGGER'", shortCircuit: true };
    if (specifier === "@/lib/net/execution/activity-runs-client") return { url: "data:text/javascript,export const getActivityRuns = (...a) => globalThis.activityRuns(...a); export const getActivityRunEvents = (...a) => globalThis.activityEvents(...a)", shortCircuit: true };
    if (specifier === "./agent-page") return { url: new URL("./fixtures/list-agent-page.tsx", import.meta.url).href, shortCircuit: true };
    if (specifier === "./program-page") return { url: "data:text/javascript,export const ProgramPage = () => 'PROGRAM PAGE'", shortCircuit: true };
    if (specifier === "./command-page") return { url: "data:text/javascript,export const CommandPage = () => 'COMMAND PAGE'", shortCircuit: true };
    if (specifier === "./scheduled-task-page") return { url: "data:text/javascript,export const ScheduledTaskPage = () => 'TASK PAGE'", shortCircuit: true };
    if (specifier === "./open-work-page") return { url: "data:text/javascript,export const OpenWorkPage = () => 'WORK PAGE'", shortCircuit: true };
    if (specifier === "./always-on-row") return { url: "data:text/javascript,export const AlwaysOnRow = () => null; export const ReportInside = () => null; export const reportForRun = () => false; export const reportNameForRun = () => null", shortCircuit: true };
    if (specifier === "@/lib/agents/pending-inbox") return { url: "data:text/javascript,export const usePendingInbox = () => ({ items: [], loaded: true }); export const pendingInOrder = (items) => items; export const openPendingItem = () => {}", shortCircuit: true };
    if (specifier === "@/components/chat/messages/cards/sub-agent-transcript") return { url: "data:text/javascript,export const SubAgentTranscript = () => null", shortCircuit: true };
    if (specifier === "@/lib/chat/transcript/sub-agent-transcripts") return { url: "data:text/javascript,export const loadSubAgentTranscript = async () => globalThis.agentTip ?? null", shortCircuit: true };
    if (specifier === "@/lib/runtime-bridge/session/session-load") return { url: "data:text/javascript,export const sendRuntimeCommand = (p) => { (globalThis.sentCommands ||= []).push(p); }", shortCircuit: true };
    if (specifier === "@/lib/runtime-bridge/state") return { url: "data:text/javascript,export const getSocket = () => globalThis.approvalSocket; export const runtimeState = globalThis.runtimeStateStub ||= { _branchesByConv: {}, _branchLaneColorMap: {} }", shortCircuit: true };
    if (specifier.endsWith(".module.css")) {
      return { url: "data:text/javascript,export default {}", shortCircuit: true };
    }
    const base = specifier.startsWith("@/")
      ? new URL(specifier.slice(2), webRoot).href
      : specifier.startsWith(".") && !/\.[a-z]+$/i.test(specifier)
        ? new URL(specifier, context.parentURL).href : null;
    if (base) {
      for (const suffix of [".ts", ".tsx", "/index.ts", "/index.tsx"]) {
        if (existsSync(fileURLToPath(base + suffix))) {
          return { url: base + suffix, shortCircuit: true };
        }
      }
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.endsWith(".tsx")) {
      return {
        format: "module", shortCircuit: true,
        source: ts.transpileModule(readFileSync(fileURLToPath(url), "utf8"), {
          compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
        }).outputText,
      };
    }
    return nextLoad(url, context);
  },
});
const { window } = parseHTML("<!doctype html><html><body></body></html>");
globalThis.window = window;
globalThis.document = window.document;
globalThis.Event = window.Event;
globalThis.CustomEvent = window.CustomEvent;
globalThis.HTMLElement = window.HTMLElement;
globalThis.MutationObserver = window.MutationObserver;
globalThis.CSS = { escape: value => value };
// linkedom has no focus model and no scrolling; the keyboard test needs both.
window.HTMLElement.prototype.focus = function () { document.activeElement = this; this.dispatchEvent(new Event("focusin", { bubbles: true })); };
window.HTMLElement.prototype.scrollIntoView = function () {};
globalThis.fetch = async () => ({ ok: false, status: 404, async json() { return {}; }, async text() { return "{}"; } });
// Text assertions select a browser preference, independent of the host OS.
globalThis.localStorage = { getItem(key) { return key === "agentic_locale" ? "en" : null; }, setItem() {}, removeItem() {} };
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.requestAnimationFrame = (callback) => setTimeout(() => callback(0), 0);
globalThis.cancelAnimationFrame = clearTimeout;
window.location = { pathname: "/chat", hash: "", search: "" };
window.history = { replaceState() {}, pushState() {} };
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
const { act, createElement } = await import("react");
const { createRoot } = await import("react-dom/client");
const { RunningPanel } = await import("../../components/right-sidebar/running/running-panel.tsx");
const { useSessionStore } = await import("../../lib/session-store/index.ts");
useSessionStore.setState({ conversations: { session: { id: "session", title: "NeurIPS trip" } } });
const DAY = 86400;
const now = Math.floor(Date.now() / 1000);
const run = (id, status, started_at, extra = {}) => ({ execution_id: id, job_id: id, session_id: "session", status, started_at, updated_at: started_at, parent_execution_id: null, effect_summary: {}, task_label: id, capabilities: { pause: false, step: false, steer: false, retry: false, fork: false }, status_version: 1, active_child_ids: [], ...extra });
async function mounted(executions, check, processes = [], stateOverrides = {}, processOverrides = {}) {
  const selected = [];
  globalThis.activityController = { executions, branches: [], connection: { state: "connected" }, fetchedAt: 1, selectExecution(id) { selected.push(id); },
    command: async (command) => { (globalThis.commands ||= []).push(command); return { status: "accepted", command_id: command.command_id }; }, ...stateOverrides };
  globalThis.activityProcesses = { items: processes, calls: [], stale: false, loaded: true, refresh() {}, ...processOverrides };
  globalThis.commands = []; globalThis.sentCommands = [];
  globalThis.activityEventReads = [];
  globalThis.activityRuns ??= async () => ({ runs: [], offset: 0, total: 0 });
  globalThis.activityEvents = async (session, runId) => { globalThis.activityEventReads.push(runId); return { run_id: runId, revision: "r", events: globalThis.runEvents?.[runId] ?? [] }; };
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  try {
    const render = props => act(async () => root.render(createElement(RunningPanel, { active: true, sessionId: "session", ...props })));
    await render();
    const click = async text => {
      const button = [...host.querySelectorAll("button, [role=button]")].find(b => b.textContent.includes(text));
      assert.ok(button, text);
      await act(async () => button.click());
    };
    await check(host, click, selected, render);
  } finally { await act(async () => root.unmount()); host.remove(); }
}

const agentCall = { id: "c1", execution_id: "turn", name: "agent", description: "Fix page close",
  prompt: "Inspect the close branch and fix it", command: "", started_at: now - 3 * DAY, status: "unknown" };
const spawned = run("j_fix", "reconciliation_required", now - 3 * DAY + 2, { parent_execution_id: "turn",
  display: { kind: "job_agent", label: "Fix_page_close", assistant_message_id: "j_fix_user_reply" }, effect_summary: { provider_response_incomplete: true } });

const activityRun = (id, started_at, extra = {}) => ({ id, message_id: id, user_message_id: `${id}_user`, execution_id: null, is_report: false, asked_by: "you", asked_preview: "the question",
  reply: `Reply ${id}`, reply_truncated: false, started_at, ended_at: started_at + 36, execution_status: null, message_status: "completed", reason_code: null, task_outcome: null, task_text: null, event_count: 1, revision: "r", ...extra });
const listRuns = runs => { globalThis.activityRuns = async (session, query) => ({ runs: runs.slice(query.offset ?? 0, (query.offset ?? 0) + (query.limit ?? runs.length)), offset: query.offset ?? 0, total: runs.length }); };
const asked = (at, text = "the question") => ({ kind: "asked", at, by: "you", text, truncated: false });
const replied = (at, text = "the answer") => ({ kind: "replied", at, text, truncated: false });
const step = (at, command, extra = {}) => ({ kind: "step", at, node_id: `node_${command}`, tool_call_id: null, name: "bash", input: { command }, input_truncated: false, result: "output", result_truncated: false, failed: false, ...extra });
const finishedTurn = [run("turn", "completed", now - 300, { terminal_at: now - 200 })];
const expanded = host => [...host.querySelectorAll("[data-row-id][aria-expanded=true]")].map(row => row.getAttribute("data-row-id"));
const settle = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
const key = async (target, name, extra = {}) => act(async () => {
  const event = new Event("keydown", { bubbles: true, cancelable: true });
  Object.assign(event, { key: name, ...extra });
  target.dispatchEvent(event);
});
const row = (host, text) => [...host.querySelectorAll("[data-row-id]")].find(item => item.textContent.includes(text));

test.afterEach(() => { globalThis.activityRuns = undefined; globalThis.runEvents = undefined; });

test("the overview sums the sub-agents up under the main agent", async () => {
  await mounted([
    run("turn", "reconciliation_required", now - 3 * DAY, { task_label: "check and fix it" }), spawned,
    run("live", "running", now - 120, { task_label: "fill the form" }),
    run("j_live", "running", now - 100, { parent_execution_id: "live", display: { kind: "job_agent", label: "Form_filler" } }),
    run("done", "completed", now - 60, { task_label: "what happened" }),
    run("j_done", "completed", now - 50, { parent_execution_id: "done", display: { kind: "job_agent", label: "Research" } }),
  ], async host => {
    const text = host.textContent;
    assert.match(text, /AgentsMain agentRunning · 2 min · 3 sub-agents$/);
    assert.doesNotMatch(text, /Research|Form filler|Fix page close/);
    assert.doesNotMatch(text, /check and fix it|fill the form|what happened/);
  }, [], {}, { calls: [agentCall] });
});

test("a conversation whose turns left no execution record still lists its main agent, and empty groups are not shown", async () => {
  useSessionStore.setState({ conversations: { session: { id: "session", title: "NeurIPS trip", updated_at: now - 60 } } });
  try {
    await mounted([], async (host, click) => {
      assert.match(host.textContent, /AgentsMain agent\d{1,2}:\d{2}/);
      assert.doesNotMatch(host.textContent, /Programs and commands|Scheduled tasks/);
      await click("Main agent");
      assert.match(host.textContent, /NeurIPS trip/);
    });
  } finally {
    useSessionStore.setState({ conversations: { session: { id: "session", title: "NeurIPS trip" } } });
  }
});

test("ongoing shell calls and programs keep their level-1 rows, and open their own pages", async () => {
  await mounted([], async (host, click) => {
    assert.match(host.textContent, /AgentsMain agentRunning bash · \d+ s/);
    assert.match(host.textContent, /Programs and commandspythonpython worker\.pyRunning · \d+ sbashCommand · Running · \d+ s/);
    await click("Command · Running");
    assert.match(host.textContent, /COMMAND PAGE/);
  }, [{ id: "proc", command: "python worker.py", status: "running", started_at: now, backend_id: "local" }], {},
  { calls: [{ id: "call", name: "bash", command: "sleep 30", started_at: now - 5, status: "running" }] });
});

test("calls do not flash as unowned before the executions are read", async () => {
  await mounted([], async host => {
    assert.doesNotMatch(host.textContent, /Needs you|Fix page close/);
  }, [], { fetchedAt: null }, { calls: [agentCall] });
});

test("Activity never flashes an error for loading, reconnection, or another conversation's failure", async () => {
  for (const connection of [{state:"reconnecting"}, {state:"gap"}, {state:"stale"}, {state:"stale",message:"previous failure",errorSessionId:"other"}]) {
    await mounted([], async host => {
      assert.doesNotMatch(host.textContent, /statuses are unavailable|Could not load activity/);
    }, [], {connection,fetchedAt:null}, {loaded:true});
  }
});

test("Activity reports continuing read failures without replacing saved records", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  for (const processFailed of [false,true]) await mounted([], async host => {
    await act(async () => { t.mock.timers.tick(5000); });
    assert.match(host.textContent, /Updating status.*Showing saved records/);
  }, [], {connection: processFailed ? {state:"connected"} : {state:"stale",message:"request failed",errorSessionId:"session"}}, {stale:processFailed});
});

test("the agent page is the head, then the runs under day labels on one axis", async () => {
  listRuns([activityRun("newest", now - 300, { ended_at: now - 196 }), activityRun("older", now - 2 * DAY)]);
  await mounted([run("turn", "completed", now - 300, { terminal_at: now - 196 })], async (host, click) => {
    await click("Main agent");
    const text = host.textContent;
    assert.match(text, /Activity/);
    assert.match(text, /Main agent|NeurIPS trip/);
    assert.doesNotMatch(text, /Each bar is one run/);
    assert.match(text, /Reply newest.*\d\d:\d\d · 1m 44s/s);
    assert.match(text, /0123 min/);
    assert.equal(host.querySelectorAll("[title]").length, 0);
  });
});

test("only an opened row reads its events, and rows stay open however many are opened", async () => {
  listRuns([activityRun("a", now - 300), activityRun("b", now - 200 - DAY), activityRun("c", now - 100 - DAY)]);
  globalThis.runEvents = { a: [asked(now - 300), replied(now - 280)], b: [asked(now - 200 - DAY)], c: [] };
  await mounted(finishedTurn, async (host, click) => {
    await click("Main agent");
    assert.deepEqual(globalThis.activityEventReads, []);
    assert.deepEqual(expanded(host), []);
    await click("Reply a");
    assert.deepEqual(globalThis.activityEventReads, ["a"]);
    assert.match(host.textContent, /Asked: the question.*Replied: the answer/s);
    await click("Reply b");
    assert.deepEqual(expanded(host), ["a", "b"]);
    await click("Reply a");
    assert.deepEqual(expanded(host), ["b"]);
    assert.doesNotMatch(host.textContent, /Replied: the answer/);
  });
});

test("the newest run opens by itself only when it failed, waits or runs, and a close sticks", async () => {
  listRuns([activityRun("fine", now - 300)]);
  await mounted(finishedTurn, async (host, click) => {
    await click("Main agent");
    assert.deepEqual(expanded(host), []);
  });
  listRuns([activityRun("bad", now - 300, { reply: "[error] boom" }), activityRun("older", now - 900)]);
  globalThis.runEvents = { bad: [asked(now - 300)] };
  await mounted(finishedTurn, async (host, click) => {
    await click("Main agent");
    assert.deepEqual(expanded(host), ["bad"]);
    await click("boom");
    assert.deepEqual(expanded(host), []);
    await act(async () => { window.dispatchEvent(new Event("op:execution-update")); });
    await settle();
    assert.deepEqual(expanded(host), []);
  });
});

test("a poll replaces rows without closing them, and keeps what was shown", async () => {
  const runs = Array.from({ length: 25 }, (_, index) => activityRun(`r${index}`, now - 300 - index * 60));
  listRuns(runs);
  globalThis.runEvents = { r1: [asked(now - 360)] };
  await mounted(finishedTurn, async (host, click) => {
    await click("Main agent");
    assert.match(host.textContent, /Show 5 earlier/);
    await click("Show 5 earlier");
    await settle();
    assert.match(host.textContent, /Reply r24/);
    await click("Reply r1");
    const before = row(host, "Reply r1");
    listRuns([activityRun("fresh", now - 10), ...runs.map(item => item.id === "r2" ? { ...item, reply: "Changed" } : item)]);
    await act(async () => { window.dispatchEvent(new Event("op:execution-update")); });
    await settle();
    assert.match(host.textContent, /Reply fresh/);
    assert.match(host.textContent, /Changed/);
    assert.equal(row(host, "Reply r1"), before);
    assert.deepEqual(expanded(host), ["r1"]);
  });
});

test("a new run does not take the oldest row, or its open content, off the page", async () => {
  const runs = Array.from({ length: 20 }, (_, index) => activityRun(`r${index}`, now - 300 - index * 60));
  listRuns(runs);
  globalThis.runEvents = { r19: [asked(now - 1440, "the oldest question")] };
  await mounted(finishedTurn, async (host, click) => {
    await click("Main agent");
    await click("Reply r19");
    assert.deepEqual(expanded(host), ["r19"]);
    listRuns([activityRun("fresh", now - 10), ...runs]);
    await act(async () => { window.dispatchEvent(new Event("op:execution-update")); });
    await settle();
    assert.match(host.textContent, /Reply fresh/);
    assert.deepEqual(expanded(host), ["r19"]);
    assert.match(host.textContent, /the oldest question/);
    assert.doesNotMatch(host.textContent, /earlier/);
  });
});

test("past the server's page size a new run removes nothing, and Show more continues in order", async () => {
  const runs = Array.from({ length: 300 }, (_, index) => activityRun(`r${index}`, now - 300 - index * 60));
  listRuns(runs);
  await mounted(finishedTurn, async (host, click) => {
    await click("Main agent");
    await click("Show 50 earlier");
    await settle();
    await click("Show 50 earlier");
    await settle();
    listRuns([activityRun("fresh", now - 10), ...runs]);
    await act(async () => { window.dispatchEvent(new Event("op:execution-update")); });
    await settle();
    const shown = [...host.querySelectorAll("[data-row-id]")].map(item => item.getAttribute("data-row-id")).filter(id => /^(r\d+|fresh)$/.test(id));
    assert.deepEqual(shown, ["fresh", ...runs.slice(0, 120).map(item => item.id)]);
    await click("Show 50 earlier");
    await settle();
    const more = [...host.querySelectorAll("[data-row-id]")].map(item => item.getAttribute("data-row-id")).filter(id => /^r\d+$/.test(id));
    assert.deepEqual(more, runs.slice(0, 170).map(item => item.id));
  });
});

test("an open finished run reads again until its background sub-agent has ended", async () => {
  listRuns([activityRun("a", now - 300)]);
  const agent = extra => ({ kind: "subagent", at: now - 290, ended_at: null, job_id: "j_bg", name: "Background", agent_id: null, context: null, status: "running", never_started: false, failed: false,
    brief: "go", brief_truncated: false, result: null, result_truncated: false, error: null, created_at: now - 290, closed_as: null, conversation: { session_id: "session", head_id: null }, children: [], ...extra });
  globalThis.runEvents = { a: [agent({})] };
  await mounted(finishedTurn, async (host, click) => {
    await click("Main agent");
    await click("Reply a");
    assert.deepEqual(globalThis.activityEventReads, ["a"]);
    globalThis.runEvents = { a: [agent({ ended_at: now - 100, status: "errored", failed: true, error: "boom", closed_as: "errored" })] };
    await act(async () => { window.dispatchEvent(new Event("op:job-status")); });
    await settle();
    assert.deepEqual(globalThis.activityEventReads, ["a", "a"]);
    assert.match(host.textContent, /BackgroundFailed/);
    await act(async () => { window.dispatchEvent(new Event("op:job-status")); });
    await settle();
    assert.deepEqual(globalThis.activityEventReads, ["a", "a"]);
  });
});

test("a run keeps its row when its reply arrives and its id changes", async () => {
  listRuns([activityRun("exec_1", now - 30, { message_id: null, execution_id: "exec_1", reply: "", ended_at: null, execution_status: "running" })]);
  globalThis.runEvents = { exec_1: [asked(now - 30)], reply_1: [asked(now - 30), replied(now - 1)] };
  await mounted([run("exec_1", "running", now - 30)], async (host, click) => {
    await click("Main agent");
    assert.deepEqual(expanded(host), ["exec_1"]);
    listRuns([activityRun("reply_1", now - 30, { execution_id: "exec_1", ended_at: now, execution_status: "completed" })]);
    await act(async () => { window.dispatchEvent(new Event("op:execution-update")); });
    await settle();
    assert.deepEqual(expanded(host), ["exec_1"]);
    assert.match(host.textContent, /Reply reply_1/);
  });
});

test("steps read in the chat's words, open to input and result, and failed ones say so first", async () => {
  listRuns([activityRun("a", now - 300)]);
  globalThis.runEvents = { a: [step(now - 290, "npm test"), step(now - 280, "ls", { failed: true })] };
  await mounted(finishedTurn, async (host, click) => {
    await click("Main agent");
    await click("Reply a");
    assert.match(host.textContent, /Ran npm test.*Failed · Ran ls/s);
    await click("Ran npm test");
    assert.match(host.textContent, /Input.*npm test.*Result.*output/s);
  });
});

test("attempts show the stored failure text, or the reason code when none was stored", async () => {
  listRuns([activityRun("a", now - 300)]);
  const attempt = (number, extra) => ({ kind: "attempt", at: now - 290 + number, number, ended_at: now - 280, status: "ended", outcome: "failed", reason_code: "agent_runner_error", failure_text: null, checkpoint_id: null, ...extra });
  globalThis.runEvents = { a: [attempt(1, { outcome: "restart_recoverable", reason_code: null, checkpoint_id: "ckpt" }), attempt(2, { failure_text: "RuntimeError: boom" }), attempt(3, {})] };
  await mounted(finishedTurn, async (host, click) => {
    await click("Main agent");
    await click("Reply a");
    assert.match(host.textContent, /Paused · Attempt 1.*Failed · Attempt 2.*Failed · Attempt 3/s);
    await click("Attempt 1");
    assert.match(host.textContent, /Saved point.*ckpt/s);
    await click("Attempt 2");
    assert.match(host.textContent, /RuntimeError: boom/);
    await click("Attempt 3");
    assert.match(host.textContent, /Reason code.*agent_runner_error/s);
  });
});

test("a failed attempt opens to its error or code alone, a paused one to where it stopped", async () => {
  listRuns([activityRun("a", now - 300)]);
  const attempt = (number, extra) => ({ kind: "attempt", at: now - 290 + number, number, ended_at: now - 280, status: "ended", outcome: "failed", reason_code: "agent_runner_error", failure_text: null, checkpoint_id: "ckpt", ...extra });
  globalThis.runEvents = { a: [attempt(1, { outcome: "waiting_at_safe_point" }), attempt(2, { failure_text: "RuntimeError: boom" })] };
  await mounted(finishedTurn, async (host, click) => {
    await click("Main agent");
    await click("Reply a");
    assert.doesNotMatch(host.textContent, /Failed · Attempt 1/);
    await click("Attempt 1");
    assert.match(host.textContent, /Outcome.*waiting_at_safe_point.*Saved point.*ckpt/s);
    assert.doesNotMatch(host.textContent, /Reason code/);
    await click("Attempt 1");
    await click("Attempt 2");
    assert.match(host.textContent, /Error.*RuntimeError: boom/s);
    assert.doesNotMatch(host.textContent, /Reason code|Outcome|Saved point/);
  });
});

test("one attempt that went fine adds no row; with more than one each is listed", async () => {
  const attempt = (number, outcome) => ({ kind: "attempt", at: now - 290 + number, number, ended_at: now - 280, status: "ended", outcome, reason_code: null, failure_text: null, checkpoint_id: null });
  listRuns([activityRun("a", now - 300), activityRun("b", now - 600)]);
  globalThis.runEvents = { a: [asked(now - 300), attempt(1, "completed"), replied(now - 280)], b: [attempt(1, "restart_recoverable"), attempt(2, "completed")] };
  await mounted(finishedTurn, async (host, click) => {
    await click("Main agent");
    await click("Reply a");
    assert.match(host.textContent, /Asked: the question/);
    assert.doesNotMatch(host.textContent, /Attempt/);
    await click("Reply b");
    assert.match(host.textContent, /Paused · Attempt 1.*Completed · Attempt 2/s);
  });
});

test("sub-agents nest in their run with their conversation and details; one that never started says so", async () => {
  listRuns([activityRun("a", now - 300)]);
  const agent = (extra) => ({ kind: "subagent", at: now - 290, ended_at: now - 228, job_id: "j_one", name: "Research_notes", agent_id: "butler", context: "clean", status: "completed", never_started: false, failed: false,
    brief: "look it up", brief_truncated: false, result: "found it", result_truncated: false, error: null, created_at: now - 290, closed_as: "completed", conversation: { session_id: "session", head_id: "h" }, children: [], ...extra });
  globalThis.agentTip = "agent_tip";
  globalThis.runEvents = { a: [agent({}), agent({ job_id: null, name: "Broken", never_started: true, failed: true, ended_at: null, error: "admission is missing", conversation: null, agent_id: null, context: null, closed_as: null, result: null })] };
  await mounted(finishedTurn, async (host, click) => {
    await click("Main agent");
    await click("Reply a");
    assert.match(host.textContent, /Research notes1m 2s/);
    assert.match(host.textContent, /BrokenFailed · never started/);
    await click("Research notes");
    assert.match(host.textContent, /Asked: look it up.*Replied: found it.*Open its conversation.*Technical details/s);
    await click("Open its conversation");
    await settle();
    assert.deepEqual(globalThis.sentCommands.map(c => [c.action, c.head_msg_id]), [["checkout_branch", "agent_tip"], ["load_session", undefined]]);
    await click("Broken");
    assert.match(host.textContent, /Failed · admission is missing/);
  });
});

test("a sub-agent still running can already be opened in its conversation", async () => {
  listRuns([activityRun("a", now - 300)]);
  globalThis.agentTip = "live_tip";
  globalThis.runEvents = { a: [{ kind: "subagent", at: now - 290, ended_at: null, job_id: "j_live", name: "Live", agent_id: null, context: null, status: "running", never_started: false, failed: false,
    brief: "go", brief_truncated: false, result: null, result_truncated: false, error: null, created_at: now - 290, closed_as: null, conversation: { session_id: "session", head_id: null }, children: [] }] };
  await mounted(finishedTurn, async (host, click) => {
    await click("Main agent");
    await click("Reply a");
    await click("Live");
    await click("Open its conversation");
    await settle();
    assert.deepEqual(globalThis.sentCommands.map(c => [c.action, c.head_msg_id]), [["checkout_branch", "live_tip"], ["load_session", undefined]]);
  });
});

test("action rows draw line icons, not filled ones", async () => {
  listRuns([activityRun("a", now - 300, { execution_id: "turn", execution_status: "running", ended_at: null })]);
  const live = run("turn", "running", now - 300, { capabilities: { pause: true, steer: false, cancel: false }, run_id: "run_1", revision_id: "rev_1" });
  await mounted([live], async (host, click) => {
    await click("Main agent");
    await settle();
    const pause = row(host, "Pause");
    assert.ok(pause, "Pause row");
    const icon = pause.querySelector("svg");
    assert.equal(icon.getAttribute("stroke-width"), "1.8");
    assert.equal(icon.getAttribute("width"), "18");
    assert.equal(icon.getAttribute("fill"), "none");
  });
});

test("a waiting run opens itself, shows the question last and goes to the chat's card", async () => {
  listRuns([activityRun("a", now - 60, { execution_id: "turn", reply: "", ended_at: null, execution_status: "paused" })]);
  globalThis.runEvents = { a: [asked(now - 60)] };
  useSessionStore.setState({ pendingDecisions: [{ id: "d1", sessionId: "session", executionId: "turn", kind: "question", prompt: "Which one?", options: ["left", "right"] }] });
  try {
    await mounted([run("turn", "paused", now - 60)], async (host, click) => {
      await click("Main agent");
      await settle();
      assert.match(host.textContent, /Which one\?Waiting for your answer/);
      assert.match(host.textContent, /Answer in chat/);
      await click("Which one?");
      assert.match(host.textContent, /Choices.*left · right/s);
    });
  } finally { useSessionStore.setState({ pendingDecisions: [] }); }
});

test("controls come from what the run allows, and are off with words when not connected", async () => {
  const live = run("turn", "running", now - 60, { capabilities: { pause: true, steer: true, cancel: true, step: false, retry: false, fork: false }, run_id: "run_1", revision_id: "rev_1" });
  listRuns([activityRun("a", now - 60, { execution_id: "turn", reply: "", ended_at: null, execution_status: "running" })]);
  await mounted([live], async (host, click) => {
    await click("Main agent");
    await settle();
    assert.match(host.textContent, /PauseHolds at the next safe point/);
    assert.match(host.textContent, /Add instruction/);
    await click("Pause");
    assert.equal(globalThis.commands[0].action, "execution.pause");
    await click("Technical details");
    assert.match(host.textContent, /Execution ID.*turn/s);
  });
  await mounted([live], async (host, click) => {
    await click("Main agent");
    await settle();
    assert.match(host.textContent, /PauseNot connected/);
    assert.equal(host.querySelectorAll("[title]").length, 0);
  }, [], { connection: { state: "reconnecting" } });
});

test("a failed run has stopped: no Retry, and Create branch in the details", async () => {
  const failed = run("turn", "failed", now - 60, { checkpoint_head_id: "ckpt_1", capabilities: { retry: true, fork: true, pause: false, step: false, steer: false }, run_id: "run_1", revision_id: "rev_1" });
  listRuns([activityRun("a", now - 60, { execution_id: "turn", execution_status: "failed" })]);
  const at = now - 30;
  const stamp = new Date(at * 1000).toTimeString().slice(0, 8);
  globalThis.runEvents = { a: [{ kind: "attempt", at, number: 1, ended_at: at, status: "ended", outcome: "restart_recoverable", reason_code: null, failure_text: null, checkpoint_id: "ckpt_1" }] };
  await mounted([failed], async (host, click) => {
    await click("Main agent");
    await settle();
    assert.doesNotMatch(host.textContent, /Retry/);
    await click("Technical details");
    assert.match(host.textContent, new RegExp(`Create branchTry a change from ${stamp}`));
  });
});

test("Esc goes back only from inside the panel, Activity in the rail goes back, and level 1 returns", async () => {
  listRuns([activityRun("a", now - 300)]);
  await mounted([], async (host, click, selected, render) => {
    await click("Main agent");
    assert.match(host.textContent, /Reply a/);
    await key(document.body, "Escape");
    assert.match(host.textContent, /Reply a/);
    const input = document.createElement("input");
    host.querySelector("[data-row-id]").closest("div").append(input);
    await key(input, "Escape");
    assert.match(host.textContent, /Reply a/);
    await key(row(host, "Reply a"), "Escape");
    assert.doesNotMatch(host.textContent, /Reply a/);
    assert.match(host.textContent, /AgentsMain agent/);
    await click("Main agent");
    assert.match(host.textContent, /Reply a/);
    await render({ resetSignal: 1 });
    assert.doesNotMatch(host.textContent, /Reply a/);
  }, [], {}, { calls: [{ id: "call", name: "bash", command: "sleep 30", started_at: now - 5, status: "running" }] });
});

test("the keyboard moves among rows with one Tab stop and opens with right, closes with left", async () => {
  listRuns([activityRun("a", now - 300), activityRun("b", now - 600)]);
  globalThis.runEvents = { a: [asked(now - 300)], b: [] };
  await mounted(finishedTurn, async (host, click) => {
    await click("Main agent");
    await settle();
    const first = row(host, "Reply a");
    assert.equal(host.querySelectorAll('[data-row-id][tabindex="0"]').length, 1);
    await key(first, "ArrowDown");
    const second = row(host, "Reply b");
    assert.equal(document.activeElement, second);
    assert.equal(host.querySelectorAll('[data-row-id][tabindex="0"]').length, 1);
    await key(second, "Home");
    assert.equal(document.activeElement, first);
    await key(first, "ArrowRight");
    assert.deepEqual(expanded(host), ["a"]);
    await key(first, "ArrowLeft");
    assert.deepEqual(expanded(host), []);
  });
});
