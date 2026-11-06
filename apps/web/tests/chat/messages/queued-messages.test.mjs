import assert from 'node:assert/strict';
import test from "node:test";
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'esbuild';
import { parseHTML } from 'linkedom';

import { scratchDir } from "../../scratch-dir.mjs";

const web = dirname(fileURLToPath(new URL('../../../package.json', import.meta.url)));
const dir = scratchDir(web, "queue-ui-test");
await build({absWorkingDir:web, stdin:{contents:`export { QueuedMessages } from './components/chat/messages/editing/queued-messages'; export { useSendQueue, registerChatSender } from './lib/chat/send/send-queue'; export { queuedMessagePayload } from './lib/chat/send/queued-attachments';`,resolveDir:web},bundle:true,format:'esm',platform:'node',packages:'external',outfile:join(dir,'test.mjs'),jsx:'automatic',tsconfig:join(web,'tsconfig.json'),plugins:[{name:'ports',setup(b){
 b.onResolve({filter:/^react$/},()=>({path:'react',external:true}));
 b.onResolve({filter:/\.module\.css$/},()=>({path:'css',namespace:'stub'}));
 b.onResolve({filter:/desktop-bridge$/},()=>({path:'bridge',namespace:'stub'}));
 b.onResolve({filter:/\/i18n$/},()=>({path:'i18n',namespace:'stub'}));
 b.onResolve({filter:/\/session-store$/},()=>({path:'session',namespace:'stub'}));
 b.onResolve({filter:/lazy-document-window$/},()=>({path:'viewer',namespace:'stub'}));
 b.onLoad({filter:/.*/,namespace:'stub'},({path})=>({contents:({
 css:`export default new Proxy({}, {get:(_,key)=>String(key)});`,
 bridge:`export const desktopBridge=()=>({getPathForFile:file=>'/fixture/'+file.name});`,
 i18n:`export const useTranslation=()=>({text:(en)=>en});`,
 session:`export const useSessionStore=selector=>selector(globalThis.sessions); useSessionStore.getState=()=>globalThis.sessions;`,
 viewer:`import {createElement} from 'react'; export const DocumentWindow=props=>createElement('div',{'data-document-path':props.path,'data-document-session':props.sessionId},'Document preview');`,
 })[path]}));
}}]});
const {window}=parseHTML('<html><body></body></html>');
Object.assign(globalThis,{window,document:window.document,HTMLElement:window.HTMLElement,Element:window.Element,CustomEvent:window.CustomEvent,IS_REACT_ACT_ENVIRONMENT:true,requestAnimationFrame:cb=>cb()});
Object.defineProperty(globalThis,'localStorage',{value:{getItem:()=>null,setItem(){},removeItem(){}},configurable:true});
globalThis.sessions={activeChatKey:'A',currentSessionId:'A',wsStatus:'open',runningTasks:{A:{msg_id:'busy'}}};
window.location={pathname:'/s/A'};
const {createElement:h,act}=await import('react');
const {createRoot}=await import('react-dom/client');
const {QueuedMessages,useSendQueue,registerChatSender,queuedMessagePayload}=await import(pathToFileURL(join(dir,'test.mjs')));

test('queued bubble previews attachments and edits files without changing order or another draft',async()=>{
 const doc={id:'old',filename:'old.txt',ext:'txt',sizeBytes:3,content:'old',sourcePath:'/fixture/old.txt',order:0};
 const settings={thinking:'medium',webSearchEnabled:false,background:false};
 const id=useSendQueue.getState().enqueue('A',{...settings,text:'first',docs:[doc]});
 const second=useSendQueue.getState().enqueue('A',{...settings,text:'second'});
 useSendQueue.getState().enqueue('B',{...settings,text:'other session'});
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const click=async el=>{assert.ok(el);await act(async()=>el.dispatchEvent(new window.Event('click',{bubbles:true})));};
 const button=name=>[...host.querySelectorAll('button')].find(el=>el.getAttribute('aria-label')===name || el.textContent===name);
 const sent=[];registerChatSender(args=>{sent.push(args);return true;});
 try {
 await act(async()=>root.render(h(QueuedMessages,{sessionId:'A'})));
 assert.equal(host.querySelectorAll('[data-queued-message]').length,2);
 assert.doesNotMatch(host.textContent,/other session/);
 // Rows are one line; clicking the text expands the message and its files.
 assert.equal(host.querySelector('[data-attachment-preview]'),null);
 await click(host.querySelector('[data-queued-message] button[aria-expanded]'));
 globalThis.sessions.currentSessionId='B'; // Preview remains local even while a peer has focus.
 await click(host.querySelector('[data-attachment-preview]'));
 assert.equal(Boolean(document.querySelector('[data-document-path]')),false, 'unsent native files must not request backend path access');
 assert.match(document.querySelector('[role="dialog"]').textContent,/old/);
 await click(document.querySelector('[aria-label="Close preview"]'));
 assert.equal(document.querySelector('[role="dialog"]'),null);
 await click(button('Edit queued message'));
 assert.equal(useSendQueue.getState().queues.A[0].editing,true);
 await click(host.querySelector('[data-attachment-remove]'));
 // The queue snapshot remains unchanged until Save.
 assert.equal(useSendQueue.getState().queues.A[0].docs[0].filename,'old.txt');
 const input=host.querySelector('input[type="file"]');
 Object.defineProperty(input,'files',{value:[{name:'new.txt',type:'text/plain',size:3,text:async()=> 'new'}],configurable:true});
 await act(async()=>input.dispatchEvent(new window.Event('change',{bubbles:true})));
 assert.match(host.textContent,/new.txt/);
 await click(button('Save'));
 assert.equal(useSendQueue.getState().queues.A[0].id,id);
 assert.equal(useSendQueue.getState().queues.A[0].docs[0].filename,'new.txt');
 assert.equal(useSendQueue.getState().queues.A[1].id,second);
 await click(button('Edit queued message'));
 await click(host.querySelector('[data-attachment-remove]'));
 await click(button('Cancel'));
 assert.equal(useSendQueue.getState().queues.A[0].docs[0].filename,'new.txt');
 // Native PDF bytes are preview-only and are snapshotted before drain.
 const pdfBytes=Buffer.from('%PDF-1.4\nfixture').toString('base64');
 globalThis.FileReader=class { readAsDataURL(){this.result='data:application/pdf;base64,'+pdfBytes;queueMicrotask(()=>this.onload());} };
 await click(button('Edit queued message'));
 const pdfInput=host.querySelector('input[type="file"]');
 Object.defineProperty(pdfInput,'files',{value:[{name:'local.pdf',type:'application/pdf',size:17}],configurable:true});
 await act(async()=>pdfInput.dispatchEvent(new window.Event('change',{bubbles:true})));
 await click(button('Save'));
 const queued=useSendQueue.getState().queues.A[0];
 assert.equal(queued.docs[1].dataB64,pdfBytes);
 assert.equal(queued.docs[1].loading,false);
 assert.equal(queuedMessagePayload(queued).attachments.length,0,'native PDF remains a path reference');
 await click([...host.querySelectorAll('[data-attachment-preview]')].find(el=>el.textContent.includes('local.pdf')));
 assert.match(document.querySelector('iframe')?.getAttribute('src') || '',/^blob:/);
 assert.equal(Boolean(document.querySelector('[data-document-path]')),false);
 await click(document.querySelector('[aria-label="Close preview"]'));
 await click(button('Remove from queue'));
 assert.equal(useSendQueue.getState().queues.A[0].id,second);
 assert.equal(useSendQueue.getState().queues.B[0].text,'other session');
 assert.equal(sent.length,0);
 await click(button('1 queued message'));
 assert.equal(host.querySelectorAll('[data-queued-message]').length,0);
 } finally {await act(async()=>root.unmount());host.remove();}
});


test('receipt polls keep waiting and uncertain status text stable', async()=>{
 useSendQueue.setState({queues:{}});
 const id=useSendQueue.getState().enqueue('A',{text:'supplement',thinking:'medium',webSearchEnabled:false,background:false});
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const patch=async data=>act(async()=>useSendQueue.getState().setSteering('A',id,data));
 try {
 await act(async()=>root.render(h(QueuedMessages,{sessionId:'A'})));
 const remove=()=>[...host.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')==='Remove from queue');
 await patch({injecting:true});
 const waiting=host.querySelector('[role=status]').textContent;
 assert.equal(remove().disabled,true,'the steer request is still being prepared');
 await patch({steerCommand:{command_id:'same'},injecting:false});
 assert.equal(host.querySelector('[role=status]').textContent,waiting);
 await patch({injecting:true});
 assert.equal(host.querySelector('[role=status]').textContent,waiting);
 await patch({injecting:false,steerError:'unconfirmed'});
 const uncertain=host.querySelector('[role=status]').textContent;
 await patch({injecting:true});
 assert.equal(host.querySelector('[role=status]').textContent,uncertain);
 assert.equal(remove().disabled,false,'a submitted steer can be taken back');
 } finally {await act(async()=>root.unmount());host.remove();useSendQueue.setState({queues:{}});}
});

test('rows tag where they go and Clear all keeps rows still being delivered', async()=>{
 useSendQueue.setState({queues:{}});
 const settings={thinking:'medium',webSearchEnabled:false,background:false};
 const steering=useSendQueue.getState().enqueue('A',{...settings,text:'add this now'});
 useSendQueue.getState().enqueue('A',{...settings,text:'next one\nsecond line'});
 useSendQueue.getState().setSteering('A',steering,{injecting:true});
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const sent=[];registerChatSender(args=>{sent.push(args);return true;});
 try {
 await act(async()=>root.render(h(QueuedMessages,{sessionId:'A'})));
 const rows=[...host.querySelectorAll('[data-queued-message]')];
 assert.equal(rows[0].querySelector('[data-tone]').textContent,'This turn');
 assert.equal(rows[1].querySelector('[data-tone]').textContent,'Next turn');
 assert.equal(rows[1].querySelector('button[aria-expanded]').textContent,'next one');
 assert.match(host.textContent,/2 queued messages/);
 assert.match(host.textContent,/1 adding to this turn/);
 const clear=[...host.querySelectorAll('button')].find(b=>b.textContent==='Clear all');
 await act(async()=>clear.dispatchEvent(new window.Event('click',{bubbles:true})));
 assert.deepEqual(useSendQueue.getState().queues.A.map(row=>row.id),[steering]);
 assert.equal(sent.length,0);
 } finally {await act(async()=>root.unmount());host.remove();useSendQueue.setState({queues:{}});}
});

test('removing, editing or clearing a This turn row takes the message back first', async()=>{
 useSendQueue.setState({queues:{}});
 const settings={thinking:'medium',webSearchEnabled:false,background:false};
 const add=(text,commandId)=>{
  const id=useSendQueue.getState().enqueue('A',{...settings,text});
  if(commandId) useSendQueue.getState().setSteering('A',id,{steerCommand:{command_id:commandId}});
  return id;
 };
 const ids=()=>(useSendQueue.getState().queues.A??[]).map(row=>row.id);
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const originalFetch=globalThis.fetch;const asked=[];const replies={};
 globalThis.fetch=async(url,init)=>{
  const commandId=/^\/api\/execution\/command\/([^/]+)\/withdraw$/.exec(url)?.[1];
  assert.ok(commandId&&init?.method==='POST',`unexpected request ${url}`);
  asked.push(commandId);
  return Response.json(replies[commandId]??{withdrawn:true,command:{command_id:commandId,status:'rejected',rejection_code:'withdrawn'}});
 };
 const press=async(row,label)=>{
  const target=[...host.querySelectorAll(`[data-queued-message="${row}"] button`)].find(b=>b.getAttribute('aria-label')===label);
  assert.equal(target.disabled,false);
  await act(async()=>{target.dispatchEvent(new window.Event('click',{bubbles:true}));await new Promise(resolve=>setTimeout(resolve,0));});
 };
 try {
 await act(async()=>root.render(h(QueuedMessages,{sessionId:'A'})));
 let removed,edited,taken,waiting;
 await act(async()=>{removed=add('drop this','c-remove');edited=add('reword this','c-edit');});
 await press(removed,'Remove from queue');
 assert.deepEqual(asked,['c-remove']);
 assert.deepEqual(ids(),[edited]);
 await press(edited,'Edit queued message');
 assert.deepEqual(asked,['c-remove','c-edit']);
 assert.equal(useSendQueue.getState().queues.A[0].editing,true);
 assert.equal(useSendQueue.getState().queues.A[0].steerCommand,undefined);
 assert.ok(host.querySelector('textarea'));
 await act(async()=>useSendQueue.getState().endEdit('A',edited));

 // A message the turn already took stays; Clear all removes the rest.
 replies['c-taken']={withdrawn:false,command:{command_id:'c-taken',status:'applying'}};
 await act(async()=>{taken=add('too late','c-taken');waiting=add('still waiting','c-waiting');});
 await press(taken,'Remove from queue');
 assert.deepEqual(ids(),[edited,taken,waiting]);
 const clear=[...host.querySelectorAll('button')].find(b=>b.textContent==='Clear all');
 assert.equal(clear.disabled,false);
 await act(async()=>{clear.dispatchEvent(new window.Event('click',{bubbles:true}));await new Promise(resolve=>setTimeout(resolve,0));});
 assert.deepEqual(ids(),[taken]);
 assert.ok(asked.includes('c-waiting'));
 } finally {
 // The row left on its way into the turn keeps a confirmation timer.
 await act(async()=>useSendQueue.setState({queues:{}}));
 await act(async()=>root.unmount());host.remove();globalThis.fetch=originalFetch;
 }
});

test('rows reorder by keyboard, and rows being delivered or edited keep their slot', async()=>{
 useSendQueue.setState({queues:{}});
 const settings={thinking:'medium',webSearchEnabled:false,background:false};
 const [a,b,c,d]=['a','b','c','d'].map(t=>useSendQueue.getState().enqueue('A',{...settings,text:t}));
 const order=()=>useSendQueue.getState().queues.A.map(row=>row.id);
 // A drag hands over the whole visual order; the store keeps it.
 useSendQueue.getState().reorder('A',[c,a,b,d]);
 assert.deepEqual(order(),[c,a,b,d]);
 // Unknown ids are ignored and rows left out keep their relative order.
 useSendQueue.getState().reorder('A',['gone',d]);
 assert.deepEqual(order(),[d,c,a,b]);
 // A row being added to the turn holds its slot whatever the drag says.
 useSendQueue.getState().setSteering('A',c,{injecting:true});
 useSendQueue.getState().reorder('A',[c,b,a,d]);
 assert.deepEqual(order(),[b,c,a,d]);
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 const key=async(id,k)=>{const el=host.querySelector(`[data-queued-message="${id}"] button[aria-expanded]`);
  await act(async()=>el.dispatchEvent(Object.assign(new window.Event('keydown',{bubbles:true}),{key:k,altKey:true})));};
 try {
 await act(async()=>root.render(h(QueuedMessages,{sessionId:'A'})));
 assert.deepEqual([...host.querySelectorAll('[data-queued-message]')].map(el=>el.dataset.queuedMessage),[b,c,a,d]);
 // Alt+↓ on b steps over the pinned row c.
 await key(b,'ArrowDown');
 assert.deepEqual(order(),[a,c,b,d]);
 await key(d,'ArrowUp');
 assert.deepEqual(order(),[a,c,d,b]);
 await key(a,'ArrowUp');
 assert.deepEqual(order(),[a,c,d,b], 'the first row cannot move up');
 assert.equal(host.querySelector(`[data-queued-message="${c}"] button[aria-expanded]`).getAttribute('aria-keyshortcuts'),null);
 } finally {await act(async()=>root.unmount());host.remove();useSendQueue.setState({queues:{}});}
});

test('rows show their enqueue time, offer Add to this turn, and announce a pending insert', async()=>{
 useSendQueue.setState({queues:{}});
 const settings={thinking:'medium',webSearchEnabled:false,background:false};
 const waiting=useSendQueue.getState().enqueue('A',{...settings,text:'add me'});
 useSendQueue.getState().enqueue('A',{...settings,text:'later'});
 useSendQueue.getState().setSteering('A',waiting,{injecting:true});
 const queuedAt=useSendQueue.getState().queues.A[1].queuedAt;
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
 try {
 await act(async()=>root.render(h(QueuedMessages,{sessionId:'A'})));
 const [first,second]=host.querySelectorAll('[data-queued-message]');
 assert.equal(second.querySelector('.message-timestamp').textContent,new Date(queuedAt).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}));
 assert.equal(first.querySelector('[role=status]').textContent,'Waiting to add to current turn…');
 const labels=row=>[...row.querySelectorAll('button[aria-label]')].map(b=>b.getAttribute('aria-label'));
 assert.ok(labels(second).includes('Add to this turn'));
 } finally {await act(async()=>root.unmount());host.remove();useSendQueue.setState({queues:{}});}
});
