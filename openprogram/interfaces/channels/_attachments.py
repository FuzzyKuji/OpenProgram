"""入站附件单点 — 下载落盘 + 转成 agent turn 的输入.

adapter 只在 parse 时把 platform 附件元数据填进
:class:`._message.Attachment`; 下载发生在 base 的 per-message 线程里
(不堵 poll loop), 文件落在账号状态目录:

    <state>/channels/<channel>/accounts/<account_id>/attachments/

之后两条腿:

* 图片 (png/jpeg/webp/gif, ≤ :data:`IMAGE_INLINE_BYTES`) 额外转成
  TurnRequest.attachments 的 image block (base64) — vision 模型直接看.
* 每个落盘文件都在 user_text 里追加一行
  ``[attachment: <绝对路径> (<mime>, <size>)]`` — agent 用文件工具打开.
  非图片文件只有这条腿.

平台差异:

* telegram — Attachment 只带 ``file_id``, 下载时经 getFile 解析出
  临时 URL (需要 bot token, 单点在这里).
* slack    — ``url_private`` 需要 Bearer bot token, adapter 已把
  header 填进 Attachment.headers.
* discord  — CDN URL 直接可下.
* wechat   — 媒体在腾讯 CDN 上, AES-128-ECB 加密; Attachment 带
  ``aes_key``, 下载时边收边解密 (协议见 :mod:`._wechat_media`).
  CDN 只回 octet-stream, 图片 MIME 从解密后的文件头认.
"""
from __future__ import annotations

import base64
import logging
import mimetypes
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Iterable

import httpx

from openprogram.interfaces.channels import _wechat_media
from openprogram.interfaces.channels import accounts as _accounts
from openprogram.interfaces.channels._message import Attachment
from openprogram.host.security.safe_http import safe_client
from openprogram.host.security.url_policy import URLPolicyError, normalize_origin

_log = logging.getLogger(__name__)


#: 单个附件下载上限 (字节). 超限跳过并记日志.
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
#: 图片额外作为 vision 输入的上限 (字节) — 更大的图片仍落盘, 只走
#: 文件路径那条腿.
IMAGE_INLINE_BYTES = 4 * 1024 * 1024
IMAGE_MIMES = ("image/png", "image/jpeg", "image/webp", "image/gif")

_SAFE_NAME = re.compile(r"[^\w.\-]+")


def attachments_dir(channel: str, account_id: str) -> Path:
    d = _accounts.account_dir(channel, account_id) / "attachments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def download_inbound(
    channel: str, account_id: str, attachments: Iterable[Attachment],
) -> list[dict]:
    """把入站附件下载到账号附件目录. 返回落盘清单, 每项::

        {"path": "<绝对路径>", "name": ..., "mime": ..., "size": <bytes>}

    单个附件失败 (太大 / 网络 / 解析不出 URL) 打日志并跳过, 不影响
    其余附件和消息本身.
    """
    tag = f"{channel}:{account_id}"
    saved: list[dict] = []
    for att in attachments or ():
        if att.size and att.size > MAX_DOWNLOAD_BYTES:
            _log.warning("[%s] attachment %r skipped: %s bytes exceeds %s",
                         tag, att.name, att.size, MAX_DOWNLOAD_BYTES)
            continue
        url, headers = att.url, dict(att.headers or ())
        if not url and att.file_id and channel == "telegram":
            resolved = _resolve_telegram_file(account_id, att.file_id)
            if resolved is None:
                _log.warning("[%s] attachment %r skipped: telegram getFile failed",
                             tag, att.name)
                continue
            url = resolved
        if not url:
            _log.warning("[%s] attachment %r skipped: no download URL", tag, att.name)
            continue
        try:
            row = _download_one(channel, account_id, att, url, headers)
        except httpx.RequestError as e:
            _log.warning("[%s] attachment %r download failed: %s for %s",
                         tag, att.name, type(e).__name__, normalize_origin(url))
            continue
        except Exception as e:  # noqa: BLE001
            detail = (
                e.reason
                if isinstance(e, URLPolicyError)
                else type(e).__name__
            )
            _log.warning("[%s] attachment %r download failed: %s", tag, att.name, detail)
            continue
        if row is not None:
            saved.append(row)
    return saved


def _download_one(
    channel: str, account_id: str, att: Attachment,
    url: str, headers: dict,
) -> dict | None:
    consumer = {
        "slack": "channel.slack.attachment",
        "telegram": "channel.telegram.attachment",
        "wechat": "channel.wechat.cdn",
    }.get(channel, "channel.attachment.download")
    decryptor = _wechat_media.Decryptor(bytes.fromhex(att.aes_key)) if att.aes_key else None
    folder = attachments_dir(channel, account_id)
    with safe_client(consumer) as client:
        with client.stream("GET", url, headers=headers, timeout=60) as response:
            if not response.is_success:
                _log.warning("[%s:%s] attachment %r download HTTP %s",
                             channel, account_id, att.name, response.status_code)
                return None
            mime = att.mime or (
                "" if decryptor else
                response.headers.get("Content-Type", "").partition(";")[0]
            )
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".download.", dir=folder
            )
            temporary = Path(temporary_name)
            size = 0
            head = b""
            try:
                try:
                    output = os.fdopen(descriptor, "wb")
                except BaseException:
                    os.close(descriptor)
                    raise
                with output:
                    for chunk in response.iter_bytes():
                        if decryptor is not None:
                            chunk = decryptor.update(chunk)
                        if len(head) < 16:
                            head += chunk[:16]
                        output.write(chunk)
                        size += len(chunk)
                        if size > MAX_DOWNLOAD_BYTES:
                            raise ValueError("attachment exceeds download limit")
                    if decryptor is not None:
                        tail = decryptor.finish()
                        head = (head + tail)[:16] if len(head) < 16 else head
                        output.write(tail)
                        size += len(tail)
                    output.flush()
                    os.fsync(output.fileno())
                if not mime:
                    mime = _wechat_media.sniff_image_mime(head) or "application/octet-stream"
                dest = folder / _dest_name(att.name, mime)
                os.replace(temporary, dest)
            finally:
                temporary.unlink(missing_ok=True)
    return {
        "path": str(dest),
        "name": att.name or dest.name,
        "mime": mime,
        "size": size,
    }


def _dest_name(name: str, mime: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    uid = uuid.uuid4().hex[:8]
    safe = _SAFE_NAME.sub("_", name or "").strip("._")[:80]
    if not safe:
        ext = mimetypes.guess_extension(mime or "") or ""
        safe = f"file{ext}"
    return f"{stamp}-{uid}-{safe}"


def _resolve_telegram_file(account_id: str, file_id: str) -> str | None:
    """telegram file_id → 可下载 URL (getFile). 失败返回 None."""
    creds = _accounts.load_credentials("telegram", account_id)
    token = creds.get("bot_token")
    if not token:
        return None
    try:
        with safe_client("channel.telegram.api") as client:
            r = client.get(
                f"https://api.telegram.org/bot{token}/getFile",
                params={"file_id": file_id},
                timeout=15,
            )
        data = r.json() if r.is_success else {}
        file_path = (data.get("result") or {}).get("file_path")
        if not data.get("ok") or not file_path:
            return None
        return f"https://api.telegram.org/file/bot{token}/{file_path}"
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# 落盘清单 → agent turn 输入
# ---------------------------------------------------------------------------

def to_turn_attachments(saved: list[dict]) -> list[dict]:
    """落盘清单里的小图片 → TurnRequest.attachments image block."""
    out: list[dict] = []
    for row in saved:
        if row.get("mime") not in IMAGE_MIMES:
            continue
        if int(row.get("size") or 0) > IMAGE_INLINE_BYTES:
            continue
        try:
            data = Path(row["path"]).read_bytes()
        except OSError:
            continue
        out.append({
            "type": "image",
            "data": base64.b64encode(data).decode("ascii"),
            "media_type": row["mime"],
        })
    return out


def attachment_notes(saved: list[dict]) -> list[str]:
    """每个落盘文件一行标记, 追加到 user_text — agent 拿路径用文件工具读,
    网页聊天流拿同一条标记渲染成可点开的 chip.

    词法跟网页上传那侧完全一致 (:func:`openprogram.state.attachments.format_marker`).
    这里以前写的是 ``[attachment: <绝对路径> (<mime>, <N> bytes)]``:
    另一套写法, 网页的 chip 正则两条都对不上, 于是从 Telegram 发进来的
    图片在网页上打开同一会话时, 那行标记被当成正文 markdown 渲染出来.
    两侧共用一个 formatter 就不会再各走各的.
    """
    from openprogram.state.attachments import format_marker
    return [
        format_marker(
            row.get("name") or Path(row["path"]).name,
            row["path"],
            int(row.get("size") or 0),
            mime=row.get("mime") or "",
        )
        for row in saved
    ]
