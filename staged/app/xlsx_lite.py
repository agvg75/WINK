"""Read .xlsx with the standard library. No openpyxl, because there isn't one.

WHY THIS EXISTS. The lab runtime ships pandas and numpy but not openpyxl, and
`pandas.read_excel` needs openpyxl for .xlsx. A tool that reads a workbook
would therefore fail on every machine it was meant to run on, and telling a
student to pip install something into a locked-down runtime is not a fix.

An .xlsx is a zip of XML, so reading one needs nothing that is not already in
Python.

DELIBERATELY LIMITED. This reads cell VALUES from a saved workbook: shared
strings, inline strings, numbers, booleans, and the cached results of
formulas. It does not evaluate formulas, read styles, or handle dates as
anything other than the serial number Excel stores - a date column comes back
as a number, and the caller must know that. It is a reader for authority
tables that people maintain by hand, not a spreadsheet engine.
"""
from __future__ import annotations

import zipfile
from xml.etree import ElementTree as ET

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"m": MAIN, "r": RELS}


class XlsxError(ValueError):
    """Refusals that name what was wrong with the workbook."""


def _column_index(ref):
    """'AB12' -> 27. Cell references skip empty cells, so this is required."""
    letters = "".join(ch for ch in ref if ch.isalpha())
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch.upper()) - 64)
    return max(n - 1, 0)


def _shared_strings(archive):
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    # A string can be split into runs by formatting; the text is the
    # concatenation, and taking only the first run silently truncates.
    return ["".join(t.text or "" for t in si.iter(f"{{{MAIN}}}t"))
            for si in root.findall("m:si", NS)]


def _sheet_targets(archive):
    rels = {}
    root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for rel in root:
        rels[rel.get("Id")] = rel.get("Target").lstrip("/")
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    out = {}
    for sheet in workbook.find("m:sheets", NS):
        target = rels.get(sheet.get(f"{{{RELS}}}id"), "")
        if not target.startswith("xl/"):
            target = "xl/" + target
        out[sheet.get("name")] = target
    return out


def _cell_text(cell, shared):
    kind = cell.get("t")
    if kind == "inlineStr":
        node = cell.find("m:is", NS)
        return "".join(t.text or "" for t in node.iter(f"{{{MAIN}}}t")) \
            if node is not None else ""
    value = cell.find("m:v", NS)
    if value is None or value.text is None:
        return ""
    if kind == "s":
        try:
            return shared[int(value.text)]
        except (ValueError, IndexError):
            return ""
    if kind == "b":
        return "TRUE" if value.text == "1" else "FALSE"
    return value.text


def sheet_names(path):
    with zipfile.ZipFile(path) as archive:
        return list(_sheet_targets(archive))


def read_sheet(path, name):
    """A sheet as a list of row lists, ragged rows padded to equal width."""
    with zipfile.ZipFile(path) as archive:
        targets = _sheet_targets(archive)
        if name not in targets:
            raise XlsxError(
                f"{path} has no sheet named {name!r}. It has: "
                f"{sorted(targets)}.")
        shared = _shared_strings(archive)
        worksheet = ET.fromstring(archive.read(targets[name]))
        rows = []
        for row in worksheet.findall(".//m:row", NS):
            cells = {}
            for cell in row.findall("m:c", NS):
                cells[_column_index(cell.get("r", "A1"))] = _cell_text(
                    cell, shared)
            rows.append(cells)
    width = max((max(c) + 1 for c in rows if c), default=0)
    return [[str(c.get(i, "")).strip() for i in range(width)] for c in rows]


def read_table(path, name, *, header_row=0):
    """A sheet as dicts keyed by its header row, blank rows dropped."""
    rows = read_sheet(path, name)
    if len(rows) <= header_row:
        raise XlsxError(
            f"Sheet {name!r} in {path} has no header row at index "
            f"{header_row}; it has {len(rows)} rows.")
    header = [h or f"column_{i}" for i, h in enumerate(rows[header_row])]
    out = []
    for row in rows[header_row + 1:]:
        if not any(cell for cell in row):
            continue
        out.append(dict(zip(header, row)))
    return out
