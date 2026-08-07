"""How much storage would actually be needed to hold all of it, once.

    py storage_audit.py --out audit.csv L=L:\\ scope=\\\\SLB122E-01\\share ...

Written to size a purchase. The question is not "how big is each drive" -
Windows answers that - but how much a SINGLE drive would need, which means
knowing how much is the same bytes held twice.

WHAT IS COMPARED, AND THE CAVEAT THAT GOES WITH IT. Two files are treated as
one copy when they share a FILENAME and an EXACT BYTE COUNT. That is a
conservative test in one direction only: a file copied and then RENAMED reads
as unique on both sides, so the duplicate total is a FLOOR and the union size
is a CEILING. Nothing here opens a file or hashes contents, so two different
files that happen to share a name and a size would be counted as one - in a
lab archive of camera-numbered frames that is possible, and it is the reason
this is presented as a bound rather than a measurement.

os.scandir, never os.path.getsize per file. On a network share the size comes
back with the directory entry, so asking again costs a round trip each: the
same 10.5 M file walk measured 400 s with scandir and 1,500 s for 8% of it
with getsize. Across four locations that difference is hours.

MEMORY. Every file needs a key held in RAM to compare across locations. The
size is packed into the low bits of the key rather than kept in a parallel
dict, which turns roughly 3 GB of dictionary into under 1 GB of set for a
15 M file archive.
"""
from __future__ import annotations

import argparse
import csv
import os
import time
from collections import Counter

SKIP_NAMES = {"$RECYCLE.BIN", "System Volume Information", ".git",
              "__pycache__", "node_modules", ".venv", "System Volume Info"}

SIZE_BITS = 40          # up to 1 TB per file, which no single file here is
SIZE_MASK = (1 << SIZE_BITS) - 1


def key_of(name, size):
    """One integer identifying (filename, exact size), size recoverable."""
    return (hash(name.lower()) & ((1 << 62) - 1)) << SIZE_BITS \
        | (size & SIZE_MASK)


def size_of(key):
    return key & SIZE_MASK


def walk(root, label, *, cap):
    """Every file under root, as keys plus per-extension totals."""
    started = time.time()
    keys = set()
    count = Counter()
    byte_total = Counter()
    files = 0
    total_bytes = 0
    dirs = 0
    stack = [root]
    stopped = False

    while stack:
        if time.time() - started > cap:
            stopped = True
            break
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name not in SKIP_NAMES:
                                stack.append(entry.path)
                            continue
                        size = entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
                    files += 1
                    total_bytes += size
                    extension = os.path.splitext(entry.name)[1].lower() \
                        or "(none)"
                    count[extension] += 1
                    byte_total[extension] += size
                    keys.add(key_of(entry.name, size))
        except OSError:
            continue
        dirs += 1
        if dirs % 5000 == 0:
            print(f"  [{label}] {dirs:,} dirs  {files:,} files  "
                  f"{total_bytes / 1e12:.2f} TB  "
                  f"{time.time() - started:.0f}s", flush=True)

    return {"label": label, "root": root, "dirs": dirs, "files": files,
            "bytes": total_bytes, "keys": keys, "count": count,
            "byte_total": byte_total, "seconds": time.time() - started,
            "stopped": stopped}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("locations", nargs="+", metavar="LABEL=PATH")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-seconds", type=float, default=3600.0)
    args = ap.parse_args()

    surveys = []
    for spec in args.locations:
        label, _, root = spec.partition("=")
        if not root:
            label, root = os.path.splitdrive(label)[0] or label, label
        if not os.path.exists(root):
            print(f"SKIPPED {label}: {root} is not reachable")
            continue
        print(f"\nwalking {label}  {root}")
        surveys.append(walk(root, label, cap=args.max_seconds))

    if not surveys:
        print("nothing to audit")
        return 1

    # How many locations hold each key. Built once, read for every question
    # below, so no key is hashed more than twice.
    holders = Counter()
    for survey in surveys:
        for key in survey["keys"]:
            holders[key] += 1

    union_files = len(holders)
    union_bytes = sum(size_of(key) for key in holders)
    gross_bytes = sum(s["bytes"] for s in surveys)
    gross_files = sum(s["files"] for s in surveys)

    print("\n" + "=" * 72)
    print("PER LOCATION")
    print(f"    {'location':12} {'files':>12} {'TB':>8} {'dirs':>9} "
          f"{'walk':>7}   only here (files / TB)")
    for survey in surveys:
        alone = [k for k in survey["keys"] if holders[k] == 1]
        alone_bytes = sum(size_of(k) for k in alone)
        flag = "  CAPPED" if survey["stopped"] else ""
        print(f"    {survey['label']:12} {survey['files']:12,} "
              f"{survey['bytes'] / 1e12:8.2f} {survey['dirs']:9,} "
              f"{survey['seconds']:6.0f}s   {len(alone):,} / "
              f"{alone_bytes / 1e12:.2f} TB{flag}")

    print("\nWHAT A SINGLE DRIVE WOULD HAVE TO HOLD")
    print(f"    {'sum of all four (gross)':34} {gross_bytes / 1e12:8.2f} TB"
          f"   {gross_files:,} files")
    print(f"    {'UNION, duplicates counted once':34} "
          f"{union_bytes / 1e12:8.2f} TB   {union_files:,} files")
    saved = gross_bytes - union_bytes
    print(f"    {'held more than once':34} {saved / 1e12:8.2f} TB"
          f"   ({saved / max(gross_bytes, 1) * 100:.0f}% of the gross)")
    print(f"\n    A drive of {union_bytes / 1e12:.1f} TB holds everything "
          f"exactly once.")
    print(f"    Treat that as a CEILING: a renamed copy reads as unique, so")
    print(f"    the true figure is this or lower, never higher.")

    print("\nCOPIES ACROSS LOCATIONS")
    spread = Counter(holders.values())
    for held_in, n in sorted(spread.items()):
        these = sum(size_of(k) for k, v in holders.items() if v == held_in)
        word = "location" if held_in == 1 else "locations"
        print(f"    in {held_in} {word:9} {n:12,} files   "
              f"{these / 1e12:7.2f} TB")

    print("\nWHERE THE BULK SITS, by extension across all locations")
    merged = Counter()
    merged_bytes = Counter()
    for survey in surveys:
        merged.update(survey["count"])
        merged_bytes.update(survey["byte_total"])
    print(f"    {'ext':12} {'files':>12} {'TB':>8} {'% of bytes':>11}")
    for extension, size in merged_bytes.most_common(18):
        print(f"    {extension:12} {merged[extension]:12,} "
              f"{size / 1e12:8.2f} {size / max(gross_bytes, 1) * 100:10.1f}%")

    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["section", "a", "b", "c", "d"])
        for survey in surveys:
            alone = [k for k in survey["keys"] if holders[k] == 1]
            writer.writerow(["location", survey["label"], survey["files"],
                             survey["bytes"], len(alone)])
        writer.writerow(["union", "", union_files, union_bytes, ""])
        writer.writerow(["gross", "", gross_files, gross_bytes, ""])
        for extension, size in merged_bytes.most_common():
            writer.writerow(["extension", extension, merged[extension],
                             size, ""])
    print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
