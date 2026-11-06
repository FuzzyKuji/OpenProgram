import assert from 'node:assert/strict';
import test from 'node:test';
import { noticeDetail, readNotice, readReceipt } from '../../../lib/chat/transcript/agent-notices.ts';

// Text and items as agent/job/notices.py writes them.
const content = [
  'Background agents you started have finished. This is an automated notice, not a message from the user.',
  '',
  'Agent "scout" finished (job s1).',
  'Task: research X',
  'Its report is attached above.',
  '',
  'Agent "frontend" finished (job r1).',
  'Task: [message from p1:a1 (main conversation)] …',
  'Reply from branch p2:hb:',
  'Settings page done.',
  '',
  'Chat page left.',
  'To continue with it, use send_message(to="p2:hb").',
  '',
  "Carry on with the user's request from here: tell the user what they found.",
].join('\n');
const items = readNotice([
  { kind: 'report', name: 'scout', failed: false, address: 'p1:h1', line: 'Agent "scout" finished (job s1).' },
  { kind: 'reply', name: 'frontend', failed: false, address: 'p2:hb', line: 'Agent "frontend" finished (job r1).' },
  { kind: 'bogus', line: 'x' },
]);

test('unknown notice items are dropped', () => {
  assert.deepEqual(items.map((it) => it.kind), ['report', 'reply']);
  assert.equal(readNotice('nope'), undefined);
});

test('a report row opens on its task, a reply row on the whole reply', () => {
  assert.equal(noticeDetail(content, items, 0), 'research X');
  assert.equal(noticeDetail(content, items, 1), 'Settings page done.\n\nChat page left.');
});

test('a delivered message names its sender', () => {
  const r = readReceipt('[message from p1:a1 (main conversation)] Your final reply in this turn is returned to the sender automatically when the turn ends; answer there, not with send_message.\n\nhow far along?');
  assert.deepEqual(r, { kind: 'message', address: 'p1:a1', from: 'main conversation', body: 'how far along?' });
  const old = readReceipt('[task from p1:a1] This is a tracked job.\n\ndo it');
  assert.equal(old.from, '');
  assert.equal(old.body, 'do it');
  assert.equal(readReceipt('hello'), null);
});
