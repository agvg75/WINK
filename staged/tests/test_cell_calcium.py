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

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("CELL_CALCIUM_PASS")
