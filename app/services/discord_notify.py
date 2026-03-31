"""Discord Bot API でチャンネルにメッセージ投稿。"""

from __future__ import annotations

import httpx

from app.core.config import get_settings


def post_channel_message(channel_id: str, content: str) -> None:
    token = (get_settings().discord_bot_token or "").strip()
    if not token:
        raise RuntimeError("discord_bot_token が未設定です")
    text = (content or "").strip()
    if not text:
        raise ValueError("本文が空です")
    if len(text) > 2000:
        text = text[:1997] + "..."
    r = httpx.post(
        f"https://discord.com/api/v10/channels/{channel_id.strip()}/messages",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
        },
        json={"content": text},
        timeout=30.0,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Discord API {r.status_code}: {r.text}")
