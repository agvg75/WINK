"""Three things every plate assay must record, from Andres.

  1. Thermotaxis needs a temperature at EACH END, so the gradient is computed
     across the plate rather than assumed from a slope.
  2. Time off food affects ANY assay run off food - basal slowing becomes
     enhanced basal slowing past the deprivation threshold, which is a
     different behaviour on a different pathway.
  3. Chemotaxis needs stimulus nature and concentration. Diacetyl attracts at
     low concentration and repels at high, so an index without them cannot be
     compared even with a repeat of itself.

The property under test throughout: a missing value is RECORDED as missing and
its cost named, never defaulted into something that looks like a measurement.
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


print("assay metadata - regression\n")

# --- 2. time off food, for any assay --------------------------------------
check("nothing recorded gives 'unknown', not 'fed'",
      pa.food_state(None)["regime"] == "unknown",
      "defaulting to fed asserts the common case over the odd plates")
check("...and says why that matters",
      "most likely to be anomalous" in pa.food_state(None)["why"])
check("a fresh plate is recently fed",
      pa.food_state(300)["regime"] == "recently_fed")
check("past the threshold it is food deprived",
      pa.food_state(35 * 60)["regime"] == "food_deprived")
check("...naming that two pathways are involved",
      "two different pathways" in pa.food_state(35 * 60)["why"])
check("the boundary is inclusive and reported in minutes",
      pa.food_state(1800)["regime"] == "food_deprived" and
      pa.food_state(1800)["minutes_off_food"] == 30.0)
check("the threshold is a parameter, not a constant",
      pa.food_state(20 * 60, threshold_s=15 * 60)["regime"] == "food_deprived",
      "it is an empirical figure belonging to the assay, not the software")

# a plate that crosses the threshold DURING the recording
tracks = [{"plate_id": "p", "worm_id": "w", "time_s": t,
           "x_mm": t * 0.1, "y_mm": 0.0, "spine_quality": 0.9,
           "heading_deg": 0.0}
          for t in range(0, 1200, 10)]
segs = [{**r, "angle_to_vector_deg": 0.0, "radial_heading_deg": 0.0,
         "signed_track_curvature_deg_s": 1.0} for r in tracks]

crossing = pa.population_layer(
    tracks=tracks, segments=segs, time_since_food_removal_s=25 * 60)
check("a plate crossing the threshold mid-recording is flagged",
      "crosses_threshold_at_s" in crossing["food_state"])
check("...naming that one label would be wrong for half of it",
      any("wrong for one half" in w for w in crossing["warnings"]))

steady = pa.population_layer(
    tracks=tracks, segments=segs, time_since_food_removal_s=60)
check("a plate that stays in one regime is not flagged",
      "crosses_threshold_at_s" not in steady["food_state"])

# --- 3. chemotaxis stimulus identity ---------------------------------------
none_given = pa.describe_stimulus(None)
check("no stimulus at all is reported", none_given["complete"] is False)
check("...naming the sign reversal that makes it uninterpretable",
      "opposite signs" in none_given["warnings"][0])

partial = pa.describe_stimulus({"compound": "diacetyl"})
check("a compound without a concentration is incomplete",
      partial["missing"] == ["concentration", "concentration_units"])
check("...naming that it cannot be compared to a repeat of itself",
      "including a repeat of this one" in partial["warnings"][0])

full = pa.describe_stimulus({"compound": "diacetyl", "concentration": 0.001,
                             "concentration_units": "v/v"})
check("a complete stimulus record passes clean",
      full["complete"] and full["warnings"] == [])
check("recording a stimulus warns, it does not refuse",
      pa.describe_stimulus({})["given"] == {},
      "an invented concentration is worse than an acknowledged missing one")

spot = pa.PointSource((10.0, 0.0))
lay = pa.population_layer(tracks=tracks, segments=segs, geometry=spot,
                          time_since_food_removal_s=60, min_worms_per_regime=1)
check("a point-source assay is asked for its stimulus even if none is passed",
      "stimulus" in lay and lay["stimulus"]["complete"] is False,
      "chemotaxis cannot opt out by omission")

# --- 1. thermotaxis end temperatures ---------------------------------------
sys.path.insert(0, str(ROOT / "tools" / "orientation_assays"))
import orientation_workbench as ow   # noqa: E402

t_cfg = ow.configuration_template("thermotaxis")
check("the thermotaxis template asks for both ends",
      set(t_cfg["gradient_ends"]) ==
      {"cold_xy_mm", "hot_xy_mm", "cold_c", "hot_c"})
check("...with a temperature at each end, not just a slope",
      isinstance(t_cfg["gradient_ends"]["cold_c"], float) and
      isinstance(t_cfg["gradient_ends"]["hot_c"], float))
check("...and the ends build a gradient the layer can use",
      pa.LinearGradient(cultivation_c=20, **t_cfg["gradient_ends"]
                        ).temperature_at(50, 0) == 20.0)

c_cfg = ow.configuration_template("chemotaxis")
check("the chemotaxis template asks for compound and concentration",
      {"compound", "concentration", "concentration_units"} <=
      set(c_cfg["stimulus"]))
check("...and for the solvent, which is what the control spot should be",
      "solvent" in c_cfg["stimulus"])

for assay in ("chemotaxis", "thermotaxis", "magnetotaxis"):
    cfg = ow.configuration_template(assay)
    check(f"{assay} asks for time off food",
          "time_since_food_removal_s" in cfg.get("state", {}),
          "any assay where worms are off food")

check("every assay carries the deprivation threshold",
      all("enhanced_slowing_threshold_s" in
          ow.configuration_template(a).get("state", {})
          for a in ("chemotaxis", "thermotaxis")))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("ASSAY_METADATA_PASS")
