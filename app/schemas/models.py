from __future__ import annotations

from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, ConfigDict, Field, EmailStr


class MemberBase(BaseModel):
    name: str
    grade: Literal["B1", "B2", "B3"]
    email: Optional[EmailStr] = None
    discord_id: Optional[str] = None
    student_id: Optional[str] = None
    university: str = "Nagoya University"
    teams: list[str] = Field(default_factory=list, description="所属班名の一覧")


class MemberCreate(MemberBase):
    pass


class Member(MemberBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class EventBase(BaseModel):
    name: str
    date: str
    start_time: str
    end_time: str
    required_members: Optional[int] = None
    target_teams: list[str] = Field(default_factory=list)


class EventCreate(EventBase):
    pass


class Event(EventBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


AttendanceStatus = Literal["planned", "absent", "late", "leave_early"]


class AttendanceBase(BaseModel):
    event_id: int
    member_id: int
    role_name: Optional[str] = None
    status: AttendanceStatus = "planned"
    note: Optional[str] = None


class Attendance(AttendanceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    updated_at: Optional[datetime] = None


class AttendanceChange(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    attendance_id: int
    changed_at: datetime
    change_type: Literal["absent", "late", "leave_early"]
    reason: Optional[str] = None
    source: Optional[str] = None

