"""S4: common stimulus-field provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from math import sqrt
from typing import Callable

import numpy as np


@dataclass(frozen=True)
class FieldSample:
    direction_xyz: tuple[float, float, float] | None
    magnitude: float
    gradient_xy: tuple[float, float]
    inclination_deg: float | None
    uncertainty: dict
    units: str

    def as_dict(self) -> dict:
        return asdict(self)


class StimulusFieldProvider(ABC):
    provider_type = "abstract"
    has_true_direction = False

    @abstractmethod
    def sample(self, x_mm: float, y_mm: float, time_s: float = 0) -> FieldSample:
        raise NotImplementedError


def _unit(vector) -> tuple[float, ...] | None:
    values = np.asarray(vector, dtype=float)
    norm = float(np.linalg.norm(values))
    if not np.isfinite(norm) or norm == 0:
        return None
    return tuple(float(value) for value in values / norm)


class NullProvider(StimulusFieldProvider):
    provider_type = "null"

    def sample(self, x_mm, y_mm, time_s=0):
        return FieldSample(None, 0.0, (0.0, 0.0), None,
                           {"kind": "exact_sham", "value": 0.0}, "none")


class ThermalLinearProvider(StimulusFieldProvider):
    provider_type = "thermal_linear"

    def __init__(self, direction_xy, slope_c_per_mm, uncertainty_c_per_mm=0):
        direction = _unit(direction_xy)
        if direction is None or len(direction) != 2:
            raise ValueError("A non-zero 2D thermal direction is required.")
        self.direction = direction
        self.slope = float(slope_c_per_mm)
        self.uncertainty = float(uncertainty_c_per_mm)

    def sample(self, x_mm, y_mm, time_s=0):
        gradient = tuple(self.slope * value for value in self.direction)
        return FieldSample(
            None, abs(self.slope), gradient, 0.0,
            {"gradient_c_per_mm": self.uncertainty}, "degC/mm")


class ThermalRadialProvider(StimulusFieldProvider):
    provider_type = "thermal_radial"

    def __init__(self, source_xy_mm, slope_c_per_mm, uncertainty_c_per_mm=0):
        self.source = np.asarray(source_xy_mm, dtype=float)
        self.slope = float(slope_c_per_mm)
        self.uncertainty = float(uncertainty_c_per_mm)

    def sample(self, x_mm, y_mm, time_s=0):
        toward = self.source - np.asarray([x_mm, y_mm], dtype=float)
        direction = _unit(toward)
        gradient = (0.0, 0.0) if direction is None else tuple(
            self.slope * value for value in direction)
        return FieldSample(
            None, abs(self.slope), gradient, 0.0,
            {"gradient_c_per_mm": self.uncertainty}, "degC/mm")


class ChemicalProvider(StimulusFieldProvider):
    provider_type = "chemical"

    def __init__(
        self, source_xy_mm, magnitude_model: Callable[[float, float, float], float],
        relative_uncertainty: float = 0.5, derivative_step_mm: float = 0.1,
    ):
        self.source = tuple(float(v) for v in source_xy_mm)
        self.model = magnitude_model
        self.relative_uncertainty = float(relative_uncertainty)
        self.step = float(derivative_step_mm)

    def sample(self, x_mm, y_mm, time_s=0):
        h = self.step
        magnitude = float(self.model(x_mm, y_mm, time_s))
        gx = (self.model(x_mm + h, y_mm, time_s) -
              self.model(x_mm - h, y_mm, time_s)) / (2 * h)
        gy = (self.model(x_mm, y_mm + h, time_s) -
              self.model(x_mm, y_mm - h, time_s)) / (2 * h)
        return FieldSample(
            None, magnitude, (float(gx), float(gy)), 0.0,
            {"relative": self.relative_uncertainty,
             "reason": "diffusion time and assay drift are model-limited"},
            "declared chemical units")


class MagnetProvider(StimulusFieldProvider):
    """Magpylib-backed 3D magnet field on the worm plane.

    Coordinates passed to ``sample`` are plate millimetres. Magnet position
    includes the required vertical distance from magnet to agar plane.
    """
    provider_type = "magnet"
    has_true_direction = True

    def __init__(
        self, *, shape: str, dimensions_mm, remanence_t: float,
        magnetization_direction_xyz, position_xyz_mm,
        distance_uncertainty_mm: float, earth_field_xyz_t=(0, 0, 0),
        earth_field_xyz_mt=None,
    ):
        try:
            import magpylib as magpy
        except ImportError as exc:
            raise RuntimeError(
                "MagnetProvider requires magpylib; install the declared "
                "dependency before magnetic analysis.") from exc
        direction = _unit(magnetization_direction_xyz)
        if direction is None or len(direction) != 3:
            raise ValueError("A non-zero 3D magnetization direction is required.")
        if float(distance_uncertainty_mm) <= 0:
            raise ValueError(
                "Vertical-distance uncertainty must be measured and positive.")
        polarization_t = tuple(
            float(remanence_t) * value for value in direction)
        dimensions_m = tuple(float(value) / 1000 for value in dimensions_mm)
        position_m = tuple(float(value) / 1000 for value in position_xyz_mm)
        shape_key = shape.lower()
        if shape_key in {"cylinder", "disc", "disk"}:
            self.source = magpy.magnet.Cylinder(
                polarization=polarization_t,
                dimension=dimensions_m,
                position=position_m)
        elif shape_key in {"cuboid", "block"}:
            self.source = magpy.magnet.Cuboid(
                polarization=polarization_t,
                dimension=dimensions_m,
                position=position_m)
        else:
            raise ValueError("Magnet shape must be cylinder/disc or cuboid.")
        self.magpy = magpy
        if earth_field_xyz_mt is not None:
            self.earth = np.asarray(earth_field_xyz_mt, dtype=float) / 1000
        else:
            self.earth = np.asarray(earth_field_xyz_t, dtype=float)
        self.distance_uncertainty_mm = float(distance_uncertainty_mm)
        self.remanence_t = float(remanence_t)
        self.shape = shape_key
        self.dimensions_m = dimensions_m
        self.position_m = position_m

    def _field(self, x, y, z=0):
        return np.asarray(
            self.magpy.getB(
                self.source, (x / 1000, y / 1000, z / 1000)),
            dtype=float) + self.earth

    def sample(self, x_mm, y_mm, time_s=0):
        point = np.asarray([x_mm, y_mm, 0.0])
        field = self._field(*point)
        magnitude = float(np.linalg.norm(field))
        h = max(0.02, self.distance_uncertainty_mm / 4)
        gx = (np.linalg.norm(self._field(x_mm + h, y_mm)) -
              np.linalg.norm(self._field(x_mm - h, y_mm))) / (2 * h)
        gy = (np.linalg.norm(self._field(x_mm, y_mm + h)) -
              np.linalg.norm(self._field(x_mm, y_mm - h))) / (2 * h)
        direction = _unit(field)
        horizontal = float(np.linalg.norm(field[:2]))
        inclination = float(np.degrees(np.arctan2(field[2], horizontal)))
        plus = float(np.linalg.norm(self._field(x_mm, y_mm,
                                                self.distance_uncertainty_mm)))
        minus = float(np.linalg.norm(self._field(
            x_mm, y_mm, -self.distance_uncertainty_mm)))
        return FieldSample(
            direction, magnitude, (float(gx), float(gy)), inclination,
            {"vertical_distance_mm": self.distance_uncertainty_mm,
             "field_range_mt": sorted([minus, plus]),
             "dominant_sensitivity": "vertical distance to agar surface"},
            "T")

    def validation_ratio(self, point_xyz_mm, expected_mt: float) -> float:
        measured = float(np.linalg.norm(self._field(*point_xyz_mm)))
        return measured / (float(expected_mt) / 1000)

    def closed_form_on_axis_t(self, z_from_center_mm: float) -> float:
        if self.shape not in {"cylinder", "disc", "disk"}:
            raise ValueError("Closed-form axial validation is for cylinders.")
        diameter_m, length_m = self.dimensions_m
        radius = diameter_m / 2
        z = float(z_from_center_mm) / 1000
        upper = (z + length_m / 2) / np.sqrt(
            radius**2 + (z + length_m / 2)**2)
        lower = (z - length_m / 2) / np.sqrt(
            radius**2 + (z - length_m / 2)**2)
        return float(self.remanence_t * (upper - lower) / 2)

    def validate_on_axis(
        self, point_xyz_mm, z_from_center_mm: float,
        tolerance_fraction: float = 0.01,
    ) -> dict:
        computed = float(np.linalg.norm(self._field(*point_xyz_mm) - self.earth))
        expected = self.closed_form_on_axis_t(z_from_center_mm)
        error = abs(computed - expected) / max(abs(expected), 1e-15)
        return {
            "computed_t": computed, "closed_form_t": expected,
            "relative_error": error, "passes": error <= tolerance_fraction,
            "validation_level": "computational_regression"}
