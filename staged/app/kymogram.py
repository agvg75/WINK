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

# Fluorophore ramps: black at zero to the channel's own colour at maximum.
CHANNEL_COLOUR = {"blue": (0.10, 0.35, 1.00),
                  "green": (0.10, 0.95, 0.25),
                  "red": (1.00, 0.15, 0.15)}

# A colour that appears in NO fluorophore ramp, so a gap cannot be mistaken for
# a dark frame. Desaturated warm grey - neither black nor any channel hue.
MISSING = (0.42, 0.40, 0.38)


class KymogramError(Exception):
    """Refusals that name the consequence."""


def channel_cmap(channel):
    """A black-to-fluorophore colormap with a distinct colour for missing data."""
    from matplotlib.colors import LinearSegmentedColormap
    rgb = CHANNEL_COLOUR.get(channel, (1.0, 1.0, 1.0))
    cm = LinearSegmentedColormap.from_list(
        f"wink_{channel}", [(0, 0, 0), rgb], N=256)
    cm.set_bad(MISSING)
    return cm


def curvature_cmap():
    """Diverging, centred on straight. Curvature is signed: the sign IS the side."""
    from matplotlib.colors import LinearSegmentedColormap
    cm = LinearSegmentedColormap.from_list(
        "wink_curv",
        [(0.15, 0.45, 0.95), (0.06, 0.06, 0.09), (0.98, 0.62, 0.10)], N=256)
    cm.set_bad(MISSING)
    return cm


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


def limits(grids, percentile=99.0, shared=True):
    """Display limits, stated rather than implied.

    `shared=True` computes one set across every grid given, which is what makes
    two recordings comparable. Per-recording limits make a dim animal and a
    bright one look identical.
    """
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
           on_flag=None, **kw):
    """Draw the panel stack. Returns (figure, axes). Click a panel to flag.

    `shared_limits` pins the fluorescence scale - pass the same value across a
    batch and the recordings become comparable by eye, which is the entire
    point of reviewing them together.
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize

    spec = panels(rows, **kw)
    if not spec:
        raise KymogramError("No panels could be built from these rows.")
    fluo = [p["grid"] for p in spec if p["kind"] == "fluorescence"]
    lo, hi, basis = (shared_limits if shared_limits
                     else limits(fluo, shared=True))
    curv = [p["grid"] for p in spec if p["kind"] == "curvature"]
    cmax = float(np.nanpercentile(np.abs(curv[0]), 98)) if curv else 1.0

    fig, axes = plt.subplots(len(spec), 1, figsize=(11, 1.35 * len(spec)),
                             sharex=True, constrained_layout=True)
    axes = np.atleast_1d(axes)
    for ax, p in zip(axes, spec):
        g = p["grid"]
        if p["kind"] == "curvature":
            im = ax.imshow(g, aspect="auto", cmap=curvature_cmap(),
                           norm=Normalize(-cmax, cmax), interpolation="nearest")
        else:
            im = ax.imshow(g, aspect="auto", cmap=channel_cmap(p["channel"]),
                           norm=Normalize(lo, hi), interpolation="nearest")
        cov = coverage(g)
        ax.set_ylabel(f"{p['label']}\n{cov['fraction']:.0%}", fontsize=8)
        ax.set_yticks([])
        fig.colorbar(im, ax=ax, pad=0.01, fraction=0.02)

    axes[-1].set_xlabel("frame" if not fps else f"frame  ({fps} fps)")
    if title:
        fig.suptitle(title, fontsize=10)

    if recording is not None:
        existing = load_flags(recording)
        for f in existing.get("flags", []):
            for ax in axes:
                ax.axvline(f["frame"], color="#FFCC00", lw=0.8, alpha=0.9)

        def onclick(event):
            if event.inaxes is None or event.xdata is None:
                return
            frame = int(round(event.xdata))
            idx = list(axes).index(event.inaxes) if event.inaxes in list(axes) else 0
            add_flag(recording, frame, panel=spec[idx]["label"],
                     reason="flagged from kymogram review")
            for ax in axes:
                ax.axvline(frame, color="#FFCC00", lw=0.8, alpha=0.9)
            event.canvas.draw_idle()
            if on_flag:
                on_flag(frame, spec[idx]["label"])

        fig.canvas.mpl_connect("button_press_event", onclick)

    return fig, axes, {"panels": [p["label"] for p in spec],
                       "limits": (lo, hi), "limit_basis": basis,
                       "coverage": [coverage(p["grid"]) for p in spec]}
