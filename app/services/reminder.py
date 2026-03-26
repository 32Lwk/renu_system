from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from app.core.config import get_settings
from app.services.db import SessionLocal, Event as EventModel, Attendance as AttendanceModel, Member as MemberModel
from app.services.sheets_repo import SheetRepo


def get_tomorrow_events():
    settings = get_settings()
    today = datetime.utcnow().date()
    target = today + timedelta(days=1)
    if settings.data_source.lower() != "mockdb":
        repo = SheetRepo()
        events = []
        for e in repo.list_events():
            if str(e.get("date", "")) == target.isoformat():
                events.append(e)
        return events

    db = SessionLocal()
    try:
        events = (
            db.query(EventModel)
            .filter(EventModel.date == target.isoformat())
            .all()
        )
        return events
    finally:
        db.close()


def build_reminder_messages() -> list[str]:
    """翌日のイベントについて、出勤予定者ごとに簡易メッセージを生成する。"""
    settings = get_settings()
    if settings.data_source.lower() != "mockdb":
        repo = SheetRepo()
        events = get_tomorrow_events()
        messages: list[str] = []
        mems = {m.get("member_id", ""): m for m in repo.list_members()}
        atts = repo.list_attendances()
        for ev in events:
            ev_id = ev.get("event_id", "")
            planned = [a for a in atts if a.get("event_id", "") == ev_id and a.get("status", "") == "planned"]
            if not planned:
                continue
            header = f"【明日の出勤リマインド】{ev.get('date','')} {ev.get('start_time','')}〜 {ev.get('name','')}"
            lines = [header, ""]
            for att in planned:
                mem = mems.get(att.get("member_id", ""), {})
                lines.append(f"- {mem.get('full_name','')} さん（役割: {att.get('role','未設定') or '未設定'}）")
            messages.append("\n".join(lines))
        return messages

    db = SessionLocal()
    messages: list[str] = []
    try:
        events = get_tomorrow_events()
        for ev in events:
            rows = (
                db.query(AttendanceModel, MemberModel)
                .join(MemberModel, AttendanceModel.member_id == MemberModel.id)
                .filter(AttendanceModel.event_id == ev.id, AttendanceModel.status == "planned")
                .all()
            )
            if not rows:
                continue
            header = f"【明日の出勤リマインド】{ev.date} {ev.start_time}〜 {ev.name}"
            lines = [header, ""]
            for att, mem in rows:
                lines.append(f"- {mem.name} さん（役割: {att.role_name or '未設定'}）")
            messages.append("\n".join(lines))
    finally:
        db.close()

    return messages

