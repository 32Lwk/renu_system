from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import csv
from typing import Any, Callable, Tuple

from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeSerializer

from app.core.config import get_settings
from app.core.roles import MemberRole, TeamRole, parse_team_roles, get_overall_role
from app.services.sheet_client import get_sheet_client
from app.services.sheet_schemas import SheetName, MembersColumns


def _get_serializer() -> URLSafeSerializer:
    settings = get_settings()
    return URLSafeSerializer(settings.secret_key, salt="member-session")


def create_member_session_cookie(response, member_id: str) -> None:
    s = _get_serializer()
    payload = {
        "sub": member_id,
        "exp": int((datetime.utcnow() + timedelta(hours=8)).timestamp()),
    }
    token = s.dumps(payload)
    response.set_cookie(
        "member_session",
        token,
        httponly=True,
        max_age=8 * 60 * 60,
        secure=False,
        samesite="lax",
    )


def get_current_member_id(request: Request) -> str:
    token = request.cookies.get("member_session")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    s = _get_serializer()
    try:
        data = s.loads(token)
    except BadSignature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    if "exp" in data and int(data["exp"]) < int(datetime.utcnow().timestamp()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    member_id = str(data.get("sub", "")).strip()
    if not member_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    return member_id


def _load_member_row(member_id: str) -> dict[str, Any]:
    """member_id に対応する members レコードを Sheets / testdata から取得する。"""
    settings = get_settings()
    data_source = settings.data_source.lower()

    # Sheets モードではまず docs/testdata を優先
    if data_source == "sheets":
        base_dir = Path(__file__).resolve().parent.parent.parent
        csv_path = base_dir / "docs" / "testdata" / "members.csv"
        if csv_path.exists():
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if str(row.get(MembersColumns.MEMBER_ID, "")) == str(member_id):
                        return dict(row)
        # なければ本物の Sheets を参照
        client = get_sheet_client()
        records = client.get_all_records(SheetName.MEMBERS)
        for rec in records:
            if str(rec.get(MembersColumns.MEMBER_ID, "")) == str(member_id):
                return dict(rec)
        return {}

    # mockdb モードでは members シートは必須ではないが、将来拡張に備えて同じパスを試みる
    base_dir = Path(__file__).resolve().parent.parent.parent
    csv_path = base_dir / "docs" / "testdata" / "members.csv"
    if csv_path.exists():
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if str(row.get(MembersColumns.MEMBER_ID, "")) == str(member_id):
                    return dict(row)
    return {}


def get_current_member_and_roles(
    member_id: str = Depends(get_current_member_id),
) -> Tuple[dict[str, Any], list[TeamRole], MemberRole]:
    """依存関数: セッション中のメンバー情報とロール情報を返す。"""
    row = _load_member_row(member_id)
    team_roles = parse_team_roles(row) if row else []
    overall = get_overall_role(team_roles)
    return row, team_roles, overall


def require_min_role(min_role: MemberRole) -> Callable:
    """FastAPI 用 Depends ファクトリ: 最低ロールを満たさない場合 403 にする。"""

    def dependency(
        ctx: Tuple[dict[str, Any], list[TeamRole], MemberRole] = Depends(get_current_member_and_roles),
    ) -> Tuple[dict[str, Any], list[TeamRole], MemberRole]:
        member_row, team_roles, overall = ctx
        if overall < min_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return member_row, team_roles, overall

    return dependency


