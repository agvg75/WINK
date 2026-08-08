"""Shared confocal stack loader: CZI / ND2 / LIF / OME-TIFF / TIFF folder.

Normalises every source format to ONE contract so downstream modules never
learn a vendor's quirks:

    array     (Z, C, Y, X) numpy array, source dtype preserved
    metadata  voxel_size_um (dz, dy, dx), channel names/wavelengths,
              objective, bit depth, source format/path, acquisition time,
              and the reader's full raw metadata blob for provenance

WHY THE CALIBRATION RULE IS A HARD STOP
---------------------------------------
A missing or zero physical calibration is an invalid state that stops the
load, exactly as Track one worm treats a missing scale - it is never a
silent "unknown scale" mode. Downstream length and volume numbers are
linear in these values, so a wrong voxel size produces plausible,
confidently wrong measurements.

In particular this loader NEVER infers dz from dy/dx. Measured on a real
Leica stack from this lab (240619_BZ33_day5A_crawl_phall_9.lif): dy = dx =
0.0545 um but dz = 0.1712 um, a 3.1x anisotropy. Assuming isotropic voxels
there would inflate every z distance by the same factor.

WHAT REAL FILES TAUGHT THIS MODULE
-----------------------------------
Checked against the lab's own confocal data before the contract was fixed:

* One .lif held **9 separate series** (paired raw and Lightning-deconvolved
  versions of several acquisitions). Loading "the file" without choosing a
  series would silently pick one arbitrary acquisition, so a multi-series
  file raises unless a series is named - see `list_series`.
* Series within one file had **different bit depths** (8-bit and 16-bit),
  so bit depth is per-series, never per-file.
* `readlif` reports scale as **pixels per micrometre**, the reciprocal of
  what this contract stores. Getting that backwards is silent and total.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

import numpy as np


class ConfocalLoadError(RuntimeError):
    """The stack cannot be loaded as asked."""


class ConfocalCalibrationError(ConfocalLoadError):
    """Physical voxel size is missing or non-physical.

    Deliberately its own type so a caller can catch exactly this case and
    prompt for manual entry, rather than having to distinguish it from a
    corrupt-file error by message text.
    """


SUFFIX_FORMATS = {
    ".lif": "lif", ".czi": "czi", ".nd2": "nd2",
    ".tif": "tiff", ".tiff": "tiff", ".ome.tif": "tiff", ".ome.tiff": "tiff",
}


@dataclass(frozen=True)
class SeriesInfo:
    """One addressable acquisition inside a container file."""
    index: int
    name: str
    shape_zcyx: tuple
    voxel_size_um: tuple | None
    bit_depth: int | None

    def describe(self):
        z, c, y, x = self.shape_zcyx
        vox = ("uncalibrated" if not self.voxel_size_um else
               "dz={:.4f} dy={:.4f} dx={:.4f} um".format(*self.voxel_size_um))
        return (f"[{self.index}] {self.name}  {z}z x {c}c x {y}y x {x}x  "
                f"{self.bit_depth or '?'}-bit  {vox}")


@dataclass
class ConfocalStack:
    array: np.ndarray                    # (Z, C, Y, X)
    metadata: dict = field(default_factory=dict)

    @property
    def voxel_size_um(self):
        return self.metadata.get("voxel_size_um")

    @property
    def n_z(self):
        return self.array.shape[0]

    @property
    def n_channels(self):
        return self.array.shape[1]

    def channel(self, index):
        """One channel as a (Z, Y, X) volume."""
        return self.array[:, index, :, :]

    def anisotropy(self):
        """dz / mean(dy, dx). Large values mean a true diagonal structure
        looks artificially segmented between z planes - report it as a
        preflight warning rather than silently resampling."""
        vox = self.voxel_size_um
        if not vox:
            return None
        dz, dy, dx = vox
        lateral = (dy + dx) / 2.0
        return float(dz / lateral) if lateral > 0 else None

    def preflight_warnings(self):
        """Conditions worth surfacing BEFORE analysis, each phrased as what
        was observed rather than as an instruction."""
        notes = []
        ratio = self.anisotropy()
        if ratio is not None and ratio >= 2.0:
            notes.append(
                f"Voxels are strongly anisotropic: z spacing is {ratio:.1f}x "
                f"the lateral pixel size. A neurite running diagonally will "
                f"look segmented between z planes.")
        declared = self.metadata.get("bit_depth")
        observed_max = int(self.array.max()) if self.array.size else 0
        if declared:
            theoretical = (1 << int(declared)) - 1
            # 12-bit data in a 16-bit container is common on Zeiss and Nikon
            # systems; the array dtype says 16 but nothing ever exceeds 4095.
            if observed_max and observed_max <= theoretical // 8:
                notes.append(
                    f"Intensities top out at {observed_max}, far below the "
                    f"{theoretical} a {declared}-bit image allows - the data "
                    f"may be lower bit depth stored in a wider container.")
            # THE ABOVE MISSES THE OTHER WAY A CONTAINER LIES. Data that has
            # been LEFT-SHIFTED into the wider word does reach the top of the
            # range, so the maximum looks correct, while only every Nth code
            # occurs. Detectable only from the step between adjacent codes.
            # Found on this lab's own transmitted-light recordings: 8-bit data
            # in 16-bit words, stepping by 128.
            try:
                unique = np.unique(self.array)
                step = int(np.min(np.diff(unique))) if unique.size > 1 else 1
            except Exception:
                step = 1
            if step > 1:
                effective = int(declared) - int(round(np.log2(step)))
                notes.append(
                    f"Intensity codes step by {step} rather than 1, so this "
                    f"is about {effective}-bit data left-shifted into a "
                    f"{declared}-bit container. It reaches the top of the "
                    f"range, so a maximum-based check sees nothing wrong, but "
                    f"only {unique.size} distinct values exist. Any threshold "
                    f"or ratio derived from the declared depth is optimistic.")
        for note in (self.metadata.get("raw_metadata_blob") or {}).get("axis_notes", []):
            notes.append(note)
        if self.metadata.get("calibration_source") == "manual":
            notes.append("Voxel size was entered by hand, not read from the "
                         "file's own metadata.")
        return notes


# ---------------------------------------------------------------------------
# format detection
# ---------------------------------------------------------------------------
def detect_format(path):
    """The format, or None. A DIRECTORY IS NOT A FORMAT BY ITSELF.

    This used to return "tiff_folder" for any directory, which made
    "tiff_folder" the shape of "everything else" rather than a thing that was
    detected. Now it is content-based: a directory is a TIFF folder when it
    CONTAINS TIFFs, and otherwise nothing is claimed about it.
    """
    path = Path(path)
    if path.is_dir():
        try:
            return "tiff_folder" if _sequence_files(path) else None
        except OSError:
            return None
    name = path.name.lower()
    for suffix in (".ome.tif", ".ome.tiff"):
        if name.endswith(suffix):
            return "tiff"
    return SUFFIX_FORMATS.get(path.suffix.lower())


def describe_unreadable(path):
    """What was actually measured about a path we cannot read.

    A refusal that only says "unsupported" sends the reader to guess. This
    reports the evidence the decision was made on.
    """
    path = Path(path)
    if not path.exists():
        return "the path does not exist"
    if path.is_dir():
        try:
            tiffs = len(_sequence_files(path))
        except OSError as exc:
            return f"directory could not be listed ({exc})"
        try:
            entries = sum(1 for _ in path.iterdir())
        except OSError:
            entries = -1
        return (f"directory holding {entries:,} entries, of which {tiffs} "
                f"are .tif/.tiff")
    return (f"file with suffix {path.suffix.lower()!r}; known suffixes are "
            f"{', '.join(sorted(SUFFIX_FORMATS))}")


def _validated_voxel(dz, dy, dx, source):
    """Reject a calibration rather than pass a silent zero downstream."""
    values = (dz, dy, dx)
    if any(v is None for v in values):
        return None
    values = tuple(float(v) for v in values)
    if any(not np.isfinite(v) or v <= 0 for v in values):
        raise ConfocalCalibrationError(
            f"{source} reports a non-physical voxel size {values}. A zero or "
            "negative spacing cannot be used; supply voxel_size_um manually.")
    return values


# ---------------------------------------------------------------------------
# per-format series listing
# ---------------------------------------------------------------------------
def list_series(path):
    """Every addressable acquisition in the file, without loading pixels.

    Container formats routinely bundle several acquisitions (and often a
    raw + deconvolved pair of each). Callers should show this and let a
    person choose.
    """
    fmt = detect_format(path)
    if fmt == "lif":
        return _list_series_lif(path)
    if fmt == "czi":
        return _list_series_czi(path)
    if fmt == "nd2":
        return _list_series_nd2(path)
    if fmt in ("tiff", "tiff_folder"):
        return _list_series_tiff(path, fmt)
    raise ConfocalLoadError(f"Unsupported confocal format: {path}")


def _list_series_lif(path):
    from readlif.reader import LifFile
    out = []
    lif = LifFile(str(path))
    for i, image in enumerate(lif.get_iter_image()):
        dims = image.dims
        # readlif reports scale as PIXELS PER MICROMETRE - the reciprocal of
        # what this module stores. Inverting this is silent and total.
        sx, sy, sz = (image.scale + (None, None, None))[:3]
        vox = _validated_voxel(
            1.0 / sz if sz else None, 1.0 / sy if sy else None,
            1.0 / sx if sx else None, "readlif")
        depths = image.bit_depth or ()
        out.append(SeriesInfo(
            index=i, name=str(image.name),
            shape_zcyx=(int(dims.z), int(image.channels), int(dims.y), int(dims.x)),
            voxel_size_um=vox,
            bit_depth=int(depths[0]) if depths else None))
    return out


def _list_series_czi(path):
    import czifile
    with czifile.CziFile(str(path)) as czi:
        axes = czi.axes
        shape = dict(zip(axes, czi.shape))
        vox = _czi_voxel(czi)
        depth = _bits_from_dtype(czi.dtype)
        name = Path(path).stem
        # czifile exposes scenes on the S axis when a file holds several.
        n_scenes = int(shape.get("S", 1))
        return [SeriesInfo(
            index=i, name=(f"{name} scene {i}" if n_scenes > 1 else name),
            shape_zcyx=(int(shape.get("Z", 1)), int(shape.get("C", 1)),
                        int(shape.get("Y", 1)), int(shape.get("X", 1))),
            voxel_size_um=vox, bit_depth=depth) for i in range(n_scenes)]


def _czi_voxel(czi):
    """Zeiss stores scaling in metres under Scaling/Items/Distance."""
    try:
        meta = czi.metadata(raw=False)
    except Exception:
        return None
    found = {}

    def walk(node):
        if isinstance(node, dict):
            if node.get("Id") in ("X", "Y", "Z") and "Value" in node:
                try:
                    found[node["Id"]] = float(node["Value"]) * 1e6  # m -> um
                except (TypeError, ValueError):
                    pass
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    walk(meta)
    return _validated_voxel(found.get("Z"), found.get("Y"), found.get("X"), "czifile")


def _list_series_nd2(path):
    import nd2
    with nd2.ND2File(str(path)) as f:
        sizes = dict(f.sizes)
        vox = None
        try:
            v = f.voxel_size()      # nd2 returns (x, y, z) in micrometres
            vox = _validated_voxel(v.z, v.y, v.x, "nd2")
        except Exception:
            vox = None
        depth = int(getattr(f.attributes, "bitsPerComponentSignificant", 0)) or \
            _bits_from_dtype(f.dtype)
        n_pos = int(sizes.get("P", 1))
        name = Path(path).stem
        return [SeriesInfo(
            index=i, name=(f"{name} position {i}" if n_pos > 1 else name),
            shape_zcyx=(int(sizes.get("Z", 1)), int(sizes.get("C", 1)),
                        int(sizes.get("Y", 1)), int(sizes.get("X", 1))),
            voxel_size_um=vox, bit_depth=depth) for i in range(n_pos)]


def _list_series_tiff(path, fmt):
    import tifffile
    if fmt == "tiff_folder":
        files = _sequence_files(path)
        if not files:
            raise ConfocalLoadError(f"No TIFF files found in {path}")
        with tifffile.TiffFile(str(files[0])) as tif:
            page = tif.pages[0]
            y, x = int(page.imagelength), int(page.imagewidth)
            depth = _bits_from_dtype(page.dtype)
        return [SeriesInfo(index=0, name=Path(path).name,
                           shape_zcyx=(len(files), 1, y, x),
                           voxel_size_um=None, bit_depth=depth)]
    with tifffile.TiffFile(str(path)) as tif:
        series = tif.series[0]
        # Map unlabelled axes the same way the loader does, so the listing
        # cannot advertise 1 z plane for a stack the loader reads as 45.
        axes = _label_unlabelled(series.axes)
        shape = dict(zip(axes, series.shape))
        vox = _ome_voxel(tif)
        return [SeriesInfo(
            index=i, name=f"{Path(path).stem} series {i}" if len(tif.series) > 1
            else Path(path).stem,
            shape_zcyx=(int(shape.get("Z", 1)), int(shape.get("C", 1)),
                        int(shape.get("Y", 1)), int(shape.get("X", 1))),
            voxel_size_um=vox,
            bit_depth=_bits_from_dtype(series.dtype))
            for i in range(len(tif.series))]


def _label_unlabelled(axes):
    """Positional Z-then-C naming for axes the file does not identify, kept
    consistent with _to_zcyx so listing and loading never disagree."""
    axes = list(axes)
    for i, a in enumerate(axes):
        if a in _SAMPLE_AXES and "C" not in axes:
            axes[i] = "C"
    for i, a in enumerate(axes):
        if a in _UNLABELLED_AXES:
            for target in ("Z", "C"):
                if target not in axes:
                    axes[i] = target
                    break
    return "".join(axes)


def _ome_voxel(tif):
    if not getattr(tif, "ome_metadata", None):
        return None
    text = tif.ome_metadata
    def grab(attr):
        m = re.search(rf'{attr}="([0-9.eE+-]+)"', text)
        return float(m.group(1)) if m else None
    return _validated_voxel(grab("PhysicalSizeZ"), grab("PhysicalSizeY"),
                            grab("PhysicalSizeX"), "OME-TIFF")


def _sequence_files(folder):
    exts = {".tif", ".tiff"}
    return sorted(p for p in Path(folder).iterdir()
                  if p.is_file() and p.suffix.lower() in exts)


def _bits_from_dtype(dtype):
    try:
        return int(np.dtype(dtype).itemsize * 8)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------
def load_stack(path, series=None, voxel_size_um=None, require_calibration=True,
               expected_z=None):
    """Load one acquisition as a (Z, C, Y, X) stack plus metadata.

    `series` must be given when the file holds more than one acquisition -
    silently taking the first would mean analysing whichever acquisition
    happened to be saved first, which for a paired raw/deconvolved file is
    a coin flip.

    `voxel_size_um` (dz, dy, dx) supplies calibration the file does not
    carry. With `require_calibration` left True, a stack with neither is
    refused rather than loaded uncalibrated.

    `expected_z` lets a caller state how many planes the acquisition was
    supposed to have; a mismatch is reported rather than silently accepted,
    which is how an interrupted acquisition otherwise passes as complete.
    """
    path = Path(path)
    fmt = detect_format(path)
    if fmt is None:
        raise ConfocalLoadError(
            f"Unsupported confocal format: {path}\n"
            f"  {describe_unreadable(path)}")

    available = list_series(path)
    if series is None:
        if len(available) > 1:
            listing = "\n  ".join(s.describe() for s in available)
            raise ConfocalLoadError(
                f"{path.name} holds {len(available)} series. Choose one "
                f"explicitly - loading the first would pick an arbitrary "
                f"acquisition.\n  {listing}")
        series = 0
    if not any(s.index == series for s in available):
        raise ConfocalLoadError(
            f"Series {series} does not exist in {path.name} "
            f"({len(available)} available).")
    info = next(s for s in available if s.index == series)

    if fmt == "lif":
        array, raw = _read_lif(path, series)
    elif fmt == "czi":
        array, raw = _read_czi(path, series)
    elif fmt == "nd2":
        array, raw = _read_nd2(path, series)
    elif fmt == "tiff":
        array, raw = _read_tiff(path, series)
    elif fmt == "tiff_folder":
        array, raw = _read_tiff_folder(path)
    else:
        # THE TERMINAL RAISE. This branch was `else: _read_tiff_folder(path)`,
        # so "tiff folder" was the shape of everything unrecognised rather
        # than a format that had been detected. Nothing has been mis-read:
        # `fmt is None` already raises above, and the only value that could
        # reach here was tiff_folder. But adding one entry to SUFFIX_FORMATS
        # would have been enough - an Olympus .oib would have been opened as
        # a folder of TIFFs, and the failure would have named TIFFs rather
        # than the format nobody wired up.
        raise ConfocalLoadError(
            f"Confocal format {fmt!r} is detected but has no reader: "
            f"{path}\n  {describe_unreadable(path)}")

    vox = _validated_voxel(*voxel_size_um, "manual entry") if voxel_size_um \
        else info.voxel_size_um
    calibration_source = ("manual" if voxel_size_um else
                          ("file_metadata" if info.voxel_size_um else None))
    if vox is None and require_calibration:
        raise ConfocalCalibrationError(
            f"{path.name} (series {series}) carries no physical voxel size. "
            "Supply voxel_size_um=(dz, dy, dx) in micrometres. Do NOT assume "
            "isotropic voxels from the lateral pixel size - confocal z "
            "spacing is routinely several times the lateral spacing.")

    truncated = None
    if expected_z is not None and int(expected_z) != array.shape[0]:
        truncated = (f"Expected {int(expected_z)} z planes, found "
                     f"{array.shape[0]} - the acquisition may have been "
                     f"interrupted.")

    metadata = {
        "voxel_size_um": vox,
        "calibration_source": calibration_source,
        "channel_names": raw.get("channel_names"),
        "channel_wavelengths_nm": raw.get("channel_wavelengths_nm"),
        "objective": raw.get("objective"),
        "bit_depth": info.bit_depth,
        "source_format": fmt,
        "source_path": str(path),
        "series_index": series,
        "series_name": info.name,
        "n_series_in_file": len(available),
        "acquisition_datetime": raw.get("acquisition_datetime"),
        "truncation_note": truncated,
        "raw_metadata_blob": raw,
    }
    return ConfocalStack(array=array, metadata=metadata)


def _read_lif(path, series):
    from readlif.reader import LifFile
    lif = LifFile(str(path))
    image = list(lif.get_iter_image())[series]
    dims = image.dims
    planes = []
    for z in range(int(dims.z)):
        chans = [np.asarray(image.get_frame(z=z, t=0, c=c))
                 for c in range(int(image.channels))]
        planes.append(np.stack(chans, axis=0))
    array = np.stack(planes, axis=0)          # (Z, C, Y, X)
    raw = {"reader": "readlif", "series_name": str(image.name),
           "dims": str(dims), "channels": int(image.channels),
           "bit_depth": list(image.bit_depth or ()),
           "scale_px_per_um": list(image.scale or ()),
           "settings": dict(getattr(image, "settings", {}) or {})}
    raw["objective"] = raw["settings"].get("ObjectiveName")
    return array, raw


def _read_czi(path, series):
    import czifile
    notes = []
    with czifile.CziFile(str(path)) as czi:
        data = czi.asarray()
        axes = czi.axes
        array = _to_zcyx(data, axes, scene=series if "S" in axes else None,
                         notes=notes)
        raw = {"reader": "czifile", "axes": axes, "shape": list(czi.shape),
               "axis_notes": notes}
    return array, raw


def _read_nd2(path, series):
    import nd2
    with nd2.ND2File(str(path)) as f:
        data = f.asarray()
        axes = "".join(f.sizes.keys())
        notes = []
        array = _to_zcyx(data, axes, scene=series if "P" in f.sizes else None,
                         scene_axis="P", notes=notes)
        chans = []
        try:
            chans = [c.channel.name for c in f.metadata.channels]
        except Exception:
            pass
        raw = {"reader": "nd2", "sizes": dict(f.sizes),
               "channel_names": chans or None, "axis_notes": notes}
    return array, raw


def _read_tiff(path, series):
    import tifffile
    notes = []
    with tifffile.TiffFile(str(path)) as tif:
        s = tif.series[series]
        array = _to_zcyx(s.asarray(), s.axes, notes=notes)
        raw = {"reader": "tifffile", "axes": s.axes, "axis_notes": notes,
               "is_ome": bool(getattr(tif, "ome_metadata", None))}
    return array, raw


def _read_tiff_folder(path):
    import tifffile
    files = _sequence_files(path)
    planes = [tifffile.imread(str(f)) for f in files]
    stack = np.stack(planes, axis=0)
    if stack.ndim == 3:                       # (Z, Y, X) -> one channel
        stack = stack[:, None, :, :]
    elif stack.ndim == 4:                     # (Z, Y, X, C) -> (Z, C, Y, X)
        stack = np.moveaxis(stack, -1, 1)
    raw = {"reader": "tifffile(folder)", "n_files": len(files),
           "first_file": str(files[0]) if files else None}
    return stack, raw


# Axis letters that carry no meaning of their own. tifffile labels any
# unidentified axis "Q" (and "I" for a plain page index), which is what a
# plain multipage TIFF - the most common way a z stack gets exported - looks
# like. "S" is a sample/component axis, i.e. RGB-style channels.
_UNLABELLED_AXES = ("Q", "I")
_SAMPLE_AXES = ("S",)
# Axes this contract genuinely does not model. Collapsing these to their
# first element is a real narrowing, so it is reported, never silent.
_COLLAPSIBLE_AXES = ("T", "M", "R", "H", "V")


def _to_zcyx(data, axes, scene=None, scene_axis="S", notes=None):
    """Reorder an arbitrary vendor axis order into (Z, C, Y, X).

    Unlabelled axes are mapped positionally to Z then C rather than being
    collapsed. That mapping matters: a plain multipage TIFF reports its
    pages as "QYX", and collapsing Q took the FIRST PLANE ONLY - a 45-plane
    z stack silently became a single image, with every downstream depth
    measurement quietly meaningless. Whether those pages are really z or
    really time is not knowable from such a file, so the assumption is
    recorded in `notes` and surfaced as a preflight warning instead of
    being made silently.
    """
    data = np.asarray(data)
    axes = list(axes)
    notes = notes if notes is not None else []

    if scene is not None and scene_axis in axes:
        idx = axes.index(scene_axis)
        data = np.take(data, scene, axis=idx)
        axes.pop(idx)

    # Sample axes are channels.
    for i, a in enumerate(axes):
        if a in _SAMPLE_AXES and "C" not in axes:
            axes[i] = "C"

    # Map unlabelled axes positionally onto whichever of Z, C is still free.
    for i, a in enumerate(axes):
        if a in _UNLABELLED_AXES:
            for target in ("Z", "C"):
                if target not in axes:
                    axes[i] = target
                    notes.append(
                        f"An unlabelled axis of length {data.shape[i]} was "
                        f"read as {target}. The file does not say what it is "
                        f"- if these are timepoints rather than "
                        f"{'z planes' if target == 'Z' else 'channels'}, "
                        f"this stack is being misread.")
                    break

    # Anything still unmodelled (time, mosaic tiles) collapses to its first
    # element - reported, because it discards data.
    for extra in [a for a in axes if a not in ("Z", "C", "Y", "X")]:
        idx = axes.index(extra)
        length = data.shape[idx]
        data = np.take(data, 0, axis=idx)
        axes.pop(idx)
        if length > 1:
            notes.append(
                f"Axis '{extra}' has {length} entries; only the first was "
                f"loaded. This loader models one (Z, C, Y, X) stack at a time.")

    for missing in ("Z", "C"):
        if missing not in axes:
            data = np.expand_dims(data, 0)
            axes.insert(0, missing)
    order = [axes.index(a) for a in ("Z", "C", "Y", "X")]
    return np.transpose(data, order)
