from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import csv
import logging
from pathlib import Path

import hashlib
import secrets
import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.core.member_session import create_member_session_cookie, get_current_member_id
from app.services.db import SessionLocal, Member as MemberModel
from app.services.sheet_client import get_sheet_client
from app.services.sheet_schemas import (
    SheetName,
    MembersColumns,
    EmailVerificationsColumns,
    get_headers,
)
from app.services.sheet_utils import dict_to_row


templates = Jinja2Templates(directory="app/templates")
router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/auth/dev-login", response_class=HTMLResponse)
async def dev_login_form(request: Request):
    """開発用: テストデータのメンバー一覧から選択してログインする画面。"""
    settings = get_settings()
    if not getattr(settings, "enable_dev_login", False):
        raise HTTPException(status_code=404, detail="Not found")

    members: list[dict[str, Any]] = []
    if settings.data_source.lower() == "mockdb":
        db = SessionLocal()
        try:
            db_members = db.query(MemberModel).order_by(MemberModel.name).all()
            members = [{"id": m.id, "name": m.name, "grade": m.grade} for m in db_members]
        finally:
            db.close()
    else:
        # sheets モード: docs/testdata/members.csv から開発用の候補を読み込む
        base_dir = Path(__file__).resolve().parent.parent.parent
        csv_path = base_dir / "docs" / "testdata" / "members.csv"
        if csv_path.exists():
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    members.append(
                        {
                            "id": row.get(MembersColumns.MEMBER_ID, ""),
                            "name": row.get(MembersColumns.FULL_NAME, ""),
                            "grade": row.get(MembersColumns.GRADE, ""),
                            "teams": row.get(MembersColumns.TEAMS, ""),
                            "roles": row.get(MembersColumns.ROLES, ""),
                        }
                    )

    return templates.TemplateResponse(
        "dev_login.html",
        {
            "request": request,
            "title": "開発用テストログイン | ReNU",
            "members": members,
        },
    )

@router.get("/auth/logout")
async def member_logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("member_session")
    return response


@router.post("/auth/dev-login")
async def dev_login_submit(request: Request, member_id: str = Form(...)):
    """開発用: 選択されたメンバーでログインする。"""
    settings = get_settings()
    if not getattr(settings, "enable_dev_login", False):
        raise HTTPException(status_code=404, detail="Not found")

    member_id = str(member_id).strip()
    data_source = settings.data_source.lower()

    if data_source == "mockdb":
        db_member: MemberModel | None = None
        db = SessionLocal()
        try:
            try:
                mid_int = int(member_id)
            except ValueError:
                mid_int = -1
            db_member = db.query(MemberModel).filter_by(id=mid_int).one_or_none()
        finally:
            db.close()

        if not db_member:
            logger.warning(
                "Dev login failed: member not found (mockdb)",
                extra={"requested_member_id": member_id, "remote_addr": getattr(request.client, "host", None)},
            )
            return templates.TemplateResponse(
                "dev_login.html",
                {
                    "request": request,
                    "title": "開発用テストログイン | ReNU",
                    "members": [],
                    "error": "選択したメンバーが見つかりませんでした。",
                },
                status_code=400,
            )

        effective_member_id = str(db_member.id)
    else:
        # sheets モード: docs/testdata/members.csv に存在する member_id か確認する
        base_dir = Path(__file__).resolve().parent.parent.parent
        csv_path = base_dir / "docs" / "testdata" / "members.csv"
        valid_ids: set[str] = set()
        if csv_path.exists():
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    mid = str(row.get(MembersColumns.MEMBER_ID, "")).strip()
                    if mid:
                        valid_ids.add(mid)

        if member_id not in valid_ids:
            logger.warning(
                "Dev login failed: member not found (sheets)",
                extra={"requested_member_id": member_id, "remote_addr": getattr(request.client, "host", None)},
            )
            # 再度フォームを出すために候補を読み込み直す
            members: list[dict[str, Any]] = []
            if csv_path.exists():
                with csv_path.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        members.append(
                            {
                                "id": row.get(MembersColumns.MEMBER_ID, ""),
                                "name": row.get(MembersColumns.FULL_NAME, ""),
                                "grade": row.get(MembersColumns.GRADE, ""),
                                "teams": row.get(MembersColumns.TEAMS, ""),
                                "roles": row.get(MembersColumns.ROLES, ""),
                            }
                        )
            return templates.TemplateResponse(
                "dev_login.html",
                {
                    "request": request,
                    "title": "開発用テストログイン | ReNU",
                    "members": members,
                    "error": "選択したメンバーが見つかりませんでした。",
                },
                status_code=400,
            )

        effective_member_id = member_id

    logger.info(
        "Dev login used",
        extra={
            "remote_addr": getattr(request.client, "host", None),
            "member_id": effective_member_id,
            "data_source": data_source,
        },
    )

    response = RedirectResponse(url="/my", status_code=302)
    create_member_session_cookie(response, effective_member_id)
    return response


@router.get("/auth/discord/start")
async def discord_oauth_start(request: Request):
    """Discord OAuth 開始エンドポイント。Discord 認可画面へリダイレクトする。"""
    settings = get_settings()
    client_id = settings.discord_client_id
    client_secret = settings.discord_client_secret
    redirect_uri = settings.discord_redirect_uri
    if not client_id or not client_secret or not redirect_uri:
        # 設定不足はログと UI の両方に明示する（ただし秘密情報はログに出さない）
        logger.error(
            "Discord OAuth is not configured",
            extra={
                "discord_client_id_set": bool(client_id),
                "discord_client_secret_set": bool(client_secret),
                "discord_redirect_uri_set": bool(redirect_uri),
            },
        )
        dev_login_available = bool(getattr(settings, "enable_dev_login", False))
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "title": "ReNU 勤怠・シフト管理",
                "error": "現在 Discord ログインは利用できません。管理者に問い合わせてください。",
                "dev_login_available": dev_login_available,
            },
            status_code=503,
        )

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify",
        "prompt": "consent",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"https://discord.com/api/oauth2/authorize?{query}"
    return RedirectResponse(url)


@router.get("/auth/discord/callback")
async def discord_oauth_callback(request: Request, code: str):
    """Discord OAuth コールバック。コードからトークンを取得し、ユーザー情報を members シートに反映する。"""
    settings = get_settings()
    client_id = settings.discord_client_id
    client_secret = settings.discord_client_secret
    redirect_uri = settings.discord_redirect_uri
    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(status_code=500, detail="Discord OAuth is not configured")

    token_url = "https://discord.com/api/oauth2/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to exchange Discord code")
        token_data: dict[str, Any] = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="No access_token from Discord")

        user_resp = await client.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch Discord user")
        user = user_resp.json()

    discord_user_id = str(user.get("id"))
    discriminator = user.get("discriminator")
    discord_username = (
        f'{user.get("username", "")}#{discriminator}' if discriminator else str(user.get("username", ""))
    )

    sheet = get_sheet_client()
    records = sheet.get_all_records(SheetName.MEMBERS)

    # 既存行に同じ discord_user_id があれば更新、なければ新規作成
    target_row_index = None
    for idx, rec in enumerate(records, start=2):  # 1 行目はヘッダー
        if str(rec.get(MembersColumns.DISCORD_USER_ID, "")) == discord_user_id:
            target_row_index = idx
            break

    now = _now_iso()
    if target_row_index is None:
        member_id = f"mem_{secrets.token_hex(8)}"
        values = {
            MembersColumns.MEMBER_ID: member_id,
            MembersColumns.DISCORD_USER_ID: discord_user_id,
            MembersColumns.DISCORD_USERNAME: discord_username,
            MembersColumns.STATUS: "pending",
            MembersColumns.CREATED_AT: now,
            MembersColumns.UPDATED_AT: now,
        }
        row = dict_to_row(get_headers(SheetName.MEMBERS), values)
        sheet.append_row(SheetName.MEMBERS, row)
    else:
        rec = records[target_row_index - 2]
        member_id = str(rec.get(MembersColumns.MEMBER_ID, "")).strip()
        if not member_id:
            member_id = f"mem_{secrets.token_hex(8)}"

        values = dict(rec)
        values[MembersColumns.MEMBER_ID] = member_id
        values[MembersColumns.DISCORD_USER_ID] = discord_user_id
        values[MembersColumns.DISCORD_USERNAME] = discord_username
        values[MembersColumns.STATUS] = values.get(MembersColumns.STATUS) or "pending"
        values[MembersColumns.UPDATED_AT] = now
        row = dict_to_row(get_headers(SheetName.MEMBERS), values)
        sheet.update_row(SheetName.MEMBERS, target_row_index, row)

    response = RedirectResponse(url="/onboarding/email", status_code=302)
    create_member_session_cookie(response, member_id)
    return response


@router.get("/onboarding/email", response_class=HTMLResponse)
async def onboarding_email_form(request: Request):
    """メールアドレス入力画面。"""
    return templates.TemplateResponse(
        "onboarding_email.html",
        {"request": request, "error": None, "info": None},
    )


@router.post("/onboarding/email", response_class=HTMLResponse)
async def onboarding_email_submit(
    request: Request,
    email: str = Form(...),
    member_id: str = Depends(get_current_member_id),
):
    """メールアドレスを受け取り、6桁コードを発行して email_verifications シートに保存し、GAS 経由で送信する。"""
    # ここでは単純な形式チェックのみ（詳細な ReNU 形式バリデーションは後続拡張）
    if "@" not in email:
        return templates.TemplateResponse(
            "onboarding_email.html",
            {"request": request, "error": "メールアドレスの形式が正しくありません。"},
        )

    # 6桁コードを生成し、ハッシュのみ保存
    code = "".join(secrets.choice("0123456789") for _ in range(6))
    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()

    now = _now_iso()
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()

    sheet = get_sheet_client()
    # email_verifications シートにレコード追加
    verification_id = f"ver_{secrets.token_hex(8)}"
    values = {
        EmailVerificationsColumns.VERIFICATION_ID: verification_id,
        EmailVerificationsColumns.MEMBER_ID: member_id,
        EmailVerificationsColumns.EMAIL: email,
        EmailVerificationsColumns.CODE_HASH: code_hash,
        EmailVerificationsColumns.EXPIRES_AT: expires_at,
        EmailVerificationsColumns.ATTEMPT_COUNT: 0,
        EmailVerificationsColumns.VERIFIED_AT: "",
        EmailVerificationsColumns.CREATED_AT: now,
    }
    row = dict_to_row(get_headers(SheetName.EMAIL_VERIFICATIONS), values)
    sheet.append_row(SheetName.EMAIL_VERIFICATIONS, row)

    # GAS に送信依頼（設定がない場合は開発用にスキップ）
    settings = get_settings()
    if settings.gas_webhook_url:
        payload = {"type": "send_verification", "email": email, "code": code}
        headers = {}
        if settings.gas_webhook_secret:
            headers["X-ReNU-Secret"] = settings.gas_webhook_secret
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(settings.gas_webhook_url, json=payload, headers=headers)

    return templates.TemplateResponse(
        "onboarding_email.html",
        {
            "request": request,
            "error": None,
            "info": "認証コードをメールで送信しました。届かない場合は数分待ってから再度お試しください。",
        },
    )


@router.get("/onboarding/verify", response_class=HTMLResponse)
async def onboarding_verify_form(request: Request):
    return templates.TemplateResponse(
        "onboarding_verify.html",
        {"request": request, "error": None, "info": None},
    )


@router.post("/onboarding/verify", response_class=HTMLResponse)
async def onboarding_verify_submit(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    member_id: str = Depends(get_current_member_id),
):
    sheet = get_sheet_client()
    records = sheet.get_all_records(SheetName.EMAIL_VERIFICATIONS)

    # member_id + email の最新レコード（created_at が最大）を探す
    latest = None
    latest_row_index = None
    for idx, rec in enumerate(records, start=2):
        if str(rec.get(EmailVerificationsColumns.MEMBER_ID, "")) != member_id:
            continue
        if str(rec.get(EmailVerificationsColumns.EMAIL, "")) != email:
            continue
        if rec.get(EmailVerificationsColumns.VERIFIED_AT):
            continue
        created_at = str(rec.get(EmailVerificationsColumns.CREATED_AT, ""))
        if (latest is None) or (created_at > str(latest.get(EmailVerificationsColumns.CREATED_AT, ""))):
            latest = rec
            latest_row_index = idx

    if not latest or not latest_row_index:
        return templates.TemplateResponse(
            "onboarding_verify.html",
            {"request": request, "error": "認証情報が見つかりません。先にメール送信を行ってください。", "info": None},
        )

    # 期限チェック
    expires_at_s = str(latest.get(EmailVerificationsColumns.EXPIRES_AT, ""))
    try:
        expires_at = datetime.fromisoformat(expires_at_s.replace("Z", "+00:00"))
    except ValueError:
        expires_at = datetime.now(timezone.utc)  # 解析失敗時は失効扱いに寄せる
    if expires_at < datetime.now(timezone.utc):
        return templates.TemplateResponse(
            "onboarding_verify.html",
            {"request": request, "error": "認証コードの有効期限が切れています。再送してください。", "info": None},
        )

    # 試行回数チェック
    attempt_count = int(latest.get(EmailVerificationsColumns.ATTEMPT_COUNT, 0) or 0)
    if attempt_count >= 5:
        return templates.TemplateResponse(
            "onboarding_verify.html",
            {"request": request, "error": "試行回数が上限に達しました。再送してください。", "info": None},
        )

    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    if code_hash != str(latest.get(EmailVerificationsColumns.CODE_HASH, "")):
        # attempt_count +1 して保存
        latest2 = dict(latest)
        latest2[EmailVerificationsColumns.ATTEMPT_COUNT] = attempt_count + 1
        row = dict_to_row(get_headers(SheetName.EMAIL_VERIFICATIONS), latest2)
        sheet.update_row(SheetName.EMAIL_VERIFICATIONS, latest_row_index, row)
        return templates.TemplateResponse(
            "onboarding_verify.html",
            {"request": request, "error": "認証コードが一致しません。", "info": None},
        )

    # email_verifications を verified に更新
    now = _now_iso()
    latest2 = dict(latest)
    latest2[EmailVerificationsColumns.VERIFIED_AT] = now
    row = dict_to_row(get_headers(SheetName.EMAIL_VERIFICATIONS), latest2)
    sheet.update_row(SheetName.EMAIL_VERIFICATIONS, latest_row_index, row)

    # members を email_verified に更新
    mem_records = sheet.get_all_records(SheetName.MEMBERS)
    mem_row_index = None
    mem_rec = None
    for idx, rec in enumerate(mem_records, start=2):
        if str(rec.get(MembersColumns.MEMBER_ID, "")) == member_id:
            mem_row_index = idx
            mem_rec = rec
            break
    if mem_row_index and mem_rec is not None:
        values = dict(mem_rec)
        values[MembersColumns.EMAIL] = email
        values[MembersColumns.EMAIL_VERIFIED] = True
        values[MembersColumns.EMAIL_VERIFIED_AT] = now
        values[MembersColumns.STATUS] = "email_verified"
        values[MembersColumns.UPDATED_AT] = now
        row = dict_to_row(get_headers(SheetName.MEMBERS), values)
        sheet.update_row(SheetName.MEMBERS, mem_row_index, row)

    return RedirectResponse(url="/onboarding/profile", status_code=302)


@router.get("/onboarding/profile", response_class=HTMLResponse)
async def onboarding_profile_form(request: Request):
    return templates.TemplateResponse(
        "onboarding_profile.html",
        {"request": request, "error": None},
    )


@router.post("/onboarding/profile", response_class=HTMLResponse)
async def onboarding_profile_submit(
    request: Request,
    full_name: str = Form(...),
    student_id: str = Form(...),
    faculty_code: str = Form(...),
    entrance_year: str = Form(...),
    grade: str = Form(...),
    member_id: str = Depends(get_current_member_id),
):
    # 学籍番号フォーマット（最低限）: 2桁 + 2桁 + 5桁（合計9桁）
    import re

    if not re.fullmatch(r"\d{9}", student_id.strip()):
        return templates.TemplateResponse(
            "onboarding_profile.html",
            {"request": request, "error": "学籍番号の形式が正しくありません。"},
        )

    sheet = get_sheet_client()
    mem_records = sheet.get_all_records(SheetName.MEMBERS)
    # 既存衝突チェック: student_id + email（email は members に入っている想定）
    current = None
    current_row_index = None
    for idx, rec in enumerate(mem_records, start=2):
        if str(rec.get(MembersColumns.MEMBER_ID, "")) == member_id:
            current = rec
            current_row_index = idx
            break
    if not current or not current_row_index:
        raise HTTPException(status_code=400, detail="Member not found")

    email = str(current.get(MembersColumns.EMAIL, "")).strip()
    collision = None
    for rec in mem_records:
        if str(rec.get(MembersColumns.MEMBER_ID, "")) == member_id:
            continue
        if str(rec.get(MembersColumns.STUDENT_ID, "")).strip() == student_id.strip() and str(
            rec.get(MembersColumns.EMAIL, "")
        ).strip() == email:
            collision = rec
            break

    now = _now_iso()
    values = dict(current)
    values[MembersColumns.FULL_NAME] = full_name.strip()
    values[MembersColumns.STUDENT_ID] = student_id.strip()
    values[MembersColumns.FACULTY_CODE] = faculty_code.strip()
    values[MembersColumns.ENTRANCE_YEAR] = entrance_year.strip()
    values[MembersColumns.GRADE] = grade.strip()
    values[MembersColumns.UPDATED_AT] = now

    if collision:
        # 衝突: merge_pending に遷移
        values[MembersColumns.STATUS] = "merge_pending"
        values[MembersColumns.MERGE_TARGET_MEMBER_ID] = str(collision.get(MembersColumns.MEMBER_ID, "")).strip()
    else:
        values[MembersColumns.STATUS] = "active"

    row = dict_to_row(get_headers(SheetName.MEMBERS), values)
    sheet.update_row(SheetName.MEMBERS, current_row_index, row)

    return RedirectResponse(url="/", status_code=302)

