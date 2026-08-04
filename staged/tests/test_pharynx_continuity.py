"""Continuity must detect HOLES and ignore BENDING.

That separation is the whole point: poor fixation bends a pharynx without
breaking it, so a measure that responds to bending would report mounting
quality as disease. Both are asserted on synthetic pharynxes where the answer
is known - a straight one, the same one bent, and one with a hole cut in it.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import pharynx_continuity as pc   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


UM = 0.1
H, W = 300, 1200


def make(bend_px=0.0, hole=None, dim=None, wall_um=6.0):
    """A pharynx: a muscle wall either side of a lumen, optionally bent."""
    img = np.zeros((H, W), dtype=float)
    x = np.arange(W)
    centre = H / 2 + bend_px * np.sin(np.pi * x / W)
    wall = wall_um / UM
    yy = np.arange(H)[:, None]
    d = np.abs(yy - centre[None, :])
    img[(d > wall * 0.35) & (d < wall)] = 1.0
    if hole:
        # muscle gone, light fine: the background stays normal
        a, b = [int(v / UM) for v in hole]
        img[:, a:b] = 0.0
    img = img + 0.01                       # background / autofluorescence
    if dim:
        # light did not arrive: EVERYTHING there is darker, background too.
        # Applying this before the background offset would have left the floor
        # intact, which is not how an unlit region looks and would have made
        # the fixture untestable rather than the code wrong.
        a, b = [int(v / UM) for v in dim]
        img[:, a:b] *= 0.05
    return img, centre


print("pharynx continuity - regression\n")

# --- an intact pharynx ----------------------------------------------------
img, cy = make()
un = pc.unroll_about_lumen(img, cy, UM)
intact = pc.continuity_metrics(un["unrolled"], un["arc_um"], un["radius_um"])
check("an intact pharynx has no gaps", intact["n_gaps"] == 0,
      f"{intact['n_gaps']} gaps, filled {intact['filled_fraction']}")
check("...and full confidence, since nothing is too dim to judge",
      intact["confidence"] > 0.99, str(intact["confidence"]))

# --- BENDING must not change the answer -----------------------------------
img_b, cy_b = make(bend_px=45.0)
un_b = pc.unroll_about_lumen(img_b, cy_b, UM)
bent = pc.continuity_metrics(un_b["unrolled"], un_b["arc_um"], un_b["radius_um"])
check("a BENT but unbroken pharynx still has no gaps", bent["n_gaps"] == 0,
      f"{bent['n_gaps']} gaps")
check("...and its filled fraction matches the straight one",
      abs(bent["filled_fraction"] - intact["filled_fraction"]) < 0.06,
      f"straight {intact['filled_fraction']} vs bent {bent['filled_fraction']}")

# --- a HOLE must be found -------------------------------------------------
img_h, cy_h = make(hole=(40.0, 52.0))
un_h = pc.unroll_about_lumen(img_h, cy_h, UM)
holed = pc.continuity_metrics(un_h["unrolled"], un_h["arc_um"], un_h["radius_um"])
check("a hole is detected", holed["n_gaps"] >= 1,
      f"{holed['n_gaps']} gaps, largest {holed['largest_gap_um']} um")
check("...and measured at about its true size",
      abs(holed["largest_gap_um"] - 12.0) < 4.0,
      f"{holed['largest_gap_um']} um for a 12 um hole")
check("...so a damaged pharynx scores worse than an intact one",
      holed["gap_fraction_of_measurable"] > intact["gap_fraction_of_measurable"])

# --- a hole in a BENT pharynx is still found, at the same size -------------
img_bh, cy_bh = make(bend_px=45.0, hole=(40.0, 52.0))
un_bh = pc.unroll_about_lumen(img_bh, cy_bh, UM)
bent_holed = pc.continuity_metrics(un_bh["unrolled"], un_bh["arc_um"],
                                   un_bh["radius_um"])
check("a hole is found whether the pharynx is straight or bent",
      bent_holed["n_gaps"] >= 1)
check("...and bending does not change the measured hole size much",
      abs(bent_holed["largest_gap_um"] - holed["largest_gap_um"]) < 5.0,
      f"straight {holed['largest_gap_um']} vs bent {bent_holed['largest_gap_um']}")

# --- a DIM region is not called damage ------------------------------------
img_d, cy_d = make(dim=(60.0, 75.0))
un_d = pc.unroll_about_lumen(img_d, cy_d, UM)
dim = pc.continuity_metrics(un_d["unrolled"], un_d["arc_um"], un_d["radius_um"])
check("an unlit stretch is reported as unlit, not as a gap",
      dim["unlit_um"] > 5.0, f"unlit {dim['unlit_um']} um, "
                             f"gaps {dim['n_gaps']}")
check("...and confidence falls to say so",
      dim["confidence"] < intact["confidence"],
      f"{dim['confidence']} vs {intact['confidence']}")
check("...and the unlit stretch is excluded from the measurable length",
      dim["measurable_length_um"] < dim["length_um"])

# --- refusals --------------------------------------------------------------
try:
    pc.unroll_about_lumen(img, cy[:10], UM)
    check("a centreline of the wrong length is refused", False)
except pc.ContinuityError as exc:
    check("a centreline of the wrong length is refused", True)
    check("...naming what would go wrong",
          "shift the whole unrolled map" in str(exc))

# --- comparison does not pretend to be a statistic -------------------------
cmp = pc.compare(intact, holed)
check("comparing two animals says it is not a statistic",
      cmp["is_a_statistic"] is False and "cannot separate genotype" in cmp["note"])
check("...and reports the weaker confidence of the pair",
      cmp["lower_confidence_of_the_pair"] == min(intact["confidence"],
                                                 holed["confidence"]))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("PHARYNX_CONTINUITY_PASS")
