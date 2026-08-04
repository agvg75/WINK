"""Rotation to the animal's own frame must be correct AND exactly invertible.

A sign or convention error in the inverse would misplace every boundary by a
consistent amount - which reads as a systematic biological finding rather than
a bug. So the round trip is asserted numerically, not assumed.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import animal_frame as af   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def diagonal_worm(H=400, W=600, angle_deg=30.0, length=380, width=48):
    """A bar at a known angle, so the recovered axis has a right answer."""
    img = np.zeros((H, W), dtype=float)
    yy, xx = np.mgrid[0:H, 0:W]
    cy, cx = H / 2.0, W / 2.0
    th = np.deg2rad(angle_deg)
    u = (xx - cx) * np.cos(th) + (yy - cy) * np.sin(th)
    v = -(xx - cx) * np.sin(th) + (yy - cy) * np.cos(th)
    img[(np.abs(u) < length / 2) & (np.abs(v) < width / 2)] = 1.0
    return img + 0.02


print("animal frame - regression\n")

for planted in (0.0, 20.0, -35.0, 55.0):
    img = diagonal_worm(angle_deg=planted)
    mask = af.tissue_mask(img)
    got, elong, centre = af.axis_angle_deg(mask)
    check(f"axis of a bar planted at {planted:+.0f} deg is recovered",
          abs(((got - planted + 90) % 180) - 90) < 2.0,
          f"got {got:+.2f} deg, elongation {elong:.1f}")

# --- rotation actually straightens it -------------------------------------
img = diagonal_worm(angle_deg=30.0)
vol = np.stack([img] * 4)
rot, tf, report = af.align(vol)
check("align reports it rotated, and by how much",
      report["rotated"] and "rotated by" in report["reason"], report["reason"])
# Threshold the BAR directly rather than reusing tissue_mask here. Rotation
# enlarges the canvas with zero padding, so a percentile threshold shifts onto
# the background and selects the rotated canvas footprint instead of the animal
# - which would measure the frame, not the worm, and report elongation 1.5.
rmask = rot.max(axis=0) > 0.5
rang, relong, _ = af.axis_angle_deg(rmask)
check("after rotation the axis is horizontal",
      abs(((rang + 90) % 180) - 90) < 2.0, f"{rang:+.2f} deg")
check("elongation survives the rotation (the bar is not smeared)",
      relong > 3.0, f"{relong:.1f}")

# --- the round trip is exact ----------------------------------------------
tf2 = af.build_transform((400, 600), 30.0, (200.0, 300.0))
pts = np.array([[10.0, 10.0], [200.0, 300.0], [399.0, 599.0], [123.4, 456.7]])
there = af.points_to_rotated(pts, tf2)
back = af.points_to_original(there, tf2)
err = np.abs(back - pts).max()
check("points map into the rotated frame and back exactly", err < 1e-9,
      f"max error {err:.2e} px")

# a point on the animal must land on the animal after rotating
img = diagonal_worm(angle_deg=25.0)
vol = np.stack([img] * 3)
rot, tf, _ = af.align(vol)
ys, xs = np.nonzero(img > 0.5)
sample = np.stack([ys[::997], xs[::997]], axis=1).astype(float)[:20]
moved = af.points_to_rotated(sample, tf)
rp = rot.max(axis=0)
inside = 0
for y, x in moved:
    iy, ix = int(round(y)), int(round(x))
    if 0 <= iy < rp.shape[0] and 0 <= ix < rp.shape[1] and rp[iy, ix] > 0.5:
        inside += 1
check("tissue points still land on tissue after rotating",
      inside >= len(moved) - 1, f"{inside}/{len(moved)}")

# --- refusals --------------------------------------------------------------
blob = np.zeros((300, 300))
yy, xx = np.mgrid[0:300, 0:300]
blob[((yy - 150) ** 2 + (xx - 150) ** 2) < 70 ** 2] = 1.0
try:
    af.align(np.stack([blob] * 3))
    check("a round region is refused, not rotated arbitrarily", False)
except af.FrameError as exc:
    check("a round region is refused, not rotated arbitrarily", True)
    check("...and says why an arbitrary axis matters",
          "along an arbitrary line" in str(exc))

try:
    af.tissue_mask(np.zeros((200, 200)))
    check("an empty image is refused", False)
except af.FrameError as exc:
    check("an empty image is refused", True)

# a steeply mounted animal is left alone rather than swung 80 degrees
steep = diagonal_worm(angle_deg=78.0)
_, _, rep = af.align(np.stack([steep] * 3), max_correction_deg=60.0)
check("an axis beyond the correction limit is left unrotated, and says so",
      rep["rotated"] is False and "exceeds" in rep["reason"], rep["reason"])

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("ANIMAL_FRAME_PASS")
