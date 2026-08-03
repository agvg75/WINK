"""Regression tests for app/scale_calibration.py, especially
detect_scale_bar_px - validated against real confocal exports on disk, not
just synthetic fixtures, since the whole point is separating a real printed
bar from real tissue signal and real text, not from an idealized shape.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import scale_calibration as sc

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("scale_calibration - regression\n")

# ---------------------------------------------------------------------------
# scalebar_um_per_px / worm_length_check: unchanged, mechanical sanity.
# ---------------------------------------------------------------------------
check("scalebar_um_per_px: mm converts to um correctly",
      abs(sc.scalebar_um_per_px(100, 1.0, "mm") - 10.0) < 1e-9)
check("scalebar_um_per_px: um unit used directly",
      abs(sc.scalebar_um_per_px(10, 5.0, "um") - 0.5) < 1e-9)

# ---------------------------------------------------------------------------
# detect_scale_bar_px: synthetic cases with known ground truth.
# ---------------------------------------------------------------------------
blank = np.zeros((200, 300), dtype=np.uint8)
check("detect_scale_bar_px: a blank frame finds nothing",
      sc.detect_scale_bar_px(blank) is None)

with_bar = np.zeros((200, 300), dtype=np.uint8)
with_bar[180, 20:100] = 255  # a clean 80px solid line, fully inside the
                              # default bottom-left search margin (0.35*300=105)
result = sc.detect_scale_bar_px(with_bar)
check("detect_scale_bar_px: finds a clean synthetic bar",
      result is not None and abs(result["length_px"] - 80) < 1e-6, result)
check("detect_scale_bar_px: reports the bottom_left corner",
      result is not None and result["corner"] == "bottom_left")
check("detect_scale_bar_px: solidity is 1.0 for a perfectly clean line",
      result is not None and abs(result["solidity"] - 1.0) < 1e-6)

text_like = np.zeros((200, 300), dtype=np.uint8)
rng = np.random.default_rng(0)
for x0 in range(20, 120, 8):
    text_like[178:186, x0:x0 + 5] = 255  # short bright blocks with gaps: "text"
check("detect_scale_bar_px: text-like scattered blocks (low solidity) are "
      "rejected, not mistaken for a bar",
      sc.detect_scale_bar_px(text_like) is None)

noisy_tissue = np.zeros((200, 300), dtype=np.uint8)
noisy_tissue[150:190, :] = (rng.random((40, 300)) * 255).astype(np.uint8)
check("detect_scale_bar_px: bright but non-contiguous real-looking texture "
      "is rejected", sc.detect_scale_bar_px(noisy_tissue) is None)

right_corner = np.zeros((200, 300), dtype=np.uint8)
right_corner[15, 250:290] = 255  # top-right, 40px
result_tr = sc.detect_scale_bar_px(right_corner)
check("detect_scale_bar_px: finds a bar in a non-default corner "
      "(top_right) when bottom-left has nothing",
      result_tr is not None and result_tr["corner"] == "top_right", result_tr)

# ---------------------------------------------------------------------------
# Real confocal exports. Skipped (not failed) if the network share isn't
# reachable in this environment - see the memory note on why L: searches
# can time out and where these specific files live.
# ---------------------------------------------------------------------------
REAL_CASES = [
    (r"L:\05_Proprioception\Ella\Myocyte Measurements\240619_BZ33_day5A_crawl_phall_9"
     r"\240619_BZ33_day5A_crawl_phall_9_W1_posterior.tif", 188),
    (r"L:\05_Proprioception\Ella\Myocyte Measurements\240619_BZ33_day5A_crawl_phall_9"
     r"\240619_BZ33_day5A_crawl_phall_9_W2_mid.tif", 188),
    (r"L:\10_AGVG LAB\ImageJ_Tools\Sample_N2_day5A_phalloidin_worm02.tif", 410),
]
any_real_case_found = False
for path_str, expected_px in REAL_CASES:
    path = Path(path_str)
    if not path.exists():
        continue
    any_real_case_found = True
    import cv2
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    gray = img[..., 1] if img.ndim == 3 else img
    result = sc.detect_scale_bar_px(gray)
    check(f"{path.name}: a real embedded scale bar was found",
          result is not None, result)
    if result is not None:
        check(f"{path.name}: detected length matches the real bar exactly "
              f"(hand-verified once, see module docstring)",
              abs(result["length_px"] - expected_px) < 1e-6,
              f"got {result['length_px']}, expected {expected_px}")
        check(f"{path.name}: solidity reflects a clean, unbroken line",
              result["solidity"] > 0.95, result["solidity"])
if not any_real_case_found:
    print("\n  (none of the real confocal exports were reachable - "
          "real-image checks skipped, synthetic coverage above still applies)")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("SCALE_CALIBRATION_REGRESSION_PASS")
