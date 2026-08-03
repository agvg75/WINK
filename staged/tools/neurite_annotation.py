"""Neurite annotation sidecars: what a person marked, kept apart from tracing.

WHY ANNOTATION AND TRACING ARE SEPARATE
----------------------------------------
Confocal work runs across several stations and there is no guarantee which
one a given stack gets opened on. If the 3D viewer and the tracing were one
program, every station that ever touched a stack would need the viewer
installed - which in practice means a heavyweight Qt/Napari dependency on
the whole fleet.

Splitting them removes that. A person marks start, end and correction
anchors ONCE, on an appointed viewer station, and those marks are written
to a small JSON sidecar next to the stack. Everything after that - tubeness
filtering, path search, length, radius, volume - is pure computation with
no GUI at all, so it runs anywhere: the base Tkinter-only install, a
headless batch job, a different station, or months later when someone wants
the numbers recomputed with a different sigma.

The sidecar holds only coordinates and provenance, never pixels. It sits
beside the stack, is human-readable, and is small enough to keep in version
control or email to a collaborator.

WHAT THAT BUYS, CONCRETELY
---------------------------
* Re-tracing after a parameter change costs no re-annotation.
* An annotation made on station A is reproducible on station B, because the
  sidecar records the stack identity it was made against and refuses to
  apply to a different one.
* Marking and computing can happen at different times, by different people.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

SCHEMA_VERSION = 1
SIDECAR_SUFFIX = ".neurites.json"


class AnnotationError(RuntimeError):
    """The annotation cannot be used with this stack."""


@dataclass
class NeuriteAnnotation:
    """One neurite a person marked: an ordered list of points to trace through.

    The first and last are the endpoints; anything between them is a
    correction anchor placed because the automatic path went somewhere the
    person could see was wrong.
    """
    neurite_id: str
    points_zyx: list                       # ordered [[z, y, x], ...]
    label: str = ""
    channel: int = 0
    notes: str = ""
    annotator: str = ""
    annotated_utc: str = ""

    def __post_init__(self):
        if len(self.points_zyx) < 2:
            raise AnnotationError(
                f"Neurite '{self.neurite_id}' has {len(self.points_zyx)} "
                "point(s); a trace needs at least a start and an end.")
        self.points_zyx = [[int(v) for v in p] for p in self.points_zyx]
        if not self.annotated_utc:
            self.annotated_utc = datetime.now(timezone.utc).isoformat()

    @property
    def anchors_zyx(self):
        """The correction anchors: everything that is not an endpoint."""
        return self.points_zyx[1:-1]


def stack_identity(stack_path, series_index, shape_zcyx, voxel_size_um):
    """A fingerprint an annotation is valid against.

    Deliberately derived from the file NAME, series, shape and calibration
    rather than a content hash: hashing a multi-gigabyte stack on every
    load would be slow enough that people would turn it off. This catches
    the realistic mistakes - a sidecar applied to the wrong series, or to a
    stack that has been recalibrated or recropped since it was annotated -
    without reading the pixels.
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


def save_annotations(path, identity, annotations, station=None):
    """Write the sidecar. Never writes pixel data."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "written_utc": datetime.now(timezone.utc).isoformat(),
        "written_on_station": station or _station_name(),
        "stack_identity": identity,
        "neurites": [asdict(a) for a in annotations],
    }
    path = Path(path)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_annotations(path, identity=None, strict=True):
    """Read a sidecar, optionally checking it belongs to this stack.

    A mismatch raises by default rather than tracing through coordinates
    that were marked against a different acquisition - which would produce
    a confident, entirely fictional path.
    """
    path = Path(path)
    if not path.is_file():
        raise AnnotationError(f"No annotation sidecar at {path}.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if identity is not None:
        stored = payload.get("stack_identity", {})
        if stored.get("fingerprint") != identity.get("fingerprint"):
            message = (
                f"This sidecar was made against a different stack.\n"
                f"  annotated: {stored.get('name')} series "
                f"{stored.get('series_index')} shape {stored.get('shape_zcyx')} "
                f"voxel {stored.get('voxel_size_um')}\n"
                f"  loading:   {identity.get('name')} series "
                f"{identity.get('series_index')} shape "
                f"{identity.get('shape_zcyx')} voxel "
                f"{identity.get('voxel_size_um')}\n"
                f"Tracing through points marked on another acquisition would "
                f"produce a confident but fictional path.")
            if strict:
                raise AnnotationError(message)
            payload["identity_warning"] = message
    annotations = [NeuriteAnnotation(**a) for a in payload.get("neurites", [])]
    return annotations, payload


def _station_name():
    import socket
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Headless tracing from a sidecar - no GUI, runs anywhere
# ---------------------------------------------------------------------------
def trace_annotations(stack, annotations, radius_um, sigma_scales=None,
                      method="sato", measure=True):
    """Trace every annotated neurite in a loaded stack. Pure computation.

    `stack` is a ConfocalStack from confocal_loader. Returns one result per
    annotation, each carrying the raw automatic path, the physical length,
    and (optionally) radius and volume - plus the parameters used, so a
    number can always be traced back to how it was produced.
    """
    import neurite_tracer as nt

    if stack.voxel_size_um is None:
        raise AnnotationError(
            "The stack has no physical voxel size, so no traced length would "
            "be meaningful. Calibrate it before tracing.")
    scales = tuple(sigma_scales or nt.DEFAULT_SIGMA_SCALES)
    out = []
    cache = {}
    for ann in annotations:
        if ann.channel not in cache:
            volume = stack.channel(ann.channel)
            cache[ann.channel] = nt.tubeness(
                volume, stack.voxel_size_um, radius_um,
                sigma_scales=scales, method=method)
        response, sigmas_um = cache[ann.channel]

        raw = nt.trace_between(response, ann.points_zyx[0], ann.points_zyx[-1],
                               stack.voxel_size_um)
        nodes = (nt.trace_with_anchors(response, ann.points_zyx,
                                       stack.voxel_size_um)
                 if len(ann.points_zyx) > 2 else raw)
        path = nt.TracedPath(
            nodes_zyx=nodes, voxel_size_um=stack.voxel_size_um,
            anchors_zyx=ann.anchors_zyx, raw_nodes_zyx=raw,
            sigma_um=sigmas_um,
            notes=nt.preflight_notes(stack.metadata, response))
        record = {
            "neurite_id": ann.neurite_id,
            "label": ann.label,
            "channel": ann.channel,
            "annotator": ann.annotator,
            "annotated_utc": ann.annotated_utc,
            "n_anchors": len(ann.anchors_zyx),
            "was_corrected": path.was_corrected(),
            "length_um": path.length_um(),
            "raw_length_um": nt.TracedPath(
                nodes_zyx=raw, voxel_size_um=stack.voxel_size_um).length_um(),
            "sigma_um": list(sigmas_um),
            "tubeness_method": method,
            "radius_um_expected": radius_um,
            "voxel_size_um": list(stack.voxel_size_um),
            "notes": path.notes,
            "path": path,
        }
        if measure:
            volume = stack.channel(ann.channel)
            radii = nt.radius_profile_um(volume, nodes, stack.voxel_size_um)
            record["median_radius_um"] = float(
                __import__("numpy").median(radii)) if len(radii) else 0.0
            record["volume_um3"] = nt.volume_from_radii_um3(
                radii, nodes, stack.voxel_size_um)
            record["radius_note"] = (
                "Radius is a thresholded cross-section estimate, not a fitted "
                "circular profile - treat it as coarse.")
        out.append(record)
    return out


def results_to_rows(results, stack_metadata):
    """Flatten trace results into CSV-ready rows, dropping the path arrays."""
    rows = []
    for r in results:
        row = {k: v for k, v in r.items() if k not in ("path", "notes")}
        row["source_path"] = stack_metadata.get("source_path")
        row["series_index"] = stack_metadata.get("series_index")
        row["series_name"] = stack_metadata.get("series_name")
        row["calibration_source"] = stack_metadata.get("calibration_source")
        row["preflight_notes"] = " | ".join(r.get("notes", []))
        rows.append(row)
    return rows
