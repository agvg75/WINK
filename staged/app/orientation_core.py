"""C2: provider-driven orientation decomposition and plate statistics."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy.stats import circmean

from stimulus_fields import StimulusFieldProvider


def wrap_degrees(value):
    return (np.asarray(value, dtype=float) + 180) % 360 - 180


@dataclass(frozen=True)
class OrientationSegment:
    plate_id: str
    worm_id: str | None
    time_s: float
    x_mm: float
    y_mm: float
    heading_deg: float
    along_gradient: float | None
    along_contour: float | None
    angle_to_vector_deg: float | None
    radial_heading_deg: float | None
    lab_heading_deg: float
    field_magnitude: float
    field_uncertainty: dict

    def as_dict(self):
        return asdict(self)


def decompose_segment(
    provider: StimulusFieldProvider, *, plate_id: str,
    worm_id: str | None, time_s: float, x_mm: float, y_mm: float,
    heading_deg: float, source_xy_mm=None,
) -> OrientationSegment:
    sample = provider.sample(x_mm, y_mm, time_s)
    theta = np.radians(heading_deg)
    heading = np.asarray([np.cos(theta), np.sin(theta)])
    gradient = np.asarray(sample.gradient_xy, dtype=float)
    gradient_norm = float(np.linalg.norm(gradient))
    if gradient_norm:
        gradient_unit = gradient / gradient_norm
        along_gradient = float(np.dot(heading, gradient_unit))
        contour = np.asarray([-gradient_unit[1], gradient_unit[0]])
        along_contour = float(np.dot(heading, contour))
    else:
        along_gradient = along_contour = None
    angle_to_vector = None
    if sample.direction_xyz is not None:
        horizontal = np.asarray(sample.direction_xyz[:2], dtype=float)
        if np.linalg.norm(horizontal):
            vector_deg = np.degrees(np.arctan2(horizontal[1], horizontal[0]))
            angle_to_vector = float(wrap_degrees(heading_deg - vector_deg))
    radial = None
    if source_xy_mm is not None:
        toward = np.asarray(source_xy_mm, dtype=float) - [x_mm, y_mm]
        if np.linalg.norm(toward):
            radial_deg = np.degrees(np.arctan2(toward[1], toward[0]))
            radial = float(wrap_degrees(heading_deg - radial_deg))
    return OrientationSegment(
        plate_id, worm_id, float(time_s), float(x_mm), float(y_mm),
        float(wrap_degrees(heading_deg)), along_gradient, along_contour,
        angle_to_vector, radial, float(wrap_degrees(heading_deg)),
        sample.magnitude, sample.uncertainty)


def mean_resultant(angles_deg) -> dict:
    values = np.asarray(angles_deg, dtype=float)
    values = values[np.isfinite(values)]
    if not values.size:
        return {"mean_angle_deg": None, "resultant_length": None, "n": 0}
    radians = np.radians(values)
    vector = np.mean(np.exp(1j * radians))
    return {
        "mean_angle_deg": float(wrap_degrees(np.degrees(np.angle(vector)))),
        "resultant_length": float(abs(vector)), "n": int(values.size)}


def rayleigh_test(angles_deg) -> dict:
    """Standard large-sample corrected Rayleigh test."""
    values = np.asarray(angles_deg, dtype=float)
    values = values[np.isfinite(values)]
    n = len(values)
    if n < 2:
        return {"z": None, "p": None, "n": n, "certifiable": False}
    resultant = abs(np.sum(np.exp(1j * np.radians(values))))
    z = resultant * resultant / n
    p = np.exp(-z) * (
        1 + (2 * z - z * z) / (4 * n) -
        (24 * z - 132 * z**2 + 76 * z**3 - 9 * z**4) /
        (288 * n**2))
    return {"z": float(z), "p": float(np.clip(p, 0, 1)), "n": n,
            "certifiable": True}


def population_plate_statistics(
    plate_angles: dict[str, list[float]], *,
    stimulus_orientations_deg: dict[str, float] | None = None,
    geometry: str, endpoint_only: bool = False,
) -> dict:
    if not plate_angles:
        raise ValueError("At least one plate is required.")
    plate_results = {
        plate: mean_resultant(values) for plate, values in plate_angles.items()}
    plate_means = [
        result["mean_angle_deg"] for result in plate_results.values()
        if result["mean_angle_deg"] is not None]
    across = mean_resultant(plate_means)
    rayleigh = rayleigh_test(plate_means)
    reasons = []
    slope = None
    if endpoint_only:
        reasons.append("endpoint-only data cannot certify a vector response")
    if geometry == "linear":
        reasons.append(
            "linear geometry confounds fixed stimulus angle with compass heading")
    if not stimulus_orientations_deg or len(stimulus_orientations_deg) < 2:
        reasons.append(
            "multiple stimulus orientations are required to certify "
            "stimulus-driven directionality")
    else:
        common = [
            plate for plate in plate_results
            if plate in stimulus_orientations_deg
            and plate_results[plate]["mean_angle_deg"] is not None]
        if len(common) >= 2:
            x = np.unwrap(np.radians(
                [stimulus_orientations_deg[p] for p in common]))
            y = np.unwrap(np.radians(
                [plate_results[p]["mean_angle_deg"] for p in common]))
            slope = float(np.polyfit(x, y, 1)[0])
    return {
        "inferential_unit": "plate",
        "plate_count": len(plate_results),
        "plate_resultants": plate_results,
        "across_plate_resultant": across,
        "rayleigh_across_plate_angles": rayleigh,
        "stimulus_rotation_slope": slope,
        "certified_stimulus_response": not reasons and slope is not None,
        "identifiability_reasons": reasons,
    }
