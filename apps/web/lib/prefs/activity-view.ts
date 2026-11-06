/**
 * activity-view — how this browser shows the Activity panel: which agents
 * to show, how to arrange them, and which sections are folded. A view preference, so it
 * lives in localStorage like the sidebar's recents view; it falls back to
 * the defaults wherever storage is unavailable.
 */
import { useSyncExternalStore } from "react";

/** all: every agent · attention: the ones waiting on the reader ·
 *  running: the ones running now. */
export type ActivityShow = "all" | "attention" | "running";
/** structure: each sub-agent under the agent that started it ·
 *  time: one list, most recent activity first. */
export type ActivityArrange = "structure" | "time";

export interface ActivityView {
  show: ActivityShow;
  arrange: ActivityArrange;
  /** Keys of the overview sections folded to their header. */
  collapsed: string[];
}

export const DEFAULT_ACTIVITY_VIEW: ActivityView = { show: "all", arrange: "structure", collapsed: [] };

const KEY = "openprogram.activity-view";
const EVENT = "openprogram:activity-view";
let cached: ActivityView | null = null;

function read(): ActivityView {
  if (cached) return cached;
  let saved: Partial<ActivityView> = {};
  try {
    const raw = typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null;
    saved = raw ? JSON.parse(raw) as Partial<ActivityView> : {};
  } catch { saved = {}; }
  cached = {
    show: (["all", "attention", "running"] as const).includes(saved.show as ActivityShow) ? saved.show as ActivityShow : DEFAULT_ACTIVITY_VIEW.show,
    arrange: (["structure", "time"] as const).includes(saved.arrange as ActivityArrange) ? saved.arrange as ActivityArrange : DEFAULT_ACTIVITY_VIEW.arrange,
    collapsed: Array.isArray(saved.collapsed) ? saved.collapsed.filter(key => typeof key === "string") : DEFAULT_ACTIVITY_VIEW.collapsed,
  };
  return cached;
}

export function setActivityView(patch: Partial<ActivityView>): void {
  cached = { ...read(), ...patch };
  try { localStorage.setItem(KEY, JSON.stringify(cached)); } catch { /* the choice still holds for this page */ }
  if (typeof window !== "undefined") window.dispatchEvent(new Event(EVENT));
}

/** Fold or unfold one overview section. */
export function toggleActivitySection(key: string): void {
  const { collapsed } = read();
  setActivityView({ collapsed: collapsed.includes(key) ? collapsed.filter(item => item !== key) : [...collapsed, key] });
}

function subscribe(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  const onStorage = (event: StorageEvent) => { if (event.key === KEY) { cached = null; onChange(); } };
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => { window.removeEventListener(EVENT, onChange); window.removeEventListener("storage", onStorage); };
}

export function useActivityView(): ActivityView {
  return useSyncExternalStore(subscribe, read, () => DEFAULT_ACTIVITY_VIEW);
}
