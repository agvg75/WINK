"""Muscle boundary marks: the sidecar, and the volume computed from it.

See docs/specs/muscle_boundary_volume_spec.md.

A body-wall muscle layer is a gently concave sheet, so its volume is taken
between two marked surfaces rather than from a solid mask. Marking is
deliberately SPARSE: a student marks the structure's inflection points and this
interpolates between them, which keeps the work proportionate to the shape
rather than to the number of planes.

Two things follow from that and are load-bearing:

  * Volume is reported over the marked extent ONLY. That is the normal case, not
    a warning - but integrating outside it, because the shape looked simple,
    would be inventing structure nobody judged.
  * Interpolation is a core component, not a fallback. Linear, and named on every
    output: anything smoother invents curvature between the very points the
    student was careful to place.

This module measures; it draws nothing. Marking happens in the viewer and writes
the sidecar, so the volume can be recomputed on any station, months later, with
different settings, without anyone re-marking - the same split as
neurite_annotation / neurite_trace_runner and for the same reasons.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SCHEMA_VERSION = 1
SIDECAR_SUFFIX = "_muscle_boundaries.json"

# Anatomical, not defect-driven. A worm is a cylinder and the muscle occupies one
# layer of it, but a stack images the whole cylinder - so structure above and
# below is imported into the field and contaminates it. Excluding it is normal
# practice rather than an admission that something went wrong.
EXCLUSION_REASONS = (
    "out_of_layer_above",
    "out_of_layer_below",
    "pharynx",
    "neuron",
    "other_structure",
    "unclear",
)
INTERPOLATION = "linear"


class BoundaryError(RuntimeError):
    """Raised with a message naming the consequence, not the errno."""


@dataclass
class Surface:
    """One marked boundary on one z plane. Points are full-resolution (x, y)."""
    surface: str                      # "upper" | "lower"
    z: int
    points: list = field(default_factory=list)


@dataclass
class Exclusion:
    """A region omitted from the measurement, with why."""
    z: int
    polygon: list = field(default_factory=list)
    reason: str = "unclear"
    note: str = ""


@dataclass
class Region:
    """One named muscle region within a stack. A stack yields several."""
    name: str
    channel: int = 0
    surfaces: list = field(default_factory=list)
    exclusions: list = field(default_factory=list)

    def marked_planes(self, surface):
        return sorted(int(s.z) for s in self.surfaces
                      if s.surface == surface and len(s.points) >= 2)


# --------------------------------------------------------------------------- #
# Sidecar
# --------------------------------------------------------------------------- #
def stack_identity(stack_path, series_index, shape_zcyx, voxel_size_um):
    """A fingerprint the marks are valid against.

    Same construction as neurite_annotation.stack_identity, deliberately: name,
    series, shape and calibration rather than a content hash, because hashing a
    multi-gigabyte stack on every load is slow enough that people switch it off.
    """
    payload = {
        "name": Path(stack_path).name,
        "series_index": int(series_index),
        "shape_zcyx": [int(v) for v in shape_zcyx],
        "voxel_size_um": [round(float(v), 9) for v in voxel_size_um]
        if voxel_size_um else None,
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return {"fingerprint": hashlib.sha256(blob).hexdigest()[:16], **payload}


def sidecar_path(stack_path, series_index=0):
    stack_path = Path(stack_path)
    return stack_path.with_name(
        f"{stack_path.stem}_series{int(series_index)}{SIDECAR_SUFFIX}")


def _station_name():
    try:
        return socket.gethostname()
    except Exception:
        return os.environ.get("COMPUTERNAME", "unknown")


def save_regions(path, identity, regions, station=None):
    """Write the sidecar. Never writes pixel data."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "written_utc": datetime.now(timezone.utc).isoformat(),
        "written_on_station": station or _station_name(),
        "stack_identity": identity,
        "exclusion_vocabulary": list(EXCLUSION_REASONS),
        "regions": [asdict(r) for r in regions],
    }
    path = Path(path)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_regions(path, identity=None, strict=True):
    """Read a sidecar, optionally checking it belongs to this stack."""
    path = Path(path)
    if not path.is_file():
        raise BoundaryError(f"No muscle boundary sidecar at {path}.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if identity is not None:
        stored = payload.get("stack_identity", {})
        if stored.get("fingerprint") != identity.get("fingerprint"):
            message = (
                f"This sidecar was marked against a different stack.\n"
                f"  marked:  {stored.get('name')} series "
                f"{stored.get('series_index')} shape {stored.get('shape_zcyx')} "
                f"voxel {stored.get('voxel_size_um')}\n"
                f"  loading: {identity.get('name')} series "
                f"{identity.get('series_index')} shape "
                f"{identity.get('shape_zcyx')} voxel "
                f"{identity.get('voxel_size_um')}\n"
                f"Measuring through boundaries marked on another acquisition "
                f"would return a confident volume for a shape nobody marked.")
            if strict:
                raise BoundaryError(message)
            payload["identity_warning"] = message
    regions = []
    for r in payload.get("regions", []):
        regions.append(Region(
            name=r.get("name", "region"),
            channel=int(r.get("channel", 0)),
            surfaces=[Surface(**s) for s in r.get("surfaces", [])],
            exclusions=[Exclusion(**e) for e in r.get("exclusions", [])]))
    return regions, payload


# --------------------------------------------------------------------------- #
# The slab model
# --------------------------------------------------------------------------- #
def _surface_curve(region, surface, width):
    """Each marked plane's boundary as a height profile over x, or None.

    Returns {z: array(width)} where the array holds the marked y at each x
    within the marked lateral extent and NaN outside it. Outside is NaN rather
    than an edge value on purpose: the student bounded a region, and filling
    past that edge would invent structure they did not judge.
    """
    out = {}
    for s in region.surfaces:
        if s.surface != surface or len(s.points) < 2:
            continue
        pts = np.asarray(s.points, dtype=float)
        order = np.argsort(pts[:, 0])
        xs, ys = pts[order, 0], pts[order, 1]
        grid = np.full(int(width), np.nan)
        lo, hi = int(np.ceil(xs.min())), int(np.floor(xs.max()))
        if hi < lo:
            continue
        cols = np.arange(max(0, lo), min(int(width), hi + 1))
        if cols.size:
            grid[cols] = np.interp(cols, xs, ys)
        out[int(s.z)] = grid
    return out


def _interpolate_between_planes(curves, width):
    """Fill the z planes BETWEEN marked ones. Linear, and only between.

    Marking is sparse by design, so this is the normal path, not a repair. It
    never extends past the outermost marked plane: beyond that the shape is
    unknown, and a smooth continuation would look exactly like a measurement.
    """
    if not curves:
        return {}
    zs = sorted(curves)
    filled = {z: curves[z].copy() for z in zs}
    for lo, hi in zip(zs, zs[1:]):
        span = hi - lo
        if span <= 1:
            continue
        a, b = curves[lo], curves[hi]
        for z in range(lo + 1, hi):
            t = (z - lo) / float(span)
            filled[z] = a * (1.0 - t) + b * t     # NaN in either -> NaN out
    return filled


def _exclusion_mask(region, z, shape_yx):
    """Boolean mask of everything excluded on plane z."""
    mask = np.zeros(shape_yx, dtype=bool)
    for e in region.exclusions:
        if int(e.z) != int(z) or len(e.polygon) < 3:
            continue
        poly = np.asarray(e.polygon, dtype=float)
        try:
            from skimage.draw import polygon2mask
            mask |= polygon2mask(shape_yx, np.column_stack([poly[:, 1],
                                                            poly[:, 0]]))
        except Exception:
            ys = np.clip(poly[:, 1].astype(int), 0, shape_yx[0] - 1)
            xs = np.clip(poly[:, 0].astype(int), 0, shape_yx[1] - 1)
            mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1] = True
    return mask


def measure_region(region, shape_zcyx, voxel_size_um):
    """Volume between the two marked surfaces, in cubic micrometres.

    voxel_size_um is (z, y, x) from the loader's metadata and is the ONLY source
    of physical scale - volume goes as the CUBE of lateral scale, so a defaulted
    value is wrong by a large factor and looks entirely plausible.
    """
    nz, _, ny, nx = [int(v) for v in shape_zcyx]
    upper_marked = region.marked_planes("upper")
    lower_marked = region.marked_planes("lower")
    if not upper_marked or not lower_marked:
        raise BoundaryError(
            f"Region '{region.name}' has "
            f"{'no upper' if not upper_marked else 'no lower'} boundary. "
            f"A slab needs both surfaces; one surface bounds nothing and a "
            f"volume computed from it would be arbitrary.")

    upper = _interpolate_between_planes(_surface_curve(region, "upper", nx), nx)
    lower = _interpolate_between_planes(_surface_curve(region, "lower", nx), nx)

    # Only planes where BOTH surfaces are known. The marked extent is the
    # intersection, not the union.
    zs = sorted(set(upper) & set(lower))
    if not zs:
        raise BoundaryError(
            f"Region '{region.name}' has upper boundaries on planes "
            f"{upper_marked} and lower on {lower_marked}, which do not overlap. "
            f"Volume can only be measured where both surfaces are known.")

    vz, vy, vx = (float(voxel_size_um[0]), float(voxel_size_um[1]),
                  float(voxel_size_um[2]))
    voxel_column_um2 = vx * vy

    included = excluded = 0.0
    crossings = []
    excluded_reasons = {}
    for z in zs:
        thickness = upper[z] - lower[z]              # in pixels, y direction
        valid = np.isfinite(thickness)
        if not valid.any():
            continue
        bad = valid & (thickness < 0)
        if bad.any():
            crossings.append((int(z), int(bad.sum())))
        keep = valid & (thickness >= 0)
        ex = _exclusion_mask(region, z, (ny, nx))
        # A column is excluded if its x is excluded anywhere within the slab on
        # this plane. Exclusions are drawn on the image, so they are y-extended;
        # collapsing to x is the conservative reading.
        ex_cols = ex.any(axis=0)
        area_um2 = voxel_column_um2
        inc = float(np.nansum(thickness[keep & ~ex_cols])) * area_um2 * vz / max(vy, 1e-12)
        exc = float(np.nansum(thickness[keep & ex_cols])) * area_um2 * vz / max(vy, 1e-12)
        included += inc
        excluded += exc
        for e in region.exclusions:
            if int(e.z) == int(z):
                excluded_reasons[e.reason] = excluded_reasons.get(e.reason, 0) + 1

    if crossings:
        where = ", ".join(f"z={z} ({n} columns)" for z, n in crossings[:5])
        raise BoundaryError(
            f"Region '{region.name}': the lower boundary rises above the upper "
            f"at {where}. That is a marking error or a fold, not a negative "
            f"volume, so nothing is reported for this region until it is "
            f"corrected.")

    total = included + excluded
    return {
        "region": region.name,
        "channel": int(region.channel),
        "volume_um3": round(included, 4),
        "excluded_volume_um3": round(excluded, 4),
        "excluded_fraction": round(excluded / total, 4) if total > 0 else 0.0,
        "z_first_marked": int(min(zs)),
        "z_last_marked": int(max(zs)),
        "n_planes_measured": len(zs),
        "n_planes_marked_upper": len(upper_marked),
        "n_planes_marked_lower": len(lower_marked),
        "n_planes_in_stack": nz,
        "measured_over_marked_extent_only": True,
        "interpolation": INTERPOLATION,
        "voxel_size_um_z": vz, "voxel_size_um_y": vy, "voxel_size_um_x": vx,
        "exclusion_counts": excluded_reasons,
    }


def region_mask(region, shape_zcyx):
    """Boolean (Z, Y, X) mask of the marked slab, exclusions removed.

    A first-class output, not an internal step: removing the muscle is HOW the
    neurons sandwiched between it and the pharynx become resolvable, so this is
    the natural input to the neurite viewer and trace runner.
    """
    nz, _, ny, nx = [int(v) for v in shape_zcyx]
    upper = _interpolate_between_planes(_surface_curve(region, "upper", nx), nx)
    lower = _interpolate_between_planes(_surface_curve(region, "lower", nx), nx)
    mask = np.zeros((nz, ny, nx), dtype=bool)
    rows = np.arange(ny)[:, None]
    for z in sorted(set(upper) & set(lower)):
        if z < 0 or z >= nz:
            continue
        lo, hi = lower[z], upper[z]
        good = np.isfinite(lo) & np.isfinite(hi) & (hi >= lo)
        if not good.any():
            continue
        # HALF-OPEN in y: [lower, upper). The volume integral uses the
        # continuous thickness (upper - lower), so an inclusive mask would
        # contain one more row per column than the integral accounts for -
        # about 2.5% on a 40 px slab. Somebody will count mask voxels to check
        # the volume, and they must agree by construction rather than nearly.
        band = (rows >= np.where(good, lo, np.inf)) & \
               (rows < np.where(good, hi, -np.inf))
        band &= ~_exclusion_mask(region, z, (ny, nx))
        mask[z] = band
    return mask
