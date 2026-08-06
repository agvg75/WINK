"""Animals leaving the field of view are censored, and they are the fast ones.

The property under test is that the bias is measured with its DIRECTION and
never corrected silently. A change in population heading over time and a change
in which animals remain produce the same plot; only the retention record tells
them apart.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import numpy as np       # noqa: E402
import censoring as cs   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("field-of-view censoring - regression\n")

BOUNDS = (0.0, 48.0, 0.0, 27.0)      # the real FOV: 47.8 x 26.9 mm


def walker(worm, speed_mm_s, t_end=3600.0, dt=10.0, x0=24.0, y0=13.5,
           heading=0.0):
    """An animal crawling from the centre until it leaves or time runs out."""
    rows, x, y, t = [], x0, y0, 0.0
    while t <= t_end:
        rows.append({"worm_id": worm, "time_s": t, "x_mm": x, "y_mm": y})
        if not (0 <= x <= 48 and 0 <= y <= 27):
            break
        x += speed_mm_s * dt * np.cos(np.radians(heading))
        y += speed_mm_s * dt * np.sin(np.radians(heading))
        t += dt
    return rows


# --- why a track ended -------------------------------------------------------
fast = walker("fast", 0.15)
ex = cs.exit_reason(fast, bounds_mm=BOUNDS)
check("a track ending at the frame edge is a departure",
      ex["reason"] == "left_field_of_view" and ex["informative"] is True)
check("...named as censoring, the animal continuing unobserved",
      "continued, unobserved" in ex["why"])

slow = walker("slow", 0.005)
ex2 = cs.exit_reason(slow, bounds_mm=BOUNDS, recording_end_s=3600.0,
                     end_margin_s=30.0)
check("a track ending with the recording is censored by design",
      ex2["reason"] == "recording_ended" and ex2["informative"] is True)
check("...naming that nothing about the animal caused it",
      "nothing about the animal caused it" in ex2["why"])

stub = [{"worm_id": "z", "time_s": float(t), "x_mm": 24.0, "y_mm": 13.5}
        for t in range(0, 200, 10)]
ex3 = cs.exit_reason(stub, bounds_mm=BOUNDS, recording_end_s=3600.0,
                     end_margin_s=30.0)
check("a track stopping mid-frame is a TRACKING failure, not a departure",
      ex3["reason"] == "lost_by_tracker" and ex3["informative"] is False)
check("...naming that it would attribute a software limit to biology",
      "software limit to biology" in ex3["why"],
      "the difference that keeps the statistics honest")
try:
    cs.exit_reason([{"worm_id": "a", "time_s": 0, "x_mm": 1, "y_mm": 1}],
                   bounds_mm=BOUNDS)
    check("a single detection has no ending to interpret", False)
except cs.CensoringError as exc:
    check("a single detection has no ending to interpret", True)
    check("...naming that it has no direction to have left in",
          "no direction to have left in" in str(exc))

# --- the bias, on a cohort where the fast ones leave -------------------------
cohort = []
for i in range(16):
    cohort += walker(f"f{i}", 0.10 + 0.01 * i, heading=0.0)     # leave early
for i in range(8):
    cohort += walker(f"s{i}", 0.0008 + 0.0001 * i, heading=90.0)  # stay
ret = cs.retention(cohort, bounds_mm=BOUNDS, window_s=600.0,
                   recording_end_s=3600.0, end_margin_s=30.0)

check("every track gets an exit reason", ret["n_tracks"] == 24,
      "16 that leave the frame, 8 that stay to the end")
check("both departures and design-censored endings are seen",
      ret["exit_reasons"].get("left_field_of_view", 0) > 0 and
      ret["exit_reasons"].get("recording_ended", 0) > 0)
first, last = ret["windows"][0], ret["windows"][max(ret["windows"])]
check("the cohort shrinks over the assay",
      last["fraction_remaining"] < first["fraction_remaining"],
      f"{first['fraction_remaining']:.0%} -> {last['fraction_remaining']:.0%}")
check("the survivors are slower than the departed",
      last["speed_ratio_present_over_departed"] < 1.0,
      f"ratio {last['speed_ratio_present_over_departed']:.2f}")

rep = cs.bias_report(ret)
check("the bias is reported with its size", "worst_speed_ratio" in rep)
check("...and its direction stated in words",
      any("survivors are" in w and "slower" in w for w in rep["warnings"]))
check("...naming that time and attrition produce the same plot",
      any("produce the same plot" in w for w in rep["warnings"]),
      "nothing in the headings distinguishes them")
check("a heavily depleted final window is called out",
      any("minority of the cohort" in w for w in rep["warnings"]))
check("...naming that the minority selected itself",
      any("selected by their own behaviour" in w for w in rep["warnings"]))

# --- nothing is corrected silently ------------------------------------------
check("no correction is applied",
      "measured, not corrected" in rep["no_correction_applied"])
check("...naming why reweighting would beg the question",
      "precisely what is in doubt" in rep["no_correction_applied"],
      "it would assume the departed resemble the slow animals that stayed")

# --- the opposite bias is distinguished, not lumped in -----------------------
odd = []
for i in range(10):
    odd += walker(f"q{i}", 0.0008, heading=90.0)[:12]   # slow, cut short
for i in range(10):
    odd += walker(f"r{i}", 0.002, heading=90.0)        # faster, stay longer
rep2 = cs.bias_report(cs.retention(odd, bounds_mm=BOUNDS, window_s=300.0,
                                   recording_end_s=3600.0, end_margin_s=30.0))
check("survivors being FASTER is flagged as a different problem",
      any("opposite of leaving-the-frame" in w for w in rep2["warnings"])
      or any("tracking failure" in w for w in rep2["warnings"]),
      "a tracker that loses fast animals would look like this")

# --- a tracker failing a lot is not censoring --------------------------------
broken = []
for i in range(10):
    broken += [{"worm_id": f"b{i}", "time_s": float(t),
                "x_mm": 24.0, "y_mm": 13.5} for t in range(0, 150, 10)]
rep3 = cs.bias_report(cs.retention(broken, bounds_mm=BOUNDS, window_s=600.0,
                                   recording_end_s=3600.0, end_margin_s=30.0))
check("mass mid-frame track loss is reported separately from departure",
      any("tracking failure rather" in w for w in rep3["warnings"]))
check("...naming that censoring assumes departures are informative",
      any("assume departures are informative" in w for w in rep3["warnings"]))

# --- retention cannot rise for a closed cohort -------------------------------
# Real data gave 0.14 -> 0.06 -> 0.21 -> 0.40 -> 0.23, which is impossible for
# animals that only ever leave. It meant one animal was becoming several.
frag = list(walker("a", 0.0008, heading=90.0))
for i in range(20):                      # fragments appearing mid-assay
    frag += [{"worm_id": f"frag{i}", "time_s": float(t), "x_mm": 24.0,
              "y_mm": 13.5} for t in range(1800, 1900, 10)]
rep5 = cs.bias_report(cs.retention(frag, bounds_mm=BOUNDS, window_s=600.0,
                                   recording_end_s=3600.0, end_margin_s=30.0))
check("retention that rises is flagged as impossible",
      any("closed cohort cannot grow" in w for w in rep5["warnings"]),
      "nobody comes back")
check("...naming the two explanations",
      any("counted as several" in w and "entering a frame" in w
          for w in rep5["warnings"]))
check("...and withdrawing trust from the speed comparison",
      any("fragments rather than animals" in w for w in rep5["warnings"]))

# --- a clean cohort raises nothing -------------------------------------------
steady = []
for i in range(12):
    steady += walker(f"c{i}", 0.0008 + 0.00005 * i, heading=90.0)
rep4 = cs.bias_report(cs.retention(steady, bounds_mm=BOUNDS, window_s=600.0,
                                   recording_end_s=3600.0, end_margin_s=30.0))
check("a cohort that all stays raises no bias warning",
      rep4["warnings"] == [], str(rep4["warnings"]))

try:
    cs.retention([{"worm_id": "a", "time_s": 0, "x_mm": 1, "y_mm": 1}],
                 bounds_mm=BOUNDS)
    check("retention from single detections is refused", False)
except cs.CensoringError:
    check("retention from single detections is refused", True)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("CENSORING_PASS")
