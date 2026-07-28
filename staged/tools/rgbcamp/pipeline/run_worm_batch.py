"""
run_worm_batch.py
=================
Run the animal-as-unit-of-N batch layer over a folder of WormRGBCaMPMap_v1
extraction CSVs.

    python run_worm_batch.py  path/to/csv_folder  output_dir  [axis]

Pipeline per file: load -> QC -> channel normalisation (background + dF/F0) ->
head mask -> all kinetics. Metadata comes from a metadata.csv manifest in the
folder if present, else from filename tokens (see WORM_BATCH_README.md).

Writes tidy master tables (transients, per-recording, animal summary), a parse
log, an inclusion report, and — if a grouping axis is statistically usable —
animal-level group statistics (worm = unit of N).
"""
import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import pandas as pd

import worm_batch as wb


def main(csv_dir, out_dir, axis=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    res = wb.run_batch(csv_dir)

    res.master_transients.to_csv(out / "worm_batch_master_transients.csv", index=False)
    res.per_recording.to_csv(out / "worm_batch_per_recording.csv", index=False)
    res.animal_summary.to_csv(out / "worm_batch_animal_summary.csv", index=False)
    res.parse_log.to_csv(out / "worm_batch_parse_log.csv", index=False)
    res.waves.to_csv(out / "worm_batch_waves.csv", index=False)
    with open(out / "worm_batch_inclusion.json", "w") as f:
        json.dump(res.inclusion, f, indent=2, default=str)

    gi = res.inclusion["group_inference_ok"]
    print(f"Files: {res.inclusion['n_files']}  included: {res.inclusion['n_included']}"
          f"  excluded: {res.inclusion['n_excluded']}")
    print("Group inference:", gi["reason"])

    # run stats on each usable axis (or the requested one)
    usable = gi.get("usable_axes", [])
    axes = [axis] if axis else usable
    for ax in axes:
        if ax not in usable:
            print(f"  ! axis '{ax}' not statistically usable; skipping")
            continue
        stats = wb.animal_level_stats(res.animal_summary, axis=ax)
        stats.to_csv(out / f"worm_batch_stats_{ax}.csv", index=False)
        print(f"  wrote animal-level stats for '{ax}' "
              f"({len(stats)} metrics)")

    print("Wrote batch tables to", out)
    return res


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    o = sys.argv[2] if len(sys.argv) > 2 else "worm_batch_output"
    a = sys.argv[3] if len(sys.argv) > 3 else None
    main(d, o, a)
