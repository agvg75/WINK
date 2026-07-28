"""T12: anchored, deformable, compartment-specific pharynx morphometry."""
from __future__ import annotations

import numpy as np
from scipy.interpolate import splprep, splev


COMPARTMENTS = {
    "procorpus": (0.00, 0.30),
    "metacorpus": (0.30, 0.48),
    "isthmus": (0.48, 0.72),
    "terminal_bulb": (0.72, 1.00),
}
COMPARTMENT_SHAPES = {
    "procorpus": ("elongated", 0.82),
    "metacorpus": ("oval", 1.30),
    "isthmus": ("elongated", 0.68),
    "terminal_bulb": ("oval", 1.55),
}
DAMAGE_DEFINITION = {
    "radial_myofilament_disorganization":
        "loss of coherent radial intensity orientation relative to the local "
        "pharyngeal axis",
    "grinder_integrity":
        "loss or fragmentation of the high-contrast terminal-bulb grinder ROI",
    "vacuolization":
        "fraction of low-intensity enclosed voids within each compartment",
    "intensity_texture":
        "compartment intensity coefficient of variation after background "
        "subtraction",
}


def centerline_from_landmarks(anterior_xy, posterior_xy, bend_landmarks=(),
                              samples=101):
    points = np.asarray(
        [anterior_xy, *list(bend_landmarks), posterior_xy], dtype=float)
    if len(points) == 2:
        t = np.linspace(0, 1, samples)[:, None]
        return points[0] * (1 - t) + points[1] * t
    if len(points) > 6:
        raise ValueError("Use at most four bend landmarks.")
    spline, _ = splprep(points.T, s=0, k=min(3, len(points) - 1))
    return np.asarray(splev(np.linspace(0, 1, samples), spline)).T


def template_mask(shape, centerline, width_px):
    yy, xx = np.indices(shape)
    mask = np.zeros(shape, dtype=bool)
    half = float(width_px) / 2
    for point in centerline:
        mask |= (xx - point[0]) ** 2 + (yy - point[1]) ** 2 <= half ** 2
    return mask

def _oriented_ellipse_mask(shape,section,width_px):
    yy,xx=np.indices(shape);center=np.mean(section,axis=0);axis=section[-1]-section[0]
    length=max(float(np.linalg.norm(axis)),1.0);u=axis/length;v=np.array([-u[1],u[0]])
    dx=xx-center[0];dy=yy-center[1];along=dx*u[0]+dy*u[1];across=dx*v[0]+dy*v[1]
    return (along/max(length*.58,1))**2+(across/max(width_px/2,1))**2<=1

def compartment_masks(shape,line,width_px):
    """Four connected expected territories: tube, bulb, tube, bulb."""
    masks={}
    for name,(start,stop) in COMPARTMENTS.items():
        a=max(0,int(start*(len(line)-1))-1);b=min(len(line),int(stop*(len(line)-1))+2)
        section=line[a:b];kind,mult=COMPARTMENT_SHAPES[name];width=float(width_px)*mult
        masks[name]=(_oriented_ellipse_mask(shape,section,width) if kind=="oval" else template_mask(shape,section,width))
    return masks


def analyze_pharynx(
    image, *, anterior_xy, posterior_xy, width_px, um_per_px,
    bend_landmarks=(), grinder_roi_mask=None, reference_ranges=None,
) -> dict:
    if width_px <= 0 or um_per_px <= 0:
        raise ValueError("width_px and um_per_px must be positive.")
    gray = np.asarray(image, dtype=float)
    if gray.ndim == 3:
        gray = np.mean(gray, axis=2)
    line = centerline_from_landmarks(
        anterior_xy, posterior_xy, bend_landmarks)
    masks=compartment_masks(gray.shape,line,width_px);mask=np.logical_or.reduce(list(masks.values()))
    if not np.any(mask):
        return {"status": "refused", "reason": "template does not intersect image"}
    background = gray[~mask]
    bg = float(np.median(background)) if background.size else 0
    normalized = gray - bg
    compartment_rows = []
    for name, section_mask in masks.items():
        values = normalized[section_mask]
        if not values.size:
            compartment_rows.append({
                "compartment": name, "status": "not measurable"})
            continue
        positive_scale = max(float(np.percentile(values, 90)), 1e-9)
        vacuole = float(np.mean(values < 0.15 * positive_scale))
        texture = float(np.std(values) / max(abs(np.mean(values)), 1e-9))
        gy, gx = np.gradient(normalized)
        orientation = np.arctan2(gy[section_mask], gx[section_mask])
        coherence = float(abs(np.mean(np.exp(2j * orientation))))
        compartment_rows.append({
            "compartment": name, "status": "measured",
            "vacuolization_fraction": vacuole,
            "intensity_texture_cv": texture,
            "radial_myofilament_disorganization": 1 - coherence})
    grinder = None
    if grinder_roi_mask is not None:
        grinder_mask = np.asarray(grinder_roi_mask, dtype=bool)
        values = normalized[grinder_mask]
        grinder = {
            "status": "measured" if values.size else "not measurable",
            "mean_contrast": None if not values.size else float(np.mean(values)),
            "fragmentation_proxy": None if not values.size else float(
                np.mean(values < np.percentile(values, 25)))}
    score_status = (
        "not reported: calibrated undamaged/damaged reference ranges required"
        if not reference_ranges else "reference-normalized metrics available")
    return {
        "status": "review_required", "inferential_unit": "one pharynx",
        "template": {
            "anterior_xy": list(anterior_xy), "posterior_xy": list(posterior_xy),
            "bend_landmarks": [list(value) for value in bend_landmarks],
            "width_px": float(width_px),
            "compartment_shapes": {name:kind for name,(kind,_width) in COMPARTMENT_SHAPES.items()},
            "length_um": float(np.sum(np.linalg.norm(
                np.diff(line, axis=0), axis=1)) * um_per_px)},
        "damage_definition": DAMAGE_DEFINITION,
        "compartments": compartment_rows,
        "grinder_integrity": grinder,
        "composite_damage_score": None,
        "composite_score_status": score_status,
        "undamaged_null": (
            "each calibrated compartment damage metric must approach zero"),
        "review_required_before_export": True}
