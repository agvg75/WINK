"""Drawn stimulus geometry, the donut assay, and the field-over-movie overlay.

Andres: for a gradient stimulus the user drops a point or ROI on the source;
for a linear field they draw a line across it; for the donut they draw the
inner edge of the magnet hole, and the measure is time to fully cross it.
Outputs superimpose the modelled field and the tracks on the movie, for all
stimuli and configurations.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"),
                str(ROOT / "tools" / "orientation_assays"),
                str(ROOT / "tools" / "population_orientation")]

import matplotlib          # noqa: E402
matplotlib.use("Agg")
import numpy as np                  # noqa: E402
import field_overlay as fo          # noqa: E402
import plate_assay as pa            # noqa: E402
import stimulus_annotation as sa    # noqa: E402
from stimulus_fields import UniformFieldProvider   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("donut assay, annotation and overlay - regression\n")

# --- drawing where the stimulus is -----------------------------------------
spot = sa.annotate("point", x_px=400, y_px=300, um_per_px=50.0, by="AV")
check("a point converts pixels to plate millimetres",
      spot["center_mm"] == [20.0, 15.0], "400 px x 0.05 mm")
check("...and records who placed it", spot["drawn_by"] == "AV")
check("...and what the shape MEANS, not just its coordinates",
      "point source" in spot["means"])

line = sa.annotate("line", x1_px=800, y1_px=0, x2_px=800, y2_px=600,
                   um_per_px=50.0, by="AV")
check("a line down the right edge declares a vertical direction",
      abs(line["direction_deg"] - 90.0) < 1e-9)
check("...and its normal, which is the perpendicular axis",
      abs(abs(line["normal_deg"]) - 180.0) < 1e-9 or
      abs(line["normal_deg"]) < 1e-9,
      f"{line['normal_deg']}")
check("a line's meaning is ambiguous and both readings are offered",
      "direction_xy" in line and "normal_xy" in line,
      "drawn ALONG the field or ACROSS it - the pixels cannot say which")
try:
    sa.to_provider_kwargs(line, assay="magnetotaxis", use="whatever")
    check("guessing along-vs-across is refused", False)
except sa.AnnotationError as exc:
    check("guessing along-vs-across is refused", True)
    check("...naming that it would rotate the field 90 degrees",
          "rotate the field 90 degrees" in str(exc))

hole = sa.annotate("circle", x_px=500, y_px=500, radius_px=100,
                   um_per_px=50.0, by="AV")
check("a circle carries a radius in millimetres", hole["radius_mm"] == 5.0)
check("...and maps to the donut's inner edge",
      sa.to_provider_kwargs(hole, assay="magnetotaxis")["inner_radius_mm"]
      == 5.0)

# --- the refusals that keep a drawing meaningful ---------------------------
try:
    sa.annotate("point", x_px=1, y_px=1)
    check("a drawing without a scale is refused", False)
except sa.AnnotationError as exc:
    check("a drawing without a scale is refused", True)
    check("...naming that the field would be silently wrong",
          "silently" in str(exc))
try:
    sa.annotate("point", x_px=1, y_px=1, um_per_px=1.0)
    check("the placeholder scale is refused", False)
except sa.AnnotationError as exc:
    check("the placeholder scale is refused", True)
    check("...and says how to mean it deliberately",
          "mm_per_px=0.001" in str(exc))
try:
    sa.annotate("blob", x_px=1, y_px=1, um_per_px=50.0)
    check("an unknown shape is refused", False)
except sa.AnnotationError as exc:
    check("an unknown shape is refused", True)
    check("...naming that shape does not imply meaning",
          "look identical and are different claims" in str(exc))
try:
    sa.annotate("line", x1_px=5, y1_px=5, x2_px=5, y2_px=5, um_per_px=50.0)
    check("a zero-length line is refused", False)
except sa.AnnotationError:
    check("a zero-length line is refused", True)

# --- the donut measurement --------------------------------------------------
def radial_track(worm, speed_mm_s, n=60, dt=1.0, start_r=0.0):
    """A worm leaving the centre at constant speed along +x."""
    return [{"plate_id": "p", "worm_id": worm, "time_s": t * dt,
             "x_mm": 25.0 + start_r + speed_mm_s * t * dt, "y_mm": 25.0}
            for t in range(n)]


tracks = (radial_track("fast", 0.5) + radial_track("slow", 0.1)
          + radial_track("stayer", 0.001))
res = pa.donut_crossing(tracks, (25.0, 25.0), 5.0, recording_duration_s=60)
check("a fast worm's crossing time is measured",
      res["crossed"][0]["crossing_time_s"] == 10.0, "5 mm at 0.5 mm/s")
check("a worm that never leaves is censored, not scored",
      res["n_censored"] == 1 and
      res["censored"][0]["crossing_time_s"] is None)
check("...and is named as censored rather than slow",
      "not a long one" in res["censored"][0]["censored"])
check("the fraction that crossed is reported alongside the median",
      res["fraction_crossed"] == round(2 / 3, 3) and
      res["median_crossing_time_s"] is not None)
check("dropping or capping the censored is warned against",
      any("pull the mean down" in w for w in res["warnings"]),
      "both biases point the same way")

full = pa.donut_crossing(tracks, (25.0, 25.0), 5.0, body_radius_mm=0.5)
check("a full-body crossing takes longer than a centroid crossing",
      full["crossed"][0]["crossing_time_s"] >
      res["crossed"][0]["crossing_time_s"],
      "by about a worm length, which matters on a 5 mm hole")
check("...and the criterion actually used is recorded",
      full["criterion"] == "fully_outside" and res["criterion"] == "centroid")
check("asking for full-body without a body radius says so",
      any("systematically SHORT" in w for w in res["warnings"]),
      "rather than quietly measuring the centroid instead")

outside = [{"plate_id": "p", "worm_id": "w", "time_s": t, "x_mm": 40.0,
            "y_mm": 25.0} for t in range(5)]
res2 = pa.donut_crossing(outside, (25.0, 25.0), 5.0)
check("a worm that started outside the hole is excluded, not scored zero",
      res2["n_crossed"] == 0 and "excluded" in res2["censored"][0])
check("...naming that a zero would describe the setup, not the animal",
      "describes the setup" in res2["censored"][0]["excluded"])
try:
    pa.donut_crossing(tracks, (0, 0), 0)
    check("a zero-radius hole is refused", False)
except ValueError:
    check("a zero-radius hole is refused", True)

# --- the ring magnet field model --------------------------------------------
from stimulus_fields import RingMagnetProvider   # noqa: E402

ring = RingMagnetProvider(inner_diameter_mm=10, outer_diameter_mm=30,
                          height_mm=5, remanence_t=1.32,
                          center_xy_mm=(25.0, 25.0))
centre = ring.sample(25.0, 25.0)
edge = ring.sample(29.0, 25.0)          # 4 mm out, inside the hole
check("the field at the centre is NOT zero",
      centre.magnitude > 0.3, f"{centre.magnitude * 1000:.0f} mT")
check("...but the in-plane gradient there is, by symmetry",
      abs(centre.gradient_xy[0]) < 1e-9 and abs(centre.gradient_xy[1]) < 1e-9,
      "an animal at the centre has no direction to follow")
check("the field RISES from centre toward the inner edge",
      edge.magnitude > centre.magnitude,
      "a worm leaving the middle climbs a gradient the whole way")
check("inside and outside the hole are distinguished",
      centre.uncertainty["inside_hole"] is True and
      ring.sample(35.0, 25.0).uncertainty["inside_hole"] is False)
check("a mid-hole gradient is trustworthy",
      edge.uncertainty["gradient_unreliable"] is False)
check("a gradient sampled ON a magnet face is flagged",
      ring.sample(25.0 + 15.0, 25.0).uncertainty["gradient_unreliable"] is True,
      "the stencil straddles the boundary and differences two regimes")
check("...naming that the value is large, plausible and meaningless",
      "plausible and meaningless" in
      ring.sample(25.0 + 15.0, 25.0).uncertainty["gradient_warning"])
check("...while saying the magnitude itself is still fine",
      "only the gradient is not" in
      ring.sample(25.0 + 5.0, 25.0).uncertainty["gradient_warning"],
      "the inner edge IS where this assay scores crossings")
for bad, phrase in (
    ({"inner_diameter_mm": 0, "outer_diameter_mm": 30}, "where the worms start"),
    ({"inner_diameter_mm": 30, "outer_diameter_mm": 10}, "no magnet material"),
):
    try:
        RingMagnetProvider(height_mm=5, remanence_t=1.32, **bad)
        check(f"a degenerate ring is refused ({sorted(bad.values())})", False)
    except ValueError as exc:
        check(f"a degenerate ring is refused ({sorted(bad.values())})", True)
        check("...naming the consequence", phrase in str(exc))

# --- the overlay ------------------------------------------------------------
frame = np.zeros((240, 320), dtype=np.uint8)
cage = UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_mt=0.065)
grid = fo.sample_grid(cage, frame.shape, mm_per_px=0.05, step_px=32)
check("any provider can be sampled across the frame",
      grid["scalar"].shape == (len(grid["y_px"]), len(grid["x_px"])))
check("a uniform field really is uniform across the image",
      float(np.ptp(grid["scalar"])) < 1e-15,
      "which is what makes the flat-contour message correct, not a bug")

ax = fo.draw(frame, cage, tracks=tracks, mm_per_px=0.05,
             annotation=hole, title="donut check")
check("the overlay composes frame, field, tracks and annotation", ax is not None)
check("...naming the provider in the title", "merritt" in ax.get_title())

try:
    fo.sample_grid(cage, frame.shape, mm_per_px=0.0)
    check("a zero scale is refused", False)
except fo.OverlayError as exc:
    check("a zero scale is refused", True)
    check("...naming that the overlay would look right while being wrong",
          "look right while being wrong" in str(exc))
try:
    fo.draw(np.zeros((3, 3, 3, 3)), cage, mm_per_px=0.05)
    check("a non-image is refused", False)
except fo.OverlayError:
    check("a non-image is refused", True)

# time is honoured, so a swept field is drawn as it was at that frame
swept = UniformFieldProvider(direction_xyz=[1, 0, 0], magnitude_mt=1.0,
                             oscillation_hz=0.5)
a = fo.sample_grid(swept, frame.shape, 0.05, step_px=64, time_s=0.0)
b = fo.sample_grid(swept, frame.shape, 0.05, step_px=64, time_s=0.5)
check("a time-varying field is drawn as it was at that frame",
      not np.allclose(a["u"], b["u"]),
      "a static snapshot of an oscillating field is a picture of something "
      "that never happened")

# --- the check the overlay exists to make ----------------------------------
class FakeSource:
    provider_type = "fake"
    def __init__(self, cx, cy):
        self.center = np.asarray([cx, cy], dtype=float)
    def sample(self, x, y, t=0):
        return None


good = fo.check_placement(FakeSource(25.0, 25.0),
                          sa.annotate("point", x_px=500, y_px=500,
                                      um_per_px=50.0))
check("a model placed where the user drew agrees",
      good["agrees"] is True and good["offset_mm"] == 0.0)
bad = fo.check_placement(FakeSource(35.0, 25.0),
                         sa.annotate("point", x_px=500, y_px=500,
                                     um_per_px=50.0))
check("a misplaced source is caught numerically, not only by eye",
      bad["agrees"] is False and bad["offset_mm"] == 10.0)
check("...naming that nothing downstream would contradict it",
      "nothing downstream will contradict it" in bad["why"],
      "a picture is only looked at when someone remembers to look")
check("a direction annotation has no place to check",
      fo.check_placement(FakeSource(0, 0), line)["checked"] is False)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("DONUT_AND_OVERLAY_PASS")
