from __future__ import annotations

from datetime import timedelta, datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from itsdangerous import URLSafeSerializer, BadSignature

from app.core.config import get_settings


security = HTTPBasic()


def _get_serializer() -> URLSafeSerializer:
    settings = get_settings()
    return URLSafeSerializer(settings.secret_key, salt="admin-session")


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    settings = get_settings()
    if not settings.admin_password_hash:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_PASSWORD_HASH is not configured",
        )

    # シンプルに平文比較にしておき、実運用ではハッシュ値を設定してもらう想定
    if credentials.username != "admin" or credentials.password != settings.admin_password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def create_admin_session_cookie(response, username: str) -> None:
    s = _get_serializer()
    payload = {
        "sub": username,
        "exp": int((datetime.utcnow() + timedelta(hours=8)).timestamp()),
    }
    token = s.dumps(payload)
    response.set_cookie(
        "admin_session",
        token,
        httponly=True,
        max_age=8 * 60 * 60,
        secure=False,
        samesite="lax",
    )


def get_current_admin(request: Request) -> str:
    token = request.cookies.get("admin_session")
    if not token:
        # 未ログイン時は 401 ではなくログイン画面へリダイレクト
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            detail="Not authenticated",
            headers={"Location": "/admin/login"},
        )
    s = _get_serializer()
    try:
        data = s.loads(token)
    except BadSignature:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            detail="Invalid session",
            headers={"Location": "/admin/login"},
        )
    if "exp" in data and int(data["exp"]) < int(datetime.utcnow().timestamp()):
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            detail="Session expired",
            headers={"Location": "/admin/login"},
        )
    return str(data.get("sub", "admin"))


def optional_admin_session(request: Request) -> str | None:
    """admin_session クッキーが有効ならユーザー名を返す。無ければ None。"""
    token = request.cookies.get("admin_session")
    if not token:
        return None
    s = _get_serializer()
    try:
        data = s.loads(token)
    except BadSignature:
        return None
    if "exp" in data and int(data["exp"]) < int(datetime.utcnow().timestamp()):
        return None
    return str(data.get("sub", "admin"))


def optional_member_session(request: Request) -> str | None:
    """member_session から member_id を返す。無効なら None。"""
    from app.core.member_session import _get_serializer as _mem_ser

    token = request.cookies.get("member_session")
    if not token:
        return None
    s = _mem_ser()
    try:
        data = s.loads(token)
    except BadSignature:
        return None
    if "exp" in data and int(data["exp"]) < int(datetime.utcnow().timestamp()):
        return None
    mid = str(data.get("sub", "")).strip()
    return mid or None

