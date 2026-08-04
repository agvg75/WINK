"""Regression tests for app/worm_area_probe.py.

Area gates are entered in SOURCE pixels, so a default that suits one camera
floods another with noise. This module turns "click one animal" into gates
derived from the detector's own mask. The tests build synthetic recordings
where the animal's true area is known, so the probe can be checked against a
number rather than against itself.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import worm_area_probe as wap        # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def make_frames(n=12, size=200, worm=(30, 8), noise_blobs=6, seed=0):
    """Frames with one moving 'worm' rectangle plus small static specks."""
    rng = np.random.default_rng(seed)
    w, h = worm
    frames = []
    specks = [(int(rng.integers(10, size - 10)), int(rng.integers(10, size - 10)))
              for _ in range(noise_blobs)]
    for i in range(n):
        img = np.full((size, size), 40, dtype=np.uint8)
        for sx, sy in specks:                      # static: absorbed by median
            img[sy:sy + 3, sx:sx + 3] = 200
        x = 20 + i * 6
        img[100:100 + h, x:x + w] = 220            # the animal, moving
        frames.append(img)
    return frames, w * h


print("worm_area_probe - regression\n")

frames, true_area = make_frames()
check("proxy scale is 1.0 for small frames", wap.proxy_scale(200, 200) == 1.0)
check("large frames are sampled down", wap.proxy_scale(4096, 2160) == 0.25)

idx = wap.sample_indices(len(frames))
check("sample indices stay inside the recording",
      idx.min() >= 0 and idx.max() < len(frames), f"{idx.min()}..{idx.max()}")

bg, chosen = wap.background_and_frame(frames)
check("a background is built from the samples", bg.shape == frames[0].shape)

try:
    wap.background_and_frame(frames[:1])
    check("one frame is refused - it cannot separate animal from plate", False)
except ValueError:
    check("one frame is refused - it cannot separate animal from plate", True)

labels, stats = wap.detect_objects(chosen, bg)
check("the moving object is detected", stats.shape[0] >= 2,
      f"{stats.shape[0] - 1} objects")

# click in the middle of where the worm is in the chosen frame
mid = len(frames) // 2
cx, cy = 20 + mid * 6 + 15, 104
label = wap.object_at(labels, stats, cx, cy)
d = wap.describe(stats, label, scale=1.0)
check("measured area is close to the true area",
      abs(d["source_area_px"] - true_area) / true_area < 0.25,
      f"{d['source_area_px']:.0f} vs {true_area}")

# a click on empty plate must still land on an object, not fail
far = wap.object_at(labels, stats, 2, 2)
check("a click on background falls back to the nearest object", far >= 1)

g = wap.suggest_gates(d)
check("suggested gates bracket the measured animal",
      g["min_area"] < d["source_area_px"] < g["max_area"],
      f"{g['min_area']}..{g['max_area']}")
check("gates use the reference tool's factors, so both agree by construction",
      g["min_factor"] == 0.40 and g["max_factor"] == 5.0)
check("the number of objects kept is reported, not just the gates",
      "kept_objects" in g and g["kept_objects"] >= 1, g["kept_objects"])

# --- the point of the whole exercise: naming what is wrong NOW -----------
# The reported defect is a 4K recording, where the animal is thousands of
# pixels and the legacy 40 px floor is a fraction of a percent of it - so
# every speck of debris clears the gate. A 240 px animal against a 40 px
# floor is NOT that case and must not be flagged, or the warning becomes
# noise that people learn to ignore.
big = dict(d, source_area_px=9000.0)

why_floor = wap.gates_look_wrong_for(big, min_area=40, max_area=50000)
check("a floor far below a 4K-sized animal is flagged, not silently used",
      why_floor is not None, why_floor)
check("...and the reason names debris being tracked as animals",
      why_floor is not None and "debris" in why_floor)

why_ceiling = wap.gates_look_wrong_for(big, min_area=40, max_area=2500)
check("an animal larger than the maximum is flagged as being discarded",
      why_ceiling is not None and "discarded" in why_ceiling, why_ceiling)

modest = wap.gates_look_wrong_for(d, min_area=40, max_area=2500)
check("a small animal with proportionate gates draws no complaint, so the "
      "warning does not become noise", modest is None, modest)

ok = wap.gates_look_wrong_for(d, min_area=int(d["source_area_px"] * 0.4),
                              max_area=int(d["source_area_px"] * 5))
check("suggested gates produce no complaint", ok is None, ok)

# --- link distance ------------------------------------------------------
link = wap.estimate_link_px(frames, bg, d["proxy_area_px"], scale=1.0)
check("a link distance is estimated from observed motion",
      link is None or link >= 8.0, link)
short = wap.estimate_link_px(frames[:2], bg, d["proxy_area_px"], scale=1.0)
check("too few frames returns None rather than a guessed number",
      short is None, short)

# --- thin-animal warning ------------------------------------------------
thin = wap.describe(stats, label, scale=0.25)
check("thickness is reported so a fragmenting skeleton can be predicted",
      "too_thin_for_skeleton" in thin)

print()
failed = [n for n, ok_, _ in results if not ok_]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("WORM_AREA_PROBE_REGRESSION_PASS")
