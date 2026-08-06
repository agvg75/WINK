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


# The conditions a double-wrapped Merritt cage can be run in. These are NOT
# interchangeable and two of them look identical in the field record while
# controlling for completely different things, which is why the condition is
# named rather than inferred from the field strength.
COIL_CONDITIONS = {
    "field": (
        "Windings parallel, current on: Earth is cancelled and the declared "
        "field is imposed in its place."),
    "zero_field": (
        "Earth cancelled and nothing imposed. The animal is in near-zero "
        "field - a real stimulus condition, not an absence of one."),
    "sham_current": (
        "Windings ANTIPARALLEL, same current as the experiment. No net field, "
        "but identical Joule heating, vibration and acoustic noise. This "
        "controls for the coil, not for the field."),
    "ambient": (
        "Coils off entirely. The animal is in Earth's field. Distinct from "
        "zero_field, where Earth has been actively cancelled."),
}


class UniformFieldProvider(StimulusFieldProvider):
    """A double-wrapped Merritt coil cage: one field everywhere, no gradient.

    Andres's rig: the cage cancels Earth's field and then imposes a new one
    vectorially. Double wrapping is what makes the sham possible - running the
    same current antiparallel produces no net field while producing identical
    heating, vibration and acoustic noise.

    THIS IS THE CONDITION THAT SEPARATES TWO HYPOTHESES, which is why it is a
    provider of its own rather than a magnet with the gradient ignored. Under a
    permanent magnet, direction and magnitude are confounded BY CONSTRUCTION:
    an animal heading toward the magnet is simultaneously heading along the
    field vector and up a steeply rising magnitude, so orienting-to-direction
    and climbing-the-gradient predict the same track. A uniform field holds
    direction while removing the gradient.

    THREE NEAR-ZERO CONDITIONS THAT ARE NOT THE SAME THING, and collapsing
    them would destroy the design:

      - `ambient`      coils off, animal in Earth's ~50 uT field
      - `zero_field`   Earth actively cancelled, total near zero
      - `sham_current` no net field, but the coil is energised and warm

    A field record cannot tell the last two apart - both read zero tesla - so
    the condition is declared and carried, and `coil_energised` distinguishes
    them for anything downstream that cares about heat or vibration.

    THE FIELD MAY VARY IN TIME. Oscillation at a set frequency, and rotation by
    a set angle at a set time, are both supported, and `sample` honours
    `time_s` rather than ignoring it. Anything that pools direction over time
    is invalid under those, so `constant_direction` says so plainly.

    The gradient is EXACTLY zero, not approximately - a property of the model,
    where rounding noise would blur the distinction the provider exists to
    draw. The real cage's uniformity is a separate matter and lives in
    `uniformity_tolerance_percent`.
    """
    provider_type = "uniform_field"
    has_true_direction = True

    def __init__(self, *, direction_xyz=None, magnitude_t=None,
                 magnitude_mt=None, condition="field",
                 oscillation_hz=None, oscillation_phase_deg=0.0,
                 rotation_schedule=None,
                 earth_field_xyz_t=(0, 0, 0), earth_field_xyz_mt=None,
                 uniformity_tolerance_percent=None,
                 includes_earth_field=True, coil="merritt_double_wrapped"):
        if condition not in COIL_CONDITIONS:
            raise ValueError(
                f"Unknown coil condition {condition!r}. Use one of "
                f"{sorted(COIL_CONDITIONS)} - a sham and a zero field both "
                f"read zero tesla and control for entirely different things, "
                f"so the condition cannot be inferred from the field.")
        self.condition = condition
        self.coil = str(coil)
        self.energised = condition in {"field", "zero_field", "sham_current"}

        if earth_field_xyz_mt is not None:
            self.earth = np.asarray(earth_field_xyz_mt, dtype=float) / 1000
        else:
            self.earth = np.asarray(earth_field_xyz_t, dtype=float)
        self.includes_earth_field = bool(includes_earth_field)
        self.uniformity_tolerance_percent = (
            None if uniformity_tolerance_percent is None
            else float(uniformity_tolerance_percent))

        # A sham still needs its current declared, because the point of the
        # control is that the current MATCHES the experiment. A sham run at a
        # different current controls for nothing.
        needs_field = condition == "field"
        if magnitude_t is not None and magnitude_mt is not None:
            raise ValueError(
                "Give the field strength once, in tesla or millitesla, not "
                "both - two values that disagree cannot be reconciled later.")
        value = (float(magnitude_t) if magnitude_t is not None
                 else None if magnitude_mt is None
                 else float(magnitude_mt) / 1000.0)
        if needs_field:
            if value is None:
                raise ValueError(
                    "Field strength is required. Direction alone cannot say "
                    "whether the animals were in Earth's field or fifty times "
                    "it, and a null result is uninterpretable without it.")
            if value <= 0:
                raise ValueError(
                    f"Field strength {value} T is not positive. For a "
                    f"deliberate zero use condition='zero_field', which "
                    f"records that Earth was cancelled rather than that the "
                    f"field was weak.")
            direction = _unit(direction_xyz)
            if direction is None or len(direction) != 3:
                raise ValueError(
                    "A non-zero 3D field direction is required. The cage "
                    "geometry does not imply it - a field parallel to the "
                    "plate is the common case, not a safe default.")
        else:
            direction = _unit(direction_xyz) or (1.0, 0.0, 0.0)
        self.direction = direction
        self.magnitude_t = value

        self.oscillation_hz = (None if oscillation_hz in (None, "")
                               else float(oscillation_hz))
        if self.oscillation_hz is not None and self.oscillation_hz <= 0:
            raise ValueError(
                "Oscillation frequency must be positive. Zero is a static "
                "field, which is a different condition and should say so.")
        self.oscillation_phase_deg = float(oscillation_phase_deg)

        self.rotation_schedule = self._check_schedule(rotation_schedule)

    @staticmethod
    def _check_schedule(schedule):
        """Rotations as [{"at_s": 300, "rotate_deg": 90}, ...], cumulative."""
        if not schedule:
            return []
        out = []
        for step in schedule:
            if "at_s" not in step or "rotate_deg" not in step:
                raise ValueError(
                    "Each rotation needs 'at_s' and 'rotate_deg'. A rotation "
                    "without a time cannot be applied to a track, and one "
                    "without an angle is not a rotation.")
            out.append({"at_s": float(step["at_s"]),
                        "rotate_deg": float(step["rotate_deg"])})
        out.sort(key=lambda s: s["at_s"])
        if out[0]["at_s"] < 0:
            raise ValueError("A rotation cannot happen before the recording.")
        return out

    # ----------------------------------------------------------------- #
    @property
    def is_time_varying(self):
        return bool(self.oscillation_hz or self.rotation_schedule)

    @property
    def constant_direction(self):
        """False when the field turns or reverses during the recording.

        Anything that pools heading-relative-to-field over the whole track is
        invalid when this is False - the reference it is measured against
        moved. Reported rather than silently handled, because the right
        response depends on the analysis.
        """
        return not self.is_time_varying

    def rotation_at(self, time_s):
        """Cumulative rotation applied by this time, in degrees."""
        return sum(s["rotate_deg"] for s in self.rotation_schedule
                   if s["at_s"] <= float(time_s))

    def applied_at(self, time_s=0.0):
        """The imposed field vector at this instant, before Earth."""
        if self.condition in {"zero_field", "sham_current", "ambient"}:
            return np.zeros(3, dtype=float)
        vec = np.asarray(self.direction, dtype=float) * self.magnitude_t
        deg = self.rotation_at(time_s)
        if deg:
            rad = np.radians(deg)
            c, s = np.cos(rad), np.sin(rad)
            # Rotation in the plate plane; the vertical component is untouched
            # because the cage turns the field within the plate, not about it.
            vec = np.asarray([vec[0] * c - vec[1] * s,
                              vec[0] * s + vec[1] * c, vec[2]])
        if self.oscillation_hz:
            phase = np.radians(self.oscillation_phase_deg)
            vec = vec * float(np.sin(2 * np.pi * self.oscillation_hz *
                                     float(time_s) + phase))
        return vec

    def total_field(self, time_s=0.0):
        applied = self.applied_at(time_s)
        if self.condition == "ambient":
            return self.earth
        # The Merritt cage cancels Earth and imposes in its place, so the
        # applied vector IS the total. A rig that adds to Earth instead sets
        # includes_earth_field=False.
        return applied if self.includes_earth_field else applied + self.earth

    def sample(self, x_mm, y_mm, time_s=0):
        field = self.total_field(time_s)
        magnitude = float(np.linalg.norm(field))
        horizontal = float(np.linalg.norm(field[:2]))
        inclination = float(np.degrees(np.arctan2(field[2], horizontal)))
        tol = self.uniformity_tolerance_percent
        unc = {
            "condition": self.condition,
            "condition_means": COIL_CONDITIONS[self.condition],
            "coil": self.coil,
            "coil_energised": self.energised,
            "gradient_is_zero_by_construction": True,
            "why": ("A uniform field has no gradient anywhere, which is what "
                    "makes it the control that separates orienting to field "
                    "direction from climbing field magnitude."),
            "uniformity_tolerance_percent": tol,
            "uniformity_unverified": tol is None,
            "includes_earth_field": self.includes_earth_field,
            "constant_direction": self.constant_direction,
            "dominant_sensitivity": (
                "cage uniformity across the plate area" if tol is not None
                else "cage uniformity, which has not been declared or measured"),
        }
        if self.oscillation_hz:
            unc["oscillation_hz"] = self.oscillation_hz
            unc["time_varying_warning"] = (
                f"The field oscillates at {self.oscillation_hz} Hz, so its "
                f"direction reverses every half cycle and its time-average is "
                f"zero. Any statistic pooling heading relative to the field "
                f"over the whole track is measuring against a reference that "
                f"moved; align to phase or analyse per half-cycle.")
        if self.rotation_schedule:
            unc["rotation_schedule"] = list(self.rotation_schedule)
            unc["rotation_applied_deg"] = self.rotation_at(time_s)
            unc["time_varying_warning"] = (
                f"The field is rotated during the recording "
                f"({len(self.rotation_schedule)} step(s)). Heading relative to "
                f"the field must be computed per segment against the field at "
                f"that time, not against the starting direction.")
        return FieldSample(
            _unit(field), magnitude,
            (0.0, 0.0),          # exactly zero: the defining property
            inclination, unc, "T")

    def describe(self):
        bits = [f"{self.coil}", self.condition]
        if self.magnitude_t and self.condition == "field":
            bits.append(f"{self.magnitude_t * 1000:.4g} mT")
        if self.oscillation_hz:
            bits.append(f"oscillating {self.oscillation_hz} Hz")
        if self.rotation_schedule:
            bits.append(f"{len(self.rotation_schedule)} rotation(s)")
        return ", ".join(bits)


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
                "Magnetic analysis needs the magpylib library, which is not "
                "installed on this machine.\n\n"
                "Re-run Setup_Lab_Tools.bat to install it. An app update will "
                "NOT add it - updates replace program files only, they do not "
                "install libraries.") from exc
        # The pin in Setup_Lab_Tools.bat protects a fresh install; this
        # protects a machine that already had magpylib from somewhere else.
        # v4 accepted magnetization= in mT/mm and v5 takes polarization= in
        # T/m, so the wrong major version does not fail here - it returns
        # field values that are wrong by orders of magnitude and look fine.
        major = str(getattr(magpy, "__version__", "0")).split(".")[0]
        if major != "5":
            raise RuntimeError(
                f"Magnetic analysis needs magpylib 5.x; this machine has "
                f"{getattr(magpy, '__version__', 'an unknown version')}.\n\n"
                f"The field calculation passes polarization in tesla with "
                f"dimensions in metres, which is the 5.x convention. Another "
                f"major version would not raise an error - it would report "
                f"plausible field strengths that are simply wrong.\n\n"
                f"Re-run Setup_Lab_Tools.bat to install the pinned version.")
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
