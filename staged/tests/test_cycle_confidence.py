"""Confidence gating and per-cycle analysis, on signals with known answers.

The property that matters most is negative: spans must never be concatenated.
A cycle formed across a join would have a period and an excursion describing
the join rather than the animal, and it would look exactly like a measurement.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import confidence_gate as cg     # noqa: E402
import cycle_analysis as ca      # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("confidence gating and cycle analysis - regression\n")

FPS = 20.0
N = 600
t = np.arange(N) / FPS
# a 1 Hz body bend, with calcium peaking a quarter cycle after maximum bend
bend = 30.0 * np.sin(2 * np.pi * 1.0 * t)
calcium = 1.0 + 0.4 * np.sin(2 * np.pi * 1.0 * t - np.pi / 2)
speed = 100.0 + 40.0 * np.abs(np.sin(2 * np.pi * 1.0 * t))

# confidence: good, then a bad stretch, then good again
conf = np.full(N, 0.9)
conf[200:320] = 0.1

# --- gating ---------------------------------------------------------------
g = cg.gate(conf, level="balanced", fps=FPS)
check("the bad stretch is excluded", g["n_spans"] == 2, f"{g['n_spans']} spans")
check("coverage reports what was kept",
      abs(g["coverage"] - (N - 120) / N) < 0.02, f"{g['coverage']}")
check("the gate states spans must NOT be concatenated",
      g["spans_must_not_be_concatenated"] is True and "inventions" in g["why"])

g_any = cg.gate(conf, level="any", fps=FPS)
check("level 'any' keeps everything as one span",
      g_any["n_spans"] == 1 and g_any["coverage"] == 1.0)

strict = cg.gate(conf, level="very strict", fps=FPS)
check("a stricter level keeps no more than a looser one",
      strict["coverage"] <= g["coverage"], f"{strict['coverage']} vs {g['coverage']}")

sw = cg.sweep(conf, fps=FPS)
check("a sweep shows what each level would cost", len(sw) >= 4,
      f"{[r['level'] for r in sw]}")

# a brief dip is bridged, a long one is not
dip = np.full(N, 0.9)
dip[300:303] = 0.1
bridged = cg.gate(dip, level="balanced", max_gap=5)
check("a brief dip is bridged rather than splitting the recording",
      bridged["n_spans"] == 1, f"{bridged['n_spans']} spans")
check("...and the bridging is recorded, not silent",
      bridged["max_gap_bridged"] == 5)

try:
    cg.gate(np.full(10, np.nan))
    check("an all-missing confidence series is refused", False)
except cg.GateError as exc:
    check("an all-missing confidence series is refused", True)
    check("...naming what would go wrong",
          "unusable frames as results" in str(exc))

# --- cycles ---------------------------------------------------------------
res = ca.cycles_over_spans(bend, g["spans"],
                           signals={"calcium": calcium, "speed": speed},
                           fps=FPS)
check("cycles are found in both spans", res["n_spans_used"] == 2,
      f"{res['n_cycles']} cycles over {res['n_spans_used']} spans")
check("no cycle crosses a span boundary",
      all(not (r["start_frame"] < 200 <= r["end_frame"]) and
          not (r["start_frame"] < 320 <= r["end_frame"])
          for r in res["cycles"]))

rows = res["cycles"]
freqs = [r["frequency_hz"] for r in rows if r.get("frequency_hz")]
check("cycle frequency matches the planted 1 Hz",
      abs(np.median(freqs) - 1.0) < 0.15, f"median {np.median(freqs):.3f} Hz")
exc = [r["excursion"] for r in rows]
check("excursion matches the planted 60 deg peak-to-peak",
      abs(np.median(exc) - 60.0) < 8.0, f"median {np.median(exc):.1f}")

phases = [r["calcium_phase_at_peak"] for r in rows
          if r.get("calcium_phase_at_peak") is not None]
check("the phase of the calcium peak is reported per cycle",
      len(phases) == len(rows) and 0.0 <= np.median(phases) <= 1.0,
      f"median phase {np.median(phases):.2f}")

# --- correlation ----------------------------------------------------------
big = ca.correlate(rows, "excursion", "calcium_peak")
check("a correlation is returned with both r and rho",
      "pearson_r" in big and "spearman_rho" in big, f"n={big['n_cycles']}")
check("...and states that within-recording cycles are not independent",
      big["is_a_within_recording_correlation"] is True
      and "not evidence about a genotype" in big["note"])

try:
    ca.correlate(rows[:4], "excursion", "calcium_peak")
    check("a correlation over too few cycles is refused", False)
except ca.CycleError as e2:
    check("a correlation over too few cycles is refused", True)
    check("...naming the count rather than returning a number",
          "Only 4 cycles" in str(e2))

# --- a signal with no oscillation ----------------------------------------
flat = np.linspace(0, 1, N)
out = ca.cycles_over_spans(flat, [(0, N - 1)], fps=FPS)
check("a non-oscillating signal yields few or no cycles",
      out["n_cycles"] <= 2, f"{out['n_cycles']} cycles from a ramp")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("CYCLE_CONFIDENCE_PASS")
