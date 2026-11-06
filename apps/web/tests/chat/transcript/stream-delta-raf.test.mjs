/**
 * text/thinking stream deltas coalesce to one store stamp per animation
 * frame. A tool/status/finalize event flushes that rid first so the
 * card cannot land before the body it followed.
 */
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { registerHooks } from "node:module";
import test from "node:test";
import { fileURLToPath } from "node:url";

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith("@/")) {
      const base = new URL(`../../../${specifier.slice(2)}`, import.meta.url).href;
      const file = `${base}.ts`;
      const url = existsSync(fileURLToPath(file)) ? file : `${base}/index.ts`;
      return { url, shortCircuit: true };
    }
    if (specifier.startsWith(".") && !/\.[a-z]+$/.test(specifier)) {
      const base = new URL(specifier, context.parentURL).href;
      const file = `${base}.ts`;
      const url = existsSync(fileURLToPath(file)) ? file : `${base}/index.ts`;
      return { url, shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
});

const values = new Map();
globalThis.window = {
  addEventListener: () => {},
  dispatchEvent: () => {},
  location: { pathname: "/chat" },
};
globalThis.localStorage = {
  getItem: (key) => values.get(key) ?? null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: (key) => values.delete(key),
};

const rafQueue = [];
let rafHandle = 1;
globalThis.requestAnimationFrame = (cb) => {
  const id = rafHandle++;
  rafQueue.push({ id, cb });
  return id;
};
globalThis.cancelAnimationFrame = (id) => {
  const i = rafQueue.findIndex((item) => item.id === id);
  if (i >= 0) rafQueue.splice(i, 1);
};

const { useSessionStore } = await import("../../../lib/session-store/index.ts");
const { applyChatWsMessage, clearSessionByMsgId, flushPendingChatDeltas } = await import(
  "../../../lib/net/ws/chat-stream.ts"
);
const {
  clearPendingUserText,
  setPendingUserText,
} = await import("../../../lib/chat/send/pending-user-text.ts");
const realUpdateMessage = useSessionStore.getState().updateMessage;

const SID = "s_raf";
const UID = "u_raf";
const RID = `${UID}_reply`;

test("verifier identity survives streaming, accepted verdict and history mapping", async () => {
  const sid = "verification-stream", uid = "verifier", rid = uid + "_reply";
  const mark = {id:"candidate",status:"pending"};
  applyChatWsMessage({type:"chat_ack",data:{session_id:sid,msg_id:uid,goal_verification:mark}});
  assert.deepEqual(useSessionStore.getState().messagesById[rid].goalVerification, mark);
  applyChatWsMessage({type:"chat_response",data:{type:"stream_event",session_id:sid,msg_id:uid,goal_verification:mark,event:{type:"text",text:'{"requirements":['}}});
  assert.deepEqual(useSessionStore.getState().messagesById[rid].goalVerification, mark);
  const accepted = {...mark,status:"met",requirements:[{id:"objective",verdict:"met",text:"Compute"}]};
  globalThis.CustomEvent = class { constructor(type, options) {this.type=type;this.detail=options.detail;} };
  const { updateSessionGoal } = await import("../../../lib/runtime-bridge/actions/goal-state.ts");
  updateSessionGoal(sid,{version:5,verification_message:{message_id:rid,presentation:accepted}});
  applyChatWsMessage({type:"chat_response",data:{type:"result",session_id:sid,msg_id:uid,content:'{"requirements":[]}',goal_verification:mark}});
  assert.deepEqual(useSessionStore.getState().messagesById[rid].goalVerification, accepted);
  applyChatWsMessage({type:"chat_ack",data:{session_id:sid,msg_id:uid,goal_verification:mark}});
  assert.deepEqual(useSessionStore.getState().messagesById[rid].goalVerification, accepted);
  updateSessionGoal(sid,{version:4,verification_message:{message_id:rid,presentation:mark}});
  assert.deepEqual(useSessionStore.getState().messagesById[rid].goalVerification, accepted);
  const { convToChatMsgs } = await import("../../../lib/chat/transcript/conv-mapper.ts");
  const raw = '{"requirements":[],"reason":"internal"}';
  const mapped = convToChatMsgs([{id:rid,role:"assistant",content:raw,goal_verification:accepted}]);
  assert.deepEqual(mapped[0].goalVerification, accepted);
  assert.equal(mapped[0].content, raw);
  assert.equal(convToChatMsgs([{id:"normal-json",role:"assistant",content:raw}])[0].goalVerification, undefined);
});

function reply() {
  return useSessionStore.getState().messagesById[RID];
}

test("accepted snapshot arriving before the row is replayed only for its exact identity", async () => {
  const { updateSessionGoal } = await import("../../../lib/runtime-bridge/actions/goal-state.ts");
  const sid="accepted-before-message", uid="verify-late", rid=uid+"_reply";
  const accepted={id:"candidate-late",status:"met"};
  updateSessionGoal(sid,{version:9,verification_message:{message_id:rid,presentation:accepted}});
  const pending={id:"candidate-late",status:"pending"};
  applyChatWsMessage({type:"chat_ack",data:{session_id:sid,msg_id:uid,goal_verification:pending}});
  applyChatWsMessage({type:"chat_response",data:{type:"result",session_id:sid,msg_id:uid,content:'{"requirements":[]}',goal_verification:pending}});
  assert.deepEqual(useSessionStore.getState().messagesById[rid].goalVerification,accepted);
  for (const [session, user, identity] of [["other-session","other-user",pending], [sid,"other-message",pending], [sid,"other-candidate",{id:"different",status:"pending"}]]) {
    applyChatWsMessage({type:"chat_ack",data:{session_id:session,msg_id:user,goal_verification:identity}});
    assert.deepEqual(useSessionStore.getState().messagesById[user+"_reply"].goalVerification,identity);
  }
});

function send(event, sid = SID, uid = UID) {
  applyChatWsMessage({
    type: "chat_response",
    data: { type: "stream_event", session_id: sid, msg_id: uid, event },
  });
}

function runFrame() {
  const batch = rafQueue.splice(0);
  for (const item of batch) item.cb(0);
}

function countReplyStamps() {
  const orig = useSessionStore.getState().updateMessage;
  let n = 0;
  useSessionStore.setState({
    updateMessage(sid, id, patch) {
      if (id === RID) n += 1;
      return orig(sid, id, patch);
    },
  });
  return {
    get count() {
      return n;
    },
    restore() {
      useSessionStore.setState({ updateMessage: orig });
    },
  };
}

function reset() {
  rafQueue.length = 0;
  useSessionStore.setState({ updateMessage: realUpdateMessage });
  clearSessionByMsgId();
  useSessionStore.setState({
    messagesById: {},
    messageOrder: {},
    currentSessionId: SID,
  });
  applyChatWsMessage({
    type: "chat_ack",
    data: { session_id: SID, msg_id: UID },
  });
}

test("two text deltas in one frame stamp the store once", () => {
  reset();
  const stamps = countReplyStamps();
  send({ type: "text", text: "hel" });
  send({ type: "text", text: "lo" });
  assert.equal(reply()?.content ?? "", "");
  assert.equal(stamps.count, 0);
  runFrame();
  assert.equal(reply().content, "hello");
  assert.deepEqual(reply().blocks, [{ type: "text", text: "hello" }]);
  assert.equal(stamps.count, 1);
  runFrame();
  assert.equal(stamps.count, 1);
  stamps.restore();
});

test("a tool event flushes pending text before the card lands", () => {
  reset();
  const stamps = countReplyStamps();
  send({ type: "text", text: "hi" });
  assert.equal(reply()?.content ?? "", "");
  send({
    type: "tool_use",
    tool: "read",
    tool_call_id: "tc_1",
    input: "{}",
  });
  assert.equal(reply().content, "hi");
  assert.equal(reply().blocks[0].type, "text");
  assert.equal(reply().blocks[0].text, "hi");
  assert.equal(reply().blocks[1].type, "tool");
  assert.equal(reply().blocks[1].tool, "read");
  assert.equal(stamps.count, 2);
  runFrame();
  assert.equal(reply().content, "hi");
  assert.equal(reply().blocks.length, 2);
  assert.equal(stamps.count, 2);
  stamps.restore();
});

test("session_loaded discard does not stamp another session", () => {
  reset();
  send({ type: "text", text: "nope" });
  useSessionStore.setState({ currentSessionId: "other" });
  clearSessionByMsgId();
  runFrame();
  assert.equal(useSessionStore.getState().messagesById[RID]?.content ?? "", "");
  assert.equal(useSessionStore.getState().messagesById.other, undefined);
});

test("ACK rekeys the immediately visible pending user row and adds one reply", () => {
  const sid = "s_pending_ack";
  const pendingId = "pending_local_ack";
  clearSessionByMsgId();
  clearPendingUserText(sid);
  useSessionStore.setState({ messagesById: {}, messageOrder: {}, currentSessionId: sid });
  setPendingUserText(sid, "hello", 123, { messageId: pendingId });
  useSessionStore.getState().appendMessage(sid, {
    id: pendingId,
    role: "user",
    content: "hello",
    status: "pending",
    timestamp: 123,
  });

  applyChatWsMessage({
    type: "chat_ack",
    data: { session_id: sid, msg_id: "server_ack_1", text: "hello" },
  });
  const state = useSessionStore.getState();
  assert.deepEqual(state.messageOrder[sid], ["server_ack_1", "server_ack_1_reply"]);
  assert.equal(state.messagesById.pending_local_ack, undefined);
  assert.equal(state.messagesById.server_ack_1.content, "hello");
  assert.equal(state.messagesById.server_ack_1.status, "done");
  assert.equal(state.messagesById.server_ack_1_reply.status, "streaming");
});

test("run_active with attachments restores the captured draft and keeps a failed row", () => {
  const sid = "s_pending_attachment_error";
  let restored = 0;
  clearSessionByMsgId();
  clearPendingUserText(sid);
  useSessionStore.setState({ messagesById: {}, messageOrder: {}, currentSessionId: sid });
  setPendingUserText(sid, "attach this", 123, {
    hasAttachments: true,
    messageId: "pending_attachment_error",
    onReject: () => { restored += 1; },
  });
  useSessionStore.getState().appendMessage(sid, {
    id: "pending_attachment_error",
    role: "user",
    content: "attach this",
    status: "pending",
  });
  applyChatWsMessage({
    type: "chat_response",
    data: { type: "error", code: "run_active", session_id: sid, msg_id: "rejected_attachment" },
  });
  assert.equal(restored, 1);
  assert.equal(useSessionStore.getState().messagesById.pending_attachment_error.status, "error");
});

test("a rejected send keeps its old row when the composer has newer text", () => {
  const sid = "s_pending_newer_draft";
  clearSessionByMsgId();
  clearPendingUserText(sid);
  useSessionStore.setState({ messagesById: {}, messageOrder: {}, currentSessionId: sid });
  setPendingUserText(sid, "old rejected text", 123, {
    messageId: "pending_newer", onReject: () => {},
  });
  useSessionStore.getState().appendMessage(sid, {
    id: "pending_newer", role: "user", content: "old rejected text", status: "pending",
  });
  applyChatWsMessage({
    type: "chat_response",
    data: { type: "error", session_id: sid, msg_id: "rejected_newer", reason: "provider" },
  });
  const row = useSessionStore.getState().messagesById.pending_newer;
  assert.equal(row.content, "old rejected text");
  assert.equal(row.status, "error");
});

test("ACK falls back to appending when hydration removed the pending row", () => {
  const sid = "s_pending_hydrate";
  clearSessionByMsgId();
  clearPendingUserText(sid);
  useSessionStore.setState({ messagesById: {}, messageOrder: {}, currentSessionId: sid });
  setPendingUserText(sid, "hello after reload", 123, { messageId: "pending_hydrate" });
  useSessionStore.getState().appendMessage(sid, {
    id: "pending_hydrate",
    role: "user",
    content: "hello after reload",
    status: "pending",
  });
  useSessionStore.getState().setMessages(sid, []);
  applyChatWsMessage({
    type: "chat_ack",
    data: { session_id: sid, msg_id: "server_hydrate", text: "hello after reload" },
  });
  const state = useSessionStore.getState();
  assert.deepEqual(state.messageOrder[sid], ["server_hydrate", "server_hydrate_reply"]);
  assert.equal(state.messagesById.server_hydrate.content, "hello after reload");
});

test("ACK rekey deduplicates when hydration already contains the server user id", () => {
  const sid = "s_pending_duplicate_hydrate";
  clearSessionByMsgId();
  clearPendingUserText(sid);
  useSessionStore.setState({ messagesById: {}, messageOrder: {}, currentSessionId: sid });
  setPendingUserText(sid, "hello", 123, { messageId: "pending_duplicate" });
  useSessionStore.getState().appendMessage(sid, {
    id: "pending_duplicate", role: "user", content: "hello", status: "pending",
  });
  useSessionStore.getState().appendMessage(sid, {
    id: "server_duplicate", role: "user", content: "hello", status: "done",
  });
  applyChatWsMessage({
    type: "chat_ack",
    data: { session_id: sid, msg_id: "server_duplicate", text: "hello" },
  });
  const order = useSessionStore.getState().messageOrder[sid];
  assert.deepEqual(order, ["server_duplicate", "server_duplicate_reply"]);
});


test("failure flushes pending progress and keeps the provider error separate", () => {
  const sid = "failed-progress", uid = "failed-user";
  send({type:"thinking",text:"Checking evidence"}, sid, uid);
  send({type:"text",text:"Partial response"}, sid, uid);
  applyChatWsMessage({type:"chat_response",data:{
    type:"error",session_id:sid,msg_id:uid,content:"provider disconnected",
  }});
  const msg=useSessionStore.getState().messagesById[uid+"_reply"];
  assert.equal(msg.status,"error");
  assert.equal(msg.content,"Partial response");
  assert.equal(msg.errorDetail,"provider disconnected");
  assert.deepEqual(msg.blocks,[
    {type:"thinking",text:"Checking evidence"},
    {type:"text",text:"Partial response"},
  ]);
});

test("retry status is visible during the same turn and clears on completion", () => {
  const sid = "retry-status", uid = "retry-user", rid = uid + "_reply";
  applyChatWsMessage({type:"chat_ack",data:{session_id:sid,msg_id:uid}});
  applyChatWsMessage({type:"chat_response",data:{type:"stream_event",session_id:sid,msg_id:uid,
    event:{type:"retry",attempt:2,max_attempts:3,reason:"transport",delay_ms:1500}}});
  assert.deepEqual(useSessionStore.getState().messagesById[rid].retryStatus, {
    attempt:2,maxAttempts:3,reason:"transport",delayMs:1500,
  });
  assert.equal(useSessionStore.getState().messagesById[rid].status,"streaming");
  applyChatWsMessage({type:"chat_response",data:{type:"stream_event",session_id:sid,msg_id:uid,
    event:{type:"thinking",text:"Continuing"}}});
  assert.equal(useSessionStore.getState().messagesById[rid].retryStatus,undefined);
  applyChatWsMessage({type:"chat_response",data:{type:"stream_event",session_id:sid,msg_id:uid,
    event:{type:"retry",attempt:3,max_attempts:3,reason:"transport"}}});
  applyChatWsMessage({type:"chat_response",data:{type:"result",session_id:sid,msg_id:uid,content:"Done"}});
  assert.equal(useSessionStore.getState().messagesById[rid].retryStatus,undefined);
});

test("host execution outcome survives live stream and history mapping", async () => {
  reset();
  send({ type: "tool_use", tool: "bash", tool_call_id: "denied", input: "{}" });
  send({ type: "tool_result", tool: "bash", tool_call_id: "denied", result: "refused", is_error: true, outcome: "not_started" });
  assert.equal(reply().blocks.find(b => b.tool_call_id === "denied").outcome, "not_started");
  const { convToChatMsgs } = await import("../../../lib/chat/transcript/conv-mapper.ts");
  const mapped = convToChatMsgs([{role: "assistant", id: RID, content: "", blocks: reply().blocks}]);
  assert.equal(mapped.flatMap(m => m.blocks ?? []).find(b => b.tool_call_id === "denied")?.outcome, "not_started");
});

test('only a new foreground successful reply requests automatic file presentation',()=>{
  const finish=(sid,id,type='result')=>{
    applyChatWsMessage({type:'chat_ack',data:{session_id:sid,msg_id:id}});
    useSessionStore.setState({currentSessionId:'file-foreground'});
    applyChatWsMessage({type:'chat_response',data:{type,session_id:sid,msg_id:id,content:'[File](/project/report.pdf)'}});
    return useSessionStore.getState().messagesById[id+'_reply'];
  };
  useSessionStore.setState({currentSessionId:'file-foreground'});
  assert.equal(finish('file-background','file-bg').autoPreviewFiles,undefined);
  assert.equal(finish('file-foreground','file-error','error').autoPreviewFiles,undefined);
  assert.equal(finish('file-foreground','file-ok').autoPreviewFiles,true);
  useSessionStore.getState().updateMessage('file-foreground','file-ok_reply',{autoPreviewFiles:false});
  applyChatWsMessage({type:'chat_response',data:{type:'result',session_id:'file-foreground',msg_id:'file-ok',content:'[File](/project/report.pdf)'}});
  assert.equal(useSessionStore.getState().messagesById['file-ok_reply'].autoPreviewFiles,false);
});

test("partial history cannot remove streamed tools or reopen a completed reply", async () => {
  const { convToChatMsgs } = await import('../../../lib/chat/transcript/conv-mapper.ts');
  const sid='trace-reload', uid='trace-turn', rid=uid+'_reply';
  const send=event=>applyChatWsMessage({type:'chat_response',data:{type:'stream_event',session_id:sid,msg_id:uid,event}});
  applyChatWsMessage({type:'chat_ack',data:{session_id:sid,msg_id:uid}});
  send({type:'text',text:'Checking. '});
  send({type:'tool_use',tool:'web_use',tool_call_id:'a',input:'{}'});
  send({type:'tool_result',tool:'web_use',tool_call_id:'a',result:'first result'});
  send({type:'tool_use',tool:'web_use',tool_call_id:'b',input:'{}'});
  const stale=()=>convToChatMsgs([{id:rid,role:'assistant',status:'running',content:'Checking. ',blocks:[{type:'text',text:'Checking. '}]}]);
  useSessionStore.getState().setMessages(sid,stale());
  assert.deepEqual(useSessionStore.getState().messagesById[rid].blocks.filter(b=>b.type==='tool').map(b=>b.tool_call_id),['a','b']);
  send({type:'tool_result',tool:'web_use',tool_call_id:'b',result:'second result'});
  applyChatWsMessage({type:'chat_response',data:{type:'result',session_id:sid,msg_id:uid,content:'Done'}});
  useSessionStore.getState().setMessages(sid,stale());
  assert.equal(useSessionStore.getState().messagesById[rid].status,'done');
  assert.equal(useSessionStore.getState().messagesById[rid].blocks.at(-1).result,'second result');
  // A deliberate branch/window change is authoritative about membership.
  useSessionStore.getState().setMessages(sid,[{id:'other-branch',role:'assistant',content:'Other',status:'done'}]);
  assert.deepEqual(useSessionStore.getState().messageOrder[sid],['other-branch']);
});

test("two same-name live call roots keep their distinct node identities", async () => {
  const {convToChatMsgs}=await import('../../../lib/chat/transcript/conv-mapper.ts');
  const sid='call-identities',uid='call-owner',rid=uid+'_reply';
  applyChatWsMessage({type:'chat_ack',data:{session_id:sid,msg_id:uid}});
  applyChatWsMessage({type:'chat_response',data:{type:'stream_event',session_id:sid,msg_id:uid,event:{type:'tool_use',tool:'web_use',tool_call_id:'a',input:'{}'}}});
  for(const path of ['first-node','second-node']) applyChatWsMessage({type:'chat_response',data:{type:'tree_update',session_id:sid,msg_id:rid,function:'web_use',tree:{path,name:'web_use',status:'running'}}});
  assert.deepEqual(useSessionStore.getState().messagesById[rid].callRoots.map(r=>r.path),['first-node','second-node']);
  const restored=convToChatMsgs([{id:rid,role:'assistant',status:'completed',content:'Done'},...['first-node','second-node'].map(id=>({id,role:'tool',function:'web_use',caller:rid,status:'completed',content:id}))]);
  assert.deepEqual(restored[0].callRoots.map(r=>r.path),['first-node','second-node']);
});

test('newer persisted results and terminal metadata are accepted without losing omitted trace', async () => {
  const {convToChatMsgs}=await import('../../../lib/chat/transcript/conv-mapper.ts');
  const sid='new-history', rid='history-reply';
  const block={type:'tool',tool:'list',tool_call_id:'one',input:'{}'};
  const load=(status,blocks,content='')=>useSessionStore.getState().setMessages(sid,convToChatMsgs([{id:rid,role:'assistant',content,status,blocks}]));
  load('running',[block]);
  load('running',[{...block,result:'persisted result'}]);
  assert.equal(useSessionStore.getState().messagesById[rid].blocks[0].result,'persisted result');
  load('error',undefined,'Provider disconnected');
  assert.equal(useSessionStore.getState().messagesById[rid].status,'error');
  assert.equal(useSessionStore.getState().messagesById[rid].errorDetail,'Provider disconnected');
  assert.equal(useSessionStore.getState().messagesById[rid].blocks[0].result,'persisted result');
  load('completed',[{...block,result:'authoritative retry result'}],'Recovered');
  assert.equal(useSessionStore.getState().messagesById[rid].blocks[0].result,'authoritative retry result');
  assert.equal(useSessionStore.getState().messagesById[rid].content,'Recovered');
});

test('partial history preserves nested calls, call trees and legacy text progress', async () => {
  const {convToChatMsgs}=await import('../../../lib/chat/transcript/conv-mapper.ts');
  const sid='nested-history',id='nested-reply';
  const store=useSessionStore.getState();
  const rows=[{id,role:'assistant',status:'running',content:'Observed full narration'},
    ...['first','second'].map(id=>({id,role:'assistant',type:'status',display:'runtime',caller:'nested-reply',function:id,status:'completed',content:id+' result'}))];
  store.setMessages(sid,convToChatMsgs(rows));
  store.updateMessage(sid,id,{callRoots:[{path:'a',name:'call',children:[{path:'a1'}]},{path:'b',name:'call'}]});
  store.setMessages(sid,convToChatMsgs([rows[0],rows[1]]));
  assert.deepEqual(useSessionStore.getState().messagesById[id].runtimeChildren.map(c=>c.id),['first','second']);
  store.setMessages(sid,[{...useSessionStore.getState().messagesById[id],callRoots:[{path:'a',name:'call'}]}]);
  store.setMessages(sid,[{...useSessionStore.getState().messagesById[id],content:'Observed'}]);
  assert.equal(useSessionStore.getState().messagesById[id].content,'Observed full narration');
  assert.equal(useSessionStore.getState().messagesById[id].callRoots.length,2);
  assert.equal(useSessionStore.getState().messagesById[id].callRoots[0].children[0].path,'a1');
});

test('loading peer history keeps foreground text waiting for its next frame', () => {
  reset();
  send({ type: 'text', text: 'Foreground progress' });
  clearSessionByMsgId('peer-session');
  runFrame();
  assert.equal(reply().content, 'Foreground progress');
});

test('accepted history flushes received text before merging its older snapshot', async () => {
  reset();
  const { runtimeState, setSocket } = await import('../../../lib/runtime-bridge/state.ts');
  const { requestSessionLoad, acceptSessionLoad, preserveSessionReadRows, disposeSessionLoads } = await import('../../../lib/runtime-bridge/session/session-load.ts');
  const previous = runtimeState.ws;
  const requests = [];
  const socket = { readyState: WebSocket.OPEN, send: raw => requests.push(JSON.parse(raw)) };
  setSocket(socket);
  try {
    requestSessionLoad({ action: 'load_session', session_id: SID });
    send({ type: 'text', text: 'Received after read began' });
    assert.equal(reply().content, '');
    acceptSessionLoad(socket, { id: SID, request_id: requests[0].request_id, messages: [
      { id: RID, role: 'assistant', content: '', status: 'streaming' },
    ] }, data => useSessionStore.getState().setMessages(SID, preserveSessionReadRows(SID, data.messages)));
    clearSessionByMsgId(SID);
    assert.equal(reply().content, 'Received after read began');
    runFrame();
    assert.equal(reply().content, 'Received after read began');
  } finally { disposeSessionLoads(socket); setSocket(previous); }
});

test('connection cleanup commits received text and cancels its scheduled frame', () => {
  reset();send({ type: 'text', text: 'Received before close' });
  flushPendingChatDeltas();clearSessionByMsgId();
  assert.equal(reply().content, 'Received before close');
  useSessionStore.getState().updateMessage(SID,RID,{content:'Recovered final',status:'done'});
  runFrame();assert.equal(reply().content,'Recovered final');assert.equal(reply().status,'done');
});

test('flushing buffered progress never reopens a cancelled or completed reply', () => {
  for (const status of ['cancelling', 'paused', 'cancelled', 'done', 'completed', 'error', 'interrupted']) {
    reset();send({type:'text',text:'Buffered before stop'});
    useSessionStore.getState().updateMessage(SID,RID,{content:'Accepted final state',status});
    flushPendingChatDeltas();
    assert.equal(reply().status,status);
    if(status!=='cancelling' && status!=='paused') assert.equal(reply().content,'Accepted final state');
  }
});

test('new output received after a pause resumes streaming', () => {
  reset();useSessionStore.getState().updateMessage(SID,RID,{status:'paused'});
  send({type:'text',text:'Resumed output'});runFrame();
  assert.equal(reply().status,'streaming');assert.equal(reply().content,'Resumed output');
});

test('new text after a recoverable error resumes instead of being discarded', () => {
  reset();
  applyChatWsMessage({type:'chat_response',data:{type:'error',session_id:SID,msg_id:UID,error:'Attempt failed'}});
  assert.equal(reply().status,'error');
  send({type:'text',text:'Recovered output'});runFrame();
  assert.equal(reply().status,'streaming');assert.equal(reply().content,'Recovered output');
});

test('output resumes after a pause even within the same animation frame', () => {
  reset();send({type:'text',text:'Before pause. '});
  useSessionStore.getState().updateMessage(SID,RID,{status:'paused'});
  send({type:'text',text:'After resume.'});runFrame();
  assert.equal(reply().status,'streaming');assert.equal(reply().content,'Before pause. After resume.');
});

test('text buffered before a history request cannot override its completed snapshot', async () => {
  reset();send({type:'text',text:'Old partial'});
  const { runtimeState, setSocket } = await import('../../../lib/runtime-bridge/state.ts');
  const { requestSessionLoad, acceptSessionLoad, preserveSessionReadRows, disposeSessionLoads } = await import('../../../lib/runtime-bridge/session/session-load.ts');
  const previous = runtimeState.ws;
  const requests = [];
  const socket = {readyState:WebSocket.OPEN,send:raw=>requests.push(JSON.parse(raw))};setSocket(socket);
  try {
    requestSessionLoad({action:'load_session',session_id:SID});
    assert.equal(reply().content,'Old partial');
    acceptSessionLoad(socket,{id:SID,request_id:requests[0].request_id,messages:[
      {id:RID,role:'assistant',content:'Complete answer',status:'done'},
    ]},data=>useSessionStore.getState().setMessages(SID,preserveSessionReadRows(SID,data.messages)));
    runFrame();assert.equal(reply().content,'Complete answer');assert.equal(reply().status,'done');
  } finally {disposeSessionLoads(socket);setSocket(previous);}
});

test("cold error history restores failure details independently from partial text", async () => {
  const {convToChatMsgs}=await import("../../../lib/chat/transcript/conv-mapper.ts");
  const [row]=convToChatMsgs([{id:"failed-history",role:"assistant",status:"error",content:"Partial answer",error_detail:"connection lost",error_reason:"transport",error_retryable:true,error_retry_after_s:4}]);
  assert.equal(row.content,"Partial answer");
  assert.equal(row.errorDetail,"connection lost");
  assert.equal(row.errorReason,"transport");
  assert.equal(row.errorRetryable,true);
  assert.equal(row.errorRetryAfterS,4);
  const [legacy]=convToChatMsgs([{id:"legacy",role:"assistant",status:"error",content:"[error] ProviderStreamError: ConnectError",blocks:[{type:"text",text:"Existing answer"}]}]);
  assert.equal(legacy.content,"Existing answer");
  assert.equal(legacy.errorDetail,"[error] ProviderStreamError: ConnectError");
});


test("persisted compatibility error output does not replace partial answer in the UI", async () => {
  const {convToChatMsgs}=await import("../../../lib/chat/transcript/conv-mapper.ts");
  const [row]=convToChatMsgs([{id:"persisted-error",role:"assistant",status:"error",content:"[error] disconnected",error_detail:"[error] disconnected",blocks:[{type:"text",text:"Partial answer"}]}]);
  assert.equal(row.content,"Partial answer");
  assert.equal(row.errorDetail,"[error] disconnected");
});
