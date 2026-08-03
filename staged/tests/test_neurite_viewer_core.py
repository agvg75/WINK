"""Regression tests for tools/neurite_viewer_core.py.

Both flagged risks are tested against the lab's REAL stack dimensions
rather than convenient round numbers, because both problems only bite at
that scale: 8.15M pixels per XY plane, and a 60:1 lateral-to-depth ratio
that makes an unstretched XZ panel a third of a screen pixel per z plane.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import neurite_viewer_core as vc

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("neurite_viewer_core - regression\n")

# The real acquisition this has to work on.
NZ, NY, NX = 24, 1807, 4512
DZ, DY, DX = 0.17118, 0.05454, 0.05454
PANEL_W = 500

# ---------------------------------------------------------------------------
# 1. Aspect: the XZ/YZ panels must be clickable
# ---------------------------------------------------------------------------
true_a = vc.true_z_aspect(DZ, DY)
check("true physical aspect reflects real anisotropy (z voxels are ~3.1x "
      "lateral)", abs(true_a - DZ / DY) < 1e-12 and 3.0 < true_a < 3.2, true_a)

px_per_lat = PANEL_W / NX
unstretched_px_per_plane = true_a * px_per_lat
check("at TRUE aspect a z plane is under 1 screen px on this stack - the "
      "reason an unstretched panel is unusable",
      unstretched_px_per_plane < 1.0, unstretched_px_per_plane)

stretch = vc.auto_z_stretch(NZ, DZ, DY, NX, PANEL_W)
check("auto stretch kicks in for this stack", stretch > 1.0, stretch)
stretched_px_per_plane = true_a * stretch * px_per_lat
check("after stretching, each z plane is at least 4 screen px, i.e. "
      "actually clickable",
      stretched_px_per_plane >= vc.MIN_SCREEN_PX_PER_PLANE - 1e-9,
      stretched_px_per_plane)
check("stretch is not wildly larger than needed (it targets the threshold, "
      "not the maximum)", stretched_px_per_plane < vc.MIN_SCREEN_PX_PER_PLANE * 1.5,
      stretched_px_per_plane)

asp = vc.ortho_aspect(NZ, DZ, DY, NX, PANEL_W)
check("a stretched panel reports itself as NOT physically true",
      asp.physically_true is False)
check("and carries a caption saying so, so shape is never read off it",
      "not to scale" in vc.z_stretch_label(asp), vc.z_stretch_label(asp))
check("the caption names the factor", "stretched" in asp.label()
      and f"{asp.z_stretch:.0f}" in asp.label(), asp.label())

# A stack that needs no distortion must not get one. 20 planes across a
# 500 px panel at 100 lateral voxels is already 5 screen px per plane.
iso = vc.ortho_aspect(20, 0.1, 0.1, 100, PANEL_W)
check("a stack whose panel is ALREADY tall enough to click is left "
      "physically true rather than gratuitously stretched",
      iso.physically_true is True and iso.z_stretch == 1.0, iso)
check("its label says z is to scale", "to scale" in iso.label()
      and "not to scale" not in iso.label(), iso.label())

# A caption must never round its own factor away to nothing.
mild = vc.ortho_aspect(NZ, DZ, DY, NX, PANEL_W, z_stretch=1.2)
check("a small stretch keeps a decimal instead of collapsing to '1x', which "
      "would read as 'stretched 1x - not to scale'",
      "1.2x" in mild.label(), mild.label())
check("a large stretch drops the decimal", "12x" in vc.ortho_aspect(
    NZ, DZ, DY, NX, PANEL_W, z_stretch=11.5).label())
tiny = vc.ortho_aspect(NZ, DZ, DY, NX, PANEL_W, z_stretch=1.01)
check("a stretch too small to see is treated as true rather than carrying a "
      "warning nobody should act on",
      tiny.physically_true is True and tiny.z_stretch == 1.0, tiny.label())

check("stretch is capped so a pathological stack cannot produce an absurd "
      "aspect", vc.auto_z_stretch(2, 0.001, 1.0, 100000, 500) <= vc.MAX_Z_STRETCH,
      vc.auto_z_stretch(2, 0.001, 1.0, 100000, 500))
check("a single-plane stack needs no stretch",
      vc.auto_z_stretch(1, DZ, DY, NX, PANEL_W) == 1.0)
try:
    vc.true_z_aspect(0.1, 0)
    check("a zero lateral voxel size is refused", False)
except ValueError:
    check("a zero lateral voxel size is refused", True)

# an explicit override is honoured
manual = vc.ortho_aspect(NZ, DZ, DY, NX, PANEL_W, z_stretch=1.0)
check("an explicit z_stretch=1 overrides the auto value, for anyone who "
      "wants true proportions", manual.physically_true is True)

# ---------------------------------------------------------------------------
# 2. Display texture: cheap redraws, exact coordinates
# ---------------------------------------------------------------------------
vol = np.zeros((NZ, NY, NX), dtype=np.uint8)
vol[5, 900, 2000] = 200          # a landmark to find again
tex = vc.DisplayTexture(vol, max_display_px=1200)

check("the texture is decimated laterally", tex.step > 1, tex.step)
check("z is NOT decimated - a stack has tens of planes, the cost is lateral",
      tex.shape[0] == NZ, tex.shape)
check("the decimated panel is within the display budget",
      max(tex.shape[1], tex.shape[2]) <= 1200, tex.shape)
check("redraw cost drops by the square of the step",
      tex.memory_ratio() == tex.step ** 2, tex.memory_ratio())
check("that is a large real saving on this stack (>10x fewer pixels per "
      "redraw)", tex.memory_ratio() >= 10, tex.memory_ratio())
check("describe() states the mapping is back to full resolution",
      "full resolution" in tex.describe(), tex.describe())

# Round-trip: full -> display -> full must land in the same neighbourhood.
worst = 0
for (fy, fx) in [(0, 0), (900, 2000), (NY - 1, NX - 1), (17, 3), (1806, 4511)]:
    dy_, dx_ = tex.to_display(fy, fx)
    back_y, back_x = tex.to_full(dy_, dx_)
    worst = max(worst, abs(back_y - fy), abs(back_x - fx))
check("full -> display -> full round-trips within one texel, so a marker "
      "drawn from a stored anchor lands where the anchor is",
      worst <= tex.step, worst)

# A click maps to the CENTRE of the texel's block, not its corner.
mid_y, mid_x = tex.to_full(10, 10)
corner_y, corner_x = 10 * tex.step, 10 * tex.step
check("a click maps to the middle of the block a drawn pixel represents, "
      "not its corner - otherwise every click is biased up and left",
      mid_y > corner_y and mid_x > corner_x, (mid_y, corner_y))

check("mapping is clamped inside the volume",
      tex.to_full(10 ** 6, 10 ** 6) == (NY - 1, NX - 1),
      tex.to_full(10 ** 6, 10 ** 6))

check("XY slice comes from the decimated texture",
      tex.xy_slice(5).shape == (tex.shape[1], tex.shape[2]), tex.xy_slice(5).shape)
check("XZ slice is (Z, X)", tex.xz_slice(900).shape == (NZ, tex.shape[2]),
      tex.xz_slice(900).shape)
check("YZ slice is (Z, Y)", tex.yz_slice(2000).shape == (NZ, tex.shape[1]),
      tex.yz_slice(2000).shape)
check("an out-of-range slice index is clamped, not an IndexError",
      tex.xz_slice(10 ** 6).shape == (NZ, tex.shape[2]))

try:
    vc.DisplayTexture(np.zeros((4, 5)))
    check("a non-3D volume is refused", False)
except ValueError:
    check("a non-3D volume is refused", True)

small = vc.DisplayTexture(np.zeros((3, 40, 50)), max_display_px=1200)
check("a small stack is not decimated at all (step 1)", small.step == 1, small.step)
check("and its coordinates are then exact",
      small.to_full(*small.to_display(21, 33)) == (21, 33))

# ---------------------------------------------------------------------------
# 3. Panel click routing - the classic ortho-viewer bug
# ---------------------------------------------------------------------------
current = (5, 900, 2000)
xy = vc.panel_click_to_full("xy", 100, 50, current, tex)
check("clicking XY sets y and x but leaves z alone (XY IS a z slice)",
      xy[0] == 5 and xy[1] != 900 and xy[2] != 2000, xy)

xz = vc.panel_click_to_full("xz", 100, 9, current, tex)
check("clicking XZ sets x and z but leaves y alone (XZ is a slice THROUGH y)",
      xz[0] == 9 and xz[1] == 900 and xz[2] != 2000, xz)

yz = vc.panel_click_to_full("yz", 100, 9, current, tex)
check("clicking YZ sets y and z but leaves x alone",
      yz[0] == 9 and yz[1] != 900 and yz[2] == 2000, yz)

check("a z click beyond the stack is clamped",
      vc.panel_click_to_full("xz", 10, 10 ** 6, current, tex)[0] == NZ - 1)
try:
    vc.panel_click_to_full("nope", 1, 1, current, tex)
    check("an unknown panel name is refused", False)
except ValueError:
    check("an unknown panel name is refused", True)

pos = vc.crosshair_positions((5, 900, 2000), tex)
check("crosshair positions are given per panel in that panel's own axes",
      set(pos) == {"xy", "xz", "yz"}, list(pos))
check("XZ and YZ crosshairs use z directly (never the decimated step)",
      pos["xz"][1] == 5 and pos["yz"][1] == 5, (pos["xz"], pos["yz"]))
check("XY crosshair is in decimated display coordinates",
      abs(pos["xy"][0] - 2000 / tex.step) < 1.0, pos["xy"])

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("NEURITE_VIEWER_CORE_REGRESSION_PASS")
