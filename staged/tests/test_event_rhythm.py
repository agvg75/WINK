"""Rhythm metrics on event trains with known regularity.

The property that matters most is negative again: an interval must never be
formed across a confidence gap. A join would appear as a long interval and be
reported as a pause - an arrest that never happened.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import event_rhythm as er   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("event rhythm - regression\n")

FPS = 30.0
rng = np.random.default_rng(3)

# A metronomic 5 Hz pump train over 20 s. The period is a WHOLE number of
# frames (6 at 30 fps) on purpose: a period like 7.5 frames alternates 7, 8,
# 7, 8 once events land on integer frames, and that quantisation is real - it
# would show up as ~7% apparent variability in a perfectly regular animal.
# Testing the metric against a quantised fixture would measure the fixture.
period = FPS / 5.0
regular = np.round(np.arange(0, 600, period)).astype(int)
m = er.rhythm_metrics(regular, [(0, 599)], FPS)
check("a regular train recovers its 5 Hz rate", abs(m["rate_hz"] - 5.0) < 0.15,
      f"{m['rate_hz']} Hz")
check("...with near-zero variability", m["cv"] < 0.05, f"CV {m['cv']}")
check("...and no pauses", m["n_pauses"] == 0)

# the same rate, jittered
jitter = np.cumsum(rng.normal(period, period * 0.25, 80)).astype(int)
jitter = jitter[jitter < 600]
mj = er.rhythm_metrics(jitter, [(0, 599)], FPS)
check("a jittered train of the same rate has higher CV",
      mj["cv"] > m["cv"] * 3, f"{mj['cv']} vs {m['cv']}")
check("...and higher RMSSD", mj["rmssd_s"] > (m["rmssd_s"] or 0),
      f"{mj['rmssd_s']} vs {m['rmssd_s']}")

# a train with a genuine arrest
arrest = list(regular[regular < 200]) + list(regular[regular > 400])
ma = er.rhythm_metrics(arrest, [(0, 599)], FPS)
check("a genuine arrest is counted as a pause", ma["n_pauses"] >= 1,
      f"{ma['n_pauses']} pauses, longest {ma['longest_pause_s']} s")
check("...and excluded from the variability statistics",
      ma["pauses_excluded_from_variability"] is True and ma["cv"] < 0.3,
      f"CV {ma['cv']} despite the arrest")

# --- THE KEY ONE: a confidence gap must not become a pause ---------------
spans = [(0, 199), (400, 599)]
mg = er.rhythm_metrics(regular, spans, FPS)
check("no interval is formed across a confidence gap",
      mg["n_pauses"] == 0,
      f"{mg['n_pauses']} pauses across a 200-frame gap "
      f"(concatenating would invent one)")
check("...and the rate is unchanged by the gap",
      abs(mg["rate_hz"] - 5.0) < 0.15, f"{mg['rate_hz']} Hz")
check("...with events reported per span", len(mg["events_per_span"]) == 2)

# --- refusals ------------------------------------------------------------
try:
    er.rhythm_metrics(regular[:4], [(0, 599)], FPS)
    check("too few intervals is refused", False)
except er.RhythmError as exc:
    check("too few intervals is refused", True)
    check("...naming the count rather than returning numbers",
          "Only 3 intervals" in str(exc) or "intervals from" in str(exc))

# --- the ordinal guard ---------------------------------------------------
g = er.ordinal_guard([1, 1, 2, 3, 3, 3, 4], name="fibrosis grade")
check("an ordinal scale reports median and quartiles",
      g["median"] == 3 and "q1" in g and "q3" in g)
check("...and deliberately does NOT report a mean",
      g["mean_deliberately_not_reported"] is True and "mean" not in g)
check("...explaining that grade spacing is not equal",
      "assumes the distance" in g["why"])
check("...and keeps the full distribution", sum(g["distribution"].values()) == 7)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("EVENT_RHYTHM_PASS")

