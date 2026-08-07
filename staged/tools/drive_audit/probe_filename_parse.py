"""Would parsing FILENAMES be worth it, and how long would it take?

    python probe_filename_parse.py --inventory L_drive_inventory.csv --folders 25

The folder-name audit is done. The vocabulary Andres supplied - strains,
isoform suffixes, RNAi controls, untransformed sisters - largely does NOT
appear in folder names: measured across the 551 labelled rows and the
1,233-folder inventory, sister-type tokens and isoform-suffixed genes are
entirely absent. `pezo-1L` names an image, not a directory.

So the next step is the same vocabulary pointed at filenames. That is a much
bigger corpus - 612,354 files against 1,233 folders - and the question is
whether it is worth the traversal.

THIS ANSWERS BOTH HALVES, SEPARATELY:

  cost   how long listing and parsing actually take, split, because they
         have completely different characters - listing is network I/O over
         SMB, parsing is local CPU on short strings
  value  what fraction of filenames yield anything at all. A pass that costs
         two minutes and labels nothing is not worth running, and a pass that
         costs an hour and labels a third of the archive is.

It SAMPLES. Reading every filename to decide whether to read every filename
would be its own joke.
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import propose_labels as pl   # noqa: E402

MEDIA = {".tif", ".tiff", ".avi", ".mp4", ".mov", ".png", ".jpg", ".jpeg",
         ".lif", ".czi", ".nd2", ".bmp", ".mkv"}


def vocabulary_hits(name):
    """Every field the drive-audit vocabulary can read out of one filename."""
    stem = os.path.splitext(name)[0]
    hits = set()
    for word in re.split(r"[^A-Za-z0-9-]+", stem):
        if not word:
            continue
        key = pl.token_key(word)
        if not key:
            continue
        if key in pl.KNOWN_STRAINS or pl.LAB_STRAIN_RE.match(word):
            hits.add("strain")
        elif pl.VECTOR_RE.match(word) or pl.SISTERS_RE.match(word) \
                or key in pl.CONTROLS:
            hits.add("control")
        elif pl.GENE_RE.match(word):
            match = pl.GENE_RE.match(word)
            hits.add("isoform" if match.group(2) else "gene")
        elif pl.WORM_NUMBER_RE.match(word):
            hits.add("worm_number")
        elif key in pl.GIVEN_NAMES:
            hits.add("person")
    if re.search(r"(20\d\d|\d{1,2}[-_]\d{1,2}[-_]\d{2,4})", stem):
        hits.add("year")
    return hits


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--authority", help="lab_name_authority.xlsx, for names")
    ap.add_argument("--folders", type=int, default=25)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    pl.load_strains()
    if args.authority and Path(args.authority).exists():
        pl.load_authority(args.authority)

    with open(args.inventory, newline="", encoding="utf-8-sig") as handle:
        rows = [r for r in csv.DictReader(handle) if r.get("path")]
    total_files = sum(int(float(r.get("n_files") or 0)) for r in rows)

    random.seed(args.seed)
    sample = random.sample(rows, min(args.folders, len(rows)))

    list_s = parse_s = 0.0
    seen = 0
    media = 0
    fields = Counter()
    per_file_hits = Counter()
    failed = 0

    print(f"sampling {len(sample)} of {len(rows)} folders "
          f"({total_files:,} files in the inventory)\n")
    for row in sample:
        t0 = time.time()
        try:
            names = os.listdir(row["path"])
        except OSError:
            failed += 1
            continue
        list_s += time.time() - t0

        t0 = time.time()
        for name in names:
            seen += 1
            if os.path.splitext(name)[1].lower() in MEDIA:
                media += 1
            hits = vocabulary_hits(name)
            for field in hits:
                fields[field] += 1
            per_file_hits[len(hits)] += 1
        parse_s += time.time() - t0

    if not seen:
        print("no files read")
        return 1

    labelled = seen - per_file_hits[0]
    per_file_us = parse_s / seen * 1e6
    rate = seen / max(list_s + parse_s, 1e-9)

    print(f"{'folders read':24} {len(sample) - failed}  ({failed} unreadable)")
    print(f"{'files seen':24} {seen:,}   ({media:,} media)")
    print()
    print(f"{'listing (SMB I/O)':24} {list_s:8.2f} s   "
          f"{list_s / max(len(sample) - failed, 1) * 1000:7.1f} ms/folder")
    print(f"{'parsing (local CPU)':24} {parse_s:8.2f} s   "
          f"{per_file_us:7.1f} us/file")
    print(f"{'combined throughput':24} {rate:8,.0f} files/s")
    print()
    print(f"{'files yielding anything':24} {labelled:,} of {seen:,} "
          f"({labelled / seen * 100:.1f}%)")
    for field, count in fields.most_common():
        print(f"    {field:20} {count:8,}  {count / seen * 100:5.1f}% of files")
    print()
    # THE PER-FILE RATE IS THE WRONG METRIC AND FLATTERS THE ANSWER. 97% of
    # files "yield something" only because camera timestamps parse as a year,
    # which the folder date already gives. What decides whether this pass is
    # worth running is how many FOLDERS gain a field they do not already have
    # from their own name.
    gained = Counter()
    folders_gaining = 0
    for row in sample:
        try:
            names = os.listdir(row["path"])
        except OSError:
            continue
        from_folder = set()
        for segment in pl.path_segments(row["path"]):
            from_folder |= vocabulary_hits(segment)
        from_files = set()
        for name in names:
            from_files |= vocabulary_hits(name)
        new = {f for f in from_files - from_folder if f != "year"}
        if new:
            folders_gaining += 1
            for field in new:
                gained[field] += 1
    print(f"FOLDERS GAINING A FIELD they do not already have from their name,")
    print(f"ignoring year, which the folder date supplies anyway:")
    print(f"    {folders_gaining} of {len(sample) - failed} sampled "
          f"({folders_gaining / max(len(sample) - failed, 1) * 100:.0f}%)")
    for field, count in gained.most_common():
        print(f"    {field:20} {count:4} folders")
    if not gained:
        print("    none - the filenames repeat what the folder already says")
    print()
    est = total_files / max(rate, 1e-9)
    print(f"EXTRAPOLATED over {total_files:,} inventory files:")
    print(f"    {est / 60:.1f} minutes at the measured rate")
    print(f"    of which listing {total_files / max(seen, 1) * list_s / 60:.1f} "
          f"min and parsing {total_files / max(seen, 1) * parse_s / 60:.1f} min")
    print()
    print("CAVEATS, so the number is not read as more than it is:")
    print("  - the inventory counts IMMEDIATE files only, so the true archive")
    print("    is larger than 612k and this estimate is a floor")
    print("  - a random folder sample under-weights the giant folders; the")
    print("    largest single folder holds 107,976 files")
    print("  - listing is SMB I/O and will vary with network and cache state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
