"""How the brightness statistics behave, on data where we know the answer.

THE DECISIVE FIXTURE is the null one: an animal whose calcium NEVER CHANGES,
imaged in an ROI whose area varies with bending. Max must appear to track
curvature there, because the maximum of N samples grows with N, and median must
not. If that separation does not show up, the diagnostic cannot protect anyone
from the plot it exists to catch.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import brightness_statistics as bs   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("brightness statistics - regression\n")
rng = np.random.default_rng(7)
NF = 120
t = np.arange(NF)
curv = 40.0 * np.sin(2 * np.pi * t / 20.0)      # the animal bends


def make_rows(area, brightness_level, n_extra_bright=0, outlier_rate=0.0):
    """One hemisegment's time series, built pixel by pixel so the statistics
    are computed the way the real ones are.

    `outlier_rate` sprinkles rare very bright pixels at a fixed rate PER PIXEL -
    granules, coelomocytes, hot pixels. A larger ROI then catches more of them,
    which is the mechanism that makes max area-dependent in real images.
    """
    rows = []
    for k in range(NF):
        n = int(area[k])
        px = rng.normal(brightness_level[k], 12.0, n)
        if outlier_rate:
            hit = rng.random(n) < outlier_rate
            px[hit] += 400.0
        if n_extra_bright:                        # a gut granule in the band
            px[:n_extra_bright] += 140.0
        rows.append({
            "segment": 11, "hemisegment": "ventral", "roi_area_px": n,
            "seg_curv_deg": float(curv[k]),
            "green_mean": float(px.mean()),
            "green_median": float(np.median(px)),
            "green_p90": float(np.percentile(px, 90)),
            "green_max": float(px.max()),
            "green_min": float(px.min()),
        })
    return rows


# --- THE NULL: brightness is CONSTANT, only ROI area moves with bending ---
area_with_bend = 360 + 100 * np.sin(2 * np.pi * t / 20.0)   # tracks curvature
flat = np.full(NF, 500.0)

# (a) HOW BIG IS THE AREA BIAS ON MAX, REALLY? Measured rather than asserted.
# An earlier version of this file claimed it was strong and was WRONG: the
# expected maximum grows only as sqrt(2 ln N), so a 1.5x area swing moves it by
# a fraction of its own scatter. It holds even with realistic bright outliers.
null_g = make_rows(area_with_bend, flat)
null_o = make_rows(area_with_bend, flat, outlier_rate=0.004)
for label, rows_ in (("gaussian pixels", null_g), ("with bright outliers", null_o)):
    st = bs.compare_statistics(rows_, "green",
                               against="seg_curv_deg")["statistics"]
    check(f"the area bias on max is modest ({label})",
          abs(st["max"]["r_with_roi_area"]) < 0.35,
          f"r = {st['max']['r_with_roi_area']}")

# (b) WHAT IS ACTUALLY WRONG WITH MAX IS VARIANCE, NOT BIAS. It is set by
# whichever bright pixel happened to fall in the ROI, so it barely reproduces
# frame to frame - which is the real reason not to plot it.
S = bs.compare_statistics(null_o, "green", against="seg_curv_deg")["statistics"]
check("max is far noisier frame to frame than median",
      S["max"]["frame_to_frame_noise"] > 4 * S["median"]["frame_to_frame_noise"],
      f"max {S['max']['frame_to_frame_noise']:.1f} vs "
      f"median {S['median']['frame_to_frame_noise']:.1f}")
check("...and median is the most stable statistic on offer",
      S["median"]["frame_to_frame_noise"]
      == min(S[s]["frame_to_frame_noise"] for s in ("mean", "median", "p90", "max")),
      f"median {S['median']['frame_to_frame_noise']:.1f}")

# (c) THE CASE THE CONTROL EXISTS FOR: brightness really does move with ROI
# area, because a wider band takes in more non-muscle tissue. The plot against
# curvature then looks convincing and is about posture.
area_partly = (360 + 60 * np.sin(2 * np.pi * t / 20.0)
               + 40 * np.sin(2 * np.pi * t / 7.0 + 1.0))
spurious_level = 500 + 0.25 * (area_partly - 360) + rng.normal(0, 4, NF)
spurious = make_rows(area_partly, spurious_level)
raw = bs.compare_statistics(spurious, "green",
                            against="seg_curv_deg")["statistics"]["mean"]
check("a posture-driven artefact looks like a strong finding",
      abs(raw["r_with_seg_curv_deg"]) > 0.6,
      f"r = {raw['r_with_seg_curv_deg']} against curvature")
check("...and the diagnostic warns that it tracks ROI area too",
      "warning" in raw, raw.get("warning", "")[:56])
ctl = bs.area_control(spurious, "green", "mean", "seg_curv_deg")
check("the area control kills it",
      ctl["survives_area_control"] is False,
      f"r {ctl['raw_r']} -> {ctl['partial_r_controlling_area']}")
check("...saying most of the plot was the ROI changing size",
      "ROI changing size with posture" in ctl["verdict"])

# --- THE REAL ONE: calcium genuinely tracks curvature ---------------------
# ROI area is only PARTLY related to curvature here, as in a real recording:
# the band widens with bending but also with tracking wobble. That separation
# is what makes the control able to say anything at all.
real_level = 500.0 + 90.0 * np.sin(2 * np.pi * t / 20.0)
real_rows = make_rows(area_partly, real_level)
res2 = bs.compare_statistics(real_rows, "green", against="seg_curv_deg")
S2 = res2["statistics"]
check("a real relationship is found by the robust statistics",
      abs(S2["median"]["r_with_seg_curv_deg"]) > 0.8,
      f"median r = {S2['median']['r_with_seg_curv_deg']}")
ctl2 = bs.area_control(real_rows, "green", "median", "seg_curv_deg")
check("...and it survives holding ROI area fixed",
      ctl2["survives_area_control"] is True,
      f"r {ctl2['raw_r']} -> {ctl2['partial_r_controlling_area']}")

# --- when area and curvature cannot be told apart, refuse ----------------
try:
    bs.area_control(make_rows(area_with_bend, real_level), "green", "median",
                    "seg_curv_deg")
    check("perfect collinearity with ROI area is refused, not reported", False)
except bs.BrightnessError as exc:
    check("perfect collinearity with ROI area is refused, not reported", True)
    check("...saying the separation must come from the experiment",
          "you need frames where the two come apart" in str(exc))

# --- a bright intruder in the band ---------------------------------------
dirty = make_rows(np.full(NF, 400), flat, n_extra_bright=12)
S3 = bs.compare_statistics(dirty, "green")["statistics"]
check("a gut granule in the band lifts the MEAN off the tissue level",
      S3["mean"]["median_level"] - 500.0 > 2.0,
      f"mean {S3['mean']['median_level']:.1f} vs true 500")
check("...while the median stays on it",
      abs(S3["median"]["median_level"] - 500.0) < 2.0,
      f"median {S3['median']['median_level']:.1f}")

# --- noise and refusals ---------------------------------------------------
check("noise is measured from successive differences, not the SD",
      S2["median"]["frame_to_frame_noise"] < S2["median"]["range_p5_p95"],
      f"noise {S2['median']['frame_to_frame_noise']}, "
      f"range {S2['median']['range_p5_p95']}")
check("an SNR is reported per statistic",
      all(S2[s]["snr"] is not None for s in ("mean", "median", "p90", "max")))
flagged_report = bs.compare_statistics(spurious, "green",
                                       against="seg_curv_deg")
check("the recommendation names what not to report against posture",
      "controlling for roi_area_px" in flagged_report["recommendation"],
      flagged_report["recommendation"][:70])
check("...and says it is a measurement on this recording, not general advice",
      "not general advice" in flagged_report["recommendation"])
check("the reading guide points at the area correlation first",
      "THE ONE TO CHECK FIRST"
      in flagged_report["how_to_read"]["r_with_roi_area"])

# --- brightness during relaxation: the PNAS-style measure ----------------
# Two animals with IDENTICAL resting calcium, one of which moves less and so
# spends more frames relaxed. A single-max measure must be inflated in the
# sluggish one; the mean and median of the per-frame maxima must not be.
def relaxed_fixture(n_frames, bend_amp):
    out = []
    for k in range(n_frames):
        curv = bend_amp * np.sin(2 * np.pi * k / 20.0)
        px = rng.normal(500.0, 12.0, 30)          # same calcium in both
        out.append({"segment": 11, "hemisegment": "ventral",
                    "roi_area_px": 30, "seg_curv_deg": float(curv),
                    "green_max": float(px.max()),
                    "green_mean": float(px.mean())})
    return out


mobile = bs.relaxed_brightness(relaxed_fixture(200, 40.0), "green", "max")
sluggish = bs.relaxed_brightness(relaxed_fixture(200, 6.0), "green", "max")
check("relaxation is selected by posture, not by calcium",
      "calcium was not used" in mobile["posture_not_calcium"])
check("the median of per-frame maxima is unaffected by how much the animal moved",
      abs(mobile["median_of_frame_max"] - sluggish["median_of_frame_max"]) < 8,
      f"{mobile['median_of_frame_max']:.1f} vs "
      f"{sluggish['median_of_frame_max']:.1f}")
check("...and the summary says which to prefer and why",
      mobile["prefer"] == "median_of_frame_max"
      and "grows with n" in mobile["why"])

# The n-dependence of single_max, shown directly: more relaxed frames, higher max.
few = bs.relaxed_brightness(relaxed_fixture(60, 40.0), "green", "max")
many = bs.relaxed_brightness(relaxed_fixture(400, 40.0), "green", "max")
check("single_max grows with the NUMBER of relaxed frames alone",
      many["single_max"] > few["single_max"],
      f"{few['n_relaxed_frames']} frames -> {few['single_max']:.1f}, "
      f"{many['n_relaxed_frames']} -> {many['single_max']:.1f}")
check("...while the median of the same frames does not",
      abs(many["median_of_frame_max"] - few["median_of_frame_max"]) < 6,
      f"{few['median_of_frame_max']:.1f} vs {many['median_of_frame_max']:.1f}")
check("the relaxed frame count is reported so the bias is visible",
      "n_relaxed_frames" in mobile and mobile["n_relaxed_frames"] > 0)

check("a within-animal quantile threshold is flagged as relative",
      "not held at the same posture" in mobile["threshold_is_relative"])
absolute = bs.relaxed_brightness(relaxed_fixture(200, 40.0), "green", "max",
                                 absolute_curv_deg=5.0)
check("...and an absolute threshold is available instead",
      "absolute" in absolute["relaxation_rule"]
      and "threshold_is_relative" not in absolute)
check("an absolute threshold selects fewer frames from a mobile animal",
      absolute["n_relaxed_frames"] < mobile["n_relaxed_frames"],
      f"{absolute['n_relaxed_frames']} vs {mobile['n_relaxed_frames']}")

try:
    bs.relaxed_brightness(relaxed_fixture(60, 40.0), "green", "max",
                          absolute_curv_deg=0.001)
    check("too few relaxed frames is refused", False)
except bs.BrightnessError as exc:
    check("too few relaxed frames is refused", True)
    check("...saying a resting level from fewer is one posture",
          "is one posture" in str(exc))

try:
    bs.compare_statistics(real_rows[:5], "green")
    check("too few frames is refused", False)
except bs.BrightnessError as exc:
    check("too few frames is refused", True)
    check("...naming that it would measure the recording's noise",
          "measures the recording's noise" in str(exc))

mixed = real_rows[:20] + [dict(r, segment=12) for r in real_rows[:20]]
try:
    bs.compare_statistics(mixed, "green")
    check("pooling different segments is refused", False)
except bs.BrightnessError as exc:
    check("pooling different segments is refused", True)
    check("...naming that it compares different pieces of the animal",
          "different pieces of the animal" in str(exc))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("BRIGHTNESS_STATISTICS_PASS")
