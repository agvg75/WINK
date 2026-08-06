"""Calcium in cultured muscle cells, and what a recording can support.

Written against the lab's actual pilot data: single 8-bit 512x512 frames of
shRNA-knockdown smooth muscle progenitors, using 47 of 256 grey levels with a
median pixel of zero. The module must say clearly that eight of the nine
measurements are impossible from it, rather than returning numbers.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import numpy as np          # noqa: E402
import cell_calcium as cc   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("cell calcium - regression\n")

# --- the real pilot data ------------------------------------------------------
pilot = cc.check_recording(n_frames=1, ratiometric=True, bit_depth=8,
                           typical_signal=2.0)
check("only the baseline measure survives a single frame",
      pilot["n_supported"] == 1 and
      pilot["measurements"]["resting"]["supported"],
      f"{pilot['n_unsupported']} of 9 unsupported")
check("every kinetic measure is refused",
      all(not pilot["measurements"][k]["supported"]
          for k in ("peak_amplitude", "time_to_peak", "decay_tau", "fwhm",
                    "auc", "event_frequency", "store_content", "soce")))
check("...naming that a single frame has no time series",
      "single frame" in
      pilot["measurements"]["decay_tau"]["fails"][0])
check("8-bit ratiometry warns", any("grey levels" in w
                                    for w in pilot["warnings"]),
      "written first as a level count, where 8-bit gave exactly the threshold")
check("...quantifying what one grey level costs",
      any("changes the ratio by 33%" in w for w in pilot["warnings"]))
check("a dim signal warns separately from bit depth",
      any("exposure problem" in w for w in pilot["warnings"]))
check("...naming that more cells will not fix it",
      any("however many cells are measured" in w for w in pilot["warnings"]))

good = cc.check_recording(n_frames=600, ratiometric=True, bit_depth=16,
                          typical_signal=800)
check("a proper recording supports everything",
      good["n_unsupported"] == 0 and good["warnings"] == [])

# --- ratiometric versus single-wavelength ------------------------------------
single = cc.check_recording(n_frames=600, ratiometric=False, bit_depth=16,
                            typical_signal=800)
check("resting calcium is refused for a single-wavelength dye",
      single["measurements"]["resting"]["supported"] is False,
      "a higher baseline is indistinguishable from a better-loaded cell")
check("...but dF/F0 measures are fine, since they self-reference",
      single["measurements"]["peak_amplitude"]["supported"] is True)
check("SOCE also needs ratiometric, being a between-condition comparison",
      single["measurements"]["soce"]["supported"] is False)

# --- baselines ----------------------------------------------------------------
quiet = np.full(200, 100.0)
active = np.concatenate([np.full(20, 300.0), np.full(180, 100.0)])
check("a percentile baseline ignores an active start",
      abs(cc.baseline(active) - 100.0) < 1e-9,
      "the first frames are exactly where F0 is most likely to be wrong")
check("...where first-frames does not",
      cc.baseline(active, method="first_frames", frames=10) == 300.0)
check("both agree on a quiet trace", cc.baseline(quiet) == 100.0)

# --- a transient ---------------------------------------------------------------
fps = 20.0
t = np.arange(400) / fps
trace = 100.0 + 100.0 * np.exp(-np.clip(t - 2.0, 0, None) / 1.5) * (t >= 2.0)
trace[t < 2.0] = 100.0
tr = cc.transient(trace, fps)
check("a transient is detected", tr["detected"] is True)
check("amplitude is dF/F0", abs(tr["amplitude_dff"] - 1.0) < 0.05,
      f"{tr['amplitude_dff']:.2f}")
check("time to peak is in seconds", abs(tr["time_to_peak_s"] - 2.0) < 0.1)
check("the decay constant is recovered",
      abs(tr["decay_tau_s"] - 1.5) < 0.2, f"{tr['decay_tau_s']:.2f} s")
check("FWHM is measured", tr["fwhm_s"] > 0)
check("area under the curve is integrated in seconds", tr["auc_dff_s"] > 0)

flat = cc.transient(np.full(200, 100.0) + np.random.default_rng(0)
                    .normal(0, 0.5, 200), fps)
check("noise is not reported as a transient", flat["detected"] is False)
check("...naming that timing on it would describe noise",
      "describing noise" in flat["why"])

# Four clean points after a peak determine an exponential perfectly, which is
# how a truncated synthetic trace once returned exactly the right tau. Real
# data would not, so the guard is that the trace must have FALLEN, not merely
# that points exist.
truncated = cc.transient(trace[:int(2.2 * fps)], fps)
check("a recording that ends near the peak gives no tau",
      truncated.get("decay_tau_s") is None,
      "it only fell a little way, so the fit would extrapolate")
check("...naming that every tau looks alike at the top of the curve",
      "every tau looks alike" in truncated["caveat"])
check("a trace that DID fall still gives tau",
      cc.transient(trace[:int(5.0 * fps)], fps)["decay_tau_s"] is not None,
      "the guard must not refuse good data")

# An empty recording must not produce a dose-response. This exact trace shape
# came off the lab's ACh movies, where 96-98% of pixels were zero: a baseline
# of a fraction of a count, and scatter of the same size. transient() reported
# 100% of cells responding with dF/F0 up to 32 before this guard existed - the
# checks in check_recording were all in place and none of them ran, because
# they check a RECORDING and this takes a TRACE.
empty = np.abs(rng_empty := np.random.default_rng(3).normal(0, 0.5, 220))
try:
    cc.transient(empty, 7.5)
    check("a trace whose baseline is noise is refused", False)
except cc.CalciumError as exc:
    check("a trace whose baseline is noise is refused", True,
          "dividing by 0.1 counts turns one grey level into dF/F0 of 10")
    check("...naming that it would report the noise confidently",
          "report it confidently" in str(exc))
    check("...and that exposure, not analysis, is the fix",
          "no analysis recovers a signal that was never" in str(exc))

# The guard must not refuse real data. A genuine transient on a proper baseline
# has scatter far below its baseline.
noisy_real = 100.0 + np.random.default_rng(4).normal(0, 3, 400)
noisy_real[40:] += 80 * np.exp(-np.arange(360) / 30.0)
ok = cc.transient(noisy_real, 20.0)
check("a real transient on a solid baseline still passes",
      ok["detected"] and ok["amplitude_dff"] > 0.5,
      f"dF/F0 {ok['amplitude_dff']:.2f} on baseline 100 with SD 3")

try:
    cc.transient(trace, 0)
    check("a missing frame rate is refused", False)
except cc.CalciumError as exc:
    check("a missing frame rate is refused", True)
    check("...naming that time would be silently rescaled",
          "silently rescale time" in str(exc))

# --- the resting ratio ---------------------------------------------------------
a = np.full((10, 10), 200.0)
b = np.full((10, 10), 100.0)
r = cc.resting_ratio(a, b)
check("a ratio of sums is computed", abs(r["ratio"] - 2.0) < 1e-9)

edge_a = np.array([[100.0, 1.0]])
edge_b = np.array([[50.0, 0.001]])
per_pixel = float(np.mean(edge_a / edge_b))
check("a ratio of SUMS is not the mean of per-pixel ratios",
      abs(cc.resting_ratio(edge_a, edge_b)["ratio"] - per_pixel) > 100,
      "the mean of ratios is dominated by the dimmest pixels, which are the "
      "cell edges")

dim = cc.resting_ratio(np.full((10, 10), 3.0), np.full((10, 10), 2.0))
check("a dim ratio warns", bool(dim["warnings"]))
check("...saying it cannot be fixed downstream",
      "cannot be fixed downstream" in dim["warnings"][0])

try:
    cc.resting_ratio(np.zeros((4, 4)), np.zeros((5, 5)))
    check("mismatched channels are refused", False)
except cc.CalciumError as exc:
    check("mismatched channels are refused", True)
    check("...naming that it would picture the misalignment",
          "picture of the misalignment" in str(exc))

# --- comparing conditions ------------------------------------------------------
cmp = cc.compare_conditions(
    {"scramble": [1.0, 1.1, 0.95, 1.05], "Dp427": [1.6, 1.7, 1.55, 1.65],
     "Dp71": [1.05, 1.0, 1.1, 0.98]}, control="scramble")
check("effect sizes are reported per condition",
      cmp["per_condition"]["Dp427"]["vs_control_fold"] > 1.4)
check("...and the control is unchanged against itself",
      "vs_control_fold" not in cmp["per_condition"]["scramble"])
check("no p-value is invented", not any("p" == k for k in cmp))
check("...and the reason is stated",
      "not independent replicates" in cmp["note"],
      "cells in one dish share a passage, a loading and a coverslip")
try:
    cc.compare_conditions({"a": [1.0]}, control="missing")
    check("an absent control is refused", False)
except cc.CalciumError:
    check("an absent control is refused", True)

# --- the probe registry --------------------------------------------------------
# Andres: Fura-2 sometimes and Fluo-4 as well, plus mitochondrial oxidation
# indicators which may or may not be ratiometric, plus antibody staining in the
# same cultures. A boolean cannot express the last two.
fura = cc.check_recording(n_frames=600, probe="Fura-2", bit_depth=16,
                          typical_signal=800)
check("Fura-2 supports a resting level",
      fura["measurements"]["resting"]["supported"])
check("...and says the ratio is not a concentration until calibrated",
      "calibrated" in fura["probe_note"])

fluo = cc.check_recording(n_frames=600, probe="fluo-4", bit_depth=16,
                          typical_signal=800)
check("Fluo-4 refuses a resting level",
      not fluo["measurements"]["resting"]["supported"])
check("...but supports dF/F0", fluo["measurements"]["auc"]["supported"])

check("probe names are matched loosely",
      cc.normalise_probe("FURA 2") == "fura-2" and
      cc.normalise_probe("fura2") == "fura-2")
try:
    cc.check_recording(n_frames=10, probe="calcium-green")
    check("an unregistered probe is refused", False)
except cc.CalciumError as exc:
    check("an unregistered probe is refused", True)
    check("...naming the three axes that must not be guessed",
          "reversible" in str(exc) and "loading-independent" in str(exc))

# The axis a boolean flag cannot see. MitoSOX's product is stuck in the DNA, so
# a decay constant fits perfectly and describes nothing.
sox = cc.check_recording(n_frames=600, probe="MitoSOX", bit_depth=16)
check("an irreversible probe is refused a decay constant",
      not sox["measurements"]["decay_tau"]["supported"])
check("...and an FWHM", not sox["measurements"]["fwhm"]["supported"])
check("...but IS given an accumulation rate",
      sox["measurements"]["accumulation_rate"]["supported"],
      "the measure that replaces the kinetic panel rather than joining it")
check("...warning that the wrong measures would still fit",
      any("will still FIT this data" in w for w in sox["warnings"]))
check("a ratiometric flag alone would have allowed that decay constant",
      cc.check_recording(n_frames=600, ratiometric=False, bit_depth=16)
      ["measurements"]["decay_tau"]["supported"],
      "which is why the registry exists")

roGFP = cc.check_recording(n_frames=600, probe="grx1-roGFP2", bit_depth=16,
                           typical_signal=800)
check("a reversible redox sensor keeps its kinetics",
      roGFP["measurements"]["decay_tau"]["supported"])
check("...and is asked about oxidation, not calcium",
      "oxidation_ratio" in roGFP["measurements"] and
      "resting" not in roGFP["measurements"])
check("...with the pH confound named", "pH" in roGFP["probe_note"])

ab = cc.check_recording(n_frames=1, probe="antibody", bit_depth=16)
check("a fixed sample supports abundance",
      ab["measurements"]["expression_level"]["supported"])
check("...and is asked nothing kinetic at all",
      set(ab["measurements"]) == {"expression_level"})
ab_kin = cc.check_recording(n_frames=600, probe="antibody", bit_depth=16,
                            wants=["decay_tau", "resting"])
check("a fixed sample refuses kinetics even with 600 frames",
      not ab_kin["measurements"]["decay_tau"]["supported"],
      "frames of a fixed slide are not time")
check("...naming that there is no time in the sample",
      any("no time in it" in f
          for f in ab_kin["measurements"]["decay_tau"]["fails"]))

check("TMRM's sign ambiguity is recorded",
      "quench" in cc.PROBES["tmrm"]["note"] and
      "brighter" in cc.PROBES["tmrm"]["note"])

# --- transfected against untransfected ------------------------------------------
# Andres: one channel shows calcium, the other mCherry showing which cells were
# transfected; transfected vs non-transfected is the experiment.
design = cc.check_two_channel_design(
    signal_channel="ch00", marker_channel="ch01",
    segmentation_channel="ch00", conditions=["Dp427", "Dp71", "scramble"])
check("segmenting on the measurement channel warns",
      any("biased towards high signal" in w for w in design["warnings"]),
      "bright cells are easier to find, and the treatment moves brightness")
check("...pointing at the transmitted channel that exists for it",
      any("ch02" in w for w in design["warnings"]))
ok_design = cc.check_two_channel_design(
    signal_channel="ch00", marker_channel="ch01",
    segmentation_channel="ch02", conditions=["Dp427", "scramble"])
check("an independent segmentation channel does not warn",
      not ok_design["warnings"])
no_ctrl = cc.check_two_channel_design(
    signal_channel="ch00", marker_channel="ch01",
    segmentation_channel="ch02", conditions=["Dp427", "Dp71"])
check("a missing scramble warns",
      any("scrambled/control" in w for w in no_ctrl["warnings"]))
check("segmenting on the marker loses the internal control",
      any("untransfected cells cannot be found" in w for w in
          cc.check_two_channel_design(signal_channel="ch00",
                                      marker_channel="ch01",
                                      segmentation_channel="ch01")["warnings"]))

rng = np.random.default_rng(7)
bimodal = np.concatenate([rng.normal(10, 2, 60), rng.normal(120, 15, 20)])
cls = cc.classify_by_marker(bimodal)
check("a bimodal marker splits into the right counts",
      cls["n_positive"] == 20 and cls["n_negative"] == 60,
      f"{cls['n_positive']}+/{cls['n_negative']}- at {cls['threshold']:.0f}")
check("...and is not warned about", not cls["warnings"])

# A single normal distribution cut in half explains 0.64 of its variance. The
# first version of this check measured the gap in units of spread AFTER the
# ambiguous band was removed, which scored unimodal data at 7 sigma.
unimodal = rng.normal(50, 10, 300)
uni = cc.classify_by_marker(unimodal)
check("a unimodal marker is flagged as not bimodal", bool(uni["warnings"]))
check("...at close to the 0.64 a split normal gives",
      0.5 < uni["separability"] < 0.75, f"{uni['separability']:.2f}")
check("a bimodal marker scores far above that",
      cls["separability"] > 0.9, f"{cls['separability']:.2f}")
boundary = cc.classify_by_marker(
    np.array([10.0, 12, 14, 54, 56, 58, 100, 102, 104]), threshold=55)
check("cells at the boundary are held out rather than forced",
      boundary["n_ambiguous"] == 3 and boundary["n_positive"] == 3 and
      boundary["n_negative"] == 3,
      "a graded marker means a graded knockdown, so these are the least "
      "certain cells")

# With a clean gap between the clusters, every threshold inside it ties. Taking
# the lowest put the boundary on the shoulder of the untransfected cluster and
# the exclusion band then swallowed 12 real negatives.
check("the threshold lands in the middle of an empty gap, not at its edge",
      30 < cls["threshold"] < 100, f"{cls['threshold']:.0f}")

# Bleed-through: the artefact that points the same way as the hypothesis.
marker = np.concatenate([rng.uniform(0, 5, 30), rng.uniform(50, 200, 20)])
positive = marker > 25
clean = np.concatenate([rng.normal(100, 10, 30), rng.normal(140, 10, 20)])
bled = clean.copy()
bled[positive] = 100 + 0.3 * marker[positive] + rng.normal(0, 3, positive.sum())
check("a real all-or-none effect is not called bleed-through",
      not cc.marker_bleedthrough(clean, marker, positive)["suspect"],
      "knockdown either happened or did not; it does not scale with mCherry")
bt = cc.marker_bleedthrough(bled, marker, positive)
check("signal scaling with marker brightness IS called bleed-through",
      bt["suspect"], f"r = {bt['r']:+.2f}")
check("...naming the control that would settle it",
      any("dye-free" in w for w in bt["warnings"]))
thin = cc.marker_bleedthrough(clean[:4], marker[:4],
                              np.ones(4, dtype=bool))
check("too few cells is reported as 'did not run', not as a pass",
      not thin["suspect"] and
      any("did not run" in w for w in thin["warnings"]),
      "silence from a check that never ran reads as reassurance")

# The field is the unit, not the cell.
def field(name, cond, pos_level, n_pos=8, n_neg=25):
    return {"field": name, "condition": cond,
            "signal": np.concatenate([rng.normal(pos_level, 8, n_pos),
                                      rng.normal(100, 8, n_neg)]),
            "marker": np.concatenate([rng.uniform(80, 200, n_pos),
                                      rng.uniform(0, 5, n_neg)])}


paired = cc.paired_field_comparison([
    field("f1", "Dp427", 150), field("f2", "Dp427", 145),
    field("f3", "Dp427", 155), field("f4", "scramble", 101),
    field("f5", "scramble", 99), field("f6", "scramble", 100),
])
check("each field yields one paired comparison",
      len(paired["per_field"]) == 6)
check("the knockdown condition shows a raised ratio",
      paired["by_condition"]["Dp427"]["median_ratio"] > 1.3,
      f"{paired['by_condition']['Dp427']['median_ratio']:.2f}")
check("the scramble sits at unity",
      abs(paired["by_condition"]["scramble"]["median_ratio"] - 1) < 0.1)
check("the unit is stated as the field, with the cell count behind it",
      "unit here is the field" in paired["note"] and
      "6 paired comparisons" in paired["note"])
check("...and pairing is credited with cancelling loading",
      "cancels loading" in paired["note"])

# The check that makes the scramble worth running.
bad_ctrl = cc.paired_field_comparison([
    field("g1", "scramble", 130), field("g2", "scramble", 135),
    field("g3", "scramble", 128),
])
check("a scramble that is NOT at unity is called out",
      any("transfection itself moving calcium" in w
          for w in bad_ctrl["warnings"]),
      "lipid stress, bleed-through, or which cells take up plasmid")
check("...saying the knockdowns must be read against it, not against 1.0",
      any("not against 1.0" in w for w in bad_ctrl["warnings"]))

thin_field = cc.paired_field_comparison([
    field("h1", "Dp71", 150, n_pos=1, n_neg=30),
    field("h2", "Dp71", 150, n_pos=9, n_neg=30),
])
check("a field with too few transfected cells is skipped",
      len(thin_field["per_field"]) == 1 and
      len(thin_field["skipped_fields"]) == 1)
check("...and listed, because losing them is itself a selection",
      any("selection" in w for w in thin_field["warnings"]),
      "the worst-transfected fields are the ones that drop out")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("CELL_CALCIUM_PASS")
