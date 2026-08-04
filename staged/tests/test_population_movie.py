"""Regression tests for tools/population_swimming/population_movie.py.

Third adapter over app/movie_core.py. With many animals the question is usually
whether the TRACKING held, so most of these check that the run's own honesty
columns survive to the screen: an animal absent from a frame must draw nothing
rather than linger, a low-confidence modality must not look like a decision,
and a mismatched recording must be refused rather than rendered.

Runs against the committed synthetic fixture - no lab data required.
"""
from pathlib import Path
import json
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools" / "population_swimming"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import population_movie as pm      # noqa: E402

FIXTURE = ROOT / "tests" / "population_swimming_synthetic" / "results"

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("population_movie - regression\n")

check("the committed fixture is present", FIXTURE.exists(), str(FIXTURE))

rec = pm.load(FIXTURE)
check("loads a results folder", rec.n_frames == 120 and len(rec.track_ids) == 2,
      f"{rec.n_frames} frames, {len(rec.track_ids)} tracks")
check("reads fps and scale from analysis_metadata.json",
      rec.fps == 20.0 and rec.um_per_px == 2.0)

speeds, units = rec.speed_by_track()
check("one speed series per animal, all the full length",
      len(speeds) == 2 and all(len(v) == rec.n_frames for v in speeds.values()))
check("speed is in um/s when a scale is declared", units == "um/s", units)

q = rec.quality_summary()
check("the run's honesty columns survive into the summary",
      "rows_without_valid_spine" in q and "median_bout_confidence" in q, q)

check("tracked count is per frame", len(rec.tracked_count()) == rec.n_frames)

rows = rec.frame_rows(rec.frames[5])
check("frames are indexed for lookup", rows is not None and len(rows) == 2)

# --- the figure states what it cannot show ------------------------------
fig, dyn, ctx = pm.build_figure(rec)
pm._update(rec, fig, dyn, ctx, 60)
check("one trail, spine and dot artist per animal",
      len(dyn["trails"]) == 2 and len(dyn["spines"]) == 2
      and len(dyn["dots"]) == 2)
check("every dynamic artist is declared, or it freezes under blitting",
      len(pm._dynamic_artists(dyn)) >= 3 * len(rec.track_ids))
note = dyn["plate_note"].get_text()
check("the plate says how many animals are present this frame",
      "of 2 animals" in note, note)
plt.close(fig)

# --- an absent animal must draw NOTHING, not linger ---------------------
thin = rec.tracks[~((rec.tracks["track_id"] == rec.track_ids[0])
                    & (rec.tracks["frame"] == rec.frames[60]))]
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    tmp = Path(td) / "results"
    shutil.copytree(FIXTURE, tmp)
    thin.to_csv(tmp / "detections_and_tracks.csv", index=False)
    rec2 = pm.load(tmp)
    fig, dyn, ctx = pm.build_figure(rec2)
    pm._update(rec2, fig, dyn, ctx, 60)
    missing = rec.track_ids[0]
    x, _ = dyn["dots"][missing].get_data()
    check("an animal absent from a frame draws nothing rather than lingering "
          "at its last position", len(x) == 0, f"{len(x)} points")
    check("...and the caption counts only the animals actually present",
          "1 of 2 animals" in dyn["plate_note"].get_text(),
          dyn["plate_note"].get_text())
    plt.close(fig)

# --- refusals -------------------------------------------------------------
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    tmp = Path(td)
    try:
        pm.load(tmp)
        check("a folder without detections_and_tracks.csv is refused", False)
    except pm.MovieInputError as exc:
        check("a folder without detections_and_tracks.csv is refused", True)
        check("...and says to point at the RESULTS folder",
              "results folder" in str(exc).lower())

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    tmp = Path(td) / "results"
    shutil.copytree(FIXTURE, tmp)
    pd.DataFrame({"frame": [1]}).to_csv(tmp / "detections_and_tracks.csv",
                                        index=False)
    try:
        pm.load(tmp)
        check("a table missing track_id is refused", False)
    except pm.MovieInputError as exc:
        check("a table missing track_id is refused", True)
        check("...naming what it would otherwise draw",
              "never tracked" in str(exc).lower())

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    tmp = Path(td)
    from PIL import Image
    frames = [Image.fromarray(np.zeros((16, 16), dtype="uint8"))
              for _ in range(5)]                       # far too few
    stack = tmp / "short.tif"
    frames[0].save(stack, save_all=True, append_images=frames[1:])
    try:
        pm.load(FIXTURE, image_path=stack)
        check("a recording with fewer frames than the results is refused", False)
    except pm.MovieInputError as exc:
        check("a recording with fewer frames than the results is refused", True)
        check("...and says a mismatched render would look entirely normal",
              "normal" in str(exc).lower())
    try:
        stack.unlink()
        check("a refused load releases the recording handle", True)
    except PermissionError as exc:
        check("a refused load releases the recording handle", False,
              str(exc)[:60])

# --- render + provenance --------------------------------------------------
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    tmp = Path(td)
    path, prov = pm.render(rec, tmp / "m.mp4", decimate=2)
    check("renders", path.exists() and path.stat().st_size > 1000)
    check("a decimated render still plays at real time",
          abs(prov["playback_speed_x"] - 1.0) < 1e-6, prov["playback_speed_x"])
    check("provenance records the results folder it came from",
          prov["results_dir"].endswith("results"))
    check("provenance carries the quality summary, not just settings",
          "quality" in prov and prov["n_tracks"] == 2)
    sheet = pm.preview(rec, tmp / "p.png")
    check("preview writes a contact sheet",
          sheet.exists() and sheet.stat().st_size > 5000)

rec.close()

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("POPULATION_MOVIE_REGRESSION_PASS")
