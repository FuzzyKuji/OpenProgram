"""Inbound-message → agent-session dispatcher.

Each channel backend calls :func:`dispatch_inbound` for every incoming
external message. 该函数协调:

  1. 路由 ``(channel, account_id, peer)`` 到具体 agent (binding / alias)
  2. 算出 session_key (按 agent.session_scope + reset policy)
  3. 加载 / 创建 session (SessionDB)
  4. 跑 agent turn (process_user_turn)
  5. 可选 progress streaming: 实时编辑占位消息显示工具进度
  6. 把消息持久化 + 给 webui WS 推一份

子模块拆分:

  _session_store.py    session 路径、创建、加载、保存、默认标题
  _session_routing.py  session_key 计算 + reset policy
  _broadcast.py        webui WS push

本文件只承担 dispatch_inbound 主流程 + progress streaming state (跟
dispatch 流程紧绑, 不适合拆出去因为需要在 closure 里共享 state).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Optional

from openprogram.runtime.events import emit_ws_frame as _emit_ws_frame
from openprogram.runtime.agent_registry import manager as _agents
from openprogram.interfaces.channels import bindings as _bindings
from openprogram.interfaces.channels._broadcast import (
    broadcast_channel_turn as _broadcast_channel_turn,
    poke_live_webui as _poke_live_webui,
)
from openprogram.interfaces.channels._session_routing import (
    apply_reset_policy as _apply_reset_policy,
    session_key_for_agent as _session_key_for_agent,
    start_new_generation,
)
from openprogram.interfaces.channels._session_store import (
    load_or_init_session as _load_or_init_session,
)


# ---------------------------------------------------------------------------
# Per-session 串行化
# ---------------------------------------------------------------------------

# 同 session 串行队列: session_key → Lock. dispatcher 对同一 session 的并发
# turn 没有锁, 两条消息同时到会交错写库. 锁在 turn 全程持有, 同 session 的
# 下一条消息排队, 不同 session 并行.
# ponytail: 锁表随 session_key 单调增长不回收; 每 key 一个 Lock 很小, 真成
# 问题再换带回收的表.
_log = logging.getLogger(__name__)

_SESSION_LOCKS: dict[str, threading.Lock] = {}
_SESSION_LOCKS_GUARD = threading.Lock()


def _session_lock_for(session_key: str) -> threading.Lock:
    with _SESSION_LOCKS_GUARD:
        lock = _SESSION_LOCKS.get(session_key)
        if lock is None:
            lock = _SESSION_LOCKS[session_key] = threading.Lock()
        return lock


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def dispatch_inbound(
    *,
    channel: str,
    account_id: str,
    peer_kind: str,
    peer_id: str,
    user_text: str,
    user_display: str = "",
    speaker_id: str | None = None,
    speaker_display: str | None = None,
    progress_stream: bool = False,
    attachments: Optional[list[dict]] = None,
    block_stream: bool = False,
    ambient: bool = False,
    memory_mode: str = "on",
    thread_id: Optional[str] = None,
) -> Optional[str]:
    """End-to-end inbound handling.

    ``attachments`` — TurnRequest.attachments 形状的 image block 列表
    (base 已下载落盘并转好 base64), 直接透传给 dispatcher; None = 无.

    ``progress_stream=False`` (default): 旧行为, 返回完整 assistant reply
    字符串供 adapter 自己发. 调用方拿到字符串后用 platform SDK / outbound
    发回去.

    ``progress_stream=True``: 进入 streaming 模式. dispatch 内部会:
       1. 先在目标 chat 发一条占位消息 "⏳ working...", 拿到 message_id
       2. 接 dispatcher emit 的 stream envelope, 按 tool 事件实时 edit 占位
          ("⚙ bash" → "✓ bash" → "⚙ read" → ...), 节流 1s 一次
       3. 最终用完整 reply edit 占位 (超长则占位放第一段 + 尾段发新消息)
       4. 返回 None 表示 adapter 不需要再发 reply
    任何 streaming 步骤失败 (占位发不出 / 平台不支持 edit / WeChat) 都会
    无声降级回非 streaming 行为, 返回 reply 字符串.

    ``block_stream=True`` (不能 edit 的平台, 即 WeChat): 没有占位消息时
    回复边生成边按段落发出 (见 :class:`_BlockStreamer`), 工具调用前写
    的那句话也会先发出去; 全部发完返回 None.

    ``ambient=True`` (群里没点名机器人的房间事件): 不发占位、不分段,
    最终回复只留在记录里, 返回 None; agent 要开口得调 ``chat_send``.

    ``memory_mode`` — 房间的 ``/memory`` 设置 (``on`` / ``read`` /
    ``off``), 经 ``memory_policy_override`` 收窄这一轮的记忆.

    ``thread_id`` — 入站消息所在的 thread (Slack ``thread_ts`` /
    Telegram 论坛话题). 占位、回复、文件都发回这个 thread; 不参与
    session 路由.

    Never raises into the channel's poll loop — any failure (no
    provider configured, runtime crash, etc.) is flattened into an
    error-shaped reply string that the bot can surface to the user
    rather than silently dropping the message.
    """
    peer = {"kind": peer_kind or "direct", "id": str(peer_id)}

    # 事件层 tap：外部消息进来了（B 类，不属于任何 turn）。懒 import 防循环。
    from openprogram.runtime.events import emit_safe
    emit_safe("channel.message_inbound", "user",
              {"channel": channel, "peer_kind": peer["kind"],
               "chars": len(user_text or "")})

    route = _route(channel, account_id, peer)
    if isinstance(route, str):
        return route
    agent_id, session_key, _base_key = route

    # ---- /answer · /decline 文本命令拦截 -------------------------------
    # 函数 runtime.ask 在本 channel 会话里挂了个待答问题，用户用一条
    # /answer <qid> <choice> 文本消息回答（聊天软件没有网页那种问题卡片）。
    # 命中且该 qid 属于本 session 才 resolve 并回执，不走 agent dispatch；
    # 否则（不是命令 / qid 不属于本 session）返回 None，照常进 agent。
    _question_actor = _channel_authority(
        channel, account_id, speaker_id or "", speaker_display or user_display,
    )
    _question_actor.update({
        "project_ids": ["default"],
        "session_ids": [session_key],
        "execution_actions": ["execution.wait.answer", "execution.wait.decline"],
    })
    from openprogram.interfaces.channels._question_commands import try_handle_question_command
    from openprogram.interfaces.channels import _active_turns
    _running = _active_turns.get(session_key)
    if (_running is not None and _running.peer_kind != "direct"
            and _running.speaker_id != (speaker_id or "")
            and (user_text or "").lstrip().lower().startswith(("/answer", "/decline"))):
        # 群里一轮停在提问上时, 只有发起这一轮的人能回答.
        return "只有发起这个问题的人可以回答它。"
    _receipt = try_handle_question_command(
        user_text, session_key, actor=_question_actor,
    )
    if _receipt is not None:
        return _receipt

    # ---- 同 session 串行 ------------------------------------------------
    # /answer·/decline 必须在锁外处理 (上面已 return): turn 停在
    # runtime.ask 时持锁等待, /answer 若也抢锁就自死锁.
    with _session_lock_for(session_key):
        return _run_session_turn(
            channel=channel, account_id=account_id, peer=peer,
            peer_id=peer_id, user_text=user_text,
            user_display=user_display, speaker_id=speaker_id,
            speaker_display=speaker_display, progress_stream=progress_stream,
            agent_id=agent_id, session_key=session_key,
            attachments=attachments, block_stream=block_stream,
            ambient=ambient, memory_mode=memory_mode, thread_id=thread_id,
        )


def _channel_authority(
    channel: str, account_id: str, speaker_id: str, display: str,
) -> dict:
    """账号的 ``sender_access``: ``owner`` (默认) 让通过准入的发信人和本机
    主人同权 — 工具、批准照常; ``paired`` 只能回复和用记忆."""
    from openprogram.runtime.permissions.authority import (
        channel_owner_authority, paired_channel_authority,
    )
    from openprogram.interfaces.channels.accounts import sender_access
    if sender_access(channel, account_id) == "owner":
        return channel_owner_authority(channel, account_id, speaker_id, display)
    return paired_channel_authority(channel, account_id, speaker_id, display)


def _sandbox_room_session(
    channel: str, account_id: str, peer: dict, agent_id: str, session_key: str,
) -> None:
    """群聊里谁都能说话, 主人权限的群会话默认开沙盒 (命令只能写工作区).
    只在会话还没设过沙盒开关时写入, 用户在网页里关掉后不再改回."""
    if (peer.get("kind") or "direct") == "direct":
        return
    from openprogram.interfaces.channels.accounts import sender_access
    if sender_access(channel, account_id) != "owner":
        return
    from openprogram.runtime.conversation.session_config import (
        load_session_run_config, save_session_run_config,
    )
    try:
        if load_session_run_config(session_key).sandbox_enabled is None:
            save_session_run_config(
                session_key, agent_id=agent_id, sandbox_enabled=True,
            )
    except Exception:
        _log.warning("could not enable the sandbox for %s", session_key,
                     exc_info=True)


def _route(channel: str, account_id: str, peer: dict):
    """路由: alias > binding. 返回 ``(agent_id, session_key, base_key)``;
    base_key 是重置前的 key (alias 会话固定, 为 None). 出错时返回一条
    给用户看的错误文本."""
    from openprogram.runtime.agent_registry import session_aliases as _aliases
    alias = _aliases.lookup(channel, account_id, peer)
    if alias is not None:
        agent_id, session_key = alias
        if _agents.get(agent_id) is None:
            return (f"[unknown agent {agent_id!r}] — alias points at a "
                    f"deleted agent.")
        return agent_id, session_key, None
    try:
        agent_id = _bindings.route(channel, account_id, peer)
    except Exception as e:  # noqa: BLE001
        return f"[routing error] {type(e).__name__}: {e}"
    if not agent_id:
        return ("[no agent configured] Run `openprogram agents add "
                "main` and configure a provider.")
    agent = _agents.get(agent_id)
    if agent is None:
        return (f"[unknown agent {agent_id!r}] — binding points at a "
                f"deleted agent.")
    base_key = _session_key_for_agent(agent, channel, account_id, peer)
    return agent_id, _apply_reset_policy(agent, base_key), base_key


def start_new_conversation(
    *, channel: str, account_id: str, peer_kind: str, peer_id: str,
) -> str:
    """``/new`` · ``/reset``: 这个 peer 之后的消息进一个新会话. 旧会话
    原样留在库里 (网页侧栏照常能看). 返回给用户的回执."""
    peer = {"kind": peer_kind or "direct", "id": str(peer_id)}
    route = _route(channel, account_id, peer)
    if isinstance(route, str):
        return route
    agent_id, _session_key, base_key = route
    if base_key is None:
        return "这个对话固定绑定在一个会话上，不能重开。"
    with _session_lock_for(_session_key):
        start_new_generation(_agents.get(agent_id), base_key)
    return "✓ 已开始新对话，之前的内容不会带进来。"


def _run_session_turn(
    *,
    channel: str,
    account_id: str,
    peer: dict,
    peer_id: str,
    user_text: str,
    user_display: str,
    speaker_id: str | None,
    speaker_display: str | None,
    progress_stream: bool,
    agent_id: str,
    session_key: str,
    attachments: Optional[list[dict]] = None,
    block_stream: bool = False,
    ambient: bool = False,
    memory_mode: str = "on",
    thread_id: Optional[str] = None,
) -> Optional[str]:
    """路由已完成、session 锁已持有 — 跑一个完整 turn: load session →
    agent turn → 持久化 → broadcast. 返回值语义同 dispatch_inbound."""
    from openprogram.interfaces.channels import _active_turns
    _active_turns.begin(session_key, _active_turns.ActiveTurn(
        channel=channel, account_id=account_id, peer_id=str(peer_id),
        peer_kind=peer.get("kind") or "direct",
        speaker_id=speaker_id or "", ambient=ambient,
    ))
    try:
        return _run_turn_body(
            channel=channel, account_id=account_id, peer=peer,
            peer_id=peer_id, user_text=user_text,
            user_display=user_display, speaker_id=speaker_id,
            speaker_display=speaker_display,
            progress_stream=progress_stream and not ambient,
            agent_id=agent_id, session_key=session_key,
            attachments=attachments,
            block_stream=block_stream and not ambient,
            ambient=ambient, memory_mode=memory_mode, thread_id=thread_id,
        )
    finally:
        _active_turns.end(session_key)


def _run_turn_body(*, channel: str, account_id: str, ambient: bool,
                   thread_id: Optional[str] = None,
                   **kwargs) -> Optional[str]:
    """一个 turn 的兜底: 任何一步意外抛异常 (session 加载等) 都变成一条
    ``[error] …`` 送到用户面前 — 改进占位消息 (改不了就新发); 没有占位
    时返回给 adapter 发. 线程不会无声死掉, 占位不会卡在 "⏳"."""
    turn: dict = {"placeholder": None, "streamer": None}
    try:
        return _run_turn_core(
            channel=channel, account_id=account_id, ambient=ambient,
            thread_id=thread_id, turn=turn, **kwargs,
        )
    except Exception as e:  # noqa: BLE001
        _log.exception("[%s:%s] channel turn failed", channel, account_id)
        err_text = f"[error] {type(e).__name__}: {e}"
        if turn["streamer"] is not None:
            try:
                turn["streamer"].close()
            except Exception:  # noqa: BLE001
                # Already on the error path; the error reply is sent anyway.
                _log.debug("[%s:%s] streamer close failed", channel,
                           account_id, exc_info=True)
        if ambient:
            return None
        if turn["placeholder"] is not None:
            _finish_placeholder(turn["placeholder"], err_text,
                                thread_id=thread_id)
            return None
        return err_text


def _post(channel: str, account_id: str, target: str, text: str,
          thread_id: Optional[str] = None):
    """``_transport.post_message``; thread_id 只在有值时传, 不在 thread
    里时调用形状和以前一样."""
    from openprogram.interfaces.channels import _transport
    if thread_id:
        return _transport.post_message(channel, account_id, target, text,
                                       thread_id=thread_id)
    return _transport.post_message(channel, account_id, target, text)


def _finish_placeholder(handle, text: str, *,
                        thread_id: Optional[str] = None) -> None:
    """把占位消息改成最终文本. 按渲染后长度判断: 一条放不下时占位放
    第一段, 余下新发. edit 失败 (限流重试耗尽 / 占位被删 / 网络) 时整段
    改成新发 — 回复不能因为 edit 失败而丢."""
    from openprogram.interfaces.channels import _transport
    head, tail = _transport.split_for_edit(
        handle.platform, text, "\n... (continued ↓)")
    try:
        result = _transport.patch_message(
            handle.platform, handle.account_id, handle.target,
            handle.message_id, head,
        )
    except Exception as e:  # noqa: BLE001
        result = _transport.SendResult.fail(
            "unknown", f"{type(e).__name__}: {e}")
    pending = tail
    if not result.ok:
        _log.warning("[%s:%s] placeholder edit failed (%s); sending the "
                     "reply as a new message", handle.platform,
                     handle.account_id, result.error_kind)
        pending = text
    if not pending:
        return
    try:
        sent = _post(handle.platform, handle.account_id, handle.target,
                     pending, thread_id)
    except Exception as e:  # noqa: BLE001
        sent = _transport.SendResult.fail("unknown", f"{type(e).__name__}: {e}")
    if not sent.ok:
        _log.warning("[%s:%s] reply send failed: %s: %s", handle.platform,
                     handle.account_id, sent.error_kind, sent.error_detail)


def _run_turn_core(
    *,
    channel: str,
    account_id: str,
    peer: dict,
    peer_id: str,
    user_text: str,
    user_display: str,
    speaker_id: str | None,
    speaker_display: str | None,
    progress_stream: bool,
    agent_id: str,
    session_key: str,
    attachments: Optional[list[dict]],
    block_stream: bool,
    ambient: bool,
    memory_mode: str,
    thread_id: Optional[str],
    turn: dict,
) -> Optional[str]:
    # ---- session 创建 / 加载 -------------------------------------------
    meta, _ = _load_or_init_session(
        agent_id=agent_id,
        session_key=session_key,
        channel=channel,
        account_id=account_id,
        peer=peer,
        user_display=user_display or str(peer_id),
    )
    _sandbox_room_session(channel, account_id, peer, agent_id, session_key)

    # ---- run config 加载 (permission/tools/effort) ---------------------
    from openprogram.runtime.conversation.session_config import (
        load_session_run_config,
        permission_from_config,
        tools_override_from_config,
        project_defaults,
    )
    from openprogram.runtime.permissions.rule import load_merged_rules as _load_merged_rules
    run_cfg = load_session_run_config(session_key)
    _pdef = project_defaults(session_key)

    # ---- progress streaming state ---------------------------------------
    # 仅在 progress_stream=True 且占位发送成功后激活. progress_handle 为
    # None 时所有 streaming-edit 逻辑跳过, 保持旧行为.
    progress_handle = None
    progress_lines: list[str] = []
    last_edit_ts: list[float] = [0.0]

    if progress_stream:
        try:
            from openprogram.interfaces.channels.base import MessageHandle as _MH
            _result = _post(
                channel, account_id, str(peer_id), "⏳ working...", thread_id,
            )
            if _result.ok and _result.message_id:
                _h = _MH(channel, account_id, str(peer_id), _result.message_id)
                if _h.editable:
                    progress_handle = _h
                    turn["placeholder"] = _h
                # 不 editable (WeChat 空 message_id) → 降级回非 streaming,
                # 占位仍然发出去了但不参与后续 edit. WeChat 在这种降级下
                # 用户看到的是 "⏳..." 加上一条完整 reply, 不完美但不
                # 出错.
        except Exception:
            progress_handle = None

    def _maybe_edit(text: str, *, force: bool = False):
        """节流的 progress edit. 至少 1 秒间隔, force=True 跳过节流.
        返回 patch 的 SendResult; 被节流或没有占位时返回 None. 最终回复
        和错误回复走 :func:`_finish_placeholder` (edit 失败会改成新发)."""
        if progress_handle is None:
            return None
        now = time.time()
        if not force and now - last_edit_ts[0] < 1.0:
            return None
        last_edit_ts[0] = now
        from openprogram.interfaces.channels import _transport
        try:
            return _transport.patch_message(
                progress_handle.platform, progress_handle.account_id,
                progress_handle.target, progress_handle.message_id, text,
            )
        except Exception as e:  # noqa: BLE001
            return _transport.SendResult.fail(
                "unknown", f"{type(e).__name__}: {e}")

    streamer = (
        _BlockStreamer(channel, account_id, str(peer_id), thread_id=thread_id)
        if block_stream and progress_handle is None else None
    )
    turn["streamer"] = streamer

    # ---- canonical Agent admission + stream event 监听 ------------------
    from openprogram.runtime.agent.turn_request import TurnRequest
    from openprogram.runtime.conversation.production_driver import CanonicalAgentAdapter

    captured_user_id: list[str] = []

    def _own_turn(msg_id) -> bool:
        # 本轮的事件带 chat_ack 里的用户消息 id (或它的 _reply); 同一
        # session 里子 agent 的流不发到聊天里.
        if msg_id is None or not captured_user_id:
            return msg_id is None
        return msg_id in (captured_user_id[0], f"{captured_user_id[0]}_reply")

    def _on_event(env: dict) -> None:
        # 转发给 webui WS — 走事件总线 (ws.frame 事件), webui 订阅后原样
        # 广播. turn 级 channel_turn / agent_session_updated 已走同一机制
        # (_broadcast.py); 这里把流式帧也从"摸 webui 私有 _broadcast"改过来.
        _emit_ws_frame(env)
        if env.get("type") == "chat_ack":
            data = env.get("data") or {}
            if data.get("msg_id"):
                captured_user_id.append(str(data["msg_id"]))

        data = env.get("data") or {}
        ev = data.get("event") or {}
        ev_type = ev.get("type")
        if (streamer is not None and env.get("type") == "chat_response"
                and data.get("type") == "stream_event"
                and data.get("session_id") in (None, session_key)
                and _own_turn(data.get("msg_id"))):
            if ev_type == "text":
                streamer.feed(ev.get("text") or "")
            elif ev_type == "tool_use":
                streamer.flush()

        # Progress streaming: 按 tool 边界 edit 占位消息.
        if progress_handle is None:
            return
        if ev_type == "tool_use":
            tool_name = ev.get("tool") or "?"
            progress_lines.append(f"⚙ {tool_name}")
            _maybe_edit("\n".join(progress_lines))
        elif ev_type == "tool_result":
            tool_name = ev.get("tool") or "?"
            is_err = bool(ev.get("is_error"))
            marker = "✗" if is_err else "✓"
            # 把最近一个 "⚙ {tool_name}" 改成 "✓/✗ {tool_name}"
            for i in range(len(progress_lines) - 1, -1, -1):
                if progress_lines[i] == f"⚙ {tool_name}":
                    progress_lines[i] = f"{marker} {tool_name}"
                    break
            _maybe_edit("\n".join(progress_lines))

    _authority = _channel_authority(
        channel, account_id, speaker_id or "",
        speaker_display or user_display,
    )
    req = TurnRequest(
        session_id=session_key,
        user_text=user_text,
        agent_id=agent_id,
        source=channel,
        peer_display=user_display or str(peer_id),
        peer_id=str(peer_id),
        permission_mode=permission_from_config(
            run_cfg, default=_pdef.get("permission_mode")),
        permission_rules=_load_merged_rules(session_key),
        additional_working_dirs=run_cfg.additional_working_dirs,
        tools_override=tools_override_from_config(run_cfg),
        thinking_effort=run_cfg.thinking_effort or _pdef.get("thinking_effort"),
        attachments=attachments or None,
        **_authority,
    )
    from openprogram.interfaces.channels._room import memory_override
    req.memory_policy_override = memory_override(memory_mode)
    adapter = CanonicalAgentAdapter(event_sink=_on_event)
    try:
        admission = adapter.admit(
            req,
            trusted_actor=_authority,
            user_message_id=req.user_msg_id,
            config_snapshot_ref=f"channel:{channel}",
        )
        _active, result = asyncio.run(adapter.activate(admission))
    except Exception as e:  # noqa: BLE001
        err_text = f"[error] {type(e).__name__}: {e}"
        if streamer is not None:
            streamer.close()
        if ambient:
            # 没人点名机器人, 别把错误发进群.
            _log.warning("[%s:%s] room event turn failed: %s", channel, account_id, err_text)
            return None
        if progress_handle is not None:
            # 把占位改成错误消息, adapter 不必再发. 用户看到的是单条
            # 带错误的消息, 没 placeholder 残留; 改不了就新发一条.
            _finish_placeholder(progress_handle, err_text, thread_id=thread_id)
            return None
        return err_text

    if result is None:
        if streamer is not None:
            streamer.close()
        if ambient:
            return None
        return "[error] canonical Agent activation produced no result"
    reply_text = (result.final_text or "").strip() or "(empty reply)"
    user_msg_id = result.user_msg_id
    assistant_msg_id = result.assistant_msg_id

    # ---- agent 交出来的文件 → 平台原生附件 -------------------------------
    # ambient 房间事件的回复不进群 (agent 用 chat_send 开口), 附件也不发.
    # reply_text 里的 [attachment: ... @ 路径] 是 send_file 工具登记的.
    # 先把文件真的传上去, 再把标记从"发给平台的那份文本"里拿掉 —— 存进
    # 会话 / 广播给网页的那份 (reply_text) 保留标记, 网页据此画 chip.
    if ambient:
        channel_text = ""
    elif streamer is not None:
        streamer.close()
        unsent = streamer.unsent_part(reply_text)
        channel_text = (
            _deliver_outbound_files(channel, account_id, str(peer_id), unsent,
                                    thread_id=thread_id)
            if unsent.strip() else ""
        )
    else:
        channel_text = _deliver_outbound_files(
            channel, account_id, str(peer_id), reply_text, thread_id=thread_id,
        )

    # ---- 持久化 + webui WS push ----------------------------------------
    user_msg = {
        "role": "user",
        "id": user_msg_id,
        "content": user_text,
        "timestamp": time.time(),
        "source": channel,
        "peer_display": user_display or str(peer_id),
        "peer_id": str(peer_id),
    }
    reply_msg = {
        "role": "assistant",
        "id": assistant_msg_id,
        "content": reply_text,
        "timestamp": time.time(),
        "source": channel,
    }
    # 网页侧推送是旁路: 失败只落日志, 不能挡住回复送达.
    try:
        _broadcast_channel_turn(agent_id, session_key, user_msg, reply_msg)
    except Exception:  # noqa: BLE001
        _log.exception("channel turn broadcast failed for %s", session_key)
    try:
        from openprogram.runtime.context.session_db import default_db
        refreshed = default_db().get_session(session_key)
        if refreshed is not None:
            refreshed.setdefault("_last_touched", time.time())
            _poke_live_webui(agent_id, session_key, refreshed,
                             default_db().get_messages(session_key))
    except Exception:  # noqa: BLE001
        _log.exception("live webui poke failed for %s", session_key)

    # ---- Progress streaming: 把占位 edit 成完整 reply, 返回 None -------
    # 按渲染后长度判断; 放不下时占位放第一段, 余下用新消息追加.
    if progress_handle is not None:
        _finish_placeholder(progress_handle, channel_text, thread_id=thread_id)
        return None

    if ambient:
        return None
    if streamer is not None and streamer.sent_any:
        # 已经分段发出去一部分: 余下的也走这里发掉, adapter 不用再发.
        if channel_text and channel_text != "(empty reply)":
            streamer.send(channel_text)
        return None
    return channel_text


class _BlockStreamer:
    """不能 edit 消息的平台 (WeChat): 回复边生成边按段落发.

    文本增量攒在缓冲里; 缓冲里出现段落边界 (空行) 且前面已经有
    :data:`MIN_CHARS` 字, 就把边界之前的部分发出去. 工具调用开始时整个
    缓冲先发掉 — "我查一下" 这种话应该在机器人去干活之前到. 未闭合的
    代码块里不切. 发送在单独线程里排队, 不阻塞模型的流.

    发出去的始终是流文本的一个前缀; 结束时 :meth:`unsent_part` 用它从
    最终回复 (流文本 + send_file 附件标记) 里算出还没发的部分.
    """

    MIN_CHARS = 200

    def __init__(self, channel: str, account_id: str, target: str,
                 thread_id: Optional[str] = None) -> None:
        import queue
        self.channel = channel
        self.account_id = account_id
        self.target = target
        self.thread_id = thread_id
        self.streamed = ""
        self.sent_upto = 0
        self.sent_any = False
        self._closed = False
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def feed(self, delta: str) -> None:
        if not delta:
            return
        self.streamed += delta
        pending = self.streamed[self.sent_upto:]
        cut = self._paragraph_cut(pending)
        if cut:
            self._emit(cut)

    def flush(self) -> None:
        pending = self.streamed[self.sent_upto:]
        if pending.strip() and pending.count("```") % 2 == 0:
            self._emit(len(pending))

    def _paragraph_cut(self, pending: str) -> int:
        from openprogram.interfaces.channels._transport import MAX_CHARS
        cut = 0
        start = 0
        while True:
            idx = pending.find("\n\n", start)
            if idx < 0:
                break
            end = idx + 2
            if pending[:end].count("```") % 2 == 0 and len(pending[:idx].strip()) >= self.MIN_CHARS:
                cut = end
            start = end
        limit = MAX_CHARS.get(self.channel, 1800)
        if not cut and len(pending) > limit and pending.count("```") % 2 == 0:
            newline = pending.rfind("\n", 0, limit)
            cut = newline + 1 if newline > 0 else limit
        return cut

    def _emit(self, length: int) -> None:
        chunk = self.streamed[self.sent_upto:self.sent_upto + length]
        self.sent_upto += length
        if chunk.strip():
            self.send(chunk.strip())

    def send(self, text: str) -> None:
        self.sent_any = True
        if self._closed:
            self._post(text)
        else:
            self._queue.put(text)

    def _post(self, text: str) -> None:
        try:
            result = _post(
                self.channel, self.account_id, self.target, text,
                self.thread_id,
            )
            if not result.ok:
                _log.warning("[%s:%s] send failed: %s",
                             self.channel, self.account_id, result.error_kind)
        except Exception as e:  # noqa: BLE001
            _log.warning("[%s:%s] send failed: %s",
                         self.channel, self.account_id, type(e).__name__)

    def _drain(self) -> None:
        while True:
            text = self._queue.get()
            if text is None:
                return
            self._post(text)

    def close(self) -> None:
        """等排队的段落按顺序发完; 之后 :meth:`send` 直接同步发."""
        if self._closed:
            return
        self._queue.put(None)
        self._thread.join(timeout=60)
        self._closed = True

    def unsent_part(self, reply_text: str) -> str:
        """最终回复里还没发出去的部分."""
        if not self.sent_any:
            return reply_text
        sent = self.streamed[:self.sent_upto].strip()
        body = reply_text
        if sent and body.startswith(sent):
            return body[len(sent):].strip()
        # 流文本和最终文本对不上 (不该发生): 只补流里没发的那段 +
        # 最终文本里流之外的尾巴 (附件标记).
        tail = body[len(self.streamed.strip()):] if body.startswith(
            self.streamed.strip()) else ""
        return (self.streamed[self.sent_upto:].strip() + tail).strip()


def _deliver_outbound_files(
    channel: str, account_id: str, peer_id: str, reply_text: str,
    *, thread_id: Optional[str] = None,
) -> str:
    """把 reply_text 里的附件标记逐个上传, 返回去掉标记后的平台文本.

    传输层四个平台早就写好了 (``_transport.post_file``), 缺的只是这一步.
    三种结局都不静默:

    * 传成功 — 标记从平台文本里删掉 (文件本身已经在对话里了).
    * 平台不支持 (``post_file`` 返回 not_supported) — 标记改写成一句人能读
      的说明加路径, 学 weclaw 的做法; 既不把原始标记漏给用户, 也不假装
      没这回事.
    * 传失败 (网络 / 太大 / 凭据) — 同样改写成一句说明, 并落日志.
    """
    from openprogram.state.attachments import find_markers
    markers = find_markers(reply_text)
    if not markers:
        return reply_text
    from openprogram.interfaces.channels import _transport
    out = reply_text
    for marker, name, path in markers:
        try:
            result = (
                _transport.post_file(channel, account_id, peer_id, path,
                                     thread_id=thread_id)
                if thread_id else
                _transport.post_file(channel, account_id, peer_id, path)
            )
        except Exception as e:  # noqa: BLE001
            result = _transport.SendResult.fail("unknown", f"{type(e).__name__}: {e}")
        if result.ok:
            out = out.replace(marker, "")
            continue
        _log.warning("[%s:%s] send_file %r failed: %s: %s",
                     channel, account_id, name, result.error_kind, result.error_detail)
        note = (f"(附件 {name} 没能发出来，这个平台不支持文件上传；"
                f"文件在 {path})"
                if result.error_kind == "not_supported"
                else f"(附件 {name} 发送失败：{result.error_kind}；文件在 {path})")
        out = out.replace(marker, note)
    return _collapse_blank_lines(out)


def _collapse_blank_lines(text: str) -> str:
    """删掉标记后留下的空行收拢, 别让平台消息末尾挂一串换行."""
    import re
    return re.sub(r"\n{3,}", "\n\n", text).strip() or "(empty reply)"
