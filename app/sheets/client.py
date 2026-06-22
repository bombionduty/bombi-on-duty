"""
Google Sheets + Drive low-level client and a generic table wrapper.

`SheetTable` gives the repository layer a tiny, consistent API over a single
worksheet:
    table.all()                       -> list[dict]  (one dict per row, by header)
    table.append(row_dict)            -> appends a row in correct column order
    table.find(col, value)            -> first matching dict (or None)
    table.find_all(col, value)        -> list of matching dicts
    table.update(col, value, changes) -> update first matching row's cells

We cache reads for a few seconds to avoid hammering the Google API (which has
quota limits). Any write invalidates that table's cache.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

import gspread
from google.oauth2.service_account import Credentials

from app.config import get_settings
from app.sheets import schema

log = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_CACHE_TTL = 5.0  # seconds


def build_credentials() -> Credentials:
    settings = get_settings()
    info = settings.service_account_info()
    return Credentials.from_service_account_info(info, scopes=_SCOPES)


class SheetTable:
    def __init__(self, book: "Workbook", tab_name: str):
        self.book = book
        self.tab_name = tab_name
        self.headers = schema.HEADERS[tab_name]
        self._ws = None
        self._cache: list[dict] | None = None
        self._cache_at = 0.0
        self._lock = threading.RLock()

    @property
    def ws(self):
        if self._ws is None:
            self._ws = self.book.spreadsheet.worksheet(self.tab_name)
        return self._ws

    def _invalidate(self) -> None:
        self._cache = None

    def all(self, fresh: bool = False) -> list[dict]:
        with self._lock:
            now = time.time()
            if (
                not fresh
                and self._cache is not None
                and (now - self._cache_at) < _CACHE_TTL
            ):
                return list(self._cache)
            records = self.ws.get_all_records(expected_headers=self.headers)
            # get_all_records returns dicts keyed by header.
            self._cache = [dict(r) for r in records]
            self._cache_at = now
            return list(self._cache)

    def find(self, col: str, value: Any) -> dict | None:
        sval = str(value)
        for row in self.all():
            if str(row.get(col, "")) == sval:
                return row
        return None

    def find_all(self, col: str, value: Any) -> list[dict]:
        sval = str(value)
        return [r for r in self.all() if str(r.get(col, "")) == sval]

    def filter(self, predicate: Callable[[dict], bool]) -> list[dict]:
        return [r for r in self.all() if predicate(r)]

    def append(self, row: dict) -> dict:
        with self._lock:
            ordered = [self._cell(row.get(h, "")) for h in self.headers]
            self.ws.append_row(ordered, value_input_option="USER_ENTERED")
            self._invalidate()
            return row

    def append_many(self, rows: list[dict]) -> None:
        if not rows:
            return
        with self._lock:
            matrix = [[self._cell(r.get(h, "")) for h in self.headers] for r in rows]
            self.ws.append_rows(matrix, value_input_option="USER_ENTERED")
            self._invalidate()

    def update(self, col: str, value: Any, changes: dict) -> bool:
        """Update the FIRST row where row[col] == value. Returns True if found."""
        with self._lock:
            sval = str(value)
            records = self.ws.get_all_records(expected_headers=self.headers)
            for idx, row in enumerate(records):
                if str(row.get(col, "")) == sval:
                    sheet_row = idx + 2  # +1 header, +1 to 1-based
                    self._apply_changes(sheet_row, changes)
                    self._invalidate()
                    return True
            return False

    def _apply_changes(self, sheet_row: int, changes: dict) -> None:
        cells = []
        for key, val in changes.items():
            if key not in self.headers:
                raise KeyError(f"{key!r} not a column of {self.tab_name}")
            col_idx = self.headers.index(key) + 1
            cells.append(gspread.Cell(sheet_row, col_idx, self._cell(val)))
        if cells:
            self.ws.update_cells(cells, value_input_option="USER_ENTERED")

    @staticmethod
    def _cell(value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        return value


class Workbook:
    """Holds the opened spreadsheet and caches SheetTable wrappers."""

    def __init__(self):
        settings = get_settings()
        self.gc = gspread.authorize(build_credentials())
        self.spreadsheet = self.gc.open_by_key(settings.google_sheet_id)
        self._tables: dict[str, SheetTable] = {}

    def table(self, tab_name: str) -> SheetTable:
        if tab_name not in self._tables:
            self._tables[tab_name] = SheetTable(self, tab_name)
        return self._tables[tab_name]


# ---- module-level singleton (lazy) ----
_workbook: Workbook | None = None


def get_workbook() -> Workbook:
    global _workbook
    if _workbook is None:
        _workbook = Workbook()
    return _workbook


def table(tab_name: str) -> SheetTable:
    return get_workbook().table(tab_name)
