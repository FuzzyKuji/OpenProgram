from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / 'apps/web'
pytestmark = pytest.mark.browser


def test_steering_boundary_and_history(tmp_path):
    from playwright.sync_api import sync_playwright, expect
    entry = r'''
import React from 'react';
import {createRoot} from 'react-dom/client';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {MessageRow} from './components/chat/messages/list/rows/message-rows';
import {useSessionStore} from './lib/session-store';
import {applyChatWsMessage} from './lib/net/ws/chat-stream';
import {convToChatMsgs} from './lib/chat/transcript/conv-mapper';
window.fetch=async()=>new Response('{}',{headers:{'content-type':'application/json'}});
const sid='steer-test',uid='turn',rid='turn_reply';
useSessionStore.setState({currentSessionId:sid,activeChatKey:sid});
window.frame=data=>applyChatWsMessage({type:'chat_response',data:{session_id:sid,...data}});
window.delta=text=>frame({type:'stream_event',msg_id:uid,event:{type:'text',text}});
applyChatWsMessage({type:'chat_ack',data:{session_id:sid,msg_id:uid}});
function App(){const ids=useSessionStore(s=>s.messageOrder[sid]);return <>{ids?.map(id=><MessageRow key={id} id={id} sessionIdOverride={sid}/>)}</>}
createRoot(document.getElementById('root')).render(<QueryClientProvider client={new QueryClient()}><App/></QueryClientProvider>);
window.reloadHistory=()=>{
 const store=useSessionStore.getState(), reply=store.messagesById[rid];
 const rows=convToChatMsgs([{id:rid,role:'assistant',content:reply.content,blocks:reply.blocks,status:'completed',predecessor:'steer-2'},
 {id:'steer-1',role:'user',content:'FIRST INPUT',steering:true,predecessor:uid},
 {id:'steer-2',role:'user',content:'SECOND INPUT',steering:true,predecessor:'steer-1'}]);
 useSessionStore.setState({messagesById:Object.fromEntries(rows.map(m=>[m.id,m])),messageOrder:{[sid]:rows.map(m=>m.id)}});
};
window.legacy=()=>{
 const rows=convToChatMsgs([{id:'oldreply',role:'assistant',content:'OLD ANSWER',predecessor:'oldsteer'},
 {id:'oldsteer',role:'user',content:'OLD INPUT',steering:true,predecessor:'olduser'}]);
 useSessionStore.setState({messagesById:Object.fromEntries(rows.map(m=>[m.id,m])),messageOrder:{[sid]:rows.map(m=>m.id)}});
};
'''
    bundle=tmp_path/'steer.js'
    subprocess.run(['node','-e',"require('esbuild').buildSync({stdin:{contents:process.argv[3],resolveDir:process.argv[1],loader:'tsx'},bundle:true,format:'iife',platform:'browser',jsx:'automatic',loader:{'.css':'css'},outfile:process.argv[2],tsconfig:process.argv[1]+'/tsconfig.json'});",str(WEB),str(bundle),entry],cwd=ROOT,check=True,capture_output=True)
    with sync_playwright() as runtime:
        browser=runtime.chromium.launch()
        try:
            page=browser.new_page(viewport={'width':760,'height':700})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.route('http://steer.test/**',lambda r:r.fulfill(body='<!doctype html><div id="root"></div>',content_type='text/html; charset=utf-8'))
            page.goto('http://steer.test/')
            if bundle.with_suffix('.css').exists():page.add_style_tag(path=str(bundle.with_suffix('.css')))
            for sheet in ['base/document.css','base/focus.css','base/list-row.css','base/layout.css','base/scrollbar.css','base/sidebar.css','base/desktop-chrome.css','base/motion.css','base/canvas-drag.css','chat/messages/bubbles.css','chat/messages/stream-blocks.css','chat/messages/message-actions.css']:
                page.add_style_tag(path=str(WEB/'app/styles'/sheet))
            page.add_script_tag(path=str(bundle))
            # A steer may arrive before the pending animation-frame delta flush.
            page.evaluate("delta('BEFORE INPUT'); frame({type:'user_message',msg_id:'steer-1',assistant_msg_id:'turn_reply',steering:true,content:'FIRST INPUT',timestamp:123})")
            page.evaluate("delta('AFTER FIRST')")
            expect(page.locator('#root')).to_contain_text('AFTER FIRST')
            page.evaluate("frame({type:'user_message',msg_id:'steer-2',assistant_msg_id:'turn_reply',steering:true,content:'SECOND INPUT',timestamp:124})")
            page.evaluate("delta('AFTER SECOND')")
            expect(page.locator('#root')).to_contain_text('AFTER SECOND')
            def order():
                texts=[s.strip() for s in page.locator('.chat-text, .message.user .message-content').all_text_contents()]
                assert texts==['BEFORE INPUT','FIRST INPUT','AFTER FIRST','SECOND INPUT','AFTER SECOND']
                expect(page.locator('[data-msg-id="steer-1"]')).to_have_count(1)
                expect(page.locator('[data-msg-id="steer-2"]')).to_have_count(1)
            order()
            # Replayed receipts must not duplicate or move an already consumed input.
            page.evaluate("frame({type:'user_message',msg_id:'steer-1',assistant_msg_id:'turn_reply',steering:true,content:'FIRST INPUT'})")
            order()
            page.evaluate("frame({type:'cancelled',msg_id:'turn'})")
            order()
            page.evaluate('reloadHistory()');order()
            page.set_viewport_size({'width':390,'height':700})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(tmp_path/'steer.png'))
            page.evaluate('legacy()')
            expect(page.locator('#root')).to_contain_text('OLD ANSWER')
            assert [s.strip() for s in page.locator('.chat-text, .message.user .message-content').all_text_contents()]==['OLD INPUT','OLD ANSWER']
            assert not errors,errors
        finally:browser.close()


@pytest.mark.parametrize("delivery", ["accepted", "lost_ack", "stopped"])
def test_pending_steer_survives_reload_without_an_ordinary_send(tmp_path, delivery):
    from playwright.sync_api import sync_playwright, expect
    entry = r'''
import React from 'react';
import {createRoot} from 'react-dom/client';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {QueuedMessages} from './components/chat/messages/editing/queued-messages';
import {useSendQueue,registerChatSender,reconcileAfterSessionLoad,holdSteeringForStop} from './lib/chat/send/send-queue';
import {steerQueuedMessage} from './lib/chat/send/steer-message';
import {useSessionStore} from './lib/session-store';
const sid='reload-steer';
window.ordinary=[];
registerChatSender(args=>{window.ordinary.push(args);return true});
useSessionStore.setState({currentSessionId:sid,activeChatKey:sid,runningTasks:{[sid]:{session_id:sid,msg_id:'u',execution_id:'exact-execution',status_version:7}}});
window.rows=()=>useSendQueue.getState().queues[sid]??[];
window.submit=async()=>{
 const id=useSendQueue.getState().enqueue(sid,{text:'retain my instruction',thinking:'medium',webSearchEnabled:false,background:false});
 await steerQueuedMessage(sid,id);
};
window.confirm=()=>steerQueuedMessage(sid,rows()[0].id);
window.hold=()=>holdSteeringForStop(sid);
createRoot(document.getElementById('root')).render(<QueryClientProvider client={new QueryClient()}><QueuedMessages sessionId={sid}/></QueryClientProvider>);
// Rows a reload left behind are adopted asynchronously (a Web Lock guards the
// storage); the run-state reply the adoption asks for is what confirms their
// receipts. Stand in for that reply once the rows are in.
const adopted=()=>rows().length?reconcileAfterSessionLoad(sid,true):setTimeout(adopted,10);
adopted();
'''
    bundle = tmp_path / 'reload.js'
    subprocess.run(['node', '-e', "require('esbuild').buildSync({stdin:{contents:process.argv[3],resolveDir:process.argv[1],loader:'tsx'},bundle:true,format:'iife',platform:'browser',jsx:'automatic',loader:{'.css':'css'},outfile:process.argv[2],tsconfig:process.argv[1]+'/tsconfig.json'});", str(WEB), str(bundle), entry], cwd=ROOT, check=True, capture_output=True)
    commands = []
    status = ['accepted']

    def route(request):
        url = request.request.url
        if '/api/execution/steer' in url:
            command = request.request.post_data_json
            commands.append(command)
            if delivery == 'lost_ack' and len(commands) == 1:
                request.abort()
            else:
                request.fulfill(json={'command': {'command_id': command['command_id'], 'status': status[0], 'rejection_code': 'superseded_by_cancel' if status[0] == 'rejected' else None}})
        elif '/api/execution/' in url:
            request.fulfill(json={'snapshot': {'session_id':'reload-steer','execution_id':'exact-execution','status_version':7,'status':'running','capabilities':{'steer':True}}})
        elif url.endswith('/reload.js'):
            request.fulfill(body=bundle.read_text(), content_type='text/javascript; charset=utf-8')
        elif url.endswith('/reload.css'):
            request.fulfill(body=bundle.with_suffix('.css').read_text(), content_type='text/css')
        else:
            request.fulfill(body='<div id="root"></div><link rel="stylesheet" href="/reload.css"><script src="/reload.js"></script>', content_type='text/html; charset=utf-8')

    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        try:
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('http://localhost/**', route)
            page.goto('http://localhost/')
            page.evaluate('submit()')
            expect(page.locator('[data-queued-message]')).to_have_count(1)
            assert len(commands) == 1
            original = commands[0]
            if delivery == 'stopped':
                page.evaluate('hold()')
            page.reload()
            expect(page.locator('[data-queued-message]')).to_contain_text('retain my instruction')
            page.wait_for_function('rows()[0]?.steerCommand && !rows()[0].injecting')
            assert len(commands) >= 2
            assert all(command == original for command in commands)
            assert page.evaluate('ordinary.length') == 0
            status[0] = 'rejected' if delivery == 'stopped' else 'applied'
            page.evaluate('confirm()')
            if delivery == 'stopped':
                expect(page.locator('[data-queued-message]')).to_contain_text('Not sent')
                page.reload()
                expect(page.locator('[data-queued-message]')).to_contain_text('Not sent')
                assert page.evaluate('rows()[0].steerError') == 'cancelled'
            else:
                expect(page.locator('[data-queued-message]')).to_have_count(0)
                page.reload()
                assert page.evaluate('rows().length') == 0
            assert page.evaluate('ordinary.length') == 0
            assert not errors, errors
        finally:
            browser.close()
