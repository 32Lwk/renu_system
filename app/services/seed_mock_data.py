from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from app.services.db import Team, Member, MemberTeam, init_db, SessionLocal


TEAM_NAMES = ["すまい", "PC", "提案", "キャリア"]


def _ensure_teams(db: Session) -> list[Team]:
    teams = []
    for name in TEAM_NAMES:
        team = db.query(Team).filter_by(name=name).one_or_none()
        if not team:
            team = Team(name=name)
            db.add(team)
        teams.append(team)
    db.commit()
    return teams


def _seed_members(db: Session, count: int = 100) -> list[Member]:
    members: list[Member] = []
    for i in range(1, count + 1):
        if i <= 30:
            grade = "B2"
        elif i <= 65:
            grade = "B1"
        else:
            grade = "B3"
        m = Member(
            name=f"メンバー{i}",
            grade=grade,
            email=f"renu{i}@example.com",
            discord_id=f"renu_member_{i}",
            student_id=f"2023{i:04d}",
        )
        db.add(m)
        members.append(m)
    db.commit()
    return members


def _assign_roles(db: Session, teams: Iterable[Team], members: list[Member]) -> None:
    # B2 メンバーのみから役職を割り当てる
    b2_members = [m for m in members if m.grade == "B2"]
    idx = 0
    for team in teams:
        # Leader 1
        leader = b2_members[idx % len(b2_members)]
        db.add(MemberTeam(member=leader, team=team, role="Leader"))
        idx += 1
        # SubLeader 1
        sub = b2_members[idx % len(b2_members)]
        db.add(MemberTeam(member=sub, team=team, role="SubLeader"))
        idx += 1
        # Chiefs 3
        for _ in range(3):
            chief = b2_members[idx % len(b2_members)]
            db.add(MemberTeam(member=chief, team=team, role="Chief"))
            idx += 1

    db.commit()


def _assign_memberships(db: Session, teams: list[Team], members: list[Member]) -> None:
    # 提案班は全員所属
    proposal_team = next(t for t in teams if t.name == "提案")
    for m in members:
        exists = (
            db.query(MemberTeam)
            .filter_by(member_id=m.id, team_id=proposal_team.id)
            .one_or_none()
        )
        if not exists:
            db.add(MemberTeam(member=m, team=proposal_team, role="Member"))

    # 他の 3 班には 0〜2 班ランダム所属（簡易ロジック）
    other_teams = [t for t in teams if t.name != "提案"]
    for i, m in enumerate(members):
        num_extra = (i % 3)  # 0,1,2
        for j in range(num_extra):
            team = other_teams[(i + j) % len(other_teams)]
            exists = (
                db.query(MemberTeam)
                .filter_by(member_id=m.id, team_id=team.id)
                .one_or_none()
            )
            if not exists:
                db.add(MemberTeam(member=m, team=team, role="Member"))

    db.commit()


def seed_all() -> None:
    """開発用のモックデータを投入する。"""
    init_db()
    db: Session = SessionLocal()
    try:
        teams = _ensure_teams(db)
        members = _seed_members(db)
        _assign_roles(db, teams, members)
        _assign_memberships(db, teams, members)
    finally:
        db.close()


if __name__ == "__main__":
    seed_all()

