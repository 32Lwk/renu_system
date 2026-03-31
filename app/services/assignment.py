from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict


@dataclass
class AssignmentInputEvent:
    id: int
    date: str
    required_members: int
    target_teams: list[str]


@dataclass
class AssignmentInputMember:
    id: int
    name: str
    teams: list[str]
    max_shifts: int


@dataclass
class AssignmentResult:
    event_id: int
    member_ids: list[int]


def greedy_assign(
    events: List[AssignmentInputEvent],
    members: List[AssignmentInputMember],
) -> List[AssignmentResult]:
    """非常にシンプルな貪欲割当アルゴリズム。

    制約:
    - メンバーは max_shifts 回まで割り当て可能
    - event.target_teams のいずれかに所属するメンバーを優先
    """
    counts: Dict[int, int] = {m.id: 0 for m in members}
    results: List[AssignmentResult] = []

    for ev in sorted(events, key=lambda e: (e.date, e.id)):
        assigned: list[int] = []
        for m in members:
            if counts[m.id] >= m.max_shifts:
                continue
            if ev.target_teams and not (set(ev.target_teams) & set(m.teams)):
                continue
            assigned.append(m.id)
            counts[m.id] += 1
            if len(assigned) >= ev.required_members:
                break
        results.append(AssignmentResult(event_id=ev.id, member_ids=assigned))
    return results

