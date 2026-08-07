"""Declared fields, flat-field scope, and per-cell censoring.

Every rule pinned here was established against Naga's real acquisition:
3,676 frames, 8-bit, baseline median 21, series maximum 255 reached by frame
~1040 and held for the remaining two thirds.

TIME_TO_PEAK DOES NOT SURVIVE CLIPPING, and this is the check most likely to
be argued with later. For a saturated cell the recorded peak is the FIRST
frame that reached the ceiling, so the measure becomes time-to-ceiling. That
is a lower bound, and a biased one: a stronger responder reaches the ceiling
sooner, so the bias runs OPPOSITE to the effect and shrinks exactly the cells
with the largest true response. It looks robust and is not.

CENSORING IS PER CELL. A series maximum of 255 does not censor a recording;
it censors the cells that reached it. Cells that never approached the ceiling
are unaffected and their numbers stand.

FLAT FIELD IS SPATIAL, NEVER TEMPORAL. Adherent cells do not move at all, so
a temporal median over the series CONTAINS them and subtracting it removes
the signal. The same error was made once on the worm side with a crawling
animal, which at least moves.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app")]

import cell_population as cp   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("\n--- clipping censors per CELL, not per series -----------------")

# Three cells: one saturates, one is bright but clear, one is quiet.
traces = np.array([
    [20, 40, 120, 255, 255, 255, 200, 90],     # saturates
    [20, 35, 90, 180, 210, 160, 80, 40],       # strong, never clips
    [20, 21, 22, 23, 22, 21, 20, 20],          # no response
], dtype=float)
flags = cp.flag_saturated(traces, bit_depth=8)

check("the saturated cell is flagged", flags[0]["saturated"])
check("...with the frame it first hit the ceiling",
      flags[0]["first_ceiling_frame"] == 3)
check("...and how long it stayed there",
      flags[0]["n_frames_at_ceiling"] == 3)
check("the bright but unclipped cell is NOT flagged",
      not flags[1]["saturated"],
      "210 of 255 is a measurement, not a censored one")
check("the quiet cell is not flagged", not flags[2]["saturated"])
check("one flag per cell, never one per series", len(flags) == 3)

print("\n--- what clipping actually costs ------------------------------")

check("peak-dependent measures are censored for the flagged cell",
      all(m in flags[0]["censored_measures"]
          for m in ("peak_amplitude", "auc", "soce", "fwhm", "decay_tau")))
check("TIME_TO_PEAK is censored too",
      "time_to_peak" in flags[0]["censored_measures"],
      "for a clipped cell it is time-to-CEILING: a lower bound whose bias "
      "runs opposite to the effect")
check("...and nothing is censored for the unclipped cells",
      flags[1]["censored_measures"] == []
      and flags[2]["censored_measures"] == [])
check("responding fraction is NOT in the censored set",
      "responding_fraction" not in cp.CENSORED_BY_SATURATION,
      "it depends on crossing a level, not on where the trace ended")
check("...and is named as robust",
      "responding_fraction" in cp.ROBUST_TO_SATURATION)
check("onset by threshold crossing is robust",
      "onset_time" in cp.ROBUST_TO_SATURATION)

check("the ceiling follows the bit depth",
      cp.saturation_level(8) == 255 and cp.saturation_level(16) == 65535)
check("a 16-bit trace peaking at 255 is not saturated",
      not cp.flag_saturated([[20, 255, 40]], bit_depth=16)[0]["saturated"],
      "255 is a ceiling only for 8-bit data")

print("\n--- the source declares its own sampling bias -----------------")

check("max projection warns it biases towards RESPONDERS",
      "RESPONDERS" in cp.describe_source("max_projection"))
check("...and says why that is circular",
      "numerator" in cp.describe_source("max_projection"))
check("std projection carries the same warning",
      "RESPONDERS" in cp.describe_source("std_projection"))
check("pre-stimulus mean warns about LOADING, not responders",
      "WELL-LOADED" in cp.describe_source("pre_stimulus_mean")
      and "does NOT bias towards responders"
      in cp.describe_source("pre_stimulus_mean"))
check("a separate channel is the only unbiased option",
      "no response or loading bias"
      in cp.describe_source("separate_channel"))

raised = False
try:
    cp.describe_source("whatever_was_handy")
except ValueError:
    raised = True
check("an undeclared source is refused, not defaulted", raised)

source, why = cp.propose_source(n_frames=3676)
check("a series proposes the pre-stimulus mean",
      source == "pre_stimulus_mean")
check("...explaining the circularity it avoids", "numerator" in why)
check("a separate channel is preferred when one exists",
      cp.propose_source(3676, has_separate_channel=True)[0]
      == "separate_channel")
check("a single frame proposes single_frame",
      cp.propose_source(1)[0] == "single_frame")

print("\n--- stimulus onset is proposed, never assumed -----------------")

trace = np.concatenate([np.full(40, 21.0) + np.random.default_rng(0)
                        .normal(0, 0.4, 40), np.linspace(21, 140, 60)])
frame, why = cp.propose_stimulus_onset(trace)
check("onset is found near the true rise", frame is not None and 38 <= frame <= 46,
      f"proposed frame {frame}")
check("...and states the pre-stimulus window", "pre-stimulus window" in why)
check("...and asks for confirmation", "Confirm" in why)

flat, why_flat = cp.propose_stimulus_onset(np.full(120, 21.0))
check("a flat trace yields NO onset", flat is None,
      "no stimulus is a finding, not a reason to pick the largest jump")
check("...and says so", "neither is a reason" in why_flat)
check("one bright frame does not define an onset",
      cp.propose_stimulus_onset(
          np.concatenate([np.full(60, 21.0), [200.0], np.full(59, 21.0)])
      )[0] is None,
      "three consecutive frames are required")
check("too short a trace is refused",
      cp.propose_stimulus_onset(np.arange(6.0))[0] is None)

print("\n--- flat field: spatial, and for segmentation only ------------")

rng = np.random.default_rng(1)
y, x = np.mgrid[0:120, 0:160]
vignette = 1.0 - 0.6 * (((x - 80) / 110.0) ** 2 + ((y - 60) / 90.0) ** 2)
field = (20 * vignette + rng.normal(0, 0.5, (120, 160))).astype(np.float32)
field[40:48, 60:70] = 200.0                      # a bright cell
corrected, factor, record = cp.flat_field(field)

edge_before = float(field[5:15, 5:15].mean() / field[55:65, 75:85].mean())
edge_after = float(corrected[5:15, 5:15].mean()
                   / corrected[55:65, 75:85].mean())
check("the vignette is flattened",
      abs(1 - edge_after) < abs(1 - edge_before),
      f"corner/centre {edge_before:.2f} -> {edge_after:.2f}")
check("the cell survives correction",
      corrected[40:48, 60:70].mean() > 3 * np.median(corrected),
      "a kernel narrower than a cell would erase it")
check("the record names the method", "spatial median" in record["method"])
check("...and the kernel scale", "kernel" in record["scale"])
check("...and states that measurement uses RAW pixels",
      "RAW" in record["applies_to"],
      "segment on corrected, measure on raw")

mask = np.zeros(field.shape, bool)
mask[40:48, 60:70] = True
check("a per-cell correction factor is exportable",
      cp.correction_factor_for(factor, mask) is not None)
check("...and an empty mask yields None rather than a number",
      cp.correction_factor_for(factor, np.zeros_like(mask)) is None)


print("\n--- segment once, then gate reuse on drift --------------------")

check("per-frame re-detection is excluded", not cp.PER_FRAME_REDETECTION)
check("...and the reason is the measured swing",
      "14-24" in cp.REDETECTION_EXCLUDED_BECAUSE)
check("...naming the circularity it creates",
      "responding fraction" in cp.REDETECTION_EXCLUDED_BECAUSE)
check("segment-once is the policy", cp.SEGMENT_ONCE)

base = np.zeros((120, 160), np.float32)
base[50:60, 70:82] = 200.0
base[20:26, 30:38] = 160.0
still = base.copy()
shifted = np.roll(np.roll(base, 14, axis=1), 9, axis=0)

offset, info = cp.drift_offset(base, still)
check("an unmoved field measures near zero drift", offset < 1.0,
      f"{offset:.2f} px")
moved, _ = cp.drift_offset(base, shifted)
check("a shifted field measures its shift",
      abs(moved - np.hypot(14, 9)) < 3.0,
      f"{moved:.1f} px against a true {np.hypot(14, 9):.1f}")

ok = cp.check_drift(base, [still, still])
check("no drift passes the gate", ok["max_drift_px"] < cp.MAX_DRIFT_PX)

raised = ""
try:
    cp.check_drift(base, [still, shifted])
except ValueError as exc:
    raised = str(exc)
check("drift beyond the limit FAILS LOUDLY", bool(raised))
check("...naming the measured offset", "px" in raised and "drifted" in raised)
check("...and what it would have done silently",
      "wrong pixels" in raised,
      "reused outlines would sample the wrong cells with nothing looking wrong")

print("\n--- hand-added cells are their own provenance -----------------")

check("human_added is distinct from human_reshaped",
      "human_added" in cp.CORRECTION_PROVENANCE
      and "human_reshaped" in cp.CORRECTION_PROVENANCE)
check("...and from auto_proposed",
      "auto_proposed" in cp.CORRECTION_PROVENANCE)
check("split and merge are separable from both",
      "human_split" in cp.CORRECTION_PROVENANCE
      and "human_merged" in cp.CORRECTION_PROVENANCE)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("CELL_POPULATION_PASS")