#!/usr/bin/env python3
"""
ローカル file モード用に docs/testdata のイベント・繁忙期希望（募集）を大量追加する。
既存行は保持し、末尾に追記する。

追加する ev_bulk イベントの表示名（name）は「MMDD_チーム名」（例: 0401_すまい）。

使い方（リポジトリルートで）:
  python3 scripts/generate_bulk_testdata.py
  python3 scripts/generate_bulk_testdata.py --events 300 --prefs 800 --atts 500
"""
from __future__ import annotations

import argparse
import csv
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def bulk_event_display_name(mmdd: str, team: str, n: int) -> str:
    """負荷テスト用イベントの表示名: MMDD_チーム名（例: 0401_すまい）。重複時は _2 などで一意化。"""
    base = f"{mmdd}_{team}"
    return base if n <= 1 else f"{base}_{n}"


def _max_suffix(path: Path, prefix: str) -> int:
    """先頭列が {prefix}_{番号}（例: ev_bulk_00500）の行の最大番号を返す。"""
    max_n = 0
    head = prefix + "_"
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.startswith(head):
                continue
            cell = line.split(",", 1)[0]
            try:
                max_n = max(max_n, int(cell.split("_")[-1]))
            except ValueError:
                pass
    return max_n


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=250, help="追加するイベント件数")
    parser.add_argument("--prefs", type=int, default=600, help="追加する繁忙期希望件数")
    parser.add_argument("--atts", type=int, default=400, help="追加する出勤件数（0でスキップ）")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    random.seed(args.seed)

    root = Path(__file__).resolve().parent.parent
    data_dir = root / "docs" / "testdata"
    members_path = data_dir / "members.csv"
    events_path = data_dir / "events.csv"
    prefs_path = data_dir / "busy_preferences.csv"
    atts_path = data_dir / "attendances.csv"

    teams = ["すまい", "PC", "提案", "キャリア"]
    slots = [("10:00", "14:00"), ("14:00", "18:00"), ("09:00", "13:00")]

    with members_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        members = list(reader)
    member_ids = [m["member_id"] for m in members if m.get("member_id")]
    member_by_id = {m["member_id"]: m.get("full_name", "") for m in members if m.get("member_id")}
    if not member_ids:
        raise SystemExit("members.csv に member_id がありません")

    start_day = date(2026, 4, 1)
    busy_cycle = [False, True, True, True, False, True]

    max_ev = _max_suffix(events_path, "ev_bulk")
    next_ev_num = max_ev + 1

    new_events: list[dict[str, str]] = []
    name_counts: dict[tuple[str, str], int] = {}
    for i in range(args.events):
        g = (next_ev_num - 1) + i
        day = start_day + timedelta(days=g // len(slots))
        st, en = slots[g % len(slots)]
        eid = f"ev_bulk_{next_ev_num + i:05d}"
        team = teams[g % len(teams)]
        busy = busy_cycle[g % len(busy_cycle)]
        mmdd = day.strftime("%m%d")
        key = (mmdd, team)
        name_counts[key] = name_counts.get(key, 0) + 1
        name = bulk_event_display_name(mmdd, team, name_counts[key])
        new_events.append(
            {
                "event_id": eid,
                "date": day.isoformat(),
                "start_time": st,
                "end_time": en,
                "name": name,
                "required_members": str(3 + (g % 6)),
                "target_teams": team,
                "is_busy_season": "true" if busy else "false",
                "confirmed": "false",
                "updated_at": _now_iso(),
            }
        )

    busy_event_ids = [e["event_id"] for e in new_events if e["is_busy_season"].lower() == "true"]
    if not busy_event_ids and new_events:
        busy_event_ids = [e["event_id"] for e in new_events[: min(50, len(new_events))]]

    new_prefs: list[dict[str, str]] = []
    roles_pref = ["受付", "誘導", "Member", "スタッフ", ""]
    pref_pool = busy_event_ids if busy_event_ids else [e["event_id"] for e in new_events]
    if args.prefs > 0 and not pref_pool:
        raise SystemExit("追加するイベントがないため busy_preferences を生成できません（--events 1 以上）。")
    for _ in range(args.prefs):
        mid = random.choice(member_ids)
        eid = random.choice(pref_pool)
        pr = (random.randint(1, 5), random.randint(1, 8))
        new_prefs.append(
            {
                "member_id": mid,
                "member_name": member_by_id.get(mid, ""),
                "event_id": eid,
                "preferred_role": random.choice(roles_pref),
                "priority": str(pr[0]),
                "max_shifts": str(pr[1]),
                "note": "",
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
        )

    # 出勤: 新規イベントに対してランダム割当
    new_atts: list[dict[str, str]] = []
    next_att = _max_suffix(atts_path, "att_bulk") + 1
    if args.atts > 0 and new_events:
        pool = new_events
        while len(new_atts) < args.atts:
            ev = random.choice(pool)
            mid = random.choice(member_ids)
            new_atts.append(
                {
                    "attendance_id": f"att_bulk_{next_att:06d}",
                    "event_id": ev["event_id"],
                    "member_id": mid,
                    "role": random.choice(["Member", "Member", "Leader"]),
                    "status": "planned",
                    "note": "",
                    "updated_at": _now_iso(),
                }
            )
            next_att += 1

    # 追記
    if new_events:
        with events_path.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(new_events[0].keys()))
            for row in new_events:
                w.writerow(row)

    if new_prefs:
        with prefs_path.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(new_prefs[0].keys()))
            for row in new_prefs:
                w.writerow(row)

    if new_atts:
        with atts_path.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(new_atts[0].keys()))
            for row in new_atts:
                w.writerow(row)

    print(
        f"追加完了: events +{len(new_events)}, busy_preferences +{len(new_prefs)}, attendances +{len(new_atts)}"
    )
    print(f"データディレクトリ: {data_dir}")


if __name__ == "__main__":
    main()
