"""S1: intake and independent scale-verification service."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np

from acquisition import AcquisitionMetadata


@dataclass(frozen=True)
class ScaleVerification:
    status: str
    declared_um_per_px: float
    measured_length_px: float | None
    declared_worm_length_um: float | None
    implied_um_per_px: float | None
    relative_discrepancy: float | None
    reason: str

    @property
    def blocking(self) -> bool:
        return self.status != "pass"

    def as_dict(self) -> dict:
        return asdict(self)


def verify_scale(
    acquisition: AcquisitionMetadata,
    measured_worm_lengths_px: Iterable[float],
    *,
    tolerance_fraction: float = 0.25,
) -> ScaleVerification:
    """Cross-check declared scale against an independent worm measurement.

    Worm length is deliberately supplied by a detector/reviewer rather than
    inferred from scale. Empty or invalid detections produce a blocking
    ``not_verifiable`` result, never a pass.
    """
    acquisition.validate()
    if acquisition.um_per_px is None:
        raise ValueError("Declared spatial calibration is required.")
    values = np.asarray(list(measured_worm_lengths_px), dtype=float)
    values = values[np.isfinite(values) & (values > 0)]
    if values.size == 0:
        return ScaleVerification(
            "not_verifiable", float(acquisition.um_per_px), None,
            acquisition.declared_worm_length_um, None, None,
            "scale not verifiable: no worm was detected for measurement")
    measured_px = float(np.median(values))
    expected_um = acquisition.declared_worm_length_um
    if expected_um is None:
        return ScaleVerification(
            "not_verifiable", float(acquisition.um_per_px), measured_px,
            None, None, None,
            "scale not verifiable: declared biological worm length is absent")
    implied = float(expected_um) / measured_px
    discrepancy = abs(implied - float(acquisition.um_per_px)) / float(
        acquisition.um_per_px)
    if discrepancy > tolerance_fraction:
        return ScaleVerification(
            "discrepancy", float(acquisition.um_per_px), measured_px,
            float(expected_um), implied, discrepancy,
            "blocking scale discrepancy: declared and independently implied "
            "calibrations disagree")
    return ScaleVerification(
        "pass", float(acquisition.um_per_px), measured_px, float(expected_um),
        implied, discrepancy, "declared scale passed the independent cross-check")


@dataclass(frozen=True)
class IntakeResult:
    acquisition: AcquisitionMetadata
    scale: ScaleVerification
    container_metadata: dict

    @property
    def validated(self) -> bool:
        return not self.scale.blocking

    def require_validated(self) -> "IntakeResult":
        if not self.validated:
            raise ValueError(self.scale.reason)
        return self

    def as_dict(self) -> dict:
        return {
            "validated": self.validated,
            "acquisition": self.acquisition.as_columns(),
            "scale_verification": self.scale.as_dict(),
            "container_metadata": dict(self.container_metadata),
        }


def run_intake(
    acquisition: AcquisitionMetadata,
    measured_worm_lengths_px: Iterable[float],
    container_metadata: dict | None = None,
    *,
    require_complete_constants: bool = True,
    tolerance_fraction: float = 0.25,
) -> IntakeResult:
    acquisition.validate(require_complete=require_complete_constants)
    scale = verify_scale(
        acquisition, measured_worm_lengths_px,
        tolerance_fraction=tolerance_fraction)
    return IntakeResult(acquisition, scale, container_metadata or {})
