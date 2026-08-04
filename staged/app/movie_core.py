"""Shared engine for WINK results movies.

A results movie shows several panels of an already-analysed recording sharing
one time cursor, so the relationship between them is observed rather than
asserted. The RGBCaMP movie was the first; kinematics, population tracking and
single-channel GCaMP want the same thing over different data.

This holds everything that is NOT specific to one assay: the blitting render
loop, the video writer and its sharp edges, the preview contact sheet, the
provenance record, and the display arithmetic (smoothing, channel limits) that
every one of them needs.

THE RULE EVERY ADAPTER INHERITS: a results movie MEASURES NOTHING. Every value
on screen is read from what the analysis already produced. If a number is not
in those files it does not appear. That is what makes re-rendering cheap and
safe, so display choices stay render-time parameters rather than commitments.

An adapter supplies a MovieSource: how many frames, what to draw once, what to
change per frame, and which artists move. It does not touch ffmpeg, blitting,
or provenance.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class MovieInputError(RuntimeError):
    """Raised with a message that names the consequence, not the errno.

    Adapters should say what will go wrong and what to do about it. "File not
    found" tells a student nothing; "the sidecar describes 155 frames and the
    CSV describes 156, so this would draw one recording's geometry over
    another's numbers and look entirely normal" tells them everything.
    """


# --------------------------------------------------------------------------- #
# Display arithmetic
# --------------------------------------------------------------------------- #
def smooth_window_frames(seconds, fps):
    """Odd frame count for a smoothing window given in SECONDS.

    Windows are specified in seconds and converted with the declared fps, never
    fixed in frames: the same window then means the same thing on recordings
    taken at different rates.
    """
    n = int(round(float(seconds) * float(fps)))
    if n < 2:
        return 0
    return n + 1 if n % 2 == 0 else n


def moving_average(values, window):
    """NaN-aware centred moving average.

    Gaps stay gaps: a window with no finite samples returns NaN rather than
    borrowing from further away, so a smoothed trace never draws across a
    stretch where nothing was measured.
    """
    v = np.asarray(values, dtype=float)
    if window < 2:
        return v
    finite = np.isfinite(v).astype(float)
    filled = np.where(np.isfinite(v), v, 0.0)
    kernel = np.ones(int(window), dtype=float)
    num = np.convolve(filled, kernel, mode="same")
    den = np.convolve(finite, kernel, mode="same")
    return np.divide(num, den, out=np.full_like(num, np.nan), where=den > 0)


def read_frame(path):
    from PIL import Image
    return np.asarray(Image.open(path))


def sampled_limits(files, plane=None, n_sample=12, pct=(50.0, 100.0)):
    """Display limits for an image sequence, sampled across the WHOLE recording.

    Sampled rather than autoscaled per frame so brightness is comparable frame
    to frame - a per-frame rescale makes a dim frame look as bright as a lit
    one, which for a calcium channel destroys the signal being looked at.

    The percentiles are deliberately lopsided. An animal occupies a few percent
    of the frame, so even a 99.8th percentile of all pixels is still plate
    background, and symmetric limits render weak channels completely black.
    """
    if not files:
        return 0.0, 1.0
    idx = np.unique(np.linspace(0, len(files) - 1,
                                min(int(n_sample), len(files))).astype(int))
    vals = []
    for i in idx:
        arr = np.asarray(read_frame(files[int(i)]))
        if arr.ndim == 3:
            arr = arr[..., plane if plane is not None else 0]
        vals.append(np.asarray(arr, dtype=float).ravel())
    pooled = np.concatenate(vals)
    lo, hi = np.percentile(pooled, pct[0]), np.percentile(pooled, pct[1])
    if hi <= lo:
        hi = float(lo) + 1.0
    return float(lo), float(hi)


def content_rows(width_in, left, right, panels_n, aspects, max_frame_row=4.0):
    """Row heights DERIVED from what each row contains, not guessed.

    Square frames get a row as tall as they are wide; a 4.2:1 schematic gets a
    row matching its own aspect. Guessing these is what leaves white gutters
    either side of everything. The frame row is capped so a single panel cannot
    claim the full width and make a figure taller than it is wide.
    """
    usable = float(width_in) * (float(right) - float(left))
    rows = [min(usable / max(1, int(panels_n)), max_frame_row)]
    for aspect in aspects:
        rows.append(usable / float(aspect) if aspect else 1.0)
    return rows, usable


# --------------------------------------------------------------------------- #
# The source contract
# --------------------------------------------------------------------------- #
class MovieSource:
    """What an adapter must provide. Nothing here touches video or blitting.

    Required attributes: ``base`` (output name stem), ``n_frames``, ``fps``.
    """

    base = "recording"
    n_frames = 0
    fps = 1.0

    def build_figure(self, **options):
        """Return (fig, dyn, ctx). Draw everything static ONCE; put every
        artist that changes per frame into ``dyn``."""
        raise NotImplementedError

    def update(self, fig, dyn, ctx, index):
        """Point every dynamic artist at frame ``index``."""
        raise NotImplementedError

    def dynamic_artists(self, dyn):
        """The artists to redraw per frame. Anything omitted freezes on the
        first frame under blitting, which looks like working code."""
        raise NotImplementedError

    def provenance(self, ctx, options):
        """Adapter-specific record, merged into the shared one."""
        return {}

    def frame_label(self, index):
        return f"frame {index + 1} / {self.n_frames}"


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def render(source, out_path, decimate=1, fps=None, progress=None,
           options=None, tool_name="WINK results movie", tool_version="0.1.0"):
    """Write the movie and its provenance JSON. Returns (path, provenance).

    Static content is drawn once and captured; per frame only the artists the
    adapter declares are redrawn and blitted.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import imageio.v2 as imageio

    options = dict(options or {})
    out_path = Path(out_path)
    fig, dyn, ctx = source.build_figure(**options)
    canvas = fig.canvas
    canvas.draw()
    background = canvas.copy_from_bbox(fig.bbox)

    indices = list(range(0, source.n_frames, max(1, int(decimate))))
    out_fps = float(fps or max(1.0, source.fps))
    writer = imageio.get_writer(str(out_path), fps=out_fps,
                                macro_block_size=None)
    try:
        for n, i in enumerate(indices):
            source.update(fig, dyn, ctx, i)
            canvas.restore_region(background)
            for artist in source.dynamic_artists(dyn):
                fig.draw_artist(artist)
            canvas.blit(fig.bbox)
            frame = np.asarray(canvas.buffer_rgba())[..., :3]
            # libx264 rejects odd dimensions, and a figure sized from content
            # aspect lands on one whenever it likes. Trim rather than rescale:
            # a rescale would resample every pixel of every frame.
            frame = frame[:frame.shape[0] // 2 * 2, :frame.shape[1] // 2 * 2]
            writer.append_data(frame)
            if progress and (n % 20 == 0 or n == len(indices) - 1):
                progress(n + 1, len(indices))
    finally:
        writer.close()
        plt.close(fig)

    prov = {
        "tool": tool_name, "tool_version": tool_version,
        "n_frames_source": source.n_frames,
        "n_frames_rendered": len(indices),
        "decimate": int(decimate), "output_fps": out_fps,
        "options": {k: v for k, v in options.items()
                    if isinstance(v, (str, int, float, bool, type(None)))},
    }
    prov.update(source.provenance(ctx, options) or {})
    Path(out_path).with_name(out_path.stem + "_provenance.json").write_text(
        json.dumps(prov, indent=2, default=str), encoding="utf-8")
    return out_path, prov


def preview(source, out_path, picks=None, options=None, n=4):
    """Contact sheet of representative frames.

    Choosing a display setting from four stills beats rendering a whole movie
    twice, which is the loop this exists to avoid.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    options = dict(options or {})
    if picks is None:
        picks = sorted({0, source.n_frames // 3, 2 * source.n_frames // 3,
                        max(0, source.n_frames - 1)})[:n]
    picks = [p for p in picks if 0 <= p < source.n_frames] or [0]

    fig, dyn, ctx = source.build_figure(**options)
    sheet, axes = plt.subplots(len(picks), 1,
                               figsize=(11, 3.2 * len(picks)))
    axes = np.atleast_1d(axes)
    for ax, i in zip(axes, picks):
        source.update(fig, dyn, ctx, i)
        fig.canvas.draw()
        ax.imshow(np.asarray(fig.canvas.buffer_rgba())[..., :3])
        ax.set_title(source.frame_label(i), fontsize=9, loc="left")
        ax.axis("off")
    sheet.tight_layout()
    sheet.savefig(str(out_path), dpi=120, facecolor="white")
    plt.close(fig)
    plt.close(sheet)
    return Path(out_path)
