"""Head/tail identification on a synthetic worm whose head we know.

THE CHECK THAT MATTERS is the symmetry one. A sign error in a cue is
self-consistent - it answers "end 0" every time and every internal comparison
agrees with it - so a fixture with the head at end 0 cannot catch it. The same
worm is therefore run again with its spine reversed, and the answer must follow.
This is the same class of bug as the rotation-sign error in animal_frame, which
a round trip could not catch either.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import head_tail as ht   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("head/tail identification - regression\n")

H, W, N = 200, 400, 25
# Blunt at index 0, tapering to a fine whip at index 24 - a real worm's shape.
RADII = np.interp(np.arange(N), [0, 3, 15, 24], [5.0, 7.0, 6.5, 1.2])


def make_worm(shift=0.0, phase=0.0, wavelength=120.0, amp=18.0):
    """Spine ordered HEAD FIRST (index 0 = head) plus its filled mask."""
    x = np.linspace(60, 260, N) + shift
    y = 100 + amp * np.sin(2 * np.pi * x / wavelength + phase)
    spine = np.column_stack([x, y])
    mask = np.zeros((H, W), bool)
    yy, xx = np.mgrid[0:H, 0:W]
    for (px, py), r in zip(spine, RADII):
        mask |= (xx - px) ** 2 + (yy - py) ** 2 <= r ** 2
    return spine, mask


# The worm travels HEAD FIRST. Index 0 sits at low x, so travelling head first
# means translating toward NEGATIVE x.
frames = [make_worm(shift=-1.5 * k, phase=0.25 * k) for k in range(20)]
spines = [s for s, _ in frames]
masks = [m for _, m in frames]

# --- the cues one at a time ----------------------------------------------
wp = ht.width_profile(masks[0], spines[0])
check("a width profile is measured along the whole spine",
      np.isfinite(wp).all(), f"{np.nanmin(wp):.1f}-{np.nanmax(wp):.1f} px")
check("...and recovers the planted taper",
      wp[0] > 3 * wp[-1], f"head {wp[0]:.1f} px vs tail {wp[-1]:.1f} px")

t_score, t_info = ht.taper_cue(wp)
check("the taper cue points at the blunt end", t_score > 0.2,
      f"score {t_score:.3f}")

m_score, m_info = ht.motion_cue(spines)
check("the motion cue points at the leading end", m_score > 0.5,
      f"score {m_score:.3f} over {m_info['n_moving_frames']} moving frames")

w_score, w_info = ht.wiggle_cue(spines)
check("the wiggle cue is reported but marked as not weighted",
      w_info["weighted"] is False and "swimming" in w_info["why_not_weighted"])

# --- the decision ---------------------------------------------------------
call = ht.identify_head(spines, masks)
check("the head is identified", call["head_end"] == 0,
      f"head_end={call['head_end']}, confidence {call['confidence']}")
check("...with usable confidence", call["confidence"] > 0.35,
      f"{call['confidence']}")
check("...from both weighted cues", call["cues_that_voted"] == ["motion", "taper"])
check("...decided once for the track, not per frame",
      call["decided_once_per_track"] is True)
check("...and the wiggle cue did not vote", "wiggle" not in call["cues"])

# --- THE SYMMETRY CHECK ---------------------------------------------------
rev_spines = [s[::-1] for s in spines]
rev = ht.identify_head(rev_spines, masks)
check("reversing the spine reverses the answer", rev["head_end"] == 1,
      f"head_end={rev['head_end']}")
check("...with the same confidence, since it is the same worm",
      abs(rev["confidence"] - call["confidence"]) < 0.05,
      f"{rev['confidence']} vs {call['confidence']}")

# --- an animal that undulates WITHOUT translating -------------------------
# Not a still worm: the body wave moves the centroid every frame, easily past
# any per-frame speed threshold, while the animal goes nowhere. This is the
# case that would otherwise read the body wave as a direction of travel.
still = [make_worm(shift=0.0, phase=1.0 * k, wavelength=380.0, amp=26.0)
         for k in range(20)]
s_still = [s for s, _ in still]
ms, mi = ht.motion_cue(s_still)
check("an animal undulating in place gives no motion cue", ms is None,
      f"straightness {mi.get('straightness')}")
check("...saying it went nowhere rather than returning a number",
      "did not go anywhere" in mi["reason"])
check("...and the centroid did move, so a speed test alone would have passed",
      mi["path_length_px"] > 10.0,
      f"{mi['path_length_px']} px of path, {mi['net_displacement_px']} px net")

only_taper = ht.identify_head(s_still, [m for _, m in still])
check("taper alone still identifies the head", only_taper["head_end"] == 0)
check("...but a single unopposed cue is capped below certainty",
      only_taper["confidence"] <= 0.7, f"{only_taper['confidence']}")

# --- refusal --------------------------------------------------------------
nothing = ht.identify_head(s_still, masks=None)
check("with no masks and no movement the call is refused",
      nothing["refused"] is True and nothing["head_end"] is None)
check("...naming what would silently invert",
      "swap dorsal for ventral" in nothing["why"])

try:
    ht.apply_head_call(spines[0], None)
    check("ordering a spine with no head call is refused", False)
except ht.HeadTailError as exc:
    check("ordering a spine with no head call is refused", True)
    check("...naming the consequence", "reversed but look normal" in str(exc))

ordered = ht.apply_head_call(spines[0][::-1], 1)
check("apply_head_call puts the head first",
      np.allclose(ordered, spines[0]))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("HEAD_TAIL_PASS")
