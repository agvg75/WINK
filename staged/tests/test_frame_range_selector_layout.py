"""The commit control must be clickable, not merely present.

REPORTED AS: after marking a start and an end in the GCaMP tool there was no
way to commit the selection, the only available action was "Analyze full
movie" - which ignores the marks - and no way back to the cockpit.

The buttons were there the whole time and correctly wired. "Accept ranges"
and "Cancel" sat in a frame packed AFTER a preview packed with expand=True,
and Tk allocates its cavity in packing order: once the preview asked for more
height than the 780 px window had, every later row was squeezed to one pixel.
Present, importable, findable by name - and with no clickable area.

Measured before the fix:

    source frame   Mark start   Analyze full movie   Accept   Cancel
      <= 384 px       25 px          25 px            25 px    25 px
      512-640 px      25 px          25 px             1 px     1 px
      >= 720 px        1 px           1 px             1 px     1 px

The preview thumbnails to 720 px, so any ordinary fluorescence frame landed
in the broken band. This test asserts the height, because every test that
asserted existence passed throughout.

Skips cleanly where there is no display.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app")]

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("frame range selector - the commit control is reachable\n")

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.withdraw()
except Exception as exc:                                  # headless
    print(f"  SKIP  no display available ({type(exc).__name__})")
    print("\nFRAME_RANGE_SELECTOR_LAYOUT_SKIPPED")
    raise SystemExit(0)

from frame_range_selector import FrameRangeSelector       # noqa: E402

# Anything below this is a strip too thin to hit with a mouse.
MIN_CLICKABLE_PX = 12
WANTED = ("Mark start", "Mark end + add range", "Delete selected",
          "Analyze full movie", "Accept ranges", "Cancel")


class FakeMovie:
    n_frames = 300

    def __init__(self, px):
        self.px = px

    def get_frame(self, i):
        return np.random.default_rng(i).integers(
            0, 255, (self.px, self.px), dtype=np.uint8)

    def close(self):
        pass


def button_heights(px):
    window = FrameRangeSelector(_root, FakeMovie(px))
    window.update_idletasks()
    window.update()
    window.update_idletasks()

    found = {}

    def walk(widget):
        for child in widget.winfo_children():
            try:
                text = child.cget("text")
            except Exception:
                text = ""
            if text in WANTED:
                found[text] = child.winfo_height()
            walk(child)

    walk(window)
    window.destroy()
    return found


# 512 and 640 are the sizes that produced the report; 720+ collapsed
# everything, and 2048 is a plausible camera frame.
for px in (128, 384, 512, 640, 720, 1024, 2048):
    heights = button_heights(px)
    check(f"every control is present at {px}x{px}",
          set(heights) == set(WANTED),
          f"missing {sorted(set(WANTED) - set(heights))}"
          if set(heights) != set(WANTED) else "")
    too_thin = {name: h for name, h in heights.items()
                if h < MIN_CLICKABLE_PX}
    check(f"...and clickable at {px}x{px}", not too_thin,
          f"collapsed: {too_thin}" if too_thin else
          f"all >= {min(heights.values())}px")

# The two the report named specifically.
tall = button_heights(640)
check("'Accept ranges' is clickable at the size that was reported broken",
      tall["Accept ranges"] >= MIN_CLICKABLE_PX,
      f"{tall['Accept ranges']}px at 640x640")
check("'Cancel' is too - the way back to the cockpit without analysing",
      tall["Cancel"] >= MIN_CLICKABLE_PX,
      f"{tall['Cancel']}px at 640x640")

_root.destroy()

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("FRAME_RANGE_SELECTOR_LAYOUT_PASS")
