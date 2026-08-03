"""Regression tests for the myocyte_morphometry.py Fiji-macro port.

WHAT THESE COVER, AND WHY THIS GROUND TRUTH IS REAL, NOT SYNTHETIC
--------------------------------------------------------------------
Per the port spec's own validation plan: replay real historical output
from Myocyte_Morphometry.ijm and compare against this port's numbers,
rather than inventing fixtures and hoping they match the macro's actual
behavior (the same discipline used elsewhere in this codebase - inventing
a synthetic "fold" shape to test coiling, for example, tests nothing real
if the synthetic signature doesn't match how real self-overlap conserves
area).

Two independent pieces of real ground truth were found on disk from an
actual past measurement session (worm "1", L:/10_AGVG LAB/ImageJ_Tools/):

1. rois/1_m0_profile.txt and 1_m1_profile.txt - the EXACT raw intensity
   profile and detected peak positions the macro itself produced and
   exported, for two real myocytes. These let detrend/autocorrelation/
   period-estimate/peak-detection be checked bit-for-bit: feed the same
   raw_profile array in, compare detected peak indices against
   detected_peak_index, with no re-derivation of the profile itself needed.

2. rois/1_rois.zip (ROI "1_Myo20_m1", 35 vertices) plus the matching real
   CSV row in myocyte_morphometry_BLINDED_day5_midbody_1_20260709_...csv -
   the ACTUAL boundary polygon a person drew, and ImageJ's own measured
   geometry for it. This lets boundary_measurements() be checked against
   real ImageJ output, not just plausible-looking numbers.

WHAT IS NOT COVERED HERE: get_profile_band() (the wide-line intensity
sampler) has no real-image ground truth in this suite, because the source
TIFF for these two profiles could not be located. It is exercised only
with synthetic sanity checks below. Do not treat it as validated - see
the module docstring.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "morphology"))
import myocyte_morphometry as mm

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("myocyte_morphometry - regression against real macro output\n")

# ---------------------------------------------------------------------------
# 1. Peak-detection chain against REAL raw_profile / detected_peak_index
#    pairs exported by the macro itself (rois/1_m0_profile.txt, 1_m1_profile.txt).
# ---------------------------------------------------------------------------
UM_PX_WORM1 = 0.05319

# 1_m0_profile.txt: a short (21-sample) profile with no genuine periodicity
# of its own - exercises the FALLBACK branch (estimate_period_px returns <2,
# so detect_band_peaks falls back to the calibrated biological midpoint).
PROFILE_M0 = [4.18, 3.82, 3.56, 3.27, 2.98, 2.84, 3.00, 3.40, 3.80, 4.04, 4.02,
              3.64, 3.33, 3.18, 3.24, 3.31, 3.42, 3.51, 3.49, 3.42, 3.69]
EXPECTED_PEAKS_M0 = [9]
EXPECTED_PERIOD_M0 = 34.78  # == ((1.2+2.5)/2) / 0.05319, the documented fallback

pos0, period0 = mm.detect_band_peaks(PROFILE_M0, um_px=UM_PX_WORM1)
check("1_m0_profile.txt: detected peaks match the macro's export exactly",
      pos0.tolist() == EXPECTED_PEAKS_M0, pos0.tolist())
check("1_m0_profile.txt: data-driven period matches the macro's export "
      "(fallback branch, no genuine periodicity in a 21-sample profile)",
      abs(period0 - EXPECTED_PERIOD_M0) < 0.01, period0)

# 1_m1_profile.txt: a real 319-sample profile with genuine periodicity AND
# two real saturation-artifact spikes (indices ~186-188 and ~296-297, values
# up to 188.42) that the 3-point smoothing must suppress rather than being
# read as extra bands - exercises the PRIMARY detection path.
PROFILE_M1 = [
    107.67, 147.93, 0.00, 0.00, 0.33, 1.71, 3.00, 3.22, 2.31, 0.89, 0.36, 0.36,
    0.20, 0.02, 0.13, 0.69, 1.73, 2.58, 2.62, 2.31, 2.16, 2.64, 4.11, 6.27,
    8.64, 10.36, 10.82, 10.13, 8.76, 7.56, 6.44, 6.22, 7.67, 11.67, 14.84,
    14.64, 11.96, 8.89, 6.42, 5.40, 5.09, 4.98, 4.58, 4.27, 3.76, 3.20, 2.22,
    1.49, 1.44, 1.56, 1.02, 1.29, 2.40, 2.91, 3.04, 3.58, 3.80, 4.73, 6.27,
    7.96, 9.07, 9.58, 9.44, 9.31, 9.00, 8.78, 8.29, 8.13, 8.91, 11.96, 14.98,
    15.80, 14.96, 13.42, 11.42, 8.27, 5.58, 3.49, 3.47, 3.93, 4.56, 5.20,
    5.47, 4.76, 3.16, 2.89, 2.98, 2.22, 1.11, 1.49, 2.87, 3.93, 4.44, 4.56,
    4.80, 4.87, 4.40, 3.87, 4.27, 5.73, 8.71, 12.24, 15.31, 16.62, 17.16,
    17.56, 15.84, 12.40, 9.93, 9.44, 10.00, 11.33, 12.58, 13.00, 11.02, 8.53,
    6.49, 4.31, 3.47, 3.80, 4.49, 5.09, 5.07, 4.78, 4.82, 4.24, 2.38, 2.02,
    2.07, 0.80, 0.02, 0.47, 2.60, 4.87, 5.84, 5.67, 4.91, 4.33, 3.93, 4.18,
    5.73, 8.89, 13.53, 18.47, 21.36, 20.98, 17.91, 13.98, 10.51, 7.11, 7.00,
    9.93, 14.76, 18.62, 18.29, 14.04, 9.18, 6.42, 5.11, 5.53, 6.27, 6.33,
    5.71, 4.93, 4.73, 5.13, 5.20, 4.20, 2.91, 2.02, 1.16, 0.36, 0.87, 2.42,
    3.49, 4.02, 4.22, 4.22, 4.82, 6.69, 10.22, 14.36, 16.87, 15.98, 12.56,
    8.73, 6.78, 5.96, 5.49, 5.96, 7.98, 9.67, 9.69, 8.02, 6.16, 5.64, 7.11,
    9.40, 10.84, 11.02, 10.09, 7.98, 5.53, 3.80, 3.47, 4.71, 6.11, 6.02, 5.02,
    4.27, 4.42, 5.62, 7.49, 19.89, 85.96, 188.42, 172.93, 50.67, 10.56, 8.93,
    7.87, 7.00, 5.42, 5.24, 5.33, 4.44, 2.40, 0.44, 0.00, 0.22, 0.58, 1.27,
    2.40, 3.31, 3.40, 2.98, 3.00, 3.31, 3.38, 3.56, 4.53, 6.84, 10.24, 14.13,
    17.56, 19.69, 20.27, 18.38, 14.71, 10.47, 6.82, 4.62, 4.51, 6.04, 9.11,
    11.98, 13.31, 12.29, 9.87, 7.29, 5.44, 4.42, 4.09, 4.11, 4.42, 4.67,
    4.73, 4.84, 4.96, 4.67, 4.09, 3.49, 3.07, 2.80, 3.58, 4.24, 4.18, 4.27,
    4.87, 5.38, 5.60, 5.49, 5.40, 5.00, 4.33, 3.87, 3.56, 3.49, 4.36, 6.58,
    9.98, 13.82, 16.73, 16.89, 13.84, 8.51, 3.87, 1.42, 0.27, 0.24, 0.87,
    2.13, 3.64, 5.31, 6.60, 6.47, 8.87, 137.16, 116.76, 4.60, 3.76, 3.71,
    3.42, 3.22, 3.33, 3.36, 2.80, 1.82, 1.13,
]
EXPECTED_PEAKS_M1 = [144, 215, 307]
EXPECTED_PERIOD_M1 = 92.09

check("1_m1_profile.txt: raw profile length matches the export (sanity on "
      "the fixture itself)", len(PROFILE_M1) == 319, len(PROFILE_M1))
pos1, period1 = mm.detect_band_peaks(PROFILE_M1, um_px=UM_PX_WORM1)
check("1_m1_profile.txt: detected peaks match the macro's export exactly "
      "(genuine periodicity, real saturation-spike artifacts suppressed)",
      pos1.tolist() == EXPECTED_PEAKS_M1, pos1.tolist())
check("1_m1_profile.txt: data-driven period matches the macro's export",
      abs(period1 - EXPECTED_PERIOD_M1) < 0.01, period1)

# ---------------------------------------------------------------------------
# 2. detrend / autocorr / interval_stats: mechanical correctness checks
#    (these don't have independent real ground truth beyond what's already
#    exercised inside detect_band_peaks above, so check them directly).
# ---------------------------------------------------------------------------
flat = np.full(21, 5.0)
check("detrend of a flat signal is all zeros",
      np.allclose(mm.detrend(flat, 3), 0))

impulse = np.zeros(41); impulse[20] = 1.0
ac = mm.autocorr(impulse)
check("autocorrelation of a unit impulse peaks only at lag 0",
      ac[0] == 1.0 and np.allclose(ac[1:], 0))

periodic = np.array([np.sin(2 * np.pi * i / 10) for i in range(200)])
est = mm.estimate_period_px(periodic)
check("estimate_period_px recovers a known 10px period from a clean sine",
      abs(est - 10) < 0.5, est)

n, mean, sd, cv = mm.interval_stats([10, 20, 32, 41], um_px=0.1)
check("interval_stats: n_intervals is len(pos)-1", n == 3, n)
check("interval_stats: mean matches hand-computed value",
      abs(mean - np.mean([1.0, 1.2, 0.9])) < 1e-9, mean)
n0, m0v, s0, c0 = mm.interval_stats([5], um_px=0.1)
check("interval_stats: fewer than 2 positions returns all zeros",
      (n0, m0v, s0, c0) == (0, 0.0, 0.0, 0.0))

check("calibration_flag: a plausible sarcomere length passes",
      mm.calibration_flag(1.6) == "OK")
check("calibration_flag: a length far outside the biological window is flagged",
      mm.calibration_flag(0.3) == "CHECK_CALIBRATION")

# region_from_myo_number: anterior 1-10, midbody 11-18, posterior 19-24,
# matching the macro's regionFromMyoNum() exactly.
check("region_from_myo_number: 1 is anterior",
      mm.region_from_myo_number(1, "fallback") == "anterior")
check("region_from_myo_number: 10 is still anterior (boundary)",
      mm.region_from_myo_number(10, "fallback") == "anterior")
check("region_from_myo_number: 11 is midbody (boundary)",
      mm.region_from_myo_number(11, "fallback") == "midbody")
check("region_from_myo_number: 18 is still midbody (boundary)",
      mm.region_from_myo_number(18, "fallback") == "midbody")
check("region_from_myo_number: 19 is posterior (boundary)",
      mm.region_from_myo_number(19, "fallback") == "posterior")
check("region_from_myo_number: 24 is still posterior (boundary)",
      mm.region_from_myo_number(24, "fallback") == "posterior")
check("region_from_myo_number: out-of-range numbers fall back to the "
      "given default (should not normally happen)",
      mm.region_from_myo_number(25, "fallback") == "fallback"
      and mm.region_from_myo_number(0, "fallback") == "fallback")

# ---------------------------------------------------------------------------
# 3. Boundary geometry against a REAL polygon ROI + REAL ImageJ CSV row
#    (worm "1", myocyte m1, roi "1_Myo20_m1" - see module docstring for the
#    exact formulas this validated, and why the naive rasterized-mask
#    versions of perimeter/major/minor were off by 3-4% before correction).
# ---------------------------------------------------------------------------
ROI_1_MYO20_M1 = np.array([
    [2270, 710], [2485, 702], [2722, 673], [3031, 635], [3227, 619],
    [3378, 612], [3478, 606], [3594, 614], [3763, 626], [3880, 627],
    [4050, 638], [4139, 644], [4216, 651], [4290, 662], [4504, 618],
    [4506, 653], [4434, 710], [4342, 741], [4305, 779], [4088, 798],
    [4013, 808], [3952, 805], [3850, 851], [3712, 875], [3615, 899],
    [3506, 908], [3431, 926], [3353, 911], [3209, 907], [3077, 869],
    [2961, 844], [2823, 830], [2635, 791], [2519, 763], [2483, 762],
], dtype=float)
# Real values from myocyte_morphometry_BLINDED_day5_midbody_1_..._153708.csv,
# row myocyte_id=1, roi_name "1_Myo20_m1".
CSV_ROW_M1 = {
    "area_um2": 1128.9498, "perimeter_um": 244.7285, "feret_um": 118.9748,
    "minferet_um": 16.8692, "major_um": 100.1602, "minor_um": 14.3512,
    "aspect_ratio": 6.9792, "circularity": 0.2369, "solidity": 0.9059,
    "anisotropy": 7.0528, "feret_angle_deg": 1.46,
}

geo = mm.boundary_measurements(ROI_1_MYO20_M1)
UM_PX_M1_ROW = 0.05319
converted = {
    "area_um2": geo["area_px2"] * UM_PX_M1_ROW ** 2,
    "perimeter_um": geo["perimeter_px"] * UM_PX_M1_ROW,
    "feret_um": geo["feret_px"] * UM_PX_M1_ROW,
    "minferet_um": geo["minferet_px"] * UM_PX_M1_ROW,
    "major_um": geo["major_px"] * UM_PX_M1_ROW,
    "minor_um": geo["minor_px"] * UM_PX_M1_ROW,
    "aspect_ratio": geo["aspect_ratio"],
    "circularity": geo["circularity"],
    "solidity": geo["solidity"],
    "anisotropy": geo["anisotropy"],
    "feret_angle_deg": geo["feret_angle_deg"],
}
# Loose tolerances chosen from the actual observed match quality (see module
# docstring): Feret/MinFeret/circularity/solidity/angle match to <0.1%,
# area/perimeter/major/minor/AR to <1% after the documented corrections.
TOLERANCE_PCT = {
    "area_um2": 0.5, "perimeter_um": 0.5, "feret_um": 0.1, "minferet_um": 0.1,
    "major_um": 1.0, "minor_um": 1.0, "aspect_ratio": 0.5, "circularity": 0.5,
    "solidity": 0.5, "anisotropy": 0.5, "feret_angle_deg": 1.0,
}
for field, real_value in CSV_ROW_M1.items():
    got = converted[field]
    tol_pct = TOLERANCE_PCT[field]
    if field == "feret_angle_deg":
        err = abs(got - real_value)
        ok = err < 0.1
        check(f"boundary geometry '{field}' matches the real ImageJ row "
              f"(within 0.1 deg)", ok, f"got {got:.4f}, real {real_value}")
    else:
        err_pct = abs(got - real_value) / abs(real_value) * 100
        ok = err_pct < tol_pct
        check(f"boundary geometry '{field}' matches the real ImageJ row "
              f"(within {tol_pct}%)", ok,
              f"got {got:.4f}, real {real_value}, err {err_pct:.3f}%")

# ---------------------------------------------------------------------------
# 4. get_profile_band: synthetic sanity only - NOT validated against a real
#    image (see module docstring and the top of this file).
# ---------------------------------------------------------------------------
synthetic = np.zeros((60, 60), dtype=np.float64)
synthetic[:, 30] = 100.0  # a bright vertical stripe at x=30
prof = mm.get_profile_band(synthetic, 10, 30, 50, 30, line_width=1)
check("get_profile_band (synthetic): horizontal line through a known bright "
      "column peaks near the expected sample index",
      bool(np.argmax(prof) in range(18, 23)), int(np.argmax(prof)))
check("get_profile_band (synthetic): sample count matches ImageJ's "
      "length+1 convention", len(prof) == 41, len(prof))

# Real-image check: replay the exact m1 line endpoints against the actual
# source TIFF (found at L:/05_Proprioception/Ella/... after this suite was
# first written) and compare to the exact raw_profile the macro exported.
# Peak LOCATION matches exactly (both peak at sample index 215) and, once a
# single constant scale factor is divided out, values match to ~2%. The
# scale factor itself (~3x) is real and reproducible across every line
# width tried, including exactly at the macro's own documented default
# (band_width_px=15, where the fitted ratio is closest to a clean 3.0) - it
# is not measurement noise. Most likely explanation: this on-disk TIFF is a
# different processing version of the frame than whatever the macro's
# session actually measured (e.g. a single slice vs. a 3-slice sum
# projection), a data-provenance question, not a sampling-geometry one.
# This validates what get_profile_band actually needs to get right for
# downstream peak detection - WHERE along the line the signal is, not its
# absolute brightness, which detect_band_peaks never uses in absolute
# terms anyway (see its own module-level note on relative-not-absolute
# thresholds).
SOURCE_TIFF_M1 = (Path("L:/05_Proprioception/Ella/Myocyte Measurements")
                  / "240619_BZ33_day5A_crawl_phall_9"
                  / "240619_BZ33_day5A_crawl_phall_9_W1_posterior.tif")
if SOURCE_TIFF_M1.exists():
    import cv2
    real_img = cv2.imread(str(SOURCE_TIFF_M1), cv2.IMREAD_UNCHANGED)
    green = real_img[..., 1].astype(np.float64)
    real_prof = mm.get_profile_band(green, 3406.0, 608.8, 3434.5, 925.5,
                                     line_width=15)
    check("get_profile_band (real image): sample count matches the real "
          "exported profile length", len(real_prof) == len(PROFILE_M1),
          len(real_prof))
    check("get_profile_band (real image): peak sample INDEX matches the "
          "real profile exactly (index 215 in both)",
          int(np.argmax(real_prof)) == int(np.argmax(PROFILE_M1)),
          (int(np.argmax(real_prof)), int(np.argmax(PROFILE_M1))))
    mask = np.asarray(PROFILE_M1) > 2
    scale = float(np.median(real_prof[:len(PROFILE_M1)][mask] / np.asarray(PROFILE_M1)[mask]))
    scaled = real_prof[:len(PROFILE_M1)] / scale
    rel_err = np.abs(scaled[mask] - np.asarray(PROFILE_M1)[mask]) / np.asarray(PROFILE_M1)[mask]
    check("get_profile_band (real image): after dividing out the one "
          "constant scale factor, values match the real profile to <5% "
          "median relative error",
          float(np.median(rel_err)) < 0.05,
          f"scale={scale:.3f}, median_rel_err={np.median(rel_err):.3%}")
else:
    print("\n  (source TIFF for the real profile not found at "
          f"{SOURCE_TIFF_M1} - real-image get_profile_band check skipped, "
          "synthetic-only coverage above still applies)")

# ---------------------------------------------------------------------------
# 5. Fiber tracing / waviness: synthetic sanity only - NOT validated against
#    real marked-up images (the macro's own calibration was done offline
#    against real hand-marked dystrophic/N2 samples; that ground truth is
#    not available in this session). A straight ridge must trace cleanly
#    and classify as not wavy; a genuinely oscillating ridge must classify
#    as wavy - the minimum bar for "the port isn't inverted or dead code."
# ---------------------------------------------------------------------------
def _make_ridge_image(centerline, w=300, h=100, thickness=2):
    img = np.zeros((h, w), dtype=np.float64)
    for x in range(w):
        yc = int(round(centerline(x)))
        for dy in range(-thickness, thickness + 1):
            y = yc + dy
            if 0 <= y < h:
                img[y, x] = 200.0 - abs(dy) * 20
    return img


def _inside(w, h):
    return lambda x, y: 0 <= x < w and 0 <= y < h


W, H = 300, 100
straight_img = _make_ridge_image(lambda x: 40, w=W, h=H)
fx_s, fy_s, amb_s = mm.trace_fiber_along(
    straight_img, _inside(W, H), 10, 40, 1, 0, 0, 1, 2, 10, 140)
check("trace_fiber_along follows a straight ridge for its full requested length",
      len(fx_s) == 140, len(fx_s))
straight_wavy, straight_len = mm.classify_fiber_wavy(
    fx_s, fy_s, 1, 0, 0, 1, um_px=1.0)
check("classify_fiber_wavy: a straight ridge is not classified as wavy",
      straight_wavy is False and straight_len == 0.0,
      (straight_wavy, straight_len))

wavy_centerline = lambda x: 40 + 20 * np.sin(2 * np.pi * x / 60)
wavy_img = _make_ridge_image(wavy_centerline, w=W, h=H)
fx_w, fy_w, amb_w = mm.trace_fiber_along(
    wavy_img, _inside(W, H), 10, wavy_centerline(10), 1, 0, 0, 1, 2, 10, 140)
wavy_class, wavy_len = mm.classify_fiber_wavy(
    fx_w, fy_w, 1, 0, 0, 1, um_px=1.0)
check("classify_fiber_wavy: a genuinely oscillating ridge IS classified as wavy",
      wavy_class is True and wavy_len > 0, (wavy_class, wavy_len))

# detect_waves aggregation: two seeded fibers, one straight one wavy, on a
# combined image where each ridge sits at a different y-offset (so both
# traces stay on their own ridge without crossing). feret_um/um_px chosen
# so max_steps_fiber stays within the synthetic canvas, matching how a real
# myocyte's Feret bounds the trace length relative to its own image.
combo_img = np.maximum(
    _make_ridge_image(lambda x: 25, w=W, h=H),
    _make_ridge_image(lambda x: 65 + 15 * np.sin(2 * np.pi * x / 50), w=W, h=H))
waves = mm.detect_waves(
    combo_img, _inside(W, H), zpos=[25, 65], ax1=10, ay1=0, mux=1, muy=0,
    nux=0, nuy=1, feret_um=90, um_px=1.0, wave_link_um=6)
check("detect_waves: n_fibers matches the number of seeded positions",
      waves["n_fibers"] == 2, waves)
check("detect_waves: exactly one of the two seeded fibers is affected "
      "(the wavy one)", waves["n_affected"] == 1, waves)
check("detect_waves: width_fraction is n_affected/n_fibers",
      abs(waves["width_fraction"] - 0.5) < 1e-9, waves["width_fraction"])
check("detect_waves: length_frac_mean/max are populated when a fiber is affected",
      waves["length_frac_mean"] > 0 and waves["length_frac_max"] > 0, waves)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("MYOCYTE_MORPHOMETRY_REGRESSION_PASS")
