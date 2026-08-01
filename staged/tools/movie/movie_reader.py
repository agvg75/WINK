"""
movie_reader.py
===============
One reader for anything, so the analysis code never cares what the source was.

open_movie(path) sniffs the source and returns a Movie that exposes a uniform
interface (n_frames, shape, dtype, bit_depth, fps, get_frame, frames) whether
the source is:
  - a video file        .mp4 .avi .mov .mkv .webm            (imageio, cv2 fallback)
  - a multipage TIFF    .tif .tiff  (ImageJ/OME hyperstacks)  (tifffile)
  - an image-sequence   a FOLDER of .tif/.png/.jpg/.pgm/...   (natural-sorted)
  - a single image      one .png/.jpg/.pgm/.bmp/.tif          (n_frames = 1)

The point is to reach into the lab drive and analyse in place, no manual
conversion step. Downstream code asks for frames as numpy arrays and gets them
identically regardless of origin.

HONESTY GUARD ON INTENSITY. Geometry and heading survive lossy 8-bit video;
calcium intensity does not. Every Movie reports quantitative_intensity_ok and a
reason, so a calcium pipeline can refuse an mp4 while a behaviour pipeline runs
on it happily. This is a property of the source, decided here once, not
re-litigated in every analysis.

fps is read from the container when present (video) and is None otherwise
(TIFF and image sequences carry no reliable frame rate), matching the existing
pipeline convention that fps is entered manually when the source cannot supply
it.

Tested here on a single TIFF, an image-sequence folder, and a single image; the
video path uses imageio/cv2 and should be confirmed on a real clip in your
environment.
"""
from __future__ import annotations

import os
import re
import glob
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Iterator

import numpy as np


VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}
TIFF_EXTS = {".tif", ".tiff"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".pgm", ".ppm", ".pnm", ".bmp",
              ".webp", ".tif", ".tiff"}
LOSSY_EXTS = {".jpg", ".jpeg", ".webp"}  # lossy still formats


def _natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _bit_depth(dtype: np.dtype) -> int:
    dt = np.dtype(dtype)
    if dt == np.uint8:
        return 8
    if dt in (np.uint16, np.int16):
        return 16
    if dt in (np.uint32, np.int32, np.float32):
        return 32
    return dt.itemsize * 8


@dataclass
class Movie:
    """Uniform handle to a frame source. Subclasses fill in _read_frame and the
    header fields; everything else (iteration, eager load, intensity verdict) is
    shared here."""
    path: Path
    source_kind: str                 # "video" | "tiff_stack" | "image_sequence" | "single_image"
    n_frames: int
    height: int
    width: int
    n_channels: int                  # 1 grayscale, 3 RGB, etc.
    dtype: np.dtype
    fps: Optional[float]
    backend: str
    lossy: bool                      # source used lossy compression
    metadata: dict = field(default_factory=dict)

    # ---- intensity verdict, decided once from the source properties ----
    @property
    def bit_depth(self) -> int:
        return _bit_depth(self.dtype)

    @property
    def quantitative_intensity_ok(self) -> bool:
        # calcium needs faithful, high-dynamic-range intensity. Lossy sources
        # fail outright; 8-bit lossless is usable but low dynamic range; >=12-bit
        # is the real quantitative regime.
        return (not self.lossy) and self.bit_depth >= 12

    @property
    def quantitative_reason(self) -> str:
        if self.lossy:
            return ("lossy-compressed source: intensity is not quantitative "
                    "(geometry and heading are fine). Use the original 16-bit "
                    "acquisition for calcium.")
        if self.bit_depth < 12:
            return (f"{self.bit_depth}-bit lossless: intensity is usable but low "
                    "dynamic range; prefer >=12-bit for quantitative calcium.")
        return f"{self.bit_depth}-bit, no lossy compression: intensity is quantitative."

    # ---- frame count exactness ------------------------------------------
    # For TIFFs, image sequences and single images the count is known exactly
    # the moment the source is opened.  Compressed video is the exception: an
    # exact count costs a full decode pass, so VideoMovie opens with a cheap
    # container ESTIMATE and only pays for exactness when someone asks.
    #
    # Anything that feeds a reported measurement (notably `analyze`, where a
    # blank end-frame means "to the last frame" and therefore sets
    # coverage_fraction) MUST call ensure_exact_n_frames() first.  Interactive
    # code - previews, ROI drawing, scrubbing - should not: the estimate is
    # what makes opening a movie instant.
    n_frames_is_exact: bool = True

    def ensure_exact_n_frames(self) -> int:
        """Return an exact frame count, computing it if necessary."""
        return self.n_frames

    # ---- frame access (subclasses implement _read_frame) ----
    def _read_frame(self, i: int) -> np.ndarray:
        raise NotImplementedError

    def get_frame(self, i: int) -> np.ndarray:
        if i < 0:
            i += self.n_frames
        if not (0 <= i < self.n_frames):
            raise IndexError(f"frame {i} out of range 0..{self.n_frames - 1}")
        try:
            return self._read_frame(i)
        except IndexError:
            raise
        except Exception:
            # An estimated count can overshoot the real end of the stream, so a
            # read past the end is a range error, not a decode failure.
            if not self.n_frames_is_exact and i >= self.ensure_exact_n_frames():
                raise IndexError(
                    f"frame {i} out of range 0..{self.n_frames - 1}") from None
            raise

    def frames(self, start: int = 0, stop: Optional[int] = None,
               step: int = 1) -> Iterator[np.ndarray]:
        stop = self.n_frames if stop is None else stop
        for i in range(start, min(stop, self.n_frames), step):
            yield self.get_frame(i)

    def to_array(self, max_frames: Optional[int] = None) -> np.ndarray:
        """Eager load to a (T, H, W[, C]) array. Guarded: refuses silently huge
        loads unless max_frames is given."""
        n = self.n_frames if max_frames is None else min(self.n_frames, max_frames)
        if max_frames is None and n * self.height * self.width * max(1, self.n_channels) > 4_000_000_000:
            raise MemoryError("movie too large to load eagerly; iterate frames() "
                              "or pass max_frames")
        return np.stack([self.get_frame(i) for i in range(n)], axis=0)

    def summary(self) -> dict:
        return dict(path=str(self.path), source_kind=self.source_kind,
                    n_frames=self.n_frames, height=self.height, width=self.width,
                    n_channels=self.n_channels, dtype=str(self.dtype),
                    bit_depth=self.bit_depth, fps=self.fps, backend=self.backend,
                    lossy=self.lossy,
                    quantitative_intensity_ok=self.quantitative_intensity_ok,
                    quantitative_reason=self.quantitative_reason)

    def close(self):
        pass


# --------------------------------------------------------------------------- #
# TIFF stack (single or multipage)
# --------------------------------------------------------------------------- #
class TiffMovie(Movie):
    def __init__(self, path: Path):
        import tifffile
        self._tif = tifffile.TiffFile(str(path))
        series = self._tif.series[0]
        axes = series.axes            # e.g. "YX","CYX","TYX","CYXS","ZYXS"
        shape = series.shape
        self._axes = axes

        def _sz(ax):
            return shape[axes.index(ax)] if ax in axes else 1

        h, w, c = _sz("Y"), _sz("X"), _sz("S")
        # Any axis that is not spatial (Y, X) or samples (S) is a frame axis.
        # tifffile may label the stack axis T, Z, I, C, Q, ... so do not hardcode.
        frame_axes = [a for a in axes if a not in ("Y", "X", "S")]
        n = int(np.prod([shape[axes.index(a)] for a in frame_axes])) if frame_axes else 1
        # fallback for plain multipage files whose series axes are unhelpful
        if n <= 1 and len(self._tif.pages) > 1:
            n = len(self._tif.pages)

        arr0 = self._read_plane(0)
        dtype = arr0.dtype
        if h == 1 or w == 1:          # axes did not expose Y/X: take from the plane
            if arr0.ndim == 2:
                h, w = arr0.shape; c = 1
            else:
                h, w = arr0.shape[:2]; c = arr0.shape[2]

        meta = {}
        try:
            if self._tif.imagej_metadata:
                meta = dict(self._tif.imagej_metadata)
        except Exception:
            pass
        fps = None
        fi = meta.get("finterval")    # ImageJ frame interval, seconds
        if fi:
            try:
                fps = 1.0 / float(fi) if float(fi) > 0 else None
            except Exception:
                fps = None
        super().__init__(path=path, source_kind="tiff_stack" if n > 1 else "single_image",
                         n_frames=int(n), height=int(h), width=int(w), n_channels=int(c),
                         dtype=dtype, fps=fps, backend="tifffile", lossy=False, metadata=meta)

    def _read_plane(self, i: int) -> np.ndarray:
        try:
            return self._tif.asarray(key=i)
        except Exception:
            a = self._tif.series[0].asarray()
            return a[i] if (a.ndim > 2 and i < a.shape[0]) else a

    def _read_frame(self, i: int) -> np.ndarray:
        return self._read_plane(i)

    def close(self):
        try:
            self._tif.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Image-sequence folder (natural-sorted) or a single still image
# --------------------------------------------------------------------------- #
class ImageSequenceMovie(Movie):
    def __init__(self, files: list, path: Path):
        import imageio.v3 as iio
        self._iio = iio
        self._files = files
        first = iio.imread(files[0])
        if first.ndim == 2:
            h, w = first.shape; c = 1
        else:
            h, w = first.shape[:2]; c = first.shape[2]
        lossy = Path(files[0]).suffix.lower() in LOSSY_EXTS
        kind = "single_image" if len(files) == 1 else "image_sequence"
        super().__init__(path=path, source_kind=kind, n_frames=len(files),
                         height=int(h), width=int(w), n_channels=int(c),
                         dtype=first.dtype, fps=None, backend="imageio",
                         lossy=lossy, metadata={"n_files": len(files)})

    def _read_frame(self, i: int) -> np.ndarray:
        return self._iio.imread(self._files[i])


# --------------------------------------------------------------------------- #
# Video container (mp4/avi/...). imageio-ffmpeg first, cv2 fallback.
# --------------------------------------------------------------------------- #
class VideoMovie(Movie):
    def __init__(self, path: Path, *, exact_count: bool = True):
        # exact_count=True (the default) preserves the historical behaviour: the
        # frame count is exact the moment the movie is open, at the cost of a
        # full decode pass.  Interactive callers that only need previews may
        # pass exact_count=False for an instant open with an approximate count,
        # but MUST call ensure_exact_n_frames() before any reported number.
        self._exact_count = bool(exact_count)
        self._backend = None
        n = h = w = c = 0
        dtype = np.uint8
        fps = None
        # try imageio (ffmpeg) first
        try:
            import imageio.v3 as iio
            meta = iio.immeta(str(path))
            fps = float(meta.get("fps")) if meta.get("fps") else None
            # frame count: prefer meta, else count lazily (bounded)
            n = int(meta.get("nframes")) if meta.get("nframes") not in (None, float("inf")) else 0
            probe = iio.imread(str(path), index=0)
            if probe.ndim == 2:
                h, w = probe.shape; c = 1
            else:
                h, w = probe.shape[:2]; c = probe.shape[2]
            dtype = probe.dtype
            self._iio = iio
            self._backend = "imageio-ffmpeg"
        except Exception:
            self._iio = None
        if self._backend is None:
            import cv2
            self._cap = cv2.VideoCapture(str(path))
            self._cv2 = cv2
            fps = self._cap.get(cv2.CAP_PROP_FPS) or None
            n = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
            w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            c = 3
            dtype = np.uint8
            self._backend = "cv2"
        # An exact count costs a full decode pass - on a 126 MB 4K clip that is
        # ~170 s, and it used to be paid on EVERY open, including opens that
        # only wanted one preview frame.  Take a cheap container estimate here
        # and defer the exact count to ensure_exact_n_frames().
        exact = bool(n)
        if not n:
            if self._exact_count:
                n = self._count_frames(path); exact = True
            else:
                n = self._estimate_frames(path, fps)
        super().__init__(path=path, source_kind="video", n_frames=int(n),
                         height=int(h), width=int(w), n_channels=int(c),
                         dtype=dtype, fps=fps, backend=self._backend, lossy=True,
                         metadata={})
        self.n_frames_is_exact = exact

    def _estimate_frames(self, path, fps):
        """Cheap, approximate frame count from container metadata (~0.3 s).

        Deliberately approximate: containers over- and under-report, so this
        may be off by a handful of frames either way.  It exists so the UI can
        open instantly; it must never reach a reported measurement.
        """
        try:
            import cv2
            cap = cv2.VideoCapture(str(path))
            try:
                count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            finally:
                cap.release()
            if count > 0:
                return count
        except Exception:
            pass
        try:                                    # duration x rate as a fallback
            meta = self._iio.immeta(str(path)) if self._iio is not None else {}
            duration = float(meta.get("duration") or 0)
            rate = float(fps or meta.get("fps") or 0)
            if duration > 0 and rate > 0:
                return max(1, int(round(duration * rate)))
        except Exception:
            pass
        return self._count_frames(path)         # nothing cheap worked

    def ensure_exact_n_frames(self):
        if not self.n_frames_is_exact:
            self.n_frames = int(self._count_frames(self.path))
            self.n_frames_is_exact = True
        return self.n_frames

    def _count_frames(self, path):
        # last resort: iterate once to count (bounded to a sane cap)
        cnt = 0
        if self._backend == "imageio-ffmpeg":
            for _ in self._iio.imiter(str(path)):
                cnt += 1
                if cnt > 2_000_000:
                    break
        return cnt

    def _read_frame(self, i: int) -> np.ndarray:
        # Random access to ONE frame. Fine for spot checks; do NOT call in a
        # loop over a video, use frames() which streams. Per-index reads on a
        # compressed video re-decode from the start (O(n) each, O(n^2) total).
        if self._backend == "imageio-ffmpeg":
            return self._iio.imread(str(self.path), index=i)
        self._cap.set(self._cv2.CAP_PROP_POS_FRAMES, i)
        ok, frame = self._cap.read()
        if not ok:
            raise IOError(f"could not read frame {i}")
        return self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)

    def frames(self, start: int = 0, stop=None, step: int = 1):
        # Sequential streaming: decode the file ONCE, and follow the ACTUAL end
        # of the stream rather than the declared frame count, which some
        # containers over- or under-report (the cause of "IndexError: <frame>"
        # on per-index reads). ~100x faster than per-index too.
        if self._backend == "imageio-ffmpeg":
            idx = 0
            for fr in self._iio.imiter(str(self.path)):
                if stop is not None and idx >= stop:
                    break
                if idx >= start and (idx - start) % step == 0:
                    yield fr
                idx += 1
        else:
            cap = self._cv2.VideoCapture(str(self.path))
            try:
                idx = 0
                while True:
                    if stop is not None and idx >= stop:
                        break
                    ok, frame = cap.read()
                    if not ok:
                        break
                    if idx >= start and (idx - start) % step == 0:
                        yield self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
                    idx += 1
            finally:
                cap.release()

    def gray_proxy_frames(self, scale: float = 1.0, start: int = 0,
                          stop=None, step: int = 1):
        """Stream decoder-scaled 8-bit grayscale frames directly from FFmpeg.

        This avoids piping full-resolution RGB into Python merely to discard
        color channels and pixels. Source frame indices/timing are unchanged.
        """
        scale=float(scale)
        if scale<=0 or scale>1:raise ValueError("proxy scale must be in (0, 1]")
        try:
            import imageio_ffmpeg
            executable=imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            for i,frame in enumerate(self.frames(start=start,stop=stop,step=step)):
                gray=(frame[...,0] if frame.ndim==3 and frame.shape[2]==1 else
                      np.mean(frame[...,:3],axis=2).astype(np.uint8) if frame.ndim==3 else frame)
                stride=max(1,int(round(1.0/scale)));yield np.ascontiguousarray(gray[::stride,::stride])
            return
        out_w=max(2,int(round(self.width*scale)));out_h=max(2,int(round(self.height*scale)))
        command=[executable,"-hide_banner","-loglevel","error","-i",str(self.path),
                 "-vf",f"scale={out_w}:{out_h}:flags=area,format=gray",
                 "-f","rawvideo","-pix_fmt","gray","pipe:1"]
        flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                 stdin=subprocess.DEVNULL,creationflags=flags)
        frame_bytes=out_w*out_h;index=0
        try:
            while True:
                data=process.stdout.read(frame_bytes)
                if len(data)<frame_bytes:break
                if stop is not None and index>=stop:break
                if index>=start and (index-start)%step==0:
                    yield np.frombuffer(data,dtype=np.uint8).reshape(out_h,out_w).copy()
                index+=1
        finally:
            if process.poll() is None:process.terminate()
            try:process.wait(timeout=2)
            except Exception:process.kill()

    def sampled_gray_proxy_frames(self, indices, scale: float = 1.0):
        """Decode the movie but pipe only explicitly requested gray frames.

        FFmpeg must still inspect compressed frames between samples, but the
        Python process no longer receives and copies gigabytes of raw frames
        merely to retain a few whole-movie background samples.
        """
        wanted=sorted({int(i) for i in indices if 0<=int(i)<self.n_frames})
        if not wanted:
            return
        scale=float(scale)
        if scale<=0 or scale>1:
            raise ValueError("proxy scale must be in (0, 1]")
        try:
            import imageio_ffmpeg
            executable=imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            wanted_set=set(wanted)
            for index,frame in enumerate(self.gray_proxy_frames(scale)):
                if index in wanted_set:
                    yield frame
                if index>wanted[-1]:
                    break
            return
        out_w=max(2,int(round(self.width*scale)))
        out_h=max(2,int(round(self.height*scale)))
        expression="+".join(f"eq(n\\,{index})" for index in wanted)
        filters=f"select={expression},scale={out_w}:{out_h}:flags=area,format=gray"
        command=[executable,"-hide_banner","-loglevel","error","-i",str(self.path),
                 "-vf",filters,"-fps_mode","passthrough",
                 "-f","rawvideo","-pix_fmt","gray","pipe:1"]
        flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                 stdin=subprocess.DEVNULL,creationflags=flags)
        frame_bytes=out_w*out_h
        try:
            for _ in wanted:
                data=process.stdout.read(frame_bytes)
                if len(data)<frame_bytes:
                    break
                yield np.frombuffer(data,dtype=np.uint8).reshape(out_h,out_w).copy()
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=2)
            except Exception:
                process.kill()

    def close(self):
        if getattr(self, "_backend", None) == "cv2":
            try:
                self._cap.release()
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def open_movie(path: str | Path, *, exact_count: bool = True) -> Movie:
    """Open any supported source behind the uniform Movie interface.

    ``exact_count=False`` lets a compressed video open instantly with an
    approximate frame count instead of paying for a full decode pass (~123 s on
    a 126 MB 4K clip, vs ~3 s).  Only interactive/preview code should use it;
    call ``ensure_exact_n_frames()`` before anything that reaches a result.
    Non-video sources are always exact and ignore the flag.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    if path.is_dir():
        files = [f for f in sorted(glob.glob(str(path / "*")), key=_natural_key)
                 if Path(f).suffix.lower() in IMAGE_EXTS]
        if not files:
            raise ValueError(f"no image files in folder {path}")
        # a folder of multipage TIFFs is unusual; treat each file as one frame
        return ImageSequenceMovie(files, path)

    ext = path.suffix.lower()
    if ext in VIDEO_EXTS:
        return VideoMovie(path, exact_count=exact_count)
    if ext in TIFF_EXTS:
        return TiffMovie(path)
    if ext in IMAGE_EXTS:
        return ImageSequenceMovie([str(path)], path)
    raise ValueError(f"unsupported source type: {ext}")


def open_numbered_image_sequence(path: str | Path) -> Movie:
    """Open only the numbered series containing a selected still image.

    ``recording-0035.jpg`` selects ``recording-####.jpg`` and cannot silently
    concatenate another same-sized recording stored in the same directory.
    Non-numbered stills remain single images.
    """
    path = Path(path).resolve()
    match = re.match(r"^(.*?[-_])(\d+)$", path.stem)
    if not match:
        return open_movie(path)
    prefix = match.group(1)
    files = sorted(
        (candidate for candidate in path.parent.iterdir()
         if candidate.is_file()
         and candidate.suffix.lower() == path.suffix.lower()
         and re.fullmatch(re.escape(prefix)+r"\d+", candidate.stem)),
        key=lambda candidate: int(candidate.stem[len(prefix):]))
    if not files:
        return open_movie(path)
    return ImageSequenceMovie([str(candidate) for candidate in files], path.parent)


if __name__ == "__main__":
    import sys, json
    m = open_movie(sys.argv[1])
    print(json.dumps(m.summary(), indent=2))
    m.close()
