"""The three damage features Andres described, each on a fixture with an answer.

The point of separating them is that they are different lesions:
  * an interior HOLE with the perimeter intact - which continuity_metrics
    cannot see at all, because every cross-section is still occupied
  * extra bright SCAR tissue - excess signal, invisible to any measure that
    only looks for absence
  * detached filaments that COIL - orientation disorder where there IS signal,
    which must not be confused with the low coherence of empty space
And one thing that is NOT damage: a bent or axially compressed pharynx.
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


UM = 0.05
H, W = 400, 400
yy, xx = np.mgrid[0:H, 0:W]
cy, cx = H / 2, W / 2
r = np.hypot(yy - cy, xx - cx)


theta = np.arctan2(yy - cy, xx - cx)


def bulb(hole_r=None, scar=False, coil=False):
    """A bulb: radial fibres inside a round organ."""
    img = np.zeros((H, W), dtype=float)
    body = r < 150
    spokes = 0.5 + 0.5 * np.cos(24 * theta)      # radial striations
    img[body] = spokes[body]
    if hole_r:
        # OFF-CENTRE on purpose. A void at the exact centre is where the lumen
        # runs, so it would be indistinguishable from normal anatomy - and
        # continuity would legitimately see empty cross-sections there. The
        # lesion Andres describes is a void in the muscle MASS with the rim
        # intact, which has to sit off the axis to mean anything.
        img[np.hypot(yy - cy, xx - (cx + 70)) < hole_r] = 0.0
    if scar:
        s = (np.hypot(yy - (cy - 70), xx - (cx + 60)) < 22)
        img[s] = 6.0                              # abnormally bright patch
    if coil:
        # A filament running ACROSS the radial direction: in a bulb the fibres
        # are radial, so a band at constant radius points perpendicular to
        # where the anatomy expects. That is "lost axial orientation", not
        # merely "turning" - radial tissue turns everywhere by construction.
        # THIN, so it is a ridge. A uniformly bright wide band has almost no
        # gradient inside it, so the structure tensor finds no coherent
        # orientation there and it is excluded as "not fibre" - the fixture
        # would test nothing.
        band = (np.abs(r - 90) < 2.5) & (np.abs(theta) < 0.9)
        img[band] = 1.6
    return img + 0.02


print("pharynx damage features - regression\n")

healthy = bulb()
holed = bulb(hole_r=40)
scarred = bulb(scar=True)
coiled = bulb(coil=True)

# --- interior hole, perimeter intact --------------------------------------
h0 = pc.interior_holes(healthy, UM)
h1 = pc.interior_holes(holed, UM)
check("a healthy bulb has no large interior hole",
      h1["largest_hole_um2"] > h0["largest_hole_um2"],
      f"healthy {h0['largest_hole_um2']} vs holed {h1['largest_hole_um2']} um2")
check("an interior hole is detected", h1["n_interior_holes"] >= 1,
      f"{h1['n_interior_holes']} holes")
expected = np.pi * (40 * UM) ** 2
check("...and measured at about its true area",
      abs(h1["largest_hole_um2"] - expected) < expected * 0.6,
      f"{h1['largest_hole_um2']} vs {expected:.1f} um2 expected")

# THE POINT: continuity cannot see this lesion. Any gaps it does report are
# at the ends, where the unrolled band runs past the bulb into background -
# not at the hole, which is what matters.
centre = np.full(W, float(cy))
un = pc.unroll_about_lumen(holed, centre, UM, radius_um=9.0)
cont = pc.continuity_metrics(un["unrolled"], un["arc_um"], un["radius_um"])
hole_x_um = (cx + 70) * UM
at_hole = [g for g in cont["gaps"]
           if g["start_um"] - 3 <= hole_x_um <= g["end_um"] + 3]
check("continuity_metrics does NOT see an interior hole - hence this module",
      not at_hole,
      f"{cont['n_gaps']} gaps total, {len(at_hole)} at the hole "
      f"({hole_x_um:.1f} um), which interior_holes DOES find")

# --- bright scar -----------------------------------------------------------
s0 = pc.bright_scar(healthy, UM)
s1 = pc.bright_scar(scarred, UM)
check("bright scar tissue is detected", s1["n_scar_patches"] >= 1,
      f"{s1['n_scar_patches']} patches, "
      f"{s1['scar_fraction_of_organ']} of the organ")
check("...and a healthy bulb shows far less",
      s1["scar_area_um2"] > max(s0["scar_area_um2"] * 3, 1.0),
      f"healthy {s0['scar_area_um2']} vs scarred {s1['scar_area_um2']} um2")

# --- coiled filaments ------------------------------------------------------
c0 = pc.coiled_filaments(healthy, UM)
c1 = pc.coiled_filaments(coiled, UM)
check("coiling is detected where filaments curl",
      c1["coiled_fraction_of_fibre"] > c0["coiled_fraction_of_fibre"],
      f"healthy {c0['coiled_fraction_of_fibre']} vs "
      f"coiled {c1['coiled_fraction_of_fibre']}")

# empty space must NOT be scored as coiling
empty = np.zeros((H, W)) + 0.02
empty[r < 150] = 0.02
try:
    pc.coiled_filaments(empty, UM)
    check("an image with no fibres is refused, not scored as disorder", False)
except pc.ContinuityError as exc:
    check("an image with no fibres is refused, not scored as disorder", True)
    check("...naming why low coherence is not coiling",
          "cannot show detached ones" in str(exc))

# --- the report keeps them separate ---------------------------------------
rep = pc.damage_report(holed, UM)
check("the damage report keeps the three lesions separate",
      rep["combined_score"] is None and "different lesions" in
      rep["why_no_combined_score"])
check("...and still reports each one",
      rep["interior_holes"] is not None and rep["bright_scar"] is not None)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("PHARYNX_DAMAGE_PASS")
