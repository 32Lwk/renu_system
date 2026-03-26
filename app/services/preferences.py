from __future__ import annotations

from typing import Any

from app.core.config import get_settings


BUSY_PREFERENCES_SHEET = "busy_season_preferences"


def get_busy_preferences_schema() -> list[str]:
    """繁忙期希望入力用シートの列名（論理スキーマ）。"""
    return [
        "タイムスタンプ",
        "名前",
        "学年",
        "所属班",
        "希望日程",
        "希望時間帯",
        "希望役割",
        "備考",
    ]


def describe_busy_preferences_usage() -> dict[str, Any]:
    """管理者向けに、どのような列構成でシートを作るべきかを返すヘルパー。"""
    cols = get_busy_preferences_schema()
    return {
        "sheet_name": BUSY_PREFERENCES_SHEET,
        "columns": cols,
        "note": "既存の Google フォーム回答シートを利用する場合は、この列構成に近づけておくと後続ロジックを実装しやすくなります。",
    }

