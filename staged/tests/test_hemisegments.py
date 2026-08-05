"""Per-side muscle ROIs on worms with planted intensities.

The property that matters is the partition: every body pixel must land in
exactly one segment, ON A BENT WORM. Perpendicular slabs cross on the inside of
a bend and gap on the outside, and the error is worst in the frames where the
muscle is most active - so a straight-worm fixture would pass while the method
was wrong exactly where it counts.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import hemisegments as hs   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("hemisegment ROIs - regression\n")

H, W, N = 200, 340, 60
RADIUS = 9.0


def _disc(mask, x, y, r):
    y0, y1 = max(int(y - r - 1), 0), min(int(y + r + 2), mask.shape[0])
    x0, x1 = max(int(x - r - 1), 0), min(int(x + r + 2), mask.shape[1])
    if y1 <= y0 or x1 <= x0:
        return
    sy, sx = np.ogrid[y0:y1, x0:x1]
    mask[y0:y1, x0:x1] |= (sx - x) ** 2 + (sy - y) ** 2 <= r * r


def make(bend=0.0):
    """Head at index 0 (low x). `bend` curves the body; 0 is straight."""
    x = np.linspace(50, 290, N)
    y = 100 + bend * np.sin(np.pi * (x - 50) / 240.0)
    spine = np.column_stack([x, y])
    mask = np.zeros((H, W), bool)
    for px, py in spine:
        _disc(mask, px, py, RADIUS)
    return spine, mask


straight_spine, straight_mask = make(0.0)
bent_spine, bent_mask = make(55.0)

# --- THE PARTITION, on a bent worm ---------------------------------------
a = hs.assign(bent_mask, bent_spine, n_seg=12)
body = bent_mask
assigned = a["segment"] >= 0
check("every body pixel is assigned to a segment",
      np.array_equal(assigned, body),
      f"{int(assigned.sum())} of {int(body.sum())} body pixels")
check("...and nothing outside the body is assigned",
      not (a["segment"] >= 0)[~body].any())
check("...each to exactly one segment, since the label is a single array",
      a["segment"][body].min() >= 0 and a["segment"][body].max() == 11)
check("both sides are populated on a bent worm",
      set(np.unique(a["side"][body])) == {1, -1})

# Segment sizes stay sane through a bend - no segment collapses to nothing,
# which is what a crossing-perpendicular construction produces on the inside.
counts = np.array([int(((a["segment"] == k) & body).sum()) for k in range(12)])
check("no segment is emptied by the bend", counts.min() > 0,
      f"smallest {counts.min()}, largest {counts.max()} px")
check("...and the spread stays modest", counts.max() / counts.min() < 2.5,
      f"ratio {counts.max() / counts.min():.2f}")

# --- anterior-posterior gradient -----------------------------------------
xs = np.tile(np.arange(W, dtype=float), (H, 1))
grad = 100.0 + xs           # brighter toward the tail (high x)
m = hs.measure({"green": grad}, hs.assign(straight_mask, straight_spine, 12))
means = [np.mean([r["green_mean"] for r in m["rows"] if r["segment"] == k])
         for k in range(12)]
check("an anterior-posterior gradient comes out monotonic",
      all(means[i] < means[i + 1] for i in range(11)),
      f"{means[0]:.0f} -> {means[-1]:.0f}")

# --- sides ----------------------------------------------------------------
yy = np.tile(np.arange(H, dtype=float).reshape(-1, 1), (1, W))
one_side = np.where(yy < 100, 200.0, 50.0)      # bright on the low-y side
a_lr = hs.assign(straight_mask, straight_spine, 12)
m_lr = hs.measure({"green": one_side}, a_lr)
by_side = {}
for r in m_lr["rows"]:
    by_side.setdefault(r["hemisegment"], []).append(r["green_mean"])
check("the two sides are separated", len(by_side) == 2, f"{sorted(by_side)}")
check("...and only one of them is bright",
      abs(np.mean(by_side["left"]) - np.mean(by_side["right"])) > 100,
      f"{np.mean(by_side['left']):.0f} vs {np.mean(by_side['right']):.0f}")

# --- dorsal/ventral honesty ----------------------------------------------
check("without a dorsoventral call the sides are LEFT and RIGHT",
      set(a_lr["labels"].values()) == {"left", "right"}
      and a_lr["dorsal_known"] is False)
check("...saying why a confident 'dorsal' would be worse",
      "nothing downstream could tell" in a_lr["side_note"])

a_dv = hs.assign(straight_mask, straight_spine, 12, ventral_sign=1,
                 dorsal_known=True)
check("with a call, sides are dorsal and ventral",
      set(a_dv["labels"].values()) == {"dorsal", "ventral"}
      and a_dv["dorsal_known"] is True)
check("...and the ventral sign picks which is which",
      a_dv["labels"][1] == "ventral"
      and hs.assign(straight_mask, straight_spine, 12, ventral_sign=-1,
                    dorsal_known=True)["labels"][1] == "dorsal")
check("dorsal_known travels on every measured row",
      all(r["dorsal_known"] is True
          for r in hs.measure({"g": grad}, a_dv)["rows"]))

# --- equal arc length, not equal index -----------------------------------
uneven = np.column_stack([np.r_[np.linspace(50, 150, 40),
                                np.linspace(152, 290, 8)],
                          np.full(48, 100.0)])
idx, arc, edges = hs.segment_bounds(uneven, 6)
check("segment boundaries are equally spaced in ARC LENGTH",
      np.allclose(np.diff(edges), edges[-1] / 6),
      f"edges {[round(e, 1) for e in edges]}")
check("...and every point falls inside its own segment's arc bounds",
      all(edges[k] - 1e-9 <= arc[i] <= edges[k + 1] + 1e-9
          for i, k in enumerate(idx)))
# The point counts are wildly unequal, which is the proof it is NOT splitting
# by index: a densely sampled stretch contributes many points to few segments.
per_seg = [int((idx == k).sum()) for k in range(6)]
check("...while point COUNTS per segment are unequal, as equal-index would not be",
      max(per_seg) > 4 * min(per_seg),
      f"points per segment {per_seg}")

# --- kinematics -----------------------------------------------------------
kin = hs.segment_kinematics(bent_spine, 12)
check("per-segment angle and curvature are produced",
      all(r["seg_angle_deg"] is not None for r in kin))
check("...and a bent worm's segments do not all point the same way",
      np.ptp([r["seg_angle_deg"] for r in kin]) > 20,
      f"angle range {np.ptp([r['seg_angle_deg'] for r in kin]):.0f} deg")
check("a straight worm's segments do point the same way",
      np.ptp([r["seg_angle_deg"]
              for r in hs.segment_kinematics(straight_spine, 12)]) < 1.0)

# --- the whole frame ------------------------------------------------------
out = hs.extract_frame({"green": grad, "red": one_side}, bent_mask, bent_spine,
                       n_seg=12, ventral_sign=1, dorsal_known=True)
check("a frame yields two hemisegments per segment", out["n_rows"] == 24,
      f"{out['n_rows']} rows, {out['n_skipped']} skipped")
check("...carrying both channels and the ROI area",
      all({"green_mean", "red_mean", "roi_area_px"} <= set(r)
          for r in out["rows"]))
check("...and per-segment kinematics on the same row",
      all("seg_angle_deg" in r for r in out["rows"]))
check("the area caveat is stated, since a bend changes areas by geometry",
      "measures posture, not muscle" in out["area_note"])
check("...as is the head-first assumption it cannot check",
      "every anterior-posterior gradient in these rows is reversed"
      in out["head_first_assumed"])

# --- refusals -------------------------------------------------------------
try:
    hs.measure({"green": np.zeros((10, 10))}, a_lr)
    check("a mismatched frame is refused", False)
except hs.HemisegmentError as exc:
    check("a mismatched frame is refused", True)
    check("...naming that it would silently read the wrong pixels",
          "without any error" in str(exc))

try:
    hs.assign(np.zeros((H, W), bool), straight_spine, 12)
    check("an empty mask is refused", False)
except hs.HemisegmentError:
    check("an empty mask is refused", True)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("HEMISEGMENTS_PASS")
