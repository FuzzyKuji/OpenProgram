import type { ChatMsg } from '../types';
import { validMessageTimestamp } from './message-timestamp.ts';

export function isLiveMessage(message: ChatMsg): boolean {
  return ['streaming', 'running', 'cancelling', 'pending'].includes(message.status ?? '');
}

function missingTreeProgress(current: Array<Record<string, unknown>> = [], incoming: Array<Record<string, unknown>> = []): boolean {
  return current.some((node, index) => {
    const next = node.path ? incoming.find(item => item.path === node.path) : incoming[index];
    if (!next) return true;
    if (node.status !== 'running' && next.status === 'running') return true;
    return missingTreeProgress(
      Array.isArray(node.children) ? node.children : [],
      Array.isArray(next.children) ? next.children : [],
    );
  });
}

/** A history request can finish after a newer stream frame. Compare only
 * append-only presentation progress for the same row, never branch membership.
 * True when `current` holds progress that `incoming` lacks. */
export function hasMissingProgress(current: ChatMsg, incoming: ChatMsg): boolean {
  if ((current.content?.length ?? 0) > (incoming.content?.length ?? 0)) return true;
  if ((current.thinking?.length ?? 0) > (incoming.thinking?.length ?? 0)) return true;
  if ((current.runtimeChildren ?? []).some(child => {
    const next = incoming.runtimeChildren?.find(item => item.id === child.id);
    return !next || hasMissingProgress(child, next)
      || (!isLiveMessage(child) && isLiveMessage(next));
  })) return true;
  if (missingTreeProgress(current.callRoots, incoming.callRoots)) return true;
  const blocks = incoming.blocks ?? [];
  return (current.blocks ?? []).some((block, index) => {
    const next = block.type === 'tool' && block.tool_call_id
      ? blocks.find(b => b.type === 'tool' && b.tool_call_id === block.tool_call_id)
      : blocks[index];
    if (!next || next.type !== block.type) return true;
    if (block.type === 'tool') return block.result != null && next.result == null;
    return (block.text?.length ?? 0) > (next.text?.length ?? 0);
  }) || (current.tools?.length ?? 0) > (incoming.tools?.length ?? 0);
}

export function reconcileMessageSnapshot(current: ChatMsg | undefined, incoming: ChatMsg): ChatMsg {
  if (!current || current.id !== incoming.id || current.role !== 'assistant'
      || incoming.role !== 'assistant' || current.display !== incoming.display) return incoming;
  // A live row wins only as a superset: a row rebuilt from post-read deltas
  // alone lacks what the snapshot holds, and the snapshot is the fuller one.
  if (isLiveMessage(incoming) && (!isLiveMessage(current)
      || (hasMissingProgress(current, incoming) && !hasMissingProgress(incoming, current)))) {
    return {
      ...incoming,
      ...current,
      timestamp: validMessageTimestamp(incoming.timestamp) ? incoming.timestamp : current.timestamp,
      // History may supply durable file references even while its text lags.
      turnFiles: incoming.turnFiles ?? current.turnFiles,
    };
  }
  // A terminal envelope/snapshot may omit the trace (for example on error).
  // Keep received steps; explicit nonempty terminal blocks remain authoritative.
  return {
    ...incoming,
    timestamp: validMessageTimestamp(incoming.timestamp) ? incoming.timestamp : current.timestamp,
    blocks: incoming.blocks?.length ? incoming.blocks : current.blocks,
    tools: incoming.tools?.length ? incoming.tools : current.tools,
    thinking: incoming.thinking ?? current.thinking,
    callRoots: incoming.callRoots?.length ? incoming.callRoots : current.callRoots,
    runtimeChildren: incoming.runtimeChildren?.length ? incoming.runtimeChildren : current.runtimeChildren,
    turnFiles: incoming.turnFiles ?? current.turnFiles,
  };
}
