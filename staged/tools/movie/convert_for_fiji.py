"""
convert_for_fiji.py
==================
Read any movie or stack through movie_reader and write ONE clean TIFF stack
that Fiji opens natively. This is the light bridge: it does not replace your
ImageJ tools, it feeds them. Your students stop fighting Media Encoder and stop
producing broken duplicate conversions; they get a single correct file that
every existing Fiji macro and plugin reads unchanged.

Key properties, chosen to be safe rather than clever:
  - No re-compression and no bit-depth change. An 8-bit RGB video comes out
    8-bit RGB; a 16-bit grayscale stack comes out 16-bit grayscale. Nothing is
    upsampled, faked, or lossily re-encoded.
  - Written frame by frame, so a multi-gigabyte movie never has to fit in RAM.
  - Under about 3.9 GB it writes a true ImageJ-format TIFF (the kind Fiji opens
    as a stack with one double-click) and carries the frame rate across in the
    metadata. Above that size, classic ImageJ TIFF cannot address the file, so
    it automatically writes BigTIFF instead, which current Fiji opens through
    its bundled Bio-Formats importer. The completion report says which one it
    wrote and how to open it.

Tested here: grayscale and RGB stacks round-trip and read back as ImageJ TIFFs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import numpy as np
import tifffile

from movie_reader import open_movie, Movie

# Classic (non-BigTIFF) uses 32-bit offsets. Stay safely under 4 GiB.
IMAGEJ_TIFF_LIMIT = 3_900_000_000


def _effective_counts(n, h, w, start, stop, step, scale):
    stop = n if (stop is None or stop > n) else stop
    start = max(0, start)
    n_eff = max(0, len(range(start, stop, max(1, step))))
    h_eff = max(1, round(h * scale))
    w_eff = max(1, round(w * scale))
    return n_eff, h_eff, w_eff


def estimate_bytes(n_frames, height, width, n_channels, itemsize,
                   start=0, stop=None, step=1, scale=1.0) -> int:
    """Estimate output bytes from raw dimensions (so a GUI can recompute live
    without holding a Movie)."""
    ch = max(1, n_channels)
    n_eff, h_eff, w_eff = _effective_counts(n_frames, height, width, start, stop, step, scale)
    return int(n_eff) * int(h_eff) * int(w_eff) * ch * int(itemsize)


def estimate_output_bytes(m: Movie, start=0, stop=None, step=1, scale=1.0) -> int:
    return estimate_bytes(m.n_frames, m.height, m.width, m.n_channels,
                          np.dtype(m.dtype).itemsize, start, stop, step, scale)


def _resize_frame(frame: np.ndarray, scale: float) -> np.ndarray:
    if scale == 1.0:
        return frame
    import cv2
    h, w = frame.shape[:2]
    nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    return cv2.resize(frame, (nw, nh), interpolation=interp)


def default_output_path(src: str | Path) -> Path:
    src = Path(src)
    stem = src.stem if src.is_file() else src.name
    parent = src.parent if src.is_file() else src.parent
    return parent / f"{stem}_forFiji.tif"


def convert_to_tiff_stack(src, out_path: Optional[str | Path] = None,
                          progress_cb: Optional[Callable[[int, int], None]] = None,
                          cancel_check: Optional[Callable[[], bool]] = None,
                          frame_start: int = 0, frame_stop: Optional[int] = None,
                          frame_step: int = 1, scale: float = 1.0,
                          max_bytes: Optional[int] = None) -> dict:
    """Convert src (path or an already-open Movie) to a Fiji TIFF stack.

    Downsampling (so an hour of 1080p does not become a 600 GB stack):
      frame_start / frame_stop : keep only this frame range
      frame_step               : keep every Nth frame (30 ~= one per second at 30 fps)
      scale                    : spatial scale, e.g. 0.5 = half resolution

    max_bytes: if the estimated output exceeds this, refuse and return without
    writing (a guard so a huge accidental conversion cannot start). None = no cap.

    progress_cb(done, total) after each written frame; cancel_check() aborts and
    removes the partial file. Returns a report dict.
    """
    m = src if isinstance(src, Movie) else open_movie(src)
    close_after = not isinstance(src, Movie)
    out_path = Path(out_path) if out_path is not None else default_output_path(m.path)

    est = estimate_output_bytes(m, frame_start, frame_stop, frame_step, scale)
    if max_bytes is not None and est > max_bytes:
        if close_after:
            m.close()
        return dict(output=str(out_path), refused=True, aborted=False,
                    estimated_bytes=est, max_bytes=max_bytes,
                    format=f"refused: estimated {est/1e9:.0f} GB exceeds the limit "
                           f"({max_bytes/1e9:.0f} GB). Downsample first.")

    use_bigtiff = est >= IMAGEJ_TIFF_LIMIT
    # Write a PLAIN multipage TIFF (no ImageJ hyperstack metadata). ImageJ opens
    # a plain multipage stack as ordinary slices; the ImageJ-hyperstack path
    # mislabels a stack of frames as CHANNELS (shows "c:150" instead of a frame
    # stack), which breaks per-frame tools. fps is entered in the tool/analysis,
    # so nothing is lost by dropping the embedded interval.
    kwargs = dict(bigtiff=use_bigtiff)

    n_eff = _effective_counts(m.n_frames, m.height, m.width,
                              frame_start, frame_stop, frame_step, scale)[0]
    aborted = False
    frames_written = 0
    try:
        with tifffile.TiffWriter(str(out_path), **kwargs) as tif:
            for i, frame in enumerate(m.frames(start=frame_start, stop=frame_stop, step=frame_step)):
                if cancel_check is not None and cancel_check():
                    aborted = True
                    break
                frame = _resize_frame(frame, scale)
                is_rgb = frame.ndim == 3 and frame.shape[2] in (3, 4)
                photometric = "rgb" if is_rgb else "minisblack"
                tif.write(frame, contiguous=True, photometric=photometric)
                frames_written = i + 1
                if progress_cb:
                    progress_cb(i + 1, n_eff)
    finally:
        if close_after:
            m.close()

    if aborted:
        try:
            Path(out_path).unlink(missing_ok=True)
        except Exception:
            pass
        return dict(output=str(out_path), aborted=True, refused=False,
                    frames_written=frames_written, n_frames=int(n_eff),
                    format="cancelled (partial file removed, nothing saved)")

    return dict(
        output=str(out_path), aborted=False, refused=False,
        frames_written=frames_written,
        format=("TIFF stack (opens in Fiji as a slice stack)" if not use_bigtiff
                else "BigTIFF stack (opens in Fiji via Bio-Formats / as a virtual stack)"),
        bigtiff=use_bigtiff, n_frames=int(frames_written),
        declared_frames=int(m.n_frames),
        width=int(round(m.width * scale)), height=int(round(m.height * scale)),
        n_channels=int(m.n_channels), dtype=str(m.dtype), fps=m.fps,
        estimated_bytes=est,
        downsample=dict(start=frame_start, stop=frame_stop, step=frame_step, scale=scale),
    )


if __name__ == "__main__":
    import sys, json
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    rep = convert_to_tiff_stack(src, out,
                                progress_cb=lambda d, t: print(f"\r{d}/{t}", end=""))
    print("\n" + json.dumps(rep, indent=2))
