"""Leica .lif files: what series are in them, and their pixels.

Written because the tool asked the user to TYPE how many frames a recording had
and then answered from that. Pointed at a 224-frame movie with the field left at
its default of 1, it reported that every kinetic measurement was impossible
because "this is a single frame". The data was right there in the file.

Anything a file states about itself is read from the file. The user declares
what the file cannot know - which probe, which channel is which - and nothing
else.

FRAME RATE IS READ, NEVER ASSUMED. Every timing this module feeds downstream is
in seconds. The .lif header gives the time dimension as a count of elements and
a total span, so the interval is span / (count - 1) - the span runs from the
first frame to the last, not one frame beyond. Checked against the CycleTime the
scope also writes: 224 frames over 29.882 s gives 0.134 s, and CycleTime says
0.134 s.
"""
from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

import cell_calcium as cc

# DimID in the Leica header. 1 and 2 are the image plane; 3 is z, 4 is time.
DIM_X, DIM_Y, DIM_Z, DIM_T = "1", "2", "3", "4"

# Length in a DimensionDescription is the total physical extent of the axis,
# and the unit is stated alongside it. Everything is converted to micrometres
# on the way out so no caller has to know what a Leica file writes.
UNIT_TO_UM = {"m": 1e6, "meter": 1e6, "metre": 1e6,
              "mm": 1e3, "um": 1.0, "µm": 1.0, "μm": 1.0, "nm": 1e-3}

# Above this, the header is not describing a pixel. Set from the data rather
# than from taste: across the 387 .lif files on the scope computer the largest
# genuine value is 25.8 um/px and the median is 0.107, so a millimetre sits
# 39x above anything real while still catching the metre-per-pixel that a
# derived image reports. An objective that gave a 1 mm pixel would not be a
# microscope objective.
MAX_CREDIBLE_UM_PER_PX = 1e3


def _extent_um(dim):
    """Physical size of one element along a dimension, in micrometres.

    Returns None when the header carries no length, which is the honest
    answer for an uncalibrated series - a scope that recorded no zoom or
    objective writes zero here, and a zero must not be read as a scale.

    The span runs from the FIRST element to the LAST, so it covers n - 1
    steps, not n. This is the same convention the time axis already uses
    above, and getting it wrong biases a small stack badly: over 5 planes
    the two readings differ by 25%.
    """
    if dim is None:
        return None
    try:
        length = float(dim.get("Length", 0) or 0)
        n = int(dim.get("NumberOfElements", 0) or 0)
    except (TypeError, ValueError):
        return None
    if n < 2 or length <= 0:
        return None
    factor = UNIT_TO_UM.get((dim.get("Unit") or "m").strip().lower())
    if factor is None:
        return None
    um = length * factor / (n - 1)
    # A light microscope does not have a millimetre pixel. Leica writes the
    # ELEMENT INDEX into Length on derived images - FLIM decay maps, pattern
    # matching scatter plots - so Length comes back as n - 1 with the unit
    # still reading metres, and the arithmetic above yields exactly 1 m per
    # pixel. That is a missing calibration wearing a number's clothes, and
    # reporting it as a scale would put a 1,000,000x error into whatever
    # measured from it.
    return um if 0 < um < MAX_CREDIBLE_UM_PER_PX else None


def _header_xml(path):
    """The XML block at the front of a .lif, without reading the pixels."""
    with open(path, "rb") as fh:
        if struct.unpack("<i", fh.read(4))[0] != 0x70:
            raise cc.CalciumError(
                f"{Path(path).name} does not start with the .lif marker, so it "
                f"is not a Leica file (or it is truncated).")
        fh.read(4)
        if fh.read(1) != b"\x2a":
            raise cc.CalciumError(
                f"{Path(path).name} has a .lif marker but a malformed header.")
        n_chars = struct.unpack("<I", fh.read(4))[0]
        return fh.read(n_chars * 2).decode("utf-16-le", errors="replace")


def series_list(path):
    """Every image series in the file, described from its own header.

    Returns dicts with name, n_x/n_y/n_z/n_t, n_channels, bit_depth,
    duration_s, fps and the spatial calibration um_per_px / um_per_px_y /
    um_per_z.

    fps and the calibrations are None where the header does not carry them,
    and callers must treat that as "not recorded" rather than substituting a
    default. A missing micrometres-per-pixel is the difference between a
    measurement and a number.
    """
    root = ET.fromstring(_header_xml(path))
    out = []

    def walk(el):
        for child in el:
            desc = None
            if child.tag == "Element":
                desc = child.find("./Data/Image/ImageDescription")
            if desc is not None:
                dims = {d.get("DimID"): d for d in
                        desc.findall("./Dimensions/DimensionDescription")}
                chans = desc.findall("./Channels/ChannelDescription")
                n_t = int(dims[DIM_T].get("NumberOfElements", 0)) \
                    if DIM_T in dims else 1
                span = float(dims[DIM_T].get("Length", 0)) \
                    if DIM_T in dims else 0.0
                depths = {int(c.get("Resolution", 8)) for c in chans}
                out.append({
                    "index": len(out),
                    "name": child.get("Name", f"series{len(out)}"),
                    "n_x": int(dims[DIM_X].get("NumberOfElements", 0))
                    if DIM_X in dims else 0,
                    "n_y": int(dims[DIM_Y].get("NumberOfElements", 0))
                    if DIM_Y in dims else 0,
                    "n_z": int(dims[DIM_Z].get("NumberOfElements", 1))
                    if DIM_Z in dims else 1,
                    "n_t": n_t,
                    "n_channels": len(chans),
                    "lut_names": [c.get("LUTName") for c in chans],
                    "bit_depth": max(depths) if depths else 8,
                    "duration_s": span if n_t > 1 else None,
                    "fps": ((n_t - 1) / span) if (n_t > 1 and span > 0)
                    else None,
                    "um_per_px": _extent_um(dims.get(DIM_X)),
                    "um_per_px_y": _extent_um(dims.get(DIM_Y)),
                    "um_per_z": _extent_um(dims.get(DIM_Z)),
                })
            walk(child)

    walk(root)
    if not out:
        raise cc.CalciumError(
            f"No image series found in {Path(path).name}.")
    return out


def read_series(path, index, channel=0):
    """Pixels for one series as (T, Y, X). Requires readlif."""
    try:
        from readlif.reader import LifFile
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise cc.CalciumError(
            "Reading .lif pixels needs the readlif package, which is missing "
            "from this environment. The series list above came from the file "
            "header and does not need it.") from exc
    images = list(LifFile(str(path)).get_iter_image())
    if not 0 <= index < len(images):
        raise cc.CalciumError(
            f"Series {index} does not exist; the file has {len(images)}.")
    img = images[index]
    if img.dims.t < 2:
        frame = np.asarray(next(img.get_iter_t(c=channel, z=0)), dtype=float)
        return frame[None, ...]
    return np.stack([np.asarray(f, dtype=float)
                     for f in img.get_iter_t(c=channel, z=0)])


def describe_source(path, *, signal_suffix="_ch00", pattern="*.tif"):
    """What is this source, and what shape is its data?

    Accepts a .lif or a folder of TIFFs and answers the same questions of both,
    so the caller never has to be told what it is looking at.
    """
    p = Path(path)
    if p.is_file() and p.suffix.lower() in (".lif", ".lifext"):
        series = series_list(p)
        movies = [s for s in series if s["n_t"] > 1]
        return {
            "kind": "lif", "path": str(p), "series": series,
            "n_series": len(series), "n_movies": len(movies),
            "max_frames": max((s["n_t"] for s in series), default=1),
            "bit_depth": max((s["bit_depth"] for s in series), default=8),
        }
    if p.is_dir():
        import tifffile
        files = sorted(p.rglob(pattern))
        sig = [f for f in files if signal_suffix in f.name] or files
        n_frames, depth = 1, 8
        if sig:
            with tifffile.TiffFile(sig[0]) as tf:
                n_frames = len(tf.pages)
                depth = int(tf.pages[0].dtype.itemsize * 8)
        return {
            "kind": "folder", "path": str(p), "series": [],
            "n_files": len(files), "n_series": len(sig),
            "n_movies": 1 if n_frames > 1 else 0,
            "max_frames": n_frames, "bit_depth": depth,
        }
    raise cc.CalciumError(
        f"{path} is neither a .lif file nor a folder.")


def cell_traces(frames, *, min_px=12, max_px=4000, percentile=80,
                smooth=1.0):
    """Per-cell traces from a movie, segmented on the TIME AVERAGE.

    Not on one frame. A cell that is dark at rest and bright once is invisible
    in a resting frame and obvious in the mean, so segmenting on a single frame
    finds only the cells that were already active and then reports that they
    were the ones that responded.

    Per cell, not whole-field: a field mean averages responders with
    non-responders and turns an all-or-none response into a small smooth one.
    """
    from scipy import ndimage
    frames = np.asarray(frames, dtype=float)
    if frames.ndim != 3:
        raise cc.CalciumError(
            f"Expected a (time, y, x) stack; got shape {frames.shape}.")
    mean_img = frames.mean(axis=0)
    labels, n = ndimage.label(
        ndimage.gaussian_filter(mean_img, smooth) >
        np.percentile(mean_img, percentile))
    if n == 0:
        return np.zeros_like(labels), np.empty((0, frames.shape[0]))
    sizes = np.bincount(labels.ravel())
    keep = [i for i in range(1, n + 1) if min_px <= sizes[i] <= max_px]
    if not keep:
        return labels, np.empty((0, frames.shape[0]))
    traces = np.stack([frames[:, labels == i].mean(axis=1) for i in keep])
    return labels, traces
