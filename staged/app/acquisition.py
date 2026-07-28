"""Shared acquisition metadata, validation, and provenance for Lab Tools.

The original contract covered only FPS, scale, exposure, and D/V orientation.
The master work orders require every result and failure report to carry the
complete declared constant set.  New fields therefore have defaults so older
tools remain readable while new analyses can require the full contract.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any
import json
from pathlib import Path


FPS_SOURCES = {"camera", "declared", "inferred", "not_applicable"}
SCALE_SOURCES = {"two_point_calibration", "declared", "inferred", "not_applicable"}
EXPOSURE_SOURCES = {"camera", "declared", "inferred", "not_applicable"}
DV_ORIENTATIONS = {"A", "B", "unknown"}
DV_SOURCES = {"vulva_click", "heuristic", "unknown"}
COMPRESSION_TYPES = {"none", "lossless", "lossy", "unknown", "not_applicable"}
ANATOMICAL_ORIENTATIONS = {
    "head_left", "head_right", "head_up", "head_down", "declared_landmarks",
    "unknown", "not_applicable",
}


@dataclass(frozen=True)
class AcquisitionMetadata:
    fps: float | None
    fps_source: str
    um_per_px: float | None
    um_per_px_source: str
    exposure_ms: float | None
    exposure_source: str
    dv_orientation: str = "unknown"
    dv_source: str = "unknown"
    bit_depth: int | None = None
    compression: str = "unknown"
    recording_duration_s: float | None = None
    channel_identity: str = "unknown"
    anatomical_orientation: str = "unknown"
    declared_worm_length_um: float | None = None
    time_since_food_removal_s: float | None = None

    def validate(self, require_complete: bool = False) -> "AcquisitionMetadata":
        numeric = {
            "fps": self.fps,
            "um_per_px": self.um_per_px,
            "exposure_ms": self.exposure_ms,
        }
        sources = {"fps": self.fps_source, "um_per_px": self.um_per_px_source,
                   "exposure_ms": self.exposure_source}
        for name, value in numeric.items():
            if sources[name] == "not_applicable":
                if value is not None:
                    raise ValueError(f"{name} must be None when its source is not_applicable.")
            elif value is None or not isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{name} must be a positive declared or inferred value.")
        allowed = {
            "fps_source": (self.fps_source, FPS_SOURCES),
            "um_per_px_source": (self.um_per_px_source, SCALE_SOURCES),
            "exposure_source": (self.exposure_source, EXPOSURE_SOURCES),
            "dv_orientation": (self.dv_orientation, DV_ORIENTATIONS),
            "dv_source": (self.dv_source, DV_SOURCES),
        }
        for name, (value, choices) in allowed.items():
            if value not in choices:
                raise ValueError(f"{name} must be one of {sorted(choices)}.")
        if self.bit_depth is not None and (
                not isinstance(self.bit_depth, int) or self.bit_depth <= 0):
            raise ValueError("bit_depth must be a positive integer when supplied.")
        if self.compression not in COMPRESSION_TYPES:
            raise ValueError(
                f"compression must be one of {sorted(COMPRESSION_TYPES)}.")
        if self.anatomical_orientation not in ANATOMICAL_ORIENTATIONS:
            raise ValueError(
                "anatomical_orientation must be a declared orientation, "
                "'unknown', or 'not_applicable'.")
        for name in ("recording_duration_s", "declared_worm_length_um"):
            value = getattr(self, name)
            if value is not None and (
                    not isfinite(float(value)) or float(value) <= 0):
                raise ValueError(f"{name} must be positive when supplied.")
        if self.time_since_food_removal_s is not None and (
                not isfinite(float(self.time_since_food_removal_s))
                or float(self.time_since_food_removal_s) < 0):
            raise ValueError(
                "time_since_food_removal_s must be non-negative when supplied.")
        if require_complete:
            missing = self.missing_declared_constants()
            if missing:
                raise ValueError(
                    "Missing required acquisition constants: " + ", ".join(missing))
        return self

    def missing_declared_constants(self) -> list[str]:
        missing = []
        sourced = (
            ("fps", self.fps, self.fps_source),
            ("um_per_px", self.um_per_px, self.um_per_px_source),
            ("exposure_ms", self.exposure_ms, self.exposure_source),
        )
        for name, value, source in sourced:
            if source != "not_applicable" and value is None:
                missing.append(name)
        for name, value in (
                ("bit_depth", self.bit_depth),
                ("recording_duration_s", self.recording_duration_s)):
            if value is None:
                missing.append(name)
        for name in ("compression", "channel_identity",
                     "anatomical_orientation"):
            if getattr(self, name) in {"unknown", ""}:
                missing.append(name)
        return missing

    @property
    def has_inferred_value(self) -> bool:
        return "inferred" in {
            self.fps_source, self.um_per_px_source, self.exposure_source}

    def as_columns(self) -> dict:
        self.validate()
        return asdict(self)

    def stamped(self, tool_name: str, tool_version: str) -> dict:
        """Return the mandatory field/version stamp for results and failures."""
        if not tool_name.strip() or not tool_version.strip():
            raise ValueError("tool_name and tool_version are required.")
        release = {}
        release_path = Path(__file__).with_name("release_info.json")
        if release_path.is_file():
            try:
                release = json.loads(release_path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                release = {}
        return {
            "tool_name": tool_name.strip(),
            "tool_version": tool_version.strip(),
            # WINK (formerly NIKE): emit the new keys and keep the old ones as
            # aliases so downstream readers of pre-rename output still resolve.
            "wink_app_version": release.get("app_version", "unknown"),
            "wink_runtime_version": release.get("runtime_version", "unknown"),
            "nike_app_version": release.get("app_version", "unknown"),
            "nike_runtime_version": release.get("runtime_version", "unknown"),
            "acquisition_constants": self.as_columns(),
            "validation_level": "computational_regression",
            "validation_stamp": {
                "level": "computational_regression",
                "tool_name": tool_name.strip(),
                "tool_version": tool_version.strip(),
                "metric": "output_bundle",
                "evidence": [],
                "validated_envelope": None,
            },
        }


def capability_gate(ok: bool, reason: str = "") -> tuple[float | None, str]:
    """Return a NaN-compatible value marker and an explicit gate reason."""
    return (None, "") if ok else (None, reason or "outside capability gate")
