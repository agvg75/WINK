"""Regression tests for tools/worm_kinematics/kinematics_movie.py.

Second adapter over app/movie_core.py. As with the RGBCaMP one, most of these
check what it REFUSES and what it STATES: a crash is obvious, but a plausible
movie built from a mismatched stack is not, and neither is a decimated render
that quietly plays seven times too fast.

Fixtures are synthetic - no lab data required.
"""
from pathlib import Path
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools" / "worm_kinematics"))

import matplotlib
matplotlib.use("Agg")

import kinematics_movie as km      # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def make_csv(tmp, n_frames=10, n_seg=24, fps=30.0, um_per_px=0.0,
             velocity_col="centroid_speed_px_s", head_bend=True,
             needs_help_frames=(3, 4)):
    rows = []
    for f in range(1, n_frames + 1):
        for s in range(n_seg):
            row = {
                "worm_id": "w1", "frame": f, "time_s": (f - 1) / fps,
                "segment": s, "fps": fps, "um_per_px": um_per_px,
                "seg_curv_deg": np.sin(f * 0.3 + s * 0.2) * 10,
                "seg_x": 100 + s * 5 + f, "seg_y": 200 + np.sin(s * 0.3) * 20,
                "head_x": 100 + f, "head_y": 200.0,
                "tail_x": 100 + n_seg * 5 + f, "tail_y": 200.0,
                "needs_help": 1 if f in needs_help_frames else 0,
            }
            if velocity_col:
                row[velocity_col] = 10.0 + f
            if head_bend:
                row["head_bend_deg"] = 20 * np.sin(f * 0.5)
            rows.append(row)
    path = tmp / "rec.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def make_stack(tmp, n_frames=10, size=64):
    from PIL import Image
    frames = [Image.fromarray(
        (np.random.default_rng(i).integers(0, 255, (size, size))).astype("uint8"))
        for i in range(n_frames)]
    path = tmp / "stack.tif"
    frames[0].save(path, save_all=True, append_images=frames[1:])
    return path


print("kinematics_movie - regression\n")

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    tmp = Path(td)
    csv_path = make_csv(tmp)
    stack = make_stack(tmp)
    rec = km.load(csv_path, image_path=stack)

    check("loads a well-formed recording",
          rec.n_frames == 10 and rec.n_seg == 24)
    check("finds the velocity column through its alias",
          rec.velocity_column == "centroid_speed_px_s", rec.velocity_column)
    check("reads geometry from the CSV, needing no sidecar",
          len(rec._geo) == 10)
    g = rec.frame_geometry(5)
    check("per-frame geometry has one midline point per segment",
          g is not None and g["mid"].shape == (24, 2), g["mid"].shape)
    check("head and tail are carried too",
          g["head"] is not None and g["tail"] is not None)

    q = rec.quality_summary()
    check("needs_help frames are counted, not averaged away",
          q["frames_flagged"] == 2, q.get("frames_flagged"))

    check("kymograph is segment x frame",
          rec.curvature_kymograph().shape == (24, 10))
    check("velocity stays in px/s when um_per_px is 0",
          rec.um_per_px == 0.0)

    # --- the multipage stack, via the shared FrameSource ------------------
    check("a multipage stack is read as frames", len(rec.images) == 10)
    check("a frame comes back 2-D", rec.images.get(0).ndim == 2)
    check("out-of-range returns None rather than wrapping",
          rec.images.get(999) is None)

    # --- decimation must not speed the movie up --------------------------
    out = tmp / "m.mp4"
    path, prov = km.render(rec, out, decimate=2)
    check("renders", path.exists() and path.stat().st_size > 1000)
    check("decimation halves the frames", prov["n_frames_rendered"] == 5,
          prov["n_frames_rendered"])
    check("a decimated render still plays at real time",
          abs(prov["playback_speed_x"] - 1.0) < 1e-6,
          prov["playback_speed_x"])
    check("output fps is the source rate divided by the decimation",
          abs(prov["output_fps"] - rec.fps / 2) < 1e-6, prov["output_fps"])
    check("an explicit fps still overrides",
          km.render(rec, tmp / "m2.mp4", decimate=2, fps=30.0)[1]["output_fps"] == 30.0)
    check("provenance names the velocity units so px/s is never read as um/s",
          prov["velocity_units"] == "px/s")
    check("provenance carries the quality summary",
          prov["quality"]["frames_flagged"] == 2)

    sheet = km.preview(rec, tmp / "p.png")
    check("preview writes a contact sheet",
          sheet.exists() and sheet.stat().st_size > 5000)

    check("long recordings get a decimation suggestion, not a silent cap",
          km.suggested_decimation(rec, target_frames=5) == 2)

    # The stack handle must be releasable, or the file stays locked for the
    # life of the process and nothing else can touch it.
    rec.close()
    try:
        stack.unlink()
        check("closing releases the stack handle so the file is no longer locked",
              True)
    except PermissionError as exc:
        check("closing releases the stack handle so the file is no longer locked",
              False, str(exc)[:70])

# --- refusals -------------------------------------------------------------
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    tmp = Path(td)
    bad = pd.DataFrame({"frame": [1], "time_s": [0.0]})
    bad.to_csv(tmp / "rec.csv", index=False)
    try:
        km.load(tmp / "rec.csv")
        check("a non-kinematics CSV is refused", False)
    except km.MovieInputError as exc:
        check("a non-kinematics CSV is refused", True)
        check("...naming the columns it needs",
              "segment" in str(exc) and "seg_curv_deg" in str(exc))

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    tmp = Path(td)
    make_csv(tmp, n_frames=10)
    stack = make_stack(tmp, n_frames=7)          # mismatched
    try:
        km.load(tmp / "rec.csv", image_path=stack)
        check("a stack/CSV frame mismatch is refused", False)
    except km.MovieInputError as exc:
        check("a stack/CSV frame mismatch is refused", True)
        check("...and says a mismatched render would look entirely normal",
              "normal" in str(exc).lower())
    # A REFUSED load must not leak the stack handle. The refusal happens after
    # the file is open and the traceback keeps the half-built object alive, so
    # without an explicit close the file stays locked - proved here by deleting
    # it, which Windows refuses while a handle is held.
    try:
        stack.unlink()
        check("a refused load releases the stack handle", True)
    except PermissionError as exc:
        check("a refused load releases the stack handle", False, str(exc)[:60])

# --- optional columns degrade rather than crash ---------------------------
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    tmp = Path(td)
    csv_path = make_csv(tmp, velocity_col=None, head_bend=False)
    rec = km.load(csv_path)
    check("a CSV with no velocity column still loads",
          rec.velocity_column is None)
    check("a CSV with no head bend still loads", rec.has_head_bend is False)
    path, prov = km.render(rec, tmp / "m.mp4")
    check("and still renders, saying what is absent rather than failing",
          path.exists() and path.stat().st_size > 1000)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("KINEMATICS_MOVIE_REGRESSION_PASS")
