"""What confocal data exists, what shape it is, and can it be measured.

    py confocal_census.py --files confocal_files.csv --out census.csv

Grant plan item 0.2. The question §5.2 asks is not "how many files" - the
survey answered that months ago - but how many are HEAD STACKS, across which
strains and years, and whether they carry the calibration a measurement needs.

READS HEADERS ONLY, NEVER PIXELS. A .lif states its own dimensions, channel
count, bit depth, frame interval and voxel size in an XML block at the front
of the file. Measured at 0.15 s per file, flat with file size, because the
header sits before the data and the data is never touched. The largest file
in the archive and the smallest cost the same to census.

WHAT THIS CANNOT DO, stated plainly because the answer looks authoritative
otherwise: nothing in a .lif header says the stack is of a HEAD. Anatomy is
not metadata. This reports the stacks and the context their path carries -
strain, person, year, project - and a human decides which are heads. A column
called `is_head_stack` would be a fabrication, so there isn't one.

Non-Leica formats (.czi, .nd2, .lsm) are counted and listed but not opened;
no reader for them exists in this codebase, and guessing at their headers
would be worse than reporting them as unread.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2] / "app"))
sys.path.insert(0, str(HERE.parents[1] / "drive_audit"))

import cell_calcium_lif as lif   # noqa: E402
import propose_labels as pl      # noqa: E402

YEAR_RE = re.compile(r"(?<!\d)(20[0-2]\d)(?!\d)")

# This lab writes YYMMDD on the front of a confocal filename:
# 230222_AVG60_dys-1_a-g_RNAi.lif. A four-digit year regex reads none of it,
# which is how the first run found a year for 91 of 5,206 series.
YYMMDD_RE = re.compile(r"(?<!\d)([0-2]\d)([01]\d)([0-3]\d)(?!\d)")

# Leica stores processed copies and analysis outputs as sibling series inside
# the same file. Counting them as acquisitions inflates the census: a
# LIGHTNING-deconvolved stack is the SAME recording as its parent, and a FLIM
# decay map is not a recording at all.
LIGHTNING_RE = re.compile(r"_lng$", re.I)
FLIM_RE = re.compile(r"^(flim|fast flim|intensity|standard deviation|"
                     r"pattern matching|photons|chi|fit )", re.I)


def derivation_of(name):
    """Whether a series is an acquisition or something computed from one."""
    if LIGHTNING_RE.search(name or ""):
        return "LIGHTNING deconvolution of the parent series"
    if FLIM_RE.match((name or "").strip()):
        return "FLIM analysis product, not an acquisition"
    return ""


def year_of(text):
    """The acquisition year a path segment carries, four-digit or YYMMDD."""
    match = YEAR_RE.search(text)
    if match:
        return int(match.group(1))
    match = YYMMDD_RE.search(text)
    if match:
        year, month, day = (int(g) for g in match.groups())
        if 1 <= month <= 12 and 1 <= day <= 31:
            return 2000 + year
    return None


def shape_of(series):
    """The kind of acquisition a series is, from its dimensions alone."""
    z, t = series["n_z"], series["n_t"]
    if z > 1 and t > 1:
        return "z-stack timelapse"
    if z > 1:
        return "z-stack"
    if t > 1:
        return "timelapse"
    return "single plane"


def context_of(path):
    """Strain, person and year the PATH carries, via the drive-audit lexicon.

    The same vocabulary the folder audit uses, so a strain found here means
    the same thing it means there and the two can be joined.
    """
    found = {}
    years = set()
    for segment in pl.path_segments(path) + [os.path.basename(path)]:
        for word in re.split(r"[^A-Za-z0-9-]+", segment):
            if not word:
                continue
            key = pl.token_key(word)
            if not key:
                continue
            if key in pl.KNOWN_STRAINS:
                found.setdefault("strain", pl.KNOWN_STRAINS[key]["strain"])
            elif pl.LAB_STRAIN_RE.match(word):
                found.setdefault("strain", word.upper())
            elif key in pl.GIVEN_NAMES:
                people = pl.GIVEN_NAMES[key]
                found.setdefault("person", " | ".join(sorted(
                    f"{p['surname']} {p['initials']}".strip()
                    for p in people)))
        year = year_of(segment)
        if year and 2000 <= year <= 2026:
            years.add(year)
    if years:
        found["year"] = str(min(years))
    return found


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--files", required=True, nargs="+", metavar="LABEL=CSV",
                    help="one or more sweeps, as label=path. The label names "
                         "the storage the files were found on and is kept "
                         "through to the output, because a file on the scope "
                         "computer and a file on the lab drive are not the "
                         "same fact even when they are the same bytes.")
    ap.add_argument("--authority", help="lab_name_authority.xlsx")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-seconds", type=float, default=600.0)
    args = ap.parse_args()

    pl.load_strains()
    if args.authority:
        # NOT a silent skip when the file is absent. The first run of this
        # census passed a path that did not exist, the loader was skipped,
        # and the report said "person: none in path" for 5,206 series on a
        # share whose top level is literally a list of people. A missing
        # input must look like a failure, not like an empty result.
        if not Path(args.authority).exists():
            print(f"authority file not found: {args.authority}",
                  file=sys.stderr)
            return 2
        pl.load_authority(args.authority)

    files = []
    for spec in args.files:
        label, _, csv_path = spec.partition("=")
        if not csv_path:
            label, csv_path = Path(label).stem, label
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                if row.get("path"):
                    row["source"] = label
                    files.append(row)

    # Same name and same byte count on two storages is one recording held
    # twice, not two recordings. Used only to answer "is this backed up" -
    # it never merges the rows, because where a file lives is the question
    # being asked.
    by_identity = defaultdict(set)
    for row in files:
        key = (os.path.basename(row["path"]).lower(), row.get("size_bytes"))
        by_identity[key].add(row["source"])

    started = time.time()
    rows = []
    read = failed = skipped = 0
    errors = Counter()
    stopped = False

    for entry in files:
        if time.time() - started > args.max_seconds:
            stopped = True
            break
        path, ext = entry["path"], entry.get("ext", "").lower()
        if ext != ".lif":
            skipped += 1
            continue
        try:
            series = lif.series_list(path)
            read += 1
        except Exception as exc:                       # noqa: BLE001
            failed += 1
            errors[type(exc).__name__] += 1
            rows.append({"path": path, "source": entry["source"],
                         "series_index": "", "series_name": "",
                         "error": str(exc)[:180]})
            continue
        ctx = context_of(path)
        held_on = by_identity[(os.path.basename(path).lower(),
                               entry.get("size_bytes"))]
        for s in series:
            rows.append({
                "path": path,
                "source": entry["source"],
                "also_held_on": "|".join(sorted(held_on - {entry["source"]})),
                "file_gb": round(float(entry.get("size_bytes") or 0) / 1e9, 3),
                "series_index": s["index"],
                "series_name": s["name"],
                "derived": derivation_of(s["name"]),
                "shape": shape_of(s),
                "n_x": s["n_x"], "n_y": s["n_y"],
                "n_z": s["n_z"], "n_t": s["n_t"],
                "n_channels": s["n_channels"],
                "lut_names": "|".join(x or "" for x in s["lut_names"]),
                "bit_depth": s["bit_depth"],
                "fps": round(s["fps"], 3) if s["fps"] else "",
                "duration_s": round(s["duration_s"], 2)
                if s["duration_s"] else "",
                "um_per_px": round(s["um_per_px"], 4)
                if s["um_per_px"] else "",
                "um_per_z": round(s["um_per_z"], 4) if s["um_per_z"] else "",
                "field_um": round(s["um_per_px"] * s["n_x"], 1)
                if s["um_per_px"] else "",
                "z_span_um": round(s["um_per_z"] * (s["n_z"] - 1), 1)
                if (s["um_per_z"] and s["n_z"] > 1) else "",
                "calibrated": "yes" if s["um_per_px"] else "NO",
                "strain": ctx.get("strain", ""),
                "person": ctx.get("person", ""),
                "year": ctx.get("year", ""),
                "error": "",
            })

    fields = ["path", "source", "also_held_on",
              "file_gb", "series_index", "series_name", "derived", "shape",
              "n_x", "n_y", "n_z", "n_t", "n_channels", "lut_names",
              "bit_depth", "fps", "duration_s", "um_per_px", "um_per_z",
              "field_um", "z_span_um", "calibrated", "strain", "person",
              "year", "error"]
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    elapsed = time.time() - started
    all_series = [r for r in rows if not r["error"] and r["series_index"] != ""]
    # EVERY COUNT BELOW IS OF ACQUISITIONS. A LIGHTNING copy and a FLIM decay
    # map live in the file as ordinary series, and counting them would report
    # the same recording more than once.
    good = [r for r in all_series if not r["derived"]]

    print(f"{'lif files read':26} {read:,}"
          + ("   STOPPED AT THE CAP" if stopped else "   (complete)"))
    print(f"{'lif files unreadable':26} {failed:,}"
          + (f"   {dict(errors)}" if errors else ""))
    print(f"{'other formats, not read':26} {skipped:,}")
    print(f"{'series in the files':26} {len(all_series):,}")
    print(f"{'  of which ACQUISITIONS':26} {len(good):,}")
    for kind, n in Counter(r["derived"] for r in all_series
                           if r["derived"]).most_common():
        print(f"{'  derived, not counted':26} {n:,}   {kind}")
    print(f"{'elapsed':26} {elapsed:.1f} s"
          + (f"   ({elapsed / read:.2f} s/file)" if read else ""))
    if not good:
        print("\nno readable acquisitions")
        return 0

    print("\nSHAPE - what was actually acquired")
    for shape, n in Counter(r["shape"] for r in good).most_common():
        z = [r for r in good if r["shape"] == shape]
        planes = sum(r["n_z"] for r in z)
        print(f"    {shape:22} {n:5,} series   {planes:7,} z planes")

    stacks = [r for r in good if r["n_z"] > 1]
    print(f"\nZ-STACKS: {len(stacks):,} series in "
          f"{len({r['path'] for r in stacks}):,} files")
    if stacks:
        depths = sorted(r["n_z"] for r in stacks)
        print(f"    planes per stack   min {depths[0]}   "
              f"median {depths[len(depths) // 2]}   max {depths[-1]}")

    print("\nCALIBRATION - can a distance be measured from these at all")
    cal = Counter(r["calibrated"] for r in good)
    for state, n in cal.most_common():
        print(f"    {state:22} {n:5,} series   {n / len(good) * 100:5.1f}%")
    xy = [r["um_per_px"] for r in good if r["um_per_px"]]
    if xy:
        xy = sorted(xy)
        print(f"    um/px  min {xy[0]:.4f}   median {xy[len(xy) // 2]:.4f}"
              f"   max {xy[-1]:.4f}")

    for column, title in (("strain", "STRAIN"), ("year", "YEAR"),
                          ("person", "PERSON")):
        counts = Counter(r[column] or "(none in path)" for r in good)
        print(f"\n{title} read from the path")
        for value, n in counts.most_common(12):
            print(f"    {value:34} {n:5,} series")

    by_year_shape = defaultdict(Counter)
    for r in stacks:
        by_year_shape[r["year"] or "?"][r["strain"] or "(no strain)"] += 1
    if by_year_shape:
        print("\nZ-STACKS by year and strain")
        for year in sorted(by_year_shape):
            inner = ", ".join(f"{k} {v}" for k, v in
                              by_year_shape[year].most_common(5))
            print(f"    {year:8} {inner}")

    # WHERE THE DATA LIVES. A stack that exists on one machine only is one
    # disk failure from not existing, and the scope computer is not a backup.
    print("\nWHERE IT IS HELD")
    per_source = defaultdict(lambda: [0, 0.0])
    for row in files:
        gb = float(row.get("size_bytes") or 0) / 1e9
        per_source[row["source"]][0] += 1
        per_source[row["source"]][1] += gb
    for source, (n, gb) in sorted(per_source.items()):
        alone = sum(1 for r in files if r["source"] == source and
                    len(by_identity[(os.path.basename(r["path"]).lower(),
                                     r.get("size_bytes"))]) == 1)
        lone_gb = sum(float(r.get("size_bytes") or 0) / 1e9 for r in files
                      if r["source"] == source and
                      len(by_identity[(os.path.basename(r["path"]).lower(),
                                       r.get("size_bytes"))]) == 1)
        print(f"    {source:14} {n:5,} files {gb:9,.1f} GB   "
              f"of which {alone:,} ({lone_gb:,.1f} GB) exist nowhere else")

    print("\nNOT ANSWERED HERE: which of these are HEADS. A .lif header has")
    print("no anatomy in it, so that judgement stays with a person.")
    print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
