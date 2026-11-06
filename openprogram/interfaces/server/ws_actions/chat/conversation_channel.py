"""The ``set_conversation_channel`` action."""
from __future__ import annotations

import logging
import json

_log = logging.getLogger(__name__)


async def handle_set_conversation_channel(ws, cmd: dict):
    """Bind (or unbind) a conversation to a chat channel + account.

    Enforces 1:1 ownership: stealing a (channel, account) slot evicts
    any prior owner back to local. Persists the binding to SessionDB
    when the conv already has a row.
    """
    from openprogram.interfaces.server import server as _s
    session_id = cmd.get("session_id")
    ch = (cmd.get("channel") or "").strip().lower() or None
    acct_id = (cmd.get("account_id") or "").strip() or None
    peer = (cmd.get("peer") or "").strip() or None
    peer_display = (cmd.get("peer_display") or "").strip() or None
    ok = False
    err = None
    if not session_id:
        err = "session_id required"
    else:
        with _s._sessions_lock:
            conv = _s._sessions.get(session_id)
        if conv is None:
            err = f"unknown conversation {session_id!r}"
        elif ch is None and (acct_id or peer):
            err = "channel must be set when account_id / peer is set"
        else:
            evicted_ids: list[str] = []
            if ch:
                from openprogram.runtime.context.session_db import default_db
                db_pre = default_db()
                db_owners = set(db_pre.sessions_with_binding(ch, acct_id))
                with _s._sessions_lock:
                    mem_owners = {
                        oid for oid, o in _s._sessions.items()
                        if o.get("channel") == ch and o.get("account_id") == acct_id
                    }
                candidates = (db_owners | mem_owners) - {session_id}
                for oid in candidates:
                    with _s._sessions_lock:
                        other = _s._sessions.get(oid)
                        if other is not None:
                            other["channel"] = None
                            other["account_id"] = None
                            other["peer"] = None
                            other["peer_display"] = None
                    try:
                        if db_pre.get_session(oid) is not None:
                            db_pre.update_session(
                                oid,
                                channel=None,
                                account_id=None,
                                peer=None,
                                peer_display=None,
                            )
                    except Exception as ex:
                        _s._log(f"[set_conversation_channel] evict {oid} db: {ex}")
                    evicted_ids.append(oid)

            _ch_val = ch
            _acct_val = acct_id if ch else None
            _peer_val = peer if ch else None
            _pd_val = (peer_display if ch else None) if peer_display is not None else None
            try:
                from openprogram.runtime.context.session_db import default_db
                db = default_db()
                _update_kw = {
                    "channel": _ch_val,
                    "account_id": _acct_val,
                    "peer": _peer_val,
                }
                if peer_display is not None:
                    _update_kw["peer_display"] = _pd_val
                if db.get_session(session_id) is not None:
                    db.update_session(session_id, **_update_kw)
                ok = True
            except Exception as e:
                err = f"persist failed: {type(e).__name__}: {e}"

            for oid in evicted_ids:
                try:
                    await ws.send_text(json.dumps({
                        "type": "session_channel_updated",
                        "data": {
                            "session_id": oid,
                            "ok": True,
                            "channel": None,
                            "account_id": None,
                            "peer": None,
                            "evicted_by": session_id,
                        },
                    }, default=str))
                except Exception:
                    # Evicted session's peers see the change on their next
                    # load.
                    _log.debug(
                        "channel eviction notice not broadcast for %s", oid, exc_info=True)
    await ws.send_text(json.dumps({
        "type": "session_channel_updated",
        "data": {
            "session_id": session_id,
            "ok": ok,
            "channel": ch,
            "account_id": acct_id,
            "peer": peer,
            "error": err,
        },
    }, default=str))
