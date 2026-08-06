"""Where the stimulus is, drawn on the image by the person who ran the assay.

Andres: for a gradient stimulus - magnetic, chemical or thermal - the user
drops a POINT or ROI over the source or magnet. For a linear field they draw a
LINE across the field, say down the right edge of the field of view. For the
donut assay they draw the INNER EDGE of the magnet hole.

ONE MODULE FOR ALL THREE STIMULI, because the drawing is the same act every
time: a person looks at the frame and says where the thing is. What differs is
what the shape MEANS - a point means a source, a line means a direction, a
circle means a boundary - and that meaning is declared here rather than
inferred from the shape, because a circle drawn over an odour spot and a circle
drawn round a magnet hole look identical and are not the same claim.

SCALE IS REQUIRED, NOT OPTIONAL. Every one of these becomes millimetres in a
field model, and a field computed from pixel distances is wrong by whatever the
magnification happened to be. A placeholder 1.000 um/px has already reached
this archive once.

THE DRAWING IS EVIDENCE AND IS STAMPED AS SUCH. Who drew it and when go in the
record, because "the magnet was here" is an assertion by a person and should
be attributable years later like any other measurement.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

KINDS = {
    "point": {
        "means": "the location of a point source: an odour spot, a magnet, "
                 "the hot end of a probe",
        "needs": ("x_px", "y_px"),
        "used_by": ("chemotaxis", "thermotaxis_radial", "magnetotaxis_magnet"),
    },
    "roi": {
        "means": "the extent of a source too large to be a point - a magnet "
                 "face, a spot that has spread",
        "needs": ("x_px", "y_px", "radius_px"),
        "used_by": ("chemotaxis", "magnetotaxis_magnet"),
    },
    "line": {
        "means": "a direction across the plate: the axis of a linear field or "
                 "gradient, drawn along or across it",
        "needs": ("x1_px", "y1_px", "x2_px", "y2_px"),
        "used_by": ("magnetotaxis_coil", "thermotaxis_linear"),
    },
    "circle": {
        "means": "a boundary the animals cross - for the donut assay, the "
                 "INNER edge of the magnet hole",
        "needs": ("x_px", "y_px", "radius_px"),
        "used_by": ("magnetotaxis_donut",),
    },
}


class AnnotationError(Exception):
    """Refusals that name the consequence."""


def _scale_mm_per_px(um_per_px=None, mm_per_px=None):
    if um_per_px in (None, "") and mm_per_px in (None, ""):
        raise AnnotationError(
            "A spatial scale is required. Every annotation becomes "
            "millimetres in a field model, and a field computed from pixel "
            "distances is wrong by whatever the magnification happened to be "
            "- silently, because the numbers still look like millimetres.")
    if um_per_px not in (None, "") and mm_per_px not in (None, ""):
        raise AnnotationError(
            "Give the scale once, in um/px or mm/px, not both. Two values "
            "that disagree cannot be reconciled after the fact.")
    value = (float(um_per_px) / 1000.0 if um_per_px not in (None, "")
             else float(mm_per_px))
    if value <= 0:
        raise AnnotationError(
            f"A scale of {value} mm/px is not usable. Every distance derived "
            f"from it would be zero or negative.")
    if abs(value - 0.001) < 1e-12:
        # 1.000 um/px is the placeholder that has reached this archive before.
        raise AnnotationError(
            "1.000 um/px is the placeholder value, not a measurement. If the "
            "scale genuinely is 1 um/px, pass mm_per_px=0.001 to say so "
            "deliberately.")
    return value


def annotate(kind, *, um_per_px=None, mm_per_px=None, by="", note="",
             origin_px=(0.0, 0.0), **coords):
    """Record a drawn stimulus location. Returns a plain dict, ready to store.

    `origin_px` is where plate millimetres are measured FROM, so an annotation
    and a track table share one coordinate frame. Defaulting it to the image
    corner is a choice, not a truth, and it is recorded so a later reader can
    see which frame the numbers are in.
    """
    if kind not in KINDS:
        raise AnnotationError(
            f"{kind!r} is not one of {sorted(KINDS)}. The shape does not imply "
            f"the meaning - a circle over an odour spot and a circle round a "
            f"magnet hole look identical and are different claims.")
    spec = KINDS[kind]
    missing = [f for f in spec["needs"] if coords.get(f) is None]
    if missing:
        raise AnnotationError(
            f"A {kind} needs {', '.join(spec['needs'])}; missing "
            f"{', '.join(missing)}.")
    scale = _scale_mm_per_px(um_per_px, mm_per_px)
    ox, oy = float(origin_px[0]), float(origin_px[1])

    def to_mm(x, y):
        return ((float(x) - ox) * scale, (float(y) - oy) * scale)

    doc = {"kind": kind, "means": spec["means"], "mm_per_px": scale,
           "origin_px": [ox, oy], "pixels": {k: float(v)
                                             for k, v in coords.items()},
           "note": note}

    if kind in {"point", "roi", "circle"}:
        doc["center_mm"] = list(to_mm(coords["x_px"], coords["y_px"]))
        if "radius_px" in spec["needs"]:
            r = float(coords["radius_px"])
            if r <= 0:
                raise AnnotationError(
                    f"A {kind} needs a positive radius; {r} px encloses "
                    f"nothing and no worm could ever be inside or outside it.")
            doc["radius_mm"] = r * scale
    if kind == "line":
        a = to_mm(coords["x1_px"], coords["y1_px"])
        b = to_mm(coords["x2_px"], coords["y2_px"])
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length <= 0:
            raise AnnotationError(
                "The two ends of the line are the same point, so it declares "
                "no direction at all.")
        doc["start_mm"], doc["end_mm"] = list(a), list(b)
        doc["length_mm"] = length
        doc["direction_xy"] = [dx / length, dy / length]
        doc["direction_deg"] = math.degrees(math.atan2(dy, dx))
        # A line drawn ACROSS a field declares the field's axis as its normal;
        # a line drawn ALONG it declares the axis directly. Which one is meant
        # cannot be recovered from the pixels, so both are offered and the
        # caller says which.
        doc["normal_xy"] = [-dy / length, dx / length]
        doc["normal_deg"] = math.degrees(math.atan2(dx, -dy))

    doc.update(_stamp(by))
    return doc


def _stamp(by=""):
    """Who drew this and when - an assertion by a person, like any measurement."""
    import datetime as _dt
    out = {"drawn_utc": _dt.datetime.now(_dt.timezone.utc).isoformat()}
    if by:
        out["drawn_by"] = by
        return out
    try:
        import operator_identity
        out["drawn_by"] = operator_identity.initials() or None
    except Exception:
        out["drawn_by"] = None
    if not out["drawn_by"]:
        out["unattributed"] = (
            "Nobody was set at this station, so the person who placed this "
            "stimulus is not recorded. The placement is an assertion and "
            "should be attributable.")
    return out


def to_provider_kwargs(annotation, *, assay, use="direction"):
    """Turn a drawing into the arguments a field provider needs.

    `use` matters only for lines: "direction" means the line was drawn ALONG
    the field, "normal" means it was drawn ACROSS it. The pixels cannot say
    which, so the caller must.
    """
    kind = annotation["kind"]
    if kind in {"point", "roi"}:
        if assay in {"chemotaxis", "thermotaxis"}:
            return {"source_xy_mm": list(annotation["center_mm"])}
        if assay == "magnetotaxis":
            c = annotation["center_mm"]
            return {"position_xyz_mm": [c[0], c[1], None]}
        raise AnnotationError(f"No provider mapping for {kind} in {assay}.")
    if kind == "line":
        if use not in {"direction", "normal"}:
            raise AnnotationError(
                "use must be 'direction' (line drawn along the field) or "
                "'normal' (drawn across it). A line across the right edge of "
                "the frame declares an axis perpendicular to itself, and "
                "guessing which was meant would rotate the field 90 degrees.")
        vec = annotation["direction_xy" if use == "direction" else "normal_xy"]
        if assay == "magnetotaxis":
            return {"direction_xyz": [vec[0], vec[1], 0.0]}
        return {"direction_xy": list(vec)}
    if kind == "circle":
        return {"inner_radius_mm": annotation["radius_mm"],
                "center_xy_mm": list(annotation["center_mm"])}
    raise AnnotationError(f"No provider mapping for {kind}.")


def save(annotation, path):
    Path(path).write_text(json.dumps(annotation, indent=2), encoding="utf-8")
    return path


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise AnnotationError(
            f"{path} is not valid JSON ({exc}). Treating an unreadable "
            f"annotation as absent would silently move the stimulus to the "
            f"origin.")
