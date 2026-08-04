"""Synchronized results movie for one Population tracking run.

Four panels sharing one time cursor:

  1. the plate, with every tracked animal's spine and a fading trail
  2. per-animal speed over time, one line per animal in its own colour
  3. proposed locomotion modality as a bout timeline, one row per animal
  4. how many animals were actually tracked, frame by frame

Third adapter over app/movie_core.py, after RGBCaMP and kinematics, so the
render loop, video writer, preview and provenance are shared.

THIS MODULE MEASURES NOTHING. Every value comes from the run's own output
tables. There is one population-tracking computation path and this is not a
second one.

WHY A POPULATION MOVIE LOOKS DIFFERENT: with one animal the question is what it
did. With many the question is usually whether the TRACKING held - identities
swapped, tracks lost, animals merged when they touched. So the honesty columns
this run already writes (crossing_ambiguous, spine_valid, coverage_fraction,
manual_points, bout confidence) are not a footnote here, they are most of the
point. Colours are shared with the review workbench via process_ui.track_colour,
so an animal is the same colour in the movie as in the tool where it was
reviewed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT / "app"), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import movie_core as mc                       # noqa: E402
# Result tables are read through read_table: under pandas 3 a numeric column
# holding one stray non-numeric cell reads as StringDtype, and numpy then
# refuses np.isfinite on it. Imported AFTER the sys.path block above, which is
# what makes app/ importable at all.
from table_io import read_table               # noqa: E402

try:
    from process_ui import track_colour        # noqa: E402
except Exception:                              # pragma: no cover
    def track_colour(track_id):
        palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
                   "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]
        return palette[int(track_id) % len(palette)]

TOOL_NAME = "Population results movie"
TOOL_VERSION = "0.1.0"
MovieInputError = mc.MovieInputError

REQUIRED = {"frame", "time_s", "x", "y", "track_id"}

# A fragmented run can produce thousands of tracks - one real pilot here has
# 1981 for a plate that should hold a couple of dozen. One timeline row each
# would be a figure hundreds of inches tall, so the panel shows the longest
# and SAYS how many it left out rather than silently truncating.
MAX_BOUT_ROWS = 20


class Run:
    """One population-tracking results folder, plus the recording it came from."""

    def __init__(self, results_dir, image_path=None):
        self.results_dir = Path(results_dir)
        tracks_csv = self.results_dir / "detections_and_tracks.csv"
        if not tracks_csv.exists():
            raise MovieInputError(
                f"No detections_and_tracks.csv in {self.results_dir}.\n\n"
                f"Point this at a population-tracking RESULTS folder - the one "
                f"holding track_summary.csv and analysis_metadata.json - not at "
                f"the recording.")
        self.tracks = read_table(tracks_csv)
        self.base = self.results_dir.name

        missing = sorted(REQUIRED - set(self.tracks.columns))
        if missing:
            raise MovieInputError(
                "detections_and_tracks.csv is missing " + ", ".join(missing)
                + ".\n\nThis does not look like a population-tracking export, "
                "and rendering it would draw animals that were never tracked.")

        self.meta = {}
        meta_path = self.results_dir / "analysis_metadata.json"
        if meta_path.exists():
            try:
                self.meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
            except Exception:
                self.meta = {}

        self.frames = sorted(self.tracks["frame"].astype(int).unique())
        self.n_frames = len(self.frames)
        self.fps = float(self.meta.get("fps") or 1.0)
        self.um_per_px = float(self.meta.get("um_per_px") or 0.0)
        self.track_ids = sorted(self.tracks["track_id"].dropna().astype(int).unique())

        self.summary = self._read_optional("track_summary.csv")
        self.bouts = self._read_optional("modality_bouts_for_review.csv")

        self.image_path = Path(image_path) if image_path else None
        self.images = mc.FrameSource(self.image_path) if self.image_path else None
        if self.images and len(self.images) and len(self.images) < self.n_frames:
            n_images = len(self.images)
            self.images.close()
            self.images = None
            raise MovieInputError(
                f"The recording has {n_images} frames and the results describe "
                f"{self.n_frames}. These are not the same run, or one is "
                f"stale.\n\nRendering anyway would draw one recording's tracks "
                f"over another's pixels and look entirely normal.")

        # Index per frame once. Filtering a dataframe per frame dominates the
        # render on a long run with many animals.
        self._by_frame = {int(f): b for f, b in self.tracks.groupby("frame")}

    def _read_optional(self, name):
        path = self.results_dir / name
        if not path.exists():
            return None
        try:
            return read_table(path)
        except Exception:
            return None

    # -- series ------------------------------------------------------------
    def times(self):
        return (self.tracks.groupby("frame")["time_s"].first()
                .astype(float).to_numpy())

    def speed_by_track(self):
        """{track_id: array over frames}. NaN where that animal was absent, so
        a gap in tracking stays a gap rather than a flat line at zero."""
        col = "speed_um_s" if "speed_um_s" in self.tracks else None
        if col is None:
            return {}, "none"
        index = {f: i for i, f in enumerate(self.frames)}
        out = {}
        for tid, block in self.tracks.groupby("track_id"):
            series = np.full(self.n_frames, np.nan)
            for f, v in zip(block["frame"].astype(int),
                            pd.to_numeric(block[col], errors="coerce")):
                if f in index:
                    series[index[f]] = v
            out[int(tid)] = series
        units = "um/s" if self.um_per_px > 0 else "px/s"
        return out, units

    def tracked_count(self):
        counts = self.tracks.groupby("frame")["track_id"].nunique()
        return counts.reindex(self.frames).fillna(0).to_numpy(dtype=float)

    def quality_summary(self):
        out = {"n_frames": self.n_frames, "n_tracks": len(self.track_ids)}
        for col in ("crossing_ambiguous", "spine_valid"):
            if col in self.tracks:
                vals = pd.to_numeric(self.tracks[col], errors="coerce").fillna(0)
                if col == "spine_valid":
                    out["rows_without_valid_spine"] = int((vals <= 0).sum())
                else:
                    out["rows_crossing_ambiguous"] = int((vals > 0).sum())
        if self.summary is not None:
            for col, key in (("coverage_fraction", "median_coverage_fraction"),
                             ("manual_points", "manual_points_total")):
                if col in self.summary:
                    series = pd.to_numeric(self.summary[col], errors="coerce")
                    out[key] = (round(float(series.median()), 3)
                                if key.startswith("median")
                                else int(series.fillna(0).sum()))
        if self.bouts is not None and "confidence" in self.bouts:
            conf = pd.to_numeric(self.bouts["confidence"], errors="coerce")
            out["n_bouts"] = int(len(self.bouts))
            out["median_bout_confidence"] = round(float(conf.median()), 3)
        return out

    def frame_rows(self, frame_number):
        return self._by_frame.get(int(frame_number))

    @staticmethod
    def spine_of(row):
        """Per-animal spine, or None. Stored as JSON in the CSV."""
        xs, ys = row.get("spine_x_json"), row.get("spine_y_json")
        if not isinstance(xs, str) or not isinstance(ys, str):
            return None
        try:
            ax, ay = json.loads(xs), json.loads(ys)
        except Exception:
            return None
        if not ax or len(ax) != len(ay):
            return None
        return np.column_stack([np.asarray(ax, float), np.asarray(ay, float)])

    def close(self):
        if self.images is not None:
            self.images.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def load(results_dir, image_path=None):
    return Run(results_dir, image_path=image_path)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
MODALITY_COLOURS = {
    "forward": "#2C7BB6", "backward": "#D7191C", "turn": "#FDAE61",
    "omega": "#E66101", "pause": "#B8B8B8", "quiescent": "#B8B8B8",
    "uncertain": "#DDDDDD",
}


def build_figure(rec, smooth_s=0.5, trail_s=2.0, width_in=13.0, dpi=110):
    """Static layers drawn once; returns the artists that change per frame."""
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    times = rec.times()
    speeds, speed_units = rec.speed_by_track()
    counts = rec.tracked_count()
    quality = rec.quality_summary()
    win = mc.smooth_window_frames(smooth_s, rec.fps)

    left, right = 0.075, 0.975
    usable = width_in * (right - left)
    w = float(rec.meta.get("source_frame_width") or 0)
    h = float(rec.meta.get("source_frame_height") or 0)
    if w <= 0 or h <= 0:
        # No frame dimensions recorded. Assume 4:3 rather than 1:1, which would
        # otherwise claim a square panel of empty white on a run with no images.
        w, h = 4.0, 3.0
    plate_row = min(usable * (h / w), 5.0)
    shown_ids = _bout_rows_shown(rec)
    rows = [plate_row, 1.2, max(0.9, 0.26 * len(shown_ids) + 0.7), 0.9]
    height_in = sum(rows) + 1.6

    fig = plt.figure(figsize=(width_in, height_in), dpi=dpi)
    fig.patch.set_facecolor("white")
    gs = GridSpec(4, 1, figure=fig, height_ratios=rows, hspace=0.45,
                  left=left, right=right,
                  top=1.0 - 0.55 / height_in, bottom=0.62 / height_in)
    ax_plate = fig.add_subplot(gs[0])
    ax_speed = fig.add_subplot(gs[1])
    ax_bout = fig.add_subplot(gs[2])
    ax_count = fig.add_subplot(gs[3])

    dyn = {"spines": {}, "trails": {}, "dots": {}}

    # -- panel 1: the plate -------------------------------------------------
    ax_plate.axis("off")
    if rec.images and len(rec.images):
        lo, hi = rec.images.limits(pct=(1.0, 99.5))
        dyn["image"] = ax_plate.imshow(rec.images.get(0), cmap="gray",
                                       vmin=lo, vmax=hi, animated=True)
    else:
        ax_plate.set_xlim(0, w)
        ax_plate.set_ylim(h, 0)
        ax_plate.set_facecolor("#F4F4F2")
        ax_plate.text(0.5, 0.02, "no recording supplied - tracks are drawn on "
                                 "the plate outline only",
                      transform=ax_plate.transAxes, ha="center", fontsize=8,
                      color="#a00000")
    for tid in rec.track_ids:
        colour = track_colour(tid)
        dyn["trails"][tid], = ax_plate.plot([], [], lw=1.0, color=colour,
                                            alpha=0.55, animated=True)
        dyn["spines"][tid], = ax_plate.plot([], [], lw=1.8, color=colour,
                                            animated=True)
        dyn["dots"][tid], = ax_plate.plot([], [], "o", ms=4, color=colour,
                                          animated=True)
    dyn["plate_note"] = ax_plate.text(
        0.01, 0.99, "", transform=ax_plate.transAxes, va="top", fontsize=9,
        color="#C1440E", animated=True)

    # -- panel 2: speed per animal ------------------------------------------
    for tid, series in speeds.items():
        ax_speed.plot(times, mc.moving_average(series, win) if win >= 2 else series,
                      lw=1.0, color=track_colour(tid), alpha=0.9)
    note = "" if win < 2 else "\nsmoothed %d fr (%.1f s)" % (win, win / rec.fps)
    scale_note = ""
    if rec.um_per_px <= 0:
        scale_note = " - scale NOT calibrated"
    elif abs(rec.um_per_px - 1.0) < 1e-9:
        scale_note = "\n(declared 1.000 um/px - often an unset default)"
    ax_speed.set_ylabel("speed\n(%s%s)%s" % (speed_units, scale_note, note),
                        fontsize=7.5)
    # Robust limits. Tracking failures produce speeds orders of magnitude above
    # anything an animal does - one real run peaks near 100,000 um/s - and an
    # autoscaled axis then flattens every real trace onto the baseline. Clip the
    # VIEW, never the data, and say that the view is clipped.
    pooled = np.concatenate([v[np.isfinite(v)] for v in speeds.values()])         if speeds else np.array([0.0])
    if pooled.size:
        hi = float(np.percentile(np.abs(pooled), 99.0))
        peak = float(np.nanmax(np.abs(pooled)))
        if hi > 0 and peak > hi * 1.5:
            ax_speed.set_ylim(-0.05 * hi, hi * 1.15)
            ax_speed.text(0.995, 0.94, "view clipped at the 99th percentile "
                          "(peak %.0f)" % peak, transform=ax_speed.transAxes,
                          ha="right", va="top", fontsize=6.5, color="#C1440E")
    ax_speed.set_xlim(float(times[0]), float(times[-1]))
    ax_speed.tick_params(labelsize=8)
    dyn["speed_cursor"] = ax_speed.axvline(float(times[0]), color="#111111",
                                           lw=1.2, animated=True)

    # -- panel 3: modality bouts, one row per animal ------------------------
    _draw_bouts(ax_bout, rec, times)
    dyn["bout_cursor"] = ax_bout.axvline(float(times[0]), color="#111111",
                                         lw=1.2, animated=True)

    # -- panel 4: how many animals were actually tracked --------------------
    ax_count.plot(times, counts, lw=1.0, color="#3A4A52")
    ax_count.set_ylim(0, max(1.0, float(np.nanmax(counts)) * 1.25))
    ax_count.set_ylabel("animals\ntracked", fontsize=7.5)
    ax_count.set_xlabel("time (s)", fontsize=9)
    ax_count.set_xlim(float(times[0]), float(times[-1]))
    ax_count.tick_params(labelsize=8)
    if "crossing_ambiguous" in rec.tracks:
        amb = pd.to_numeric(rec.tracks["crossing_ambiguous"],
                            errors="coerce").fillna(0) > 0
        bad = sorted(rec.tracks.loc[amb, "frame"].astype(int).unique())
        index = {f: i for i, f in enumerate(rec.frames)}
        tt = [times[index[f]] for f in bad if f in index]
        if tt:
            ax_count.plot(tt, np.full(len(tt), ax_count.get_ylim()[1] * 0.95),
                          "|", ms=5, color="#C1440E", alpha=0.7)
    dyn["count_cursor"] = ax_count.axvline(float(times[0]), color="#111111",
                                           lw=1.2, animated=True)

    # -- honesty footer -----------------------------------------------------
    bits = ["%d animals" % quality["n_tracks"]]
    if quality.get("rows_without_valid_spine"):
        bits.append("%d/%d rows without a valid spine"
                    % (quality["rows_without_valid_spine"], len(rec.tracks)))
    if quality.get("rows_crossing_ambiguous"):
        bits.append("%d rows flagged crossing_ambiguous (ticked above)"
                    % quality["rows_crossing_ambiguous"])
    if quality.get("manual_points_total"):
        bits.append("%d manually placed points (identity only, excluded from "
                    "speed)" % quality["manual_points_total"])
    if quality.get("median_bout_confidence") is not None:
        bits.append("median bout confidence %.2f"
                    % quality["median_bout_confidence"])
    fig.text(left, 0.014, "   |   ".join(bits), fontsize=7.5, color="#5E6E76")
    fig.text(right, 0.014, "%s %s - renders, measures nothing"
             % (TOOL_NAME, TOOL_VERSION), fontsize=7.5, color="#9AA6AC",
             ha="right")

    ctx = {"times": times, "quality": quality, "smooth_frames": win,
           "speed_units": speed_units,
           "trail_frames": max(1, int(round(trail_s * rec.fps))),
           "axes": (ax_plate, ax_speed, ax_bout, ax_count)}
    return fig, dyn, ctx


def _bout_rows_shown(rec):
    """The tracks the modality panel will show: the longest-lived, capped."""
    ids = list(rec.track_ids)
    if len(ids) <= MAX_BOUT_ROWS:
        return ids
    counts = rec.tracks.groupby("track_id")["frame"].nunique()
    ranked = counts.sort_values(ascending=False).index.astype(int).tolist()
    return sorted(ranked[:MAX_BOUT_ROWS])


def _draw_bouts(ax, rec, times):
    """One row per animal, coloured by proposed modality, alpha by confidence.

    Modality is a PROPOSAL awaiting review, so a low-confidence call is drawn
    faint rather than as firmly as a confident one - and 'uncertain' has its
    own near-white colour so it cannot be mistaken for a decision.
    """
    ids = _bout_rows_shown(rec)
    omitted = len(rec.track_ids) - len(ids)
    ax.set_yticks(range(len(ids)))
    ax.set_yticklabels(["%d" % t for t in ids], fontsize=7)
    ax.set_ylabel("modality\nby animal", fontsize=7.5)
    ax.set_ylim(-0.6, len(ids) - 0.4)
    ax.set_xlim(float(times[0]), float(times[-1]))
    ax.tick_params(labelsize=8)
    ax.invert_yaxis()
    if omitted:
        ax.set_ylabel("modality\nby animal\n(%d longest of %d)"
                      % (len(ids), len(rec.track_ids)), fontsize=7.5)
        ax.text(0.005, 0.02, "%d shorter tracks not shown - a run this "
                "fragmented usually means tracking, not behaviour"
                % omitted, transform=ax.transAxes, fontsize=6.5,
                color="#C1440E")

    if rec.bouts is None or not len(rec.bouts):
        ax.text(0.5, 0.5, "no modality bouts in this run",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=9, color="#5E6E76")
        return

    row_of = {t: i for i, t in enumerate(ids)}
    seen = set()
    for _, b in rec.bouts.iterrows():
        tid = int(b.get("track_id", -1))
        if tid not in row_of:
            continue
        t0 = float(b.get("start_time_s", np.nan))
        t1 = float(b.get("end_time_s", np.nan))
        if not np.isfinite(t0) or not np.isfinite(t1):
            continue
        label = str(b.get("proposed_modality", "uncertain")).lower()
        conf = float(pd.to_numeric(b.get("confidence", np.nan),
                                   errors="coerce") or 0.0)
        colour = MODALITY_COLOURS.get(label, "#999999")
        ax.barh(row_of[tid], t1 - t0, left=t0, height=0.6,
                color=colour, edgecolor="none",
                alpha=0.25 + 0.65 * max(0.0, min(1.0, conf)))
        seen.add(label)
    if seen:
        from matplotlib.patches import Patch
        ax.legend(handles=[Patch(facecolor=MODALITY_COLOURS.get(s, "#999999"),
                                 label=s) for s in sorted(seen)],
                  fontsize=6.5, ncol=min(len(seen), 6), loc="upper right",
                  frameon=False)


def _update(rec, fig, dyn, ctx, i):
    frame_no = rec.frames[i]
    if "image" in dyn and rec.images:
        frame = rec.images.get(i)
        if frame is not None:
            dyn["image"].set_data(frame)

    rows = rec.frame_rows(frame_no)
    present = set()
    ambiguous = 0
    if rows is not None:
        trail_from = max(0, i - ctx["trail_frames"])
        window = set(rec.frames[trail_from:i + 1])
        for _, row in rows.iterrows():
            tid = int(row["track_id"])
            present.add(tid)
            if tid not in dyn["dots"]:
                continue
            dyn["dots"][tid].set_data([float(row["x"])], [float(row["y"])])
            spine = rec.spine_of(row)
            if spine is None:
                dyn["spines"][tid].set_data([], [])
            else:
                dyn["spines"][tid].set_data(spine[:, 0], spine[:, 1])
            past = rec.tracks[(rec.tracks["track_id"] == tid)
                              & (rec.tracks["frame"].isin(window))]
            dyn["trails"][tid].set_data(past["x"].to_numpy(float),
                                        past["y"].to_numpy(float))
            if float(pd.to_numeric(row.get("crossing_ambiguous", 0),
                                   errors="coerce") or 0) > 0:
                ambiguous += 1

    # An animal absent this frame draws nothing at all, rather than lingering
    # at its last position - a stale dot reads as a tracked animal.
    for tid in rec.track_ids:
        if tid not in present:
            for key in ("spines", "trails", "dots"):
                dyn[key][tid].set_data([], [])

    note = "frame %d / %d    %d of %d animals" % (
        frame_no, rec.n_frames, len(present), len(rec.track_ids))
    if ambiguous:
        note += "    %d CROSSING AMBIGUOUS" % ambiguous
    dyn["plate_note"].set_text(note)

    t = float(ctx["times"][i])
    for key in ("speed_cursor", "bout_cursor", "count_cursor"):
        dyn[key].set_xdata([t, t])


def _dynamic_artists(dyn):
    out = [dyn.get("image"), dyn.get("plate_note"), dyn.get("speed_cursor"),
           dyn.get("bout_cursor"), dyn.get("count_cursor")]
    for key in ("trails", "spines", "dots"):
        out += list(dyn.get(key, {}).values())
    return [a for a in out if a is not None]


class _PopulationSource(mc.MovieSource):
    """Adapts one population-tracking Run to app/movie_core.py."""

    def __init__(self, rec, smooth_s=0.5, trail_s=2.0):
        self.rec = rec
        self.base = rec.base
        self.n_frames = rec.n_frames
        self.fps = rec.fps
        self.smooth_s = smooth_s
        self.trail_s = trail_s

    def build_figure(self, **_):
        return build_figure(self.rec, smooth_s=self.smooth_s,
                            trail_s=self.trail_s)

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
            "results_dir": str(rec.results_dir),
            "image_source": str(rec.image_path) if rec.image_path else None,
            "n_tracks": len(rec.track_ids),
            "speed_units": ctx["speed_units"],
            "um_per_px_declared": rec.um_per_px,
            "smoothing_seconds": float(self.smooth_s),
            "smoothing_frames": ctx["smooth_frames"],
            "trail_seconds": float(self.trail_s),
            "quality": ctx["quality"],
        }


def render(rec, out_path, smooth_s=0.5, trail_s=2.0, decimate=1, fps=None,
           progress=None):
    """Write the movie and its provenance JSON. Returns (path, provenance)."""
    return mc.render(_PopulationSource(rec, smooth_s=smooth_s, trail_s=trail_s),
                     out_path, decimate=decimate, fps=fps, progress=progress,
                     tool_name=TOOL_NAME, tool_version=TOOL_VERSION)


def preview(rec, out_path, smooth_s=0.5, trail_s=2.0, n=4):
    """Contact sheet, preferring a frame where tracking was ambiguous - that is
    the one worth eyeballing."""
    picks = [0, rec.n_frames // 3, 2 * rec.n_frames // 3]
    if "crossing_ambiguous" in rec.tracks:
        amb = pd.to_numeric(rec.tracks["crossing_ambiguous"],
                            errors="coerce").fillna(0) > 0
        bad = sorted(rec.tracks.loc[amb, "frame"].astype(int).unique())
        if bad:
            index = {f: i for i, f in enumerate(rec.frames)}
            picks.append(index.get(bad[len(bad) // 2], 0))
    picks = sorted(set(p for p in picks if 0 <= p < rec.n_frames))[:n]
    return mc.preview(_PopulationSource(rec, smooth_s=smooth_s,
                                        trail_s=trail_s),
                      out_path, picks=picks, n=n)


def suggested_decimation(rec, target_frames=900):
    return max(1, int(round(rec.n_frames / float(target_frames))))
