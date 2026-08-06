"""Chemotaxis and thermotaxis now get what only magnetotaxis had.

Andres: "they all share a population of worms migrating in an assay plate. We
should not have to redo each one every time."

The property under test is that all three assays get the SAME population layer
from ONE call, and that what differs between them is stimulus geometry and
nothing else.
"""
from pathlib import Path
import math
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


print("shared population layer - regression\n")


def make(n_worms=4, n_t=30):
    tracks = []
    for w in range(n_worms):
        theta = math.radians(30 * w)
        speed = 0.0 if w == 3 else 0.05 + 0.02 * w
        for t in range(n_t):
            time_s = t * 2.0
            r = speed * time_s
            tracks.append({
                "plate_id": "p0", "worm_id": f"w{w}", "time_s": time_s,
                "x_mm": 50.0 + r * math.cos(theta),
                "y_mm": 50.0 + r * math.sin(theta),
                "heading_deg": math.degrees(theta), "spine_quality": 0.9})
    segments = [{**r, "angle_to_vector_deg": 0.0, "radial_heading_deg": 0.0,
                 "signed_track_curvature_deg_s": 1.0} for r in tracks]
    return tracks, segments


tracks, segments = make()

# --- one call gives an assay the whole layer -------------------------------
spot = pa.PointSource((100.0, 50.0))
lay = pa.population_layer(
    tracks=tracks, segments=segments, geometry=spot,
    time_since_food_removal_s=300, min_worms_per_regime=1)

check("the food clock is resolved", lay["time_off_op50_at_start_s"] == 300)
check("movement state at plate opening is classified",
      len(lay["initial_states"]) == 4)
check("per-segment covariates are produced",
      len(lay["covariate_rows"]) == len(tracks))
check("...carrying the food clock forward per row",
      lay["covariate_rows"][-1]["time_off_op50_s"] is not None)
check("worms are split toward and away", lay["regimes"]["per_plate"]["p0"])
check("the geometry is named in the result",
      "point source" in lay["geometry"] and
      lay["geometry_kind"] == "point_source")
check("the warnings left are the unrecorded stimulus and population",
      [w for w in lay["warnings"]
       if "stimulus" not in w.lower() and "animals" not in w.lower()] == [],
      "a point source is a chemotaxis spot, so compound, concentration and "
      "how many worms were placed are all asked for")
full = pa.population_layer(
    tracks=tracks, segments=segments, geometry=spot,
    time_since_food_removal_s=300, min_worms_per_regime=1,
    stimulus={"compound": "diacetyl", "concentration": 0.001,
              "concentration_units": "v/v"},
    n_placed=4)
check("nothing is warned about when everything was supplied",
      full["warnings"] == [], str(full["warnings"]))
check("...and the declared population matches what was tracked",
      full["population"]["recovery"] == 1.0)

# --- what is missing is SAID, not silently dropped -------------------------
bare = pa.population_layer(tracks=tracks, segments=segments)
check("a missing food clock is reported, not just null",
      any("time off OP50" in w for w in bare["warnings"]))
check("...naming that plates at different delays are not comparable",
      any("look like a treatment effect" in w for w in bare["warnings"]),
      "a null column is indistinguishable from a worm never off food")
check("a missing geometry is reported", bare["regimes"] is None and
      any("not split into" in w for w in bare["warnings"]))
check("...while keeping the covariates that are still valid",
      len(bare["covariate_rows"]) == len(tracks))

# --- the same layer, three geometries --------------------------------------
warm = pa.LinearGradient(cold_xy_mm=(0, 50), hot_xy_mm=(100, 50),
                         cold_c=15.0, hot_c=25.0, cultivation_c=25.0)
cool = pa.LinearGradient(cold_xy_mm=(0, 50), hot_xy_mm=(100, 50),
                         cold_c=15.0, hot_c=25.0, cultivation_c=15.0)
field = pa.VectorField(0.0)
layers = {
    "chemotaxis": pa.population_layer(tracks=tracks, segments=segments,
                                      geometry=spot, min_worms_per_regime=1),
    "thermotaxis": pa.population_layer(tracks=tracks, segments=segments,
                                       geometry=warm, min_worms_per_regime=1),
    "magnetotaxis": pa.population_layer(tracks=tracks, segments=segments,
                                        geometry=field, min_worms_per_regime=1),
}
check("all three assays produce the same covariate columns",
      len({tuple(sorted(l["covariate_rows"][0])) for l in layers.values()}) == 1,
      "the population layer is genuinely shared, not three lookalikes")
check("all three classify initial state identically",
      len({tuple(sorted(l["initial_states"].items()))
           for l in layers.values()}) == 1)
check("...and they differ only in the geometry",
      {l["geometry_kind"] for l in layers.values()} ==
      {"point_source", "linear_gradient", "vector_field"})

# --- rearing history flips "toward" on identical plates --------------------
w_lay = pa.population_layer(tracks=tracks, segments=segments, geometry=warm,
                            min_worms_per_regime=1)
c_lay = pa.population_layer(tracks=tracks, segments=segments, geometry=cool,
                            min_worms_per_regime=1)
check("cultivation temperature is recorded in the geometry description",
      "cultivated at 25.0 C" in w_lay["geometry"] and
      "cultivated at 15.0 C" in c_lay["geometry"])
check("the same tracks split differently for differently reared worms",
      w_lay["regimes"] != c_lay["regimes"],
      "identical geometry, opposite toward - a position could not express this")

# --- a gradient that offers no choice --------------------------------------
outside = pa.LinearGradient(cold_xy_mm=(0, 50), hot_xy_mm=(100, 50),
                            cold_c=15.0, hot_c=25.0, cultivation_c=30.0)
o_lay = pa.population_layer(tracks=tracks, segments=segments, geometry=outside,
                            min_worms_per_regime=1)
check("a cultivation temperature off the plate is flagged in the layer",
      o_lay["stimulus_range_check"]["within"] is False)
check("...and raised as a warning, not left in a nested field",
      any("no choice" in w for w in o_lay["warnings"]),
      "the index still looks fine, which is why it must be surfaced")
check("an in-range gradient raises no range warning",
      not any("no choice" in w for w in w_lay["warnings"]) and
      w_lay["stimulus_range_check"]["within"] is True,
      "w_lay has no food clock, so it warns about THAT - correctly")

# --- the assays actually call it -------------------------------------------
chem_src = (ROOT / "tools" / "orientation_assays" / "chemotaxis.py").read_text(
    encoding="utf-8")
therm_src = (ROOT / "tools" / "orientation_assays" / "thermotaxis.py").read_text(
    encoding="utf-8")
check("chemotaxis calls the shared layer",
      "population_layer(" in chem_src and "PointSource(source_xy_mm)" in chem_src)
check("thermotaxis calls the shared layer",
      "population_layer(" in therm_src and "LinearGradient(" in therm_src)
check("thermotaxis passes cultivation temperature into the geometry",
      "cultivation_c=cultivation_temperature_c" in therm_src,
      "this is the parameter that decides which end is 'toward'")
check("thermotaxis says so when the gradient ends are unknown",
      "gradient_ends was not supplied" in therm_src)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("SHARED_POPULATION_LAYER_PASS")
