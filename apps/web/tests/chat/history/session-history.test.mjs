import assert from 'node:assert/strict';
import test, { after } from 'node:test';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'esbuild';

import { scratchDir } from "../../scratch-dir.mjs";

const root = dirname(fileURLToPath(new URL('../../../package.json', import.meta.url)));
const dir = scratchDir(root, "history-test");
await build({absWorkingDir:root,stdin:{contents:`
export {loadOlderSessionHistory,loadSessionData} from './lib/runtime-bridge/session/conversations';
export {seedHistoryWindow,loadSessionHistoryWindow,registerHistoryViewport,retrySessionHistory} from './lib/runtime-bridge/session/session-history-loader';
export {runtimeState,setSocket} from './lib/runtime-bridge/state';
export {useSessionStore} from './lib/session-store';
export {createHistoryFragmentDecoder} from './lib/net/ws/history-fragments';
export {registerSessionHistory,updateSessionHistory,useSessionHistory} from './lib/chat/history/session-history';
export {peekTakeLatest,lastSettledTakeLatest} from './lib/chat/history/chat-scroll';
export {setFollowLock} from './lib/chat/history/history-viewport';
`,resolveDir:root},bundle:true,format:'esm',platform:'node',packages:'external',tsconfig:join(root,'tsconfig.json'),outfile:join(dir,'test.mjs')});
const fragment=(decoder,data)=>decoder.receive(JSON.stringify({type:'history_fragment',data}));
const {peekTakeLatest,lastSettledTakeLatest,setFollowLock,registerHistoryViewport,retrySessionHistory,seedHistoryWindow,loadSessionHistoryWindow,loadOlderSessionHistory,loadSessionData,runtimeState,setSocket,useSessionStore,createHistoryFragmentDecoder,registerSessionHistory,updateSessionHistory,useSessionHistory}=await import(pathToFileURL(join(dir,'test.mjs')));
test('large Unicode response is dispatched only when all ordered fragments arrive',()=>{
 const decoder=createHistoryFragmentDecoder();
 const original=JSON.stringify({type:'session_loaded',data:{id:'s',messages:['中文😀'.repeat(500000)]}});
 const parts=[];for(let i=0;i<original.length;i+=16384)parts.push(original.slice(i,i+16384));
 for(let i=0;i<parts.length;i++) {
  const result=fragment(decoder,{id:'x',index:i,text:parts[i],final:i===parts.length-1});
  assert.deepEqual(result,i===parts.length-1?[original]:[]);
 }
});
test('socket replacement discards partial history and rejects out-of-order continuation',()=>{
 const decoder=createHistoryFragmentDecoder();
 fragment(decoder,{id:'x',index:0,text:'old',final:false});decoder.clear();
 assert.throws(()=>fragment(decoder,{id:'x',index:1,text:'tail',final:true}));
 assert.deepEqual(fragment(decoder,{id:'fresh',index:0,text:'new',final:true}),['new']);
});
test('old history response cannot change a reloaded or different conversation',()=>{
 registerSessionHistory('a',{head_id:'head-a',before:'old-a'});
 const generation=useSessionHistory.getState().pages.a.generation;
 registerSessionHistory('b',{head_id:'head-b',before:'old-b'});
 registerSessionHistory('a',{head_id:'new-head',before:'new-old'});
 assert.equal(updateSessionHistory('a',generation,{before:null}),false);
 assert.equal(useSessionHistory.getState().pages.a.before,'new-old');
 assert.equal(useSessionHistory.getState().pages.b.before,'old-b');
});

test('public older-page load preserves live rows and rejects a page after reload',async()=>{
 class Socket extends EventTarget {
  static OPEN=1;readyState=1;sent=[];
  send(text){this.sent.push(JSON.parse(text));}
 }
 globalThis.WebSocket=Socket;
 globalThis.window ??= new EventTarget();
 const ws=new Socket();setSocket(ws);
 runtimeState.currentSessionId='other';
 runtimeState.conversations.s={id:'s',messages:[{id:'live',role:'assistant',content:'old'}]};
 useSessionStore.getState().setMessages('s',[{id:'live',role:'assistant',content:'streamed newest',status:'running'}]);
 registerSessionHistory('s',{head_id:'head',before:'live'});
 const load=loadOlderSessionHistory('s');
 const request=ws.sent.at(-1);
 ws.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type:'session_history_page',data:{
  id:'s',action:'load_session',request_id:request.request_id,
  messages:[{id:'old',role:'user',content:'earlier'}],history:{head_id:'head',before:null},
 }})}));
 await load;
 assert.deepEqual(useSessionStore.getState().messageOrder.s,['old','live']);
 assert.equal(useSessionStore.getState().messagesById.live.content,'streamed newest');
 assert.equal(runtimeState.currentSessionId,'other');
 registerSessionHistory('s',{head_id:'head',before:'old'});
 const stale=loadOlderSessionHistory('s');const staleRequest=ws.sent.at(-1);
 registerSessionHistory('s',{head_id:'different',before:'new-before'});
 ws.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type:'session_history_page',data:{
  id:'s',action:'load_session',request_id:staleRequest.request_id,
  messages:[{id:'stale',role:'user',content:'wrong'}],history:{head_id:'head',before:null},
 }})}));
 await stale;
 assert.equal(useSessionStore.getState().messagesById.stale,undefined);
 assert.equal(useSessionHistory.getState().pages.s.before,'new-before');
 setSocket(null);
});

test('historical compaction loads full content without graph placeholders',async()=>{
 class Socket extends EventTarget {static OPEN=1;readyState=1;sent=[];send(t){this.sent.push(JSON.parse(t));}}
 globalThis.WebSocket=Socket; const ws=new Socket();setSocket(ws);
 runtimeState.currentSessionId='other';
 loadSessionData({id:'compacted',messages:[{id:'new',role:'user',content:'latest'}],history:{head_id:'new',before:'new'},graph:[{id:'sum',covers_ids:['old'],preview:'short preview',summarised_count:1}]});
 const pending=loadOlderSessionHistory('compacted');const request=ws.sent.at(-1);
 ws.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type:'session_history_page',data:{id:'compacted',action:'load_session',request_id:request.request_id,messages:[{id:'sum_card',role:'system',kind:'compaction',slot:'card',content:'FULL SUMMARY CONTENT',covers_ids:['old']}],history:{head_id:'new',before:null}}})}));
 await pending;
 assert.equal(runtimeState.conversations.compacted.messages.find(m=>m.id==='sum_card').content,'FULL SUMMARY CONTENT');
 setSocket(null);
});

test('snapshot completes before interleaved terminal updates are applied',()=>{
 runtimeState.currentSessionId='other';
 const id='fragment-live';
 loadSessionData({id,messages:[{id:'running-row',role:'assistant',content:'initial',status:'running'}]});
 const decoder=createHistoryFragmentDecoder();
 const snapshot=JSON.stringify({type:'session_loaded',data:{id,messages:[{id:'running-row',role:'assistant',content:'snapshot-old',status:'running'}],history:{head_id:'running-row',before:null}}});
 const cut=Math.floor(snapshot.length/2);
 assert.deepEqual(fragment(decoder,{id:'snapshot',index:0,text:snapshot.slice(0,cut),final:false}),[]);
 assert.deepEqual(decoder.receive(JSON.stringify({type:'terminal',data:'terminal-result'})),[]);
 for(const wire of fragment(decoder,{id:'snapshot',index:1,text:snapshot.slice(cut),final:true})) {
  const message=JSON.parse(wire);
  if(message.type==='session_loaded')loadSessionData(message.data);
  else useSessionStore.getState().setMessages(id,[{id:'running-row',role:'assistant',content:message.data,status:'completed'}]);
 }
 assert.equal(useSessionStore.getState().messagesById['running-row'].content,'terminal-result');
});
test('interleaved snapshots retain first-fragment order and clear deferred notifications on disconnect',()=>{
 const decoder=createHistoryFragmentDecoder();
 assert.deepEqual(fragment(decoder,{id:'a',index:0,text:'A',final:false}),[]);
 assert.deepEqual(fragment(decoder,{id:'b',index:0,text:'B',final:true}),[]);
 assert.deepEqual(decoder.receive('"notification"'),[]);
 assert.deepEqual(fragment(decoder,{id:'a',index:1,text:'!',final:true}),['A!','B','"notification"']);
 fragment(decoder,{id:'c',index:0,text:'old',final:false});decoder.receive('"old-live"');decoder.clear();
 assert.deepEqual(decoder.receive('"fresh"'),['"fresh"']);
});


test('visiting many sessions evicts inactive raw pages and store rows; deletion releases history state',t=>{
 const storageDescriptor=Object.getOwnPropertyDescriptor(globalThis,'localStorage');
 Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}}});
 t.after(()=>storageDescriptor?Object.defineProperty(globalThis,'localStorage',storageDescriptor):delete globalThis.localStorage);
 runtimeState.currentSessionId='other';
 for(let i=0;i<10;i++){
  const id=`cache-${i}`, messages=[{id:`row-${i}`,role:'user',content:'content'}];
  runtimeState.conversations[id]={id,messages};
  useSessionStore.getState().setMessages(id,messages);
  const history={snapshot:id,head_id:`row-${i}`,start:0,end:1,total:1,before:null,after:null};
  registerSessionHistory(id,history);seedHistoryWindow(id,messages,history);
 }
 assert.ok(Object.values(runtimeState.conversations).filter(c=>c.id?.startsWith('cache-')&&c.messages?.length).length<=4);
 assert.ok(Object.entries(useSessionStore.getState().messageOrder).filter(([id,ids])=>id.startsWith('cache-')&&ids.length).length<=4);
 useSessionStore.getState().removeConversation('cache-9');
 assert.equal(useSessionHistory.getState().pages['cache-9'],undefined);
});

test('latest waits for a pending page instead of dropping the navigation intent',async()=>{
 class Socket extends EventTarget {static OPEN=1;readyState=1;sent=[];send(t){this.sent.push(JSON.parse(t));}}
 globalThis.WebSocket=Socket; const ws=new Socket();setSocket(ws);
 runtimeState.currentSessionId='other';
 runtimeState.conversations.queued={id:'queued',messages:[{id:'m50',role:'user',content:'middle'}]};
 useSessionStore.getState().setMessages('queued',[{id:'m50',role:'user',content:'middle'}]);
 const history={snapshot:'queue',head_id:'head',before:'m50',after:'m99',start:50,end:100,total:1000};
 seedHistoryWindow('queued',runtimeState.conversations.queued.messages,history);registerSessionHistory('queued',history);
 const older=loadOlderSessionHistory('queued');const latest=loadSessionHistoryWindow('queued','latest');
 assert.equal(ws.sent.length,1);
 function reply(messages,history){const req=ws.sent.at(-1);ws.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type:'session_history_page',data:{id:'queued',action:'load_session',request_id:req.request_id,messages,history}})}));}
 reply([{id:'m0',role:'user',content:'old'}],{...history,start:0,end:50,before:null,after:'m49'});
 await older;await new Promise(resolve=>setImmediate(resolve));
 assert.equal(ws.sent.length,2);assert.equal(ws.sent[1].history_latest,true);
 reply([{id:'newest',role:'user',content:'latest'}],{...history,start:950,end:1000,before:'m950',after:null});
 await latest;assert.deepEqual(useSessionStore.getState().messageOrder.queued,['newest']);setSocket(null);
});

const rows=(from,to)=>Array.from({length:to-from},(_,i)=>({id:`m${from+i}`,role:'user',content:`row ${from+i}`}));
function pageSocket(){
 class Socket extends EventTarget {static OPEN=1;readyState=1;sent=[];send(t){this.sent.push(JSON.parse(t));}}
 globalThis.WebSocket=Socket;const ws=new Socket();setSocket(ws);
 const send=(type,data)=>ws.dispatchEvent(new MessageEvent('message',{data:JSON.stringify({type,data:{action:'load_session',request_id:ws.sent.at(-1).request_id,...data}})}));
 return {ws,send,settle:()=>new Promise(resolve=>setImmediate(resolve))};
}
function readingArea(id){
 const row={dataset:{msgId:id},getBoundingClientRect:()=>({top:10,bottom:50,height:40})};
 return {scrollTop:2000,scrollHeight:5000,isConnected:true,dispatchEvent(){},
  getBoundingClientRect:()=>({top:0}),querySelectorAll:()=>[row]};
}

test('an older page from a rebuilt snapshot at the same head renews around the reading anchor',async t=>{
 const {ws,send,settle}=pageSocket();t.after(()=>setSocket(null));
 runtimeState.currentSessionId='other';
 const id='rebuilt', shown=rows(50,100);
 runtimeState.conversations[id]={id,messages:shown};useSessionStore.getState().setMessages(id,shown);
 const history={snapshot:'old',head_id:'m999',before:'m50',after:'m99',start:50,end:100,total:1000};
 seedHistoryWindow(id,shown,history);registerSessionHistory(id,history);
 const release=registerHistoryViewport(id,readingArea('m70'),id);t.after(release);
 const older=loadOlderSessionHistory(id);
 assert.equal(ws.sent[0].history_snapshot,'old');assert.equal(ws.sent[0].history_before,'m50');
 // The server evicted 'old' and answered from a new snapshot of the same head.
 send('session_history_page',{id,messages:rows(0,50),history:{...history,snapshot:'new',start:0,end:50,before:null,after:'m49'}});
 await settle();
 assert.equal(ws.sent.length,2);
 assert.equal(ws.sent[1].history_around,'m70');assert.equal(ws.sent[1].history_snapshot,'new');
 send('session_history_page',{id,messages:rows(45,95),history:{...history,snapshot:'new',start:45,end:95,before:'m45',after:'m94'}});
 await older;
 const order=useSessionStore.getState().messageOrder[id];
 assert.ok(order.includes('m70'),'the row being read stays in the window');
 assert.equal(order[0],'m45');
 const state=useSessionHistory.getState().pages[id];
 assert.equal(state.snapshot,'new');assert.equal(state.before,'m45');
 assert.equal(state.error,false);assert.ok(!state.renewalRequired);
});

test('an expired cursor with no reading anchor renews at the newest page and keeps retrying',async t=>{
 const {ws,send,settle}=pageSocket();t.after(()=>setSocket(null));
 runtimeState.currentSessionId='other';
 const id='unanchored', shown=rows(50,100);
 runtimeState.conversations[id]={id,messages:shown};useSessionStore.getState().setMessages(id,shown);
 const history={snapshot:'gone',head_id:'m999',before:'m50',after:'m99',start:50,end:100,total:1000};
 seedHistoryWindow(id,shown,history);registerSessionHistory(id,history);
 let older=loadOlderSessionHistory(id);
 send('operation_error',{code:'invalid_request',scope:'session'});
 await settle();
 assert.equal(ws.sent.length,2,'no anchor must not stop the renewal');
 assert.equal(ws.sent[1].history_latest,true);assert.equal(ws.sent[1].history_snapshot,undefined);
 send('operation_error',{code:'invalid_request',scope:'session'});
 await older;
 let state=useSessionHistory.getState().pages[id];
 assert.equal(state.error,true);assert.equal(state.renewalRequired,true);assert.equal(state.loading,false);
 // The next older request (autoload backoff) renews instead of being refused.
 older=loadOlderSessionHistory(id);
 assert.equal(ws.sent.length,3);assert.equal(ws.sent[2].history_latest,true);
 send('session_history_page',{id,messages:rows(950,1000),history:{...history,snapshot:'fresh',start:950,end:1000,before:'m950',after:null}});
 await older;
 state=useSessionHistory.getState().pages[id];
 assert.equal(state.error,false);assert.ok(!state.renewalRequired);
 assert.equal(state.snapshot,'fresh');assert.equal(state.before,'m950');
 // The manual retry works without an anchor too.
 const retry=retrySessionHistory(id);
 assert.equal(ws.sent.at(-1).history_latest,true);
 send('session_history_page',{id,messages:rows(950,1000),history:{...history,snapshot:'fresh',start:950,end:1000,before:'m950',after:null}});
 assert.equal(await retry,true);
});

test('a newest page nobody asked for hands its placement to the stick hook as a take-latest note',async t=>{
 const {ws,send,settle}=pageSocket();t.after(()=>setSocket(null));
 runtimeState.currentSessionId='other';
 const id='renewed-latest', shown=rows(50,100);
 runtimeState.conversations[id]={id,messages:shown};useSessionStore.getState().setMessages(id,shown);
 const history={snapshot:'fresh',head_id:'m999',before:'m50',after:'m99',start:50,end:100,total:1000};
 seedHistoryWindow(id,shown,history);registerSessionHistory(id,history);
 // A viewport with no readable row: the retry has no anchor and asks for the newest page.
 const area={scrollTop:2000,scrollHeight:5000,isConnected:true,dispatchEvent(){},getBoundingClientRect:()=>({top:0}),querySelectorAll:()=>[]};
 const release=registerHistoryViewport(id,area,id);t.after(release);
 const before=peekTakeLatest(id,id)?.generation ?? 0;
 let retry=retrySessionHistory(id);
 assert.equal(ws.sent.at(-1).history_latest,true);
 send('session_history_page',{id,messages:rows(950,1000),history:{...history,start:950,end:1000,before:'m950',after:null}});
 assert.equal(await retry,true);await settle();
 const note=peekTakeLatest(id,id);
 assert.ok(note && note.generation>before,'the hook is told to take the latest');
 assert.ok(note.generation>lastSettledTakeLatest(id,id),'the note is still waiting to be applied');
 assert.equal(area.scrollTop,2000,'the loader itself pins nothing');
 // A Jump or a send holds the follow lock and places the view itself: no second note.
 setFollowLock(id,true);t.after(()=>setFollowLock(id,false));
 retry=retrySessionHistory(id);
 send('session_history_page',{id,messages:rows(950,1000),history:{...history,start:950,end:1000,before:'m950',after:null}});
 assert.equal(await retry,true);await settle();
 assert.equal(peekTakeLatest(id,id).generation,note.generation);
});
