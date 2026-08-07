"""Read filenames across the drive and pull labels out of them.

    python parse_filenames.py --inventory L_drive_inventory.csv --out x.csv \
                              --max-seconds 120

Stops cleanly at --max-seconds and reports how far it got, so a run that turns
out to be slower than expected returns partial results rather than nothing.

TWO THINGS THIS IS AFTER, and the second was nearly missed:

1. The lab vocabulary - strains, isoform suffixes, RNAi controls - which the
   feasibility probe found in filenames far more than in folder names.

2. ACQUISITION TIMESTAMPS. The year column is only 33% covered from folder
   names, and cameras stamp the acquisition time into the filename:
   `fc2_save_2021-04-19-143320-8995.tif`. That is a better date than the
   file's mtime, which is what the inventory carries - an mtime records when
   the file was last WRITTEN, so copying an archive rewrites every one of
   them while the filename keeps the day the animal was actually filmed.

   Where the two disagree, the filename is the acquisition date and the mtime
   is the date of some later copy. This reports the disagreement rather than
   picking silently.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import propose_labels as pl   # noqa: E402

# Acquisition stamps as cameras write them. Ordered most specific first.
STAMP_RES = [
    re.compile(r"(20\d\d)[-_](\d{2})[-_](\d{2})"),      # 2021-04-19
    re.compile(r"(20\d\d)(\d{2})(\d{2})"),              # 20210419
]
YEAR_RE = re.compile(r"(?<!\d)(20[0-2]\d)(?!\d)")


def stamp_year(name):
    """The acquisition year a filename carries, or None."""
    for pattern in STAMP_RES:
        match = pattern.search(name)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            if 2000 <= year <= 2026 and 1 <= month <= 12:
                return year
    match = YEAR_RE.search(name)
    return int(match.group(1)) if match else None


def vocabulary(name):
    stem = os.path.splitext(name)[0]
    found = {}
    for word in re.split(r"[^A-Za-z0-9-]+", stem):
        if not word:
            continue
        key = pl.token_key(word)
        if not key:
            continue
        if key in pl.KNOWN_STRAINS:
            found.setdefault("strain", pl.KNOWN_STRAINS[key]["strain"])
        elif pl.LAB_STRAIN_RE.match(word):
            found.setdefault("strain", word.upper())
        elif pl.VECTOR_RE.match(word):
            found.setdefault("condition", "L4440 (empty RNAi vector, control)")
        elif pl.SISTERS_RE.match(word):
            found.setdefault("condition", "untransformed sisters (control)")
        elif key in pl.CONTROLS:
            found.setdefault("condition", pl.CONTROLS[key][0])
        elif pl.GENE_RE.match(word):
            match = pl.GENE_RE.match(word)
            base, suffix = match.group(1).lower(), (match.group(2) or "")
            _, note = pl.describe_isoforms(base, suffix)
            found.setdefault("condition", f"{base}{suffix.upper()}")
            if suffix:
                found.setdefault("isoform_note", note)
        elif key in pl.GIVEN_NAMES:
            people = pl.GIVEN_NAMES[key]
            found.setdefault("person", " | ".join(sorted(
                f"{p['surname']} {p['initials']}".strip() for p in people)))
    return found


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--authority")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-seconds", type=float, default=120.0)
    args = ap.parse_args()

    pl.load_strains()
    if args.authority and Path(args.authority).exists():
        pl.load_authority(args.authority)

    with open(args.inventory, newline="", encoding="utf-8-sig") as handle:
        rows = [r for r in csv.DictReader(handle) if r.get("path")]

    started = time.time()
    out_rows = []
    files_seen = 0
    folders_done = 0
    stopped_early = False
    agree = disagree = no_mtime = 0
    fields = Counter()

    for row in rows:
        if time.time() - started > args.max_seconds:
            stopped_early = True
            break
        try:
            names = os.listdir(row["path"])
        except OSError:
            continue
        folders_done += 1
        found = {}
        years = Counter()
        for name in names:
            files_seen += 1
            year = stamp_year(name)
            if year:
                years[year] += 1
            for field, value in vocabulary(name).items():
                found.setdefault(field, value)
        if not found and not years:
            continue
        for field in found:
            fields[field] += 1
        stamp = max(years, key=years.get) if years else None
        # The two survey CSVs carry different date columns: LABEL_ME has
        # `oldest` and `newest`, the inventory only `newest`. Reading one name
        # blindly makes the comparison silently do nothing, which is what
        # happened on the first run - 655 stamped folders and zero compared.
        mtime_year = (row.get("oldest") or row.get("newest") or "")[:4]
        if stamp and mtime_year.isdigit():
            if int(mtime_year) == stamp:
                agree += 1
            else:
                disagree += 1
        elif stamp:
            no_mtime += 1
        out_rows.append({
            "path": row["path"],
            "n_files": len(names),
            "stamp_year": stamp or "",
            "stamp_year_files": years.get(stamp, 0) if stamp else 0,
            "mtime_year": mtime_year,
            "date_source_agrees": ("" if not stamp or not mtime_year.isdigit()
                                   else str(int(mtime_year) == stamp)),
            "strain": found.get("strain", ""),
            "condition": found.get("condition", ""),
            "person": found.get("person", ""),
            "isoform_note": found.get("isoform_note", ""),
        })

    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "path", "n_files", "stamp_year", "stamp_year_files", "mtime_year",
            "date_source_agrees", "strain", "condition", "person",
            "isoform_note"])
        writer.writeheader()
        writer.writerows(out_rows)

    elapsed = time.time() - started
    print(f"{'folders read':26} {folders_done:,} of {len(rows):,}"
          + ("   STOPPED AT THE TIME CAP" if stopped_early else "   (complete)"))
    print(f"{'files read':26} {files_seen:,}")
    print(f"{'elapsed':26} {elapsed:.1f} s")
    print(f"{'rate':26} {files_seen / max(elapsed, 1e-9):,.0f} files/s")
    print()
    print(f"{'folders with a label':26} {len(out_rows):,}")
    for field, count in fields.most_common():
        print(f"    {field:22} {count:,} folders")
    print()
    stamped = agree + disagree + no_mtime
    print(f"ACQUISITION DATE from filename stamps: {stamped:,} folders")
    if agree + disagree:
        print(f"    agrees with the file mtime     {agree:,}")
        print(f"    DISAGREES with the mtime       {disagree:,}"
              f"   ({disagree / (agree + disagree) * 100:.0f}%)")
        print("    where they disagree the filename is the acquisition date")
        print("    and the mtime is when the file was last copied")
    print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
