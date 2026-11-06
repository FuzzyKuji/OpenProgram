import { flushSync } from 'react-dom';
import { convToChatMsgs } from '@/lib/chat/transcript/conv-mapper';
import { useSessionHistory, updateSessionHistory, type HistoryPage } from '@/lib/chat/history/session-history';
import { HistoryWindow, type HistoryDirection, type HistoryRow } from '@/lib/chat/history/history-window';
import { captureHistoryAnchor, captureAreaRestoreState, historyAreaStillOwned, isFollowLocked, restoreAreaWindow } from '@/lib/chat/history/history-viewport';
import { noteTakeLatest } from '@/lib/chat/history/chat-scroll';
import { clearHeights, retainRowHeights } from '@/lib/chat/history/message-window';
import { useSessionStore } from '@/lib/session-store';
import { wsRequest } from '@/lib/net/ws/ws-request';
import { getSocket, runtimeState } from '../state';

const windows = new Map<string, HistoryWindow>();
const viewports = new Map<string, Map<HTMLElement, string>>();
// The server keeps MAX_SNAPSHOTS_PER_CONNECTION (session_history.py) snapshots,
// more than this, so every retained window can keep paging its own snapshot.
const MAX_CACHED_SESSIONS = 4;

export function registerHistoryViewport(id: string, area: HTMLElement, chatKey: string): () => void {
  const areas = viewports.get(id) ?? new Map<HTMLElement, string>();
  areas.set(area,chatKey); viewports.set(id,areas);
  return () => { areas.delete(area); if (!areas.size) viewports.delete(id); trimHistoryWindows(); };
}

/** A split-view pane shows this session through its own windowed read. */
export function peerPresentsSession(id: string): boolean {
  for (const chatKey of viewports.get(id)?.values() ?? []) {
    if (chatKey.startsWith('peer:')) return true;
  }
  return false;
}

function trimHistoryWindows(protectedId?: string): void {
  for (const id of windows.keys()) {
    if (windows.size <= MAX_CACHED_SESSIONS) break;
    if (id===protectedId || viewports.has(id) || id===useSessionStore.getState().currentSessionId
        || useSessionHistory.getState().pages[id]?.loading) continue;
    windows.delete(id);
    const conv=runtimeState.conversations[id];
    if(conv){delete conv.messages;delete conv.graph;}
    const state=useSessionStore.getState();
    const live=(state.messageOrder[id]??[]).map(mid=>state.messagesById[mid]).filter(m=>m && ['running','streaming','pending','cancelling'].includes(m.status??''));
    state.setMessages(id,live);
    clearHeights(id);clearHeights(`peer:${id}`);
  }
}

// Removing a conversation or clearing the store releases every retained page.
useSessionStore.subscribe((state,previous)=>{
  for(const id of windows.keys()){
    if(previous.messageOrder[id] && !state.messageOrder[id]){
      windows.delete(id);clearHeights(id);clearHeights(`peer:${id}`);
      useSessionHistory.setState(s=>{const pages={...s.pages};delete pages[id];return {pages};});
    }
  }
});
export function seedHistoryWindow(id: string, messages: HistoryRow[], history?: HistoryPage): void {
  windows.delete(id);
  if (!history?.snapshot) return;
  const historyWindow = new HistoryWindow();
  historyWindow.add(messages, history, 'latest');
  windows.set(id, historyWindow);
  trimHistoryWindows(id);
}
export async function loadOlderSessionHistory(id: string): Promise<void> {
  await loadSessionHistoryWindow(id, 'older');
}

function readingAnchor(id: string): string | undefined {
  const area = viewports.get(id)?.keys().next().value
    ?? (runtimeState.currentSessionId === id ? document.getElementById('chatArea') : null);
  return area ? captureHistoryAnchor(area)?.id : undefined;
}
/** Re-read around what the reader sees, or the newest page when no transcript is on screen. */
export async function retrySessionHistory(id: string): Promise<boolean> {
  const anchor = readingAnchor(id);
  return anchor ? loadSessionHistoryWindow(id, 'around', anchor) : loadSessionHistoryWindow(id, 'latest');
}

/** Network and data coordination. All viewport operations live in history-viewport. */
export async function loadSessionHistoryWindow(id: string, direction: HistoryDirection, around?: string, options?: { isCurrent: () => boolean }): Promise<boolean> {
  if (options && !options.isCurrent()) return false;
  const expected = useSessionHistory.getState().pages[id];
  if (expected?.loading && (direction === 'latest' || direction === 'around')) {
    await new Promise<void>(resolve => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        unsubscribe();
        queueMicrotask(resolve);
      };
      const unsubscribe = useSessionHistory.subscribe((state) => {
        if (!state.pages[id]?.loading || state.pages[id]?.generation !== expected.generation) {
          finish();
        }
      });
      const current = useSessionHistory.getState().pages[id];
      if (!current?.loading || current.generation !== expected.generation) finish();
    });
    return loadSessionHistoryWindow(id, direction, around, options);
  }
  if (expected?.renewalRequired && !expected.loading && (direction === 'older' || direction === 'newer')) {
    // An expired cursor cannot page; renew around the reading anchor, or at
    // the newest page when this chat is not on screen, so paging resumes.
    const anchor = readingAnchor(id);
    return loadSessionHistoryWindow(id, anchor ? 'around' : 'latest', anchor, options);
  }
  if (!expected || expected.loading || (direction === 'older' && !expected.before)
      || (direction === 'newer' && !expected.after)) return false;
  const socket = getSocket();
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    updateSessionHistory(id, expected.generation, {error: true});
    return false;
  }
  updateSessionHistory(id, expected.generation, { loading: true, error: false });
  const field = direction === 'older' ? {history_before: expected.before}
    : direction === 'newer' ? {history_after: expected.after}
    : direction === 'around' ? {history_around: around} : {history_latest: true};
  type PageReply = {id: string; messages: HistoryRow[]; history: HistoryPage; error_code?: string};
  let page = await wsRequest<PageReply>(
    'load_session', {session_id:id, history_head:expected.head_id, ...(!expected.renewalRequired ? {history_snapshot:expected.snapshot} : {}), ...field},
    'session_history_page', {requestId:true}, 15000,
  );
  if (useSessionHistory.getState().pages[id]?.generation !== expected.generation) return false;
  const previous = windows.get(id);
  let renewedAround = false;
  if (page?.history?.snapshot && previous?.history?.snapshot && page.history.snapshot !== previous.history.snapshot
      && page.history.head_id === expected.head_id && (direction === 'older' || direction === 'newer')
      && !expected.renewalRequired && getSocket() === socket && (!options || options.isCurrent())) {
    // The server dropped this chat's snapshot and built a new one at the same
    // head. Its positions are not comparable with the retained pages, so read
    // the new snapshot around what the user is reading instead of replacing
    // the window with one edge page.
    const anchor = readingAnchor(id);
    const renewal = anchor ? await wsRequest<PageReply>('load_session', {
      session_id: id, history_head: expected.head_id, history_snapshot: page.history.snapshot, history_around: anchor,
    }, 'session_history_page', {requestId:true}, 15000) : null;
    if (useSessionHistory.getState().pages[id]?.generation !== expected.generation) return false;
    if (renewal?.id === id && renewal.history?.snapshot && Array.isArray(renewal.messages)) { page = renewal; renewedAround = true; }
  }
  let renewed = !!expected.renewalRequired || renewedAround;
  if (page?.error_code === 'invalid_request' && !(renewed && direction === 'latest')
      && getSocket() === socket && (!options || options.isCurrent())) {
    updateSessionHistory(id, expected.generation, { renewalRequired: true });
    // Retry once without the expired cursor. A new snapshot can have a new head.
    // A renewal that already failed around its anchor, or a chat with no rows
    // on screen, falls back to the newest page instead of stopping.
    const anchor = renewed ? undefined : around ?? readingAnchor(id);
    page = await wsRequest<PageReply>('load_session', {
      session_id: id, history_head: expected.head_id, ...(anchor ? {history_around: anchor} : {history_latest: true}),
    }, 'session_history_page', {requestId:true}, 15000);
    renewed = true;
    if (useSessionHistory.getState().pages[id]?.generation !== expected.generation) return false;
  }
  if (getSocket() !== socket || !page || page.id !== id || !page.history || !Array.isArray(page.messages)
      || (!renewed && direction !== 'latest' && page.history.head_id !== expected.head_id)) {
    updateSessionHistory(id, expected.generation, {loading:false,error:true});
    return false;
  }
  if (options && !options.isCurrent()) {
    updateSessionHistory(id, expected.generation, { loading: false });
    return false;
  }
  const conv = runtimeState.conversations[id] as {messages?: HistoryRow[]} | undefined;
  if (!conv) { updateSessionHistory(id, expected.generation, {loading:false}); return false; }
  const registered=viewports.get(id);
  const captures = registered
    ? [...registered.entries()].map(([area, chatKey]) => captureAreaRestoreState(area, chatKey, true))
    : [];
  if (!captures.length && runtimeState.currentSessionId === id) {
    const area = document.getElementById('chatArea');
    if (area) captures.push(captureAreaRestoreState(area, useSessionStore.getState().activeChatKey ?? id, false));
  }
  const store = useSessionStore.getState();
  const current = (store.messageOrder[id] ?? []).map(mid=>store.messagesById[mid]).filter(Boolean);
  const known = new Set(previous?.messages.map(m=>m.id) ?? (conv.messages ?? []).map(m=>m.id));
  let messages: HistoryRow[], history: HistoryPage;
  if (page.history.snapshot) {
    const historyWindow = previous ?? new HistoryWindow();
    historyWindow.add(page.messages,page.history,renewed ? 'around' : direction, direction === 'around' ? around : captures[0]?.anchor?.id);
    windows.delete(id); windows.set(id,historyWindow);
    messages=historyWindow.messages; history=historyWindow.history!;
  } else {
    // Compatibility with an older server: its before-only protocol has no eviction cursors.
    const incomingIds=new Set(page.messages.map(m=>m.id));
    messages=[...page.messages,...(conv.messages ?? []).filter(m=>!incomingIds.has(m.id))];
    history=page.history;
  }
  const mapped=convToChatMsgs(messages as never[]);
  const selected=new Set(mapped.map(m=>m.id));
  const live = current.filter(m=>!selected.has(m.id) && (!known.has(m.id)
    || ['running','streaming','pending','cancelling'].includes(m.status ?? ''))).slice(-50);
  const currentById=new Map(current.map(m=>[m.id,m]));
  const merged=[...mapped.map(m=>currentById.get(m.id) ?? m),...live];
  conv.messages=messages as typeof conv.messages;
  flushSync(()=>{
    store.setMessages(id,merged);
    updateSessionHistory(id,expected.generation,{...history,loading:false,error:false,renewalRequired:false});
  });
  const liveIds = new Set(merged.map(m=>m.id));
  const liveRegistered = viewports.get(id);
  for (const cap of captures) {
    retainRowHeights(cap.chatKey, liveIds);
    if (direction === 'latest') {
      // The newest page replaced this viewport's window. A Jump or a send
      // that asked for it holds the follow lock and places the view itself;
      // a renewal or a retry did not, so hand the placement to the stick
      // hook as a take-latest note (the loader never pins the view), or the
      // reader is left wherever the browser clamped the old offset.
      if (!isFollowLocked(cap.chatKey)) noteTakeLatest({ sessionId: id, scrollerKey: cap.chatKey, turnSeed: '' });
      continue;
    }
    if (historyAreaStillOwned(cap, liveRegistered, {
      sessionId: id,
      focusedSessionId: runtimeState.currentSessionId,
      focusedChatKey: useSessionStore.getState().activeChatKey,
    })) {
      restoreAreaWindow(cap, direction, around);
    }
  }
  trimHistoryWindows(id);
  return true;
}
