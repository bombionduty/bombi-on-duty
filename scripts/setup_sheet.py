"""
Create every tab + header row in the Google Sheet (spec section 40).

Run once after you create an empty Google Sheet and share it with the service
account:
    python -m scripts.setup_sheet

Safe to re-run: existing tabs keep their data; only missing tabs/headers are added.
"""
from __future__ import annotations

import gspread

from app.config import get_settings
from app.sheets import schema
from app.sheets.client import build_credentials


def main() -> None:
    settings = get_settings()
    gc = gspread.authorize(build_credentials())
    book = gc.open_by_key(settings.google_sheet_id)
    existing = {ws.title: ws for ws in book.worksheets()}

    for tab, headers in schema.HEADERS.items():
        if tab in existing:
            ws = existing[tab]
            current = ws.row_values(1)
            if current != headers:
                ws.update(values=[headers], range_name="A1")
                print(f"  updated headers: {tab}")
            else:
                print(f"  ok: {tab}")
        else:
            ws = book.add_worksheet(title=tab, rows=1000, cols=len(headers))
            ws.update(values=[headers], range_name="A1")
            ws.freeze(rows=1)
            print(f"  created: {tab}")

    # Remove the default 'Sheet1' if empty.
    if "Sheet1" in existing and "Sheet1" not in schema.HEADERS:
        try:
            book.del_worksheet(existing["Sheet1"])
            print("  removed default Sheet1")
        except Exception:
            pass
    print("Sheet setup complete.")


if __name__ == "__main__":
    main()
