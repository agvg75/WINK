"""Changes that defy biology: large, unprecedented, and spatially alone.

The decisive pair of fixtures is a REAL vigorous bend against an ARTEFACT of
the same magnitude. Both are large. Only the artefact is spatially alone, and a
detector that cannot tell them apart is useless on an animal that actually
moves.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import implausible as im   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("implausible change detection - regression\n")

NSEG, NF = 24, 300
seg = np.arange(NSEG)[:, None]
t = np.arange(NF)[None, :]
base = 35 * np.sin(2 * np.pi * (t / 22.0 - seg / 14.0))

# (a) an ARTEFACT: one segment jumps 60 deg, alone
artefact = base.copy()
artefact[12, 150:] += 60.0

# (b) REAL BEHAVIOUR of the same size: a sharp bend involving the whole region,
# which is what a body actually does - it is continuous.
behaviour = base.copy()
for s in range(9, 16):
    behaviour[s, 150:] += 60.0 * np.exp(-((s - 12) ** 2) / 8.0)

# --- clause 3 does the work ----------------------------------------------
fa = im.find(artefact, absolute_min=25.0)
fb = im.find(behaviour, absolute_min=25.0)
check("a lone 60 degree jump is flagged", fa["n_events"] >= 1,
      f"{fa['n_events']} events")
check("A COHERENT BEND OF THE SAME SIZE IS NOT",
      fb["n_events"] == 0,
      f"{fb['n_events']} events - magnitude alone would have flagged both")
check("...and the flagged one names its neighbours as quiet",
      fa["events"][0]["neighbour_support"] < 0.45,
      f"neighbours moved {fa['events'][0]['neighbour_support']:.0%} as much")
check("the three clauses are stated", "coherent front" in fa["three_clauses"])

# --- clause 2: per segment, against its own history ----------------------
# The head sweeps hard all recording long. That is its normal, and a threshold
# set for the midbody would condemn it in every frame.
busy = base.copy()
rng = np.random.default_rng(2)
busy[0:4, :] += rng.normal(0, 30, (4, NF))
fh = im.find(busy, absolute_min=25.0)
head_hits = [e for e in fh["events"] if e["segment"] < 4]
check("a habitually active segment is not condemned for being active",
      len(head_hits) <= 2, f"{len(head_hits)} events in the busy head")

# The same absolute jump in a QUIET segment is unprecedented and is caught.
quiet = base.copy()
quiet[20, 200] += 60.0
check("...while the same jump in a quiet segment is caught",
      any(e["segment"] == 20 for e in im.find(quiet, absolute_min=25.0)["events"]))

# --- robustness: the artefact must not hide itself -----------------------
many = base.copy()
for f in (60, 61, 62):
    many[12, f] += 80.0
check("repeated large steps do not inflate the scale and hide themselves",
      im.find(many, absolute_min=25.0)["n_events"] >= 2,
      "MAD does not move the way a standard deviation would")

# --- gaps must not manufacture steps -------------------------------------
gappy = base.copy()
gappy[:, 100:140] = np.nan
d = im.step_sizes(gappy)
check("a change measured ACROSS a gap is not scored as a change",
      np.all(np.isnan(d[:, 99])) and np.all(np.isnan(d[:, 139])),
      "otherwise every dropout produces two huge false steps at its edges")
check("...so a dropout alone raises nothing",
      im.find(gappy, absolute_min=25.0)["n_events"] == 0)

# --- the absolute floor ---------------------------------------------------
still = np.zeros((NSEG, NF)) + rng.normal(0, 0.02, (NSEG, NF))
still[10, 150] += 0.4
check("without a floor, a still animal generates findings",
      im.find(still)["n_events"] > 0)
check("...and the report says a floor was not set",
      "Set a floor" in im.find(still)["no_absolute_floor"])
check("with a floor, it does not",
      im.find(still, absolute_min=25.0)["n_events"] == 0)

# --- sections, not frames -------------------------------------------------
burst = base.copy()
burst[12, 150:158] += 70.0
sec = im.sections(im.find(burst, absolute_min=25.0)["events"])
check("a burst is reported as ONE section, not many findings",
      len(sec) <= 2, f"{len(sec)} sections from {im.find(burst, absolute_min=25.0)['n_events']} events")
check("...carrying the span and the segments that objected",
      "start_frame" in sec[0] and sec[0]["segments"] == [12])

# --- the queue across panels ---------------------------------------------
q = im.review_queue({"curvature": artefact, "green dorsal": base},
                    absolute_min=25.0)
check("the queue says WHICH panel objected",
      q["n_sections"] >= 1 and q["sections"][0]["panel"] == "curvature")
check("...and is built for cutting montage clips",
      "cut a clip with the tracking overlaid" in q["for_montage"])

# --- brightness uses the same three clauses ------------------------------
bright = np.full((NSEG, NF), 120.0) + rng.normal(0, 3, (NSEG, NF))
bright[7, 180:] += 90.0                    # one myocyte jumps, alone
fbr = im.find(bright, absolute_min=40.0)
check("the same detector works on brightness",
      any(e["segment"] == 7 for e in fbr["events"]),
      f"{fbr['n_events']} events")

try:
    im.find(np.zeros((4, 2)))
    check("too few frames is refused", False)
except im.ImplausibleError:
    check("too few frames is refused", True)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("IMPLAUSIBLE_PASS")
