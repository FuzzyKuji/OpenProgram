import { flushPendingChatDeltas } from "@/lib/net/ws/chat-stream";
import { createSessionLoads, retainChangedRows, type SessionRead, type SessionReadStatus } from '@/lib/net/ws/session-load';
import { useSessionStore, type ChatMsg } from '@/lib/session-store';
import { runtimeState, getSocket } from '../state';

function rows(id: string): ChatMsg[] {
  const state = useSessionStore.getState();
  return (state.messageOrder[id] ?? []).map(mid => state.messagesById[mid]).filter(Boolean);
}
function status(id: string, value: SessionReadStatus) {
  useSessionStore.getState().setTranscriptReadStatus(id, value);
}
function createOwner(socket: WebSocket) {
  return createSessionLoads({
    send: request => {
      if (socket.readyState !== WebSocket.OPEN) throw new Error('Disconnected');
      socket.send(JSON.stringify(request));
    },
    capture: id => {
      // Progress received before this read belongs to its baseline; only later
      // deltas may override the returned snapshot.
      flushPendingChatDeltas(id);
      return { rows: rows(id), wire: [...(runtimeState.conversations[id]?.messages as { id: string }[] ?? [])] };
    },
    status: (id, value) => { if (getSocket() === socket) status(id, value); }, requestId: () => crypto.randomUUID(),
  });
}
const applying = new Map<string, { before: ChatMsg[]; current: ChatMsg[] }>();
/** Called at the existing transcript store write, so no intermediate state loses live rows. */
export function preserveSessionReadRows(id: string, loaded: ChatMsg[]): ChatMsg[] {
  const read = applying.get(id);
  return read ? retainChangedRows(read.before, read.current, loaded) : loaded;
}
const owners = new WeakMap<WebSocket, ReturnType<typeof createOwner>>();
function owner(socket: WebSocket) {
  let value = owners.get(socket);
  if (!value) { value = createOwner(socket); owners.set(socket, value); }
  return value;
}
export function requestSessionLoad(payload: SessionRead, invalidate = false): boolean {
  const socket = getSocket();
  if (!socket || socket.readyState !== WebSocket.OPEN) { status(payload.session_id, 'disconnected'); return false; }
  return owner(socket).request(payload, invalidate);
}
/** Existing command helpers route reads here; all other commands keep their original delivery. */
export function sendRuntimeCommand(payload: unknown): boolean {
  const request = payload as Record<string, unknown> | null;
  if (request?.action === 'load_session' && typeof request.session_id === 'string') {
    return requestSessionLoad(request as SessionRead, true);
  }
  const socket = getSocket();
  if (!socket || socket.readyState !== WebSocket.OPEN) return false;
  socket.send(JSON.stringify(payload));
  return true;
}
export function acceptSessionLoad(socket: WebSocket, data: Record<string, unknown>, apply: (data: never) => void): boolean {
  const accepted = owner(socket).accept(data);
  if (!accepted) return false;
  const id = data.id as string;
  flushPendingChatDeltas(id);
  const current = rows(id);
  const context = accepted.context;
  if (context) {
    const wire = runtimeState.conversations[id]?.messages as { id: string }[] ?? [];
    data = { ...data, messages: retainChangedRows(context.wire, wire, data.messages as { id: string }[] ?? []) };
  }
  if (context) applying.set(id, { before: context.rows, current });
  try { apply(data as never); } catch (error) { status(id, 'error'); throw error; }
  finally { applying.delete(id); }
  return true;
}
export function failSessionLoad(socket: WebSocket, data: { request_id?: unknown }) { return owner(socket).error(data); }
export function disposeSessionLoads(socket: WebSocket) { owners.get(socket)?.dispose(); }
