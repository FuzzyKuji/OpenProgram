import type { ChatMsg } from '../../session-store/types';
import { hasMissingProgress } from '../../session-store/messages/message-snapshot.ts';
import { isUnsentUserRow } from '../../session-store/messages/pending-sends.ts';

export type SessionReadStatus = 'loading' | 'ready' | 'error' | 'disconnected';
export type SessionRead = { action: 'load_session'; session_id: string; [key: string]: unknown };

/** One connection owns pending reads. Mutations invalidate reads, never retry commands. */
export function createSessionLoads<T>(options: {
  send: (request: SessionRead) => void;
  capture: (id: string) => T;
  status: (id: string, status: SessionReadStatus) => void;
  requestId: () => string;
}) {
  type Pending = { request: SessionRead; context: T; timer: ReturnType<typeof setTimeout>; next?: SessionRead };
  const pending = new Map<string, Pending>();
  const seen = new Set<string>();
  let disposed = false;
  function request(payload: SessionRead, invalidate = false): boolean {
    if (disposed) return false;
    const id = payload.session_id;
    const active = pending.get(id);
    if (active) {
      if (invalidate) active.next = payload;
      return true;
    }
    seen.add(id);
    const wire = { ...payload, request_id: options.requestId() };
    const entry: Pending = {
      request: wire, context: options.capture(id),
      timer: setTimeout(() => fail(id, 'error'), 15_000),
    };
    pending.set(id, entry);
    options.status(id, 'loading');
    try { options.send(wire); } catch { fail(id, 'disconnected'); return false; }
    return true;
  }
  function take(id: string) {
    const entry = pending.get(id);
    if (entry) { clearTimeout(entry.timer); pending.delete(id); }
    return entry;
  }
  function fail(id: string, status: SessionReadStatus) {
    const entry = take(id);
    if (!entry) return;
    if (entry.next && status === 'error' && !disposed) { request(entry.next); return; }
    options.status(id, status);
  }
  return {
    request,
    accept(data: { id?: unknown; request_id?: unknown }): { context?: T } | false {
      if (disposed || typeof data.id !== 'string') return false;
      const entry = pending.get(data.id);
      // Unsolicited legacy loads are allowed only before a managed read.
      if (!entry) return !data.request_id && !seen.has(data.id) ? {} : false;
      if (data.request_id !== entry.request.request_id) return false;
      take(data.id);
      if (entry.next) { request(entry.next); return false; }
      options.status(data.id, 'ready');
      return { context: entry.context };
    },
    error(data: { request_id?: unknown }) {
      for (const [id, entry] of pending) {
        if (data.request_id === entry.request.request_id) { fail(id, 'error'); return true; }
      }
      return false;
    },
    dispose() {
      disposed = true;
      for (const id of pending.keys()) fail(id, 'disconnected');
      seen.clear();
    },
  };
}

/** Store rows are immutable: retain only progress written after the read began.
 * A row changed during the read wins only when it holds everything the loaded
 * row does; a live row rebuilt from post-read deltas alone (a reload or
 * reconnect mid-reply) would otherwise replace the fuller loaded row. */
export function retainChangedRows<T extends { id: string; status?: string; role?: string }>(before: readonly T[], current: readonly T[], loaded: readonly T[]): T[] {
  const baseline = new Map(before.map(row => [row.id, row]));
  const loadedIds = new Set(loaded.map(row => row.id));
  // Live rows the load does not hold yet survive it, and so does a user row
  // whose send failed: the server never stored it, only the client shows it.
  const clientOnly = (row: T) => ['pending', 'running', 'streaming', 'cancelling'].includes(row.status ?? '') || isUnsentUserRow(row);
  const changed = new Map(current.filter(row => baseline.get(row.id) !== row || (!loadedIds.has(row.id) && clientOnly(row))).map(row => [row.id, row]));
  const result = loaded.map(row => {
    const live = changed.get(row.id);
    changed.delete(row.id);
    return live && !hasMissingProgress(row as unknown as ChatMsg, live as unknown as ChatMsg) ? live : row;
  });
  return [...result, ...changed.values()];
}
