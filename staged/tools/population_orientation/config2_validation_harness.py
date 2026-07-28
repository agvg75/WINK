"""Evidence harness required before enabling Config 2 per-worm paths."""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np


def synthetic_fixed_angle_check(stimulus_deg, observed_heading_deg,
                                expected_offset_deg, tolerance_deg=5.0):
    stimulus = np.deg2rad(np.asarray(stimulus_deg, dtype=float))
    heading = np.deg2rad(np.asarray(observed_heading_deg, dtype=float))
    relative = np.angle(np.exp(1j * (heading - stimulus)))
    vector = np.mean(np.exp(1j * relative))
    recovered = float(np.rad2deg(np.angle(vector)))
    concentration = float(abs(vector))
    error = abs(float(np.rad2deg(np.angle(
        np.exp(1j * (np.deg2rad(recovered - expected_offset_deg)))))))
    # Deliberately wrong lab frame should lose concentration when the field rotates.
    wrong_frame_concentration = float(abs(np.mean(np.exp(1j * heading))))
    return {
        "passed": error <= tolerance_deg and
                  concentration > wrong_frame_concentration,
        "recovered_offset_deg": recovered,
        "error_deg": error,
        "correct_frame_concentration": concentration,
        "wrong_lab_frame_concentration": wrong_frame_concentration,
    }


def write_manual_validation_fixture(path, *, dataset_id, reviewer,
                                    identity_accuracy=None,
                                    heading_mae_deg=None, notes=""):
    """Write a versioned crowded-plate comparison record; nulls mean pending."""
    record = {
        "fixture_type": "config2_manual_crowded_plate_validation",
        "dataset_id": dataset_id,
        "reviewer": reviewer,
        "identity_accuracy": identity_accuracy,
        "heading_mae_deg": heading_mae_deg,
        "notes": notes,
        "status": "pending" if identity_accuracy is None or
                  heading_mae_deg is None else "measured",
        "validation_level": "technical_validation_fixture",
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def record_validated_envelope(
    path, fixtures, *, density_worms_per_cm2, magnification,
    fps_range, strains, image_quality_range,
    minimum_identity_accuracy=.95, maximum_heading_mae_deg=10,
):
    """Promote only from measured representative crowded-plate fixtures."""
    if not fixtures:
        raise ValueError("Representative crowded-plate fixtures are required.")
    if any(row.get("status") != "measured" for row in fixtures):
        raise ValueError("Every technical-validation fixture must be measured.")
    if min(row["identity_accuracy"] for row in fixtures) < (
            minimum_identity_accuracy):
        raise ValueError("Identity accuracy did not clear the technical gate.")
    if max(row["heading_mae_deg"] for row in fixtures) > (
            maximum_heading_mae_deg):
        raise ValueError("Heading error did not clear the technical gate.")
    envelope = {
        "density_worms_per_cm2": density_worms_per_cm2,
        "magnification": magnification,
        "fps": {"min": float(fps_range[0]), "max": float(fps_range[1])},
        "strain": list(strains),
        "image_quality": image_quality_range,
        "technical_validation_fixture_ids": [
            row["dataset_id"] for row in fixtures],
        "identity_accuracy_minimum_observed": min(
            row["identity_accuracy"] for row in fixtures),
        "heading_mae_deg_maximum_observed": max(
            row["heading_mae_deg"] for row in fixtures),
    }
    target = Path(path)
    target.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    return envelope
