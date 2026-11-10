// What an Agent's time chart draws, without a page around it.
import assert from "node:assert/strict";
import test from "node:test";
import { buildChart, columnStop, forEachNode, heightAt, levelAt, opensInPlace, pageStop, paintColor, readableInput, sizeChart, LEVELS } from "../../components/right-sidebar/running/agent-chart-model.ts";

const NOW = 1_794_000_000;
const text = english => english;
const run = (id, started_at, extra = {}) => ({ id, message_id: id, user_message_id: `u_${id}`, execution_id: null, is_report: false, asked_by: "you", asked_preview: `asked ${id}`,
  reply: `Reply ${id}`, started_at, ended_at: started_at + 30, execution_status: null, message_status: "completed", reason_code: null, task_outcome: null, task_text: null, steps: [], ...extra });
const topic = (id, order, title = `Topic ${id}`) => ({ topic_id: id, topic_order: order, topic_title: title });
const step = (at, name, command, extra = {}) => ({ kind: "step", at, node_id: `${name}_${at}`, name, input: { command, path: command }, failed: false, result: null, ...extra });
const chart = (runs, extra = {}) => buildChart(runs, { text, now: NOW, waitOf: () => null, hasActions: () => false, liveCalls: () => [], reportName: () => null, nextWake: null, earlier: 0, ...extra });
const topics = roots => roots.filter(root => root.kind === "topic").map(root => root.node);
const hueOf = node => node.paint.hue;

test("a topic that comes back is drawn again in its own colour", () => {
  const roots = chart([run("c", NOW - 100, topic("t1", 0)), run("b", NOW - 200, topic("t2", 1)), run("a", NOW - 300, topic("t1", 0))]);
  const [newest, middle, oldest] = topics(roots);
  assert.equal(newest.title, "Topic t1");
  assert.equal(oldest.title, "Topic t1");
  assert.equal(paintColor(newest.paint), paintColor(oldest.paint));
  assert.notEqual(paintColor(newest.paint), paintColor(middle.paint));
});

test("messages are shades of their topic, steps shades of their message", () => {
  const runs = [run("b", NOW - 100, { ...topic("t1", 0), steps: [step(NOW - 95, "bash", "ls"), step(NOW - 90, "read", "a.py", { name: "read" })] }), run("a", NOW - 200, topic("t1", 0))];
  const [node] = topics(chart(runs));
  const [newer, older] = node.kids;
  assert.notEqual(paintColor(newer.paint), paintColor(older.paint));
  for (const message of node.kids) assert.ok(Math.abs(hueOf(message) - hueOf(node)) <= 10);
  for (const row of newer.kids) {
    assert.ok(Math.abs(hueOf(row) - hueOf(newer)) <= 4);
    assert.ok(row.paint.lift > newer.paint.lift);
  }
});

test("a failure keeps the topic's colour and says why under the step", () => {
  const failed = step(NOW - 90, "bash", "pytest", { failed: true, result: "2 tests timed out" });
  const [node] = topics(chart([run("a", NOW - 100, { ...topic("t1", 0), execution_status: "failed", steps: [failed] })]));
  const [message] = node.kids;
  assert.match(message.line, /^Failed · 30s$/);
  const [row] = message.kids;
  assert.match(row.line, /^Failed · /);
  assert.equal(row.detail, "2 tests timed out");
  assert.ok(!paintColor(row.paint).includes("#"));
  assert.equal(row.paint.order, node.paint.order);
});

test("a step that failed mid-run leaves a finished message plain", () => {
  const steps = [step(NOW - 95, "bash", "pytest", { failed: true, result: "no" }), step(NOW - 90, "bash", "pytest")];
  const [node] = topics(chart([run("a", NOW - 100, { ...topic("t1", 0), steps })]));
  assert.match(node.kids[0].line, /^30s · 1 step failed$/);
  assert.equal(node.kids[0].strong, false);
});

test("calls of one function in a row share a line, each call one column right", () => {
  const steps = Array.from({ length: 22 }, (_, index) => step(NOW - 90 + index, "bash", `cmd ${index}`));
  const [node] = topics(chart([run("a", NOW - 100, { ...topic("t1", 0), steps })]));
  const [group, ...others] = node.kids[0].kids;
  assert.equal(others.length, 0);
  assert.match(group.line, / · 22 commands$/);
  assert.equal(group.kids.length, 22);
  assert.equal(group.kids[0].depth, 3);
  assert.match(group.kids[0].line, /cmd 21/);
});

test("a failure splits the run of calls, so it stays in the Steps column", () => {
  const steps = [step(NOW - 95, "bash", "a"), step(NOW - 94, "bash", "b"), step(NOW - 93, "bash", "c", { failed: true, result: "x" }), step(NOW - 92, "bash", "d")];
  const [node] = topics(chart([run("a", NOW - 100, { ...topic("t1", 0), steps })]));
  assert.deepEqual(node.kids[0].kids.map(row => Boolean(row.kids)), [false, false, true]);
});

test("a sub-agent's own steps are one column right", () => {
  const agent = { kind: "subagent", at: NOW - 90, ended_at: NOW - 70, job_id: "j", name: "reviewer", status: "completed", never_started: false, failed: false, error: null, children: [], conversation: null,
    steps: [step(NOW - 88, "read", "settings.json"), { kind: "replied", at: NOW - 75, text: "No conflicts" }] };
  const [node] = topics(chart([run("a", NOW - 100, { ...topic("t1", 0), steps: [agent] })]));
  const [row] = node.kids[0].kids;
  assert.match(row.line, /Sub-agent · reviewer/);
  assert.equal(row.kids.length, 2);
  assert.match(row.kids[0].line, /^Replied: No conflicts/);
});

test("the question asked titles a message and the time is its latest moment", () => {
  const [node] = topics(chart([run("a", NOW - 100, topic("t1", 0))]));
  assert.equal(node.kids[0].title, "asked a");
  assert.equal(node.time, node.kids[0].time);
  assert.equal(node.kids[0].time, new Date((NOW - 70) * 1000).toTimeString().slice(0, 5));
});

test("an unsorted message joins the one before it, and with none before it waits", () => {
  let [node] = topics(chart([run("b", NOW - 100), run("a", NOW - 200, topic("t1", 0))]));
  assert.equal(node.title, "Topic t1");
  assert.equal(node.kids.length, 2);
  [node] = topics(chart([run("a", NOW - 200)]));
  assert.equal(node.title, "Not sorted yet");
  assert.equal(node.paint.order, null);
});

test("runs nobody asked for sit apart, in grey", () => {
  const roots = topics(chart([run("b", NOW - 100, { asked_by: "schedule" }), run("a", NOW - 200, topic("t1", 0))]));
  assert.deepEqual(roots.map(node => node.title), ["Automatic runs", "Topic t1"]);
  assert.match(paintColor(roots[0].paint), /oklch\([\d.]+ 0\.000/);
});

test("a long silence and a new day are marked across the columns", () => {
  const roots = chart([run("b", NOW - 100, topic("t1", 0)), run("a", NOW - 100 - 14 * 3600, topic("t1", 0))]);
  const gap = roots.find(root => root.kind === "gap" && root.id.startsWith("gap:"));
  assert.equal(gap.idle, "14h idle");
  assert.equal(typeof gap.day, "string", "a new day's date goes in the time column");
  assert.ok(gap.day.length <= 8, "short enough to stay left of the bars");
  assert.equal(topics(roots).length, 2);
});

test("running and waiting say what they are doing, and only they get actions", () => {
  const live = run("a", NOW - 125, { ...topic("t1", 0), ended_at: null, execution_id: "e", execution_status: "running", steps: [step(NOW - 60, "bash", "build")] });
  let [node] = topics(chart([live], { hasActions: () => true }));
  assert.match(node.kids[0].line, /^Running .* · 2m 5s$/);
  assert.equal(node.kids[0].hasActions, true);
  assert.match(node.line, /^Running · 1 message$/);
  [node] = topics(chart([live], { hasActions: () => true, waitOf: () => ({ waitLabel: "Waiting for your answer", question: "Overwrite it?" }) }));
  assert.equal(node.kids[0].line, "Waiting · Overwrite it?");
  assert.equal(node.line, "Waiting for your answer");
  [node] = topics(chart([run("a", NOW - 100, { ...topic("t1", 0), execution_status: "failed" })], { hasActions: () => true }));
  assert.equal(node.kids[0].hasActions, false);
});

test("the next wake is on top and earlier runs come last", () => {
  const roots = chart([run("a", NOW - 100, topic("t1", 0))], { nextWake: { at: NOW + 60, line: "Always-on · hourly" }, earlier: 50 });
  assert.equal(roots[0].kind, "next");
  assert.equal(roots.at(-1).label, "Show 50 earlier");
});

test("a parent is as tall as its children at every deeper level, so the columns line up", () => {
  const steps = Array.from({ length: 6 }, (_, index) => step(NOW - 90 + index * 5, index % 2 ? "bash" : "read", `c${index}`));
  const [node] = topics(chart([run("b", NOW - 300, { ...topic("t1", 0), steps }), run("a", NOW - 900, topic("t1", 0))]));
  for (let level = 1; level < LEVELS; level += 1) {
    const sum = node.kids.reduce((total, kid) => total + kid.heights[level], 0);
    assert.ok(Math.abs(sum - node.heights[level]) < 1, `level ${level}`);
  }
});

test("a group's calls are capped at four rows' height and scroll in their cell", () => {
  const steps = Array.from({ length: 22 }, (_, index) => step(NOW - 90 + index, "bash", `cmd ${index}`));
  const [node] = topics(chart([run("a", NOW - 100, { ...topic("t1", 0), steps })]));
  const group = node.kids[0].kids[0];
  assert.ok(group.heights[3] <= 120);
  forEachNode(group, kid => assert.ok(kid.heights[3] > 0));
});

test("height follows the sideways scroll between two levels", () => {
  const [node] = topics(chart([run("a", NOW - 100, { ...topic("t1", 0), steps: [step(NOW - 90, "bash", "x")] }), run("b", NOW - 900, topic("t1", 0))]));
  assert.equal(levelAt(0, 272), 0);
  assert.equal(levelAt(256, 272), 1);
  assert.equal(levelAt(5000, 272), 3);
  assert.equal(levelAt(32, 272), 0.5, "part-way only while a column arrives");
  assert.equal(levelAt(64, 272), 1, "a column that has arrived reads in full");
  assert.equal(levelAt(0, 480), 1, "a panel resting between two widths");
  assert.equal(levelAt(424, 600), 3, "a wide panel reaches the last level, where a long group scrolls");
  assert.equal(heightAt(node, 0.5), (node.heights[0] + node.heights[1]) / 2);
  assert.equal(heightAt(node, 3), node.heights[3]);
});

test("a sideways scroll settles on a column once it stops", () => {
  assert.equal(columnStop(40, 0, 768), 0, "not far enough falls back");
  assert.equal(columnStop(70, 0, 768), 256, "far enough carries on");
  assert.equal(columnStop(216, 256, 768), 256, "a little back returns");
  assert.equal(columnStop(180, 256, 768), 0, "far enough back goes back");
  assert.equal(columnStop(540, 0, 768), 512, "a long flick stops at the column it passed");
  assert.equal(columnStop(330, 0, 424), 424, "a wide panel's far end is a stop");
  assert.equal(columnStop(424, 0, 424), 424);
  assert.equal(columnStop(266, 0, 270), 270, "a short last step still reaches the end");
});

test("a block with a next column goes there, and any other block with something to say opens in place", () => {
  const steps = [step(NOW - 95, "bash", "ls"), step(NOW - 94, "bash", "pwd"), step(NOW - 90, "read", "a.py")];
  const live = { liveCalls: item => item.id === "b" ? [{ id: "c1", at: NOW - 80, label: "npm test" }] : [] };
  const [node] = topics(chart([run("b", NOW - 100, { ...topic("t1", 0), ended_at: null, steps }), run("a", NOW - 200, topic("t1", 0))], live));
  const [withSteps, plain] = node.kids;
  assert.equal(opensInPlace(node), false, "a topic leads to its messages");
  assert.equal(opensInPlace(withSteps), false, "a message with steps leads to them");
  assert.equal(opensInPlace(plain), true, "a message with no steps shows what was asked and replied");
  const [running, single, group] = withSteps.kids;
  assert.equal(opensInPlace(running), false, "a call still running has nothing to add yet");
  assert.equal(opensInPlace(single), true);
  assert.equal(opensInPlace(group), false);
  assert.ok(group.kids.every(opensInPlace), "each call of a group opens too");
});

test("opened details make the block taller, and every column to its left with it", () => {
  const steps = [step(NOW - 95, "bash", "ls"), step(NOW - 90, "read", "a.py"), step(NOW - 85, "bash", "pytest", { failed: true, result: "no" })];
  const roots = chart([run("a", NOW - 100, { ...topic("t1", 0), steps })]);
  const [node] = topics(roots);
  const [message] = node.kids;
  const [failed, read] = message.kids;
  const before = { topic: node.heights[2], message: message.heights[2], read: read.heights[2], failed: failed.heights[2], overview: node.heights[0] };
  read.extra = 140;
  sizeChart(roots);
  assert.equal(read.heights[2], before.read + 140);
  assert.equal(message.heights[2], before.message + 140);
  assert.equal(node.heights[2], before.topic + 140);
  assert.equal(node.heights[0], before.overview, "a column that does not show the block keeps its height");
  read.extra = 0;
  failed.extra = 90;
  sizeChart(roots);
  assert.equal(read.heights[2], before.read);
  assert.equal(failed.heights[2], before.failed - 38 + 90, "the details stand in for the error's two lines");
});

test("a group makes room for a call opened inside it", () => {
  const steps = Array.from({ length: 22 }, (_, index) => step(NOW - 90 + index, "bash", `cmd ${index}`));
  const roots = chart([run("a", NOW - 100, { ...topic("t1", 0), steps })]);
  const [group] = topics(roots)[0].kids[0].kids;
  const capped = group.heights[3];
  group.kids[0].extra = 200;
  sizeChart(roots);
  assert.equal(group.heights[3], capped + 200);
});

test("one sideways swipe turns one column, however hard it was thrown", () => {
  assert.equal(pageStop(0, 900, 768), 256);
  assert.equal(pageStop(256, 1, 768), 512);
  assert.equal(pageStop(512, -4000, 768), 256);
  assert.equal(pageStop(0, -1, 768), 0);
  assert.equal(pageStop(768, 1, 768), 768);
  assert.equal(pageStop(256, 1, 424), 424, "a wide panel's last step is short");
  assert.equal(pageStop(424, -1, 424), 256);
});

test("a call's input reads as what it was given, not as JSON", () => {
  assert.equal(readableInput({ command: "cp a b" }), "cp a b");
  assert.equal(readableInput({ path: "a.py", limit: 20, offset: null }), "path: a.py\nlimit: 20");
  assert.equal(readableInput({ edits: [{ old: "a" }] }), '[{"old":"a"}]');
  assert.equal(readableInput("plain"), "plain");
  assert.equal(readableInput({}), "");
  assert.equal(readableInput(null), "");
});
