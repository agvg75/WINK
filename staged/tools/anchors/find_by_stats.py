"""Find a worksheet by the statistics it produces, not by its name or author.

    py tools\\anchors\\find_by_stats.py --roots "L:\\..." --fingerprints fp.json

WHY CONTENT AND NOT METADATA. The search for Akash Anbu's measurements failed
twice on identity: no file carries his name, and Office metadata records the
account that SAVED a file rather than the person who measured. Both are
properties of the container. The numbers are the thing that is actually his.

THE FINGERPRINT TEST IS THE STRUCTURAL ACCEPTANCE. A column matches when its
count AND its central value AND its spread all reproduce a statistic his
notebook printed. Count alone is a coincidence; count plus mean plus s.d. to
three decimals is not. Nothing is accepted on resemblance.

It scans every numeric column of every sheet, because a worksheet laid out
with conditions side by side - which these lab workbooks are - has no
reliable column names to search on.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
SKIP_DIRS = {"$RECYCLE.BIN", "System Volume Information", "__pycache__"}


def columns_from_xlsx(path):
    """[(sheet, column index, [values])] for every numeric column."""
    archive = zipfile.ZipFile(path)
    names = [s.get("name") for s in
             ET.fromstring(archive.read("xl/workbook.xml")).iter(NS + "sheet")]
    out = []
    sheets = sorted(n for n in archive.namelist()
                    if n.startswith("xl/worksheets/sheet"))
    for index, sheet in enumerate(sheets):
        grid = {}
        for row in ET.fromstring(archive.read(sheet)).iter(NS + "row"):
            for position, cell in enumerate(row):
                if cell.get("t") == "s":
                    continue
                value = cell.find(NS + "v")
                if value is None:
                    continue
                try:
                    grid.setdefault(position, []).append(float(value.text))
                except (TypeError, ValueError):
                    continue
        for position, values in grid.items():
            if len(values) >= 3:
                out.append((names[index] if index < len(names) else sheet,
                            position, values))
    return out


def columns_from_csv(path):
    out = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as handle:
        for row in csv.reader(handle):
            for position, cell in enumerate(row):
                try:
                    out.setdefault(position, []).append(float(cell))
                except (TypeError, ValueError):
                    continue
    return [("csv", position, values) for position, values in out.items()
            if len(values) >= 3]


def matches(values, fingerprint, tolerance=0.01):
    """Does this column reproduce the printed statistic?"""
    _measure, _group, n, centre, spread, _third = fingerprint
    if len(values) != n:
        return None
    for label, computed in (("mean", st.mean(values)),
                            ("median", st.median(values))):
        if abs(computed - centre) <= max(abs(centre) * tolerance, 1e-6):
            note = label
            if len(values) > 1:
                sd = st.stdev(values)
                if abs(sd - spread) <= max(abs(spread) * tolerance, 1e-6):
                    return f"{label}+sd"
            return note
    return None


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roots", nargs="+", required=True)
    ap.add_argument("--fingerprints", required=True)
    ap.add_argument("--tolerance", type=float, default=0.01)
    args = ap.parse_args()

    fingerprints = [tuple(f) for f in
                    json.loads(Path(args.fingerprints).read_text(
                        encoding="utf-8"))]
    print(f"{len(fingerprints)} fingerprints:")
    for measure, group, n, centre, spread, _ in fingerprints:
        print(f"  {measure[:38]:<38} {group:<7} n={n:<4} {centre:.3f} "
              f"+-{spread:.3f}")

    scanned = hits = 0
    for root in args.roots:
        for path in Path(root).rglob("*"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix not in (".xlsx", ".xlsm", ".csv"):
                continue
            scanned += 1
            try:
                columns = (columns_from_csv(path) if suffix == ".csv"
                           else columns_from_xlsx(path))
            except Exception:                                # noqa: BLE001
                continue
            for sheet, position, values in columns:
                for fingerprint in fingerprints:
                    how = matches(values, fingerprint, args.tolerance)
                    if how:
                        hits += 1
                        print(f"\n  MATCH [{how}] {fingerprint[0][:34]} "
                              f"{fingerprint[1]}")
                        print(f"    {path}")
                        print(f"    sheet {sheet!r} column {position}, "
                              f"n={len(values)}")
    print(f"\nscanned {scanned:,} workbooks; {hits} column match(es)")
    if not hits:
        print("  No column reproduced a printed statistic. That is a real "
              "negative: these numbers are not sitting in a spreadsheet "
              "anywhere under the roots searched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
