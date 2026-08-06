"""Area gates must come from the worm's physical size, not from fixed pixels.

Backlog #12. The gates were min_area=40, max_area=2500 in PIXELS, while this
lab's recordings span more than an order of magnitude of scale. Those numbers
admit an adult worm only between about 20 and 10 um/px. At 2.5 um/px - an
ordinary 4K recording of a plate - an adult covers 14,720 px against a 2,500
px ceiling, so every animal is rejected and only debris in the 40-2500 band is
tracked. The tool does not fail; it tracks the wrong objects.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "tools" / "basal_slowing")]

import basal_slowing as bs   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def _raises(call, exc=ValueError):
    try:
        call()
    except exc:
        return True
    except Exception:
        return False
    return False


print("basal slowing area gates - regression\n")

ADULT_UM2 = 92_000


def adult_px(scale):
    return ADULT_UM2 / (scale * scale)


# --- the bug, demonstrated ---------------------------------------------------
old_min, old_max = 40, 2500
broken = [s for s in (50.0, 20.0, 10.0, 5.0, 2.5, 1.0)
          if not old_min <= adult_px(s) <= old_max]
check("the old fixed gates reject an adult worm at most scales",
      len(broken) >= 4, f"fails at {broken} um/px")
check("...including 2.5 um/px, an ordinary 4K plate recording",
      2.5 in broken,
      f"an adult is {adult_px(2.5):,.0f} px against a 2500 px ceiling")

# --- derived gates track the scale -------------------------------------------
for scale in (50.0, 20.0, 10.0, 5.0, 2.5, 1.0):
    g = bs.area_gates_for(scale)
    inside = g["min_area"] <= adult_px(scale) <= g["max_area"]
    check(f"an adult falls inside the derived gates at {scale:g} um/px",
          inside,
          f"{adult_px(scale):,.0f} px in {g['min_area']}-{g['max_area']}")

check("gates scale with the square of the resolution",
      bs.area_gates_for(5.0)["max_area"] ==
      4 * bs.area_gates_for(10.0)["max_area"],
      "halving um/px quadruples the pixel area")

# --- linking distance had the same defect ------------------------------------
fine = bs.area_gates_for(2.5)["max_link_px"]
coarse = bs.area_gates_for(50.0)["max_link_px"]
check("the link distance also tracks the scale", fine > coarse,
      f"{fine} px at 2.5 um/px vs {coarse} px at 50")
check("...both representing the same physical distance",
      abs(fine * 2.5 - coarse * 50.0) < 60,
      "60 px was 150 um at one scale and 3 mm at another")

# --- tuning is a multiplier, not a pixel count -------------------------------
base = bs.area_gates_for(2.5)
g = bs.area_gates_for(2.5, min_area_mult=0.5, max_area_mult=2.0,
                      max_link_mult=3.0)
check("a multiplier scales the computed gate",
      (g["min_area"], g["max_area"], g["max_link_px"]) ==
      (round(base["min_area"] * 0.5), round(base["max_area"] * 2.0),
       round(base["max_link_px"] * 3.0)),
      "someone who tuned gates for a rig keeps that judgement...")
check("...expressed in a form that survives a change of scale",
      bs.area_gates_for(5.0, max_area_mult=2.0)["max_area"] ==
      2 * bs.area_gates_for(5.0)["max_area"],
      "the same 2.0x means the same thing at any magnification")
check("...and the adjustment is recorded",
      set(g["adjusted"]) == {"min_area", "max_area", "max_link_px"})
check("...while the unadjusted values are still reported for comparison",
      g["derived"]["max_area"] == base["derived"]["max_area"])
check("an unadjusted call records no adjustment", base["adjusted"] == [])

check("a multiplier of zero or less is refused",
      _raises(lambda: bs.area_gates_for(2.5, min_area_mult=0)),
      "it would collapse the gate rather than loosen it")

# --- raw pixel gates are gone from the API -----------------------------------
_sig = __import__("inspect").signature(bs.area_gates_for)
check("area_gates_for no longer accepts raw pixel counts",
      not {"min_area", "max_area", "max_link_px"} & set(_sig.parameters),
      "a pixel count is only correct at the magnification it was written for")

# --- the warning that would have caught this in the first place --------------
# Reproduce the old 40/2500 px band as multipliers of what 2.5 um/px implies.
bad = bs.area_gates_for(
    2.5,
    min_area_mult=40 / base["derived"]["min_area"],
    max_area_mult=2500 / base["derived"]["max_area"])
check("supplying the old fixed gates now WARNS",
      any("OUTSIDE the gates" in w for w in bad["warnings"]))
check("...naming that only wrong-sized objects would be tracked",
      any("only objects of the wrong size tracked" in w
          for w in bad["warnings"]))
check("...and identifying it as the historical failure",
      any("40-2500" in w for w in bad["warnings"]))
check("sensible derived gates raise nothing",
      bs.area_gates_for(10.0)["warnings"] == [])

# --- a resolution problem is not a threshold problem -------------------------
coarse_g = bs.area_gates_for(400.0)
check("at absurdly coarse scale the gates say so",
      any("magnification problem" in w for w in coarse_g["warnings"]),
      "an adult is a couple of pixels; no threshold helps")
check("...and the floor never drops below a usable blob",
      coarse_g["min_area"] >= bs.MIN_USABLE_AREA_PX)

# --- an uncalibrated recording falls back to the frame, not to 40/2500 -------
fallback = bs.area_gates_for(0, frame_shape=(2160, 3840))
check("with no scale, the gates come from the frame size",
      fallback["basis"] == "frame_size",
      f"{fallback['min_area']:,}-{fallback['max_area']:,} px on 4K")
check("...bracketing the adult that framing implies",
      fallback["min_area"] <= fallback["expected_adult_px"]
      <= fallback["max_area"])
check("...and saying out loud that it is an assumption",
      any("not a measurement" in w for w in fallback["warnings"]),
      "a framing assumption must never read as a calibration")
check("...still far above the old 2500 px ceiling on a 4K frame",
      fallback["max_area"] > 2500 * 5,
      f"{fallback['max_area']:,} px vs 2500")
small = bs.area_gates_for(0, frame_shape=(480, 640))
check("the frame fallback tracks the sensor", fallback["max_area"] >
      small["max_area"] * 10,
      f"4K {fallback['max_area']:,} px vs VGA {small['max_area']:,} px")
check("a real calibration is preferred over the frame when both are given",
      bs.area_gates_for(2.5, frame_shape=(480, 640))["basis"] ==
      "calibration")

# --- refusals -----------------------------------------------------------------
try:
    bs.area_gates_for(0)
    check("neither a scale nor a frame shape is refused", False)
except ValueError as exc:
    check("neither a scale nor a frame shape is refused", True)
    check("...naming that fixed pixel gates are what this replaces",
          "narrow band of magnifications" in str(exc))
check("a nonsensical frame shape is refused",
      _raises(lambda: bs.area_gates_for(0, frame_shape=(0, 640))))

# --- the signature no longer carries the bad defaults ------------------------
import inspect   # noqa: E402
sig = inspect.signature(bs.analyze)
check("analyze takes multipliers, defaulting to the computed gate",
      sig.parameters["min_area_mult"].default == 1.0 and
      sig.parameters["max_area_mult"].default == 1.0 and
      sig.parameters["max_link_mult"].default == 1.0,
      "1.0 means 'use what the recording implies'")
check("...and no longer accepts raw pixel gates at all",
      not {"min_area", "max_area", "max_link_px"} & set(sig.parameters),
      "the GUI used to pass 40/2500/60 here on every single run")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("BASAL_SLOWING_GATES_PASS")
