"""Show the flagged span as frames, so a person can answer the question.

The queue says "frames 49 to 136 of this recording look inverted". This is what
turns that into something answerable: the actual frames from inside the span,
beside frames from outside it, with the curvature strip underneath showing
where the span sits.

WHAT THE PERSON IS ACTUALLY JUDGING. Not the curvature - they have already been
told the curvature inverted. The question is WHY, and only the images answer it.
A tracking failure and a genuine reversal produce the same inversion, and the
way to tell them apart is to look at which end of the animal is the head. The
DIC channel is used for exactly that reason: the pharynx is visible in it, which
is why this lab scores pumping from these movies, and it is the one feature that
says which end is which without trusting the tracker that is under suspicion.

FRAMES FROM OUTSIDE THE SPAN ARE SHOWN TOO, and that is the point of the
layout. "Is this frame inverted?" is nearly unanswerable in isolation; "is this
frame the same way round as that one?" is easy. The comparison does the work.

NO OVERLAY, AND DELIBERATELY SO. The 18 recordings needing review have extracted
CSVs but no geometry sidecar, so no midline exists to draw. Drawing a midline
inferred from the very data under suspicion would beg the question anyway - the
person would be checking the tracker against itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for sub in ("app", "tools", "tools/batch_inspection"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)


class MontageError(Exception):
    """Refusals that name the consequence."""


def find_frames(folder, prefer=("ch03", "ch02", "ch01", "ch00")):
    """The image sequence to show. DIC first, because the pharynx is in it."""
    folder = Path(folder)
    for ch in prefer:
        d = folder / ch
        if d.is_dir():
            files = sorted(d.glob("*.tif")) or sorted(d.glob("*.tiff"))
            if files:
                return ch, files
    raise MontageError(
        f"No image channel found under {folder}. The span cannot be judged "
        f"from the curvature alone - that is what raised the question.")


def _read(path):
    import tifffile
    a = np.asarray(tifffile.imread(str(path)), dtype=float)
    if a.ndim == 3:
        # DIC is written as an RGB image with identical planes; any one will do.
        a = a[..., 0] if np.allclose(a[..., 0], a[..., 1]) else a.max(axis=2)
    return a


def sample_frames(span, n_frames, inside=4, outside=2):
    """Which frames to show: a few from inside the span, a few from each side.

    Outside frames come from BOTH sides where they exist. A span that runs to
    the end of the recording has no 'after', and showing only a 'before' would
    still answer the question - but silently dropping one side without saying
    so would let a reader think they had compared both.
    """
    a, b = int(span["start_frame"]), int(span["end_frame"])
    within = np.unique(np.linspace(a, b, min(inside, b - a + 1)).astype(int))
    before = [f for f in range(max(a - outside * 3, 0), a) if f >= 0][-outside:]
    after = [f for f in range(b + 1, min(b + 1 + outside * 3, n_frames))][:outside]
    return {"before": before, "inside": list(within), "after": after,
            "no_before": not before, "no_after": not after}


def render(folder, span, grid=None, n_frames=None, title=None,
           inside=4, outside=2, figsize=None):
    """Draw the montage. Returns (figure, layout)."""
    import matplotlib.pyplot as plt

    ch, files = find_frames(folder)
    n = n_frames or len(files)
    pick = sample_frames(span, n, inside, outside)
    order = ([("before", f) for f in pick["before"]]
             + [("inside", f) for f in pick["inside"]]
             + [("after", f) for f in pick["after"]])
    if not order:
        raise MontageError("The span yielded no frames to show.")

    ncol = len(order)
    has_strip = grid is not None
    fig = plt.figure(figsize=figsize or (1.5 * ncol, 2.5 if has_strip else 2.0),
                     constrained_layout=True)
    gs = fig.add_gridspec(2 if has_strip else 1, ncol,
                          height_ratios=[3, 1] if has_strip else [1])

    for i, (where, f) in enumerate(order):
        ax = fig.add_subplot(gs[0, i])
        if f < len(files):
            ax.imshow(_read(files[f]), cmap="gray", interpolation="nearest")
        else:
            ax.text(0.5, 0.5, "no frame", ha="center", va="center",
                    transform=ax.transAxes, fontsize=7)
        ax.set_xticks([]); ax.set_yticks([])
        flagged = where == "inside"
        ax.set_title(f"{f}", fontsize=7,
                     color="#B03030" if flagged else "#22303A")
        for s in ax.spines.values():
            s.set_color("#B03030" if flagged else "#C8CCD4")
            s.set_linewidth(2.0 if flagged else 0.8)

    if has_strip:
        import kymogram as ky
        from matplotlib.colors import Normalize
        ax = fig.add_subplot(gs[1, :])
        cmax = float(np.nanpercentile(np.abs(grid), 98)) or 1.0
        ax.imshow(grid, aspect="auto", cmap=ky.curvature_cmap(),
                  norm=Normalize(-cmax, cmax), interpolation="nearest")
        ax.invert_yaxis()
        ax.axvspan(span["start_frame"] - 0.5, span["end_frame"] + 0.5,
                   facecolor="none", edgecolor="#B03030", linewidth=1.6)
        ax.set_yticks([])
        ax.set_xlabel("frame", fontsize=7)
        ax.text(0.004, 0.06, "head", transform=ax.transAxes, fontsize=6,
                bbox=dict(facecolor="white", alpha=0.8, edgecolor="none",
                          pad=1.0))

    head = title or Path(folder).name
    fig.suptitle(f"{head}   frames {span['start_frame']}-{span['end_frame']} "
                 f"({span.get('n_frames', 0)} frames)   [{ch}]", fontsize=9)
    return fig, {"channel": ch, "frames_shown": order,
                 "no_before": pick["no_before"], "no_after": pick["no_after"],
                 "what_to_look_for": (
                     "Which end carries the pharynx. A red-bordered frame is "
                     "inside the flagged span; the others are outside it. If "
                     "the head is at the same end throughout, the span is not "
                     "inverted and the verdict is 'correct'."),
                 "sides_missing": (
                     "This span reaches the edge of the recording, so there "
                     "are no frames on one side to compare against."
                     if pick["no_before"] or pick["no_after"] else None)}


def review(folder, span, csv_path, grid=None, n_frames=None, on_done=None):
    """The montage with verdict buttons. Writes straight into the sidecar."""
    import matplotlib.pyplot as plt
    from matplotlib.widgets import Button
    import orientation_review as orv

    fig, layout = render(folder, span, grid, n_frames)
    fig.subplots_adjust(bottom=0.16)
    state = {"verdict": None}

    def _set(v):
        def handler(_event):
            state["verdict"] = v
            doc = orv.load(csv_path)
            spans = doc.get("spans") or [span]
            for s in spans:
                if s["start_frame"] == span["start_frame"]:
                    s["verdict"] = v
            orv.record(csv_path, spans, by="montage review")
            fig.suptitle(f"{fig._suptitle.get_text()}   ->  {v.upper()}",
                         fontsize=9)
            fig.canvas.draw_idle()
            if on_done:
                on_done(v)
        return handler

    axes = [fig.add_axes([0.10 + i * 0.22, 0.03, 0.20, 0.07])
            for i in range(3)]
    labels = [("inverted", "#B03030"), ("correct", "#3E7C4A"),
              ("unsure", "#8A7A20")]
    buttons = []
    for ax, (lab, col) in zip(axes, labels):
        b = Button(ax, lab, color="#F2F2F2", hovercolor=col)
        b.on_clicked(_set(lab))
        buttons.append(b)
    fig._wink_buttons = buttons          # keep them alive
    return fig, state, layout
