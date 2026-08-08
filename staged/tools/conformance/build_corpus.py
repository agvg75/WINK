"""Build the repro corpus. Frozen inputs, so a diff means drift and not edits.

    py tools\\conformance\\build_corpus.py --clip pezo1_frozen_six

TWO KINDS OF ENTRY, and choosing the right one is most of the design:

  LISTING   a frozen record of filenames and sizes. Enough for anything that
            reasons about structure - session boundaries, frame counts, date
            conventions, ordering. Costs kilobytes.
  FRAMES    actual copied image files, for anything that touches pixels -
            segmentation, masks, overlays.

The six frozen recordings need only a LISTING: session structure is computed
from FlyCap filenames, never from image data. As frames they would be about
600 GB; as a listing they are a few megabytes, and they are equally frozen.

WHY FROZEN AT ALL. My first golden entry walked the live drive. If anyone
adds, renames or moves one file, the baseline shifts and the next diff
reports drift that never happened - the golden record would be measuring the
drive rather than the pipeline. A corpus that changes is not a corpus.

READ-ONLY BY CONVENTION AND BY PERMISSION WHERE POSSIBLE. Modifying a clip
after it is baselined is itself a scanner violation: it silently redefines
what "unchanged" means for every future run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

CORPUS = Path(r"L:\10_AGVG LAB\Lab Tools\repro_corpus")

SOURCES = {
    "pezo1_frozen_six": {
        "kind": "listing",
        "root": Path(r"L:\05_Proprioception\pezo-1 CRISPR mutants"),
        "folders": ("41921_cop1367", "41921_cop1553", "42821_AG406",
                    "5121_AG405", "CRISPR mutants food density",
                    "pezo CRISPR mutants"),
        "why": ("The frozen development set, confirmed 6 Aug 2026. Session "
                "structure comes from FlyCap filenames, so a listing is the "
                "whole input - as frames this would be ~600 GB and no more "
                "frozen than it already is."),
    },
}

FRAME_EXT = {".tif", ".tiff", ".jpg", ".jpeg", ".pgm", ".png", ".bmp"}


def build_listing(name, spec):
    target = CORPUS / name
    target.mkdir(parents=True, exist_ok=True)
    manifest = {"clip": name, "kind": "listing", "why": spec["why"],
                "source_root": str(spec["root"]),
                "built_utc": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"),
                "folders": {}}
    for folder in spec["folders"]:
        source = spec["root"] / folder
        if not source.is_dir():
            manifest["folders"][folder] = {"error": "not found"}
            print(f"  MISSING {folder}")
            continue
        rows = []
        for path in sorted(source.rglob("*")):
            if path.is_file() and path.suffix.lower() in FRAME_EXT:
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                rows.append(f"{path.relative_to(source)}\t{size}")
        out = target / f"{folder}.listing.tsv"
        text = "\n".join(rows)
        out.write_text(text, encoding="utf-8")
        # The hash is what makes "unmodified" checkable rather than trusted.
        manifest["folders"][folder] = {
            "listing": out.name, "n_files": len(rows),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        print(f"  {folder:<32} {len(rows):>9,} files")
    (target / "CORPUS.json").write_text(json.dumps(manifest, indent=2),
                                        encoding="utf-8")
    try:
        # Best-effort read-only. Convention is the real guard; this is a
        # reminder for the person who reaches for the file anyway.
        for item in target.iterdir():
            os.chmod(item, 0o444)
    except OSError:
        pass
    return manifest


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clip", default=None)
    args = ap.parse_args()
    names = [args.clip] if args.clip else sorted(SOURCES)
    for name in names:
        spec = SOURCES[name]
        print(f"\n{name}  ({spec['kind']})")
        if spec["kind"] != "listing":
            print("  only listing clips are implemented")
            continue
        manifest = build_listing(name, spec)
        total = sum(f.get("n_files", 0) for f in manifest["folders"].values())
        print(f"  total {total:,} files listed -> {CORPUS / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
