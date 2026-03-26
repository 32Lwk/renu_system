from __future__ import annotations

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    ForeignKey,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session

from app.core.config import get_settings

Base = declarative_base()


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)

    members = relationship("MemberTeam", back_populates="team")


class Member(Base):
    __tablename__ = "members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    grade = Column(String, nullable=False)
    email = Column(String)
    discord_id = Column(String)
    student_id = Column(String)
    university = Column(String, default="Nagoya University")

    teams = relationship("MemberTeam", back_populates="member")


class MemberTeam(Base):
    __tablename__ = "member_teams"

    member_id = Column(Integer, ForeignKey("members.id"), primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), primary_key=True)
    role = Column(String, nullable=False)

    member = relationship("Member", back_populates="teams")
    team = relationship("Team", back_populates="members")


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    date = Column(String, nullable=False)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=False)
    required_members = Column(Integer)
    target_team_ids = Column(Text)


class Attendance(Base):
    __tablename__ = "attendances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    role_name = Column(String)
    status = Column(String, nullable=False)
    note = Column(Text)
    updated_at = Column(String)


class AttendanceChange(Base):
    __tablename__ = "attendance_changes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    attendance_id = Column(Integer, ForeignKey("attendances.id"), nullable=False)
    changed_at = Column(String, nullable=False)
    change_type = Column(String, nullable=False)
    reason = Column(Text)
    source = Column(String)


def get_engine_url() -> str:
    # 単純なローカル SQLite。設定を追加したくなったらここで変更する。
    return "sqlite:///dev.db"


engine = create_engine(get_engine_url(), echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def init_db() -> None:
    """開発用モックDBの初期化。"""
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

