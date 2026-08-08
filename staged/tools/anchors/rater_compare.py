"""Compare two measurement generations of the same myocytes.

    py tools\\anchors\\rater_compare.py --a old.xlsx --b new.xlsx

WHAT IT IS FOR. The anchor's images were measured more than once, by more than
one person. Those repeats are the only direct evidence the lab has of how much
a human measurement of a myocyte moves - and that number is the floor any
automated tolerance has to respect. An automated method agreeing with a human
to better than humans agree with each other is not more accurate; it is
measuring something else.

TWO DIFFERENT QUANTITIES, AND THEY MUST NOT BE POOLED:

    INTRA-RATER   one person, two passes. Stability.
    INTER-RATER   two people. Agreement.

Intra-rater is almost always the tighter of the two, so mixing them produces a
tolerance that is too tight for real use and too loose to detect a drifting
rater.

THE JOIN IS THE HARD PART, AND IT IS REPORTED RATHER THAN ASSUMED. These
worksheets key rows by `.lif` filename and series, not by cell. Where a
generation numbers its myocytes, cells can be paired directly; where it does
not, only the per-series DISTRIBUTIONS can be compared. This tool says which
it did, per series, because a difference computed from a wrong pairing looks
exactly like a difference in measurement.
"""
from __future__ import annotations

import argparse
import re
import statistics as st
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def read_sheets(path):
    """{sheet name: [row, ...]} with shared strings resolved."""
    archive = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in archive.namelist():
        for item in ET.fromstring(
                archive.read("xl/sharedStrings.xml")).findall(NS + "si"):
            shared.append("".join(t.text or "" for t in item.iter(NS + "t")))
    names = [s.get("name") for s in
             ET.fromstring(archive.read("xl/workbook.xml")).iter(NS + "sheet")]
    out = {}
    sheets = sorted(n for n in archive.namelist()
                    if n.startswith("xl/worksheets/sheet"))
    for index, sheet in enumerate(sheets):
        rows = []
        for row in ET.fromstring(archive.read(sheet)).iter(NS + "row"):
            values = []
            for cell in row:
                value = cell.find(NS + "v")
                if value is None:
                    values.append("")
                elif cell.get("t") == "s":
                    values.append(shared[int(value.text)])
                else:
                    values.append(value.text or "")
            rows.append(values)
        out[names[index] if index < len(names) else sheet] = rows
    return out


def harvest(path):
    """[(lif, series, area)] from any sheet shaped like these worksheets.

    Deliberately structural rather than column-name driven: the two
    generations name the same column differently ("Myocyte area (um^2)" and
    "Area (um^2)"), and one lays three conditions side by side in one row.
    A row contributes wherever a .lif name is followed by a series label and
    a number.
    """
    found = []
    for sheet, rows in read_sheets(path).items():
        for row in rows:
            for i, cell in enumerate(row):
                if not isinstance(cell, str) or not cell.lower().endswith(".lif"):
                    continue
                series = row[i + 1] if i + 1 < len(row) else ""
                if not series or not re.search(r"series", str(series), re.I):
                    continue
                for j in range(i + 2, min(i + 5, len(row))):
                    try:
                        area = float(row[j])
                    except (TypeError, ValueError):
                        continue
                    if 50.0 < area < 10000.0:      # a myocyte area in um^2
                        found.append((cell.strip(), str(series).strip(), area))
                        break
    return found


def group(rows):
    out = {}
    for lif, series, area in rows:
        out.setdefault((lif.lower(), series.lower()), []).append(area)
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True, help="earlier generation")
    ap.add_argument("--b", required=True, help="later generation")
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    args = ap.parse_args()

    a, b = group(harvest(args.a)), group(harvest(args.b))
    print(f"{args.label_a}: {sum(len(v) for v in a.values()):,} measurements "
          f"in {len(a)} series")
    print(f"{args.label_b}: {sum(len(v) for v in b.values()):,} measurements "
          f"in {len(b)} series")

    shared = sorted(set(a) & set(b))
    print(f"\nseries measured in BOTH generations: {len(shared)}")
    if not shared:
        print("  nothing to compare - the generations cover different series")
        return 1

    same_count, diffs, count_gaps = 0, [], []
    for key in shared:
        va, vb = sorted(a[key]), sorted(b[key])
        if len(va) == len(vb):
            same_count += 1
            diffs.extend(y - x for x, y in zip(va, vb))
        else:
            count_gaps.append((key, len(va), len(vb)))

    print(f"  same myocyte COUNT in both: {same_count}")
    print(f"  differing counts:           {len(count_gaps)}")
    for key, na, nb in count_gaps[:8]:
        print(f"     {key[0][:44]:<44} {key[1][:14]:<14} "
              f"{args.label_a}={na} {args.label_b}={nb}")

    if not diffs:
        print("\nno series had matching counts, so no per-cell comparison is "
              "possible without a myocyte identifier.")
        return 0

    absolute = [abs(d) for d in diffs]
    mean_a = st.mean([x for key in shared for x in a[key]])
    print(f"\nPAIRED BY RANK within series where counts match "
          f"({len(diffs)} cells).")
    print("  RANK PAIRING IS AN ASSUMPTION: it pairs the smallest with the "
          "smallest. It is right only if both generations measured the same "
          "cells, and it hides a swap.")
    print(f"  mean signed difference   {st.mean(diffs):+9.1f} um^2   "
          f"({st.mean(diffs) / mean_a * 100:+.1f}% of mean area)")
    print(f"  mean |difference|        {st.mean(absolute):9.1f} um^2   "
          f"({st.mean(absolute) / mean_a * 100:.1f}%)")
    if len(diffs) > 1:
        print(f"  s.d. of differences      {st.stdev(diffs):9.1f} um^2")
    ordered = sorted(absolute)
    for label, q in (("median", 0.5), ("p90", 0.9), ("p95", 0.95)):
        k = int(q * (len(ordered) - 1))
        print(f"  {label} |difference|     {ordered[k]:9.1f} um^2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
