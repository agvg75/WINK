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
                            earth_field_xyz_t=earth,
                            includes_earth_field=False)
cancels = UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_t=0.001,
                               earth_field_xyz_t=earth)
check("cancelling Earth is the DEFAULT, because that is what a Merritt does",
      cancels.includes_earth_field is True)
check("a rig that adds to Earth instead gets a different total",
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
     "condition='zero_field'"),
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
FULL_PROTOCOL = {
    "life_stage": "day 1 adult", "assay_start_latency_s": 240,
    "cultivation_apparatus": "environmental box",
    "culture_starved": False, "culture_contaminated": False,
    "culture_overpopulated": False, "coil_orientation_randomised": True,
    "field_measured_before_mT": 0.065, "field_measured_after_mT": 0.065,
    "faraday_shielded": True, "thermal_gradient_c": 0.1,
    "illumination_gradient_checked": True, "food_on_assay_surface": False,
    "bacterial_strain": "OP50", "plate_age_days": 1, "time_of_day": "10:15",
}
signed_lay = pa.population_layer(
    tracks=tracks, segments=segs, assay="magnetotaxis", n_placed=1,
    time_since_food_removal_s=60,
    geometry=pa.VectorField(0.0), min_worms_per_regime=1,
    ambient={"temperature_c": 21.0, "humidity_percent": 40.0,
             "pressure_atm": 1.0}, ambient_confirmed=True,
    protocol=FULL_PROTOCOL)
check("...and goes quiet once signed", signed_lay["warnings"] == [],
      str(signed_lay["warnings"]))
check("the protocol controls are carried in the result",
      signed_lay["protocol"]["n_findings"] == 0 and
      signed_lay["protocol"]["interpretable"] is True)
bare_proto = pa.population_layer(
    tracks=tracks, segments=segs, assay="magnetotaxis", n_placed=1,
    time_since_food_removal_s=60, geometry=pa.VectorField(0.0),
    min_worms_per_regime=1,
    ambient={"temperature_c": 21.0, "humidity_percent": 40.0,
             "pressure_atm": 1.0}, ambient_confirmed=True)
check("an unrecorded protocol surfaces as a single ranked warning",
      any("reverse or abolish the result" in w
          for w in bare_proto["warnings"]),
      "not sixteen separate ones")
check("humidity is read from the ambient block, not recorded twice",
      not any(f["check"] == "relative_humidity"
              for f in bare_proto["protocol"]["findings"]),
      "40% RH was signed off, so the 50% threshold has its value")

for assay in ("chemotaxis", "thermotaxis", "magnetotaxis"):
    block = ow.configuration_template(assay).get("ambient", {})
    check(f"{assay} template prepopulates ambient conditions",
          block.get("temperature_c") == 20.0 and
          block.get("humidity_percent") == 37.0 and
          block.get("pressure_atm") == 1.0)
    check(f"...with the sign-off unticked ({assay})",
          block.get("confirmed") is False)

# --- the four coil conditions ----------------------------------------------
# Andres: double-wrapped Merritt cage. It cancels Earth then imposes a new
# field vectorially. Zero-field controls cancel Earth and impose nothing.
# Current controls run the SAME current antiparallel, for vibration and
# thermal noise.
from stimulus_fields import COIL_CONDITIONS   # noqa: E402

earth_t = (0.000020, 0.0, -0.000045)
common = {"earth_field_xyz_t": earth_t, "includes_earth_field": True}
exp = UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_mt=0.065,
                           condition="field", **common)
zero = UniformFieldProvider(condition="zero_field", **common)
sham = UniformFieldProvider(condition="sham_current", **common)
amb = UniformFieldProvider(condition="ambient", **common)

check("the cage cancels Earth and imposes in its place",
      abs(exp.sample(0, 0).magnitude - 0.000065) < 1e-12,
      "the applied vector IS the total, not added to Earth")
check("a zero-field control really is near zero",
      zero.sample(0, 0).magnitude == 0.0)
check("a sham reads zero field too", sham.sample(0, 0).magnitude == 0.0)
check("...but is distinguishable from a zero field, which is the point",
      zero.sample(0, 0).uncertainty["condition"] !=
      sham.sample(0, 0).uncertainty["condition"],
      "both read zero tesla and control for entirely different things")
check("...naming that the sham controls for the coil, not the field",
      "controls for the coil, not for the field" in
      sham.sample(0, 0).uncertainty["condition_means"])
check("ambient leaves the animal in Earth's field",
      abs(amb.sample(0, 0).magnitude - float(np.linalg.norm(earth_t))) < 1e-12)
check("...and is distinct from a cancelled zero field",
      amb.sample(0, 0).magnitude > zero.sample(0, 0).magnitude,
      "coils off is not the same as Earth actively cancelled")
check("the sham records that the coil is energised",
      sham.sample(0, 0).uncertainty["coil_energised"] is True and
      amb.sample(0, 0).uncertainty["coil_energised"] is False,
      "the field record cannot tell them apart; this can")
check("a control needs no field strength to be constructed",
      zero.magnitude_t is None,
      "requiring one would push people to type a fake number")
try:
    UniformFieldProvider(condition="off", **common)
    check("an unknown condition is refused", False)
except ValueError as exc:
    check("an unknown condition is refused", True)
    check("...naming that it cannot be inferred from the field",
          "cannot be inferred from the field" in str(exc))
try:
    UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_t=0.0,
                         condition="field", **common)
    check("a zero-strength 'field' condition is refused", False)
except ValueError as exc:
    check("a zero-strength 'field' condition is refused", True)
    check("...steering to the condition that records WHY it is zero",
          "condition='zero_field'" in str(exc),
          "Earth cancelled, not a weak field")

# --- oscillating fields ------------------------------------------------------
# Andres: "Oscillations are usually 60 degrees around the mean (30 each way)."
# The DIRECTION sweeps at constant strength - not a polarity reversal.
osc = UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_mt=1.0,
                           oscillation_hz=1.0, **common)
check("a direction sweep is the default oscillation",
      osc.oscillation_mode == "direction" and
      osc.oscillation_amplitude_deg == 30.0,
      "60 degrees around the mean is what this lab runs")
check("the field STRENGTH is constant while it sweeps",
      abs(osc.sample(0, 0, 0.0).magnitude -
          osc.sample(0, 0, 0.25).magnitude) < 1e-15,
      "this is what makes it a sweep and not a reversal")
check("at t=0 the field is on the mean direction",
      abs(osc.applied_at(0.0)[1]) < 1e-12)
check("...swinging 30 degrees one way a quarter cycle later",
      abs(np.degrees(np.arctan2(osc.applied_at(0.25)[1],
                                osc.applied_at(0.25)[0])) - 30.0) < 1e-6)
check("...and 30 degrees the other way at three quarters",
      abs(np.degrees(np.arctan2(osc.applied_at(0.75)[1],
                                osc.applied_at(0.75)[0])) + 30.0) < 1e-6,
      "60 degrees swept in total")
check("the mean direction is NOT cancelled by a sweep",
      osc.applied_at(0.25)[0] > 0 and osc.applied_at(0.75)[0] > 0,
      "unlike a polarity reversal, which would flip the sign")

att = osc.direction_attenuation()
check("the resultant attenuation is computed, not just warned about",
      abs(att["factor"] - 0.9326) < 0.001, f"J0(30 deg) = {att['factor']:.4f}")
check("...reporting the total swept angle", att["swept_deg"] == 60.0)
check("...and what ignoring it would cost",
      "understated" in att["why"])
check("a wider sweep attenuates more",
      UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_mt=1.0,
                           oscillation_hz=1.0, oscillation_amplitude_deg=60.0,
                           **common).direction_attenuation()["factor"] <
      att["factor"])
check("a static field is not attenuated at all",
      exp.direction_attenuation()["factor"] == 1.0)

check("an oscillating field is flagged as time varying",
      osc.is_time_varying and osc.constant_direction is False)
check("...warning that the mean survives but the resultant shrinks",
      "MEAN direction survives" in
      osc.sample(0, 0, 0.1).uncertainty["time_varying_warning"])
check("...and carrying the frequency and the swept angle",
      osc.sample(0, 0, 0.1).uncertainty["oscillation_hz"] == 1.0 and
      osc.sample(0, 0, 0.1).uncertainty["swept_deg"] == 60.0)

# polarity reversal is still available, and is a different stimulus
rev = UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_mt=1.0,
                           oscillation_hz=1.0, oscillation_mode="polarity",
                           **common)
check("a polarity reversal passes through zero strength",
      abs(rev.sample(0, 0, 0.0).magnitude) < 1e-12,
      "which a sweep never does")
check("...and does reverse the vector",
      rev.applied_at(0.25)[0] > 0 > rev.applied_at(0.75)[0])
check("...warning that the reference cancels rather than shrinks",
      "cancels" in rev.sample(0, 0, 0.1).uncertainty["time_varying_warning"])
try:
    UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_mt=1.0,
                         oscillation_hz=1.0, oscillation_mode="wobble",
                         **common)
    check("an unknown oscillation mode is refused", False)
except ValueError as exc:
    check("an unknown oscillation mode is refused", True)
    check("...naming that the two modes are different stimuli",
          "preserves the mean direction and the other cancels" in str(exc))
try:
    UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_mt=1.0,
                         oscillation_hz=1.0, oscillation_amplitude_deg=None,
                         **common)
    check("a sweep with no amplitude is refused", False)
except ValueError as exc:
    check("a sweep with no amplitude is refused", True)
    check("...naming that the swept angle sets the attenuation",
          "how much the measured resultant is attenuated" in str(exc))
try:
    UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_mt=1.0,
                         oscillation_hz=0, **common)
    check("a zero oscillation frequency is refused", False)
except ValueError as exc:
    check("a zero oscillation frequency is refused", True)
    check("...naming that a static field is a different condition",
          "different condition" in str(exc))

# --- rotating fields ---------------------------------------------------------
rot = UniformFieldProvider(
    direction_xyz=[1, 0, 0], magnitude_mt=1.0,
    rotation_schedule=[{"at_s": 300, "rotate_deg": 90}], **common)
check("before the rotation the field is where it started",
      abs(rot.applied_at(0)[0] - 0.001) < 1e-12 and
      abs(rot.applied_at(0)[1]) < 1e-12)
check("...and after it has turned by the declared angle",
      abs(rot.applied_at(400)[1] - 0.001) < 1e-9 and
      abs(rot.applied_at(400)[0]) < 1e-9, "90 degrees at 300 s")
check("rotations accumulate",
      UniformFieldProvider(
          direction_xyz=[1, 0, 0], magnitude_mt=1.0,
          rotation_schedule=[{"at_s": 100, "rotate_deg": 45},
                             {"at_s": 200, "rotate_deg": 45}],
          **common).rotation_at(250) == 90.0)
check("a rotating field is time varying",
      rot.is_time_varying and rot.constant_direction is False)
check("...and says the comparison must be made against the field at that time",
      "not against the starting direction" in
      rot.sample(0, 0, 400).uncertainty["time_varying_warning"])
check("...recording how much rotation had been applied by then",
      rot.sample(0, 0, 400).uncertainty["rotation_applied_deg"] == 90.0)
check("a static field is not flagged as time varying",
      exp.constant_direction is True and
      "time_varying_warning" not in exp.sample(0, 0).uncertainty)
for bad, phrase in (({"at_s": 10}, "not a rotation"),
                    ({"rotate_deg": 90}, "cannot be applied to a track")):
    try:
        UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_mt=1.0,
                             rotation_schedule=[bad], **common)
        check(f"an incomplete rotation step is refused ({bad})", False)
    except ValueError as exc:
        check(f"an incomplete rotation step is refused ({sorted(bad)})", True)
        check("...naming what is missing", phrase in str(exc))

check("the description names the condition and modulation",
      "sham_current" in sham.describe() and
      "sweeping 60 deg at 1.0 Hz" in osc.describe() and
      "reversing at 1.0 Hz" in rev.describe(),
      "a sweep and a reversal must not read the same in a results file")
check("every condition documents what it means",
      all(len(v) > 40 for v in COIL_CONDITIONS.values()))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("UNIFORM_FIELD_PASS")
