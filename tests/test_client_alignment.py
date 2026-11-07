"""SheetTable must order writes by the LIVE sheet's physical header row, not the
schema list — otherwise a column appended at the end of an existing sheet (while
the schema lists it mid-array) misaligns every cell after it. Regression test for
the Nov-2026 'blank status / hidden admin button' corruption."""
import gspread

from app.sheets import client, schema


class FakeWS:
    def __init__(self, physical_headers, records=None):
        self._headers = list(physical_headers)
        self._records = records or []
        self.appended = []
        self.updated_cells = []

    def row_values(self, n):
        return list(self._headers)

    def update(self, values=None, range_name=None):
        pass

    def append_row(self, vals, value_input_option=None):
        self.appended.append(vals)

    def append_rows(self, matrix, value_input_option=None):
        self.appended.extend(matrix)

    def update_cells(self, cells, value_input_option=None):
        self.updated_cells.extend(cells)

    def get_all_records(self, expected_headers=None):
        return list(self._records)


def _table(physical_headers, schema_headers, records=None):
    t = client.SheetTable.__new__(client.SheetTable)
    t.book = None
    t.tab_name = schema.TASKS
    t.headers = schema_headers           # schema order (new col mid-array)
    t._phys = list(physical_headers)     # live sheet order (new col at end)
    t._ws = FakeWS(physical_headers, records)
    t._cache = None
    t._cache_at = 0.0
    import threading
    t._lock = threading.RLock()
    return t


# Schema inserts "New Col" in the MIDDLE; the live sheet has it at the END.
SCHEMA = ["ID", "A", "New Col", "B", "Status"]
PHYSICAL = ["ID", "A", "B", "Status", "New Col"]


def test_append_orders_by_physical_header_row():
    t = _table(PHYSICAL, SCHEMA)
    t.append({"ID": "x1", "A": "a", "New Col": "n", "B": "b", "Status": "Pending"})
    # Values must line up with the PHYSICAL columns, so "Status" lands under Status.
    assert t._ws.appended[0] == ["x1", "a", "b", "Pending", "n"]


def test_update_writes_to_physical_column_index():
    rec = {"ID": "x1", "A": "a", "B": "b", "Status": "", "New Col": ""}
    t = _table(PHYSICAL, SCHEMA, records=[rec])
    t.update("ID", "x1", {"Status": "Submitted On Time"})
    # Physical index of "Status" is 4 (1-based), NOT the schema index 5.
    cell = t._ws.updated_cells[0]
    assert cell.col == PHYSICAL.index("Status") + 1 == 4
    assert cell.value == "Submitted On Time"
