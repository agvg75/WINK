"""From two- or three-channel images to per-cell calcium measurements.

cell_calcium.py holds the measurement logic and stays numpy-only. This module
is the part that touches images: find the cells, read each channel inside each
cell, and hand the numbers over.

WHAT THIS MODULE WILL NOT DO. It will not report a between-condition difference
computed from raw intensities across coverslips. With a single-wavelength dye
that comparison measures dye loading as much as calcium, and the whole point of
the transfected/untransfected layout is that it does not have to. Every value
that leaves here is normalised to the untransfected cells in ITS OWN field.

NORMALISING PER CELL, NOT PER FIELD. The obvious analysis takes each field's
transfected median against its untransfected median. On the lab's pilot that
threw away 23 of 24 fields, because transfection efficiency was 3% and almost
no field held three clearly-transfected cells. Dividing each transfected cell
by its own field's untransfected median keeps the same internal control - the
reference cells still share the coverslip, the loading and the illumination -
while letting a field with one transfected cell still contribute it. The unit
for any test remains the coverslip, not the cell; that is the caller's job and
is stated in the output.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import ndimage

import cell_calcium as cc

# A smooth-muscle progenitor at 10x on the SP8 is ~2.3 um/pixel, so a cell of
# 50 x 20 um covers a few hundred pixels. The floor removes debris and the
# ceiling removes merged clumps, which are not single cells and whose mean
# intensity belongs to no one.
MIN_CELL_PX = 50
MAX_CELL_PX = 20000
SMOOTH_SIGMA = 1.5


def segment_cells(channels, threshold, *, min_px=MIN_CELL_PX,
                  max_px=MAX_CELL_PX, smooth=SMOOTH_SIGMA):
    """Label cells from whichever channels are offered.

    Pass the DIC or nuclear channel when there is one. Absent that, pass both
    fluorescence channels: taking the per-pixel maximum lets an untransfected
    cell be found by its dye and a transfected one by either, where using the
    signal channel alone would find only the bright cells and bias the sample
    towards high calcium. That is a mitigation, not a fix - see
    cell_calcium.check_two_channel_design.
    """
    stack = [np.asarray(c, dtype=float) for c in channels]
    if not stack:
        raise cc.CalciumError("No channel given to segment on.")
    if len({c.shape for c in stack}) != 1:
        raise cc.CalciumError(
            f"Channels differ in shape: {[c.shape for c in stack]}. Cells "
            f"labelled on one and measured on another would be measuring the "
            f"wrong pixels.")
    base = stack[0] if len(stack) == 1 else np.maximum.reduce(stack)
    labels, n = ndimage.label(ndimage.gaussian_filter(base, smooth) > threshold)
    if n == 0:
        return np.zeros_like(labels), []
    sizes = np.bincount(labels.ravel())
    keep = [i for i in range(1, n + 1) if min_px <= sizes[i] <= max_px]
    return labels, keep


def measure_field(signal, marker, *, threshold, segmentation=None,
                  saturation_level=None):
    """Per-cell signal and marker for one field, plus what went wrong."""
    signal = np.asarray(signal, dtype=float)
    marker = np.asarray(marker, dtype=float)
    seg_on = ([np.asarray(segmentation, dtype=float)]
              if segmentation is not None else [signal, marker])
    labels, keep = segment_cells(seg_on, threshold)
    out = {"n_cells": len(keep), "signal": np.array([]),
           "marker": np.array([]), "area_px": np.array([]),
           "saturated_fraction": np.array([]), "warnings": []}
    if not keep:
        out["warnings"].append(
            f"No cell-sized object found above a threshold of {threshold:g}.")
        return out
    sig, mrk, area, sat = [], [], [], []
    for i in keep:
        m = labels == i
        sig.append(float(signal[m].mean()))
        mrk.append(float(marker[m].mean()))
        area.append(int(m.sum()))
        sat.append(float((signal[m] >= saturation_level).mean())
                   if saturation_level else 0.0)
    out.update(signal=np.array(sig), marker=np.array(mrk),
               area_px=np.array(area), saturated_fraction=np.array(sat))
    n_sat = int((out["saturated_fraction"] > 0).sum())
    if n_sat:
        out["warnings"].append(
            f"{n_sat} of {len(keep)} cells contain saturated pixels. A "
            f"saturated pixel has no intensity to report - its true value is "
            f"'at least the maximum' - so those cells understate their signal "
            f"by an unknown amount.")
    return out


def analyse_fields(fields, *, min_reference_cells=5):
    """Normalise every transfected cell to its own field, then pool.

    `fields` is a sequence of dicts with 'field', 'condition', 'signal' and
    'marker' (per-cell arrays in the same order), optionally 'threshold'.
    """
    cells, per_field, skipped = [], [], []
    for f in fields:
        name, cond = f.get("field", "?"), f.get("condition", "?")
        sig = np.asarray(f["signal"], dtype=float)
        mrk = np.asarray(f["marker"], dtype=float)
        if sig.shape != mrk.shape:
            raise cc.CalciumError(
                f"Field {name!r}: {sig.size} signal values against "
                f"{mrk.size} marker values; they must be one per cell.")
        if sig.size < min_reference_cells + 1:
            skipped.append(f"{name}: only {sig.size} cells found")
            continue
        try:
            cls = cc.classify_by_marker(mrk, threshold=f.get("threshold"))
        except cc.CalciumError as exc:
            skipped.append(f"{name}: {exc}")
            continue
        neg = cls["negative"]
        if int(neg.sum()) < min_reference_cells:
            skipped.append(
                f"{name}: {int(neg.sum())} untransfected cells, below the "
                f"floor of {min_reference_cells} needed for a field reference")
            continue
        ref = float(np.median(sig[neg]))
        if ref <= 0:
            skipped.append(f"{name}: the untransfected reference is zero")
            continue
        bleed = cc.marker_bleedthrough(sig, mrk, cls["positive"])
        per_field.append({
            "field": name, "condition": cond, "reference": ref,
            "n_positive": cls["n_positive"], "n_negative": cls["n_negative"],
            "n_ambiguous": cls["n_ambiguous"],
            "marker_threshold": cls["threshold"],
            "separability": cls["separability"],
            "bleedthrough_r": bleed["r"],
            "warnings": cls["warnings"] + bleed["warnings"],
        })
        for idx in np.nonzero(cls["positive"])[0]:
            cells.append({"field": name, "condition": cond,
                          "transfected": True, "signal": float(sig[idx]),
                          "reference": ref, "normalised": float(sig[idx]) / ref,
                          "marker": float(mrk[idx])})
        for idx in np.nonzero(neg)[0]:
            cells.append({"field": name, "condition": cond,
                          "transfected": False, "signal": float(sig[idx]),
                          "reference": ref, "normalised": float(sig[idx]) / ref,
                          "marker": float(mrk[idx])})

    out = {"cells": cells, "per_field": per_field, "skipped": skipped,
           "by_condition": {}, "warnings": []}

    # The untransfected cells, normalised the same way, ARE the null. They had
    # no treatment, so their spread is what one cell differs from another by
    # for no reason at all, and a transfected cell has to clear it to mean
    # anything. Reporting the treatment groups without this is how a 1.3-fold
    # difference gets believed in data whose untreated cells span 0.65 to 1.85.
    null = np.array([c["normalised"] for c in cells if not c["transfected"]])
    if null.size:
        out["null"] = {
            "n": int(null.size), "median": float(np.median(null)),
            "p5": float(np.percentile(null, 5)),
            "p95": float(np.percentile(null, 95)),
        }

    for cond in sorted({c["condition"] for c in cells}):
        v = np.array([c["normalised"] for c in cells
                      if c["condition"] == cond and c["transfected"]])
        if v.size == 0:
            continue
        out["by_condition"][cond] = {
            "n_transfected_cells": int(v.size),
            "n_fields": len({c["field"] for c in cells
                             if c["condition"] == cond and c["transfected"]}),
            "median_normalised": float(np.median(v)),
            "iqr": [float(np.percentile(v, 25)), float(np.percentile(v, 75))],
            "inside_null_band": (
                int(((v >= out["null"]["p5"]) & (v <= out["null"]["p95"])).sum())
                if null.size else None),
        }
    if skipped:
        out["warnings"].append(
            f"{len(skipped)} field(s) contributed nothing. They are listed "
            f"rather than dropped silently: the fields that fail are usually "
            f"the worst-transfected ones, so losing them is a selection.")
    out["note"] = (
        "Each transfected cell is divided by the median of the untransfected "
        "cells in its own field, so loading, illumination and focus cancel "
        "per cell. The cells are NOT independent replicates - a coverslip is - "
        "so counts here describe how much was measured, not how many degrees "
        "of freedom a test has.")
    return out


def load_field_pairs(root, *, signal_suffix="_ch00", marker_suffix="_ch01",
                     segmentation_suffix=None, pattern="*.tif"):
    """Find condition folders and pair their channel files by stem.

    Returns [(condition, stem, {suffix: Path})], with unpaired stems reported
    rather than silently half-loaded.
    """
    root = Path(root)
    if not root.is_dir():
        raise cc.CalciumError(f"{root} is not a folder.")
    wanted = [s for s in (signal_suffix, marker_suffix, segmentation_suffix)
              if s]
    found, unpaired = [], []
    conditions = sorted(p for p in root.iterdir() if p.is_dir())
    if not conditions:
        conditions = [root]
    for cond_dir in conditions:
        groups = {}
        for f in sorted(cond_dir.glob(pattern)):
            for suf in wanted:
                if suf in f.name:
                    groups.setdefault(f.name.replace(suf, ""), {})[suf] = f
                    break
        for stem, chans in sorted(groups.items()):
            missing = [s for s in (signal_suffix, marker_suffix)
                       if s not in chans]
            if missing:
                unpaired.append(f"{cond_dir.name}/{stem}: missing {missing}")
                continue
            found.append((cond_dir.name, stem, chans))
    return found, unpaired
