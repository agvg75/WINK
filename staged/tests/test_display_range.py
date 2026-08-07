"""Brightness is a display choice and must never reach a measurement.

WHY THIS EXISTS. The single-worm tracker drew its outline-seeding frame with
a bare `ax.imshow(G[0], cmap="gray")` - no vmin, no vmax, no control. On
oblique-lit agar the worm is mid-grey against mid-grey and is close to
invisible at default scaling.

That is not cosmetic. The outline drawn on that frame sets `area_ref` and
`len_ref`, and every later frame is accepted only if its area falls within
0.55x to 1.60x of that reference. An outline drawn around something the
person could not see produces a reference no real detection matches, and the
tracker then finds the worm in ZERO frames while every individual step
behaves exactly as written. Found in use, 7 Aug 2026.

The 0.5/99.5 stretch already existed in five places - pboc_tool twice,
render_failure_queue, myocyte_morphometry_tool, pumping_tool - and in none of
the two tracker screens that needed it most. This is that rule, once.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app")]

import display_range as dr   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("\n--- the stretch is the one every other screen already used ------")

check("the percentiles are 0.5 and 99.5",
      (dr.LOW_PERCENTILE, dr.HIGH_PERCENTILE) == (0.5, 99.5),
      "a different stretch per screen makes two views of one recording "
      "disagree about what is visible")

# A mid-grey worm on mid-grey agar: a narrow distribution with a faint tail.
rng = np.random.default_rng(0)
agar = rng.normal(128, 4, (256, 256))
agar[100:110, 40:200] = 116          # the worm, 12 grey levels down
lo, hi = dr.auto_range(agar)
check("the auto range is far narrower than the full range",
      (hi - lo) < (agar.max() - agar.min()),
      f"auto {hi - lo:.1f} vs full {agar.max() - agar.min():.1f} grey levels")
check("...and still contains the worm",
      lo <= 116 <= hi,
      "a stretch that clipped the animal would be worse than none")

print("\n--- degenerate frames get a drawable range, never a blank -------")

check("a flat frame does not collapse to zero width",
      dr.auto_range(np.full((8, 8), 7.0))[1]
      > dr.auto_range(np.full((8, 8), 7.0))[0],
      "vmin == vmax draws pure black")
check("...and neither does full_range on one",
      dr.full_range(np.full((8, 8), 7.0))[1]
      > dr.full_range(np.full((8, 8), 7.0))[0])
check("an empty array yields a usable default",
      dr.auto_range(np.array([])) == (0.0, 1.0))
check("all-NaN yields a usable default",
      dr.auto_range(np.full((4, 4), np.nan)) == (0.0, 1.0))
check("NaNs among real values are ignored, not propagated",
      np.isfinite(dr.auto_range(
          np.where(np.arange(100).reshape(10, 10) % 7 == 0,
                   np.nan, 50.0))).all())

print("\n--- integer frames behave like the camera writes them -----------")

frame16 = (rng.normal(2000, 60, (128, 128))).astype(np.uint16)
lo, hi = dr.auto_range(frame16)
check("a uint16 frame gets a sane range",
      0 < lo < hi < 65535, f"{lo:.0f}-{hi:.0f}")
check("full_range on uint16 spans the data",
      dr.full_range(frame16)[0] <= lo and dr.full_range(frame16)[1] >= hi)

print("\n--- the data is never modified ---------------------------------")

original = agar.copy()
dr.auto_range(agar)
dr.full_range(agar)
check("computing a range does not touch the array",
      np.array_equal(agar, original),
      "these values go to imshow's vmin/vmax; the frame is never rescaled, "
      "so no measurement can inherit a display choice")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("DISPLAY_RANGE_PASS")
