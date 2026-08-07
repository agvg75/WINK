"""Frame rate, size and frame count from a movie header. No decoder, no cv2.

WHY THIS EXISTS. The eligibility pass has to read the frame rate of every
recording on a 16 TB drive, and frame rate is the threshold the whole pass
classifies against. The obvious route is cv2.VideoCapture - but cv2 IS NOT
INSTALLED in the lab runtime and adding it would enlarge what the lab ships
to fix one script. The repo already has the precedent: xlsx_lite.py exists
because openpyxl is not there either.

It is also simply faster. An AVI states its frame rate in a fixed structure
in the first few hundred bytes; opening a decoder to ask the same question
reads and initialises far more.

NOTHING IS ASSUMED. Every field returned was read from the file. Where a
header does not carry a value the value is None, and callers must treat that
as "not recorded" rather than substituting a default - a frame rate that was
guessed would make every downstream verdict a guess wearing a number.

FORMATS

  .avi   RIFF. The `avih` chunk gives microseconds per frame, dimensions and
         a total frame count; the video stream's `strh` gives rate/scale,
         which is the more precise figure and is preferred. `strf` carries
         the bit depth. OpenDML files above 4 GB keep the true frame count
         in `dmlh`, because the avih field is only 32 bits - that is read
         where present, since this archive has files far over 4 GB.

  .mp4   ISO base media. `mvhd` gives a timescale and duration; the video
  .mov   track's `mdhd` and `stsz`/`stts` give the frame count. Handled at
         the container level only.

  .tif   Delegated to tifffile, which is installed, since a TIFF stack's
         page count is its frame count and tifffile reads pages lazily.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path


class MovieHeaderError(Exception):
    """Refusals that name what could not be read."""


def _blank(path):
    return {
        "path": str(path),
        "ext": Path(path).suffix.lower(),
        "fps": None,
        "frames": None,
        "width": None,
        "height": None,
        "duration_s": None,
        "bit_depth": None,
        "channels": None,
        "codec": "",
        "read": False,
        "note": "",
    }


# ----------------------------------------------------------------- AVI ----
def _avi(path, out):
    """RIFF walk. Reads chunk headers and skips every payload."""
    with open(path, "rb") as fh:
        if fh.read(4) != b"RIFF":
            raise MovieHeaderError(f"{Path(path).name} is not a RIFF file")
        fh.read(4)
        if fh.read(4) != b"AVI ":
            raise MovieHeaderError(f"{Path(path).name} is RIFF but not AVI")

        stream_kind = None
        end = os.path.getsize(path)

        while fh.tell() + 8 <= end:
            header = fh.read(8)
            if len(header) < 8:
                break
            fourcc, size = struct.unpack("<4sI", header)
            start = fh.tell()

            if fourcc == b"LIST":
                # Descend into lists rather than skipping them: hdrl, strl
                # and odml all nest, and the fields wanted are inside.
                fh.read(4)
                continue

            if fourcc == b"avih" and size >= 40:
                fields = struct.unpack("<10I", fh.read(40))
                micros, frames = fields[0], fields[4]
                out["width"], out["height"] = fields[8], fields[9]
                if micros:
                    out["fps"] = round(1_000_000.0 / micros, 6)
                if frames:
                    out["frames"] = frames

            elif fourcc == b"strh" and size >= 40:
                body = fh.read(min(size, 56))
                kind = body[0:4]
                if kind == b"vids":
                    stream_kind = kind
                    scale, rate = struct.unpack("<II", body[20:28])
                    length = struct.unpack("<I", body[32:36])[0]
                    if scale:
                        # rate/scale is exact where micros-per-frame was
                        # rounded to a whole microsecond.
                        out["fps"] = round(rate / scale, 6)
                    if length:
                        out["frames"] = length

            elif fourcc == b"strf" and stream_kind == b"vids" and size >= 40:
                body = fh.read(40)
                width, height = struct.unpack("<ii", body[4:12])
                planes, bits = struct.unpack("<HH", body[12:16])
                codec = body[16:20]
                out["width"] = out["width"] or abs(width)
                out["height"] = out["height"] or abs(height)
                out["bit_depth"] = bits or None
                # 8 bits per pixel is one channel; 24 is three.
                out["channels"] = max(1, bits // 8) if bits else None
                out["codec"] = codec.decode("ascii", "replace").strip("\x00 ")
                stream_kind = None

            elif fourcc == b"dmlh" and size >= 4:
                # OpenDML. avih's frame count is 32 bits and wrong past 4 GB.
                total = struct.unpack("<I", fh.read(4))[0]
                if total:
                    out["frames"] = total

            fh.seek(start + size + (size & 1))

    if out["fps"] and out["frames"]:
        out["duration_s"] = round(out["frames"] / out["fps"], 3)
    out["read"] = out["fps"] is not None or out["frames"] is not None
    return out


# ------------------------------------------------------------ ISO BMFF ----
def _boxes(fh, end):
    """Yield (type, payload_start, payload_end) for boxes in a range."""
    while fh.tell() + 8 <= end:
        start = fh.tell()
        header = fh.read(8)
        if len(header) < 8:
            return
        size, kind = struct.unpack(">I4s", header)
        if size == 1:                       # 64-bit extended size
            size = struct.unpack(">Q", fh.read(8))[0]
            body = start + 16
        elif size == 0:                     # runs to end of file
            size = end - start
            body = start + 8
        else:
            body = start + 8
        if size < 8:
            return
        yield kind, body, start + size
        fh.seek(start + size)


def _mp4(path, out):
    size_total = os.path.getsize(path)
    with open(path, "rb") as fh:
        moov = None
        for kind, body, stop in _boxes(fh, size_total):
            if kind == b"moov":
                moov = (body, stop)
                break
        if not moov:
            raise MovieHeaderError(
                f"{Path(path).name} has no moov box, so it carries no "
                f"timing - it may be a fragmented or truncated file")

        fh.seek(moov[0])
        for kind, body, stop in _boxes(fh, moov[1]):
            if kind == b"mvhd":
                fh.seek(body)
                version = struct.unpack(">B", fh.read(1))[0]
                fh.read(3)
                if version == 1:
                    fh.read(16)
                    scale, duration = struct.unpack(">IQ", fh.read(12))
                else:
                    fh.read(8)
                    scale, duration = struct.unpack(">II", fh.read(8))
                if scale:
                    out["duration_s"] = round(duration / scale, 3)
            elif kind == b"trak":
                _mp4_track(fh, body, stop, out)
            fh.seek(stop)

    if out["frames"] and out["duration_s"]:
        out["fps"] = round(out["frames"] / out["duration_s"], 6)
    out["read"] = out["fps"] is not None or out["frames"] is not None
    return out


def _mp4_track(fh, start, stop, out):
    fh.seek(start)
    for kind, body, end in _boxes(fh, stop):
        if kind in (b"mdia", b"minf", b"stbl"):
            _mp4_track(fh, body, end, out)     # descend
        elif kind == b"tkhd":
            fh.seek(body)
            version = struct.unpack(">B", fh.read(1))[0]
            fh.read(3)
            fh.read(sizes := 20 if version == 1 else 12)
            fh.read(60)
            width, height = struct.unpack(">II", fh.read(8))
            if width and height:
                out["width"] = out["width"] or width >> 16
                out["height"] = out["height"] or height >> 16
        elif kind == b"stsz":
            fh.seek(body + 8)
            count = struct.unpack(">I", fh.read(4))[0]
            if count:
                out["frames"] = count
        fh.seek(end)


# ---------------------------------------------------------------- TIFF ----
def _tiff(path, out):
    try:
        import tifffile
    except ImportError as exc:
        raise MovieHeaderError(
            f"tifffile is needed to read {Path(path).name} and is not "
            f"installed") from exc
    with tifffile.TiffFile(path) as handle:
        page = handle.pages[0]
        out["frames"] = len(handle.pages)
        out["width"] = int(page.imagewidth)
        out["height"] = int(page.imagelength)
        out["bit_depth"] = int(page.bitspersample) \
            if isinstance(page.bitspersample, int) else None
        out["channels"] = int(page.samplesperpixel)
        # A TIFF stack states no frame rate. That is not a failure and it
        # must not be filled in - it is why the acquisition standard asks
        # for the rate to be recorded alongside.
        out["note"] = "TIFF carries no frame rate"
    out["read"] = True
    return out


READERS = {
    ".avi": _avi,
    ".mp4": _mp4, ".mov": _mp4, ".m4v": _mp4,
    ".tif": _tiff, ".tiff": _tiff,
}


def read_header(path):
    """Everything the file states about itself, without decoding a frame."""
    out = _blank(path)
    reader = READERS.get(out["ext"])
    if reader is None:
        out["note"] = f"no header reader for {out['ext']}"
        return out
    try:
        return reader(path, out)
    except MovieHeaderError as exc:
        out["note"] = str(exc)
        return out
    except (OSError, struct.error, ValueError) as exc:
        out["note"] = f"{type(exc).__name__}: {exc}"
        return out
