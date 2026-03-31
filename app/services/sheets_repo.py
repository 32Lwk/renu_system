from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.sheet_client import get_sheet_client
from app.services.sheet_schemas import (
    SheetName,
    EventsColumns,
    AttendancesColumns,
    AttendanceChangesColumns,
    MembersColumns,
    get_headers,
)
from app.services.sheet_utils import dict_to_row


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SheetRepo:
    """Sheets 読み書きをアプリ用の形に寄せる薄いリポジトリ層。"""

    def list_events(self) -> list[dict[str, Any]]:
        client = get_sheet_client()
        return client.get_all_records(SheetName.EVENTS)

    def list_members(self) -> list[dict[str, Any]]:
        client = get_sheet_client()
        return client.get_all_records(SheetName.MEMBERS)

    def list_attendances(self) -> list[dict[str, Any]]:
        client = get_sheet_client()
        return client.get_all_records(SheetName.ATTENDANCES)

    def list_attendance_changes(self) -> list[dict[str, Any]]:
        client = get_sheet_client()
        return client.get_all_records(SheetName.ATTENDANCE_CHANGES)

    def find_event(self, event_id: str) -> Optional[dict[str, Any]]:
        for rec in self.list_events():
            if str(rec.get(EventsColumns.EVENT_ID, "")) == str(event_id):
                return rec
        return None

    def find_member(self, member_id: str) -> Optional[dict[str, Any]]:
        for rec in self.list_members():
            if str(rec.get(MembersColumns.MEMBER_ID, "")) == str(member_id):
                return rec
        return None

    def _find_row_index(self, sheet: SheetName, key: str, value: str) -> tuple[int | None, dict[str, Any] | None]:
        client = get_sheet_client()
        records = client.get_all_records(sheet)
        for idx, rec in enumerate(records, start=2):
            if str(rec.get(key, "")) == str(value):
                return idx, rec
        return None, None

    def update_attendance_status(
        self,
        attendance_id: str,
        status: str,
        note: str,
        source: str,
    ) -> None:
        client = get_sheet_client()
        row_idx, att = self._find_row_index(SheetName.ATTENDANCES, AttendancesColumns.ATTENDANCE_ID, attendance_id)
        if not row_idx or att is None:
            raise ValueError("attendance not found")

        now = _now_iso()
        att2 = dict(att)
        att2[AttendancesColumns.STATUS] = status
        att2[AttendancesColumns.NOTE] = note
        att2[AttendancesColumns.UPDATED_AT] = now
        client.update_row(SheetName.ATTENDANCES, row_idx, dict_to_row(get_headers(SheetName.ATTENDANCES), att2))

        # 変更履歴を追記
        change = {
            AttendanceChangesColumns.CHANGE_ID: f"chg_{attendance_id}_{int(datetime.now(timezone.utc).timestamp())}",
            AttendanceChangesColumns.CHANGED_AT: now,
            AttendanceChangesColumns.EVENT_ID: att.get(AttendancesColumns.EVENT_ID, ""),
            AttendanceChangesColumns.MEMBER_ID: att.get(AttendancesColumns.MEMBER_ID, ""),
            AttendanceChangesColumns.ATTENDANCE_ID: attendance_id,
            AttendanceChangesColumns.CHANGE_TYPE: status,
            AttendanceChangesColumns.REASON: note,
            AttendanceChangesColumns.SOURCE: source,
        }
        client.append_row(SheetName.ATTENDANCE_CHANGES, dict_to_row(get_headers(SheetName.ATTENDANCE_CHANGES), change))

