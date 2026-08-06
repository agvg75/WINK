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

# DimID in the Leica header. 1 and 2 are the image plane; 4 is time.
DIM_X, DIM_Y, DIM_Z, DIM_T = "1", "2", "3", "4"


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

    Returns dicts with name, n_x/n_y/n_t, n_channels, bit_depth, duration_s
    and fps. fps is None where there is no time dimension, and callers must
    treat that as "no time series" rather than substituting a default.
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
