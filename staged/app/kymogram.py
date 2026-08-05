"""The whole animal and the whole recording in one look, so oddities jump out.

Andres's design for reviewing at scale: not one file at a time, but a dense
display where a recording's entire behaviour is visible at once, and a click on
anything strange flags that frame AND that recording for manual inspection.

For an RGBCaMP animal that is FOUR kymograms: one curvature, three fluorescence.
The fluorescence ones follow their fluorophore - black at zero rising to the
channel's own colour - and each is split into TWO ROWS, dorsal and ventral,
because the myocytes alternate across the midline and a single row would
average the two sides of a bending animal into mush.

THREE THINGS THIS HAS TO GET RIGHT OR IT MISLEADS.

1. MISSING FRAMES MUST NOT LOOK DARK. Black is zero brightness. A frame that
   was never measured, rendered black, is indistinguishable from a frame where
   the muscle was silent - and a tracking dropout would read as a quiescent
   period. Gaps are drawn in a colour that appears nowhere in any fluorophore
   ramp, so an absence looks like an absence.

2. THE SCALE MUST BE STATED, AND SHARED WHEN COMPARING. Normalising each
   recording to its own maximum makes every animal look alike: a dim dystrophic
   animal and a bright control both fill the ramp. That is fine for spotting
   oddities within one recording and fatal for comparing across them, so the
   limits are explicit and a batch can pin them.

3. TIME MUST BE REAL TIME. Dropping skipped frames shortens the axis and slides
   everything after a dropout leftward, which quietly changes when events
   appear to happen. Frames are placed by index, not by position in the list of
   surviving rows.

Flagging writes a small sidecar per recording. It records the frame, the panel
clicked, and a reason - and it is reversible, because a review pass where you
cannot take a flag back becomes a pass nobody trusts.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

# Fluorophore ramps: WHITE at zero rising to the channel's own colour.
#
# Inverted from the microscope's own black-on-dark, and for a reason beyond
# print economy. On a black-based ramp the low end is perceptually crushed -
# black to dark blue is a much smaller visual step than mid to bright blue - so
# resolution is lost exactly where RESTING calcium lives, which is the quantity
# the dystrophy work cares about most. A white-based ramp spends its
# perceptual range at the bottom instead.
CHANNEL_COLOUR = {"blue": (0.05, 0.25, 0.85),
                  "green": (0.00, 0.60, 0.15),
                  "red": (0.85, 0.05, 0.05)}

# With white at zero, MISSING is dark - which on a white-to-colour ramp cannot
# be confused with anything, because nothing else in the panel is dark.
MISSING = (0.20, 0.20, 0.24)


# The head carries ADDITIONAL reporters in green and red, which is why this lab
# does not read body-wall calcium there. Matches worm_kinetics.HEAD_SEGMENTS.
HEAD_SEGMENTS = tuple(range(8))
# Blue survives the head: worm_kinetics.KEEP_IN_HEAD says the same.
MASK_HEAD_CHANNELS = ("green", "red")


class KymogramError(Exception):
    """Refusals that name the consequence."""


def channel_cmap(channel):
    """A white-to-fluorophore colormap with a distinct colour for missing data."""
    from matplotlib.colors import LinearSegmentedColormap
    rgb = CHANNEL_COLOUR.get(channel, (0.2, 0.2, 0.2))
    cm = LinearSegmentedColormap.from_list(
        f"wink_{channel}", [(1, 1, 1), rgb], N=256)
    cm.set_bad(MISSING)
    return cm


def curvature_cmap():
    """Red-white-blue, the convention for curvature kymographs in this field.

    White is straight. Curvature is signed and the sign IS the side, so a
    diverging map centred on zero puts dorsal and ventral bends on opposite
    limbs and makes the travelling wave read as alternating bands. Matching the
    convention matters more than any improvement on it: a reader who has seen
    one worm curvature kymograph can read this one without a legend.
    """
    from matplotlib.colors import LinearSegmentedColormap
    cm = LinearSegmentedColormap.from_list(
        "wink_curv",
        [(0.02, 0.19, 0.55), (0.26, 0.52, 0.80), (1, 1, 1),
         (0.84, 0.38, 0.30), (0.40, 0.00, 0.12)], N=256)
    cm.set_bad(MISSING)
    return cm


def downsample(grid, max_columns, keep="structure"):
    """Compress the time axis. `keep` decides WHAT the compression protects.

    THIS DEFAULT WAS WRONG AND IS NOW CORRECTED. The first version preserved
    point outliers, on the theory that a review display exists to make one bad
    frame jump out. It does not. A recording survives one bad frame. What a
    kymogram is for is spotting things that SPAN TIME - a bad section, a head
    flip, a break in the continuity of the travelling wave - and preserving
    extremes actively works against that, because it injects the spikiest
    sample of every block into the picture and turns smooth structure into
    noise. The wave is the signal; the outlier is not.

      "structure"  (default) the column MEDIAN. Preserves the wave, so a break
                   in it is visible as a break rather than lost in speckle. A
                   bad SECTION still shows, because many bad frames move the
                   median of their block.
      "extreme"    the value furthest from the column median. Only for hunting
                   isolated artefacts, which is a different job from review.

    Returns (grid, frames_per_column). At 1 the grid is untouched.
    """
    n = grid.shape[1]
    if max_columns is None or n <= int(max_columns):
        return grid, 1
    step = int(np.ceil(n / int(max_columns)))
    pad = (-n) % step
    if pad:
        grid = np.concatenate(
            [grid, np.full((grid.shape[0], pad), np.nan)], axis=1)
    blocks = grid.reshape(grid.shape[0], -1, step)
    allnan = np.all(np.isnan(blocks), axis=2)
    import warnings
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        # An all-NaN block is an expected case - it is a gap - and is
        # restored to NaN below, so the warning is noise.
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(blocks, axis=2)
        if keep == "structure":
            out = med
        elif keep == "extreme":
            dev = np.abs(blocks - med[:, :, None])
            dev = np.where(np.isnan(blocks), -np.inf, dev)
            out = np.take_along_axis(blocks, np.nanargmax(dev, axis=2)[:, :, None],
                                     axis=2)[:, :, 0]
        else:
            raise KymogramError(
                f"keep must be 'structure' or 'extreme', not {keep!r}.")
    # A block that is entirely missing must stay missing rather than inherit
    # whatever the reduction fell back on.
    out = np.asarray(out, dtype=float).copy()
    out[allnan] = np.nan
    return out, step


# Kept under the old name so nothing that called it breaks, but it is no longer
# the default and the docstring above says why.
def downsample_preserving_outliers(grid, max_columns):
    return downsample(grid, max_columns, keep="extreme")


def build(rows, value, n_seg=24, side=None, n_frames=None):
    """A (segment x frame) array from long-format rows. Gaps stay as NaN.

    `side` selects one hemisegment label; None pools both, which is right for a
    per-segment quantity like curvature and wrong for fluorescence.
    """
    if not rows:
        raise KymogramError("No rows supplied; there is nothing to draw.")
    frames = [int(r["frame"]) for r in rows]
    total = int(n_frames) if n_frames else max(frames) + 1
    # NaN, not zero. An unmeasured cell must render as missing, and zero is a
    # real brightness that would render as a dark muscle.
    grid = np.full((int(n_seg), total), np.nan, dtype=float)
    for r in rows:
        if side is not None and r.get("hemisegment") != side:
            continue
        seg = r.get("segment")
        if seg is None or seg < 0 or seg >= n_seg:
            continue
        v = r.get(value)
        if v is None:
            continue
        # Placed by FRAME INDEX, so a dropout leaves a gap rather than sliding
        # everything after it leftward and changing when events appear.
        grid[int(seg), int(r["frame"])] = float(v)
    return grid


def limits(grids, percentile=99.0, shared=True, exclude_rows=None):
    """Display limits, stated rather than implied.

    `shared=True` computes one set across every grid given, which is what makes
    two recordings comparable. Per-recording limits make a dim animal and a
    bright one look identical.

    `exclude_rows` keeps segments OUT OF THE SCALE without removing them from
    the picture. The head carries extra reporters in green and red, so including
    it sets the ceiling from tissue nobody is measuring and crushes the entire
    body into the bottom of the ramp - which is exactly what the first render
    did. The body normalises the body.
    """
    if exclude_rows is not None:
        keep = [i for i in range(max(g.shape[0] for g in grids if g is not None))
                if i not in set(exclude_rows)]
        grids = [g[keep] if g is not None else None for g in grids]
    arrays = [g for g in grids if g is not None and np.isfinite(g).any()]
    if not arrays:
        return (0.0, 1.0, {"basis": "no finite data", "shared": shared})
    if shared:
        pool = np.concatenate([g[np.isfinite(g)].ravel() for g in arrays])
        lo, hi = float(np.nanmin(pool)), float(np.nanpercentile(pool, percentile))
    else:
        lo = float(min(np.nanmin(g) for g in arrays))
        hi = float(max(np.nanpercentile(g[np.isfinite(g)], percentile)
                       for g in arrays))
    if hi <= lo:
        hi = lo + 1.0
    return (lo, hi, {
        "basis": f"{percentile}th percentile of {'all' if shared else 'each'} "
                 f"panel", "shared": bool(shared),
        "warning": (None if shared else
                    "Per-panel limits. Comparable WITHIN this recording only - "
                    "a dim animal and a bright one both fill the ramp, so two "
                    "recordings scaled this way cannot be compared by eye."),
    })


def panels(rows, channels=("blue", "green", "red"), n_seg=24,
           curvature="seg_curv_deg", value_suffix="_p90", n_frames=None,
           sides=("dorsal", "ventral")):
    """The four kymograms: curvature, then one per channel split by side.

    `value_suffix` defaults to `_p90` - the statistic that measured least
    sensitive to ROI area on real recordings, which is what a display used for
    spotting oddities should show. `_mean` tracked ROI area at r = -0.28 and
    would put a bending artefact on screen as though it were calcium.
    """
    present = {r.get("hemisegment") for r in rows}
    use_sides = [s for s in sides if s in present] or [None]
    out = [{"kind": "curvature", "label": "curvature (deg)",
            "side": None,
            "grid": build(rows, curvature, n_seg, None, n_frames)}]
    for ch in channels:
        key = f"{ch}{value_suffix}"
        if not any(key in r for r in rows):
            continue
        for s in use_sides:
            out.append({"kind": "fluorescence", "channel": ch, "side": s,
                        "label": f"{ch} {s or ''}".strip(),
                        "grid": build(rows, key, n_seg, s, n_frames)})
    return out


def coverage(grid):
    """How much of this panel was actually measured."""
    total = grid.size
    good = int(np.isfinite(grid).sum())
    return {"measured": good, "total": int(total),
            "fraction": round(good / max(total, 1), 4),
            "gap_columns": int(np.sum(~np.isfinite(grid).any(axis=0)))}


# --------------------------------------------------------------------------- #
# Flags
# --------------------------------------------------------------------------- #
def flag_path(recording):
    return Path(str(recording)).with_suffix(".wink_flags.json")


def load_flags(recording):
    try:
        return json.loads(flag_path(recording).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"recording": str(recording), "flags": []}
    except json.JSONDecodeError as exc:
        raise KymogramError(
            f"{flag_path(recording)} is not valid JSON ({exc}). Review flags "
            f"would be silently lost if this were ignored.")


def add_flag(recording, frame, panel="", reason="", by=""):
    """Flag one frame, and thereby the recording, for manual inspection."""
    doc = load_flags(recording)
    doc["flags"] = [f for f in doc["flags"]
                    if not (f["frame"] == int(frame) and f.get("panel") == panel)]
    doc["flags"].append({"frame": int(frame), "panel": panel,
                         "reason": reason, "by": by})
    doc["flags"].sort(key=lambda f: f["frame"])
    doc["recording_flagged"] = True
    flag_path(recording).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def remove_flag(recording, frame, panel=""):
    """Take a flag back. A review pass you cannot undo is one nobody trusts."""
    doc = load_flags(recording)
    before = len(doc["flags"])
    doc["flags"] = [f for f in doc["flags"]
                    if not (f["frame"] == int(frame) and f.get("panel") == panel)]
    doc["recording_flagged"] = bool(doc["flags"])
    flag_path(recording).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return before - len(doc["flags"])


def flagged_recordings(paths):
    """Which of these recordings carry any flag. The review queue."""
    out = []
    for p in paths:
        try:
            doc = load_flags(p)
        except KymogramError:
            out.append({"recording": str(p), "n_flags": None,
                        "error": "unreadable flag file"})
            continue
        if doc.get("flags"):
            out.append({"recording": str(p), "n_flags": len(doc["flags"]),
                        "frames": [f["frame"] for f in doc["flags"]]})
    return out


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #
def render(rows, recording=None, fps=None, shared_limits=None, title=None,
           on_flag=None, width=5.5, row_height=0.85, max_columns=1400,
           head_down=True, axis_labels=True,
           head_segments=HEAD_SEGMENTS, **kw):
    """Draw the panel stack. Returns (figure, axes). Click a panel to flag.

    `shared_limits` pins the fluorescence scale - pass the same value across a
    batch and the recordings become comparable by eye, which is the entire
    point of reviewing them together.

    HEAD DOWN BY DEFAULT, and labelled. Segment 0 is the head and imshow puts
    row 0 at the top, so the first version plotted head-up without saying so.
    This lab publishes head-down, and an unlabelled body axis is worse than a
    wrong one: a reader who knows the convention will assume it, and a reader
    who does not has no way to check. Both ends are now named on every panel.
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    from matplotlib.patches import Rectangle

    spec = panels(rows, **kw)
    if not spec:
        raise KymogramError("No panels could be built from these rows.")
    # Green and red are normalised on the BODY ONLY. Blue is not, because the
    # head does not compromise it.
    body_scaled = [p["grid"] for p in spec if p["kind"] == "fluorescence"
                   and p.get("channel") in MASK_HEAD_CHANNELS]
    other = [p["grid"] for p in spec if p["kind"] == "fluorescence"
             and p.get("channel") not in MASK_HEAD_CHANNELS]
    if shared_limits:
        lo, hi, basis = shared_limits
    elif body_scaled:
        lo, hi, basis = limits(body_scaled, shared=True,
                               exclude_rows=head_segments)
        basis["excluded"] = (f"segments {min(head_segments)}-"
                             f"{max(head_segments)} (extra reporters in "
                             f"{', '.join(MASK_HEAD_CHANNELS)})")
    else:
        lo, hi, basis = limits(other, shared=True)
    curv = [p["grid"] for p in spec if p["kind"] == "curvature"]
    cmax = float(np.nanpercentile(np.abs(curv[0]), 98)) if curv else 1.0

    fig, axes = plt.subplots(len(spec), 1,
                             figsize=(width, row_height * len(spec)),
                             sharex=True, constrained_layout=True)
    axes = np.atleast_1d(axes)
    step = 1
    for ax, p in zip(axes, spec):
        g, step = downsample_preserving_outliers(p["grid"], max_columns)
        p["grid_shown"] = g
        if p["kind"] == "curvature":
            im = ax.imshow(g, aspect="auto", cmap=curvature_cmap(),
                           norm=Normalize(-cmax, cmax), interpolation="nearest")
        else:
            im = ax.imshow(g, aspect="auto", cmap=channel_cmap(p["channel"]),
                           norm=Normalize(lo, hi), interpolation="nearest")
        # Segment 0 is the HEAD, and imshow puts row 0 at the top. This lab
        # publishes head-down, so flip unless asked otherwise.
        if head_down:
            ax.invert_yaxis()
        cov = coverage(p["grid"])
        # The label goes INSIDE the panel. At half width, stacked ylabels
        # collide with each other and with the neighbouring panel's - the first
        # render read "blue dorsalcurvature". Inside, they cannot.
        ax.text(0.006, 0.5, f"{p['label']}  {cov['fraction']:.0%}",
                transform=ax.transAxes, va="center", ha="left", fontsize=7,
                color="#22303A",
                bbox=dict(facecolor="white", alpha=0.72, edgecolor="none",
                          pad=1.2))
        ax.set_ylabel("")
        # Mark the head where its signal is NOT the one being measured. The
        # data stays - it is still drawn, and a reader can see what is there -
        # but the box says plainly that this stretch carries extra reporters
        # and is not body-wall calcium. Removing it would be worse: an absence
        # invites the assumption that nothing was there.
        if (p["kind"] == "fluorescence"
                and p.get("channel") in MASK_HEAD_CHANNELS and head_segments):
            h0, h1 = min(head_segments), max(head_segments)
            ax.add_patch(Rectangle(
                (-0.5, h0 - 0.5), g.shape[1], (h1 - h0) + 1,
                fill=False, edgecolor="#22303A", linewidth=1.0,
                linestyle=(0, (3, 2)), zorder=5))
            ax.text(0.985, (h0 + h1) / 2.0 / max(g.shape[0] - 1, 1)
                    if head_down else 1 - (h0 + h1) / 2.0 / max(g.shape[0] - 1, 1),
                    "head reporters - not body wall",
                    transform=ax.get_yaxis_transform(which="grid")
                    if False else ax.transAxes,
                    fontsize=5.5, ha="right", va="center", color="#22303A",
                    bbox=dict(facecolor="white", alpha=0.75, edgecolor="none",
                              pad=1.0), zorder=6)
        # ONE label, on the last panel only, inside the plot. Naming both ends
        # on all seven panels was clutter: once "head" is placed, the other end
        # is implied, and the panels share an axis so the convention carries
        # across all of them. The label sits inside because the margin at half
        # width is where the panels collide.
        if axis_labels and p is spec[-1]:
            ax.text(0.012, 0.06 if head_down else 0.94, "head",
                    transform=ax.transAxes, fontsize=6.5,
                    ha="left", va="bottom" if head_down else "top",
                    color="#22303A",
                    bbox=dict(facecolor="white", alpha=0.85,
                              edgecolor="none", pad=1.2), zorder=7)
        ax.set_yticks([])
        fig.colorbar(im, ax=ax, pad=0.01, fraction=0.02)

    axes[-1].set_xlabel("frame" if not fps else f"frame  ({fps} fps)")
    if title:
        fig.suptitle(title, fontsize=10)

    if recording is not None:
        existing = load_flags(recording)
        for f in existing.get("flags", []):
            for ax in axes:
                ax.axvline(f["frame"] / step, color="#E8A200", lw=0.8,
                           alpha=0.9)

        def onclick(event):
            if event.inaxes is None or event.xdata is None:
                return
            frame = int(round(event.xdata) * step)
            idx = list(axes).index(event.inaxes) if event.inaxes in list(axes) else 0
            add_flag(recording, frame, panel=spec[idx]["label"],
                     reason="flagged from kymogram review")
            for ax in axes:
                ax.axvline(frame / step, color="#E8A200", lw=0.8, alpha=0.9)
            event.canvas.draw_idle()
            if on_flag:
                on_flag(frame, spec[idx]["label"])

        fig.canvas.mpl_connect("button_press_event", onclick)

    return fig, axes, {"panels": [p["label"] for p in spec],
                       "orientation": ("head at bottom" if head_down
                                       else "head at top"),
                       "head_masked_in": list(MASK_HEAD_CHANNELS),
                       "head_segments": list(head_segments),
                       "limits": (lo, hi), "limit_basis": basis,
                       "frames_per_column": step,
                       "coverage": [coverage(p["grid"]) for p in spec]}
