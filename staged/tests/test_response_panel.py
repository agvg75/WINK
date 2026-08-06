"""Axis versus polarity, and everything else the stimulus might change.

Two traps, both of the same shape as the temporal-pooling one:

  A population perfectly ALIGNED to the field axis but split 50/50 on
  direction scores r=0 on a Rayleigh test. Indistinguishable from random,
  when in fact every animal is lying along the field line.

  A field that changes speed, turning or pausing without changing heading is
  acting on the animal without steering it. An orientation-only analysis
  records that as a null.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"),
                str(ROOT / "tools" / "orientation_assays"),
                str(ROOT / "tools" / "population_orientation")]

import numpy as np              # noqa: E402
import heading_analysis as ha   # noqa: E402
import response_panel as rp     # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("axis vs polarity and the response panel - regression\n")
RNG = np.random.default_rng(5)

# --- the axial trap ----------------------------------------------------------
bimodal = np.concatenate([RNG.normal(0, 12, 40), RNG.normal(180, 12, 40)])
ax = ha.axis_versus_polarity(bimodal)
check("a bimodal population is NOT directed", ax["polar_p"] > 0.05,
      f"polar r={ax['polar_r']:.3f}, p={ax['polar_p']:.2f}")
check("...which a Rayleigh test alone would report as no preference",
      ax["polar_r"] < 0.15)
check("...but it IS axially aligned",
      ax["axial_p"] < 0.001, f"axial r={ax['axial_r']:.2f}")
check("...and the verdict says so", ax["verdict"] == "axial_only")
check("...naming that the animals are not ignoring the field",
      "not ignoring the field" in ax["why"])
check("...and that bimodal orientation is a known outcome",
      "not a failed experiment" in ax["why"])
check("the axis is reported in [0,180), since an axis has no head",
      0 <= ax["axis_deg"] < 180, f"{ax['axis_deg']:.1f} deg")
check("...and recovers the true axis", abs(ax["axis_deg"]) < 8
      or abs(ax["axis_deg"] - 180) < 8, f"{ax['axis_deg']:.1f}")

directed = RNG.normal(40, 15, 60)
d = ha.axis_versus_polarity(directed)
check("a directed population reads as directed", d["verdict"] == "directed")
check("...with the polar mean near the true heading",
      abs(d["polar_deg"] - 40) < 8, f"{d['polar_deg']:.0f} deg")
check("...and is axially aligned too, as a directed population should be",
      d["axial_p"] < 0.05)

rand = ha.axis_versus_polarity(RNG.uniform(0, 360, 80))
check("random headings read as unoriented", rand["verdict"] == "unoriented")
check("...so axial statistics do not manufacture an axis from noise",
      rand["axial_p"] > 0.05, f"axial p={rand['axial_p']:.2f}")

# A 180-degree reversal is one axis with the polarity flipped, which is a
# different biological claim from two unrelated preferences.
early, late = RNG.normal(183, 12, 40), RNG.normal(3, 12, 40)
e, l = ha.axis_statistics if False else None, None
ax_e = ha.axial_statistics(early)
ax_l = ha.axial_statistics(late)
check("a 180-degree reversal keeps the SAME axis",
      abs(((ax_e["axis_deg"] - ax_l["axis_deg"] + 90) % 180) - 90) < 10,
      f"{ax_e['axis_deg']:.0f} vs {ax_l['axis_deg']:.0f} deg")
check("...while the polar means are opposite",
      abs(abs(ha._max_angular_spread(
          [float(np.degrees(np.angle(np.mean(np.exp(1j * np.radians(x))))))
           for x in (early, late)])) - 180) < 15,
      "same line, opposite direction along it")

# --- the response panel ------------------------------------------------------
def track(worm, heading, speed, n=120, dt=1.0, turn_sd=10.0, t0=0.0):
    rows, x, y = [], 0.0, 0.0
    for i in range(n):
        rows.append({"plate_id": "p", "worm_id": worm,
                     "time_s": t0 + i * dt, "x_mm": x, "y_mm": y})
        th = np.radians(heading + RNG.normal(0, turn_sd))
        x += speed * dt * np.cos(th)
        y += speed * dt * np.sin(th)
    return rows


straight = [r for i in range(5) for r in track(f"s{i}", 0, 0.05, turn_sd=5)]
wiggly = [r for i in range(5) for r in track(f"w{i}", 0, 0.05, turn_sd=60)]
sp = rp.panel(straight, field_deg=0.0)
wp = rp.panel(wiggly, field_deg=0.0)

check("speed is measured", rp.summarise(sp, "speed_mm_s")["mean"] > 0.04)
check("a wiggly path is more tortuous than a straight one",
      rp.summarise(wp, "tortuosity")["mean"] >
      rp.summarise(sp, "tortuosity")["mean"],
      f"{rp.summarise(wp, 'tortuosity')['mean']:.2f} vs "
      f"{rp.summarise(sp, 'tortuosity')['mean']:.2f}")
check("...and turns more often",
      rp.summarise(wp, "turn_rate_hz")["mean"] >
      rp.summarise(sp, "turn_rate_hz")["mean"])
check("...at the same speed, so speed alone would have missed it",
      abs(rp.summarise(wp, "speed_mm_s")["mean"] -
          rp.summarise(sp, "speed_mm_s")["mean"]) < 0.02,
      "klinokinesis without orthokinesis")
check("heading concentration is higher for the straight path",
      rp.summarise(sp, "heading_r")["mean"] >
      rp.summarise(wp, "heading_r")["mean"])

# --- taxis versus kinesis -----------------------------------------------------
kin = rp.kinesis_versus_taxis({"speed_mm_s": True, "turn_rate_hz": True,
                               "heading_r": False, "axial_r": False})
check("changed locomotion without steering reads as kinesis",
      kin["verdict"] == "kinesis")
check("...naming that an orientation-only analysis would call it a null",
      "recorded it as a null" in kin["why"])
tax = rp.kinesis_versus_taxis({"heading_r": True, "speed_mm_s": False,
                               "turn_rate_hz": False})
check("steering without changed locomotion reads as taxis",
      tax["verdict"] == "taxis")
both = rp.kinesis_versus_taxis({"heading_r": True, "speed_mm_s": True})
check("both together is flagged for confounding",
      both["verdict"] == "both" and
      "samples the field differently" in both["why"],
      "a slower animal samples the field differently")
check("nothing moving reads as no effect",
      rp.kinesis_versus_taxis({"heading_r": False})["verdict"] == "no_effect")

# --- multiplicity -------------------------------------------------------------
g = rp.required_threshold(14)
check("the required threshold tightens with the number of measures",
      g["required_p"] < 0.05 / 13)
check("...and states the chance of a false positive from nothing",
      g["chance_of_one_false_positive"] > 0.5,
      f"{g['chance_of_one_false_positive']:.0%} with 14 measures")
check("...and says a predicted finding stands on its own",
      "predicted in advance" in g["why"])
check("counting is on measures COMPUTED, not reported",
      "not everything reported" in rp.required_threshold.__doc__,
      "choosing what to show after seeing it is the same error")

# --- what the recording can support -------------------------------------------
cen = rp.available("centroid")
check("posture measures are unavailable from centroids",
      "body_curvature_deg" in cen["unavailable"] and
      "deep_bend_rate_hz" in cen["unavailable"])
check("...including body angle relative to the field",
      "body_field_angle_deg" in cen["unavailable"])
check("...and it names why that one matters",
      "travelling somewhere else" in cen["why"],
      "a body oriented to the field while the animal travels elsewhere")
check("spines unlock everything", rp.available("spine")["unavailable"] == [])
check("directional and non-directional measures are labelled",
      {v["kind"] for v in rp.MEASURES.values()} ==
      {"directional", "non_directional"})
check("every measure states the hypothesis it tests",
      all(v.get("hypothesis") for v in rp.MEASURES.values()))

# --- posture measures when spines exist ---------------------------------------
spined = []
for i, r in enumerate(track("sp0", 0, 0.05, n=60)):
    r["body_curvature_deg"] = 20.0 + 5 * np.sin(i / 3.0)
    r["body_angle_deg"] = 10.0
    r["deep_bend"] = (i % 20 == 0)
    spined.append(r)
res = rp.track_measures(spined, field_deg=0.0, tier="spine")
check("body curvature is measured when spines are present",
      res["body_curvature_deg"] > 15)
check("body angle relative to the field is measured",
      abs(res["body_field_angle_deg"] - 10) < 2,
      "independent of travel direction")
check("deep bends are counted", res["deep_bend_rate_hz"] > 0)
check("...and none of these appear at the centroid tier",
      "body_curvature_deg" not in rp.track_measures(spined, 0.0, "centroid"))

# --- honest gaps ---------------------------------------------------------------
sparse = [{"plate_id": "p", "worm_id": "x", "time_s": float(t),
           "x_mm": 0.0, "y_mm": 0.0} for t in range(4)]
m = rp.track_measures(sparse, field_deg=0.0)
check("a stationary track gives no tortuosity rather than zero",
      m["tortuosity"] is None,
      "zero displacement makes the ratio undefined, not one")
check("...and a summary counts what it could not compute",
      rp.summarise({"x": {0: m}}, "tortuosity")["missing"] == 1)
check("too short a track yields nothing at all",
      rp.track_measures(sparse[:2], 0.0) == {})

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("RESPONSE_PANEL_PASS")
