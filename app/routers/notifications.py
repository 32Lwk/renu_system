from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import csv
from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.auth import optional_admin_session, optional_member_session
from app.core.config import get_settings
from app.core.member_session import _load_member_row
from app.core.roles import (
    MemberRole,
    get_overall_role,
    leader_teams,
    managed_teams_subleader_plus,
    parse_team_roles,
)
from app.services.discord_notify import post_channel_message
from app.services.mail import send_gmail_message
from app.services.sheet_client import get_sheet_client
from app.services.sheet_schemas import (
    AttendancesColumns,
    EventsColumns,
    MembersColumns,
    NotificationsLogColumns,
    SheetName,
    get_headers,
)
from app.services.sheet_utils import dict_to_row

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(tags=["notifications"])


def _faculty_label(code: str) -> str:
    """学部学科コードから学部学科名を返す（空・未知コードは空文字）。"""
    m = {
        "01": "文学部",
        "02": "教育学部",
        "03": "法学部",
        "04": "経済学部",
        "05": "情報文化学部",
        "06": "理学部",
        "07": "医学部",
        "08": "工学部",
        "09": "農学部",
        "17": "医学部保健学科",
    }
    c = (code or "").strip()
    return m.get(c, "")


def _testdata_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "docs" / "testdata"


def _ensure_notifications_log_file() -> None:
    p = _testdata_dir() / "notifications_log.csv"
    if p.exists():
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(get_headers(SheetName.NOTIFICATIONS_LOG))


def _append_notification_log(values: dict[str, Any]) -> None:
    settings = get_settings()
    if settings.data_source.lower() == "mockdb":
        return
    if not settings.google_service_account_json_path or not settings.spreadsheet_id:
        _ensure_notifications_log_file()
    client = get_sheet_client()
    client.append_row(
        SheetName.NOTIFICATIONS_LOG,
        dict_to_row(get_headers(SheetName.NOTIFICATIONS_LOG), values),
    )


def _notify_optout(row: dict) -> bool:
    v = str(row.get(MembersColumns.NOTIFY_OPTOUT, "") or "").lower()
    return v in ("true", "1", "yes", "on")


def _row_is_active(row: dict) -> bool:
    s = str(row.get(MembersColumns.STATUS, "") or "").strip().lower()
    return s in ("active", "1", "true", "yes", "アクティブ")


def _row_member_id(row: dict) -> str:
    for key in (
        MembersColumns.MEMBER_ID,
        "member_id",
        "Member ID",
        "メンバーID",
    ):
        v = row.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _row_teams_set(row: dict) -> set[str]:
    raw = row.get(MembersColumns.TEAMS) or row.get("teams") or ""
    return {x.strip() for x in str(raw).replace("、", ",").split(",") if x.strip()}


def _normalize_header_row(row: dict[str, Any]) -> dict[str, Any]:
    return {(k or "").strip().lstrip("\ufeff"): v for k, v in row.items()}


def _read_members_testdata_csv() -> list[dict[str, Any]]:
    """docs/testdata/members.csv を読む（ローカル開発で確実に一覧を出すため）。"""
    path = _testdata_dir() / "members.csv"
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = [_normalize_header_row(r) for r in csv.DictReader(f)]
        return [r for r in rows if r]
    except OSError:
        return []


def _read_events_testdata_csv() -> list[dict[str, Any]]:
    path = _testdata_dir() / "events.csv"
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = [_normalize_header_row(r) for r in csv.DictReader(f)]
        return [r for r in rows if r]
    except OSError:
        return []


def _merge_member_row_with_testdata(member_id: str, base_row: dict[str, Any]) -> dict[str, Any]:
    """同じ member_id の testdata 行があれば teams/roles 等を上書き（Sheets と CSV の食い違い対策）。"""
    mid = str(member_id).strip()
    for r in _read_members_testdata_csv():
        if _row_member_id(r) == mid:
            merged = dict(base_row) if base_row else {}
            merged.update(r)
            return merged
    return dict(base_row) if base_row else {}


def _actor_email_notifier(request: Request) -> tuple[str, str]:
    """(triggered_by, actor_label) — メール送信権限: admin または Leader+"""
    if optional_admin_session(request):
        return "admin", "admin"
    mid = optional_member_session(request)
    if not mid:
        raise HTTPException(status_code=401, detail="ログインが必要です")
    row = _load_member_row(mid)
    ov = get_overall_role(parse_team_roles(row)) if row else MemberRole.MEMBER
    if ov < MemberRole.LEADER:
        raise HTTPException(status_code=403, detail="メール一斉送信は Leader 以上または管理者のみです")
    return mid, mid


def _actor_discord_notifier(request: Request) -> tuple[str, str]:
    """Discord: admin または SubLeader+"""
    if optional_admin_session(request):
        return "admin", "admin"
    mid = optional_member_session(request)
    if not mid:
        raise HTTPException(status_code=401, detail="ログインが必要です")
    row = _load_member_row(mid)
    tr = parse_team_roles(row) if row else []
    ov = get_overall_role(tr)
    if ov < MemberRole.SUBLEADER:
        raise HTTPException(status_code=403, detail="Discord 投稿は SubLeader 以上または管理者のみです")
    return mid, mid


def _collect_targets(
    member_ids_csv: str,
    target_team: str,
    event_id: str,
    *,
    restrict_teams: set[str] | None = None,
) -> list[dict]:
    """members から対象行を返す（active のみ、opt-out は呼び出し側で除外）。"""
    client = get_sheet_client()
    mems = client.get_all_records(SheetName.MEMBERS)
    ids = {x.strip() for x in (member_ids_csv or "").split(",") if x.strip()}
    team = (target_team or "").strip()
    ev = (event_id or "").strip()

    attendees: set[str] | None = None
    if ev:
        atts = client.get_all_records(SheetName.ATTENDANCES)
        attendees = {
            str(a.get(AttendancesColumns.MEMBER_ID, ""))
            for a in atts
            if str(a.get(AttendancesColumns.EVENT_ID, "")) == ev
        }
    out: list[dict] = []
    for m in mems:
        if str(m.get(MembersColumns.STATUS, "")) != "active":
            continue
        mid = str(m.get(MembersColumns.MEMBER_ID, ""))
        if attendees is not None and mid not in attendees:
            continue
        teams = {x.strip() for x in str(m.get(MembersColumns.TEAMS, "") or "").split(",") if x.strip()}
        if restrict_teams and not (teams & restrict_teams):
            continue
        if ids and mid in ids:
            out.append(m)
        elif team and team in teams:
            out.append(m)
    # 重複除去
    seen: set[str] = set()
    uniq: list[dict] = []
    for m in out:
        mid = str(m.get(MembersColumns.MEMBER_ID, ""))
        if mid in seen:
            continue
        seen.add(mid)
        uniq.append(m)
    return uniq


def _selectable_members_admin() -> list[dict[str, Any]]:
    mems = _read_members_testdata_csv()
    if not mems:
        mems = get_sheet_client().get_all_records(SheetName.MEMBERS)
    rows: list[dict[str, Any]] = []
    for m in mems:
        if not _row_is_active(m):
            continue
        mid = _row_member_id(m)
        if not mid:
            continue
        fn = m.get(MembersColumns.FULL_NAME) or m.get("full_name") or ""
        fac_code = str(
            m.get(MembersColumns.FACULTY_CODE, "") or m.get("faculty_code", "") or ""
        ).strip()
        if fac_code:
            z2h = str.maketrans("０１２３４５６７８９", "0123456789")
            normalized = "".join(ch for ch in fac_code.translate(z2h) if ch.isdigit())
            if normalized.startswith("17"):
                fac_code = "17"
            elif len(normalized) >= 2:
                fac_code = normalized[:2]
            elif normalized:
                fac_code = normalized.zfill(2)
        rows.append(
            {
                "member_id": mid,
                "full_name": str(fn or ""),
                "teams": str(m.get(MembersColumns.TEAMS, "") or m.get("teams", "") or ""),
                "grade": str(m.get(MembersColumns.GRADE, "") or m.get("grade", "") or ""),
                "faculty_code": fac_code,
                "faculty_label": _faculty_label(fac_code),
                "roles": str(m.get(MembersColumns.ROLES, "") or m.get("roles", "") or ""),
            }
        )
    rows.sort(key=lambda x: ((x["full_name"] or x["member_id"]).lower(), x["member_id"]))
    return rows


def _selectable_members_leader(leader_team_set: set[str]) -> list[dict[str, Any]]:
    if not leader_team_set:
        return []
    norm_leaders = {t.strip() for t in leader_team_set if t and str(t).strip()}
    # 必ず testdata を優先（Sheets 接続時でも空・列違いで一覧が消えるのを防ぐ）
    mems = _read_members_testdata_csv()
    if not mems:
        mems = get_sheet_client().get_all_records(SheetName.MEMBERS)

    def build_rows(team_filter: set[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for m in mems:
            if not _row_is_active(m):
                continue
            mid = _row_member_id(m)
            if not mid or mid in seen:
                continue
            teams = _row_teams_set(m)
            if not (teams & team_filter):
                continue
            seen.add(mid)
            fn = m.get(MembersColumns.FULL_NAME) or m.get("full_name") or ""
            fac_code = str(
                m.get(MembersColumns.FACULTY_CODE, "") or m.get("faculty_code", "") or ""
            ).strip()
            if fac_code:
                z2h = str.maketrans("０１２３４５６７８９", "0123456789")
                normalized = "".join(ch for ch in fac_code.translate(z2h) if ch.isdigit())
                if normalized.startswith("17"):
                    fac_code = "17"
                elif len(normalized) >= 2:
                    fac_code = normalized[:2]
                elif normalized:
                    fac_code = normalized.zfill(2)
            out.append(
                {
                    "member_id": mid,
                    "full_name": str(fn or ""),
                    "teams": str(m.get(MembersColumns.TEAMS, "") or m.get("teams", "") or ""),
                    "grade": str(m.get(MembersColumns.GRADE, "") or m.get("grade", "") or ""),
                    "faculty_code": fac_code,
                    "faculty_label": _faculty_label(fac_code),
                    "roles": str(m.get(MembersColumns.ROLES, "") or m.get("roles", "") or ""),
                }
            )
        out.sort(key=lambda x: ((x["full_name"] or x["member_id"]).lower(), x["member_id"]))
        return out

    rows = build_rows(norm_leaders)
    # Leader チーム名と CSV の表記がずれて空になる場合の救済: 所属チーム名の部分一致
    if not rows and norm_leaders:
        expanded: set[str] = set(norm_leaders)
        for m in mems:
            if not _row_is_active(m):
                continue
            for t in _row_teams_set(m):
                for L in norm_leaders:
                    if L in t or t in L:
                        expanded.add(t)
        rows = build_rows(expanded)
    return rows


def _admin_notifications_context(
    request: Request,
    *,
    error: str | None = None,
    info: str | None = None,
) -> dict[str, Any]:
    evs = _read_events_testdata_csv()
    if not evs:
        evs = get_sheet_client().get_all_records(SheetName.EVENTS)
    events = [
        {
            "event_id": e.get(EventsColumns.EVENT_ID, ""),
            "name": e.get(EventsColumns.NAME, ""),
            "date": e.get(EventsColumns.DATE, ""),
        }
        for e in evs
    ]
    return {
        "request": request,
        "error": error,
        "info": info,
        "events": events,
        "selectable_members": _selectable_members_admin(),
    }


def _member_team_notifications_context(
    request: Request,
    tr: list,
    *,
    error: str | None = None,
    info: str | None = None,
    member_id: str | None = None,
) -> dict[str, Any]:
    """member_id を渡すと testdata の members.csv で teams/roles を補正する。"""
    tr_eff = tr
    if member_id:
        base = _load_member_row(member_id)
        merged = _merge_member_row_with_testdata(member_id, base)
        tr_eff = parse_team_roles(merged) if merged else tr
    ov = get_overall_role(tr_eff)
    managed = sorted(managed_teams_subleader_plus(tr_eff))
    lt = sorted(leader_teams(tr_eff))
    can_email = bool(lt)
    evs = _read_events_testdata_csv()
    if not evs:
        evs = get_sheet_client().get_all_records(SheetName.EVENTS)
    related_events: list[dict[str, Any]] = []
    lt_set = set(lt)
    for e in evs:
        target = str(e.get(EventsColumns.TARGET_TEAMS, "") or "").split(",")[0].strip()
        if target and target in lt_set:
            related_events.append(
                {
                    "event_id": e.get(EventsColumns.EVENT_ID, ""),
                    "name": e.get(EventsColumns.NAME, ""),
                    "date": e.get(EventsColumns.DATE, ""),
                    "team": target,
                }
            )
    selectable = _selectable_members_leader(set(lt)) if lt else []
    return {
        "request": request,
        "can_email": can_email,
        "can_discord": ov >= MemberRole.SUBLEADER,
        "leader_teams": lt,
        "teams": managed,
        "events": related_events,
        "selectable_members": selectable,
        "error": error,
        "info": info,
    }


@router.get("/admin/notifications", response_class=HTMLResponse)
async def admin_notifications_page(request: Request):
    if not optional_admin_session(request):
        return RedirectResponse("/admin/login", status_code=302)
    return templates.TemplateResponse(
        "admin_notifications.html",
        _admin_notifications_context(request),
    )


@router.get("/my/team/notifications", response_class=HTMLResponse)
async def member_notifications_page(request: Request):
    mid = optional_member_session(request)
    if not mid:
        raise HTTPException(status_code=401, detail="メンバーログインが必要です")
    base = _load_member_row(mid)
    row_m = _merge_member_row_with_testdata(mid, base)
    tr = parse_team_roles(row_m) if row_m else []
    ov = get_overall_role(tr)
    if ov < MemberRole.SUBLEADER:
        raise HTTPException(status_code=403, detail="SubLeader 以上が必要です")
    return templates.TemplateResponse(
        "member_team_notifications.html",
        _member_team_notifications_context(request, tr, member_id=mid),
    )


@router.post("/notifications/email")
async def notifications_email(
    request: Request,
    subject: str = Form(...),
    body: str = Form(...),
    target_team: str = Form(""),
    event_id: str = Form(""),
):
    form = await request.form()
    member_ids_csv = ",".join(
        str(x).strip() for x in form.getlist("member_ids") if str(x).strip()
    )
    triggered_by, _ = _actor_email_notifier(request)
    if triggered_by != "admin":
        merged = _merge_member_row_with_testdata(triggered_by, _load_member_row(triggered_by))
        tr = parse_team_roles(merged) if merged else []
    else:
        tr = []
    restrict = None
    if triggered_by != "admin":
        lt = leader_teams(tr)
        if not lt:
            raise HTTPException(status_code=403, detail="Leader チームがありません")
        restrict = lt
        tt = (target_team or "").strip()
        if tt and tt not in lt:
            raise HTTPException(status_code=400, detail="そのチームへのメール送信は許可されていません")

    targets = _collect_targets(member_ids_csv, target_team, event_id, restrict_teams=restrict)
    if not targets:
        msg = "送信対象がありません。対象チーム・イベント・メンバーからいずれかを指定してください。"
        if optional_admin_session(request):
            ctx = _admin_notifications_context(request, error=msg)
            return templates.TemplateResponse("admin_notifications.html", ctx, status_code=400)
        ctx = _member_team_notifications_context(
            request, tr, error=msg, member_id=str(triggered_by)
        )
        return templates.TemplateResponse("member_team_notifications.html", ctx, status_code=400)

    emails: list[str] = []
    skipped_optout: list[str] = []
    for m in targets:
        if _notify_optout(m):
            skipped_optout.append(str(m.get(MembersColumns.MEMBER_ID, "")))
            continue
        em = str(m.get(MembersColumns.EMAIL, "") or "").strip()
        if em:
            emails.append(em)

    if not emails:
        msg = "送信可能なメールアドレスがありません（全員オプトアウトまたはメール未登録）。"
        if optional_admin_session(request):
            ctx = _admin_notifications_context(request, error=msg)
            return templates.TemplateResponse("admin_notifications.html", ctx, status_code=400)
        ctx = _member_team_notifications_context(
            request, tr, error=msg, member_id=str(triggered_by)
        )
        return templates.TemplateResponse("member_team_notifications.html", ctx, status_code=400)

    try:
        send_gmail_message(emails, subject.strip(), body)
    except Exception as e:
        _append_notification_log(
            {
                NotificationsLogColumns.LOG_ID: f"log_{secrets.token_hex(8)}",
                NotificationsLogColumns.TYPE: "email",
                NotificationsLogColumns.TARGET_IDS: ",".join(
                    str(m.get(MembersColumns.MEMBER_ID, "")) for m in targets
                )[:2000],
                NotificationsLogColumns.TRIGGERED_BY: triggered_by,
                NotificationsLogColumns.SUBJECT: subject.strip()[:500],
                NotificationsLogColumns.STATUS: "error",
                NotificationsLogColumns.DETAIL: str(e)[:4000],
                NotificationsLogColumns.CREATED_AT: datetime.now(timezone.utc).isoformat(),
            }
        )
        if optional_admin_session(request):
            ctx = _admin_notifications_context(request, error=str(e))
            return templates.TemplateResponse("admin_notifications.html", ctx, status_code=500)
        ctx = _member_team_notifications_context(
            request, tr, error=str(e), member_id=str(triggered_by)
        )
        return templates.TemplateResponse("member_team_notifications.html", ctx, status_code=500)

    detail_obj = {
        "to_count": len(emails),
        "skipped_optout": skipped_optout,
    }
    _append_notification_log(
        {
            NotificationsLogColumns.LOG_ID: f"log_{secrets.token_hex(8)}",
            NotificationsLogColumns.TYPE: "email",
            NotificationsLogColumns.TARGET_IDS: ",".join(
                str(m.get(MembersColumns.MEMBER_ID, "")) for m in targets
            )[:2000],
            NotificationsLogColumns.TRIGGERED_BY: triggered_by,
            NotificationsLogColumns.SUBJECT: subject.strip()[:500],
            NotificationsLogColumns.STATUS: "ok",
            NotificationsLogColumns.DETAIL: json.dumps(detail_obj, ensure_ascii=False)[:4000],
            NotificationsLogColumns.CREATED_AT: datetime.now(timezone.utc).isoformat(),
        }
    )
    info = (
        f"送信が完了しました。\n"
        f"・メール送信: {len(emails)} 件\n"
        f"・オプトアウトで除外: {len(skipped_optout)} 件"
    )
    if optional_admin_session(request):
        ctx = _admin_notifications_context(request, info=info)
        return templates.TemplateResponse("admin_notifications.html", ctx)
    ctx = _member_team_notifications_context(
        request, tr, info=info, member_id=str(triggered_by)
    )
    return templates.TemplateResponse("member_team_notifications.html", ctx)


@router.post("/notifications/discord/channel")
async def notifications_discord_channel(
    request: Request,
    channel_id: str = Form(...),
    message: str = Form(...),
):
    triggered_by, _ = _actor_discord_notifier(request)
    cid = channel_id.strip()
    try:
        post_channel_message(cid, message)
    except Exception as e:
        _append_notification_log(
            {
                NotificationsLogColumns.LOG_ID: f"log_{secrets.token_hex(8)}",
                NotificationsLogColumns.TYPE: "discord_channel",
                NotificationsLogColumns.TARGET_IDS: cid,
                NotificationsLogColumns.TRIGGERED_BY: triggered_by,
                NotificationsLogColumns.SUBJECT: message.strip()[:200],
                NotificationsLogColumns.STATUS: "error",
                NotificationsLogColumns.DETAIL: str(e)[:4000],
                NotificationsLogColumns.CREATED_AT: datetime.now(timezone.utc).isoformat(),
            }
        )
        if optional_admin_session(request):
            ctx = _admin_notifications_context(request, error=str(e))
            return templates.TemplateResponse("admin_notifications.html", ctx, status_code=500)
        merged = _merge_member_row_with_testdata(triggered_by, _load_member_row(triggered_by))
        tr_d = parse_team_roles(merged) if merged else []
        ctx = _member_team_notifications_context(
            request, tr_d, error=str(e), member_id=str(triggered_by)
        )
        return templates.TemplateResponse("member_team_notifications.html", ctx, status_code=500)

    _append_notification_log(
        {
            NotificationsLogColumns.LOG_ID: f"log_{secrets.token_hex(8)}",
            NotificationsLogColumns.TYPE: "discord_channel",
            NotificationsLogColumns.TARGET_IDS: cid,
            NotificationsLogColumns.TRIGGERED_BY: triggered_by,
            NotificationsLogColumns.SUBJECT: message.strip()[:200],
            NotificationsLogColumns.STATUS: "ok",
            NotificationsLogColumns.DETAIL: "",
            NotificationsLogColumns.CREATED_AT: datetime.now(timezone.utc).isoformat(),
        }
    )
    info = "Discord チャンネルに投稿しました。"
    if optional_admin_session(request):
        ctx = _admin_notifications_context(request, info=info)
        return templates.TemplateResponse("admin_notifications.html", ctx)
    merged = _merge_member_row_with_testdata(triggered_by, _load_member_row(triggered_by))
    tr_d = parse_team_roles(merged) if merged else []
    ctx = _member_team_notifications_context(
        request, tr_d, info=info, member_id=str(triggered_by)
    )
    return templates.TemplateResponse("member_team_notifications.html", ctx)
