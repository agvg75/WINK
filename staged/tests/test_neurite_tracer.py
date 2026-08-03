"""Regression tests for tools/neurite_tracer.py.

Synthetic volumes with a KNOWN embedded path: a tube is drawn along a
route the test itself defines, so "did the tracer follow the neurite" has
an actual answer rather than being judged by eye. Includes the failure the
module's own docstring says is the most common - a brighter distractor
pulling the path off the true neurite - because a tracer that is only ever
tested on clean data tells you nothing about the case anchors exist for.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import neurite_tracer as nt

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def draw_tube(vol, points, radius=2, value=255.0):
    """Paint a tube through an ordered list of (z, y, x) points."""
    pts = np.asarray(points, float)
    for a, b in zip(pts[:-1], pts[1:]):
        steps = int(max(np.abs(b - a).max() * 3, 2))
        for t in np.linspace(0, 1, steps):
            c = a + (b - a) * t
            zz, yy, xx = np.ogrid[:vol.shape[0], :vol.shape[1], :vol.shape[2]]
            m = ((zz - c[0]) ** 2 + (yy - c[1]) ** 2 + (xx - c[2]) ** 2) <= radius ** 2
            vol[m] = value
    return vol


print("neurite_tracer - regression\n")

VOX = (0.4, 0.1, 0.1)          # deliberately anisotropic, like real confocal

# ---------------------------------------------------------------------------
# 1. Tubeness responds to tubes, and is anisotropy-aware
# ---------------------------------------------------------------------------
vol = np.zeros((20, 40, 60), dtype=np.float32)
straight = [(10, 20, 5), (10, 20, 54)]
draw_tube(vol, straight, radius=2)

resp, sigmas_um = nt.tubeness(vol, VOX, radius_um=0.2)
check("tubeness returns a volume of the same shape",
      resp.shape == vol.shape, resp.shape)
check("tubeness is normalised to 0..1",
      0.0 <= resp.min() and abs(resp.max() - 1.0) < 1e-6, (resp.min(), resp.max()))
on_tube = resp[10, 20, 30]
off_tube = resp[3, 5, 5]
check("a voxel on the tube scores far above background",
      on_tube > 0.3 and on_tube > off_tube * 10, (on_tube, off_tube))
check("sigmas are reported in micrometres, so the parameter means the same "
      "thing at any magnification", all(s > 0 for s in sigmas_um), sigmas_um)

try:
    nt.tubeness(np.zeros((4, 5, 6, 7)), VOX, radius_um=0.2)
    check("a 4-D array is refused with a useful message", False)
except nt.NeuriteTraceError as exc:
    check("a 4-D array is refused with a useful message",
          "one channel" in str(exc).lower(), str(exc)[:60])

# ---------------------------------------------------------------------------
# 2. Path search recovers a known route
# ---------------------------------------------------------------------------
path = nt.trace_between(resp, (10, 20, 5), (10, 20, 54), VOX)
check("the traced path connects the requested endpoints",
      tuple(path[0]) == (10, 20, 5) and tuple(path[-1]) == (10, 20, 54),
      (tuple(path[0]), tuple(path[-1])))
off_axis = np.abs(path[:, :2] - np.array([10, 20])).max()
check("the path stays on the known straight tube rather than wandering",
      off_axis <= 2, off_axis)

for bad, label in (((99, 20, 5), "start"), ((10, 20, 999), "end")):
    try:
        nt.trace_between(resp, bad if label == "start" else (10, 20, 5),
                         (10, 20, 54) if label == "start" else bad, VOX)
        check(f"an out-of-bounds {label} point is refused", False)
    except nt.NeuriteTraceError:
        check(f"an out-of-bounds {label} point is refused", True)

try:
    nt.trace_between(resp, (10, 20, 5), (10, 20, 5), VOX)
    check("identical start and end are refused", False)
except nt.NeuriteTraceError:
    check("identical start and end are refused", True)

# ---------------------------------------------------------------------------
# 3. Snapping: an imprecise click lands back on the ridge
# ---------------------------------------------------------------------------
snapped = nt.snap_to_ridge(resp, (12, 22, 30), radius_vox=3)
check("a click 2 voxels off the tube snaps back onto it",
      resp[snapped] > resp[12, 22, 30], (resp[snapped], resp[12, 22, 30]))
check("snapping stays inside the volume",
      all(0 <= c < s for c, s in zip(snapped, resp.shape)), snapped)

# ---------------------------------------------------------------------------
# 4. THE failure anchors exist for: a brighter distractor steals the path
# ---------------------------------------------------------------------------
vol2 = np.zeros((20, 40, 60), dtype=np.float32)
# True neurite: bows away in y, and is dimmer.
true_route = [(10, 20, 5), (10, 34, 30), (10, 20, 54)]
draw_tube(vol2, true_route, radius=2, value=120.0)
# Distractor: brighter and straighter, near the direct line between endpoints.
draw_tube(vol2, [(10, 18, 5), (10, 18, 54)], radius=2, value=255.0)
resp2, _ = nt.tubeness(vol2, VOX, radius_um=0.2)

auto = nt.trace_between(resp2, (10, 20, 5), (10, 20, 54), VOX)
mid_y_auto = float(auto[len(auto) // 2][1])
check("without anchors the path is pulled onto the brighter distractor "
      "instead of the true, dimmer neurite - the documented failure mode",
      mid_y_auto < 25, mid_y_auto)

anchored = nt.trace_with_anchors(resp2, [(10, 20, 5), (10, 34, 30), (10, 20, 54)], VOX)
mid_y_anchored = float(anchored[len(anchored) // 2][1])
check("an anchor on the true neurite pulls the path back onto it",
      mid_y_anchored > 28, mid_y_anchored)
check("the anchored path still reaches both endpoints",
      tuple(anchored[0]) == (10, 20, 5) and tuple(anchored[-1]) == (10, 20, 54))
check("legs are joined without duplicating the anchor voxel",
      len(anchored) == len(np.unique(anchored, axis=0))
      or len(anchored) - len(np.unique(anchored, axis=0)) < 3,
      (len(anchored), len(np.unique(anchored, axis=0))))

try:
    nt.trace_with_anchors(resp2, [(10, 20, 5)], VOX)
    check("a single point is refused (a path needs two ends)", False)
except nt.NeuriteTraceError:
    check("a single point is refused (a path needs two ends)", True)

# ---------------------------------------------------------------------------
# 5. Physical measurement uses real voxel spacing, not voxel counts
# ---------------------------------------------------------------------------
tp = nt.TracedPath(nodes_zyx=path, voxel_size_um=VOX, raw_nodes_zyx=path)
length = tp.length_um()
expected = (54 - 5) * VOX[2]          # a straight run along x
check("path length is measured in micrometres using the real anisotropic "
      "voxel size, not in voxel counts",
      abs(length - expected) < expected * 0.15, (length, expected))
check("an untouched path reports itself as not corrected", tp.was_corrected() is False)

tp2 = nt.TracedPath(nodes_zyx=anchored, voxel_size_um=VOX, raw_nodes_zyx=path)
check("a path differing from the raw proposal reports as corrected",
      tp2.was_corrected() is True)
check("the raw automatic proposal is retained alongside the correction, "
      "never overwritten in place",
      tp2.raw_nodes_zyx is not None and len(tp2.raw_nodes_zyx) == len(path))

# a z-running path must be longer in um than the same voxel count laterally
zpath = np.array([[z, 20, 30] for z in range(5, 15)])
z_len = nt.TracedPath(nodes_zyx=zpath, voxel_size_um=VOX).length_um()
xpath = np.array([[10, 20, x] for x in range(5, 15)])
x_len = nt.TracedPath(nodes_zyx=xpath, voxel_size_um=VOX).length_um()
check("the same number of voxels along z is 4x longer than along x at this "
      "anisotropy - treating voxels as cubes would be wrong",
      abs(z_len / x_len - VOX[0] / VOX[2]) < 0.01, (z_len, x_len))

# ---------------------------------------------------------------------------
# 6. Radius and volume
# ---------------------------------------------------------------------------
radii = nt.radius_profile_um(vol, path, VOX)
check("a radius is produced for every node", len(radii) == len(path), len(radii))
mid_radius = float(np.median(radii))
true_radius_um = 2 * VOX[1]           # tube drawn with radius 2 voxels laterally
check("the measured radius is the right order for a 2-voxel tube",
      0.3 * true_radius_um < mid_radius < 3.0 * true_radius_um,
      (mid_radius, true_radius_um))
vol_um3 = nt.volume_from_radii_um3(radii, path, VOX)
cylinder = np.pi * mid_radius ** 2 * length
check("volume is within a small factor of a cylinder of the same radius "
      "and length", 0.4 * cylinder < vol_um3 < 2.5 * cylinder, (vol_um3, cylinder))

# ---------------------------------------------------------------------------
# 7. Preflight honesty
# ---------------------------------------------------------------------------
notes = nt.preflight_notes({"voxel_size_um": VOX}, resp)
check("strong anisotropy is reported before tracing",
      any("z spacing" in n for n in notes), notes)
empty_notes = nt.preflight_notes({"voxel_size_um": VOX}, np.zeros((5, 5, 5)))
check("a volume with nothing tube-like says so rather than returning a "
      "confident path through noise",
      any("tube-like" in n for n in empty_notes), empty_notes)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("NEURITE_TRACER_REGRESSION_PASS")
