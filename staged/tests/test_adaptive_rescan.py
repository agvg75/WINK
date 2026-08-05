"""Two-pass detection, on a train where we know which events were merged away.

The decisive fixture reproduces the actual defect: pboc_engine merges events
closer than 5 s, which FUSES two intervals into one long one. If the method
works, the merged pairs are exactly the windows it flags.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import adaptive_rescan as ar   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("adaptive rescan - regression\n")

FPS = 10.0
PERIOD = 45 * FPS                      # a 45 s defecation cycle, in frames
truth = np.arange(0, 30 * PERIOD, PERIOD).astype(int)

# The defect: three pairs are merged, the second of each pair disappearing.
MERGED_AWAY = [truth[5], truth[12], truth[20]]
observed = [int(e) for e in truth if e not in MERGED_AWAY]

d = ar.suspect_intervals(observed, FPS)
check("the animal's own period is recovered",
      abs(d["period_s"] - 45.0) < 1.0, f"{d['period_s']} s")
check("exactly the fused intervals are flagged", d["n_suspect"] == 3,
      f"{d['n_suspect']} suspect of {d['n_intervals']}")
check("...each expecting one missing event",
      all(w["expected_missing"] == 1 for w in d["suspect"]))
check("...and each spanning about two periods",
      all(1.8 < w["gap_periods"] < 2.2 for w in d["suspect"]),
      f"{[w['gap_periods'] for w in d['suspect']]}")
check("the period is taken from the median, and says why",
      "would be dragged up by exactly the problem" in d["why_median"])


def perfect_rescanner(a, b):
    """A second pass that finds what the first one merged away."""
    return [e for e in MERGED_AWAY if a < e < b]


rep = ar.rescan(observed, FPS, perfect_rescanner)
check("rescanning recovers the merged events", rep["recovered"] == 3,
      f"{rep['events_before']} -> {rep['events_after']}")
check("...restoring the full train",
      rep["corrected_events"] == sorted(truth.tolist()))
check("...and nothing is left unresolved", rep["n_unresolved"] == 0)
check("the audit states what changed", "recovered 3 events" in rep["audit"])
check("...and warns against reporting it silently",
      "indistinguishable from a phenotype" in rep["not_silent"])

# --- a metronomic animal must be untouched -------------------------------
calls = []


def counting_rescanner(a, b):
    calls.append((a, b))
    return []


clean = ar.rescan([int(e) for e in truth], FPS, counting_rescanner)
check("A METRONOMIC ANIMAL IS NEVER RESCANNED", not calls,
      f"{len(calls)} windows opened")
check("...so nothing about it can change",
      clean["events_after"] == clean["events_before"] == len(truth))
check("...which is what makes two passes safe across genotypes",
      "loosening a global threshold would not be"
      in clean["unrescanned_animals_unchanged"])

# --- a genuine arrest is not credited with forty missed pumps -------------
arrest = [int(e) for e in truth if not (10 * PERIOD < e < 20 * PERIOD)]
capped = ar.suspect_intervals(arrest, FPS, max_multiple=3)
check("a genuine arrest is capped, not credited with every missing cycle",
      max(w["expected_missing"] for w in capped["suspect"]) <= 3,
      f"max expected_missing {max(w['expected_missing'] for w in capped['suspect'])}")

# --- a rescanner that re-finds the endpoints must not inflate ------------
def lazy_rescanner(a, b):
    return [a, b]              # the events that bound the window, already known


rep2 = ar.rescan(observed, FPS, lazy_rescanner)
check("re-finding the window's own endpoints recovers nothing",
      rep2["recovered"] == 0, f"{rep2['recovered']} recovered")

# --- refusals -------------------------------------------------------------
try:
    ar.suspect_intervals([0, 10, 20], FPS)
    check("too few events is refused", False)
except ar.RescanError as exc:
    check("too few events is refused", True)
    check("...naming that it would invent events",
          "would invent events" in str(exc))

# --- THE GENOTYPE CHECK ---------------------------------------------------
wt = [ar.rescan([int(e) for e in truth], FPS, lambda a, b: []) for _ in range(4)]
dys = [ar.rescan(observed, FPS, perfect_rescanner) for _ in range(4)]
ev = ar.recovery_rate_by_group(wt + dys, ["WT"] * 4 + ["DYS"] * 4)
check("uneven recovery between genotypes is detected",
      ev["uneven"] is True,
      f"WT {ev['by_group']['WT']['recovery_fraction']}, "
      f"DYS {ev['by_group']['DYS']['recovery_fraction']}")
check("...and named as detection rather than biology",
      "detection rather than" in ev["interpretation"])
even = ar.recovery_rate_by_group(wt + wt, ["WT"] * 4 + ["DYS"] * 4)
check("even recovery is reported as even", even["uneven"] is False)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("ADAPTIVE_RESCAN_PASS")
