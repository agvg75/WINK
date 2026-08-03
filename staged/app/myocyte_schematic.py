"""The WINK body-wall myocyte schematic, drawn rather than stored.

WHY THIS IS GENERATED
---------------------
Cell boundaries come from the same profile the RGBCaMP extractor measures with
(``buildMuscleBoundaries()`` in ``tools/rgbcamp/fiji/WormRGBCaMPMap_v1.java``)::

    prof[k] = 0.55 + 0.45 * (0.5 - 0.5*cos(2*pi*u)),   u = k/(n_seg-1)

normalised to cumulative fractions.  The drawn cell sizes therefore ARE the
measured segment sizes.  A stored image cannot make that promise: change
``n_seg`` or the profile and a stored diagram silently starts describing a
segmentation the tools no longer use.

Two consumers:

  * the RGBCaMP results movie, which tints each myocyte per frame
  * "Show myocyte numbering schematic" in the myocyte morphometry tool

WHAT THE DIAGRAM DOES AND DOES NOT CLAIM
----------------------------------------
Two bands of ``n_seg`` cells are drawn, representing two opposing muscle
quadrants.  **No dorsal/ventral identity is asserted.**  The tracker labels
sides L and R in image space and only knows anatomical orientation when a
vulva seed was given, so the bands are drawn without anatomical names and the
vulva is drawn as an X spanning the full width - belonging to neither band,
exactly as the lab's original figure has it.

One drawn cell is one myocyte because these are confocal optical sections
through a single muscle layer.  On projected or widefield data each band would
superimpose two quadrants and one drawn cell would be two myocytes averaged
together, so do not reuse this diagram for such recordings.

Importing this module has no side effects: no backend is selected, no figure
is created, nothing is written.  Run it directly to regenerate the reference
PNG.
"""
from __future__ import annotations

import numpy as np

N_SEG = 24
PHARYNX_THROUGH = 7        # the pharynx spans through myocyte 7
WMAX = 0.056               # max half-width in body lengths (mildly exaggerated
                           # for legibility; a true ~12:1 worm is too thin to tint)
AMP = 0.026                # undulation amplitude - alive, not a sine wave
VULVA_FRAC = 0.5           # mid-body; on the default profile this is exactly
                           # the cell 12/13 boundary

SLATE = "#3A4A52"
INK = "#22303A"
MUTED = "#5E6E76"
CHANNEL_RGB = ((0.83, 0.16, 0.20), (0.13, 0.66, 0.28), (0.16, 0.36, 0.86))


def boundaries(n_seg=N_SEG):
    """Cumulative cell boundaries along the body, length n_seg+1, 0..1."""
    if n_seg < 2:
        raise ValueError("n_seg must be at least 2")
    u = np.arange(n_seg) / (n_seg - 1)
    prof = 0.55 + 0.45 * (0.5 - 0.5 * np.cos(2 * np.pi * u))
    frac = np.concatenate([[0.0], np.cumsum(prof / prof.sum())])
    frac[-1] = 1.0
    return frac


def halfwidth(x):
    """Rounded head, near-uniform trunk, long fine tail."""
    x = np.asarray(x, dtype=float)
    head = np.clip(x / 0.075, 0, 1) ** 0.42
    tail = np.clip((1 - x) / 0.30, 0, 1) ** 0.62
    return WMAX * head * tail


def midline(x):
    x = np.asarray(x, dtype=float)
    return AMP * np.sin(2 * np.pi * (0.85 * x + 0.04))


def body_point(x, r):
    """(x, y) at fractional body length x and radial offset r in half-widths."""
    return np.asarray(x, float), midline(x) + r * halfwidth(x)


def _spindle(x0, x1, r_in, r_out, n=48, overlap=0.46):
    """One lozenge myocyte, overlapping its neighbours so the band reads as
    interdigitated the way the anatomy actually is."""
    span = x1 - x0
    a = max(x0 - span * overlap / 2, 0.0015)
    b = min(x1 + span * overlap / 2, 0.9985)
    xs = np.linspace(a, b, n)
    t = (xs - a) / max(b - a, 1e-9)
    taper = np.sin(np.pi * t)
    r_mid = 0.5 * (r_in + r_out)
    ux, uy = body_point(xs, r_mid + (r_out - r_mid) * taper)
    lx, ly = body_point(xs[::-1], (r_mid + (r_in - r_mid) * taper)[::-1])
    return np.column_stack([np.r_[ux, lx], np.r_[uy, ly]])


def cell_polygons(n_seg=N_SEG):
    """[(band, k, polygon, r_lo, r_hi)] for all 2*n_seg myocytes.

    band 0 is one quadrant, band 1 the opposing one. Neither is dorsal.
    """
    frac = boundaries(n_seg)
    out = []
    for band, (rlo, rhi) in enumerate([(0.07, 0.99), (-0.99, -0.07)]):
        span = rhi - rlo
        for k in range(n_seg):
            outer = (k % 2 == 0) if band == 0 else (k % 2 == 1)
            if outer:
                r_in, r_out = rlo + 0.38 * span, rhi
            else:
                r_in, r_out = rlo, rlo + 0.62 * span
            lo, hi = min(r_in, r_out), max(r_in, r_out)
            out.append((band, k, _spindle(frac[k], frac[k + 1], lo, hi), lo, hi))
    return out


def body_outline(n=600):
    xs = np.linspace(0, 1, n)
    tx, ty = body_point(xs, 1.0)
    bx, by = body_point(xs[::-1], -1.0)
    return np.column_stack([np.r_[tx, bx], np.r_[ty, by]])


def _slice_x(poly, lo, hi):
    keep = poly[(poly[:, 0] >= lo) & (poly[:, 0] <= hi)]
    return keep if len(keep) >= 3 else None


def draw(ax, n_seg=N_SEG, values=None, numbered=True, landmarks=True,
         regions=True):
    """Draw the schematic onto ``ax``.

    values : array (n_seg, 2, 3) of 0..1 per (segment, band, channel), or None
        for a blank template. Passing None still creates the channel patches so
        a caller can tint them per frame without rebuilding the figure - which
        is what makes blitting possible in the results movie.

    Returns a dict of handles:
        'channels' : {(band, k, channel): Polygon}   set_facecolor() per frame
        'cells'    : {(band, k): Polygon}            set_alpha()/hatch for
                                                     provenance shading
    """
    from matplotlib.patches import Polygon      # imported late: no backend cost

    frac = boundaries(n_seg)
    if values is not None:
        values = np.asarray(values, dtype=float)
        if values.shape != (n_seg, 2, 3):
            raise ValueError(
                f"values must have shape ({n_seg}, 2, 3), got {values.shape}")

    ax.add_patch(Polygon(body_outline(), closed=True, facecolor="#FCFCFA",
                         edgecolor=INK, lw=1.6, zorder=1, joinstyle="round"))

    # pharynx: procorpus and terminal bulb, closing with myocyte 7
    ph_end = frac[min(PHARYNX_THROUGH, n_seg)]
    xs = np.linspace(0.008, ph_end, 160)
    t = (xs - 0.008) / max(ph_end - 0.008, 1e-9)
    lobe = (0.22 + 0.32 * np.exp(-((t - 0.24) / 0.20) ** 2)
            + 0.42 * np.exp(-((t - 0.80) / 0.12) ** 2))
    lobe *= np.clip((1 - t) / 0.09, 0, 1) ** 0.6
    lobe *= np.clip(t / 0.05, 0, 1) ** 0.5
    ux, uy = body_point(xs, lobe)
    lx, ly = body_point(xs[::-1], -lobe[::-1])
    ax.add_patch(Polygon(np.column_stack([np.r_[ux, lx], np.r_[uy, ly]]),
                         closed=True, facecolor="#C7CFCB", edgecolor="#93A09A",
                         lw=0.8, zorder=2))

    channels, cells = {}, {}
    for band, k, poly, lo, hi in cell_polygons(n_seg):
        xa, xb = poly[:, 0].min(), poly[:, 0].max()
        for c in range(3):
            sl = _slice_x(poly, xa + (xb - xa) * c / 3,
                          xa + (xb - xa) * (c + 1) / 3)
            if sl is None:
                continue
            if values is None:
                face = "white"
            else:
                v = float(np.clip(values[k, band, c], 0.0, 1.0))
                face = tuple(1 - (1 - ch) * v for ch in CHANNEL_RGB[c])
            patch = Polygon(sl, closed=True, facecolor=face, edgecolor="none",
                            zorder=3)
            ax.add_patch(patch)
            channels[(band, k, c)] = patch
        outline_patch = Polygon(poly, closed=True, facecolor="none",
                                edgecolor=SLATE, lw=0.7, zorder=4)
        ax.add_patch(outline_patch)
        cells[(band, k)] = outline_patch

    if numbered:
        for band, k, poly, lo, hi in cell_polygons(n_seg):
            if band != 0:
                continue
            cx = 0.5 * (frac[k] + frac[k + 1])
            # the last myocytes are too small to hold a legible label, so they
            # move outside on a leader rather than shrink past readability
            if k < n_seg - 5:
                _, cy = body_point(cx, 0.5 * (lo + hi))
                ax.text(cx, float(cy), str(k + 1), ha="center", va="center",
                        fontsize=5.8, color=INK, zorder=6)
            else:
                _, ay = body_point(cx, 1.0)
                ty = float(ay) + 0.020 + 0.011 * ((k - (n_seg - 5)) % 2)
                ax.plot([cx, cx], [float(ay), ty - 0.004], lw=0.5,
                        color="#9AA6AC", zorder=5)
                ax.text(cx, ty, str(k + 1), ha="center", va="bottom",
                        fontsize=5.8, color=INK, zorder=6)

    if landmarks:
        # vulva as an X across the FULL width: it belongs to neither band,
        # because this diagram does not claim to know which side is ventral
        d = 0.011
        for sgn in (1, -1):
            x1, y1 = body_point(VULVA_FRAC - sgn * d, -1.02)
            x2, y2 = body_point(VULVA_FRAC + sgn * d, 1.02)
            ax.plot([float(x1), float(x2)], [float(y1), float(y2)],
                    color="#71797E", lw=5.0, solid_capstyle="round", zorder=5)

        def lead(x, r, dx, dy, text, ha="center"):
            px, py = body_point(x, r)
            ax.annotate(text, xy=(float(px), float(py)),
                        xytext=(float(px) + dx, float(py) + dy), ha=ha,
                        fontsize=9, color=INK, zorder=7,
                        arrowprops=dict(arrowstyle="-", lw=0.7, color=MUTED,
                                        shrinkA=0, shrinkB=2))

        lead(0.004, 0.0, -0.035, 0.020, "head", ha="right")
        lead(0.16, 0.55, -0.03, 0.052, "pharynx")
        lead(VULVA_FRAC, 1.02, 0.0, 0.046, "vulva")
        lead(0.935, -0.6, 0.02, -0.050, "anus")
        hx, hy = body_point(0.999, 0.0)
        ax.text(float(hx) + 0.012, float(hy), "tail", fontsize=9, va="center",
                color=INK)

    if regions:
        yb = -0.122
        thirds = [("anterior", 0, n_seg // 3),
                  ("midbody", n_seg // 3, 2 * n_seg // 3),
                  ("posterior", 2 * n_seg // 3, n_seg)]
        for name, a, b in thirds:
            xa, xb = frac[a], frac[b]
            ax.plot([xa, xb], [yb, yb], color=MUTED, lw=0.9)
            for e in (xa, xb):
                ax.plot([e, e], [yb - 0.005, yb + 0.005], color=MUTED, lw=0.9)
            ax.text(0.5 * (xa + xb), yb - 0.019, name, ha="center", fontsize=9,
                    color="#3E4F58")

    ax.set_xlim(-0.075, 1.075)
    ax.set_ylim(-0.158, 0.115)
    ax.set_aspect("equal")
    ax.axis("off")
    return {"channels": channels, "cells": cells}


def render_reference(path, n_seg=N_SEG, dpi=200):
    """Write the static numbering schematic used by the morphometry tool."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(16, 3.2))
    draw(ax, n_seg=n_seg)
    fig.patch.set_facecolor("white")
    fig.subplots_adjust(left=0.02, right=0.98, top=0.99, bottom=0.02)
    fig.savefig(path, dpi=dpi, facecolor="white")
    plt.close(fig)
    return path


if __name__ == "__main__":
    import sys

    import matplotlib
    matplotlib.use("Agg")
    out = sys.argv[1] if len(sys.argv) > 1 else "myocyte_schematic.png"
    print("wrote", render_reference(out))
