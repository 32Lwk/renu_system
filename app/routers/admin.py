from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.auth import create_admin_session_cookie, get_current_admin
from app.schemas.models import MemberCreate
from app.core.config import get_settings
from app.services.db import (
    SessionLocal,
    Event as EventModel,
    Member as MemberModel,
    MemberTeam,
    Team as TeamModel,
    Attendance as AttendanceModel,
    AttendanceChange as AttendanceChangeModel,
)
from app.services.sheet_client import get_sheet_client
from app.services.sheets_repo import SheetRepo
from app.services.sheet_schemas import SheetName, EventsColumns, MembersColumns, get_headers
from app.services.sheet_utils import dict_to_row


templates = Jinja2Templates(directory="app/templates")
router = APIRouter(tags=["admin"])


@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_form(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})

@router.get("/admin/logout")
async def admin_logout():
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("admin_session")
    return response


@router.post("/admin/login")
async def admin_login(
    request: Request,
    password: str = Form(...),
):
    # username は固定で admin とする
    from app.core.config import get_settings

    settings = get_settings()
    if password != (settings.admin_password_hash or ""):
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "パスワードが正しくありません"},
            status_code=400,
        )

    response = RedirectResponse(url="/admin", status_code=302)
    create_admin_session_cookie(response, "admin")
    return response


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, _user: str = Depends(get_current_admin)):
    settings = get_settings()
    events: list[dict[str, Any]] = []
    if settings.data_source.lower() == "mockdb":
        db = SessionLocal()
        try:
            rows = (
                db.query(EventModel)
                .order_by(EventModel.date.asc(), EventModel.start_time.asc())
                .limit(20)
                .all()
            )
            for r in rows:
                events.append(
                    {
                        "id": r.id,
                        "name": r.name,
                        "date": r.date,
                        "start_time": r.start_time,
                        "end_time": r.end_time,
                        "required_members": r.required_members,
                    }
                )
        finally:
            db.close()
    else:
        client = get_sheet_client()
        records = client.get_all_records(SheetName.EVENTS)
        for rec in records:
            events.append(
                {
                    "id": rec.get(EventsColumns.EVENT_ID, ""),
                    "name": rec.get(EventsColumns.NAME, ""),
                    "date": rec.get(EventsColumns.DATE, ""),
                    "start_time": rec.get(EventsColumns.START_TIME, ""),
                    "end_time": rec.get(EventsColumns.END_TIME, ""),
                    "required_members": rec.get(EventsColumns.REQUIRED_MEMBERS, ""),
                }
            )

    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "events": events,
        },
    )


def _member_roles_match(roles_csv: str, role_filter: str) -> bool:
    if not role_filter.strip():
        return True
    want = role_filter.strip().lower()
    raw = str(roles_csv or "").replace(";", ",")
    parts = [x.strip().lower() for x in raw.split(",") if x.strip()]
    return any(p == want or p.startswith(want) for p in parts)

def _normalize_faculty_code(code: str) -> str:
    """学部学科コードを正規化（全角→半角、数字抽出、2桁ゼロ埋め。17は特例）。"""
    c = (code or "").strip()
    if not c:
        return ""
    z2h = str.maketrans("０１２３４５６７８９", "0123456789")
    normalized = "".join(ch for ch in c.translate(z2h) if ch.isdigit())
    if not normalized:
        return ""
    if normalized.startswith("17"):
        return "17"
    if len(normalized) >= 2:
        return normalized[:2]
    return normalized.zfill(2)


@router.get("/admin/members", response_class=HTMLResponse)
async def list_members(
    request: Request,
    faculty: str = "",
    grade: str = "",
    role: str = "",
    _user: str = Depends(get_current_admin),
):
    settings = get_settings()
    members: list[dict[str, Any]] = []
    faculty = _normalize_faculty_code(faculty or "")
    grade = (grade or "").strip()
    role_f = (role or "").strip()

    if settings.data_source.lower() == "mockdb":
        db = SessionLocal()
        try:
            rows = (
                db.query(MemberModel)
                .order_by(MemberModel.id.asc())
                .all()
            )
            for r in rows:
                mt_rows = (
                    db.query(MemberTeam)
                    .filter_by(member_id=r.id)
                    .all()
                )
                role_names = [mt.role for mt in mt_rows]
                roles_csv = ",".join(role_names)
                team_names: list[str] = []
                for mt in mt_rows:
                    t = db.query(TeamModel).filter_by(id=mt.team_id).first()
                    if t:
                        team_names.append(t.name)
                teams_csv = ",".join(team_names)
                fac = (r.student_id or "")[:2] if len(r.student_id or "") >= 2 else ""
                if faculty and _normalize_faculty_code(fac) != faculty:
                    continue
                if grade and (r.grade or "").strip() != grade:
                    continue
                if role_f and not _member_roles_match(roles_csv, role_f):
                    continue
                members.append(
                    {
                        "id": r.id,
                        "member_id": "",
                        "name": r.name,
                        "grade": r.grade,
                        "faculty_code": fac or "-",
                        "roles": roles_csv or "-",
                        "teams": teams_csv or "-",
                        "status": "active",
                        "email": r.email,
                        "discord_id": r.discord_id,
                    }
                )
        finally:
            db.close()
    else:
        client = get_sheet_client()
        records = client.get_all_records(SheetName.MEMBERS)
        for idx, rec in enumerate(records, start=2):
            # faculty_code が空/欠損でも student_id 先頭2桁から推定できるようにする
            fac_raw = str(rec.get(MembersColumns.FACULTY_CODE, "") or "").strip()
            if not fac_raw:
                sid = str(rec.get(MembersColumns.STUDENT_ID, "") or "").strip()
                fac_raw = sid[:2] if len(sid) >= 2 else ""
            fac = _normalize_faculty_code(fac_raw)
            gr = str(rec.get(MembersColumns.GRADE, "")).strip()
            roles_csv = str(rec.get(MembersColumns.ROLES, "") or "")
            if faculty and fac != faculty:
                continue
            if grade and gr != grade:
                continue
            if role_f and not _member_roles_match(roles_csv, role_f):
                continue
            members.append(
                {
                    "row_index": idx,
                    "member_id": rec.get(MembersColumns.MEMBER_ID, ""),
                    "name": rec.get(MembersColumns.FULL_NAME, ""),
                    "grade": gr,
                    "faculty_code": fac or "-",
                    "roles": roles_csv or "-",
                    "email": rec.get(MembersColumns.EMAIL, ""),
                    "discord_id": rec.get(MembersColumns.DISCORD_USER_ID, ""),
                    "teams": rec.get(MembersColumns.TEAMS, ""),
                    "status": rec.get(MembersColumns.STATUS, ""),
                }
            )

    return templates.TemplateResponse(
        "admin_members.html",
        {
            "request": request,
            "members": members,
            "filter_faculty": faculty,
            "filter_grade": grade,
            "filter_role": role_f,
        },
    )


@router.get("/admin/members/new", response_class=HTMLResponse)
async def new_member_form(request: Request, _user: str = Depends(get_current_admin)):
    return templates.TemplateResponse(
        "admin_member_form.html",
        {"request": request, "mode": "new", "member": {}, "error": None},
    )


@router.post("/admin/members/new", response_class=HTMLResponse)
async def new_member_submit(
    request: Request,
    full_name: str = Form(...),
    grade: str = Form(...),
    email: str = Form(""),
    teams: str = Form(""),
    roles: str = Form(""),
    status: str = Form("active"),
    _user: str = Depends(get_current_admin),
):
    from datetime import datetime, timezone
    import secrets

    client = get_sheet_client()
    now = datetime.now(timezone.utc).isoformat()
    member_id = f"mem_{secrets.token_hex(8)}"

    values = {
        MembersColumns.MEMBER_ID: member_id,
        MembersColumns.FULL_NAME: full_name.strip(),
        MembersColumns.GRADE: grade.strip(),
        MembersColumns.EMAIL: email.strip(),
        MembersColumns.TEAMS: teams.strip(),
        MembersColumns.ROLES: roles.strip(),
        MembersColumns.STATUS: status.strip(),
        MembersColumns.CREATED_AT: now,
        MembersColumns.UPDATED_AT: now,
    }
    row = dict_to_row(get_headers(SheetName.MEMBERS), values)
    client.append_row(SheetName.MEMBERS, row)
    return RedirectResponse(url="/admin/members", status_code=302)


@router.get("/admin/members/{member_id}/edit", response_class=HTMLResponse)
async def edit_member_form(
    member_id: str, request: Request, _user: str = Depends(get_current_admin)
):
    settings = get_settings()
    if settings.data_source.lower() == "mockdb":
        return HTMLResponse(status_code=400, content="Sheets mode only")

    client = get_sheet_client()
    records = client.get_all_records(SheetName.MEMBERS)
    for rec in records:
        if str(rec.get(MembersColumns.MEMBER_ID, "")) == member_id:
            return templates.TemplateResponse(
                "admin_member_form.html",
                {"request": request, "mode": "edit", "member": rec, "error": None},
            )
    return HTMLResponse(status_code=404, content="Member not found")


@router.post("/admin/members/{member_id}/edit", response_class=HTMLResponse)
async def edit_member_submit(
    member_id: str,
    request: Request,
    full_name: str = Form(...),
    grade: str = Form(...),
    email: str = Form(""),
    teams: str = Form(""),
    roles: str = Form(""),
    status: str = Form("active"),
    _user: str = Depends(get_current_admin),
):
    from datetime import datetime, timezone

    client = get_sheet_client()
    records = client.get_all_records(SheetName.MEMBERS)
    row_index = None
    target = None
    for idx, rec in enumerate(records, start=2):
        if str(rec.get(MembersColumns.MEMBER_ID, "")) == member_id:
            row_index = idx
            target = rec
            break
    if not row_index or target is None:
        return HTMLResponse(status_code=404, content="Member not found")

    values = dict(target)
    values[MembersColumns.FULL_NAME] = full_name.strip()
    values[MembersColumns.GRADE] = grade.strip()
    values[MembersColumns.EMAIL] = email.strip()
    values[MembersColumns.TEAMS] = teams.strip()
    values[MembersColumns.ROLES] = roles.strip()
    values[MembersColumns.STATUS] = status.strip()
    values[MembersColumns.UPDATED_AT] = datetime.now(timezone.utc).isoformat()
    row = dict_to_row(get_headers(SheetName.MEMBERS), values)
    client.update_row(SheetName.MEMBERS, row_index, row)
    return RedirectResponse(url="/admin/members", status_code=302)


@router.post("/admin/members/{member_id}/deactivate", response_class=HTMLResponse)
async def deactivate_member(member_id: str, _user: str = Depends(get_current_admin)):
    from datetime import datetime, timezone

    client = get_sheet_client()
    records = client.get_all_records(SheetName.MEMBERS)
    row_index = None
    target = None
    for idx, rec in enumerate(records, start=2):
        if str(rec.get(MembersColumns.MEMBER_ID, "")) == member_id:
            row_index = idx
            target = rec
            break
    if not row_index or target is None:
        return HTMLResponse(status_code=404, content="Member not found")
    values = dict(target)
    values[MembersColumns.STATUS] = "inactive"
    values[MembersColumns.UPDATED_AT] = datetime.now(timezone.utc).isoformat()
    row = dict_to_row(get_headers(SheetName.MEMBERS), values)
    client.update_row(SheetName.MEMBERS, row_index, row)
    return RedirectResponse(url="/admin/members", status_code=302)


@router.get("/admin/merge-requests", response_class=HTMLResponse)
async def list_merge_requests(request: Request, _user: str = Depends(get_current_admin)):
    client = get_sheet_client()
    records = client.get_all_records(SheetName.MEMBERS)
    pending = []
    for rec in records:
        if str(rec.get(MembersColumns.STATUS, "")) != "merge_pending":
            continue
        pending.append(
            {
                "member_id": rec.get(MembersColumns.MEMBER_ID, ""),
                "full_name": rec.get(MembersColumns.FULL_NAME, ""),
                "student_id": rec.get(MembersColumns.STUDENT_ID, ""),
                "email": rec.get(MembersColumns.EMAIL, ""),
                "discord_username": rec.get(MembersColumns.DISCORD_USERNAME, ""),
                "merge_target_member_id": rec.get(MembersColumns.MERGE_TARGET_MEMBER_ID, ""),
            }
        )
    return templates.TemplateResponse(
        "admin_merge_requests.html",
        {"request": request, "requests": pending},
    )


def _find_member_row_by_id(client, member_id: str):
    records = client.get_all_records(SheetName.MEMBERS)
    for idx, rec in enumerate(records, start=2):
        if str(rec.get(MembersColumns.MEMBER_ID, "")) == member_id:
            return idx, rec
    return None, None


@router.post("/admin/merge-requests/{member_id}/approve", response_class=HTMLResponse)
async def approve_merge_request(member_id: str, _user: str = Depends(get_current_admin)):
    from datetime import datetime, timezone

    client = get_sheet_client()
    req_row_idx, req = _find_member_row_by_id(client, member_id)
    if not req_row_idx or req is None:
        return HTMLResponse(status_code=404, content="Request not found")
    target_id = str(req.get(MembersColumns.MERGE_TARGET_MEMBER_ID, "")).strip()
    if not target_id:
        return HTMLResponse(status_code=400, content="merge_target_member_id is missing")

    target_row_idx, target = _find_member_row_by_id(client, target_id)
    if not target_row_idx or target is None:
        return HTMLResponse(status_code=404, content="Target member not found")

    now = datetime.now(timezone.utc).isoformat()

    # 既存メンバーに discord_user_id を付与（空の場合のみ上書き）
    target_values = dict(target)
    if not str(target_values.get(MembersColumns.DISCORD_USER_ID, "")).strip():
        target_values[MembersColumns.DISCORD_USER_ID] = req.get(MembersColumns.DISCORD_USER_ID, "")
        target_values[MembersColumns.DISCORD_USERNAME] = req.get(MembersColumns.DISCORD_USERNAME, "")
    target_values[MembersColumns.UPDATED_AT] = now
    client.update_row(SheetName.MEMBERS, target_row_idx, dict_to_row(get_headers(SheetName.MEMBERS), target_values))

    # 仮メンバーを inactive に変更し、承認情報を記録
    req_values = dict(req)
    req_values[MembersColumns.STATUS] = "inactive"
    req_values[MembersColumns.APPROVED_BY] = "admin"
    req_values[MembersColumns.APPROVED_AT] = now
    req_values[MembersColumns.UPDATED_AT] = now
    client.update_row(SheetName.MEMBERS, req_row_idx, dict_to_row(get_headers(SheetName.MEMBERS), req_values))

    return RedirectResponse(url="/admin/merge-requests", status_code=302)


@router.post("/admin/merge-requests/{member_id}/reject", response_class=HTMLResponse)
async def reject_merge_request(member_id: str, _user: str = Depends(get_current_admin)):
    from datetime import datetime, timezone

    client = get_sheet_client()
    req_row_idx, req = _find_member_row_by_id(client, member_id)
    if not req_row_idx or req is None:
        return HTMLResponse(status_code=404, content="Request not found")

    now = datetime.now(timezone.utc).isoformat()
    req_values = dict(req)
    req_values[MembersColumns.STATUS] = "inactive"
    req_values[MembersColumns.APPROVED_BY] = "admin"
    req_values[MembersColumns.APPROVED_AT] = now
    req_values[MembersColumns.UPDATED_AT] = now
    client.update_row(SheetName.MEMBERS, req_row_idx, dict_to_row(get_headers(SheetName.MEMBERS), req_values))
    return RedirectResponse(url="/admin/merge-requests", status_code=302)


@router.get("/admin/events/{event_id}", response_class=HTMLResponse)
async def event_detail(
    event_id: int,
    request: Request,
    _user: str = Depends(get_current_admin),
):
    """イベント詳細 + 出勤者一覧（モックDBモードのみ先に対応）。"""
    settings = get_settings()
    attendees: list[dict[str, Any]] = []
    if settings.data_source.lower() == "mockdb":
        db = SessionLocal()
        try:
            event = db.query(EventModel).filter_by(id=event_id).one_or_none()
            if not event:
                return HTMLResponse(status_code=404, content="Event not found")
            rows = (
                db.query(AttendanceModel, MemberModel)
                .join(MemberModel, AttendanceModel.member_id == MemberModel.id)
                .filter(AttendanceModel.event_id == event_id)
                .all()
            )
            for att, mem in rows:
                attendees.append(
                    {
                        "attendance_id": att.id,
                        "member_name": mem.name,
                        "status": att.status,
                        "role_name": att.role_name,
                        "note": att.note,
                    }
                )
        finally:
            db.close()
    else:
        repo = SheetRepo()
        event = repo.find_event(str(event_id))
        if not event:
            return HTMLResponse(status_code=404, content="Event not found")
        atts = repo.list_attendances()
        mems = {m.get(MembersColumns.MEMBER_ID, ""): m for m in repo.list_members()}
        for a in atts:
            if str(a.get("event_id", "")) != str(event_id):
                continue
            mid = a.get("member_id", "")
            mem = mems.get(mid, {})
            attendees.append(
                {
                    "attendance_id": a.get("attendance_id", ""),
                    "member_name": mem.get(MembersColumns.FULL_NAME, "") or mid,
                    "status": a.get("status", ""),
                    "role_name": a.get("role", ""),
                    "note": a.get("note", ""),
                }
            )

    return templates.TemplateResponse(
        "admin_event_detail.html",
        {"request": request, "attendees": attendees, "event_id": event_id},
    )


@router.post("/admin/attendances/{attendance_id}/status", response_class=HTMLResponse)
async def update_attendance_status(
    attendance_id: int,
    request: Request,
    status_value: str = Form(...),
    note: str = Form(""),
    _user: str = Depends(get_current_admin),
):
    """出勤状態の更新 + 変更履歴の記録（モックDBモードのみ）。"""
    from datetime import datetime

    settings = get_settings()
    if settings.data_source.lower() != "mockdb":
        return HTMLResponse(status_code=400, content="MockDB mode only for now")

    db = SessionLocal()
    try:
        att = db.query(AttendanceModel).filter_by(id=attendance_id).one_or_none()
        if not att:
            return HTMLResponse(status_code=404, content="Attendance not found")
        att.status = status_value
        att.note = note
        att.updated_at = datetime.utcnow().isoformat()
        change = AttendanceChangeModel(
            attendance_id=attendance_id,
            changed_at=att.updated_at,
            change_type=status_value,
            reason=note,
            source="web-admin",
        )
        db.add(change)
        db.commit()
    finally:
        db.close()

    # 簡易的にリダイレクトでイベント詳細に戻す
    return RedirectResponse(
        url=f"/admin/events/{request.path_params.get('event_id', '')}", status_code=302
    )

