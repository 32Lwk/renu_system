from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable

from app.services.sheet_schemas import MembersColumns


class MemberRole(IntEnum):
    MEMBER = 0
    CHIEF = 1
    SUBLEADER = 2
    LEADER = 3


@dataclass
class TeamRole:
    team: str
    role: MemberRole


def _normalize_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [x.strip() for x in str(value).split(",") if x.strip()]


def parse_team_roles(row: dict) -> list[TeamRole]:
    """members 行から (team, role) の対応を推定する。

    - teams: "すまい,PC,提案"
    - roles: "Leader,Chief" など
    """
    teams = _normalize_list(row.get(MembersColumns.TEAMS, ""))
    roles_raw = _normalize_list(row.get(MembersColumns.ROLES, ""))
    if not teams:
        return []

    def to_role(name: str) -> MemberRole:
        name = name.lower()
        if "leader" in name and "sub" in name:
            return MemberRole.SUBLEADER
        if name == "leader":
            return MemberRole.LEADER
        if "chief" in name:
            return MemberRole.CHIEF
        return MemberRole.MEMBER

    role_list = [to_role(r) for r in roles_raw] or [MemberRole.MEMBER]

    team_roles: list[TeamRole] = []
    if len(role_list) == 1 and len(teams) >= 1:
        # 単一ロールをすべてのチームに適用
        r = role_list[0]
        for t in teams:
            team_roles.append(TeamRole(team=t, role=r))
    else:
        # インデックス対応、足りなければ MEMBER
        for idx, t in enumerate(teams):
            if idx < len(role_list):
                r = role_list[idx]
            else:
                r = MemberRole.MEMBER
            team_roles.append(TeamRole(team=t, role=r))
    return team_roles


def get_overall_role(team_roles: Iterable[TeamRole]) -> MemberRole:
    max_role = MemberRole.MEMBER
    for tr in team_roles:
        if tr.role > max_role:
            max_role = tr.role
    return max_role


def managed_teams_subleader_plus(team_roles: list[TeamRole]) -> set[str]:
    """SubLeader / Leader として管理できるチーム名。"""
    return {tr.team for tr in team_roles if tr.role >= MemberRole.SUBLEADER}


def leader_teams(team_roles: list[TeamRole]) -> set[str]:
    """Leader として責任を持つチーム。"""
    return {tr.team for tr in team_roles if tr.role == MemberRole.LEADER}

