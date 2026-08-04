"""Synchronized results movie for one "Track one worm" kinematics recording.

Four panels sharing one time cursor:

  1. the frame, with the tracked midline, head and tail overlaid
  2. head-bend (foraging) over time
  3. axial velocity over time
  4. a body-curvature kymograph

Sibling of tools/rgbcamp/pipeline/results_movie.py; both are adapters over
app/movie_core.py, so the render loop, video writer, preview and provenance
are shared rather than reimplemented.

THIS MODULE MEASURES NOTHING. Every value comes from the kinematics CSV the
DIC tracker exported. There is one kinematics computation path - run_one_kinematics
and the browser both read it - and this is not a second one.

Unlike RGBCaMP this needs no geometry sidecar: the tracker already writes
seg_x/seg_y per segment, plus head and tail, crop-corrected back to full-frame
coordinates (run_dic_kinematics.py:1065). The overlay comes straight out of the
same CSV as the numbers, so the two cannot disagree about which recording they
describe.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT / "app"), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import movie_core as mc                     # noqa: E402

# Result tables are read through read_table. Under pandas 3 a numeric column
# holding one stray non-numeric cell reads as StringDtype, and numpy then
# refuses np.isfinite on it - aborting an analysis with an error that names
# numpy internals rather than the column at fault. The import is guarded
# because these modules are launched several different ways and sys.path is
# not identical in all of them; a hard import would turn a latent dtype
# problem into a tool that will not start.
try:
    from table_io import read_table as _read_table
except Exception:                                    # pragma: no cover
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "app"))
        from table_io import read_table as _read_table
    except Exception:
        _read_table = None


def read_table(path, **kwargs):
    """pandas.read_csv with the pandas-3 dtype trap handled where available."""
    import pandas as _pd
    if _read_table is not None:
        return _read_table(path, **kwargs)
    return _pd.read_csv(path, **kwargs)


TOOL_NAME = "Kinematics results movie"
TOOL_VERSION = "0.1.0"
MovieInputError = mc.MovieInputError

REQUIRED = {"frame", "time_s", "segment", "seg_curv_deg", "fps"}
# The tracker reports whole-worm quantities under clearer names; run_one_kinematics
# aliases them for the shared algorithms and this follows the same mapping
# rather than inventing a third vocabulary.
VELOCITY_ALIASES = ("axial_vel_px_s", "centroid_speed_px_s")


class Recording:
    """One kinematics CSV, plus the image stack it was tracked on."""

    def __init__(self, csv_path, image_path=None):
        self.csv_path = Path(csv_path)
        if not self.csv_path.exists():
            raise MovieInputError(f"No kinematics CSV at {self.csv_path}.")
        self.df = read_table(self.csv_path, encoding="utf-8-sig")
        self.base = self.csv_path.with_suffix("").name

        missing = sorted(REQUIRED - set(self.df.columns))
        if missing:
            raise MovieInputError(
                "This is not a Track one worm / kinematics CSV - it is missing "
                + ", ".join(missing) + ".\n\n"
                "Rendering a movie from the wrong export would draw a worm "
                "that was never tracked in these frames.")

        for col in REQUIRED - {"frame"}:
            self.df[col] = pd.to_numeric(self.df[col], errors="coerce")

        self.frames = sorted(self.df["frame"].astype(int).unique())
        self.n_frames = len(self.frames)
        self.n_seg = int(self.df["segment"].max()) + 1
        self.fps = float(pd.to_numeric(self.df["fps"], errors="coerce").iloc[0] or 1.0)
        self.um_per_px = float(pd.to_numeric(
            self.df.get("um_per_px", pd.Series([0.0])), errors="coerce").iloc[0] or 0.0)

        self.velocity_column = next(
            (c for c in VELOCITY_ALIASES if c in self.df.columns), None)
        self.has_head_bend = "head_bend_deg" in self.df.columns

        self.image_path = Path(image_path) if image_path else None
        self.images = mc.FrameSource(self.image_path) if self.image_path else None
        if self.images and len(self.images) and len(self.images) != self.n_frames:
            # Close BEFORE raising. The stack is already open by this point, and
            # the exception's traceback keeps this half-built object alive, so
            # __del__ never runs and the file stays locked - every refused load
            # would leak a handle, which on a share is somebody else's tool
            # failing for no visible reason.
            n_images = len(self.images)
            self.images.close()
            self.images = None
            raise MovieInputError(
                f"The image stack has {n_images} frames and the CSV "
                f"describes {self.n_frames}. These are not the same recording, "
                f"or one of them is stale.\n\n"
                f"Rendering anyway would draw one recording's midline over "
                f"another's pixels and look entirely normal.")

        # Per-frame geometry, indexed once rather than filtered per frame -
        # at 6000+ frames a per-frame dataframe query dominates the render.
        self._geo = {}
        cols = [c for c in ("segment", "seg_x", "seg_y", "head_x", "head_y",
                            "tail_x", "tail_y") if c in self.df.columns]
        if "seg_x" in cols and "seg_y" in cols:
            for frame, block in self.df[["frame"] + cols].groupby("frame"):
                block = block.sort_values("segment")
                self._geo[int(frame)] = {
                    "mid": block[["seg_x", "seg_y"]].to_numpy(dtype=float),
                    "head": (block["head_x"].iloc[0], block["head_y"].iloc[0])
                            if "head_x" in block else None,
                    "tail": (block["tail_x"].iloc[0], block["tail_y"].iloc[0])
                            if "tail_x" in block else None,
                }

    # -- series, all read straight from the CSV ----------------------------
    def times(self):
        return self.df.groupby("frame")["time_s"].first().astype(float).to_numpy()

    def velocity(self):
        if self.velocity_column is None:
            return None
        return (self.df.groupby("frame")[self.velocity_column]
                .mean().astype(float).to_numpy())

    def head_bend(self):
        if not self.has_head_bend:
            return None
        return (self.df.groupby("frame")["head_bend_deg"]
                .first().astype(float).to_numpy())

    def curvature_kymograph(self):
        piv = self.df.pivot_table(index="segment", columns="frame",
                                  values="seg_curv_deg", aggfunc="mean")
        return piv.reindex(index=range(self.n_seg),
                           columns=self.frames).to_numpy(dtype=float)

    def quality_summary(self):
        out = {"n_frames": self.n_frames, "n_seg": self.n_seg}
        if "needs_help" in self.df:
            flagged = pd.to_numeric(self.df["needs_help"],
                                    errors="coerce").fillna(0) > 0
            out["rows_flagged_needs_help"] = int(flagged.sum())
            out["frames_flagged"] = int(
                self.df.loc[flagged, "frame"].nunique())
        curv = pd.to_numeric(self.df["seg_curv_deg"], errors="coerce")
        out["curvature_missing_rows"] = int(curv.isna().sum())
        out["curvature_missing_fraction"] = round(
            float(curv.isna().mean()), 4)
        out["frames_with_geometry"] = len(self._geo)
        return out

    def frame_geometry(self, frame_number):
        return self._geo.get(int(frame_number))

    def close(self):
        """Release the image stack handle. See movie_core.FrameSource.close -
        an unreleased handle locks the file for the life of the process."""
        if self.images is not None:
            self.images.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def load(csv_path, image_path=None):
    return Recording(csv_path, image_path=image_path)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def build_figure(rec, smooth_s=0.5, width_in=13.0, dpi=110):
    """Static layers drawn once; returns the artists that change per frame."""
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    times = rec.times()
    vel = rec.velocity()
    bend = rec.head_bend()
    kymo = rec.curvature_kymograph()
    quality = rec.quality_summary()
    win = mc.smooth_window_frames(smooth_s, rec.fps)

    left, right = 0.075, 0.975
    rows, usable = mc.content_rows(width_in, left, right, 1, [None, None, None])
    frame_h = min(usable * 0.42, 4.2)          # the frame is 4:3, not square
    rows = [frame_h, 1.15, 1.15, 1.45]
    height_in = sum(rows) + 1.5

    fig = plt.figure(figsize=(width_in, height_in), dpi=dpi)
    fig.patch.set_facecolor("white")
    gs = GridSpec(4, 1, figure=fig, height_ratios=rows, hspace=0.42,
                  left=left, right=right,
                  top=1.0 - 0.55 / height_in, bottom=0.60 / height_in)
    ax_img = fig.add_subplot(gs[0])
    ax_bend = fig.add_subplot(gs[1])
    ax_vel = fig.add_subplot(gs[2])
    ax_kym = fig.add_subplot(gs[3])

    dyn = {}

    # -- panel 1: the frame with the tracked midline -----------------------
    ax_img.axis("off")
    if rec.images and len(rec.images):
        lo, hi = rec.images.limits(pct=(1.0, 99.5))
        dyn["image"] = ax_img.imshow(rec.images.get(0), cmap="gray",
                                     vmin=lo, vmax=hi, animated=True)
    else:
        ax_img.text(0.5, 0.5, "no image stack supplied - the traces below "
                              "are unaffected", ha="center", va="center",
                    fontsize=9, color="#a00000")
    dyn["midline"], = ax_img.plot([], [], lw=1.6, color="#00C8FF", animated=True)
    dyn["head"], = ax_img.plot([], [], "o", ms=5, color="#20C020", animated=True)
    dyn["tail"], = ax_img.plot([], [], "o", ms=5, color="#E03020", animated=True)
    dyn["flag"] = ax_img.text(
        0.01, 0.98, "", transform=ax_img.transAxes, va="top", fontsize=9,
        color="#C1440E", animated=True)

    # -- panel 2: head bend (foraging) -------------------------------------
    if bend is not None:
        _trace(ax_bend, times, bend, win, rec.fps, "#3A4A52")
        ax_bend.set_ylabel("head bend\n(deg)%s" % _smooth_note(win, rec.fps),
                           fontsize=7.5)
    else:
        ax_bend.text(0.5, 0.5, "no head_bend_deg column in this export",
                     ha="center", va="center", fontsize=9, color="#5E6E76")
        ax_bend.set_yticks([])
    ax_bend.axhline(0, lw=0.6, color="#9AA6AC")
    ax_bend.set_xlim(float(times[0]), float(times[-1]))
    ax_bend.tick_params(labelsize=8)
    dyn["bend_cursor"] = ax_bend.axvline(float(times[0]), color="#C1440E",
                                         lw=1.2, animated=True)

    # -- panel 3: velocity --------------------------------------------------
    if vel is not None:
        _trace(ax_vel, times, vel, win, rec.fps, "#3A4A52")
        # A declared scale of exactly 1.000 is placeholder-shaped: it is what a
        # field left alone tends to hold, and it converts px to um invisibly by
        # doing nothing. Say so rather than presenting um/s as calibrated - the
        # reader can then decide, which they cannot do if nothing is said.
        if rec.um_per_px <= 0:
            units = "px/s - scale NOT calibrated"
        elif abs(rec.um_per_px - 1.0) < 1e-9:
            units = "um/s at a declared 1.000 um/px\n(check - 1.000 is often an unset default)"
        else:
            units = "um/s, declared scale"
        ax_vel.set_ylabel("centroid speed\n(%s)%s"
                          % (units, _smooth_note(win, rec.fps)), fontsize=7.5)
    else:
        ax_vel.text(0.5, 0.5, "no velocity column in this export",
                    ha="center", va="center", fontsize=9, color="#5E6E76")
        ax_vel.set_yticks([])
    ax_vel.set_xlim(float(times[0]), float(times[-1]))
    ax_vel.tick_params(labelsize=8)
    dyn["vel_cursor"] = ax_vel.axvline(float(times[0]), color="#C1440E",
                                       lw=1.2, animated=True)

    # -- panel 4: curvature kymograph ---------------------------------------
    shown = kymo
    if win >= 2:
        shown = np.vstack([mc.moving_average(row, win) for row in kymo])
    finite = shown[np.isfinite(shown)]
    lim = float(np.percentile(np.abs(finite), 99)) if finite.size else 1.0
    ax_kym.imshow(shown, aspect="auto", cmap="RdBu_r", vmin=-lim, vmax=lim,
                  extent=[float(times[0]), float(times[-1]), rec.n_seg, 0],
                  interpolation="nearest")
    ax_kym.set_ylabel("segment\n(head at top)%s" % _smooth_note(win, rec.fps),
                      fontsize=7.5)
    ax_kym.set_xlabel("time (s)", fontsize=9)
    ax_kym.tick_params(labelsize=8)
    dyn["kym_cursor"] = ax_kym.axvline(float(times[0]), color="#111111",
                                       lw=1.2, animated=True)

    # -- flagged frames, marked along the time axis -------------------------
    # 17% of frames were flagged on the recording this was built against.
    # Averaged into a trace that is invisible; drawn here it is not.
    flagged_times = _flagged_times(rec, times)
    if len(flagged_times):
        for ax in (ax_bend, ax_vel, ax_kym):
            ax.plot(flagged_times,
                    np.full(len(flagged_times), ax.get_ylim()[1]),
                    "|", ms=4, color="#C1440E", alpha=0.5, zorder=5)

    note = ("%d/%d frames flagged needs_help (%.1f%%)"
            % (quality.get("frames_flagged", 0), rec.n_frames,
               100.0 * quality.get("frames_flagged", 0) / max(rec.n_frames, 1)))
    note += ("   |   curvature missing on %.1f%% of segment-rows"
             % (100.0 * quality["curvature_missing_fraction"]))
    if len(flagged_times):
        note += "   |   flagged frames ticked in orange above each trace"
    fig.text(left, 0.014, note, fontsize=7.5, color="#5E6E76")
    fig.text(right, 0.014, "%s %s - renders, measures nothing"
             % (TOOL_NAME, TOOL_VERSION), fontsize=7.5, color="#9AA6AC",
             ha="right")

    ctx = {"times": times, "quality": quality, "smooth_frames": win,
           "axes": (ax_img, ax_bend, ax_vel, ax_kym)}
    return fig, dyn, ctx


def _smooth_note(win, fps):
    return "" if win < 2 else "\nsmoothed %d fr (%.1f s)" % (win, win / fps)


def _trace(ax, times, series, win, fps, colour):
    """Raw in grey under the smoothed line, so smoothing never makes the data
    look cleaner than it was."""
    if win >= 2:
        ax.plot(times, series, lw=0.6, color="#C6CED2", zorder=1)
        ax.plot(times, mc.moving_average(series, win), lw=1.3, color=colour,
                zorder=2)
    else:
        ax.plot(times, series, lw=1.0, color=colour)


def _flagged_times(rec, times):
    if "needs_help" not in rec.df:
        return np.array([])
    flag = pd.to_numeric(rec.df["needs_help"], errors="coerce").fillna(0) > 0
    frames = sorted(rec.df.loc[flag, "frame"].astype(int).unique())
    index = {f: i for i, f in enumerate(rec.frames)}
    return np.array([times[index[f]] for f in frames if f in index], dtype=float)


def _update(rec, fig, dyn, ctx, i):
    frame_no = rec.frames[i]
    if "image" in dyn and rec.images:
        frame = rec.images.get(i)
        if frame is not None:
            dyn["image"].set_data(frame)

    geo = rec.frame_geometry(frame_no)
    if geo is None:
        for key in ("midline", "head", "tail"):
            dyn[key].set_data([], [])
    else:
        mid = geo["mid"]
        good = np.isfinite(mid).all(axis=1)
        dyn["midline"].set_data(mid[good, 0], mid[good, 1])
        for key in ("head", "tail"):
            pt = geo.get(key)
            if pt is None or not all(np.isfinite(pt)):
                dyn[key].set_data([], [])
            else:
                dyn[key].set_data([pt[0]], [pt[1]])

    flagged = False
    if "needs_help" in rec.df:
        block = rec.df.loc[rec.df["frame"] == frame_no, "needs_help"]
        flagged = bool(pd.to_numeric(block, errors="coerce").fillna(0).gt(0).any())
    dyn["flag"].set_text("frame %d / %d%s"
                         % (frame_no, rec.n_frames,
                            "    NEEDS HELP" if flagged else ""))
    dyn["midline"].set_color("#FFB000" if flagged else "#00C8FF")

    t = float(ctx["times"][i])
    for key in ("bend_cursor", "vel_cursor", "kym_cursor"):
        dyn[key].set_xdata([t, t])


def _dynamic_artists(dyn):
    return [a for a in (dyn.get("image"), dyn.get("midline"), dyn.get("head"),
                        dyn.get("tail"), dyn.get("flag"),
                        dyn.get("bend_cursor"), dyn.get("vel_cursor"),
                        dyn.get("kym_cursor")) if a is not None]


class _KinematicsSource(mc.MovieSource):
    """Adapts one kinematics Recording to app/movie_core.py."""

    def __init__(self, rec, smooth_s=0.5):
        self.rec = rec
        self.base = rec.base
        self.n_frames = rec.n_frames
        self.fps = rec.fps
        self.smooth_s = smooth_s

    def build_figure(self, **_):
        return build_figure(self.rec, smooth_s=self.smooth_s)

    def update(self, fig, dyn, ctx, index):
        _update(self.rec, fig, dyn, ctx, index)

    def dynamic_artists(self, dyn):
        return _dynamic_artists(dyn)

    def frame_label(self, index):
        return "frame %d  (t=%.1fs)" % (self.rec.frames[index],
                                        index / max(self.fps, 1e-9))

    def provenance(self, ctx, options):
        rec = self.rec
        return {
            "source_csv": str(rec.csv_path),
            "image_stack": str(rec.image_path) if rec.image_path else None,
            "n_seg": rec.n_seg,
            "velocity_column": rec.velocity_column,
            "velocity_units": "um/s" if rec.um_per_px > 0 else "px/s",
            "um_per_px_declared": rec.um_per_px,
            "smoothing_seconds": float(self.smooth_s),
            "smoothing_frames": ctx["smooth_frames"],
            "quality": ctx["quality"],
        }


def render(rec, out_path, smooth_s=0.5, decimate=1, fps=None, progress=None):
    """Write the movie and its provenance JSON. Returns (path, provenance)."""
    return mc.render(_KinematicsSource(rec, smooth_s=smooth_s), out_path,
                     decimate=decimate, fps=fps, progress=progress,
                     tool_name=TOOL_NAME, tool_version=TOOL_VERSION)


def preview(rec, out_path, smooth_s=0.5, n=4):
    """Contact sheet: first frame, two spread through, and a flagged frame if
    there is one - the flagged case is the one worth eyeballing."""
    picks = [0, rec.n_frames // 3, 2 * rec.n_frames // 3]
    if "needs_help" in rec.df:
        flag = pd.to_numeric(rec.df["needs_help"], errors="coerce").fillna(0) > 0
        bad = sorted(rec.df.loc[flag, "frame"].astype(int).unique())
        if bad:
            index = {f: i for i, f in enumerate(rec.frames)}
            picks.append(index.get(bad[len(bad) // 2], 0))
    picks = sorted(set(p for p in picks if 0 <= p < rec.n_frames))[:n]
    return mc.preview(_KinematicsSource(rec, smooth_s=smooth_s), out_path,
                      picks=picks, n=n)


def suggested_decimation(rec, target_frames=900):
    """Long recordings need thinning: 6260 frames at 30 fps is a 3.5 minute
    movie and a 20 minute render. Returned rather than applied, and the factor
    is printed on the movie by the core's provenance."""
    return max(1, int(round(rec.n_frames / float(target_frames))))
