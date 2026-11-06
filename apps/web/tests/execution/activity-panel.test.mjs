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
const { setActivityView, DEFAULT_ACTIVITY_VIEW } = await import("../../lib/prefs/activity-view.ts");
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
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(createElement(RunningPanel, { active: true, sessionId: "session" })));
    const click = async text => {
      const button = [...host.querySelectorAll("button, [role=button]")].find(b => b.textContent.includes(text));
      assert.ok(button, text);
      await act(async () => button.click());
    };
    await check(host, click, selected);
  } finally { await act(async () => root.unmount()); host.remove(); }
}

const agentCall = { id: "c1", execution_id: "turn", name: "agent", description: "Fix page close",
  prompt: "Inspect the close branch and fix it", command: "", started_at: now - 3 * DAY, status: "unknown" };
const spawned = run("j_fix", "reconciliation_required", now - 3 * DAY + 2, { parent_execution_id: "turn",
  display: { kind: "job_agent", label: "Fix_page_close", assistant_message_id: "j_fix_user_reply" }, effect_summary: { provider_response_incomplete: true } });

test("the overview sums the sub-agents up under the main agent, whose page lists each once", async () => {
  await mounted([
    run("turn", "reconciliation_required", now - 3 * DAY, { task_label: "check and fix it" }), spawned,
    run("live", "running", now - 120, { task_label: "fill the form" }),
    run("j_live", "running", now - 100, { parent_execution_id: "live", display: { kind: "job_agent", label: "Form_filler" } }),
    run("done", "completed", now - 60, { task_label: "what happened" }),
    run("j_done", "completed", now - 50, { parent_execution_id: "done", display: { kind: "job_agent", label: "Research" } }),
  ], async (host, click) => {
    let text = host.textContent;
    // The overview is the main agent alone, with its sub-agents summed up.
    assert.match(text, /AgentsMain agentRunning · 2 min · 3 sub-agentsPrograms and commandsScheduled tasks$/);
    assert.doesNotMatch(text, /Research|Form filler|Fix page close/);
    // The messages themselves stay in the chat.
    assert.doesNotMatch(text, /check and fix it|fill the form|what happened/);
    // Its page lists every sub-agent, newest first; the interrupted one
    // once, where it sits, as plain history.
    await click("Main agent");
    text = host.textContent;
    assert.match(text, /Sub-agents.*ResearchCompleted.*Form fillerRunning.*Fix page closeInterrupted/s);
    assert.equal(text.match(/Fix page close/g).length, 1);
    // They are the page's own list, so the first level draws no lines.
    assert.equal(host.querySelectorAll("[data-last]").length, 0);
    // Only the view menu opens; no row expands in place.
    assert.equal(host.querySelectorAll("[aria-expanded]:not([aria-haspopup])").length, 0);
  }, [], {}, { calls: [agentCall] });
});

test("an interrupted agent call opens a page with its task and nothing to handle", async () => {
  globalThis.agentTip = "j_fix_tip";
  await mounted([run("turn", "reconciliation_required", now - 3 * DAY, { task_label: "check and fix it" }), spawned], async (host, click) => {
    await click("Main agent");
    await click("Fix page close");
    const text = host.textContent;
    assert.match(text, /Sub-agent ·/);
    assert.match(text, /Interrupted/);
    assert.doesNotMatch(text, /Mark as ended|to handle|Waiting for you/);
    assert.match(text, /Task.*Inspect the close branch/s);
    assert.match(text, /From.*check and fix it/s);
    await click("Open its conversation");
    assert.deepEqual(globalThis.sentCommands.map(c => c.action), ["checkout_branch", "load_session"]);
    assert.equal(globalThis.sentCommands[0].head_msg_id, "j_fix_tip");
    // Back goes up one level, to the main agent's page, then the overview.
    await click("← Main agent");
    assert.match(host.textContent, /Sub-agents/);
    await click("Activity");
    assert.match(host.textContent, /AgentsMain agent/);
  }, [], {}, { calls: [agentCall] });
  delete globalThis.agentTip;
});

test("an agent page leads with its status, then where it came from and what it did", async () => {
  await mounted([run("turn", "reconciliation_required", now - 3 * DAY, { task_label: "check and fix it" }), spawned,
    run("j_other", "completed", now - 3 * DAY + 50, { parent_execution_id: "turn", display: { kind: "job_agent", label: "Write_docs" } })],
  async (host, click, selected) => {
    await click("Main agent");
    await click("Fix page close");
    let text = host.textContent;
    assert.match(text, /Sub-agent ·.*Fix page close.*Interrupted/s);
    // The page carries the run's own record (progress, controls, raw
    // details) after what it did; opening it selects the run.
    assert.match(text, /Open its conversation.*From.*check and fix it.*Task.*Steps.*Progress.*DEBUGGER/s);
    assert.doesNotMatch(text, /Technical details/);
    assert.deepEqual(selected, ["j_fix"]);
    await click("check and fix it");
    text = host.textContent;
    assert.match(text, /Run ·.*check and fix it/s);
    assert.match(text, /Steps.*Write docs.*Fix page close.*DEBUGGER/s);
    assert.match(host.textContent, /← Fix page close/);
    await click("Write docs");
    assert.deepEqual(selected, ["j_fix", "turn", "j_other"]);
    assert.match(host.textContent, /DEBUGGER/);
  }, [], {}, { calls: [agentCall] });
});

test("sub-agents are paged on the main agent's page", async () => {
  const runs = Array.from({ length: 25 }, (_, i) => run(`j${i}`, "completed", now - i * 60 - (i > 2 ? 2 * DAY : 0),
    { parent_execution_id: "turn", display: { kind: "job_agent", label: `agent_${i}` } }));
  await mounted([run("turn", "completed", now - 3 * DAY), ...runs], async (host, click) => {
    assert.match(host.textContent, /AgentsMain agent.+ · 25 sub-agents/);
    await click("Main agent");
    const listed = () => [...host.querySelectorAll("button")].filter(button => /^agent \d+/.test(button.textContent)).length;
    assert.equal(listed(), 20);
    await click("Show 5 earlier");
    assert.doesNotMatch(host.textContent, /Show \d+ earlier/);
    assert.equal(listed(), 25);
  });
});

test("ongoing shell calls show on the main agent and, with programs, in their own group", async () => {
  await mounted([], async (host, click) => {
    assert.match(host.textContent, /AgentsMain agentRunning bash · \d+ s/);
    // A program row: its name, its command in monospace, then its state.
    assert.match(host.textContent, /Programs and commandspythonpython worker\.pyRunning · \d+ sbashCommand · Running · \d+ s/);
    assert.doesNotMatch(host.textContent, /will appear here/);
    await click("Main agent");
    assert.match(host.textContent, /Running.*bash/s);
    await click("bash");
    assert.match(host.textContent, /Command.*sleep 30/s);
  }, [{ id: "proc", command: "python worker.py", status: "running", started_at: now, backend_id: "local" }], {},
  { calls: [{ id: "call", name: "bash", command: "sleep 30", started_at: now - 5, status: "running" }] });
});

const failedSpawn = { id: "turn_t_call_1", caller: "turn_reply", owner_job_id: null, job_id: null, description: "Upload fix",
  prompt: "Fix the upload path", at: now - 5 * DAY, failed: true, error: "[agent error] JobAgentInputError: Job Agent input must be JSON serializable" };

test("the main conversation page shows its latest run, the sub-agents it started and the ones that never started", async () => {
  await mounted([run("turn", "reconciliation_required", now - 3 * DAY, { task_label: "check and fix it" }), spawned,
    run("latest", "completed", now - 600, { task_label: "prepare the visa form", terminal_at: now - 480 })],
  async (host, click, selected) => {
    // A call that never started a sub-agent counts with the sub-agents.
    assert.match(host.textContent, /AgentsMain agent\S+ · 2 sub-agentsPrograms and commandsScheduled tasks$/);
    await click("Main agent");
    let text = host.textContent;
    assert.doesNotMatch(text, /Idle/);
    assert.match(text, /Last message.*prepare the visa form.*Completed · /s);
    assert.match(text, /Sub-agents.*Fix page close.*Interrupted.*Upload fix.*Failed to start/s);
    await click("Upload fix");
    text = host.textContent;
    assert.match(text, /← Main agent/);
    assert.match(text, /Upload fix.*Failed to start.*did not start a sub-agent.*Started by.*Main agent.*Error.*JobAgentInputError.*Task.*Fix the upload path/s);
    await click("Main agent");
    // The main page has no inspector of its own: the latest run's row
    // opens the run, whose page holds the record.
    assert.doesNotMatch(host.textContent, /Technical details/);
    await click("prepare the visa form");
    assert.deepEqual(selected, ["latest"]);
    assert.match(host.textContent, /Run ·.*prepare the visa form.*Completed.*Progress.*DEBUGGER/s);
  }, [], {}, { calls: [agentCall], spawns: [failedSpawn] });
});

test("a command cut short by a restart is history, not something to handle", async () => {
  const bash = { id: "c2", execution_id: "old", name: "bash", description: "Install the browser", command: "npx playwright install", prompt: "", started_at: now - DAY, status: "unknown" };
  await mounted([run("old", "reconciliation_required", now - DAY), run("latest", "completed", now - 600, { terminal_at: now - 500 })],
  async (host, click) => {
    assert.match(host.textContent, /AgentsMain agent\d\d:\d\dPrograms/);
    // The command is listed with the shell work, greyed as interrupted.
    assert.match(host.textContent, /Programs and commandsInstall the browserCommand · Interrupted · /);
    await click("Main agent");
    assert.match(host.textContent, /Last message/);
    assert.doesNotMatch(host.textContent, /Mark as ended|to handle|Install the browser/);
    await click("Activity");
    await click("Install the browser");
    assert.match(host.textContent, /Interrupted.*interrupted before this call returned/s);
  }, [], {}, { calls: [bash] });
});

test("a sub-agent another one started sits under it and names it", async () => {
  await mounted([run("turn", "completed", now - 600), run("j_parent", "completed", now - 500, { parent_execution_id: "turn", display: { kind: "job_agent", label: "Research" } }),
    run("j_child", "completed", now - 400, { parent_execution_id: "j_parent", display: { kind: "job_agent", label: "Read_pages" } })],
  async (host, click) => {
    await click("Main agent");
    assert.match(host.textContent, /Sub-agents.*Research.*Read pages/s);
    // Research is the page's own list; Read pages hangs under it.
    const depths = [...host.querySelectorAll("[style*='--depth']")].map(node => node.getAttribute("style"));
    assert.deepEqual(depths.map(style => style.match(/--depth:\s*(\d)/)[1]), ["1"]);
    // It is the last and the first row under its parent: no line runs on
    // past it, and its elbow reaches up to the parent.
    assert.deepEqual([...host.querySelectorAll("[data-last]")].map(node => node.getAttribute("data-last")), ["1"]);
    assert.deepEqual([...host.querySelectorAll("[data-first]")].map(node => node.getAttribute("data-first")), ["1"]);
    await click("Read pages");
    assert.match(host.textContent, /Started by.*Research/s);
    assert.match(host.textContent, /Task.*Read the pages/s);
    await click("Research");
    assert.match(host.textContent, /Sub-agent ·.*Research.*Steps.*Read pages/s);
  }, [], {}, { spawns: [{ id: "j_parent_user_reply_t_x", caller: "j_parent_user_reply", owner_job_id: "j_parent", job_id: "j_child",
    description: "Read pages", prompt: "Read the pages", at: now - 400, failed: false, error: "" }] });
});

test("titles read as the words a person wrote, not attachment markup, sender ids or resume prompts", async () => {
  await mounted([
    run("a", "paused", now - 10, { task_label: '[attachment: IMG_0177.JPG (jpg, 987 KB) @json "/Users/x/attachments/IMG_0177.JPG" ' }),
    run("b", "paused", now - 20, { task_label: '[attachment: Inv.pdf (pdf, 112 KB) @json "/Users/x/Inv.pdf"] what about this?' }),
    run("c", "paused", now - 30, { task_label: "Continue the interrupted task using saved conversation history. Inspect actual state" }),
    run("d", "paused", now - 40, { task_label: "[oTestUser000@im.wechat] hello there" }),
  ], async (host, click) => {
    // Paused runs are the main agent's; its page names each one.
    // Four runs wait for an answer: a red 4 on the glyph, the line keeps the time.
    assert.match(host.textContent, /Agents4Main agent\d\d:\d\dPrograms and commandsScheduled tasks$/);
    await click("Main agent");
    const text = host.textContent;
    assert.match(text, /"Attachment IMG_0177\.JPG" is waiting for your answer/);
    assert.match(text, /what about this\?/);
    assert.match(text, /Continue the interrupted task(?! using)/);
    assert.match(text, /hello there/);
    assert.doesNotMatch(text, /\[attachment:|@json|@im\.wechat/);
  });
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

test("the branch tree carries the lines of the rows above that still have siblings below", async () => {
  const { agentBranches } = await import("../../lib/execution/activity-model.ts");
  const job = (id, parent, at) => run(id, "completed", at, { parent_execution_id: parent, display: { kind: "job_agent", label: id } });
  const rows = agentBranches([run("turn", "completed", now - 900), job("j_a", "turn", now - 800), job("j_a1", "j_a", now - 700),
    job("j_a1x", "j_a1", now - 650), job("j_a2", "j_a", now - 600), job("j_b", "turn", now - 500)]).tree();
  assert.deepEqual(rows.map(row => [row.item.execution_id, row.depth, row.last, row.guides]), [
    ["j_b", 1, false, []],
    ["j_a", 1, true, []],
    ["j_a2", 2, false, []],
    ["j_a1", 2, true, []],
    ["j_a1x", 3, true, []],
  ]);
  const deep = agentBranches([run("turn", "completed", now - 900), job("j_a", "turn", now - 800), job("j_a1", "j_a", now - 700),
    job("j_b", "turn", now - 900 + 50)]).tree();
  // j_a has a later sibling (j_b), so the line at depth 1 runs past j_a's children.
  assert.deepEqual(deep.map(row => [row.item.execution_id, row.guides]), [["j_a", []], ["j_a1", [1]], ["j_b", []]]);
});

const viewSessions = [run("turn", "reconciliation_required", now - 3 * DAY, { task_label: "check and fix it" }), spawned,
  run("done", "completed", now - 600, { task_label: "what happened", terminal_at: now - 500 }),
  run("j_done", "completed", now - 550, { parent_execution_id: "done", display: { kind: "job_agent", label: "Research" } }),
  run("j_read", "completed", now - 520, { parent_execution_id: "j_done", display: { kind: "job_agent", label: "Read_pages" } })];

async function withView(view, body) {
  setActivityView(view);
  try { await body(); } finally { setActivityView(DEFAULT_ACTIVITY_VIEW); }
}

test("showing what waits for you keeps the branches above it and lights the menu button", async () => {
  const waiting = run("j_wait", "paused", now - 510, { parent_execution_id: "j_done", display: { kind: "job_agent", label: "Book_hotel" } });
  await withView({ show: "attention" }, () => mounted([...viewSessions, waiting], async (host, click) => {
    await click("Main agent");
    const text = host.textContent;
    assert.match(text, /Sub-agentsResearch.*1Book hotel/s);
    assert.doesNotMatch(text, /Read pages|Fix page close/);
    assert.equal(host.querySelector("[data-view-changed]").getAttribute("data-view-changed"), "1");
  }, [], {}, { calls: [agentCall] }));
});

test("arranged by time the agents are one list, latest first, each naming who started it", async () => {
  await withView({ arrange: "time" }, () => mounted(viewSessions, async (host, click) => {
    await click("Main agent");
    const text = host.textContent;
    assert.match(text, /Sub-agents.*Read pagesCompleted · .* · by Research.*ResearchCompleted · .* · by Main agent.*Fix page closeInterrupted · .* · by Main agent/s);
    assert.equal(host.querySelectorAll("[data-last]").length, 0, "no tree lines");
  }, [], {}, { calls: [agentCall] }));
});

test("a filter with nothing to show says so and keeps the menu reachable", async () => {
  await withView({ show: "running" }, () => mounted(viewSessions, async (host, click) => {
    await click("Main agent");
    assert.match(host.textContent, /Sub-agentsNo sub-agent is running\./);
    assert.ok(host.querySelector("[aria-label='Show and arrange agents']"));
  }, [], {}, { calls: [agentCall] }));
});

test("a pruned tree redraws its lines for the rows that are left", async () => {
  const { agentBranches, pruneBranches } = await import("../../lib/execution/activity-model.ts");
  const job = (id, parent, at) => run(id, "completed", at, { parent_execution_id: parent, display: { kind: "job_agent", label: id } });
  const rows = agentBranches([run("turn", "completed", now - 900), job("j_a", "turn", now - 800), job("j_a1", "j_a", now - 700),
    job("j_a2", "j_a", now - 600), job("j_b", "turn", now - 500)]).tree();
  const kept = pruneBranches(rows, row => row.item.execution_id === "j_a1");
  assert.deepEqual(kept.map(row => [row.item.execution_id, row.depth, row.last, row.guides]), [
    ["j_a", 1, true, []],
    ["j_a1", 2, true, []],
  ]);
  const two = pruneBranches(rows, row => ["j_a1", "j_b"].includes(row.item.execution_id));
  assert.deepEqual(two.map(row => [row.item.execution_id, row.last, row.guides]), [["j_b", false, []], ["j_a", true, []], ["j_a1", true, []]]);
});

test("a sub-agent waiting on a question shows it and goes to the chat's card to answer", async () => {
  const decision = { id: "q1", sessionId: "session", executionId: "j_ask", waitGeneration: 1, expectedVersion: 1, kind: "ask",
    prompt: "Which venue should I book?", options: ["Hotel A", "Hotel B"], multi: false, allow_custom: true };
  useSessionStore.setState({ pendingDecisions: [decision] });
  const card = document.createElement("section");
  card.setAttribute("data-decision-output", "q1");
  const choice = document.createElement("button"); choice.textContent = "Hotel A"; card.append(choice);
  choice.focus = () => { card.dataset.focused = "Hotel A"; };
  card.scrollIntoView = () => { card.dataset.scrolled = "1"; };
  document.body.append(card);
  try {
    await mounted([run("turn", "completed", now - 600), run("j_ask", "paused", now - 300, { parent_execution_id: "turn", display: { kind: "job_agent", label: "Book_hotel" } })],
    async (host, click) => {
      assert.match(host.textContent, /Agents1Main agent\S+ · 1 sub-agent/);
      await click("Main agent");
      // Waiting, a sub-agent carries the red count; its page says what it waits on.
      assert.match(host.textContent, /1Book hotel\d\d:\d\d/);
      await click("Book hotel");
      assert.match(host.textContent, /Book hotelWaiting for your answerWaiting for your answerWhich venue should I book\?Choices: Hotel A · Hotel BAnswer in chat/);
      await click("Answer in chat");
      assert.equal(card.dataset.scrolled, "1");
      assert.equal(card.dataset.focused, "Hotel A");
    });
  } finally { card.remove(); useSessionStore.setState({ pendingDecisions: [] }); }
});

test("a run page selects its run once, not again each time the list polls", async () => {
  // Every refresh rebuilds `selectExecution`; re-selecting would reset
  // the inspector to "reconnecting" and drop its progress events.
  const selected = [];
  const controller = (selectedExecutionId) => ({ executions: [run("latest", "completed", now - DAY, { task_label: "prepare the visa form" })], branches: [],
    connection: { state: "connected" }, fetchedAt: 1, selectedExecutionId, selectExecution(id) { selected.push(id); } });
  globalThis.activityController = controller(null);
  globalThis.activityProcesses = { items: [], calls: [], stale: false, loaded: true, refresh() {} };
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  try {
    const render = () => act(async () => root.render(createElement(RunningPanel, { active: true, sessionId: "session" })));
    await render();
    const click = async text => {
      const button = [...host.querySelectorAll("button, [role=button]")].find(b => b.textContent.includes(text));
      assert.ok(button, text);
      await act(async () => button.click());
    };
    await click("Main agent");
    await click("prepare the visa form");
    assert.deepEqual(selected, ["latest"]);
    // Two polls: the hook now reports the run as selected and hands out
    // a fresh `selectExecution` each time.
    globalThis.activityController = controller("latest"); await render();
    globalThis.activityController = controller("latest"); await render();
    assert.deepEqual(selected, ["latest"]);
    // Only a run page whose run is not yet selected asks again.
    globalThis.activityController = controller("other"); await render();
    assert.deepEqual(selected, ["latest", "latest"]);
  } finally { await act(async () => root.unmount()); host.remove(); }
});

test("a program shows its description, progress and live output", async () => {
  await mounted([], async (host, click) => {
    assert.match(host.textContent, /Evaluate 100 samplespython eval\.py45 \/ 100 samples · 3\.4\/s16s left/);
    assert.ok(host.querySelector('[role="progressbar"][aria-valuenow="45"]'));
    await click("Evaluate 100 samples");
    assert.match(host.textContent, /45 \/ 100 samples45%/);
    assert.match(host.textContent, /Elapsed\d+sSpeed3\.4\/sLeft16s/);
  }, [{
    id: "proc", command: "python eval.py", title: "Evaluate 100 samples", status: "running", started_at: now - 13, backend_id: "local",
    progress: { source: "marker", state: "normal", current: 45, total: 100, label: "samples", rate: 3.4, eta: 16, updated_at: now },
  }]);
});

test("each branch the reader made is a main agent of its own, with its runs and sub-agents", async () => {
  globalThis.runtimeStateStub._branchesByConv.session = [
    { head_msg_id: "h_main", name: "main", active: true },
    { head_msg_id: "h_alt", name: "Try another wording", active: false },
  ];
  try {
    await mounted([
      run("turn", "completed", now - 600, { terminal_at: now - 500 }),
      run("j_research", "completed", now - 580, { parent_execution_id: "turn", display: { kind: "job_agent", label: "Research" } }),
      run("alt", "running", now - 60),
    ], async (host, click) => {
      // One row per branch, the checked-out one tagged; each sums up only its own sub-agents.
      assert.match(host.textContent, /AgentsmainCurrent\S+ · 1 sub-agentTry another wordingRunning · 1 min/);
      assert.doesNotMatch(host.textContent, /Main agent/);
      await click("Try another wording");
      let text = host.textContent;
      assert.match(text, /Branch.*Try another wording.*Running.*Switch to this branch.*No sub-agents yet\./s);
      await click("Switch to this branch");
      assert.deepEqual(globalThis.sentCommands.map(c => [c.action, c.head_msg_id]), [["checkout_branch", "h_alt"], ["load_session", undefined]]);
      await click("Activity");
      await click("main");
      text = host.textContent;
      assert.match(text, /Branch · Current.*main.*Sub-agents.*Research/s);
      assert.doesNotMatch(text, /Switch to this branch/);
    }, [], { branches: [
      { branch_id: "session:h_main", session_id: "session", head_msg_id: "h_main", name: "main", execution_ids: ["turn"] },
      { branch_id: "session:h_alt", session_id: "session", head_msg_id: "h_alt", name: "Try another wording", execution_ids: ["alt"] },
    ] });
  } finally { delete globalThis.runtimeStateStub._branchesByConv.session; }
});
