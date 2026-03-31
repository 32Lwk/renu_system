from __future__ import annotations

import re
import secrets
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.auth import get_current_admin
from app.core.config import get_settings
from app.services.assignment import (
    AssignmentInputEvent,
    AssignmentInputMember,
    greedy_assign,
)
from datetime import datetime, timezone

from app.services.db import SessionLocal, Event as EventModel, Member as MemberModel
from app.services.sheet_client import get_sheet_client
from app.services.sheet_schemas import (
    SheetName,
    AttendancesColumns,
    BusyPreferencesColumns,
    EventsColumns,
    MembersColumns,
    get_headers,
)
from app.services.sheet_utils import dict_to_row
from app.core.member_session import get_current_member_id, get_current_member_and_roles
from app.core.roles import MemberRole, leader_teams


templates = Jinja2Templates(directory="app/templates")
router = APIRouter(tags=["busy"])

_PENDING_BATCH_RE = re.compile(r"PENDING_BATCH\|([a-zA-Z0-9_]+)\|")


def _note_for_pending_batch(batch: str, leader_mid: str) -> str:
    return f"PENDING_BATCH|{batch}|leader:{leader_mid}"


def _parse_pending_batch(note: str | None) -> str | None:
    m = _PENDING_BATCH_RE.search(str(note or ""))
    return m.group(1) if m else None


def _member_teams_set(row: dict) -> set[str]:
    return {x.strip() for x in str(row.get(MembersColumns.TEAMS, "") or "").split(",") if x.strip()}


def _event_teams(ev: dict) -> set[str]:
    return {x.strip() for x in str(ev.get(EventsColumns.TARGET_TEAMS, "") or "").split(",") if x.strip()}


@router.get("/admin/busy/summary", response_class=HTMLResponse)
async def admin_busy_summary(
    request: Request,
    _user: str = Depends(get_current_admin),
):
    """繁忙期希望をイベント別に集計する。"""
    client = get_sheet_client()
    prefs = client.get_all_records(SheetName.BUSY_PREFERENCES)
    evs = {str(e.get(EventsColumns.EVENT_ID, "")): e for e in client.get_all_records(SheetName.EVENTS)}

    by_event: dict[str, int] = defaultdict(int)
    for p in prefs:
        eid = str(p.get(BusyPreferencesColumns.EVENT_ID, "") or "")
        if eid:
            by_event[eid] += 1
    rows = []
    for eid, n in sorted(by_event.items(), key=lambda x: (-x[1], x[0])):
        ev = evs.get(eid, {})
        rows.append(
            {
                "event_id": eid,
                "name": ev.get(EventsColumns.NAME, eid),
                "date": ev.get(EventsColumns.DATE, ""),
                "count": n,
            }
        )
    return templates.TemplateResponse(
        "admin_busy_summary.html",
        {
            "request": request,
            "rows": rows,
            "total_prefs": len(prefs),
        },
    )


@router.get("/admin/busy/preview", response_class=HTMLResponse)
async def preview_busy_assignment(
    request: Request,
    _user: str = Depends(get_current_admin),
):
    """繁忙期の簡易割当案をプレビューする開発用画面（モックDBベース）。"""
    settings = get_settings()
    suggestions: list[dict[str, Any]] = []

    if settings.data_source.lower() == "mockdb":
        db = SessionLocal()
        try:
            events = [
                AssignmentInputEvent(
                    id=e.id,
                    date=e.date,
                    required_members=e.required_members or 3,
                    target_teams=(e.target_team_ids or "").split(",") if e.target_team_ids else [],
                )
                for e in db.query(EventModel).all()
            ]
            members = [
                AssignmentInputMember(
                    id=m.id,
                    name=m.name,
                    teams=[],  # 班情報は後続で拡張
                    max_shifts=5,
                )
                for m in db.query(MemberModel).all()
            ]
            results = greedy_assign(events, members)
            name_map = {m.id: m.name for m in members}
            event_map = {e.id: e for e in events}
            for r in results:
                ev = event_map[r.event_id]
                suggestions.append(
                    {
                        "event": ev,
                        "members": [name_map[mid] for mid in r.member_ids],
                    }
                )
        finally:
            db.close()
    else:
        client = get_sheet_client()
        ev_records = client.get_all_records(SheetName.EVENTS)
        mem_records = client.get_all_records(SheetName.MEMBERS)
        events = [
            AssignmentInputEvent(
                id=str(e.get(EventsColumns.EVENT_ID, "")),
                date=str(e.get(EventsColumns.DATE, "")),
                required_members=int(e.get(EventsColumns.REQUIRED_MEMBERS, 3) or 3),
                target_teams=[x.strip() for x in str(e.get(EventsColumns.TARGET_TEAMS, "") or "").split(",") if x.strip()],
            )
            for e in ev_records
            if str(e.get(EventsColumns.IS_BUSY_SEASON, "")).lower() in ("true", "1", "yes")
        ]
        members = [
            AssignmentInputMember(
                id=str(m.get(MembersColumns.MEMBER_ID, "")),
                name=str(m.get(MembersColumns.FULL_NAME, "")),
                teams=[x.strip() for x in str(m.get(MembersColumns.TEAMS, "") or "").split(",") if x.strip()],
                max_shifts=5,
            )
            for m in mem_records
            if str(m.get(MembersColumns.STATUS, "")) == "active"
        ]
        results = greedy_assign(events, members)
        name_map = {m.id: m.name for m in members}
        event_map = {e.id: e for e in events}
        for r in results:
            ev = event_map[r.event_id]
            suggestions.append(
                {
                    "event": ev,
                    "members": [name_map.get(mid, str(mid)) for mid in r.member_ids],
                }
            )

    return templates.TemplateResponse(
        "busy_preview.html",
        {"request": request, "suggestions": suggestions},
    )


@router.get("/my/busy/preferences", response_class=HTMLResponse)
async def busy_preferences_form(request: Request, _member_id: str = Depends(get_current_member_id)):
    return templates.TemplateResponse(
        "busy_preferences_form.html",
        {"request": request, "error": None, "info": None},
    )


@router.post("/my/busy/preferences", response_class=HTMLResponse)
async def busy_preferences_submit(
    request: Request,
    event_id: str = Form(...),
    preferred_role: str = Form(""),
    priority: int = Form(3),
    max_shifts: int = Form(5),
    note: str = Form(""),
    member_id: str = Depends(get_current_member_id),
):
    client = get_sheet_client()
    now = datetime.now(timezone.utc).isoformat()
    values = {
        BusyPreferencesColumns.MEMBER_ID: member_id,
        BusyPreferencesColumns.MEMBER_NAME: "",
        BusyPreferencesColumns.EVENT_ID: event_id.strip(),
        BusyPreferencesColumns.PREFERRED_ROLE: preferred_role.strip(),
        BusyPreferencesColumns.PRIORITY: int(priority),
        BusyPreferencesColumns.MAX_SHIFTS: int(max_shifts),
        BusyPreferencesColumns.NOTE: note.strip(),
        BusyPreferencesColumns.CREATED_AT: now,
        BusyPreferencesColumns.UPDATED_AT: now,
    }
    client.append_row(SheetName.BUSY_PREFERENCES, dict_to_row(get_headers(SheetName.BUSY_PREFERENCES), values))
    return templates.TemplateResponse(
        "busy_preferences_form.html",
        {"request": request, "error": None, "info": "保存しました。"},
    )


@router.get("/my/busy/preferences/list", response_class=HTMLResponse)
async def my_busy_preferences_list(
    request: Request,
    member_id: str = Depends(get_current_member_id),
):
    """自分の繁忙期希望一覧。"""
    client = get_sheet_client()
    records = client.get_all_records(SheetName.BUSY_PREFERENCES)
    mine = [r for r in records if str(r.get(BusyPreferencesColumns.MEMBER_ID, "")) == str(member_id)]
    return templates.TemplateResponse(
        "my_busy_preferences_list.html",
        {"request": request, "preferences": mine},
    )


@router.get("/my/team/busy/preferences", response_class=HTMLResponse)
async def team_busy_preferences_list(
    request: Request,
    ctx=Depends(get_current_member_and_roles),
):
    """自チームの繁忙期希望一覧（Chief / SubLeader / Leader 用）。"""
    member_row, team_roles, overall = ctx
    if overall < MemberRole.CHIEF:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    # 自チーム一覧
    teams = {tr.team for tr in team_roles}

    client = get_sheet_client()
    mem_records = client.get_all_records(SheetName.MEMBERS)
    prefs = client.get_all_records(SheetName.BUSY_PREFERENCES)

    # member_id -> row (members)
    mem_by_id = {str(m.get(MembersColumns.MEMBER_ID, "")): m for m in mem_records}

    result: list[dict[str, Any]] = []
    for p in prefs:
        mid = str(p.get(BusyPreferencesColumns.MEMBER_ID, ""))
        mrow = mem_by_id.get(mid)
        if not mrow:
            continue
        member_teams = [x.strip() for x in str(mrow.get(MembersColumns.TEAMS, "") or "").split(",") if x.strip()]
        if not any(t in teams for t in member_teams):
            continue
        result.append(
            {
                "member_id": mid,
                "member_name": mrow.get(MembersColumns.FULL_NAME, ""),
                "event_id": p.get(BusyPreferencesColumns.EVENT_ID, ""),
                "preferred_role": p.get(BusyPreferencesColumns.PREFERRED_ROLE, ""),
                "priority": p.get(BusyPreferencesColumns.PRIORITY, ""),
                "max_shifts": p.get(BusyPreferencesColumns.MAX_SHIFTS, ""),
                "note": p.get(BusyPreferencesColumns.NOTE, ""),
            }
        )

    return templates.TemplateResponse(
        "team_busy_preferences_list.html",
        {
            "request": request,
            "preferences": result,
            "teams": sorted(teams),
        },
    )


@router.get("/my/team/assignment/proposals", response_class=HTMLResponse)
async def leader_assignment_proposals_form(
    request: Request,
    ctx=Depends(get_current_member_and_roles),
):
    """Leader: 繁忙期イベントへの出勤案を作成する。"""
    member_row, team_roles, overall = ctx
    if overall < MemberRole.LEADER:
        raise HTTPException(status_code=403, detail="Leader のみ利用できます")
    lt = leader_teams(team_roles)
    if not lt:
        return HTMLResponse(status_code=403, content="Leader としてのチームがありません")
    mid = str(member_row.get(MembersColumns.MEMBER_ID, ""))
    client = get_sheet_client()
    evs = client.get_all_records(SheetName.EVENTS)
    mems = client.get_all_records(SheetName.MEMBERS)
    active = [m for m in mems if str(m.get(MembersColumns.STATUS, "")) == "active"]

    event_blocks: list[dict[str, Any]] = []
    for ev in evs:
        if str(ev.get(EventsColumns.IS_BUSY_SEASON, "")).lower() not in ("true", "1", "yes"):
            continue
        et = _event_teams(ev)
        overlap = et & lt
        if not overlap:
            continue
        candidates = [
            m
            for m in active
            if _member_teams_set(m) & overlap
        ]
        event_blocks.append({"event": ev, "candidates": candidates})

    saved = request.query_params.get("saved")
    message = f"{saved} 件を提案として保存しました。" if saved is not None and saved != "" else None

    return templates.TemplateResponse(
        "leader_assignment_proposals.html",
        {
            "request": request,
            "leader_id": mid,
            "event_blocks": event_blocks,
            "message": message,
        },
    )


@router.post("/my/team/assignment/proposals")
async def leader_assignment_proposals_submit(
    request: Request,
    ctx=Depends(get_current_member_and_roles),
):
    member_row, team_roles, overall = ctx
    if overall < MemberRole.LEADER:
        raise HTTPException(status_code=403, detail="Leader のみ利用できます")
    lt = leader_teams(team_roles)
    leader_mid = str(member_row.get(MembersColumns.MEMBER_ID, ""))
    form = await request.form()
    pairs = form.getlist("assign")
    if not pairs:
        return RedirectResponse("/my/team/assignment/proposals", status_code=302)

    client = get_sheet_client()
    evs = {str(e.get(EventsColumns.EVENT_ID, "")): e for e in client.get_all_records(SheetName.EVENTS)}
    mems = client.get_all_records(SheetName.MEMBERS)
    mem_by_id = {str(m.get(MembersColumns.MEMBER_ID, "")): m for m in mems}
    existing = client.get_all_records(SheetName.ATTENDANCES)
    existing_keys = {
        (str(a.get(AttendancesColumns.EVENT_ID, "")), str(a.get(AttendancesColumns.MEMBER_ID, "")))
        for a in existing
        if str(a.get(AttendancesColumns.STATUS, "")).lower() != "pending_proposal"
    }

    batch = secrets.token_hex(6)
    note = _note_for_pending_batch(batch, leader_mid)
    now = datetime.now(timezone.utc).isoformat()
    added = 0

    for raw in pairs:
        part = str(raw).split("|", 1)
        if len(part) != 2:
            continue
        eid, mem_id = part[0].strip(), part[1].strip()
        ev = evs.get(eid)
        if not ev:
            continue
        et = _event_teams(ev)
        if not (et & lt):
            continue
        mrow = mem_by_id.get(mem_id)
        if not mrow or not (_member_teams_set(mrow) & et & lt):
            continue
        if (eid, mem_id) in existing_keys:
            continue
        aid = f"att_prop_{secrets.token_hex(6)}"
        values = {
            AttendancesColumns.ATTENDANCE_ID: aid,
            AttendancesColumns.EVENT_ID: eid,
            AttendancesColumns.MEMBER_ID: mem_id,
            AttendancesColumns.ROLE: "Member",
            AttendancesColumns.STATUS: "pending_proposal",
            AttendancesColumns.NOTE: note,
            AttendancesColumns.UPDATED_AT: now,
        }
        client.append_row(SheetName.ATTENDANCES, dict_to_row(get_headers(SheetName.ATTENDANCES), values))
        added += 1

    return RedirectResponse(
        f"/my/team/assignment/proposals?saved={added}",
        status_code=302,
    )


@router.get("/admin/assignment/proposals", response_class=HTMLResponse)
async def admin_assignment_proposals_list(
    request: Request,
    _user: str = Depends(get_current_admin),
):
    client = get_sheet_client()
    atts = client.get_all_records(SheetName.ATTENDANCES)
    batches: dict[str, list[dict[str, Any]]] = {}
    for a in atts:
        if str(a.get(AttendancesColumns.STATUS, "")).lower() != "pending_proposal":
            continue
        bid = _parse_pending_batch(a.get(AttendancesColumns.NOTE, ""))
        if not bid:
            continue
        batches.setdefault(bid, []).append(dict(a))

    # メタ: 先頭行の leader を表示
    summaries: list[dict[str, Any]] = []
    for bid, rows in sorted(batches.items(), key=lambda x: x[0]):
        note0 = str(rows[0].get(AttendancesColumns.NOTE, ""))
        leader = ""
        if "leader:" in note0:
            leader = note0.split("leader:", 1)[-1].strip()
        summaries.append(
            {
                "batch_id": bid,
                "count": len(rows),
                "leader_member_id": leader,
                "sample_event": rows[0].get(AttendancesColumns.EVENT_ID, ""),
            }
        )

    return templates.TemplateResponse(
        "admin_assignment_proposals.html",
        {"request": request, "summaries": summaries},
    )


@router.get("/admin/assignment/proposals/{batch_id}", response_class=HTMLResponse)
async def admin_assignment_proposal_detail(
    batch_id: str,
    request: Request,
    _user: str = Depends(get_current_admin),
):
    client = get_sheet_client()
    atts = client.get_all_records(SheetName.ATTENDANCES)
    rows: list[tuple[int, dict[str, Any]]] = []
    for idx, a in enumerate(atts, start=2):
        if str(a.get(AttendancesColumns.STATUS, "")).lower() != "pending_proposal":
            continue
        if _parse_pending_batch(a.get(AttendancesColumns.NOTE, "")) != batch_id:
            continue
        rows.append((idx, dict(a)))
    if not rows:
        return HTMLResponse(status_code=404, content="バッチが見つかりません")

    evs = {str(e.get(EventsColumns.EVENT_ID, "")): e for e in client.get_all_records(SheetName.EVENTS)}
    mems = {str(m.get(MembersColumns.MEMBER_ID, "")): m for m in client.get_all_records(SheetName.MEMBERS)}

    display = []
    for _ri, r in rows:
        eid = r.get(AttendancesColumns.EVENT_ID, "")
        mid = r.get(AttendancesColumns.MEMBER_ID, "")
        ev = evs.get(eid, {})
        m = mems.get(mid, {})
        display.append(
            {
                "row_hint": r.get(AttendancesColumns.ATTENDANCE_ID, ""),
                "event_id": eid,
                "event_name": ev.get(EventsColumns.NAME, eid),
                "member_id": mid,
                "member_name": m.get(MembersColumns.FULL_NAME, mid),
            }
        )

    return templates.TemplateResponse(
        "admin_assignment_proposal_detail.html",
        {
            "request": request,
            "batch_id": batch_id,
            "rows": display,
        },
    )


@router.post("/admin/assignment/proposals/{batch_id}/approve")
async def admin_assignment_proposal_approve(
    batch_id: str,
    _user: str = Depends(get_current_admin),
):
    client = get_sheet_client()
    headers = get_headers(SheetName.ATTENDANCES)
    atts = client.get_all_records(SheetName.ATTENDANCES)
    now = datetime.now(timezone.utc).isoformat()
    for idx, a in enumerate(atts, start=2):
        if str(a.get(AttendancesColumns.STATUS, "")).lower() != "pending_proposal":
            continue
        if _parse_pending_batch(a.get(AttendancesColumns.NOTE, "")) != batch_id:
            continue
        vals = dict(a)
        vals[AttendancesColumns.STATUS] = "planned"
        vals[AttendancesColumns.NOTE] = ""
        vals[AttendancesColumns.UPDATED_AT] = now
        client.update_row(SheetName.ATTENDANCES, idx, dict_to_row(headers, vals))
    return RedirectResponse("/admin/assignment/proposals", status_code=302)


@router.post("/admin/assignment/proposals/{batch_id}/reject")
async def admin_assignment_proposal_reject(
    batch_id: str,
    _user: str = Depends(get_current_admin),
):
    client = get_sheet_client()
    atts = client.get_all_records(SheetName.ATTENDANCES)
    to_delete: list[int] = []
    for idx, a in enumerate(atts, start=2):
        if str(a.get(AttendancesColumns.STATUS, "")).lower() != "pending_proposal":
            continue
        if _parse_pending_batch(a.get(AttendancesColumns.NOTE, "")) != batch_id:
            continue
        to_delete.append(idx)
    for idx in sorted(to_delete, reverse=True):
        client.delete_row(SheetName.ATTENDANCES, idx)
    return RedirectResponse("/admin/assignment/proposals", status_code=302)

