"use client";

/** An Agent's time chart. React draws the blocks; where they sit is written
 *  straight on the elements, because it follows every frame of a sideways
 *  scroll. A block with more under it leads one column right; a block that
 *  is one call or one message opens its details in place. */
import { useCallback, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type KeyboardEvent, type MouseEvent, type RefObject } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { availableExecutionActions, buildExecutionCommand, newCommandId, type ExecutionCommandAction, type ExecutionSnapshot } from "@/lib/execution/execution-debugger";
import type { ActivityRun } from "@/lib/net/execution/activity-runs-client";
import { processIsActive } from "@/lib/net/execution/process-client";
import type { ActivityPanelContext } from "./activity-page-types";
import { ActivityKeyValue, ActivityRowStoreReact, createActivityRowStore } from "./activity-page-row";
import { stepTitle } from "./activity-run-wording";
import { COLUMN_WIDTH, HEADER_HEIGHT, LEVELS, buildChart, columnStop, easeInOut, pageStop, readableInput, forEachNode, heightAt, levelAt, opensInPlace, paintColor, rootHeight, sizeChart, type ChartNode, type ChartRoot } from "./agent-chart-model";
import { useExecutionControls } from "./execution-controls";
import { EventDetail } from "./run-insides";
import { useActivityRuns } from "./use-activity-runs";
import { useRunInspection } from "./use-run-inspection";
import styles from "./agent-chart.module.css";

const TRAVEL_MS = 620;
/** How long the wheel stays quiet before a sideways scroll settles on a column. */
const SETTLE_MS = 160;
/** How far a sideways swipe goes before it turns the column. */
const SWIPE_TURNS = 48;
const NO_ROWS_OPEN = () => false;

interface AgentChartProps {
  head: string | null;
  context: ActivityPanelContext;
  box: RefObject<HTMLDivElement | null>;
  reportName: (run: ActivityRun) => string | null;
  nextWake: { at: number; line: string } | null;
  onOpenNextWake: () => void;
}

const LIVE_ACTIONS: readonly ExecutionCommandAction[] = ["pause", "continue", "cancel"];

function RunActions({ snapshot, context }: { snapshot: ExecutionSnapshot; context: ActivityPanelContext }) {
  const { text, connected } = context;
  const inspection = useRunInspection(snapshot, context.sessionId, context.active);
  const controls = useExecutionControls(snapshot, inspection, context);
  const [writing, setWriting] = useState(false);
  const [instruction, setInstruction] = useState("");
  const decision = context.waitingFor(snapshot);
  const available = availableExecutionActions(snapshot);
  const labels: Partial<Record<ExecutionCommandAction, string>> = { pause: text("Pause", "暂停"), continue: text("Continue", "继续"), cancel: text("Cancel", "取消") };
  const hold = (event: MouseEvent) => event.stopPropagation();
  const send = () => {
    const message = instruction.trim();
    if (!message || !connected) return;
    void controls.submit(buildExecutionCommand(snapshot, "steer", newCommandId(), { message }));
    setInstruction("");
    setWriting(false);
  };
  const onKey = (event: KeyboardEvent<HTMLInputElement>) => {
    event.stopPropagation();
    if (event.key === "Enter") send();
    if (event.key === "Escape") setWriting(false);
  };
  if (writing) {
    return <span className={styles.actions} onClick={hold}>
      <Input autoFocus className={styles.steer} value={instruction} aria-label={text("Add instruction", "补充指令")} placeholder={text("Applied at the next safe point", "在下一个安全点生效")}
        onChange={event => setInstruction(event.target.value)} onKeyDown={onKey} onBlur={() => { if (!instruction.trim()) setWriting(false); }} />
    </span>;
  }
  const rejected = Object.values(controls.commandResults).some(result => result.status === "rejected");
  if (rejected) return <span className={styles.actions}><span className={styles.line}>{text("That did not go through.", "没有生效。")}</span></span>;
  const action = (key: string, label: string, onClick: () => void, busy = false) =>
    <Button key={key} type="button" variant="ghost" className={styles.action} disabled={!connected || busy} onClick={event => { event.stopPropagation(); onClick(); }}>{label}</Button>;
  return <span className={styles.actions}>
    {decision?.answerLabel ? action("answer", decision.answerLabel, () => context.answerInChat(snapshot)) : null}
    {decision ? null : <>
      {LIVE_ACTIONS.slice(0, 2).filter(item => available.includes(item)).map(item => action(item, labels[item]!, () => controls.run(item), controls.pendingActions.has(`execution.${item}`)))}
      {available.includes("steer") ? action("steer", text("Add instruction", "补充指令"), () => setWriting(true)) : null}
      {available.includes("cancel") ? action("cancel", labels.cancel!, () => controls.run("cancel"), controls.pendingActions.has("execution.cancel")) : null}
    </>}
  </span>;
}

/** What a block with no next column shows when it is opened: the same words
 *  the run list gives the event. Its height is reported so the chart makes room. */
function BlockInsides({ node, context, onMeasure }: { node: ChartNode; context: ActivityPanelContext; onMeasure: (id: string, height: number) => void }) {
  const { text } = context;
  const element = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const box = element.current;
    if (!box) return;
    const measure = () => onMeasure(node.id, box.offsetHeight);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    return () => observer.disconnect();
  }, [node.id, onMeasure]);
  const { event, run } = node;
  // Text here is for reading and copying, so a click in it leaves the block open.
  return <div ref={element} className={styles.insides} onClick={click => click.stopPropagation()}>
    {event?.kind === "subagent" ? <>
      {event.brief.trim() ? <ActivityKeyValue label={text("Asked", "提问")} value={event.brief} /> : null}
      {event.error?.trim() ? <ActivityKeyValue label={text("Error", "报错")} value={event.error} /> : null}
      {event.result?.trim() ? <ActivityKeyValue label={text("Reply", "回复")} value={event.result} /> : null}
    </> : event?.kind === "step" ? <>
      {readableInput(event.input) ? <ActivityKeyValue label={text("Input", "输入")} value={readableInput(event.input)} mono /> : null}
      {event.result?.trim() ? <ActivityKeyValue label={event.failed ? text("Error", "报错") : text("Result", "结果")} value={event.result.trim()} mono /> : null}
      {!readableInput(event.input) && !event.result?.trim() ? <ActivityKeyValue label="" value={text("No input and no result.", "没有输入，也没有结果。")} /> : null}
    </> : event ? <EventDetail event={event} context={context} />
      : run ? <>
        {run.asked_preview.trim() ? <ActivityKeyValue label={text("Asked", "提问")} value={run.asked_preview} /> : null}
        {run.reply.trim() ? <ActivityKeyValue label={text("Reply", "回复")} value={run.reply} /> : null}
      </> : null}
  </div>;
}

function Block({ node, context, executionOf, open, onOpen, onBack, onMeasure }: {
  node: ChartNode; context: ActivityPanelContext; executionOf: (run: ActivityRun) => ExecutionSnapshot | null; open: boolean;
  onOpen: (node: ChartNode) => void; onBack: () => void; onMeasure: (id: string, height: number) => void;
}) {
  const travels = Boolean(node.kids?.length);
  const acts = travels || opensInPlace(node);
  const snapshot = node.hasActions && node.run ? executionOf(node.run) : null;
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === "ArrowLeft") { event.preventDefault(); onBack(); return; }
    if (event.key === "Enter" || event.key === " " || (travels && event.key === "ArrowRight")) { event.preventDefault(); onOpen(node); }
  };
  return <div className={styles.block} data-chart-id={node.id} data-small={node.depth >= 2 ? "1" : undefined} data-open={open ? "1" : undefined}
    {...acts ? { role: "button", tabIndex: -1, "data-row-id": node.id, onClick: () => onOpen(node), onKeyDown } : {}}
    {...acts && !travels ? { "aria-expanded": open } : {}}>
    <span className={styles.time}>{node.time}</span>
    <span className={styles.rail}><i className={styles.bar} data-bar="1" style={{ background: paintColor(node.paint) }} /></span>
    <span className={styles.card}><span className={styles.label}>
      {node.title ? <span className={styles.title}>{node.title}</span> : null}
      <span className={styles.line} data-strong={node.strong ? "1" : undefined}>{node.line}</span>
      {node.detail && !open ? <span className={styles.detail}>{node.detail}</span> : null}
      {snapshot ? <RunActions snapshot={snapshot} context={context} /> : null}
    </span>{open ? <BlockInsides node={node} context={context} onMeasure={onMeasure} /> : null}</span>
  </div>;
}

/** The chart's elements, found once per chart: a frame of a sideways scroll
 *  writes to all of them, and looking them up again cost more than the writes. */
interface ChartParts {
  blocks: Map<string, HTMLElement>;
  bars: Map<string, HTMLElement>;
  cells: Map<string, HTMLElement>;
  others: Map<string, HTMLElement[]>;
  columnElements: HTMLElement[];
  crumbs: HTMLElement[];
}

function findParts(content: HTMLElement): ChartParts {
  const all = (selector: string) => [...content.querySelectorAll<HTMLElement>(selector)];
  const blocks = new Map(all("[data-chart-id]").map(element => [element.dataset.chartId!, element]));
  const bars = new Map<string, HTMLElement>();
  blocks.forEach((element, id) => { const bar = element.querySelector<HTMLElement>("[data-bar]"); if (bar) bars.set(id, bar); });
  const others = new Map<string, HTMLElement[]>();
  all("[data-chart-root]").forEach(element => others.set(element.dataset.chartRoot!, [...others.get(element.dataset.chartRoot!) ?? [], element]));
  return { blocks, bars, others, cells: new Map(all("[data-chart-cell]").map(element => [element.dataset.chartCell!, element])), columnElements: all("[data-chart-column]"), crumbs: all("[data-chart-crumb]") };
}

export function AgentChart({ head, context, box, reportName, nextWake, onOpenNextWake }: AgentChartProps) {
  const { text, now } = context;
  const source = useMemo(() => ({ kind: "branch" as const, head }), [head]);
  const { runs, total, loaded, failed, showMore } = useActivityRuns({ sessionId: context.sessionId, source, active: context.active, isOpen: NO_ROWS_OPEN, openVersion: 0, chart: true });
  const executionOf = useCallback((run: ActivityRun) => run.execution_id ? context.controller.executions.find(item => item.execution_id === run.execution_id) ?? null : null, [context.controller.executions]);
  const waiting = runs.some(run => { const snapshot = executionOf(run); return snapshot ? context.waitingFor(snapshot) !== null : false; });
  const anyLive = waiting || runs.some(run => run.ended_at === null);
  // Text and bars move only every few seconds while something runs, never while idle.
  const beat = anyLive ? Math.floor(now / 5) * 5 : 0;
  const roots = useMemo<ChartRoot[]>(() => buildChart(runs, {
    text, now: anyLive ? beat : now,
    waitOf: run => { const snapshot = executionOf(run); return snapshot ? context.waitingFor(snapshot) : null; },
    hasActions: run => executionOf(run) !== null,
    liveCalls: run => {
      if (!run.execution_id || run.ended_at !== null) return [];
      const saved = new Set((run.steps ?? []).flatMap(event => event.kind === "step" && event.tool_call_id ? [event.tool_call_id] : []));
      const calls = (context.processes.calls ?? []).filter(call => call.execution_id === run.execution_id && call.status === "running" && call.name !== "agent" && !(call.tool_call_id && saved.has(call.tool_call_id)))
        .map(call => ({ id: call.id, at: call.started_at, label: call.description || stepTitle(call.name, undefined, text) }));
      const programs = context.processes.items.filter(item => item.execution_id === run.execution_id && processIsActive(item) && item.status !== "unknown")
        .map(item => ({ id: item.id, at: item.started_at, label: item.title?.trim() || item.command.trim() }));
      return [...calls, ...programs];
    },
    reportName, nextWake, earlier: Math.min(50, total - runs.length),
    // `now` is `beat` while anything runs; while idle a new render needs no new chart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [runs, total, beat, waiting, text, executionOf, nextWake?.at, nextWake?.line, context.processes.calls, context.processes.items]);

  const inner = useRef<HTMLDivElement>(null);
  const pin = useRef<{ node: ChartNode; view: number } | null>(null);
  const travel = useRef(0);
  const frame = useRef(0);
  const moving = useRef(false);
  const settling = useRef(0);
  const parts = useRef<ChartParts | null>(null);
  const rootsNow = useRef(roots);
  rootsNow.current = roots;
  // Which blocks are open, and how tall each one's details measured.
  const [store] = useState(createActivityRowStore);
  useSyncExternalStore(store.subscribe, store.version, store.version);
  const extras = useRef(new Map<string, number>());
  const applyExtras = useCallback(() => {
    for (const root of rootsNow.current) if (root.kind === "topic") forEachNode(root.node, node => { node.extra = extras.current.get(node.id) ?? 0; });
    sizeChart(rootsNow.current);
  }, []);

  const layout = useCallback(() => {
    const scroller = box.current;
    const content = inner.current;
    if (!scroller || !content) return;
    const place = (element: HTMLElement | undefined, top: number, height: number) => { if (element) { element.style.top = `${top}px`; element.style.height = `${height}px`; } };
    const { blocks, bars, cells, others, columnElements, crumbs } = parts.current ??= findParts(content);
    // Read the box before any write below, or each read costs a layout.
    const width = scroller.clientWidth || 0;
    const view = scroller.clientHeight || 0;
    const level = levelAt(scroller.scrollLeft || 0, width);
    const columns: ChartNode[][] = Array.from({ length: LEVELS }, () => []);
    for (const root of rootsNow.current) if (root.kind === "topic") forEachNode(root.node, node => columns[node.depth].push(node));

    // The block the reader is looking at stays where it is while heights change.
    const held = pin.current;
    let anchor: ChartNode | undefined = held?.node;
    let fraction = 0;
    if (!anchor) {
      const at = scroller.scrollTop;
      anchor = columns[Math.min(LEVELS - 1, Math.round(level))].filter(node => node.depth < LEVELS - 1 && node.height > 0).find(node => node.top + node.height > at);
      if (anchor) fraction = (at - anchor.top) / anchor.height;
    }

    const placeNode = (node: ChartNode, top: number): number => {
      const height = heightAt(node, level);
      const moved = node.top !== top || node.height !== height;
      node.top = top; node.height = height;
      if (moved) {
        place(blocks.get(node.id), top, height);
        const bar = bars.get(node.id);
        if (bar) bar.style.height = `${Math.max(2, height - 6)}px`;
      }
      if (!node.kids) return height;
      if (node.depth === LEVELS - 2) {
        const cell = cells.get(node.id);
        if (moved) place(cell, top, height);
        let below = 0;
        for (const kid of node.kids) below += placeNode(kid, below);
        if (cell) {
          const scrolls = level > LEVELS - 1.02 && below > height + 1;
          // Setting scrollTop lays the page out, so only a cell that did scroll is reset.
          if (scrolls) cell.dataset.scrolls = "1";
          else if (cell.dataset.scrolls) { delete cell.dataset.scrolls; cell.scrollTop = 0; }
        }
        return height;
      }
      let below = top;
      for (const kid of node.kids) below += placeNode(kid, below);
      return height;
    };

    let y = HEADER_HEIGHT;
    for (const root of rootsNow.current) {
      if (root.kind === "topic") { y += placeNode(root.node, y); continue; }
      const height = rootHeight(root);
      others.get(root.id)?.forEach(element => place(element, y, height));
      if (root.kind === "next") { const bar = others.get(root.id)?.[0]?.querySelector<HTMLElement>("[data-bar]"); if (bar) bar.style.height = `${height - 6}px`; }
      y += height;
    }
    content.style.height = `${y + 12}px`;
    columnElements.forEach(column => { column.style.height = `${y}px`; });
    if (width > 0) content.style.paddingRight = width < 2 * COLUMN_WIDTH ? `${width - COLUMN_WIDTH}px` : "0px";
    if (anchor) scroller.scrollTop = held ? anchor.top - held.view : anchor.top + fraction * anchor.height;

    const at = scroller.scrollTop;
    // Only blocks near the view are drawn: a long chart has hundreds a screen away.
    if (view > 0) {
      const show = (element: HTMLElement | undefined, node: ChartNode) => {
        if (!element) return;
        const display = node.top < at + 2 * view && node.top + node.height > at - view ? "" : "none";
        if (element.style.display !== display) element.style.display = display;
      };
      for (let depth = 0; depth < LEVELS - 1; depth += 1) for (const node of columns[depth]) show(blocks.get(node.id), node);
      for (const node of columns[LEVELS - 2]) if (node.kids) show(cells.get(node.id), node);
    }
    // A column on its way in fades in as its blocks open, instead of showing them stacked.
    const arriving = level % 1;
    columnElements.forEach((column, depth) => {
      const opacity = arriving > 0 && depth === Math.floor(level) + 1 ? String(arriving * arriving) : "";
      if (column.style.opacity !== opacity) column.style.opacity = opacity;
    });
    crumbs.forEach(crumb => {
      const list = columns[Number(crumb.dataset.chartCrumb)];
      const top = list.find(node => node.top + node.height > at + HEADER_HEIGHT);
      const name = top?.parent ? top.parent.title ?? top.parent.line : "";
      if (crumb.textContent !== name) crumb.textContent = name;
    });
  }, [box]);

  useLayoutEffect(() => { parts.current = null; if (extras.current.size) applyExtras(); layout(); }, [roots, layout, applyExtras]);
  const onMeasure = useCallback((id: string, height: number) => {
    if (!store.has(id) || extras.current.get(id) === height) return;
    extras.current.set(id, height);
    applyExtras();
    layout();
  }, [store, applyExtras, layout]);
  const moveTo = useCallback((target: number, held: ChartNode | null) => {
    const scroller = box.current;
    if (!scroller) return;
    const from = scroller.scrollLeft;
    const to = Math.max(0, Math.min(target, scroller.scrollWidth - scroller.clientWidth));
    if (Math.abs(to - from) < 1) return;
    const token = ++travel.current;
    moving.current = true;
    window.clearTimeout(settling.current);
    pin.current = held ? { node: held, view: held.top - scroller.scrollTop } : null;
    const still = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    // A full column takes the whole time; the last few pixels of a settle don't.
    const duration = TRAVEL_MS * Math.min(1, 0.4 + 0.6 * Math.abs(to - from) / COLUMN_WIDTH);
    const started = performance.now();
    const step = (time: number) => {
      if (token !== travel.current) return;
      const progress = still ? 1 : Math.min(1, Math.max(0, time - started) / duration);
      scroller.scrollLeft = from + (to - from) * easeInOut(progress);
      layout();
      if (progress < 1) requestAnimationFrame(step); else { pin.current = null; moving.current = false; }
    };
    requestAnimationFrame(step);
  }, [box, layout]);

  useLayoutEffect(() => {
    const scroller = box.current;
    if (!scroller) return;
    let lastLeft = scroller.scrollLeft;
    let gestureFrom: number | null = null;
    const onScroll = () => {
      if (!frame.current) frame.current = requestAnimationFrame(() => { frame.current = 0; layout(); });
      const left = scroller.scrollLeft;
      if (left === lastLeft) return;
      if (moving.current || swipe) { lastLeft = left; return; }
      gestureFrom ??= lastLeft;
      lastLeft = left;
      // Still scrolling holds the chart where it is; once the wheel goes quiet it settles on a column.
      window.clearTimeout(settling.current);
      settling.current = window.setTimeout(() => {
        const from = gestureFrom ?? scroller.scrollLeft;
        gestureFrom = null;
        moveTo(columnStop(scroller.scrollLeft, from, scroller.scrollWidth - scroller.clientWidth), null);
      }, SETTLE_MS);
    };
    // A sideways swipe turns one column, like a page: the chart follows the
    // hand until the swipe has gone far enough, then travels to the next
    // column, and what is left of the swipe and its momentum moves nothing.
    let swipe: { from: number; sum: number; turned: boolean; peak: number; low: number } | null = null;
    let quiet = 0;
    let target = scroller.scrollLeft;
    const onWheel = (event: WheelEvent) => {
      if (Math.abs(event.deltaX) <= Math.abs(event.deltaY)) return;
      event.preventDefault();
      window.clearTimeout(quiet);
      window.clearTimeout(settling.current);
      const size = Math.abs(event.deltaX);
      // A swipe rises once and then fades, momentum included, so one that has
      // faded and grows again is a new swipe.
      if (swipe?.turned && swipe.low < swipe.peak * 0.6 && size > swipe.low * 1.5 && size > swipe.low + 8) swipe = null;
      if (!swipe) {
        const from = moving.current ? target : scroller.scrollLeft;
        travel.current += 1; moving.current = false; pin.current = null;
        swipe = { from, sum: 0, turned: false, peak: size, low: size };
      }
      if (size > swipe.peak) { swipe.peak = size; swipe.low = size; } else swipe.low = Math.min(swipe.low, size);
      if (!swipe.turned) {
        swipe.sum += event.deltaX;
        const max = scroller.scrollWidth - scroller.clientWidth;
        if (Math.abs(swipe.sum) >= SWIPE_TURNS) { swipe.turned = true; target = pageStop(swipe.from, swipe.sum, max); moveTo(target, null); }
        else scroller.scrollLeft = swipe.from + swipe.sum;
      }
      quiet = window.setTimeout(() => {
        const ended = swipe;
        swipe = null;
        if (ended && !ended.turned) moveTo(ended.from, null);
      }, SETTLE_MS);
    };
    scroller.addEventListener("scroll", onScroll);
    scroller.addEventListener("wheel", onWheel, { passive: false });
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(layout);
    observer?.observe(scroller);
    return () => {
      scroller.removeEventListener("scroll", onScroll);
      scroller.removeEventListener("wheel", onWheel);
      observer?.disconnect();
      cancelAnimationFrame(frame.current);
      window.clearTimeout(settling.current);
      window.clearTimeout(quiet);
      frame.current = 0; travel.current += 1; moving.current = false;
    };
  }, [box, layout, moveTo]);

  const open = useCallback((node: ChartNode) => {
    if (node.kids?.length) { moveTo((node.depth + 1) * COLUMN_WIDTH, node); return; }
    if (!opensInPlace(node)) return;
    store.toggle(node.id);
    if (store.has(node.id) || !extras.current.delete(node.id)) return;
    applyExtras();
    layout();
  }, [moveTo, store, applyExtras, layout]);
  const back = useCallback(() => { const scroller = box.current; if (scroller) moveTo(scroller.scrollLeft - COLUMN_WIDTH, null); }, [box, moveTo]);

  const names = [text("Topics", "话题"), text("Messages", "消息"), text("Steps", "步骤"), text("Inside a step", "步骤里面")];
  const nodes: ChartNode[][] = Array.from({ length: LEVELS }, () => []);
  for (const root of roots) if (root.kind === "topic") forEachNode(root.node, node => nodes[node.depth].push(node));
  const block = (node: ChartNode) => <Block key={node.id} node={node} context={context} executionOf={executionOf} open={store.has(node.id)} onOpen={open} onBack={back} onMeasure={onMeasure} />;
  const others = roots.filter((root): root is Exclude<ChartRoot, { kind: "topic" }> => root.kind !== "topic");

  return <ActivityRowStoreReact.Provider value={store}><div ref={box as RefObject<HTMLDivElement>} className={styles.cols}>
    <div ref={inner} className={styles.inner}>
      {names.map((name, depth) => <div key={name} className={styles.col} data-chart-column="1">
        <div className={styles.ch}><span>{name}</span>{depth > 0 ? <span className={styles.crumb} data-chart-crumb={depth} /> : null}</div>
        {depth < LEVELS - 1 ? nodes[depth].map(block) : nodes[LEVELS - 2].filter(node => node.kids).map(node => <div key={node.id} className={styles.cell} data-chart-cell={node.id}>{node.kids!.map(block)}</div>)}
        {others.map(root => {
          if (root.kind === "gap") return <div key={root.id} className={`${styles.block} ${styles.gap}`} data-chart-root={root.id} data-small={depth >= 2 ? "1" : undefined}><span className={styles.day}>{root.day}</span><span className={styles.dash} /><span className={styles.line}>{depth === 0 ? root.idle : null}</span></div>;
          if (depth > 0) return null;
          if (root.kind === "more") return <div key={root.id} className={styles.block} data-chart-root={root.id}><span /><span /><span className={styles.more}><Button type="button" variant="ghost" className={styles.action} onClick={() => void showMore()}>{root.label}</Button></span></div>;
          return <div key={root.id} className={styles.block} data-chart-root={root.id} data-row-id={root.id} role="button" tabIndex={-1} onClick={onOpenNextWake}
            onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onOpenNextWake(); } }}>
            <span className={styles.time}>{root.time}</span>
            <span className={styles.rail}><i className={styles.bar} data-bar="1" data-next="1" /></span>
            <span className={styles.card}><span className={styles.label}><span className={styles.title}>{root.title}</span><span className={styles.line}>{root.line}</span></span></span>
          </div>;
        })}
      </div>)}
      {loaded && runs.length === 0 ? <div className={styles.empty} style={{ position: "absolute", top: HEADER_HEIGHT, left: 0, width: COLUMN_WIDTH }}>{failed ? text("Could not read the runs. Retrying automatically.", "读不到运行记录，正在自动重试。") : text("No runs yet.", "还没有运行记录。")}</div> : null}
    </div>
  </div></ActivityRowStoreReact.Provider>;
}
