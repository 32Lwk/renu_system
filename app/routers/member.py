from __future__ import annotations

from typing import Any
import csv
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.core.member_session import get_current_member_id, get_current_member_and_roles
from app.core.roles import MemberRole, managed_teams_subleader_plus
from app.services.sheet_client import get_sheet_client
from app.services.sheet_schemas import (
    SheetName,
    MembersColumns,
    AttendancesColumns,
    EventsColumns,
    get_headers,
)
from app.services.sheet_utils import dict_to_row
from app.services.db import (
    SessionLocal,
    Attendance as AttendanceModel,
    Event as EventModel,
    AttendanceChange as AttendanceChangeModel,
)
from app.services.sheets_repo import SheetRepo


templates = Jinja2Templates(directory="app/templates")
router = APIRouter(tags=["member"])


@router.get("/my", response_class=HTMLResponse)
async def my_dashboard(
    request: Request,
    ctx=Depends(get_current_member_and_roles),
):
    """メンバー用マイページ。プロフィール情報と主要な導線を表示する。"""
    settings = get_settings()
    member_row, team_roles, overall_role = ctx

    member_info: dict[str, Any] = {
        "full_name": member_row.get(MembersColumns.FULL_NAME, "") if member_row else "",
        "grade": member_row.get(MembersColumns.GRADE, "") if member_row else "",
        "teams": member_row.get(MembersColumns.TEAMS, "") if member_row else "",
        "roles": member_row.get(MembersColumns.ROLES, "") if member_row else "",
    }

    return templates.TemplateResponse(
        "member_dashboard.html",
        {
            "request": request,
            "member": member_info,
            "overall_role": overall_role,
            "team_roles": team_roles,
        },
    )


@router.get("/my/events", response_class=HTMLResponse)
async def my_events(
    request: Request,
    member_session_id: str = Depends(get_current_member_id),
):
    settings = get_settings()
    events: list[dict[str, Any]] = []
    if settings.data_source.lower() == "mockdb":
        try:
            member_id_int = int(member_session_id)
        except ValueError:
            return HTMLResponse(status_code=400, content="Invalid member id for mockdb")
        db = SessionLocal()
        try:
            rows = (
                db.query(AttendanceModel, EventModel)
                .join(EventModel, AttendanceModel.event_id == EventModel.id)
                .filter(AttendanceModel.member_id == member_id_int)
                .all()
            )
            for att, ev in rows:
                events.append(
                    {
                        "attendance_id": att.id,
                        "event_name": ev.name,
                        "date": ev.date,
                        "start_time": ev.start_time,
                        "end_time": ev.end_time,
                        "status": att.status,
                        "note": att.note,
                    }
                )
        finally:
            db.close()
    else:
        repo = SheetRepo()
        atts = repo.list_attendances()
        evs = {e.get("event_id", ""): e for e in repo.list_events()}
        for a in atts:
            if str(a.get(AttendancesColumns.MEMBER_ID, "")) != str(member_session_id):
                continue
            ev = evs.get(a.get(AttendancesColumns.EVENT_ID, ""), {})
            events.append(
                {
                    "attendance_id": a.get(AttendancesColumns.ATTENDANCE_ID, ""),
                    "event_name": ev.get("name", ""),
                    "date": ev.get("date", ""),
                    "start_time": ev.get("start_time", ""),
                    "end_time": ev.get("end_time", ""),
                    "status": a.get("status", ""),
                    "note": a.get("note", ""),
                }
            )

    return templates.TemplateResponse(
        "member_events.html",
        {"request": request, "events": events},
    )


@router.post("/my/attendances/{attendance_id}/change")
async def apply_attendance_change(
    attendance_id: int,
    reason: str = Form(""),
    status_value: str = Form(...),
    member_session_id: str = Depends(get_current_member_id),
):
    """メンバーからの出勤変更申請（モックDBモード）。"""
    from datetime import datetime

    settings = get_settings()
    if settings.data_source.lower() != "mockdb":
        repo = SheetRepo()
        try:
            repo.update_attendance_status(str(attendance_id), status_value, reason, "web-member")
        except ValueError:
            return HTMLResponse(status_code=404, content="Attendance not found")
        return RedirectResponse(url="/my/events", status_code=302)

    db = SessionLocal()
    try:
        try:
            member_id_int = int(member_session_id)
        except ValueError:
            return HTMLResponse(status_code=400, content="Invalid member id for mockdb")
        att = (
            db.query(AttendanceModel)
            .filter_by(id=attendance_id, member_id=member_id_int)
            .one_or_none()
        )
        if not att:
            return HTMLResponse(status_code=404, content="Attendance not found")
        att.status = status_value
        att.note = reason
        now = datetime.utcnow().isoformat()
        att.updated_at = now
        change = AttendanceChangeModel(
            attendance_id=attendance_id,
            changed_at=now,
            change_type=status_value,
            reason=reason,
            source="web-member",
        )
        db.add(change)
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/my/events", status_code=302)


def _event_target_team(ev: dict) -> str:
    return str(ev.get(EventsColumns.TARGET_TEAMS, "") or "").split(",")[0].strip()


def _member_teams_set(row: dict) -> set[str]:
    return {x.strip() for x in str(row.get(MembersColumns.TEAMS, "") or "").split(",") if x.strip()}


@router.get("/my/team/events", response_class=HTMLResponse)
async def team_events_list(request: Request, ctx=Depends(get_current_member_and_roles)):
    member_row, team_roles, overall = ctx
    if overall < MemberRole.SUBLEADER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SubLeader以上が必要です")
    managed = managed_teams_subleader_plus(team_roles)
    if not managed:
        return HTMLResponse(status_code=403, content="管理対象チームがありません")
    client = get_sheet_client()
    evs = client.get_all_records(SheetName.EVENTS)
    mine = [e for e in evs if _event_target_team(e) in managed]
    return templates.TemplateResponse(
        "team_events_list.html",
        {"request": request, "events": mine, "managed_teams": sorted(managed)},
    )


@router.get("/my/team/events/new", response_class=HTMLResponse)
async def team_event_new_form(request: Request, ctx=Depends(get_current_member_and_roles)):
    member_row, team_roles, overall = ctx
    if overall < MemberRole.SUBLEADER:
        raise HTTPException(status_code=403, detail="SubLeader以上が必要です")
    managed = sorted(managed_teams_subleader_plus(team_roles))
    if not managed:
        return HTMLResponse(status_code=403, content="管理対象チームがありません")
    return templates.TemplateResponse(
        "team_event_form.html",
        {"request": request, "mode": "new", "event": {}, "teams": managed, "error": None},
    )


@router.post("/my/team/events/new", response_class=HTMLResponse)
async def team_event_new_submit(
    request: Request,
    date: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    name: str = Form(...),
    required_members: int = Form(3),
    target_team: str = Form(...),
    is_busy_season: str = Form("false"),
    ctx=Depends(get_current_member_and_roles),
):
    member_row, team_roles, overall = ctx
    if overall < MemberRole.SUBLEADER:
        raise HTTPException(status_code=403, detail="SubLeader以上が必要です")
    managed = managed_teams_subleader_plus(team_roles)
    if target_team.strip() not in managed:
        return templates.TemplateResponse(
            "team_event_form.html",
            {
                "request": request,
                "mode": "new",
                "event": {},
                "teams": sorted(managed),
                "error": "選択したチームは管理対象外です",
            },
            status_code=400,
        )
    now = datetime.now(timezone.utc).isoformat()
    event_id = f"ev_{secrets.token_hex(8)}"
    busy = str(is_busy_season).lower() in ("true", "1", "yes", "on")
    values = {
        EventsColumns.EVENT_ID: event_id,
        EventsColumns.DATE: date.strip(),
        EventsColumns.START_TIME: start_time.strip(),
        EventsColumns.END_TIME: end_time.strip(),
        EventsColumns.NAME: name.strip(),
        EventsColumns.REQUIRED_MEMBERS: int(required_members),
        EventsColumns.TARGET_TEAMS: target_team.strip(),
        EventsColumns.IS_BUSY_SEASON: "true" if busy else "false",
        EventsColumns.CONFIRMED: "false",
        EventsColumns.UPDATED_AT: now,
    }
    client = get_sheet_client()
    client.append_row(SheetName.EVENTS, dict_to_row(get_headers(SheetName.EVENTS), values))
    return RedirectResponse(url="/my/team/events", status_code=302)


def _find_event_row(event_id: str) -> tuple[int | None, dict | None]:
    client = get_sheet_client()
    recs = client.get_all_records(SheetName.EVENTS)
    for idx, rec in enumerate(recs, start=2):
        if str(rec.get(EventsColumns.EVENT_ID, "")) == str(event_id):
            return idx, dict(rec)
    return None, None


@router.get("/my/team/events/{event_id}/edit", response_class=HTMLResponse)
async def team_event_edit_form(event_id: str, request: Request, ctx=Depends(get_current_member_and_roles)):
    member_row, team_roles, overall = ctx
    if overall < MemberRole.SUBLEADER:
        raise HTTPException(status_code=403, detail="SubLeader以上が必要です")
    managed = managed_teams_subleader_plus(team_roles)
    _, ev = _find_event_row(event_id)
    if not ev or _event_target_team(ev) not in managed:
        return HTMLResponse(status_code=404, content="イベントが見つかりません")
    return templates.TemplateResponse(
        "team_event_form.html",
        {
            "request": request,
            "mode": "edit",
            "event": ev,
            "teams": sorted(managed),
            "error": None,
        },
    )


@router.post("/my/team/events/{event_id}/edit", response_class=HTMLResponse)
async def team_event_edit_submit(
    event_id: str,
    request: Request,
    date: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    name: str = Form(...),
    required_members: int = Form(3),
    target_team: str = Form(...),
    is_busy_season: str = Form("false"),
    ctx=Depends(get_current_member_and_roles),
):
    member_row, team_roles, overall = ctx
    if overall < MemberRole.SUBLEADER:
        raise HTTPException(status_code=403, detail="SubLeader以上が必要です")
    managed = managed_teams_subleader_plus(team_roles)
    row_idx, ev = _find_event_row(event_id)
    if not row_idx or not ev or _event_target_team(ev) not in managed:
        return HTMLResponse(status_code=404, content="イベントが見つかりません")
    if target_team.strip() not in managed:
        return templates.TemplateResponse(
            "team_event_form.html",
            {
                "request": request,
                "mode": "edit",
                "event": ev,
                "teams": sorted(managed),
                "error": "選択したチームは管理対象外です",
            },
            status_code=400,
        )
    now = datetime.now(timezone.utc).isoformat()
    busy = str(is_busy_season).lower() in ("true", "1", "yes", "on")
    values = dict(ev)
    values[EventsColumns.DATE] = date.strip()
    values[EventsColumns.START_TIME] = start_time.strip()
    values[EventsColumns.END_TIME] = end_time.strip()
    values[EventsColumns.NAME] = name.strip()
    values[EventsColumns.REQUIRED_MEMBERS] = int(required_members)
    values[EventsColumns.TARGET_TEAMS] = target_team.strip()
    values[EventsColumns.IS_BUSY_SEASON] = "true" if busy else "false"
    values[EventsColumns.UPDATED_AT] = now
    client = get_sheet_client()
    client.update_row(SheetName.EVENTS, row_idx, dict_to_row(get_headers(SheetName.EVENTS), values))
    return RedirectResponse(url="/my/team/events", status_code=302)


@router.get("/my/team/events/{event_id}/attendances", response_class=HTMLResponse)
async def team_event_attendances(
    event_id: str,
    request: Request,
    ctx=Depends(get_current_member_and_roles),
):
    member_row, team_roles, overall = ctx
    if overall < MemberRole.SUBLEADER:
        raise HTTPException(status_code=403, detail="SubLeader以上が必要です")
    managed = managed_teams_subleader_plus(team_roles)
    _, ev = _find_event_row(event_id)
    if not ev or _event_target_team(ev) not in managed:
        return HTMLResponse(status_code=404, content="イベントが見つかりません")
    target = _event_target_team(ev)
    client = get_sheet_client()
    mems = client.get_all_records(SheetName.MEMBERS)
    atts = client.get_all_records(SheetName.ATTENDANCES)
    team_members = [
        m
        for m in mems
        if target in _member_teams_set(m) and str(m.get(MembersColumns.STATUS, "")) == "active"
    ]
    current = [a for a in atts if str(a.get(AttendancesColumns.EVENT_ID, "")) == str(event_id)]
    assigned_ids = {str(a.get(AttendancesColumns.MEMBER_ID, "")) for a in current}
    available = [m for m in team_members if str(m.get(MembersColumns.MEMBER_ID, "")) not in assigned_ids]
    return templates.TemplateResponse(
        "team_event_attendances.html",
        {
            "request": request,
            "event": ev,
            "attendances": current,
            "available_members": available,
        },
    )


@router.post("/my/team/events/{event_id}/attendances/add", response_class=HTMLResponse)
async def team_event_attendance_add(
    event_id: str,
    member_id: str = Form(...),
    role: str = Form("Member"),
    ctx=Depends(get_current_member_and_roles),
):
    member_row, team_roles, overall = ctx
    if overall < MemberRole.SUBLEADER:
        raise HTTPException(status_code=403, detail="SubLeader以上が必要です")
    managed = managed_teams_subleader_plus(team_roles)
    _, ev = _find_event_row(event_id)
    if not ev or _event_target_team(ev) not in managed:
        return HTMLResponse(status_code=404, content="イベントが見つかりません")
    target = _event_target_team(ev)
    client = get_sheet_client()
    mems = client.get_all_records(SheetName.MEMBERS)
    mrow = next((m for m in mems if str(m.get(MembersColumns.MEMBER_ID, "")) == str(member_id)), None)
    if not mrow or target not in _member_teams_set(mrow):
        return HTMLResponse(status_code=400, content="無効なメンバーです")
    now = datetime.now(timezone.utc).isoformat()
    aid = f"att_{secrets.token_hex(8)}"
    values = {
        AttendancesColumns.ATTENDANCE_ID: aid,
        AttendancesColumns.EVENT_ID: event_id,
        AttendancesColumns.MEMBER_ID: member_id.strip(),
        AttendancesColumns.ROLE: role.strip() or "Member",
        AttendancesColumns.STATUS: "planned",
        AttendancesColumns.NOTE: "",
        AttendancesColumns.UPDATED_AT: now,
    }
    client.append_row(SheetName.ATTENDANCES, dict_to_row(get_headers(SheetName.ATTENDANCES), values))
    return RedirectResponse(url=f"/my/team/events/{event_id}/attendances", status_code=302)


@router.post("/my/team/events/{event_id}/attendances/{attendance_id}/remove", response_class=HTMLResponse)
async def team_event_attendance_remove(
    event_id: str,
    attendance_id: str,
    ctx=Depends(get_current_member_and_roles),
):
    member_row, team_roles, overall = ctx
    if overall < MemberRole.SUBLEADER:
        raise HTTPException(status_code=403, detail="SubLeader以上が必要です")
    managed = managed_teams_subleader_plus(team_roles)
    _, ev = _find_event_row(event_id)
    if not ev or _event_target_team(ev) not in managed:
        return HTMLResponse(status_code=404, content="イベントが見つかりません")
    client = get_sheet_client()
    recs = client.get_all_records(SheetName.ATTENDANCES)
    row_idx = None
    for idx, rec in enumerate(recs, start=2):
        if str(rec.get(AttendancesColumns.ATTENDANCE_ID, "")) == str(attendance_id):
            if str(rec.get(AttendancesColumns.EVENT_ID, "")) != str(event_id):
                return HTMLResponse(status_code=400, content="不一致")
            row_idx = idx
            break
    if not row_idx:
        return HTMLResponse(status_code=404, content="出勤行が見つかりません")
    client.delete_row(SheetName.ATTENDANCES, row_idx)
    return RedirectResponse(url=f"/my/team/events/{event_id}/attendances", status_code=302)

