"""Gmail API 経由のメール送信（リフレッシュトークン）。"""

from __future__ import annotations

import base64
import html
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from app.core.config import get_settings


def _body_to_html_fragment(body_text: str) -> str:
    """入力した改行をそのまま見せる HTML（プレーンテキスト互換）。"""
    esc = html.escape(body_text or "", quote=False)
    return (
        '<div style="white-space:pre-wrap;word-break:break-word;line-height:1.65;'
        "font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        'font-size:15px;color:#1f2937;max-width:640px;padding:4px 0;">'
        f"{esc}</div>"
    )


def _refresh_access_token() -> str:
    s = get_settings()
    if not (
        s.gmail_client_id
        and s.gmail_client_secret
        and s.gmail_refresh_token
    ):
        raise RuntimeError("Gmail OAuth 設定（client_id / client_secret / refresh_token）が不足しています")
    r = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": s.gmail_client_id,
            "client_secret": s.gmail_client_secret,
            "refresh_token": s.gmail_refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30.0,
    )
    r.raise_for_status()
    data = r.json()
    tok = data.get("access_token")
    if not tok:
        raise RuntimeError(f"アクセストークン取得失敗: {data}")
    return str(tok)


def send_gmail_message(
    to_addresses: list[str],
    subject: str,
    body_text: str,
    *,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> None:
    """To に1通ずつ送信（Bcc は各宛先に個別送信しない。To が複数なら1通に複数 To）。"""
    settings = get_settings()
    from_addr = (settings.gmail_from_address or "").strip()
    if not from_addr:
        raise RuntimeError("gmail_from_address が未設定です")
    from_name = (settings.gmail_from_name or "").strip()
    access = _refresh_access_token()

    to_clean = [x.strip() for x in to_addresses if x and x.strip()]
    if not to_clean:
        raise ValueError("送信先メールアドレスがありません")

    msg = MIMEMultipart("alternative")
    if from_name:
        msg["From"] = f"{from_name} <{from_addr}>"
    else:
        msg["From"] = from_addr
    msg["To"] = ", ".join(to_clean)
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = ", ".join(x.strip() for x in cc if x and x.strip())
    plain = body_text.replace("\r\n", "\n").replace("\r", "\n")
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(_body_to_html_fragment(plain), "html", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    resp = httpx.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        headers={"Authorization": f"Bearer {access}"},
        json={"raw": raw},
        timeout=60.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Gmail API エラー {resp.status_code}: {resp.text}")


def send_gmail_per_recipient(
    recipients: list[tuple[str, str]],
    subject: str,
    body_template: str,
) -> list[tuple[str, str, str]]:
    """(email, member_id) ごとに1通。body_template の {name} を差し込み可能。

    戻り値: [(member_id, email, status), ...] status は ok / error:...
    """
    results: list[tuple[str, str, str]] = []
    for email, mid in recipients:
        name = ""
        body = body_template
        try:
            send_gmail_message([email], subject, body)
            results.append((mid, email, "ok"))
        except Exception as e:
            results.append((mid, email, f"error:{e}"))
    return results
