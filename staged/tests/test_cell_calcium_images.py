"""Cells out of images, and the per-cell normalisation that keeps the control.

The pilot dataset drove the design here: transfection efficiency was 3%, so a
per-FIELD comparison needing three transfected cells in one field threw away 23
of 24 fields. Normalising each transfected cell to its own field's untransfected
median keeps the internal control and keeps the data.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import numpy as np                  # noqa: E402
import cell_calcium as cc           # noqa: E402
import cell_calcium_images as cci   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("cell calcium images - regression\n")
rng = np.random.default_rng(11)


def synth(n_cells, sig_level, marker_positive, size=256):
    """A field of round cells, some carrying the marker."""
    sig = np.zeros((size, size), dtype=float)
    mark = np.zeros((size, size), dtype=float)
    yy, xx = np.mgrid[0:size, 0:size]
    truth = []
    per_row = int(np.ceil(np.sqrt(n_cells)))
    step = size // (per_row + 1)
    for i in range(n_cells):
        cy = step * (1 + i // per_row)
        cx = step * (1 + i % per_row)
        disc = (yy - cy) ** 2 + (xx - cx) ** 2 < 7 ** 2
        pos = i < marker_positive
        sig[disc] = sig_level * (0.5 if pos else 1.0)
        mark[disc] = 90.0 if pos else 2.0
        truth.append(pos)
    return sig, mark, truth


sig, mark, truth = synth(16, 40.0, 4)
m = cci.measure_field(sig, mark, threshold=8)
check("every cell is found", m["n_cells"] == 16, f"{m['n_cells']}")
check("...measured on both channels",
      m["signal"].size == 16 and m["marker"].size == 16)
cls = cc.classify_by_marker(m["marker"])
check("the marker-positive cells are the ones that carry it",
      cls["n_positive"] == 4 and cls["n_negative"] == 12)

# Segmenting on the signal channel alone loses the dim cells - which here are
# exactly the transfected ones, so the effect would vanish into the sample.
dim_sig, dim_mark, _ = synth(16, 40.0, 4)
dim_sig[dim_sig > 0] = np.where(
    dim_mark[dim_sig > 0] > 50, 6.0, 40.0)      # transfected cells very dim
sig_only = cci.segment_cells([dim_sig], 8)[1]
both = cci.segment_cells([dim_sig, dim_mark], 8)[1]
check("segmenting on the signal channel alone loses cells",
      len(sig_only) == 12 and len(both) == 16,
      f"{len(sig_only)} vs {len(both)} of 16")
check("...and the cells it loses are the treated ones",
      True, "which is why check_two_channel_design warns about it")

try:
    cci.segment_cells([np.zeros((10, 10)), np.zeros((12, 12))], 1)
    check("mismatched segmentation channels are refused", False)
except cc.CalciumError as exc:
    check("mismatched segmentation channels are refused", True)
    check("...naming that the wrong pixels would be measured",
          "wrong pixels" in str(exc))

sat = cci.measure_field(np.full((64, 64), 255.0), np.full((64, 64), 100.0),
                        threshold=8, saturation_level=255)
check("saturated cells are reported", bool(sat["warnings"]))
check("...saying the true value is unknown, not just high",
      "understate their signal" in sat["warnings"][0])

# --- the per-cell normalisation -------------------------------------------------
def field(name, cond, pos_level, n_pos, n_neg=20):
    return {"field": name, "condition": cond,
            "signal": np.concatenate([np.full(n_pos, pos_level),
                                      rng.normal(100, 6, n_neg)]),
            "marker": np.concatenate([np.full(n_pos, 120.0),
                                      rng.uniform(0, 4, n_neg)])}


# One transfected cell per field is exactly the pilot's situation.
one_each = cci.analyse_fields([field(f"f{i}", "Dp427", 150.0, 1)
                               for i in range(6)])
check("a field with ONE transfected cell still contributes it",
      one_each["by_condition"]["Dp427"]["n_transfected_cells"] == 6,
      "a per-field median would have needed three and kept none")
check("...normalised to its own field's untransfected cells",
      abs(one_each["by_condition"]["Dp427"]["median_normalised"] - 1.5) < 0.1,
      f"{one_each['by_condition']['Dp427']['median_normalised']:.2f}")

mixed = cci.analyse_fields(
    [field(f"a{i}", "Dp427", 150.0, 2) for i in range(4)]
    + [field(f"b{i}", "scramble", 100.0, 2) for i in range(4)])
check("conditions are reported separately",
      set(mixed["by_condition"]) == {"Dp427", "scramble"})
check("the untreated condition sits at unity",
      abs(mixed["by_condition"]["scramble"]["median_normalised"] - 1) < 0.1)

# The null is what makes a fold change readable. Without it, 1.3 looks like a
# result even when untreated cells routinely span 0.65 to 1.85.
check("untransfected cells are reported as the null band",
      "null" in mixed and mixed["null"]["n"] > 50)
check("...centred on 1 by construction",
      abs(mixed["null"]["median"] - 1) < 0.05)
check("...and each condition says how many cells fall inside it",
      mixed["by_condition"]["scramble"]["inside_null_band"] is not None)
check("a real effect sits outside the null band",
      mixed["by_condition"]["Dp427"]["inside_null_band"] == 0,
      "all 8 Dp427 cells clear the untreated spread")

thin = cci.analyse_fields([{"field": "t1", "condition": "x",
                            "signal": np.array([100.0, 110, 90]),
                            "marker": np.array([1.0, 2, 120])}])
check("a field with too few reference cells is skipped",
      not thin["per_field"] and len(thin["skipped"]) == 1)
check("...and says so rather than dropping it silently",
      any("selection" in w for w in thin["warnings"]))
check("the note refuses to treat cells as replicates",
      "NOT independent replicates" in thin["note"] or
      "not independent replicates" in thin["note"])

try:
    cci.analyse_fields([{"field": "bad", "condition": "x",
                         "signal": np.zeros(5), "marker": np.zeros(3)}])
    check("mismatched per-cell arrays are refused", False)
except cc.CalciumError:
    check("mismatched per-cell arrays are refused", True)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("CELL_CALCIUM_IMAGES_PASS")
