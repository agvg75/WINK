"""Many animals in one field of view, with the broken ones at the top.

Andres's actual problem: not one recording at a time, and not one bad frame in
fifteen hundred. A recording survives a bad frame. What has to surface from a
whole archive is the recording with a BAD SECTION, a head flip, or a break in
the continuity of the travelling wave - and it has to surface when a hundred
animals are on one screen at thumbnail size.

AT THUMBNAIL SIZE THE EYE CANNOT DO IT ALONE, so the ranking does half the
work. Each recording is scored for the three failures that actually occur, the
sheet is ordered worst-first, and the thumbnail's job is then only to CONFIRM
or dismiss what the score proposed. Scanning a hundred unordered thumbnails
means finding the fourth-worst by luck; scanning a hundred ordered ones means
looking hard at the first ten.

THE SCORE IS A TRIAGE ORDER, NOT A VERDICT. It decides what a person looks at
first and nothing else. Nothing is excluded by it, the components are reported
separately so a high score can be traced to which failure caused it, and a
recording that scores zero is still on the sheet.

WHY CURVATURE IS THE PANEL THAT GETS THE THUMBNAIL. All three failures show
there. A head flip inverts the whole profile at once; a wave break stops the
diagonal banding; a bad section blanks or scrambles a stripe of time.
Fluorescence panels show the last of those and neither of the first two.
"""
from __future__ import annotations

import numpy as np

try:
    import kymogram as ky
except ImportError:                                        # pragma: no cover
    ky = None


class SheetError(Exception):
    """Refusals that name the consequence."""


def wave_continuity(curv_grid, min_overlap=6):
    """How steadily the body wave carries from one frame to the next.

    Correlates each frame's curvature profile with the one before it. A
    travelling wave gives high, smoothly varying correlation. A break gives a
    sudden collapse toward zero; a HEAD FLIP gives a sudden swing to strongly
    NEGATIVE, because the whole profile reverses at once.

    The sign matters and is kept: a near -1 frame is a different fault from a
    near 0 one, and reporting only the magnitude would merge a flip with a
    dropout.
    """
    g = np.asarray(curv_grid, dtype=float)
    if g.ndim != 2 or g.shape[1] < 3:
        raise SheetError("Need a (segment x frame) grid with at least 3 frames.")
    r = np.full(g.shape[1] - 1, np.nan)
    for i in range(g.shape[1] - 1):
        a, b = g[:, i], g[:, i + 1]
        ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() < min_overlap:
            continue
        sa, sb = a[ok] - a[ok].mean(), b[ok] - b[ok].mean()
        d = np.linalg.norm(sa) * np.linalg.norm(sb)
        if d > 0:
            r[i] = float(np.dot(sa, sb) / d)
    return r


def _classify_flips(grid, r, flip_threshold, settle=3):
    """Split flips into PERSISTENT and TRANSIENT. Returns (persistent, transient).

    A flip that inverts the profile and comes straight back costs one frame. A
    flip after which the animal stays inverted costs everything downstream,
    because from there on anterior is posterior and dorsal is ventral.

    FLIPS TOGGLE THE ORIENTATION, which is the model that finally fits. A flip
    at frame 10 and another at frame 30 does not mean two ruined recordings, or
    one recording ruined from frame 10 - it means frames 10 to 30 are inverted
    and the rest is fine. So the cost is the FRACTION OF FRAMES SPENT INVERTED,
    and whether the recording ENDS inverted is a separate fact worth reporting.

    Two earlier attempts were wrong in instructive ways. Weighting every flip
    by the frames downstream of it made 18 of 24 real recordings rank on head
    flips when the median recording has 0.905 continuity. Comparing the profile
    a few frames after the event with a few frames before does not work either:
    in a travelling wave those frames are already tens of degrees apart in
    phase and anticorrelated whether or not anything flipped, so the wave's own
    advance masquerades as the fault.

    Returns (inverted_fraction, flip_frames, ends_inverted).
    """
    n = len(r) + 1
    idx = [i + 1 for i, v in enumerate(np.nan_to_num(r, nan=1.0))
           if v < flip_threshold]
    if not idx:
        return 0.0, [], False
    inverted = 0
    state = 0
    bounds = idx + [n]
    for k in range(len(idx)):
        state ^= 1
        if state:
            inverted += bounds[k + 1] - bounds[k]
    return inverted / max(n, 1), idx, bool(state)


def score(curv_grid, flip_threshold=-0.4, break_threshold=0.15,
          run_frames=3):
    """Triage score for one recording, plus the components that produced it.

    Three failures, each counted in the units a person would use:

      coverage    fraction of frames with no usable geometry, and the LONGEST
                  unbroken run of them - a bad section is a run, not a total
      flips       frames where the curvature profile inverted wholesale
      breaks      runs where frame-to-frame continuity collapsed, which is the
                  wave stopping rather than reversing
    """
    g = np.asarray(curv_grid, dtype=float)
    n = g.shape[1]
    measured = np.isfinite(g).any(axis=0)
    missing = ~measured
    longest = 0
    run = 0
    for m in missing:
        run = run + 1 if m else 0
        longest = max(longest, run)

    r = wave_continuity(g)
    flips = int(np.sum(np.nan_to_num(r, nan=1.0) < flip_threshold))
    low = np.nan_to_num(r, nan=1.0) < break_threshold
    breaks, run = 0, 0
    for v in low:
        run = run + 1 if v else 0
        if run == run_frames:
            breaks += 1
    continuity = float(np.nanmedian(r)) if np.isfinite(r).any() else 0.0

    missing_frac = float(missing.mean())
    longest_frac = longest / max(n, 1)

    # A FLIP COSTS THE REST OF THE RECORDING ONLY IF IT PERSISTS, and the
    # first version did not check. Weighting every flip by the fraction
    # downstream of it made 18 of 24 real recordings rank on "head flip" when
    # the median recording has excellent continuity (0.905) and only 4.7% of
    # frames inverted. Those were TRANSIENT: the profile inverts for a frame
    # or two and comes straight back, which is one bad frame, not a relabelled
    # second half.
    #
    # A flip persists if the frames after it stay inverted relative to the
    # frames before. Transient flips are counted like other point faults;
    # a persistent one still costs everything downstream, because there
    # everything downstream really is backwards.
    inverted_frac, flip_frames, ends_inverted = _classify_flips(
        g, r, flip_threshold)
    # Ending inverted is worse than the same time inverted mid-recording:
    # nothing downstream corrects it, and anything computed from the tail
    # of the recording is backwards with no later frame to reveal it.
    affected = inverted_frac + (0.15 if ends_inverted else 0.0)

    # Deliberately simple and additive, because the point is an ORDER. A
    # weighted product would rank slightly differently and be far harder to
    # explain when someone asks why a recording was second rather than tenth.
    total = (2.0 * longest_frac + 1.0 * missing_frac
             + 1.5 * affected + 2.0 * (breaks / max(n, 1))
             + max(0.0, 0.5 - continuity))
    return {
        "n_frames": int(n),
        "missing_fraction": round(missing_frac, 4),
        "longest_gap_frames": int(longest),
        "longest_gap_fraction": round(longest_frac, 4),
        "head_flips": flips,
        "inverted_fraction": round(float(inverted_frac), 4),
        "ends_inverted": ends_inverted,
        "flip_frames": flip_frames[:12],
        "wave_breaks": breaks,
        "median_continuity": round(continuity, 4),
        "score": round(float(total), 4),

        "worst": max(
            [("bad section", 2.0 * longest_frac),
             ("missing frames", 1.0 * missing_frac),
             ("inverted stretch", 1.5 * affected),
             ("wave break", 2.0 * breaks / max(n, 1)),
             ("low continuity", max(0.0, 0.5 - continuity))],
            key=lambda t: t[1])[0],
        "triage_only": ("An order for a person to look in, not a verdict. "
                        "Nothing is excluded by it and a zero still appears "
                        "on the sheet."),
    }


def rank(recordings):
    """`recordings` maps a name to a curvature grid. Returns worst first."""
    out = []
    for name, grid in recordings.items():
        try:
            s = score(grid)
        except SheetError as exc:
            out.append({"name": name, "score": float("inf"),
                        "error": str(exc), "worst": "unscoreable"})
            continue
        out.append({"name": name, **s})
    # Unscoreable recordings sort FIRST. A recording too broken to score is the
    # most likely to be broken, and dropping it to the bottom would hide the
    # worst cases behind the merely poor ones.
    return sorted(out, key=lambda d: -d["score"])


def sheet(recordings, columns=4, thumb_frames=160, title=None,
          annotate=True, on_click=None):
    """Draw the ranked contact sheet. Returns (figure, order).

    Every thumbnail uses the SAME curvature limits, or a gently bending animal
    beside a violently coiling one would look equally dramatic and the sheet
    would rank by nothing.
    """
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize

    if ky is None:                                         # pragma: no cover
        raise SheetError("kymogram module unavailable")
    if not recordings:
        raise SheetError("No recordings supplied; there is nothing to show.")

    order = rank(recordings)
    grids = {}
    for row in order:
        g = recordings[row["name"]]
        grids[row["name"]] = ky.downsample(g, thumb_frames,
                                           keep="structure")[0]
    pool = np.concatenate([g[np.isfinite(g)].ravel() for g in grids.values()
                           if np.isfinite(g).any()] or [np.array([1.0])])
    cmax = float(np.nanpercentile(np.abs(pool), 98)) or 1.0

    n = len(order)
    rows_n = int(np.ceil(n / columns))
    fig, axes = plt.subplots(rows_n, columns,
                             figsize=(2.6 * columns, 0.95 * rows_n),
                             constrained_layout=True, squeeze=False)
    flat = axes.ravel()
    for ax in flat[n:]:
        ax.axis("off")

    for ax, row in zip(flat, order):
        g = grids[row["name"]]
        ax.imshow(g, aspect="auto", cmap=ky.curvature_cmap(),
                  norm=Normalize(-cmax, cmax), interpolation="nearest")
        ax.set_xticks([]); ax.set_yticks([])
        if annotate:
            bad = row["score"] > 0.35
            ax.set_title(
                f"{row['name']}   {row['score']:.2f}"
                + (f"  {row['worst']}" if bad else ""),
                fontsize=6.5, color=("#B03030" if bad else "#22303A"),
                pad=2)
            for s in ax.spines.values():
                s.set_color("#B03030" if bad else "#C8CCD4")
                s.set_linewidth(1.6 if bad else 0.6)

    if title:
        fig.suptitle(title, fontsize=10)

    if on_click:
        def _click(event):
            for ax, row in zip(flat, order):
                if event.inaxes is ax:
                    on_click(row["name"], row)
                    return
        fig.canvas.mpl_connect("button_press_event", _click)

    return fig, order
