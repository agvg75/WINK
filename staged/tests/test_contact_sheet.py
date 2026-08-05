"""Many animals, one sheet, the broken ones first.

The three failures that actually occur are planted separately and each must
outrank a clean animal. A recording survives one bad frame; what has to surface
is a bad SECTION, a head flip, and a break in the travelling wave.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import contact_sheet as cs   # noqa: E402
import kymogram as ky        # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("contact sheet - regression\n")

NSEG, NF = 24, 400
seg = np.arange(NSEG)[:, None]
t = np.arange(NF)[None, :]


def clean():
    """A travelling body wave: diagonal banding in the kymogram."""
    return 35 * np.sin(2 * np.pi * (t / 22.0 - seg / 14.0))


good = clean()

bad_section = clean(); bad_section[:, 150:230] = np.nan     # 80 frames lost
flipped = clean(); flipped[:, 200:] *= -1                   # head flip midway
broken = clean()
rng = np.random.default_rng(3)
broken[:, 180:260] = rng.normal(0, 35, (NSEG, 80))          # wave -> noise
one_bad = clean(); one_bad[:, 199] = np.nan                 # a single frame

# --- the components ------------------------------------------------------
r = cs.wave_continuity(good)
check("a travelling wave has high frame-to-frame continuity",
      np.nanmedian(r) > 0.85, f"median r = {np.nanmedian(r):.3f}")
rf = cs.wave_continuity(flipped)
check("A HEAD FLIP SHOWS AS A STRONGLY NEGATIVE STEP, not merely a low one",
      np.nanmin(rf) < -0.8, f"min r = {np.nanmin(rf):.3f}")
check("...so a flip is distinguishable from a dropout, which goes toward zero",
      cs.score(flipped)["head_flips"] >= 1
      and cs.score(bad_section)["head_flips"] == 0,
      f"flip {cs.score(flipped)['head_flips']}, "
      f"section {cs.score(bad_section)['head_flips']}")

s = cs.score(bad_section)
check("a bad section is measured as a RUN, not just a total",
      s["longest_gap_frames"] == 80, f"{s['longest_gap_frames']} frames")
check("...and named as the worst component", s["worst"] == "bad section",
      s["worst"])
check("a scrambled wave registers as breaks or low continuity",
      cs.score(broken)["wave_breaks"] > 0
      or cs.score(broken)["median_continuity"] < 0.5,
      f"breaks {cs.score(broken)['wave_breaks']}, "
      f"continuity {cs.score(broken)['median_continuity']}")

# --- THE RANKING, which is what does the work at thumbnail size ----------
recs = {"clean_a": good, "clean_b": clean(), "one_bad_frame": one_bad,
        "SECTION": bad_section, "FLIP": flipped, "BROKEN": broken}
order = cs.rank(recs)
names = [d["name"] for d in order]
check("the three real failures rank above the clean animals",
      set(names[:3]) == {"SECTION", "FLIP", "BROKEN"},
      " > ".join(names))
check("...and a single bad frame does NOT outrank them",
      names.index("one_bad_frame") > 2,
      f"one_bad_frame is #{names.index('one_bad_frame') + 1} of {len(names)}")
check("...scoring barely above a clean recording, as it should",
      abs(cs.score(one_bad)["score"] - cs.score(good)["score"]) < 0.05,
      f"{cs.score(one_bad)['score']} vs {cs.score(good)['score']}")
check("every recording stays on the sheet, none excluded",
      len(order) == len(recs))
check("the score says it is a triage order, not a verdict",
      "not a verdict" in order[0]["triage_only"])

# --- the corrected reduction ---------------------------------------------
sm, step = ky.downsample(good, 100)
# NOTE the honest limit this exposed: compressing 4:1 leaves ~5 columns per
# 22-frame undulation cycle, so consecutive columns are a large phase step
# apart and frame-to-frame continuity necessarily falls. That is ALIASING of
# the wave, not a fault in the reduction - but it means a thumbnail squeezed
# below a few columns per cycle can no longer show a wave break at all.
per_cycle = 22 / step
check("compression is reported so aliasing is visible", step == 4,
      f"{step} frames per column, ~{per_cycle:.0f} columns per cycle")
check("the default reduction still shows an ordered wave, not speckle",
      np.nanmedian(cs.wave_continuity(sm)) > 0.35,
      f"continuity {np.nanmedian(cs.wave_continuity(sm)):.2f} at "
      f"{per_cycle:.0f} columns/cycle")
ex, _ = ky.downsample(good, 100, keep="extreme")
check("...and beats the old outlier-preserving default at showing the wave",
      np.nanmedian(cs.wave_continuity(sm))
      > np.nanmedian(cs.wave_continuity(ex)),
      f"structure {np.nanmedian(cs.wave_continuity(sm)):.2f} vs "
      f"extreme {np.nanmedian(cs.wave_continuity(ex)):.2f}")
check("a compressed bad SECTION is still visible",
      np.isnan(ky.downsample(bad_section, 100)[0]).any())
try:
    ky.downsample(good, 100, keep="nonsense")
    check("an unknown reduction is refused", False)
except ky.KymogramError:
    check("an unknown reduction is refused", True)

# --- the sheet ------------------------------------------------------------
import matplotlib
matplotlib.use("Agg")
fig, shown = cs.sheet(recs, columns=3, title="test")
check("the sheet draws every recording", len(shown) == len(recs))
check("...worst first", shown[0]["name"] in {"SECTION", "FLIP", "BROKEN"})

try:
    cs.sheet({})
    check("an empty sheet is refused", False)
except cs.SheetError:
    check("an empty sheet is refused", True)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("CONTACT_SHEET_PASS")
