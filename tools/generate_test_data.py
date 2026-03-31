from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.services.sheet_schemas import (
    SheetName,
    MembersColumns,
    EventsColumns,
    AttendancesColumns,
    AttendanceChangesColumns,
    BusyPreferencesColumns,
    get_headers,
)

OUT_DIR = BASE_DIR / "docs" / "testdata"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def write_csv(sheet: SheetName, rows: list[dict[str, Any]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    headers = get_headers(sheet)
    path = OUT_DIR / f"{sheet.value}.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for r in rows:
            writer.writerow([r.get(h, "") for h in headers])


def gen_members(count: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    now = _now()
    for i in range(1, count + 1):
        # 学年の比率: 1年:2年:3年:4年 = 4:3:2:1 （合計10のうち）
        # 全体100人として、おおよそ 40, 30, 20, 10 人に対応
        if i <= 40:
            grade = "B1"  # 1年生
            entrance_year = 25
        elif i <= 70:
            grade = "B2"  # 2年生
            entrance_year = 24
        elif i <= 90:
            grade = "B3"  # 3年生
            entrance_year = 23
        else:
            grade = "B4"  # 4年生
            entrance_year = 22
        faculty_code = f"{(i % 9) + 1:02d}"
        member_id = f"mem_seed_{i:03d}"
        teams = []
        if i % 2 == 0:
            teams.append("すまい")
        if i % 3 == 0:
            teams.append("PC")
        if i % 5 == 0:
            teams.append("キャリア")
        teams.append("提案")
        roles = []
        if i <= 8:
            roles.append("Leader")
        elif i <= 20:
            roles.append("SubLeader")
        elif i <= 40:
            roles.append("Chief")
        else:
            roles.append("Member")
        email = f"member{i:03d}@example.com"
        rows.append(
            {
                MembersColumns.MEMBER_ID: member_id,
                MembersColumns.FULL_NAME: f"メンバー{i}",
                MembersColumns.STUDENT_ID: f"{faculty_code}{entrance_year:02d}{i:05d}",
                MembersColumns.EMAIL: email,
                MembersColumns.FACULTY_CODE: faculty_code,
                MembersColumns.ENTRANCE_YEAR: str(entrance_year),
                MembersColumns.GRADE: grade,
                MembersColumns.DISCORD_USER_ID: f"discord_{i:03d}",
                MembersColumns.DISCORD_USERNAME: f"member{i:03d}",
                MembersColumns.TEAMS: ",".join(teams),
                MembersColumns.ROLES: ",".join(roles),
                MembersColumns.STATUS: "active",
                MembersColumns.EMAIL_VERIFIED: True,
                MembersColumns.EMAIL_VERIFIED_AT: _iso(now),
                MembersColumns.MERGE_TARGET_MEMBER_ID: "",
                MembersColumns.APPROVED_BY: "seed",
                MembersColumns.APPROVED_AT: _iso(now),
                MembersColumns.CREATED_AT: _iso(now - timedelta(days=7)),
                MembersColumns.LAST_LOGIN_AT: _iso(now - timedelta(days=1)),
                MembersColumns.UPDATED_AT: _iso(now),
            }
        )
    return rows


def gen_events(days: int = 14) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    today = _now().date()
    name_counts: dict[tuple[str, str], int] = {}
    for i in range(days):
        d = today + timedelta(days=i)
        for j, start in enumerate(["10:00", "14:00"], start=1):
            event_id = f"ev_{d.strftime('%Y%m%d')}_{j}"
            is_busy = "true" if d.weekday() in (5, 6) else "false"
            mmdd = d.strftime("%m%d")
            team_label = "総合"
            key = (mmdd, team_label)
            name_counts[key] = name_counts.get(key, 0) + 1
            name = f"{mmdd}_{team_label}" if name_counts[key] == 1 else f"{mmdd}_{team_label}_{name_counts[key]}"
            rows.append(
                {
                    EventsColumns.EVENT_ID: event_id,
                    EventsColumns.DATE: d.isoformat(),
                    EventsColumns.START_TIME: start,
                    EventsColumns.END_TIME: "18:00",
                    EventsColumns.NAME: name,
                    EventsColumns.REQUIRED_MEMBERS: 5,
                    EventsColumns.TARGET_TEAMS: "すまい,PC,提案,キャリア",
                    EventsColumns.IS_BUSY_SEASON: is_busy,
                    EventsColumns.CONFIRMED: "false",
                    EventsColumns.UPDATED_AT: _iso(_now()),
                }
            )
    return rows


def gen_attendances(
    events: list[dict[str, Any]],
    members: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    now = _now()
    att_id = 1
    # 単純にイベントごとに先頭5人を割り当て
    for ev in events:
        ev_id = ev[EventsColumns.EVENT_ID]
        for i, mem in enumerate(members[:5]):
            member_id = mem[MembersColumns.MEMBER_ID]
            role = "Leader" if i == 0 else "Member"
            rows.append(
                {
                    AttendancesColumns.ATTENDANCE_ID: f"att_{att_id:04d}",
                    AttendancesColumns.EVENT_ID: ev_id,
                    AttendancesColumns.MEMBER_ID: member_id,
                    AttendancesColumns.ROLE: role,
                    AttendancesColumns.STATUS: "planned",
                    AttendancesColumns.NOTE: "",
                    AttendancesColumns.UPDATED_AT: _iso(now),
                }
            )
            att_id += 1
    return rows


def gen_attendance_changes(attendances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    now = _now()
    change_id = 1
    # 最初の数件に対して欠席・遅刻の変更サンプルを付与
    for a in attendances[:10]:
        rows.append(
            {
                AttendanceChangesColumns.CHANGE_ID: f"chg_{change_id:04d}",
                AttendanceChangesColumns.CHANGED_AT: _iso(now - timedelta(days=1)),
                AttendanceChangesColumns.EVENT_ID: a[AttendancesColumns.EVENT_ID],
                AttendanceChangesColumns.MEMBER_ID: a[AttendancesColumns.MEMBER_ID],
                AttendanceChangesColumns.ATTENDANCE_ID: a[AttendancesColumns.ATTENDANCE_ID],
                AttendanceChangesColumns.CHANGE_TYPE: "absent",
                AttendanceChangesColumns.REASON: "体調不良のため",
                AttendanceChangesColumns.SOURCE: "web-member",
            }
        )
        change_id += 1
    return rows


def gen_busy_preferences(
    events: list[dict[str, Any]],
    members: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    now = _now()
    busy_events = [e for e in events if str(e.get(EventsColumns.IS_BUSY_SEASON, "")).lower() in ("true", "1", "yes")]
    for ev in busy_events[:10]:
        ev_id = ev[EventsColumns.EVENT_ID]
        for mem in members[:10]:
            member_id = mem[MembersColumns.MEMBER_ID]
            rows.append(
                {
                    BusyPreferencesColumns.MEMBER_ID: member_id,
                    BusyPreferencesColumns.MEMBER_NAME: mem[MembersColumns.FULL_NAME],
                    BusyPreferencesColumns.EVENT_ID: ev_id,
                    BusyPreferencesColumns.PREFERRED_ROLE: "Member",
                    BusyPreferencesColumns.PRIORITY: 3,
                    BusyPreferencesColumns.MAX_SHIFTS: 5,
                    BusyPreferencesColumns.NOTE: "",
                    BusyPreferencesColumns.CREATED_AT: _iso(now - timedelta(days=2)),
                    BusyPreferencesColumns.UPDATED_AT: _iso(now),
                }
            )
    return rows


def main() -> None:
    members = gen_members()
    events = gen_events()
    attendances = gen_attendances(events, members)
    changes = gen_attendance_changes(attendances)
    prefs = gen_busy_preferences(events, members)

    write_csv(SheetName.MEMBERS, members)
    write_csv(SheetName.EVENTS, events)
    write_csv(SheetName.ATTENDANCES, attendances)
    write_csv(SheetName.ATTENDANCE_CHANGES, changes)
    write_csv(SheetName.BUSY_PREFERENCES, prefs)

    print(f"Test data generated under: {OUT_DIR}")


if __name__ == "__main__":
    main()

