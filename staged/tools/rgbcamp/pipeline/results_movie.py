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

TOOL_NAME = "RGBCaMP results movie"
TOOL_VERSION = "0.1.0"
MYOCYTE_SEGMENTS = 24
CHANNELS = ("red", "green", "blue")


class MovieInputError(RuntimeError):
    """Raised with a message that names the consequence, not the errno."""


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
class Recording:
    """CSV + geometry sidecar + image sequence for one recording."""

    def __init__(self, csv_path, image_dir=None):
        self.csv_path = Path(csv_path)
        if not self.csv_path.exists():
            raise MovieInputError(f"No recording CSV at {self.csv_path}.")
        self.df = pd.read_csv(self.csv_path, encoding="utf-8-sig")
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

    def _find_images(self):
        if self.image_dir is None or not self.image_dir.exists():
            return []
        exts = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}
        files = sorted(p for p in self.image_dir.iterdir()
                       if p.suffix.lower() in exts)
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
def _read_frame(path):
    from PIL import Image
    return np.asarray(Image.open(path))


def build_figure(rec, normalisation="percentile", figsize=(13.0, 7.2), dpi=110):
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

    fig = plt.figure(figsize=figsize, dpi=dpi)
    fig.patch.set_facecolor("white")
    # The frame is square and the diagram is a long thin worm, so stacking them
    # wasted width on one and height on the other. Side by side, the row is set
    # by the taller of the two and the movie loses a third of its height.
    gs = GridSpec(3, 2, figure=fig, width_ratios=[1.0, 3.05],
                  height_ratios=[2.2, 1.0, 1.15],
                  hspace=0.55, wspace=0.06,
                  left=0.075, right=0.975, top=0.92, bottom=0.09)

    ax_img = fig.add_subplot(gs[0, 0])
    ax_dia = fig.add_subplot(gs[0, 1])
    ax_vel = fig.add_subplot(gs[1, :])
    ax_kym = fig.add_subplot(gs[2, :])

    dyn = {}

    # -- panel 1: worm + overlay -------------------------------------------
    ax_img.set_title("frame 1", fontsize=10, loc="left", color="#22303A")
    ax_img.axis("off")
    if rec.image_files:
        first = _read_frame(rec.image_files[0])
        dyn["image"] = ax_img.imshow(
            first, cmap=None if first.ndim == 3 else "gray", animated=True)
    else:
        ax_img.text(0.5, 0.5,
                    "no image sequence supplied - panels 2-4 are unaffected",
                    ha="center", va="center", fontsize=10, color="#a00000")
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
    if vel_um is not None:
        ax_vel.plot(times, vel_um, lw=1.0, color="#3A4A52")
        ax_vel.set_ylabel("axial velocity\n(um/s, declared scale)", fontsize=8)
    else:
        ax_vel.plot(times, vel_px, lw=1.0, color="#3A4A52")
        ax_vel.set_ylabel("axial velocity\n(px/s - scale NOT calibrated)",
                          fontsize=8)
    ax_vel.axhline(0, lw=0.6, color="#9AA6AC")
    ax_vel.set_xlim(float(times[0]), float(times[-1]))
    ax_vel.tick_params(labelsize=8)
    dyn["vel_cursor"] = ax_vel.axvline(float(times[0]), color="#C1440E",
                                       lw=1.2, animated=True)

    # -- panel 4: curvature kymograph ---------------------------------------
    finite = kymo[np.isfinite(kymo)]
    lim = float(np.percentile(np.abs(finite), 99)) if finite.size else 1.0
    ax_kym.imshow(kymo, aspect="auto", cmap="RdBu_r", vmin=-lim, vmax=lim,
                  extent=[float(times[0]), float(times[-1]), rec.n_seg, 0],
                  interpolation="nearest")
    ax_kym.set_ylabel("segment\n(head at top)", fontsize=8)
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
    ax_img.set_title("frame %d / %d" % (frame_no, rec.n_frames),
                     fontsize=10, loc="left", color="#22303A")

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
    return [a for a in out if a is not None]


def render(rec, out_path, normalisation="percentile", decimate=1, fps=None,
           progress=None):
    """Write the movie and its provenance JSON. Returns (path, provenance)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import imageio.v2 as imageio

    out_path = Path(out_path)
    fig, dyn, ctx = build_figure(rec, normalisation=normalisation)
    canvas = fig.canvas
    canvas.draw()
    background = canvas.copy_from_bbox(fig.bbox)

    indices = list(range(0, rec.n_frames, max(1, int(decimate))))
    out_fps = float(fps or max(1.0, rec.fps))
    writer = imageio.get_writer(str(out_path), fps=out_fps,
                                macro_block_size=None)
    try:
        for n, i in enumerate(indices):
            _update(rec, fig, dyn, ctx, i)
            canvas.restore_region(background)
            for artist in _dynamic_artists(dyn):
                fig.draw_artist(artist)
            canvas.blit(fig.bbox)
            writer.append_data(np.asarray(canvas.buffer_rgba())[..., :3])
            if progress and (n % 20 == 0 or n == len(indices) - 1):
                progress(n + 1, len(indices))
    finally:
        writer.close()
        plt.close(fig)

    prov = {
        "tool": TOOL_NAME, "tool_version": TOOL_VERSION,
        "source_csv": str(rec.csv_path),
        "geometry_sidecar": str(rec.geometry_path),
        "image_dir": str(rec.image_dir) if rec.image_dir else None,
        "n_frames_source": rec.n_frames, "n_frames_rendered": len(indices),
        "decimate": int(decimate), "output_fps": out_fps,
        "n_seg": rec.n_seg, "band_names": rec.band_names,
        "normalisation": normalisation,
        "channel_ranges": {k: list(v) for k, v in ctx["ranges"].items()},
        "um_per_px_declared": rec.um_per_px,
        "velocity_units": "um/s" if rec.um_per_px > 0 else "px/s",
        "src8bit": rec.src8bit,
        "provenance": ctx["prov"],
    }
    prov_path = out_path.with_name(out_path.stem + "_provenance.json")
    prov_path.write_text(json.dumps(prov, indent=2), encoding="utf-8")
    return out_path, prov


def preview(rec, out_path, normalisation="percentile", n=4):
    """Contact sheet of representative frames.

    Choosing a normalisation from four stills beats rendering a whole movie
    twice, which is the loop this exists to avoid.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    values, _ = rec.channel_values(normalisation=normalisation)
    per_frame = np.nanmean(values.reshape(rec.n_frames, -1), axis=1)
    ordered = np.argsort(np.nan_to_num(per_frame, nan=-1.0))
    picks = sorted({0, int(ordered[0]), int(ordered[len(ordered) // 2]),
                    int(ordered[-1])})[:n]

    fig, dyn, ctx = build_figure(rec, normalisation=normalisation)
    sheet, axes = plt.subplots(len(picks), 1, figsize=(11, 3.2 * len(picks)))
    axes = np.atleast_1d(axes)
    for ax, i in zip(axes, picks):
        _update(rec, fig, dyn, ctx, i)
        fig.canvas.draw()
        ax.imshow(np.asarray(fig.canvas.buffer_rgba())[..., :3])
        ax.set_title("frame %d  (t=%.1fs)" % (rec.frames[i], ctx["times"][i]),
                     fontsize=9, loc="left")
        ax.axis("off")
    sheet.tight_layout()
    sheet.savefig(str(out_path), dpi=120, facecolor="white")
    plt.close(fig)
    plt.close(sheet)
    return Path(out_path)
