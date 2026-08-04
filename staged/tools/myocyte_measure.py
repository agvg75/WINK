"""Per-cell measurements from REVIEWED myocyte boundaries.

WHAT THIS MEASURES AND WHAT IT REFUSES TO. Cells are the regions between
approved boundary curves. Because the curves cross - Andres's marks are a braid
of long shallow curves, not a stack of parallel lines - the cells are faces of
that arrangement, so they are found by rasterising the boundaries as barriers
and labelling what is left rather than by pairing curves.

IT WILL NOT MEASURE AN UNREVIEWED FIELD. A boundary nobody judged is a
detector's guess, and a guess that reaches a results table is indistinguishable
from a measurement once it is there. Numbers here are only as good as the review
that preceded them, which is why the review must have been accepted.

WHAT A CELL AREA IS NOT. A face of the boundary arrangement is bounded by the
boundaries that were drawn. Where a boundary was missed, two cells merge into
one and the area is the sum of both - which looks like a large cell, not like an
error. The detector's recall therefore sets a floor on how wrong these can be,
and `flags` names the cases most likely to be that failure rather than biology.
"""
from __future__ import annotations

import numpy as np

# A body-wall myocyte is roughly 30-100 um long and 5-20 um across. These are
# not filters - nothing is discarded - they decide which rows get FLAGGED, so a
# merged pair of cells is visible as such rather than passing as one big cell.
PLAUSIBLE_AREA_UM2 = (80.0, 1500.0)
PLAUSIBLE_LENGTH_UM = (15.0, 130.0)


class MeasurementError(Exception):
    """Refusals that name the consequence."""


def _rasterise(state, shape, thickness_px=2):
    """Draw accepted and edited boundaries as barriers. Rejected are ignored."""
    from scipy import ndimage as ndi

    H, W = shape
    bar = np.zeros((H, W), dtype=bool)
    used = []
    for b in state.boundaries.values():
        if b.status not in ("accepted", "edited"):
            continue
        pts = np.asarray(b.points, dtype=float)
        order = np.argsort(pts[:, 0])
        pts = pts[order]
        xs = np.arange(int(np.floor(pts[:, 0].min())),
                       int(np.ceil(pts[:, 0].max())) + 1)
        if xs.size < 2:
            continue
        ys = np.interp(xs, pts[:, 0], pts[:, 1])
        xi = np.clip(xs, 0, W - 1).astype(int)
        yi = np.clip(np.rint(ys), 0, H - 1).astype(int)
        bar[yi, xi] = True
        used.append(b.boundary_id)
    if thickness_px > 1:
        bar = ndi.binary_dilation(bar, np.ones((thickness_px, thickness_px)))
    return bar, used


def cells_from_boundaries(state, tissue_mask, min_area_um2=40.0,
                          thickness_px=2):
    """Label the faces between approved boundaries.

    `tissue_mask` bounds the search: without it every region outside the muscle
    would be labelled a cell, and background is not anatomy.
    """
    from scipy import ndimage as ndi

    if not state.accepted:
        raise MeasurementError(
            "This review was never accepted, so some boundaries may not have "
            "been judged. Measuring now would put a detector's unreviewed "
            "guesses into a results table, where nothing distinguishes them "
            "from measurements. Finish the review first.")

    tissue = np.asarray(tissue_mask, dtype=bool)
    bar, used = _rasterise(state, tissue.shape, thickness_px)
    if not used:
        raise MeasurementError(
            "No boundary survived review, so there is nothing to divide the "
            "tissue into cells. Every proposal was rejected.")

    labels, n = ndi.label(tissue & ~bar, structure=np.ones((3, 3)))
    px_area = state.um_per_px ** 2
    keep = np.zeros(n + 1, dtype=int)
    nxt = 1
    for i in range(1, n + 1):
        if (labels == i).sum() * px_area >= min_area_um2:
            keep[i] = nxt
            nxt += 1
    labels = keep[labels]
    return labels, int(nxt - 1), used


def measure_cells(labels, um_per_px, fibre_skeleton=None, angles=None,
                  coherence=None):
    """Geometry per cell, plus fibre statistics where a skeleton is supplied.

    Orientation and axis lengths come from the second moments of the region, so
    a rhomboid cell reports the axis of its own elongation rather than a
    bounding box, which for a slanted cell would be mostly empty.
    """
    from scipy import ndimage as ndi

    lab = np.asarray(labels)
    n = int(lab.max())
    rows = []
    for i in range(1, n + 1):
        m = lab == i
        area_px = int(m.sum())
        if area_px == 0:
            continue
        ys, xs = np.nonzero(m)
        cy, cx = ys.mean(), xs.mean()
        yy, xx = ys - cy, xs - cx
        cov = np.array([[(xx * xx).mean(), (xx * yy).mean()],
                        [(xx * yy).mean(), (yy * yy).mean()]])
        evals, evecs = np.linalg.eigh(cov)
        order = np.argsort(evals)[::-1]
        evals, evecs = evals[order], evecs[:, order]
        # 4*sqrt(eigenvalue) is the length of an equivalent ellipse's axis
        major = 4.0 * np.sqrt(max(evals[0], 0)) * um_per_px
        minor = 4.0 * np.sqrt(max(evals[1], 0)) * um_per_px
        angle = np.degrees(np.arctan2(evecs[1, 0], evecs[0, 0])) % 180.0

        row = {
            "cell_id": i,
            "area_um2": round(area_px * um_per_px ** 2, 3),
            "length_um": round(float(major), 3),
            "width_um": round(float(minor), 3),
            "aspect_ratio": round(float(major / minor), 3) if minor > 0 else None,
            "orientation_deg": round(float(angle), 2),
            "centroid_x_um": round(float(cx) * um_per_px, 3),
            "centroid_y_um": round(float(cy) * um_per_px, 3),
            "x_extent_um": round(float(xs.max() - xs.min()) * um_per_px, 3),
        }

        if fibre_skeleton is not None:
            sk = np.asarray(fibre_skeleton, dtype=bool) & m
            row["fibre_length_um"] = round(float(sk.sum()) * um_per_px, 3)
            row["fibre_density_per_um"] = (
                round(float(sk.sum()) * um_per_px / row["area_um2"], 5)
                if row["area_um2"] else None)
        if angles is not None and coherence is not None:
            a = np.asarray(angles, dtype=float)
            c = np.asarray(coherence, dtype=float)
            if a.ndim == 3:
                a, c = np.nanmean(a, axis=0), np.nanmean(c, axis=0)
            w = np.where(m & (c > 0.2), c, 0.0)
            if w.sum() > 0:
                d = np.deg2rad(a * 2.0)
                mean_ang = (np.degrees(np.arctan2((np.sin(d) * w).sum(),
                                                  (np.cos(d) * w).sum()))
                            / 2.0) % 180.0
                row["fibre_angle_deg"] = round(float(mean_ang), 2)
                # relative to the cell's own long axis, which is what anatomy
                # cares about - an absolute angle changes if the worm is tilted
                rel = abs(mean_ang - angle) % 180.0
                row["fibre_angle_vs_cell_axis_deg"] = round(
                    float(min(rel, 180.0 - rel)), 2)
                row["fibre_coherence"] = round(float(w[m].mean()), 4)

        flags = []
        if not (PLAUSIBLE_AREA_UM2[0] <= row["area_um2"] <= PLAUSIBLE_AREA_UM2[1]):
            flags.append("area_outside_plausible_range")
        if not (PLAUSIBLE_LENGTH_UM[0] <= row["length_um"]
                <= PLAUSIBLE_LENGTH_UM[1]):
            flags.append("length_outside_plausible_range")
        if row["aspect_ratio"] is not None and row["aspect_ratio"] < 1.5:
            flags.append("not_elongated")
        row["flags"] = ";".join(flags)
        row["flag_note"] = ("" if not flags else
                            "A MISSED boundary merges two cells into one, which "
                            "looks like a large cell rather than an error - "
                            "check this region against the image.")
        rows.append(row)
    return rows


def summarise(rows, um_per_px=None):
    """Field-level summary, with the merge caveat carried alongside."""
    if not rows:
        return {"n_cells": 0, "note": "no cells - every boundary was rejected"}
    a = np.array([r["area_um2"] for r in rows])
    L = np.array([r["length_um"] for r in rows])
    flagged = [r["cell_id"] for r in rows if r["flags"]]
    return {
        "n_cells": len(rows),
        "area_um2_median": round(float(np.median(a)), 2),
        "area_um2_iqr": [round(float(np.percentile(a, 25)), 2),
                         round(float(np.percentile(a, 75)), 2)],
        "length_um_median": round(float(np.median(L)), 2),
        "n_flagged": len(flagged),
        "flagged_cells": flagged,
        "caveat": ("Cell count and areas are bounded by the boundaries that "
                   "were drawn. A missed boundary merges two cells and inflates "
                   "one area; a spurious one splits a cell. Neither is visible "
                   "in these numbers alone - read them with the detector's "
                   "recall and the review's rejection counts."),
    }
