"""Stimulus geometry is the only thing that differs between plate assays.

Each geometry answers one question - how far is this animal from the condition
it prefers - and "toward" is that scalar falling. The property under test is
that the abstraction does not quietly invent a preference when the experiment
has not established one.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"),
                str(ROOT / "tools" / "orientation_assays"),
                str(ROOT / "tools" / "population_orientation")]

import plate_assay as pa   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("plate assay geometry - regression\n")

# --- chemotaxis: a point source -------------------------------------------
spot = pa.PointSource((10.0, 0.0))
check("preference falls as the worm nears the spot",
      spot.preference(0, 0) > spot.preference(5, 0) > spot.preference(9, 0))
check("...and is zero at the spot", spot.preference(10, 0) == 0.0)
check("a point source describes itself", "point source" in spot.describe())
try:
    pa.PointSource((1.0, 2.0, 3.0))
    check("a malformed source is refused", False)
except pa.GeometryError as exc:
    check("a malformed source is refused", True)
    check("...naming that it would redefine which worms count as toward",
          "silently redefine" in str(exc))

# --- thermotaxis: two ends, worms in the middle, toward cultivation temp ---
# Andres: "thermotaxis should have two temperatures, one at each end, worms in
# the middle. they crawl towards cultivation temp."
warm = pa.LinearGradient(cold_xy_mm=(0, 0), hot_xy_mm=(100, 0),
                         cold_c=15.0, hot_c=25.0, cultivation_c=25.0)
cool = pa.LinearGradient(cold_xy_mm=(0, 0), hot_xy_mm=(100, 0),
                         cold_c=15.0, hot_c=25.0, cultivation_c=15.0)
check("the gradient interpolates between the ends",
      warm.temperature_at(50, 0) == 20.0, "midpoint of 15-25 C")
check("worms start in the middle at the neutral point",
      warm.temperature_at(50, 0) == cool.temperature_at(50, 0))
check("a worm reared warm prefers the hot end",
      warm.preference(90, 0) < warm.preference(10, 0))
check("...and a worm reared cool prefers the cold end, same plate",
      cool.preference(10, 0) < cool.preference(90, 0),
      "identical geometry, opposite toward - this is why a position cannot "
      "express preference")
check("off-axis position projects onto the gradient axis",
      warm.temperature_at(50, 40) == warm.temperature_at(50, -40))

# --- the refusals that keep a gradient honest ------------------------------
try:
    pa.LinearGradient(cold_xy_mm=(0, 0), hot_xy_mm=(100, 0),
                      cold_c=15.0, hot_c=25.0, cultivation_c=None)
    check("thermotaxis without cultivation temperature is refused", False)
except pa.GeometryError as exc:
    check("thermotaxis without cultivation temperature is refused", True)
    check("...naming that it cannot be recovered from the plate",
          "opposite preferred ends" in str(exc))

try:
    pa.LinearGradient(cold_xy_mm=(0, 0), hot_xy_mm=(100, 0),
                      cold_c=20.0, hot_c=20.0, cultivation_c=20.0)
    check("an isothermal plate is refused", False)
except pa.GeometryError as exc:
    check("an isothermal plate is refused", True)
    check("...naming that it would read noise as thermotaxis",
          "reading noise as thermotaxis" in str(exc))

outside = pa.LinearGradient(cold_xy_mm=(0, 0), hot_xy_mm=(100, 0),
                            cold_c=15.0, hot_c=25.0, cultivation_c=30.0)
r = outside.within_range()
check("a cultivation temperature off the plate is flagged", r["within"] is False)
check("...naming that the plate offers no choice", "no choice" in r["why"])
check("...and that a non-zero index would measure the gradient, not preference",
      "measures the gradient, not" in r["why"])
check("an in-range cultivation temperature passes",
      warm.within_range()["within"] is True and warm.within_range()["why"] is None)

# --- magnetotaxis: a direction, not a place --------------------------------
field = pa.VectorField(0.0)
check("preference falls when moving along the field",
      field.preference(10, 0) < field.preference(0, 0))
check("...and is unchanged moving across it",
      field.preference(0, 10) == field.preference(0, -10))
try:
    pa.VectorField(None)
    check("a field with no direction is refused", False)
except pa.GeometryError as exc:
    check("a field with no direction is refused", True)

# --- the regime split runs identically for all three ------------------------
def track(plate, worm, x0, x1):
    return [{"plate_id": plate, "worm_id": worm, "time_s": t,
             "x_mm": x, "y_mm": 0.0, "angle_to_vector_deg": 0.0,
             "signed_track_curvature_deg_s": 1.0}
            for t, x in ((0, x0), (1, x1))]


rows = track("p", "a", 10, 90) + track("p", "b", 90, 10)
for label, geom, expect_a in (
    ("point source", pa.PointSource((100.0, 0.0)), "toward"),
    ("warm-reared gradient", warm, "toward"),
    ("cool-reared gradient", cool, "away"),
    ("vector field", pa.VectorField(0.0), "toward"),
):
    res = pa.regime_comparison(rows, geometry=geom, min_worms_per_regime=1)
    per = res["per_plate"]["p"]
    got = per.get("status")
    check(f"the same split runs for a {label}", got is not None, str(got))

check("a geometry and a bare source agree when both are a point",
      pa.regime_comparison(rows, (100.0, 0.0), min_worms_per_regime=1) ==
      pa.regime_comparison(rows, geometry=pa.PointSource((100.0, 0.0)),
                           min_worms_per_regime=1),
      "the original call is exactly PointSource, which is what makes the "
      "move behaviour-preserving")

try:
    pa.regime_comparison(rows, min_worms_per_regime=1)
    check("a split with neither geometry nor source is refused", False)
except ValueError as exc:
    check("a split with neither geometry nor source is refused", True)
    check("...naming that the split would be arbitrary",
          "would be arbitrary" in str(exc))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("PLATE_ASSAY_GEOMETRY_PASS")
