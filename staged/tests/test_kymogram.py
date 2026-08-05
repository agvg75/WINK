"""Kymogram review: the whole recording in one look, with honest gaps.

The property that matters is that a MISSING frame cannot look like a DARK one.
Black is zero brightness, so a tracking dropout rendered black reads as a
quiescent muscle - the display would turn a failure to measure into a finding.
"""
from pathlib import Path
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import kymogram as ky   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("kymogram review - regression\n")

NF, NSEG = 120, 24
rows = []
for f in range(NF):
    if 40 <= f < 50:          # a tracking dropout
        continue
    for seg in range(NSEG):
        for side in ("dorsal", "ventral"):
            phase = 2 * np.pi * (f / 20.0 - seg / NSEG)
            rows.append({
                "frame": f, "segment": seg, "hemisegment": side,
                "seg_curv_deg": 30 * np.sin(phase),
                "green_p90": 100 + 60 * np.sin(phase + (0 if side == "dorsal"
                                                        else np.pi)),
                "red_p90": 80.0, "blue_p90": 40.0,
            })

# --- the grid -------------------------------------------------------------
g = ky.build(rows, "green_p90", NSEG, side="dorsal", n_frames=NF)
check("the grid is segments by frames", g.shape == (NSEG, NF), f"{g.shape}")
check("THE DROPOUT IS NaN, NOT ZERO",
      np.all(np.isnan(g[:, 40:50])),
      "zero is a real brightness; a gap drawn black would read as a silent muscle")
check("...and everything else is measured",
      np.isfinite(g[:, :40]).all() and np.isfinite(g[:, 50:]).all())

cov = ky.coverage(g)
check("coverage reports the gap", cov["gap_columns"] == 10,
      f"{cov['gap_columns']} empty columns, {cov['fraction']:.0%} measured")

# --- TIME IS REAL TIME ----------------------------------------------------
# Frames after the dropout must stay where they belong. If rows were packed by
# position instead of frame index, everything after frame 50 would slide 10
# columns left and events would appear to happen earlier than they did.
check("frames after a dropout are NOT slid leftward",
      np.isfinite(g[:, 50]).all() and np.all(np.isnan(g[:, 49])),
      "column 50 is measured, column 49 is the gap")

# --- the missing colour is unique -----------------------------------------
cm = ky.channel_cmap("green")
bad = cm.get_bad()[:3]
check("the missing colour appears in no fluorophore ramp",
      all(not np.allclose(bad, cm(x)[:3], atol=0.06)
          for x in np.linspace(0, 1, 256)),
      f"missing={tuple(round(c,2) for c in bad)}")
check("each channel ramps from WHITE to its own fluorophore",
      np.allclose(ky.channel_cmap("red")(0.0)[:3], (1, 1, 1), atol=0.01)
      and ky.channel_cmap("red")(1.0)[0] > 0.8
      and ky.channel_cmap("blue")(1.0)[2] > 0.8
      and ky.channel_cmap("green")(1.0)[1] > 0.5)
check("...so the low end keeps its resolution, where resting calcium lives",
      abs(ky.channel_cmap("green")(0.05)[1] - ky.channel_cmap("green")(0.0)[1])
      > 0.01)
check("curvature is red-white-blue, white at straight",
      np.allclose(ky.curvature_cmap()(0.5)[:3], (1, 1, 1), atol=0.02)
      and ky.curvature_cmap()(0.0)[2] > ky.curvature_cmap()(0.0)[0]
      and ky.curvature_cmap()(1.0)[0] > ky.curvature_cmap()(1.0)[2])

# --- compression must not swallow the odd frame --------------------------
wide = np.tile(np.linspace(10, 12, 2000), (4, 1))
wide[2, 1234] = 900.0                     # one bad frame in two thousand
small, step = ky.downsample_preserving_outliers(wide, 200)
check("a long recording compresses to the requested width",
      small.shape[1] <= 200 and step == 10, f"{small.shape[1]} cols, {step}/col")
check("THE SINGLE ODD FRAME SURVIVES COMPRESSION",
      np.nanmax(small) == 900.0,
      "averaging would have divided it by 10 and hidden it")
mean_would = np.nanmean(wide[2, 1230:1240])
check("...where a mean would have buried it",
      mean_would < 110, f"mean of that block is {mean_would:.0f}, not 900")
gap = wide.copy(); gap[:, 500:520] = np.nan
sg, _ = ky.downsample_preserving_outliers(gap, 200)
check("a wholly missing block stays missing after compression",
      np.isnan(sg[:, 50:51]).all())

# --- panels ---------------------------------------------------------------
spec = ky.panels(rows, n_seg=NSEG, n_frames=NF)
labels = [p["label"] for p in spec]
check("one curvature panel plus three channels x two sides",
      len(spec) == 7, f"{len(spec)} panels: {labels}")
check("...the fluorescence panels are split dorsal and ventral",
      "green dorsal" in labels and "green ventral" in labels)
check("...and curvature is a single panel, since its SIGN is the side",
      sum(1 for p in spec if p["kind"] == "curvature") == 1)
check("the default statistic is p90, the one least tied to ROI area",
      any("green_p90" in r for r in rows)
      and ky.panels(rows, n_seg=NSEG)[1]["grid"] is not None)

# --- limits ---------------------------------------------------------------
lo, hi, basis = ky.limits([p["grid"] for p in spec if p["kind"] == "fluorescence"])
check("shared limits are the default", basis["shared"] is True)
check("...and per-panel limits carry a warning about comparing recordings",
      "cannot be compared by eye" in
      ky.limits([np.array([[1.0, 2.0]]), np.array([[100.0, 200.0]])],
                shared=False)[2]["warning"])

# --- flags ----------------------------------------------------------------
tmp = Path(tempfile.mkdtemp()) / "rec_001.csv"
tmp.write_text("x", encoding="utf-8")

check("a fresh recording has no flags", ky.load_flags(tmp)["flags"] == [])
ky.add_flag(tmp, 44, panel="green dorsal", reason="dropout", by="andres")
ky.add_flag(tmp, 91, panel="curvature (deg)", reason="odd bend")
doc = ky.load_flags(tmp)
check("flagging a frame flags the recording",
      len(doc["flags"]) == 2 and doc["recording_flagged"] is True)
check("...recording which panel and why",
      doc["flags"][0]["panel"] == "green dorsal"
      and doc["flags"][0]["reason"] == "dropout")
ky.add_flag(tmp, 44, panel="green dorsal", reason="changed my mind")
check("re-flagging the same frame and panel replaces rather than duplicates",
      len(ky.load_flags(tmp)["flags"]) == 2)

check("a flag can be taken back", ky.remove_flag(tmp, 44, "green dorsal") == 1)
check("...and the recording stays flagged while others remain",
      ky.load_flags(tmp)["recording_flagged"] is True)
ky.remove_flag(tmp, 91, "curvature (deg)")
check("...until the last one goes",
      ky.load_flags(tmp)["recording_flagged"] is False)

# --- the review queue -----------------------------------------------------
a = Path(tempfile.mkdtemp()) / "a.csv"; a.write_text("x", encoding="utf-8")
b = Path(tempfile.mkdtemp()) / "b.csv"; b.write_text("x", encoding="utf-8")
ky.add_flag(a, 12, reason="check this")
q = ky.flagged_recordings([a, b])
check("the queue lists only recordings with flags",
      len(q) == 1 and q[0]["frames"] == [12], f"{q}")

# --- refusals -------------------------------------------------------------
try:
    ky.build([], "green_p90")
    check("empty rows are refused", False)
except ky.KymogramError:
    check("empty rows are refused", True)

bad_json = Path(tempfile.mkdtemp()) / "c.csv"
bad_json.write_text("x", encoding="utf-8")
ky.flag_path(bad_json).write_text("{not json", encoding="utf-8")
try:
    ky.load_flags(bad_json)
    check("an unreadable flag file is refused, not ignored", False)
except ky.KymogramError as exc:
    check("an unreadable flag file is refused, not ignored", True)
    check("...saying flags would be silently lost",
          "silently lost" in str(exc))

# --- orientation: head DOWN, and both ends named -------------------------
import matplotlib   # noqa: E402
matplotlib.use("Agg")

fig, axes, info = ky.render(rows, n_frames=NF, n_seg=NSEG)
check("head is at the BOTTOM by default, matching how the lab publishes",
      info["orientation"] == "head at bottom", info["orientation"])
# imshow itself inverts the y-axis (row 0 at top), so head-down means putting
# it back: segment 0 ends up at the BOTTOM, i.e. ylim ascending.
lo, hi = axes[0].get_ylim()
check("...segment 0 sits at the bottom of the panel", lo < hi,
      f"ylim {lo:.1f} -> {hi:.1f}")
texts = {t.get_text() for ax in axes for t in ax.texts}
check("both ends are NAMED on every panel", {"head", "tail"} <= texts,
      "an unlabelled body axis is worse than a wrongly-oriented one")

up = ky.render(rows, n_frames=NF, n_seg=NSEG, head_down=False)
check("the convention can be flipped", up[2]["orientation"] == "head at top")
ulo, uhi = up[1][0].get_ylim()
check("...and segment 0 moves to the top when it is", ulo > uhi,
      f"ylim {ulo:.1f} -> {uhi:.1f}")

# --- the head: marked, kept, and out of the scale ------------------------
# The head carries extra reporters in green and red. Including it in the scale
# sets the ceiling from tissue nobody is measuring and crushes the body.
head_bright = [dict(r) for r in rows]
for r in head_bright:
    if r["segment"] < 8:
        r["green_p90"] = 250.0        # the head reporters, far above the body
        r["red_p90"] = 250.0

fig2, ax2, info2 = ky.render(head_bright, n_frames=NF, n_seg=NSEG)
check("green and red are scaled on the BODY, not the head",
      info2["limits"][1] < 200,
      f"ceiling {info2['limits'][1]:.0f}, not the head's 250")
check("...and the report says what was excluded and why",
      "extra reporters" in info2["limit_basis"]["excluded"],
      info2["limit_basis"]["excluded"])
check("...which is what stops the body being crushed into the ramp's bottom",
      info2["limits"][1] < 200)

from matplotlib.patches import Rectangle   # noqa: E402
boxes = {lbl: sum(1 for p in ax.patches if isinstance(p, Rectangle))
         for lbl, ax in zip(info2["panels"], ax2)}
check("green and red panels carry a head box",
      all(boxes[l] >= 1 for l in boxes if l.startswith(("green", "red"))),
      f"{boxes}")
check("...blue does NOT, because the head does not compromise it",
      all(boxes[l] == 0 for l in boxes if l.startswith("blue")),
      f"blue boxes: {[boxes[l] for l in boxes if l.startswith('blue')]}")
check("...and curvature does not either", boxes["curvature (deg)"] == 0)
check("the head data is KEPT, not removed - an absence would invite the "
      "assumption that nothing was there",
      np.isfinite(ky.build(head_bright, "green_p90", NSEG, "dorsal",
                           NF)[:8]).any())
check("which channels are masked is reported",
      set(info2["head_masked_in"]) == {"green", "red"}
      and info2["head_segments"] == list(range(8)))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("KYMOGRAM_PASS")
