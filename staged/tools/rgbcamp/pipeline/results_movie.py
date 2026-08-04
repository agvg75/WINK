"""Synchronized results movie for one RGBCaMP recording.

Four stacked panels sharing one time cursor:

  1. the worm frame with its midline and the measurement bands overlaid
  2. a muscle diagram, each myocyte split R/G/B by that channel's brightness
  3. linear velocity over time
  4. a body-curvature kymograph

See docs/specs/rgbcamp_results_movie_spec.md.

THIS MODULE MEASURES NOTHING. Every number on screen is read from the exported
recording CSV and the geometry sidecar the Fiji extractor writes. If a value is
not in those files it does not appear. There is one analysis path in this
toolset and this is not it - the same rule results_browser.py follows.

Because nothing is measured, every display choice is a render-time parameter and
re-rendering is cheap and safe. Parse once, render many.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for p in (str(ROOT / "app"), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import myocyte_schematic as msch          # noqa: E402
import movie_core as mc                   # noqa: E402

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


TOOL_NAME = "RGBCaMP results movie"
TOOL_VERSION = "0.1.0"
MYOCYTE_SEGMENTS = 24
CHANNELS = ("red", "green", "blue")


MovieInputError = mc.MovieInputError


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
class Recording:
    """CSV + geometry sidecar + image sequence for one recording."""

    def __init__(self, csv_path, image_dir=None):
        self.csv_path = Path(csv_path)
        if not self.csv_path.exists():
            raise MovieInputError(f"No recording CSV at {self.csv_path}.")
        self.df = read_table(self.csv_path, encoding="utf-8-sig")
        self.base = self.csv_path.with_suffix("").name

        self.geometry_path = self.csv_path.with_name(self.base + "_geometry.json")
        self.geometry = self._load_geometry()

        self.n_seg = int(self.geometry["n_seg"])
        self._check_segment_count()

        self.frames = sorted(self.df["frame"].astype(int).unique())
        self.n_frames = len(self.frames)
        self._check_frame_counts()

        self.fps = float(self.df["fps"].iloc[0]) if "fps" in self.df else 1.0
        self.um_per_px = float(self.df["um_per_px"].iloc[0]) if "um_per_px" in self.df else 0.0
        self.src8bit = bool(int(self.df["src8bit"].iloc[0])) if "src8bit" in self.df else False

        # The two bands, named as the CSV names them. This recording may have
        # dorsal/ventral (a vulva seed was given) or L/R (it was not). Report
        # what the tracker recorded; never promote L/R into an anatomical claim.
        self.band_names = sorted(self.df["hemisegment"].astype(str).unique())
        if len(self.band_names) != 2:
            raise MovieInputError(
                f"Expected two hemisegment bands, found {self.band_names}. "
                f"The muscle diagram draws two opposing quadrants and cannot "
                f"represent {len(self.band_names)}.")

        self.image_dir = Path(image_dir) if image_dir else None
        self.image_files = self._find_images()

    # -- refusals ----------------------------------------------------------
    def _load_geometry(self):
        if not self.geometry_path.exists():
            raise MovieInputError(
                f"No geometry sidecar beside this CSV ({self.geometry_path.name}).\n\n"
                f"Panel 1 draws the midline and the measurement bands, and that "
                f"geometry exists only in the sidecar - the extractor builds the "
                f"bands for its on-screen overlay and they are gone when the "
                f"window closes.\n\n"
                f"Re-run this recording through the RGBCaMP extractor with "
                f"'Export geometry sidecar' ticked. Note that re-running does "
                f"not reproduce manual corrections made during the original "
                f"review.")
        return json.loads(self.geometry_path.read_text(encoding="utf-8"))

    def _check_segment_count(self):
        if self.n_seg != MYOCYTE_SEGMENTS:
            raise MovieInputError(
                f"This recording was measured with {self.n_seg} segments per side, "
                f"not {MYOCYTE_SEGMENTS}.\n\n"
                f"At {MYOCYTE_SEGMENTS} each segment is one projected myocyte, which is what "
                f"makes the muscle diagram a diagram of muscles. At 12 each "
                f"segment lumps several neighbouring myocytes, so the panel "
                f"would draw cells that do not exist and give one calcium value "
                f"to several muscles at once.\n\n"
                f"Re-extract at {MYOCYTE_SEGMENTS} segments per side to render this recording.")

    def _check_frame_counts(self):
        geo_n = int(self.geometry["n_frames"])
        if geo_n != self.n_frames:
            raise MovieInputError(
                f"The sidecar describes {geo_n} frames and the CSV describes "
                f"{self.n_frames}. These are not the same recording, or one of "
                f"them is stale.\n\n"
                f"Rendering anyway would draw one recording's geometry over "
                f"another's numbers and look entirely normal.")

    # The extractor's own mapping, from WormRGBCaMPMap_v1.java:692 -
    # "ch00 blue, ch01 green, ch02 red, ch03 DIC. Track on DIC, measure the
    # three fluorescent channels." Never inferred from folder order.
    CHANNEL_DIRS = (("blue", "ch00"), ("green", "ch01"), ("red", "ch02"))
    DIC_DIR = "ch03"
    IMAGE_EXTS = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}

    def _list_images(self, folder):
        if folder is None or not Path(folder).exists():
            return []
        return sorted(p for p in Path(folder).iterdir()
                      if p.suffix.lower() in self.IMAGE_EXTS)

    def _find_images(self):
        """The DIC sequence, plus the three fluorescent channels if they sit
        beside it as the extractor expects.

        Seeing the raw channel next to the diagram is the point: it is what
        lets a viewer check that a bright cell in the schematic corresponds to
        something actually present in the recording.
        """
        self.channel_files = {}
        if self.image_dir is None:
            return []
        files = self._list_images(self.image_dir)
        parent = self.image_dir.parent
        for name, sub in self.CHANNEL_DIRS:
            found = self._list_images(parent / sub)
            if found:
                self.channel_files[name] = found
        return files

    # -- derived, all read straight from the CSV ---------------------------
    def channel_values(self, normalisation="percentile", pct=(1.0, 99.0)):
        """(n_frames, n_seg, 2, 3) in 0..1, background-subtracted.

        Returns the array plus the numeric range used, which must be printed on
        the panel: a viewer must never have to guess whether a brighter cell
        means more calcium or a different normalisation.
        """
        out = np.full((self.n_frames, self.n_seg, 2, 3), np.nan)
        frame_index = {f: i for i, f in enumerate(self.frames)}
        band_index = {b: i for i, b in enumerate(self.band_names)}
        for ch_i, ch in enumerate(CHANNELS):
            col, bg = f"{ch}_mean", f"bg_{ch}"
            if col not in self.df:
                continue
            vals = self.df[col].astype(float)
            if bg in self.df:
                vals = vals - self.df[bg].astype(float)
            for (fr, seg, band), v in zip(
                    zip(self.df["frame"].astype(int),
                        self.df["segment"].astype(int),
                        self.df["hemisegment"].astype(str)), vals):
                fi = frame_index.get(fr)
                bi = band_index.get(band)
                if fi is None or bi is None or seg >= self.n_seg:
                    continue
                out[fi, seg, bi, ch_i] = v

        ranges = {}
        scaled = np.full_like(out, np.nan)
        for ch_i, ch in enumerate(CHANNELS):
            data = out[..., ch_i]
            finite = data[np.isfinite(data)]
            if finite.size == 0:
                ranges[ch] = (0.0, 1.0)
                continue
            if normalisation == "absolute":
                lo, hi = 0.0, 255.0
            else:
                lo, hi = np.percentile(finite, pct[0]), np.percentile(finite, pct[1])
            if hi <= lo:
                hi = lo + 1.0
            ranges[ch] = (float(lo), float(hi))
            scaled[..., ch_i] = np.clip((data - lo) / (hi - lo), 0, 1)
        return scaled, ranges

    def velocity(self):
        """(times, px_per_s, um_per_s or None). One value per frame."""
        g = self.df.groupby("frame")
        t = g["time_s"].first().astype(float).to_numpy()
        v = g["axial_vel_px_s"].mean().astype(float).to_numpy()
        um = v * self.um_per_px if self.um_per_px > 0 else None
        return t, v, um

    def curvature_kymograph(self):
        """(n_seg, n_frames) of seg_curv_deg, head at row 0. NaN stays NaN so a
        gap is drawn as a gap rather than interpolated across."""
        piv = self.df.pivot_table(index="segment", columns="frame",
                                  values="seg_curv_deg", aggfunc="mean")
        piv = piv.reindex(index=range(self.n_seg), columns=self.frames)
        return piv.to_numpy(dtype=float)

    def provenance_summary(self):
        """What the geometry actually was, per the CSV's own honesty columns."""
        out = {}
        if "body_provenance" in self.df:
            counts = self.df["body_provenance"].value_counts()
            total = int(counts.sum())
            out["provenance_counts"] = {k: int(v) for k, v in counts.items()}
            out["provenance_fraction"] = {k: round(v / total, 4)
                                          for k, v in counts.items()}
        for flag in ("coil_flag", "low_evidence", "skip"):
            if flag in self.df:
                out[flag] = int(pd.to_numeric(self.df[flag],
                                              errors="coerce").fillna(0).sum())
        found_frames = sum(1 for fr in self.geometry["frames"] if "bands" in fr)
        out["frames_with_geometry"] = found_frames
        out["frames_total"] = self.n_frames
        return out

    def frame_geometry(self, frame_number):
        """midline, outline, bands for a 1-based frame, or None."""
        for fr in self.geometry["frames"]:
            if int(fr["frame"]) == int(frame_number):
                return fr if "bands" in fr else None
        return None


def load(csv_path, image_dir=None):
    return Recording(csv_path, image_dir=image_dir)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
# Generic display arithmetic lives in app/movie_core.py so every results
# movie shares one implementation. Re-exported here under the names this
# module already used.
_read_frame = mc.read_frame
smooth_window_frames = mc.smooth_window_frames
moving_average = mc.moving_average

# The channel TIFFs are RGB with the signal in the plane matching the
# channel: ch00 carries blue in B, ch01 green in G, ch02 red in R, and the
# other two planes are identically zero. Reading a fixed plane silently
# returns an all-zero image for two channels out of three, which looks
# exactly like a recording with no signal in them.
CHANNEL_PLANE = {"blue": 2, "green": 1, "red": 0}


def channel_plane(frame, name):
    frame = np.asarray(frame)
    if frame.ndim == 2:
        return frame
    return frame[..., CHANNEL_PLANE.get(name, 0)]


def _channel_limits(files, name, n_sample=12, pct=(50.0, 100.0)):
    return mc.sampled_limits(files, plane=CHANNEL_PLANE.get(name, 0),
                             n_sample=n_sample, pct=pct)


def build_figure(rec, normalisation="percentile", smooth_s=0.6,
                 width_in=15.0, dpi=110):
    """Static layers drawn once; returns the artists that change per frame.

    The split is the point: axes, the diagram outline, the whole velocity
    trace, the kymograph image and every caption are drawn once and captured as
    a background. Per frame only the worm image, the overlay geometry, the cell
    fills, the bend text and two cursors are redrawn.
    """
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec
    from matplotlib.patches import Polygon

    values, ranges = rec.channel_values(normalisation=normalisation)
    times, vel_px, vel_um = rec.velocity()
    kymo = rec.curvature_kymograph()
    prov = rec.provenance_summary()

    # Row heights are derived from the CONTENT's aspect, not guessed, so
    # nothing letterboxes: square frames get a row as tall as they are wide,
    # and the schematic gets a row matching its own 4.2:1 worm. Guessing these
    # is what left white gutters either side of everything.
    panels_n = 1 + sum(1 for n, _ in rec.CHANNEL_DIRS if n in rec.channel_files)
    left, right = 0.05, 0.99
    usable_w = width_in * (right - left)
    # Capped: with only the DIC panel present, a full-width square row would
    # make the figure taller than it is wide and produce an absurd movie.
    frame_row = min(usable_w / max(1, panels_n), 4.0)   # square frames
    diagram_row = usable_w / 4.2                     # the schematic's aspect
    rows = [frame_row, diagram_row, 1.55, 2.0]
    height_in = sum(rows) + 1.5                      # titles, captions, margins

    fig = plt.figure(figsize=(width_in, height_in), dpi=dpi)
    fig.patch.set_facecolor("white")
    # Top row is the DIC frame with its overlay, then each fluorescent channel
    # raw beside it. That row is what lets a viewer check that a bright cell in
    # the diagram below corresponds to signal actually present in the
    # recording, rather than taking the schematic on trust.
    panels = ["DIC"] + [n for n, _ in rec.CHANNEL_DIRS if n in rec.channel_files]
    n_panels = max(1, len(panels))
    gs = GridSpec(4, n_panels, figure=fig, height_ratios=rows,
                  hspace=0.34, wspace=0.02,
                  left=left, right=right,
                  top=1.0 - 0.55 / height_in, bottom=0.62 / height_in)

    image_axes = [fig.add_subplot(gs[0, i]) for i in range(n_panels)]
    ax_img = image_axes[0]
    ax_dia = fig.add_subplot(gs[1, :])
    ax_vel = fig.add_subplot(gs[2, :])
    ax_kym = fig.add_subplot(gs[3, :])

    dyn = {}

    # -- top row: DIC with overlay, then each channel raw -------------------
    from matplotlib.colors import LinearSegmentedColormap
    # Black -> the channel's own hue, so a frame reads as fluorescence rather
    # than a wash of colour. A matplotlib "Blues_r" puts the BACKGROUND in
    # saturated blue and the signal in white, which inverts the thing being
    # looked at.
    CH_HUE = {"blue": (0.25, 0.45, 1.0), "green": (0.15, 1.0, 0.35),
              "red": (1.0, 0.25, 0.2)}
    dyn["channels_img"] = {}
    for ax, name in zip(image_axes, panels):
        ax.axis("off")
        ax.set_title(name if name == "DIC" else f"{name} channel (raw)",
                     fontsize=9, loc="left", color="#22303A")
    if rec.image_files:
        first = _read_frame(rec.image_files[0])
        dyn["image"] = ax_img.imshow(
            first, cmap=None if first.ndim == 3 else "gray", animated=True)
    else:
        ax_img.text(0.5, 0.5,
                    "no image sequence supplied - the panels below are unaffected",
                    ha="center", va="center", fontsize=9, color="#a00000")
    for ax, name in zip(image_axes[1:], panels[1:]):
        files = rec.channel_files[name]
        frame0 = channel_plane(_read_frame(files[0]), name)
        hue = CH_HUE.get(name, (1.0, 1.0, 1.0))
        cmap = LinearSegmentedColormap.from_list(
            f"wink_{name}", [(0, 0, 0), hue, (1, 1, 1)])
        # Fixed limits computed ACROSS the recording, not autoscaled off the
        # first frame: a channel whose opening frame happens to be flat would
        # otherwise stay flat for the whole movie, which is exactly what a weak
        # blue channel did. Percentiles so one saturated speck cannot flatten
        # everything else.
        lo, hi = _channel_limits(files, name)
        dyn["channels_img"][name] = ax.imshow(
            frame0, cmap=cmap, vmin=lo, vmax=hi, animated=True)
        ax.set_title("%s channel (raw)   shown %.0f-%.0f" % (name, lo, hi),
                     fontsize=8, loc="left", color="#22303A")
        # The animal's outline in white on every channel, so a dim channel
        # still shows WHERE the worm is rather than looking empty. No signal
        # and no animal are different findings and must not look alike.
        outline, = ax.plot([], [], lw=0.9, color="white", alpha=0.9,
                           animated=True)
        dyn.setdefault("channel_outlines", {})[name] = outline
    line, = ax_img.plot([], [], lw=1.4, color="#00C8FF", animated=True)
    dyn["midline"] = line
    dyn["bands"] = []
    for _ in range(rec.n_seg * 2):
        poly = Polygon(np.zeros((4, 2)), closed=True, facecolor="none",
                       edgecolor="#FFB000", lw=0.6, animated=True)
        ax_img.add_patch(poly)
        dyn["bands"].append(poly)

    # -- panel 2: muscle diagram -------------------------------------------
    handles = msch.draw(ax_dia, n_seg=rec.n_seg, values=None, numbered=True)
    dyn["cells"] = handles["channels"]
    for patch in dyn["cells"].values():
        patch.set_animated(True)
    dyn["bend"] = ax_dia.text(0.5, -0.16, "", transform=ax_dia.transAxes,
                              ha="center", fontsize=8, color="#3E4F58",
                              animated=True)
    rng_txt = "  ".join("%s %.0f-%.0f" % (c, lo, hi)
                        for c, (lo, hi) in ranges.items())
    # Two short lines rather than one long one: at this figure width a single
    # line ran off the right edge and truncated the 8-bit caption mid-word,
    # which is the one caption that must never be half-read.
    ax_dia.set_title(
        "bands: %s (upper) / %s (lower)   |   %s scaling, background-subtracted"
        "\nchannel range   %s"
        % (rec.band_names[0], rec.band_names[1], normalisation, rng_txt),
        fontsize=8, loc="left", color="#3E4F58", linespacing=1.6)

    # -- panel 3: velocity --------------------------------------------------
    # Smoothing is a DISPLAY choice, so the raw trace stays visible underneath
    # it. A smoothed line alone would look like a cleaner measurement than the
    # one that was taken, which is the one thing this module must not do.
    win = smooth_window_frames(smooth_s, rec.fps)
    series = vel_um if vel_um is not None else vel_px
    units = ("um/s, declared scale" if vel_um is not None
             else "px/s - scale NOT calibrated")
    if win >= 2:
        ax_vel.plot(times, series, lw=0.7, color="#B8C2C7", zorder=1)
        ax_vel.plot(times, moving_average(series, win), lw=1.4,
                    color="#3A4A52", zorder=2)
        units += f"\nsmoothed {win} frames ({win / rec.fps:.1f} s), raw in grey"
    else:
        ax_vel.plot(times, series, lw=1.0, color="#3A4A52")
    ax_vel.set_ylabel("axial velocity\n(%s)" % units, fontsize=7.5)
    ax_vel.axhline(0, lw=0.6, color="#9AA6AC")
    ax_vel.set_xlim(float(times[0]), float(times[-1]))
    ax_vel.tick_params(labelsize=8)
    dyn["vel_cursor"] = ax_vel.axvline(float(times[0]), color="#C1440E",
                                       lw=1.2, animated=True)

    # -- panel 4: curvature kymograph ---------------------------------------
    # Smoothed along TIME only. Smoothing across segments would blur the
    # head-to-tail structure the kymograph exists to show, and that structure
    # is the wave.
    shown = kymo
    kym_note = ""
    if win >= 2:
        shown = np.vstack([moving_average(row, win) for row in kymo])
        kym_note = f"\nsmoothed {win} frames in time"
    finite = shown[np.isfinite(shown)]
    lim = float(np.percentile(np.abs(finite), 99)) if finite.size else 1.0
    ax_kym.imshow(shown, aspect="auto", cmap="RdBu_r", vmin=-lim, vmax=lim,
                  extent=[float(times[0]), float(times[-1]), rec.n_seg, 0],
                  interpolation="nearest")
    ax_kym.set_ylabel("segment\n(head at top)%s" % kym_note, fontsize=7.5)
    ax_kym.set_xlabel("time (s)", fontsize=9)
    ax_kym.tick_params(labelsize=8)
    dyn["kym_cursor"] = ax_kym.axvline(float(times[0]), color="#111111",
                                       lw=1.2, animated=True)

    # -- honesty strip ------------------------------------------------------
    frac = prov.get("provenance_fraction", {})
    parts = ["%s %.1f%%" % (k, v * 100) for k, v in sorted(frac.items())]
    note = ("geometry provenance: " + ", ".join(parts)) if parts else ""
    extra = ["%s %d" % (k, prov[k]) for k in ("coil_flag", "low_evidence", "skip")
             if prov.get(k)]
    if extra:
        note += "   |   flagged: " + ", ".join(extra)
    note += ("   |   %d/%d frames carry geometry"
             % (prov["frames_with_geometry"], prov["frames_total"]))
    if rec.src8bit:
        note += "   |   8-bit source: ratios are the trustworthy quantity"
    fig.text(0.08, 0.014, note, fontsize=7.5, color="#5E6E76")
    fig.text(0.97, 0.014, "%s %s - renders, measures nothing"
             % (TOOL_NAME, TOOL_VERSION), fontsize=7.5, color="#9AA6AC",
             ha="right")

    ctx = {"values": values, "ranges": ranges, "times": times, "kymo": kymo,
           "prov": prov, "axes": (ax_img, ax_dia, ax_vel, ax_kym)}
    return fig, dyn, ctx


def _update(rec, fig, dyn, ctx, i):
    """Point every dynamic artist at frame index i."""
    frame_no = rec.frames[i]
    ax_img = ctx["axes"][0]

    if "image" in dyn and i < len(rec.image_files):
        dyn["image"].set_data(_read_frame(rec.image_files[i]))
    for name, artist in dyn.get("channels_img", {}).items():
        files = rec.channel_files.get(name, [])
        if i < len(files):
            artist.set_data(channel_plane(_read_frame(files[i]), name))
    fig.suptitle("%s   -   frame %d / %d" % (rec.base, frame_no, rec.n_frames),
                 fontsize=10, x=0.065, ha="left", color="#22303A")

    geo = rec.frame_geometry(frame_no)
    if geo is None:
        dyn["midline"].set_data([], [])
        for poly in dyn["bands"]:
            poly.set_visible(False)
    else:
        mid = np.array([[x, y] for x, y in geo["midline"]
                        if x is not None and y is not None], dtype=float)
        if len(mid):
            dyn["midline"].set_data(mid[:, 0], mid[:, 1])
        else:
            dyn["midline"].set_data([], [])
        k = 0
        for seg in range(rec.n_seg):
            for side in ("L", "R"):
                poly = dyn["bands"][k]
                k += 1
                pts = geo.get("bands", {}).get(str(seg), {}).get(side)
                if not pts:
                    poly.set_visible(False)
                    continue
                poly.set_xy(np.asarray(pts, dtype=float))
                poly.set_visible(True)

    outline_xy = None
    if geo is not None:
        pts = np.array([[x, y] for x, y in geo.get("outline", [])
                        if x is not None and y is not None], dtype=float)
        if len(pts) >= 3:
            outline_xy = np.vstack([pts, pts[:1]])
    for artist in dyn.get("channel_outlines", {}).values():
        if outline_xy is None:
            artist.set_data([], [])
        else:
            artist.set_data(outline_xy[:, 0], outline_xy[:, 1])

    vals = ctx["values"][i]
    for key, patch in dyn["cells"].items():
        band, seg, ch = key
        v = vals[seg, band, ch] if seg < vals.shape[0] else np.nan
        if not np.isfinite(v):
            patch.set_facecolor("#EDEDED")       # absent reads as absent
        else:
            base = msch.CHANNEL_RGB[ch]
            patch.set_facecolor(tuple(1 - (1 - c) * float(v) for c in base))

    bend = pd.to_numeric(rec.df.loc[rec.df["frame"] == frame_no, "seg_curv_deg"],
                         errors="coerce").dropna()
    dyn["bend"].set_text("mean local bend this frame: %+.1f deg" % bend.mean()
                         if len(bend) else "bend unavailable this frame")

    t = float(ctx["times"][i])
    dyn["vel_cursor"].set_xdata([t, t])
    dyn["kym_cursor"].set_xdata([t, t])


def _dynamic_artists(dyn):
    out = [dyn.get("image"), dyn.get("midline"), dyn.get("bend"),
           dyn.get("vel_cursor"), dyn.get("kym_cursor")]
    out += list(dyn.get("bands", []))
    out += list(dyn.get("cells", {}).values())
    out += list(dyn.get("channels_img", {}).values())
    out += list(dyn.get("channel_outlines", {}).values())
    return [a for a in out if a is not None]


class _RGBCaMPSource(mc.MovieSource):
    """Adapts one Recording to the shared engine in app/movie_core.py.

    Everything assay-specific stays here - the panels, the muscle diagram, the
    band overlay. Nothing here touches ffmpeg, blitting or the provenance
    plumbing; that is the core's job and every results movie shares it.
    """

    def __init__(self, rec, normalisation="percentile", smooth_s=0.6):
        self.rec = rec
        self.base = rec.base
        self.n_frames = rec.n_frames
        self.fps = rec.fps
        self.normalisation = normalisation
        self.smooth_s = smooth_s

    def build_figure(self, **_):
        return build_figure(self.rec, normalisation=self.normalisation,
                            smooth_s=self.smooth_s)

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
            "geometry_sidecar": str(rec.geometry_path),
            "image_dir": str(rec.image_dir) if rec.image_dir else None,
            "n_seg": rec.n_seg, "band_names": rec.band_names,
            "normalisation": self.normalisation,
            "channel_ranges": {k: list(v) for k, v in ctx["ranges"].items()},
            "smoothing_seconds": float(self.smooth_s),
            "smoothing_frames": mc.smooth_window_frames(self.smooth_s, rec.fps),
            "channels_shown": sorted(rec.channel_files),
            "um_per_px_declared": rec.um_per_px,
            "velocity_units": "um/s" if rec.um_per_px > 0 else "px/s",
            "src8bit": rec.src8bit,
            "provenance": ctx["prov"],
        }


def render(rec, out_path, normalisation="percentile", smooth_s=0.6,
           decimate=1, fps=None, progress=None):
    """Write the movie and its provenance JSON. Returns (path, provenance)."""
    source = _RGBCaMPSource(rec, normalisation=normalisation,
                            smooth_s=smooth_s)
    return mc.render(source, out_path, decimate=decimate, fps=fps,
                     progress=progress, tool_name=TOOL_NAME,
                     tool_version=TOOL_VERSION)


def preview(rec, out_path, normalisation="percentile", smooth_s=0.6, n=4):
    """Contact sheet of representative frames: brightest, dimmest, median."""
    source = _RGBCaMPSource(rec, normalisation=normalisation,
                            smooth_s=smooth_s)
    values, _ = rec.channel_values(normalisation=normalisation)
    per_frame = np.nanmean(values.reshape(rec.n_frames, -1), axis=1)
    ordered = np.argsort(np.nan_to_num(per_frame, nan=-1.0))
    picks = sorted({0, int(ordered[0]), int(ordered[len(ordered) // 2]),
                    int(ordered[-1])})[:n]
    return mc.preview(source, out_path, picks=picks, n=n)
