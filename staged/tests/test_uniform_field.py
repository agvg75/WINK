"""A coil cage and a permanent magnet are the same assay and different physics.

Under a permanent magnet, direction and magnitude are confounded BY
CONSTRUCTION: an animal heading toward the magnet is simultaneously heading
along the field vector and up a steeply rising magnitude, so orienting-to-
direction and climbing-the-gradient predict the same track. A uniform field
holds direction and removes the gradient, which is what makes it the condition
that tells those two apart.

Also here: ambient conditions, prepopulated with standard lab values and NOT
treated as measured until somebody signs off.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"),
                str(ROOT / "tools" / "orientation_assays"),
                str(ROOT / "tools" / "population_orientation")]

import numpy as np          # noqa: E402
import plate_assay as pa    # noqa: E402
from stimulus_fields import UniformFieldProvider   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("uniform field and ambient conditions - regression\n")

# --- the defining property --------------------------------------------------
cage = UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_mt=0.065)
a = cage.sample(0.0, 0.0)
b = cage.sample(40.0, 25.0)

check("the field is the same everywhere on the plate",
      a.magnitude == b.magnitude and a.direction_xyz == b.direction_xyz)
check("the gradient is EXACTLY zero, not merely small",
      b.gradient_xy == (0.0, 0.0),
      "rounding noise in would blur the distinction this exists to draw")
check("...and says it is zero by construction, not measured",
      b.uncertainty["gradient_is_zero_by_construction"] is True)
check("...naming what that separates",
      "climbing field magnitude" in b.uncertainty["why"])
check("a uniform field still has a true direction",
      UniformFieldProvider.has_true_direction is True,
      "analyze_magnetotaxis requires this")

# --- direction is declared, never inferred from the cage --------------------
flat = UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_mt=1.0,
                            includes_earth_field=True)
vert = UniformFieldProvider(direction_xyz=[0, 0, 1], magnitude_mt=1.0,
                            includes_earth_field=True)
check("a field parallel to the plate has zero inclination",
      abs(flat.sample(0, 0).inclination_deg) < 1e-9)
check("...and a vertical field is 90 degrees, so xyz really is honoured",
      abs(vert.sample(0, 0).inclination_deg - 90.0) < 1e-9,
      "parallel to the plate is the common case, not a hard-coded assumption")

# --- Earth's field: added, or replaced ---------------------------------------
earth = (0.000020, 0.0, -0.000045)
adds = UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_t=0.001,
                            earth_field_xyz_t=earth)
cancels = UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_t=0.001,
                               earth_field_xyz_t=earth,
                               includes_earth_field=True)
check("a cage that adds to Earth's field includes it in the total",
      adds.sample(0, 0).magnitude != cancels.sample(0, 0).magnitude,
      "a cage may cancel and replace Earth's field or add to it")
check("...and which one it is, is recorded",
      adds.sample(0, 0).uncertainty["includes_earth_field"] is False)

# --- refusals ---------------------------------------------------------------
for label, kwargs, phrase in (
    ("no direction", {"direction_xyz": [0, 0, 0], "magnitude_mt": 1.0},
     "not imply it"),
    ("no strength", {"direction_xyz": [1, 0, 0]},
     "null result is uninterpretable"),
    ("two strengths", {"direction_xyz": [1, 0, 0], "magnitude_t": 1.0,
                       "magnitude_mt": 1000.0}, "not both"),
    ("zero strength", {"direction_xyz": [1, 0, 0], "magnitude_t": 0.0},
     "sham condition"),
):
    try:
        UniformFieldProvider(**kwargs)
        check(f"{label} is refused", False)
    except ValueError as exc:
        check(f"{label} is refused", True)
        check(f"...naming the consequence ({label})", phrase in str(exc),
              str(exc)[:70])

check("uniformity that was never measured is flagged",
      cage.sample(0, 0).uncertainty["uniformity_unverified"] is True,
      "the real cage's uniformity is uncertain even though the model's is not")
measured = UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_mt=0.065,
                                uniformity_tolerance_percent=5.0)
check("...and a declared tolerance clears it, without touching the gradient",
      measured.sample(0, 0).uncertainty["uniformity_unverified"] is False and
      measured.sample(0, 0).gradient_xy == (0.0, 0.0))

# --- the workbench can build both --------------------------------------------
import orientation_workbench as ow   # noqa: E402

cfg = ow.configuration_template("magnetotaxis")
check("the magnetotaxis template declares which source it is",
      cfg["provider"]["source_type"] == "magnet",
      "defaulting to magnet keeps every existing configuration working")

coil_cfg = {"provider": {"source_type": "coil", "direction_xyz": [1, 0, 0],
                         "magnitude_mt": 0.065}}
built = ow.build_provider("magnetotaxis", coil_cfg)
check("the workbench builds a cage when asked for one",
      built.provider_type == "uniform_field")
check("...and building it did not mutate the caller's config",
      "source_type" in coil_cfg["provider"],
      "pop on a shared dict would break the second run")
try:
    ow.build_provider("magnetotaxis", {"provider": {"source_type": "wand"}})
    check("an unknown magnetic source is refused", False)
except ValueError as exc:
    check("an unknown magnetic source is refused", True)
    check("...naming that they are not interchangeable",
          "not interchangeable" in str(exc))

# --- ambient conditions, prepopulated but unsigned ---------------------------
amb = pa.ambient_conditions()
check("standard lab conditions are prepopulated",
      amb["values"] == {"temperature_c": 20.0, "humidity_percent": 37.0,
                        "pressure_atm": 1.0})
check("...but not confirmed", amb["confirmed"] is False)
check("...and the lack of sign-off is warned about", bool(amb["warnings"]))
check("...naming that a default reads as a measurement later",
      "will read as measurements" in amb["warnings"][0],
      "a blank field is visibly missing; 20.0 C is not")

signed = pa.ambient_conditions({"temperature_c": 22.5, "humidity_percent": 41,
                                "pressure_atm": 1.0}, confirmed=True)
check("entered and signed conditions pass clean", signed["warnings"] == [])
check("...and keep the entered values", signed["values"]["temperature_c"] == 22.5)

half = pa.ambient_conditions({"temperature_c": 22.5}, confirmed=True)
check("signing off with defaults still in place is called out",
      "defaults still in place" in half["warnings"][0])
check("...listing exactly which ones were defaulted",
      set(half["defaulted"]) == {"humidity_percent", "pressure_atm"})

for assay, phrase in (("magnetotaxis", "agar surface"),
                      ("thermotaxis", "preferred isotherm"),
                      ("chemotaxis", "not the gradient that was pipetted")):
    got = pa.ambient_conditions(assay=assay)
    check(f"{assay} says why ambient conditions matter for it",
          phrase in got["why_it_matters"])

tracks = [{"plate_id": "p", "worm_id": "w", "time_s": t, "x_mm": t * 0.1,
           "y_mm": 0.0, "spine_quality": 0.9, "heading_deg": 0.0}
          for t in range(20)]
segs = [{**r, "angle_to_vector_deg": 0.0, "radial_heading_deg": 0.0,
         "signed_track_curvature_deg_s": 1.0} for r in tracks]
lay = pa.population_layer(tracks=tracks, segments=segs, assay="magnetotaxis",
                          n_placed=1, time_since_food_removal_s=60)
check("the layer carries ambient conditions", "ambient" in lay)
check("...and surfaces the unsigned warning",
      any("not signed off" in w for w in lay["warnings"]))
signed_lay = pa.population_layer(
    tracks=tracks, segments=segs, assay="magnetotaxis", n_placed=1,
    time_since_food_removal_s=60,
    geometry=pa.VectorField(0.0), min_worms_per_regime=1,
    ambient={"temperature_c": 21.0, "humidity_percent": 40.0,
             "pressure_atm": 1.0}, ambient_confirmed=True)
check("...and goes quiet once signed", signed_lay["warnings"] == [],
      str(signed_lay["warnings"]))

for assay in ("chemotaxis", "thermotaxis", "magnetotaxis"):
    block = ow.configuration_template(assay).get("ambient", {})
    check(f"{assay} template prepopulates ambient conditions",
          block.get("temperature_c") == 20.0 and
          block.get("humidity_percent") == 37.0 and
          block.get("pressure_atm") == 1.0)
    check(f"...with the sign-off unticked ({assay})",
          block.get("confirmed") is False)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("UNIFORM_FIELD_PASS")
