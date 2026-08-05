"""The Fiji-free extractor, end to end on a synthetic recording.

The property that matters most is that a BAD FRAME STILL PRODUCES A ROW. A
frame silently dropped is indistinguishable downstream from a frame that was
never recorded, and every rate computed afterwards uses a denominator that
quietly shrank.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "rgbcamp"))
sys.path.insert(0, str(ROOT / "app"))

import extract_python as ep   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("Fiji-free RGBCaMP extraction - regression\n")

H, W, N, NF = 160, 320, 50, 30
FPS, UM = 5.0, 1.2


def _disc(mask, x, y, r):
    y0, y1 = max(int(y - r - 1), 0), min(int(y + r + 2), mask.shape[0])
    x0, x1 = max(int(x - r - 1), 0), min(int(x + r + 2), mask.shape[1])
    if y1 > y0 and x1 > x0:
        sy, sx = np.ogrid[y0:y1, x0:x1]
        mask[y0:y1, x0:x1] |= (sx - x) ** 2 + (sy - y) ** 2 <= r * r


states, masks, channels = [], [], []
for k in range(NF):
    x = np.linspace(40, 280, N)
    y = 80 + 16 * np.sin(2 * np.pi * x / 150.0 + 0.4 * k)
    spine = np.column_stack([x, y])
    m = np.zeros((H, W), bool)
    for px, py in spine:
        _disc(m, px, py, 8.0)
    # green brightens toward the TAIL, so an A-P gradient exists to check
    g = np.zeros((H, W), float)
    g[m] = 100.0
    xs = np.tile(np.arange(W, dtype=float), (H, 1))
    g[m] += xs[m] * 0.5
    states.append({"pts": spine, "provenance": "measured", "needs_help": 0})
    masks.append(m)
    channels.append({"green": g, "red": np.where(m, 60.0, 0.0)})

# one unusable frame in the middle
states[10] = {"pts": None, "provenance": "help", "needs_help": 1}
masks[10] = np.zeros((H, W), bool)

rows = ep.extract(states, masks, channels, fps=FPS, um_per_px=UM,
                  worm_id="w1", condition="test")
good = [r for r in rows if r["skip"] == 0]
bad = [r for r in rows if r["skip"] == 1]

check("every usable frame yields 2 rows per segment",
      len(good) == (NF - 1) * ep.N_SEG * 2,
      f"{len(good)} rows over {NF - 1} frames x {ep.N_SEG} segments x 2")
check("THE UNUSABLE FRAME STILL PRODUCES A ROW", len(bad) == 1,
      f"{len(bad)} skip row")
check("...carrying skip=1, found=0 and a reason",
      bad[0]["skip"] == 1 and bad[0]["found"] == 0
      and "no usable midline" in bad[0]["skip_reason"])
check("...and the frame index, so nothing downstream loses the denominator",
      bad[0]["frame"] == 10 and abs(bad[0]["time_s"] - 10 / FPS) < 1e-9)

check("segments run 0..23, one per myocyte",
      sorted({r["segment"] for r in good}) == list(range(24)))
check("both sides appear", {r["hemisegment"] for r in good} == {"left", "right"})
check("time is derived from fps", abs(good[-1]["time_s"]
                                      - good[-1]["frame"] / FPS) < 1e-9)

# --- the statistics the contract needs -----------------------------------
r0 = good[0]
for stat in ("min", "p10", "mean", "median", "p90", "max"):
    check(f"green_{stat} is present", f"green_{stat}" in r0)
check("roi_area_px is carried", "roi_area_px" in r0 and r0["roi_area_px"] > 0)
check("per-segment kinematics are carried",
      "seg_angle_deg" in r0 and "seg_curv_deg" in r0)

# --- the planted anterior-posterior gradient survives ---------------------
prof = {}
for r in good:
    prof.setdefault(r["segment"], []).append(r["green_mean"])
means = [np.mean(prof[k]) for k in range(24)]
check("the planted anterior-posterior gradient is recovered",
      means[0] < means[12] < means[23],
      f"{means[0]:.0f} -> {means[12]:.0f} -> {means[23]:.0f}")

# --- dorsal/ventral honesty ----------------------------------------------
check("without a ventral call the sides are left/right and dorsal_label empty",
      all(r["dorsal_known"] is False and r["dorsal_label"] == "" for r in good))
dv = [r for r in ep.extract(states, masks, channels, fps=FPS, um_per_px=UM,
                            ventral_sign=1, dorsal_known=True)
      if r["skip"] == 0]
check("with one, sides are dorsal/ventral and dorsal_label is filled",
      {r["hemisegment"] for r in dv} == {"dorsal", "ventral"}
      and all(r["dorsal_label"] == r["hemisegment"] for r in dv))

# --- the mismatch that would silently misalign everything ----------------
try:
    ep.extract(states, masks[:-1], channels, fps=FPS, um_per_px=UM)
    check("a length mismatch is refused", False)
except ep.ExtractError as exc:
    check("a length mismatch is refused", True)
    check("...naming that it would yield a plausible table describing nothing",
          "describes nothing" in str(exc))

# --- head check is advisory ----------------------------------------------
chk = ep.check_head_orientation(states, masks=masks)
check("the head orientation is checked independently", chk["checked"] is True,
      f"agrees={chk.get('agrees')}, confidence={chk.get('confidence')}")
check("...and explicitly not applied",
      "reported, not applied" in chk["advisory_only"])

# --- the parity comparison ------------------------------------------------
FIJI = ROOT / "tests" / "parity" / "golden_input" / "WormRGBCaMP_extracted_w1.csv"
if FIJI.exists():
    cmp_ = ep.compare_with_fiji(rows, FIJI, channel="green", stats=("mean",))
    check("a parity comparison against real Fiji output runs",
          cmp_["mean"]["compared"] is True,
          f"{cmp_['n_fiji_rows']} Fiji rows vs {cmp_['n_python_rows']} python, "
          f"profile r = {cmp_['mean']['profile_r']}")
    check("...and says a reversed profile means the head is on the wrong end",
          "numbered backwards" in cmp_["mean"]["verdict"]
          or "agree" in cmp_["mean"]["verdict"])
    check("...while stating exact agreement is not the target",
          "would be suspicious" in cmp_["note"])
else:                                                     # pragma: no cover
    check("the golden Fiji CSV is present to compare against", False)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("EXTRACT_PYTHON_PASS")
