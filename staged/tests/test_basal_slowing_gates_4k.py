"""A 4K frame, segmented for real, against the old gates and the new ones.

test_basal_slowing_gates.py checks the arithmetic. This checks the thing the
arithmetic was about: take a 3840x2160 frame holding six adult-sized animals
and forty specks of debris, segment it with the same OpenCV call the tracker
uses, and count what each set of gates admits.

The old fixed band of 40-2500 px does not merely mis-sort them. It admits
every speck and rejects every animal - an exact inversion - and the tracker
reports a plate full of worms without raising anything.

Scale is 2.5 um/px, which is an ordinary 4K recording of a plate. At that
scale an adult of 1150 x 80 um covers 460 x 32 px, or 14,720 px.
"""
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "tools" / "basal_slowing")]

import basal_slowing as bs   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("basal slowing area gates - 4K fixture\n")

FRAME_H, FRAME_W = 2160, 3840
UM_PER_PX = 2.5
WORM_LEN_PX = int(bs.WORM_LENGTH_UM / UM_PER_PX)     # 460
WORM_WIDTH_PX = int(bs.WORM_WIDTH_UM / UM_PER_PX)    # 32
N_WORMS, N_DEBRIS = 6, 40
OLD_MIN, OLD_MAX = 40, 2500


def build_frame():
    """Six animals and forty specks on an otherwise empty 4K field."""
    mask = np.zeros((FRAME_H, FRAME_W), np.uint8)
    worm_centres = []
    for i in range(N_WORMS):
        cx = 500 + (i % 3) * 1300
        cy = 600 + (i // 3) * 900
        half = WORM_LEN_PX // 2
        # A gentle arc, so the object is worm-shaped rather than a bar.
        pts = np.array([[cx - half, cy], [cx, cy - 70], [cx + half, cy]],
                       np.int32)
        cv2.polylines(mask, [pts], False, 255, WORM_WIDTH_PX)
        worm_centres.append((cx, cy))

    rng = np.random.default_rng(4)
    placed = 0
    while placed < N_DEBRIS:
        x = int(rng.integers(60, FRAME_W - 60))
        y = int(rng.integers(60, FRAME_H - 60))
        if any(abs(x - cx) < WORM_LEN_PX and abs(y - cy) < 220
               for cx, cy in worm_centres):
            continue
        # Radius 4-25 px is 50-1963 px of area: squarely inside the old band.
        cv2.circle(mask, (x, y), int(rng.integers(4, 26)), 255, -1)
        placed += 1
    return mask


def areas_of(mask):
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    return np.array([stats[i, cv2.CC_STAT_AREA] for i in range(1, count)])


def kept(areas, lo, hi):
    return areas[(areas >= lo) & (areas <= hi)]


mask = build_frame()
areas = areas_of(mask)
adult_px = bs.WORM_TYPICAL_AREA_UM2 / (UM_PER_PX ** 2)
worms = areas[areas > adult_px * 0.4]
debris = areas[areas <= adult_px * 0.4]

check("the fixture segments into the objects it was built from",
      len(worms) == N_WORMS and len(debris) == N_DEBRIS,
      f"{len(worms)} worms, {len(debris)} debris, {len(areas)} objects")
check("...with animals the size an adult is at 2.5 um/px",
      abs(float(np.median(worms)) - adult_px) < adult_px * 0.45,
      f"median {np.median(worms):,.0f} px against {adult_px:,.0f} expected")
check("...and debris inside the old fixed band, as real specks are",
      all(OLD_MIN <= a <= OLD_MAX for a in debris),
      f"{debris.min():,} to {debris.max():,} px")

# --- the old gates, on this frame --------------------------------------------
old_worms = kept(worms, OLD_MIN, OLD_MAX)
old_debris = kept(debris, OLD_MIN, OLD_MAX)
check("the old 40-2500 px gates reject EVERY animal",
      len(old_worms) == 0,
      f"an adult is {adult_px:,.0f} px against a {OLD_MAX:,} px ceiling")
check("...while admitting EVERY speck of debris",
      len(old_debris) == N_DEBRIS,
      f"{len(old_debris)} of {N_DEBRIS} - the tracker fills with noise")
check("...so the tool tracks the exact complement of what it should",
      len(old_worms) == 0 and len(old_debris) == len(debris),
      "it does not fail; it silently tracks the wrong objects")

# --- the gates this recording implies ----------------------------------------
g = bs.area_gates_for(UM_PER_PX)
new_worms = kept(worms, g["min_area"], g["max_area"])
new_debris = kept(debris, g["min_area"], g["max_area"])
check("gates computed from the scale admit every animal",
      len(new_worms) == N_WORMS,
      f"{len(new_worms)} of {N_WORMS} in {g['min_area']:,}-{g['max_area']:,} px")
check("...and reject every speck",
      len(new_debris) == 0, f"{len(new_debris)} debris admitted")
check("...without needing a warning", g["warnings"] == [])

# --- and with no calibration at all ------------------------------------------
f = bs.area_gates_for(0, frame_shape=(FRAME_H, FRAME_W))
fb_worms = kept(worms, f["min_area"], f["max_area"])
fb_debris = kept(debris, f["min_area"], f["max_area"])
check("falling back to the frame size still admits every animal",
      len(fb_worms) == N_WORMS,
      f"{len(fb_worms)} of {N_WORMS} in {f['min_area']:,}-{f['max_area']:,} px")
check("...and rejects the large majority of debris",
      len(fb_debris) <= N_DEBRIS * 0.15,
      f"{len(fb_debris)} of {N_DEBRIS} admitted, against all {N_DEBRIS} "
      f"under the old fixed gates")
check("...but is measurably weaker than a real calibration, as it warns",
      len(fb_debris) >= len(new_debris),
      "0.1% of the frame under-estimates an adult at 2.5 um/px by about "
      "1.8x, so the floor sits lower than a calibration would put it and "
      "the biggest specks clear it")
check("...while warning that it is a framing assumption",
      any("not a measurement" in w for w in f["warnings"]))

# --- a multiplier moves the band without reintroducing pixel counts ----------
loose = bs.area_gates_for(UM_PER_PX, min_area_mult=0.5, max_area_mult=1.5)
check("a multiplier widens the band it was given",
      loose["min_area"] < g["min_area"] and loose["max_area"] > g["max_area"],
      f"{loose['min_area']:,}-{loose['max_area']:,} px")
check("...and still admits every animal",
      len(kept(worms, loose["min_area"], loose["max_area"])) == N_WORMS)

# --- the caller that actually shipped the bug --------------------------------
# The library has computed gates from um_per_px since backlog #12, but the
# GUI passed 40 / 2500 / 60 as explicit overrides on every run, so the fix
# never reached a single student. That is the regression to hold down.
tool_src = (ROOT / "tools" / "basal_slowing"
            / "basal_slowing_tool.py").read_text(encoding="utf-8")
check("the GUI no longer ships the old pixel defaults",
      'value="40"' not in tool_src and 'value="2500"' not in tool_src
      and 'value="60"' not in tool_src,
      "these were StringVar defaults passed straight into analyze()")
check("...and no longer passes raw pixel gates to analyze",
      '"min_area":' not in tool_src and '"max_area":' not in tool_src
      and '"max_link_px":' not in tool_src)
check("...passing multipliers instead",
      '"min_area_mult":' in tool_src and '"max_area_mult":' in tool_src
      and '"max_link_mult":' in tool_src)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("BASAL_SLOWING_GATES_4K_PASS")
