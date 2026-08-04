"""Regression tests for tools/rgbcamp/pipeline/results_movie.py.

The module renders and measures nothing, so the tests are mostly about what it
REFUSES and what it states. A movie is the most persuasive artifact this
toolset produces; the failure that matters is not a crash but a plausible movie
built from mismatched inputs, or one that presents an assumption as a
measurement.

Fixtures are synthetic and built here - no lab data is required.
"""
from pathlib import Path
import json
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools" / "rgbcamp" / "pipeline"))

import matplotlib
matplotlib.use("Agg")

import results_movie as rm      # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def make_recording(tmp, n_frames=6, n_seg=24, bands=("dorsal", "ventral"),
                   um_per_px=0.0, src8bit=1, geometry=True, geo_frames=None):
    """A minimal but structurally real CSV + geometry sidecar pair."""
    base = tmp / "rec"
    rows = []
    for f in range(1, n_frames + 1):
        for s in range(n_seg):
            for b in bands:
                rows.append({
                    "frame": f, "time_s": (f - 1) / 5.0, "segment": s,
                    "hemisegment": b, "fps": 5.0, "um_per_px": um_per_px,
                    "src8bit": src8bit,
                    "red_mean": 100 + s, "green_mean": 80 + s, "blue_mean": 20 + s,
                    "bg_red": 1.0, "bg_green": 1.0, "bg_blue": 1.0,
                    "seg_curv_deg": np.sin(f + s), "axial_vel_px_s": f - 3.0,
                    "body_provenance": "measured" if s % 2 else "inferred",
                    "coil_flag": 0, "low_evidence": 0, "skip": 0, "found": 1,
                })
    csv_path = tmp / "rec.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    if geometry:
        gframes = []
        for f in range(1, (geo_frames or n_frames) + 1):
            mid = [[float(i), 10.0] for i in range(20)]
            gframes.append({
                "frame": f, "found": True, "skip": False,
                "midline": mid, "outline": mid + mid[::-1],
                "bands": {str(s): {"L": [[0, 0], [1, 0], [1, 1], [0, 1]],
                                   "R": [[0, 2], [1, 2], [1, 3], [0, 3]]}
                          for s in range(n_seg)},
            })
        (tmp / "rec_geometry.json").write_text(json.dumps({
            "tool": "rgbcamp_fiji", "n_frames": geo_frames or n_frames,
            "n_seg": n_seg, "n_mid": 20, "width_scale": 1.0,
            "muscle_boundary_frac": list(np.linspace(0, 1, n_seg + 1)),
            "frames": gframes}), encoding="utf-8")
    return csv_path


print("results_movie - regression\n")

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)

    # --- the happy path ---------------------------------------------------
    csv_path = make_recording(tmp)
    rec = rm.load(csv_path)
    check("loads a well-formed recording", rec.n_frames == 6 and rec.n_seg == 24)
    check("band names are read from the CSV, not assumed to be L/R",
          rec.band_names == ["dorsal", "ventral"], rec.band_names)

    vals, ranges = rec.channel_values()
    check("channel values are (frames, seg, band, channel)",
          vals.shape == (6, 24, 2, 3), vals.shape)
    check("values are scaled into 0..1",
          np.nanmin(vals) >= 0 and np.nanmax(vals) <= 1)
    check("the numeric range used is reported, so the scale is never implicit",
          set(ranges) == {"red", "green", "blue"}, ranges)

    t, vpx, vum = rec.velocity()
    check("velocity stays in px/s when um_per_px is 0 rather than inventing um",
          vum is None)

    ky = rec.curvature_kymograph()
    check("kymograph is segment x frame", ky.shape == (24, 6), ky.shape)

    prov = rec.provenance_summary()
    check("provenance fractions are reported",
          abs(sum(prov["provenance_fraction"].values()) - 1.0) < 1e-6,
          prov["provenance_fraction"])

# --- refusals: each must name the consequence -----------------------------
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    make_recording(tmp, geometry=False)
    try:
        rm.load(tmp / "rec.csv")
        check("a missing geometry sidecar is refused", False)
    except rm.MovieInputError as exc:
        msg = str(exc).lower()
        check("a missing geometry sidecar is refused", True)
        check("...and the refusal says how to produce one",
              "export geometry sidecar" in msg)
        check("...and warns that re-running loses manual corrections",
              "manual correction" in msg)

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    make_recording(tmp, n_seg=12)
    try:
        rm.load(tmp / "rec.csv")
        check("a 12-segment recording is refused", False)
    except rm.MovieInputError as exc:
        check("a 12-segment recording is refused", True)
        check("...naming the myocyte mapping rather than 'unsupported value'",
              "myocyte" in str(exc).lower())

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    make_recording(tmp, n_frames=6, geo_frames=5)
    try:
        rm.load(tmp / "rec.csv")
        check("a sidecar/CSV frame mismatch is refused", False)
    except rm.MovieInputError as exc:
        check("a sidecar/CSV frame mismatch is refused", True)
        check("...and says a mismatched render would look entirely normal",
              "normal" in str(exc).lower())

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    make_recording(tmp, bands=("dorsal", "ventral", "extra"))
    try:
        rm.load(tmp / "rec.csv")
        check("more than two hemisegment bands is refused", False)
    except rm.MovieInputError:
        check("more than two hemisegment bands is refused", True)

# --- rendering, end to end, with no image sequence ------------------------
with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    csv_path = make_recording(tmp, n_frames=4)
    rec = rm.load(csv_path)
    out = tmp / "movie.mp4"
    try:
        path, prov = rm.render(rec, out, progress=None)
        rendered = path.exists() and path.stat().st_size > 1000
    except Exception as exc:
        rendered, prov = False, {}
        check("renders without an image sequence", False, f"{type(exc).__name__}: {exc}")
    if prov:
        check("renders without an image sequence", rendered,
              f"{out.stat().st_size} bytes" if out.exists() else "no file")
        check("a provenance JSON is written beside the movie",
              (tmp / "movie_provenance.json").exists())
        check("provenance records the normalisation and its numeric ranges",
              "normalisation" in prov and "channel_ranges" in prov)
        check("provenance records velocity units, so px/s is never read as um/s",
              prov["velocity_units"] == "px/s", prov.get("velocity_units"))
        check("provenance records the source CSV and sidecar",
              prov["source_csv"].endswith("rec.csv")
              and prov["geometry_sidecar"].endswith("_geometry.json"))

    # decimation must be recorded, not silent
    path2, prov2 = rm.render(rec, tmp / "movie2.mp4", decimate=2)
    check("decimation renders fewer frames and records the factor",
          prov2["n_frames_rendered"] == 2 and prov2["decimate"] == 2,
          f"{prov2['n_frames_rendered']} frames")

    sheet = rm.preview(rec, tmp / "preview.png")
    check("preview writes a contact sheet",
          sheet.exists() and sheet.stat().st_size > 5000,
          f"{sheet.stat().st_size} bytes" if sheet.exists() else "missing")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("RESULTS_MOVIE_REGRESSION_PASS")
