"""Choosing the imaging plane at the microscope.

Two properties matter. Sharpness must NOT move when the gain does, or 'better
focus' and 'brighter laser' become the same measurement. And a peak at the edge
of the sampled range must be reported as such, because that is the case a
single frame cannot reveal and the one where picking the best is worst.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

import acquisition_focus as af   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("acquisition focus - regression\n")

H, W, N = 120, 260, 40
rng = np.random.default_rng(5)
spine = np.column_stack([np.linspace(40, 220, N), np.full(N, 60.0)])
yy, xx = np.mgrid[0:H, 0:W]
mask = np.zeros((H, W), bool)
for px, py in spine:
    mask |= (xx - px) ** 2 + (yy - py) ** 2 <= 10 ** 2


def plane(blur, gain=1.0, tilt=0.0):
    """A frame whose structure blurs with `blur`; `gain` scales everything."""
    from scipy.ndimage import gaussian_filter
    img = np.zeros((H, W))
    for px, py in spine[::3]:                       # discrete organelles
        img += 90 * np.exp(-(((xx - px) ** 2 + (yy - py) ** 2) / 6.0))
    if blur > 0:
        img = gaussian_filter(img, blur)
    if tilt:
        img *= 1.0 + tilt * np.sign(yy - 60)        # one side favoured
    return (img + rng.normal(0, 0.5, (H, W))) * gain


sharp, soft = plane(0.0), plane(3.0)
check("a sharp plane scores above a blurred one",
      af.sharpness(sharp, mask) > af.sharpness(soft, mask),
      f"{af.sharpness(sharp, mask):.3f} vs {af.sharpness(soft, mask):.3f}")

# THE PROPERTY THAT MATTERS: turning the laser up must not improve the score.
loud = plane(3.0, gain=4.0)
check("SHARPNESS DOES NOT RISE WITH GAIN",
      abs(af.sharpness(loud, mask) - af.sharpness(soft, mask)) < 0.02,
      f"gain x4 moves it {af.sharpness(loud, mask) - af.sharpness(soft, mask):+.4f}")
check("...while raw signal does, which is why it is not the criterion",
      np.median(loud[mask]) > 3 * np.median(soft[mask]),
      "brightness alone would rank a louder laser as better focus")

# --- symmetry catches what sharpness cannot ------------------------------
even = af.side_symmetry(plane(0.0), mask, spine)
tilted = af.side_symmetry(plane(0.0, tilt=0.6), mask, spine)
check("an even plane is symmetric", even > 0.8, f"{even:.2f}")
check("a tilted plane is caught, though it is just as sharp",
      tilted < even * 0.8, f"tilted {tilted:.2f} vs even {even:.2f}")

# --- scoring uses the SUSCEPTIBLE channels -------------------------------
q = af.frame_quality({"green": soft, "red": sharp, "blue": sharp}, mask, spine)
check("focus is scored on red and blue, not green", set(q["scored_on"]) == {"red", "blue"},
      f"{q['scored_on']}")
check("...and green is still measured, just not trusted to guide",
      q["channels"]["green"]["sharpness"] is not None)
gq = af.frame_quality({"green": sharp}, mask, spine)
check("green alone cannot guide focus, and says so",
      gq["focus_score"] is None and "barely changes" in gq["why"])
check("a single frame states that it cannot give direction",
      "not whether a better one is above or below" in q["single_frame_limit"])

# --- the sweep ------------------------------------------------------------
blurs = [3.0, 1.5, 0.0, 1.5, 3.0]                   # optimum in the middle
planes = [(z, {"red": plane(b), "blue": plane(b)}, mask, spine)
          for z, b in zip(range(-2, 3), blurs)]
s = af.sweep(planes)
check("the sweep finds the bracketed optimum", s["best_z"] == 0,
      f"best z = {s['best_z']}")
check("...and says the peak was inside the range", s["peak_at_edge"] is False)
check("...ranking on sharpness rather than brightness",
      "does not move when the gain does" in s["why_not_brightness"])

# THE CASE THAT MATTERS: the optimum was never visited.
rising = [3.0, 2.0, 1.0]
edge = af.sweep([(z, {"red": plane(b), "blue": plane(b)}, mask, spine)
                 for z, b in zip(range(3), rising)])
check("A PEAK AT THE EDGE IS REPORTED, not silently returned as the best",
      edge["peak_at_edge"] is True and "EDGE" in edge["guidance"],
      edge["guidance"][:64])
check("...and it says which way to extend", "deeper" in edge["guidance"])

tilt_planes = [(z, {"red": plane(0.0, tilt=0.6), "blue": plane(0.0, tilt=0.6)},
                mask, spine) for z in range(3)]
ts = af.sweep(tilt_planes)
check("a tilted mount is called out even when focus is good",
      "will not be safe" in (ts["symmetry_note"] or ""),
      f"symmetry {ts['symmetry_at_best']}")

try:
    af.sweep(planes[:2])
    check("two planes are refused", False)
except af.FocusError as exc:
    check("two planes are refused", True)
    check("...naming it a coin toss dressed as a measurement",
          "coin toss" in str(exc))

try:
    af.sharpness(sharp, np.zeros((5, 5), bool))
    check("a mismatched mask is refused", False)
except af.FocusError as exc:
    check("a mismatched mask is refused", True)
    check("...naming that it would rank planes by the background",
          "by what was in the background" in str(exc))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("ACQUISITION_FOCUS_PASS")
