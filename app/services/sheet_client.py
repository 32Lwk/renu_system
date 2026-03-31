from __future__ import annotations

from typing import Any

import csv
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from app.core.config import get_settings
from app.services.sheet_schemas import SheetName


class SheetClient:
    """Google Sheets への読み書きを行う薄いラッパー。"""

    def __init__(self) -> None:
        settings = get_settings()
        base_dir = Path(__file__).resolve().parent.parent.parent

        # 環境変数が設定されていない場合は docs/testdata のローカル CSV を使う
        if not settings.google_service_account_json_path or not settings.spreadsheet_id:
            self._mode = "file"
            self._data_dir = base_dir / "docs" / "testdata"
        else:
            self._mode = "sheets"
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_file(
                settings.google_service_account_json_path,
                scopes=scopes,
            )
            client = gspread.authorize(creds)
            self._spreadsheet = client.open_by_key(settings.spreadsheet_id)

    def worksheet(self, name: SheetName | str):
        if getattr(self, "_mode", "sheets") == "sheets":
            return self._spreadsheet.worksheet(str(name))
        raise RuntimeError("file モードでは worksheet は利用できません")

    @staticmethod
    def _sheet_key(sheet: SheetName | str) -> str:
        # Enum の str(...) は "SheetName.MEMBERS" になるため value を使う
        if isinstance(sheet, SheetName):
            return str(sheet.value)
        return str(sheet)

    def get_all_records(self, sheet: SheetName | str) -> list[dict[str, Any]]:
        if getattr(self, "_mode", "sheets") == "sheets":
            ws = self.worksheet(sheet)
            return ws.get_all_records()

        # file モード: docs/testdata の CSV を読む
        filename = f"{self._sheet_key(sheet)}.csv"
        path = self._data_dir / filename
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)

    def append_row(self, sheet: SheetName | str, values: list[Any]) -> None:
        if getattr(self, "_mode", "sheets") == "sheets":
            ws = self.worksheet(sheet)
            ws.append_row(values)
            return

        # file モード: 末尾に1行追記
        filename = f"{self._sheet_key(sheet)}.csv"
        path = self._data_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                # ヘッダー情報がない場合は values 長だけ空ヘッダーを出す
                writer.writerow([f"col{i}" for i in range(1, len(values) + 1)])
            writer.writerow(values)

    def update_row(self, sheet: SheetName | str, row_index: int, values: list[Any]) -> None:
        if getattr(self, "_mode", "sheets") == "sheets":
            ws = self.worksheet(sheet)
            ws.update(f"A{row_index}:Z{row_index}", [values])
            return

        # file モード: 指定行を書き換え（1行目はヘッダー想定）
        filename = f"{self._sheet_key(sheet)}.csv"
        path = self._data_dir / filename
        if not path.exists():
            return
        with path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        if row_index - 1 < 0 or row_index - 1 >= len(rows):
            return
        rows[row_index - 1] = values
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)

    def delete_row(self, sheet: SheetName | str, row_index: int) -> None:
        """1始まりの行番号を削除（ヘッダーが1行目）。"""
        if getattr(self, "_mode", "sheets") == "sheets":
            ws = self.worksheet(sheet)
            ws.delete_rows(row_index)
            return
        filename = f"{self._sheet_key(sheet)}.csv"
        path = self._data_dir / filename
        if not path.exists():
            return
        with path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        if row_index < 1 or row_index > len(rows):
            return
        del rows[row_index - 1]
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)


_sheet_client_singleton: SheetClient | None = None


def get_sheet_client() -> SheetClient:
    global _sheet_client_singleton
    if _sheet_client_singleton is None:
        _sheet_client_singleton = SheetClient()
    return _sheet_client_singleton

