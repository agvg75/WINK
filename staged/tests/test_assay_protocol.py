"""The per-assay controls, checked against the lab's own published methods.

The properties under test: unrecorded is distinguished from not-done, every
finding names its consequence, and the one genuine GATE - life stage - is
treated differently from every confound, because outside day-1 adult a null
magnetotaxis result carries no information rather than weak information.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import assay_protocol as apr   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def has(findings, name):
    return next((f for f in findings if f["check"] == name), None)


print("assay protocol - regression\n")

GOOD = {
    "life_stage": "day 1 adult",
    "assay_start_latency_s": 240,
    "cultivation_apparatus": "environmental box",
    "culture_starved": False, "culture_contaminated": False,
    "culture_overpopulated": False,
    "coil_orientation_randomised": True,
    "field_measured_before_mT": 0.065, "field_measured_after_mT": 0.065,
    "faraday_shielded": True,
    "humidity_percent": 35.4,
    "thermal_gradient_c": 0.1,
    "illumination_gradient_checked": True,
    "food_on_assay_surface": False,
    "bacterial_strain": "OP50",
    "plate_age_days": 1,
    "time_of_day": "10:15",
}

clean = apr.summarise(GOOD)
check("a fully recorded, well-controlled assay raises nothing",
      clean["n_findings"] == 0, f"{clean['n_findings']} findings")
check("...and is interpretable", clean["interpretable"] is True)

empty = apr.summarise({})
check("an empty record raises everything", empty["n_findings"] > 12,
      f"{empty['n_findings']} findings")
check("...all of them as unrecorded rather than as failures",
      empty["n_unrecorded"] == empty["n_findings"])
check("...and the distinction is stated",
      "different fixing" in empty["unrecorded_is_not_not_done"])

# --- the gate ---------------------------------------------------------------
larval = apr.summarise({**GOOD, "life_stage": "L4"})
f = has(larval["findings"], "life_stage")
check("a larval assay is gated, not merely warned", f["severity"] == "gate")
check("...naming that a null result carries no information",
      "uninformative rather than evidence of no effect" in f["message"])
check("...and the assay is marked uninterpretable",
      larval["interpretable"] is False)
check("a day-1 adult assay passes the gate",
      has(apr.check(GOOD), "life_stage") is None)
check("an unrecorded life stage is still raised",
      has(apr.check({k: v for k, v in GOOD.items() if k != "life_stage"}),
          "life_stage")["state"] == "unrecorded")
check("...but life stage does not apply to a chemotaxis assay",
      has(apr.check({}, assay="chemotaxis"), "life_stage") is None,
      "larvae chemotax and thermotax normally; only magnetotaxis is gated")

# --- unrecorded vs not done -------------------------------------------------
unrec = has(apr.check({**GOOD, "coil_orientation_randomised": None}),
            "coil_orientation_randomised")
notdone = has(apr.check({**GOOD, "coil_orientation_randomised": False}),
              "coil_orientation_randomised")
check("an unrecorded control and a skipped one are different states",
      unrec["state"] == "unrecorded" and notdone["state"] == "not_done")
check("...and say different things",
      unrec["message"] != notdone["message"])
check("...both naming the room-fixed confound",
      "room-fixed" in unrec["message"] and
      "room coordinates" in notdone["message"],
      "any directional cue in the room predicts field direction exactly")

# --- the things that reverse the sign ---------------------------------------
late = has(apr.check({**GOOD, "assay_start_latency_s": 900}),
           "assay_start_latency")
check("a long start latency is flagged", late["severity"] == "reverses_result")
check("...expressed as a fraction of the way to the reversal",
      "50%" in late["message"], "15 min against a 30 min reversal")
check("...and naming that plates are then not replicates",
      "not replicates of each other" in late["message"])

inc = has(apr.check({**GOOD, "cultivation_apparatus": "20C incubator"}),
          "cultivation_apparatus")
check("rearing in an incubator is flagged",
      inc["severity"] == "abolishes_result")
check("...naming the field cast during development",
      "throughout development" in inc["message"])
check("...and that it is a named cause of failed replication",
      "failed replication" in inc["message"])

starved = has(apr.check({**GOOD, "culture_starved": True}), "culture_starved")
check("a starved culture is flagged as sign-reversing",
      starved["severity"] == "reverses_result" and
      starved["state"] == "present")

# --- environment ------------------------------------------------------------
humid = has(apr.check({**GOOD, "humidity_percent": 62}), "relative_humidity")
check("humidity above 50% RH is flagged", humid is not None)
check("...with the source's own dry and humid averages",
      "35.4" in humid["message"] and "60.8" in humid["message"])
check("...and warning that a weak result is not a null result",
      "not evidence of no effect" in humid["message"])
check("humidity below the threshold passes",
      has(apr.check(GOOD), "relative_humidity") is None)

grad = has(apr.check({**GOOD, "thermal_gradient_c": 1.2}), "thermal_gradient")
check("a measured thermal gradient is flagged as a competing stimulus",
      "competing directional stimulus" in grad["message"])
check("...naming that worms thermotax to shallower gradients than they "
      "magnetotax", "far shallower" in grad["message"])
check("a small measured gradient passes",
      has(apr.check(GOOD), "thermal_gradient") is None)
check("an UNMEASURED gradient is raised, since the source measures every assay",
      "EVERY assay" in has(
          apr.check({k: v for k, v in GOOD.items()
                     if k != "thermal_gradient_c"}),
          "thermal_gradient")["message"])

# --- field verification ------------------------------------------------------
drift = has(apr.check({**GOOD, "field_measured_after_mT": 0.050}),
            "field_verification")
check("a field that drifted between measurements is flagged",
      drift["state"] == "drifted")
check("...naming that the animals were not in one condition",
      "not in one condition" in drift["message"])
check("...and a model cannot substitute for the measurement",
      "a model cannot see" in has(
          apr.check({k: v for k, v in GOOD.items()
                     if k != "field_measured_after_mT"}),
          "field_verification")["message"],
      "a drifting supply or a coil never switched on")

# --- ordering ---------------------------------------------------------------
mixed = apr.check({**GOOD, "life_stage": "L4", "humidity_percent": 62,
                   "plate_age_days": None})
check("findings are ordered worst first",
      mixed[0]["severity"] == "gate" and
      mixed[-1]["severity"] == "unquantified")
check("every finding names its source",
      all("Bainbridge" in f["source"] for f in mixed),
      "a checklist a student does not believe is one they click through")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("ASSAY_PROTOCOL_PASS")
