"""Run one recording through BOTH spine skeleton methods and diff the results.

The two methods are not interchangeable - spine, curvature and bend frequency
all depend on the choice - so before changing what you report, run this and look
at how far apart they actually are ON YOUR DATA.  Synthetic worms are not
evidence about your recordings.

Usage (from this folder, with the WINK runtime):

    python compare_spine_methods.py <movie-or-folder> --fps 20 --scale 2.0

Optional: --min-area, --max-area, --start, --end, --resolution, --out.

Writes <out>/spine_method_comparison/ containing:
    morphological/            full results from the historical default
    thinning/                 full results from connected thinning
    per_track_comparison.csv  track-by-track differences
    comparison_summary.json   headline numbers and timings

Nothing here changes either method; it only runs both and measures.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
from population_swimming import analyze, SPINE_METHODS

# Result tables are read through read_table. Under pandas 3 a numeric column
# holding one stray non-numeric cell reads as StringDtype, and numpy then
# refuses np.isfinite on it - aborting an analysis with an error that names
# numpy internals rather than the column at fault. The import is guarded
# because these modules are launched several different ways and sys.path is
# not identical in all of them; a hard import would turn a latent dtype
# problem into a tool that will not start.
try:
    from table_io import read_table as _read_table
except Exception:                                    # pragma: no cover
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "app"))
        from table_io import read_table as _read_table
    except Exception:
        _read_table = None


def read_table(path, **kwargs):
    """pandas.read_csv with the pandas-3 dtype trap handled where available."""
    import pandas as _pd
    if _read_table is not None:
        return _read_table(path, **kwargs)
    return _pd.read_csv(path, **kwargs)



def _run(source, out_dir, method, args):
    started = time.perf_counter()
    summary, out = analyze(
        source, args.fps, args.scale, output_dir=out_dir,
        min_area=args.min_area, max_area=args.max_area,
        start_frame=args.start, end_frame=args.end,
        detection_scale=args.resolution,
        progress=lambda i, n, phase="": print(f"  [{method}] {phase}: {i} of {n}   ",
                                              end="\r", flush=True),
        spine_method=method)
    print()
    return summary, Path(out), time.perf_counter() - started


def _spine_stats(results: Path):
    """Per-track spine coverage and curvature from one run."""
    tracks = read_table(results / "detections_and_tracks.csv")
    rows = []
    for tid, g in tracks.groupby("track_id"):
        valid = g.spine_valid.astype(bool) if "spine_valid" in g else pd.Series(False, index=g.index)
        curv = pd.to_numeric(g.get("midbody_curvature_px_inv"), errors="coerce")
        rows.append(dict(
            track_id=int(tid), frames=int(len(g)),
            spine_frames=int(valid.sum()),
            spine_fraction=float(valid.mean()) if len(g) else np.nan,
            median_abs_midbody_curvature=float(np.nanmedian(np.abs(curv))) if len(curv) else np.nan))
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source")
    p.add_argument("--fps", type=float, required=True)
    p.add_argument("--scale", type=float, required=True, help="um per pixel")
    p.add_argument("--min-area", type=int, default=40)
    p.add_argument("--max-area", type=int, default=2500)
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--end", type=int, default=None)
    p.add_argument("--resolution", type=float, default=1.0,
                   help="detection scale: 1.0, 0.5 or 0.25")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    source = Path(args.source)
    base = Path(args.out) if args.out else (
        (source if source.is_dir() else source.parent) / "spine_method_comparison")
    base.mkdir(parents=True, exist_ok=True)

    runs, timings = {}, {}
    for method in SPINE_METHODS:
        print(f"\n=== {method} ===")
        summary, out, elapsed = _run(source, base / method, method, args)
        runs[method] = out
        timings[method] = elapsed
        print(f"  done in {elapsed:.1f} s -> {out}")

    a, b = SPINE_METHODS[0], SPINE_METHODS[1]
    sa, sb = _spine_stats(runs[a]), _spine_stats(runs[b])
    merged = sa.merge(sb, on="track_id", how="outer", suffixes=(f"_{a}", f"_{b}"))

    fa = read_table(runs[a] / "track_summary.csv")[["track_id", "spine_bend_frequency_hz"]]
    fb = read_table(runs[b] / "track_summary.csv")[["track_id", "spine_bend_frequency_hz"]]
    merged = merged.merge(fa.rename(columns={"spine_bend_frequency_hz": f"bend_hz_{a}"}),
                          on="track_id", how="left")
    merged = merged.merge(fb.rename(columns={"spine_bend_frequency_hz": f"bend_hz_{b}"}),
                          on="track_id", how="left")
    merged["bend_hz_difference"] = merged[f"bend_hz_{b}"] - merged[f"bend_hz_{a}"]
    merged["spine_fraction_difference"] = (merged[f"spine_fraction_{b}"]
                                           - merged[f"spine_fraction_{a}"])
    merged.to_csv(base / "per_track_comparison.csv", index=False)

    both = merged.dropna(subset=[f"bend_hz_{a}", f"bend_hz_{b}"])
    summary_json = {
        "source": str(source),
        "detection_scale": args.resolution,
        "seconds": {m: round(t, 1) for m, t in timings.items()},
        "tracks": {m: int(len(_spine_stats(runs[m]))) for m in SPINE_METHODS},
        "mean_spine_fraction": {m: float(_spine_stats(runs[m]).spine_fraction.mean())
                                for m in SPINE_METHODS},
        "tracks_with_frequency_from_both": int(len(both)),
        "bend_hz_mean_absolute_difference": (float(both.bend_hz_difference.abs().mean())
                                             if len(both) else None),
        "bend_hz_max_absolute_difference": (float(both.bend_hz_difference.abs().max())
                                            if len(both) else None),
        "interpretation": (
            "spine_fraction is the share of frames that yielded a usable spine. A large "
            "gap means one method is silently dropping frames. bend_hz differences are "
            "the reported measurement changing; judge them against your effect size."),
    }
    (base / "comparison_summary.json").write_text(json.dumps(summary_json, indent=2),
                                                  encoding="utf-8")

    print("\n--- comparison ---")
    for m in SPINE_METHODS:
        print(f"  {m:<15} {timings[m]:7.1f} s   mean spine fraction "
              f"{summary_json['mean_spine_fraction'][m]:.3f}")
    if len(both):
        print(f"  bend frequency: mean |diff| "
              f"{summary_json['bend_hz_mean_absolute_difference']:.4f} Hz, "
              f"max {summary_json['bend_hz_max_absolute_difference']:.4f} Hz "
              f"over {len(both)} track(s)")
    print(f"\nwritten to {base}")


if __name__ == "__main__":
    main()
