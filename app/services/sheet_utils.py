from __future__ import annotations

from typing import Any


def dict_to_row(headers: list[str], values: dict[str, Any]) -> list[Any]:
    """ヘッダー順に values を並べた行データを作る。存在しないキーは空文字。"""
    return [values.get(h, "") for h in headers]

