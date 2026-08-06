"""What every plate-migration assay shares: a population of worms on a plate.

Andres: magnetotaxis, chemotaxis and thermotaxis "all share a population of
worms migrating in an assay plate. We should not have to redo each one every
time." This is that shared layer.

THESE FOUR FUNCTIONS WERE NEVER MAGNETIC. They lived in magnetotaxis.py
because that is the assay that got built out first - 418 lines against
chemotaxis's 49 and thermotaxis's 41 - and so it accumulated machinery that
the other two assays simply went without. Time off OP50, movement state at
plate opening, per-segment covariates and the toward/away regime split are
facts about worms on a plate, not about a magnetic field.

`regime_comparison` is the clearest case: its docstring calls it a "field-flip
analog", but its parameter is `source_xy_mm` - a POINT SOURCE, which is
chemotaxis's native geometry, implemented inside magnetotaxis and unavailable
to chemotaxis.

WHAT STAYS PER-ASSAY IS STIMULUS GEOMETRY, and only that: a magnetic vector
field, a chemical point source, a thermal linear gradient.

MOVED VERBATIM. The bodies below are byte-identical to the magnetotaxis
originals, and magnetotaxis.py imports them back so every existing caller
keeps working. tests/test_plate_assay_pin.py holds the complete pre-move
output of all four and compares it byte for byte - the magnetotaxis results
are the ones Andres has published against, so "probably equivalent" is not
good enough. Generalising the geometry is a SEPARATE step, deliberately, so
that the pin can tell a relocation from a change.
"""
from __future__ import annotations

from datetime import datetime
import numpy as np

from orientation_core import mean_resultant, wrap_degrees


class GeometryError(Exception):
    """Refusals that name the consequence."""


# --------------------------------------------------------------------------- #
# Stimulus geometry - the ONLY part that differs between these assays
# --------------------------------------------------------------------------- #
# Each geometry answers one question: given a position on the plate, how far is
# the animal from the condition it prefers? "Toward" is then simply that scalar
# falling, and the identical statistics run for all three assays.
#
# A POSITION CANNOT EXPRESS THIS IN GENERAL, which is why the old
# `source_xy_mm` parameter had to go. For a thermal gradient the preferred
# condition is a TEMPERATURE, and the animal's cultivation history decides it -
# two plates on the same rig with worms reared at 15 and 20 degrees have
# opposite "toward" directions and identical geometry. The preferred
# temperature may not even lie on the plate.
class PointSource:
    """Chemotaxis: an odour spot. Preference falls with distance to it.

    Also the exact behaviour of the original `regime_comparison(rows, source)`,
    which is what keeps the move behaviour-preserving.
    """

    kind = "point_source"

    def __init__(self, xy_mm):
        self.xy = np.asarray(xy_mm, dtype=float)
        if self.xy.shape != (2,):
            raise GeometryError(
                f"A point source needs an (x, y) in mm, got {xy_mm!r}. "
                f"Guessing a spot location would silently redefine which "
                f"worms count as moving toward it.")

    def preference(self, x_mm, y_mm):
        return float(np.linalg.norm(
            np.asarray([x_mm, y_mm], dtype=float) - self.xy))

    def describe(self):
        return f"point source at ({self.xy[0]:.1f}, {self.xy[1]:.1f}) mm"


class LinearGradient:
    """Thermotaxis: two temperatures, one at each end, worms in the middle.

    Andres: "they crawl towards cultivation temp." So the target end is a fact
    about the ANIMAL, not the plate, and it cannot be inferred from geometry -
    which is why cultivation_c is required rather than defaulted.

    Preference is |T(x) - T_cultivation| along the gradient axis.
    """

    kind = "linear_gradient"

    def __init__(self, *, cold_xy_mm, hot_xy_mm, cold_c, hot_c, cultivation_c):
        if cultivation_c is None or cultivation_c == "":
            raise GeometryError(
                "Cultivation temperature is required for thermotaxis. Worms "
                "crawl toward the temperature they were reared at, so without "
                "it 'toward' is undefined - and it cannot be recovered from "
                "the plate, because two plates with identical geometry and "
                "differently reared worms have opposite preferred ends.")
        self.cold = np.asarray(cold_xy_mm, dtype=float)
        self.hot = np.asarray(hot_xy_mm, dtype=float)
        self.cold_c, self.hot_c = float(cold_c), float(hot_c)
        self.cultivation_c = float(cultivation_c)
        self.axis = self.hot - self.cold
        self.span = float(np.linalg.norm(self.axis))
        if self.span <= 0:
            raise GeometryError(
                "The two gradient ends are at the same position, so there is "
                "no axis and every worm would score identically.")
        if self.hot_c == self.cold_c:
            raise GeometryError(
                f"Both ends are at {self.hot_c} C - this is an isothermal "
                f"plate, not a gradient. Any 'toward' score would be reading "
                f"noise as thermotaxis.")

    def temperature_at(self, x_mm, y_mm):
        """Linear interpolation along the axis, extrapolating past the ends."""
        rel = np.asarray([x_mm, y_mm], dtype=float) - self.cold
        u = float(np.dot(rel, self.axis)) / (self.span ** 2)
        return self.cold_c + u * (self.hot_c - self.cold_c)

    def preference(self, x_mm, y_mm):
        return abs(self.temperature_at(x_mm, y_mm) - self.cultivation_c)

    def within_range(self):
        """Is the preferred temperature actually ON the plate?

        If cultivation temperature sits outside the two end temperatures, every
        worm's preferred direction is the same end and the assay offers no
        choice. The animals will still migrate and the index will still come
        out non-zero, which is exactly why this has to be checked rather than
        left to look like a result.
        """
        lo, hi = sorted((self.cold_c, self.hot_c))
        inside = lo <= self.cultivation_c <= hi
        return {
            "cultivation_c": self.cultivation_c,
            "range_c": [lo, hi],
            "within": bool(inside),
            "why": (None if inside else
                    f"Cultivation temperature {self.cultivation_c} C lies "
                    f"outside the plate range {lo}-{hi} C. Every worm's "
                    f"preferred end is the same one, so the plate offers no "
                    f"choice and a non-zero index measures the gradient, not "
                    f"a preference."),
        }

    def describe(self):
        return (f"linear gradient {self.cold_c}-{self.hot_c} C, "
                f"cultivated at {self.cultivation_c} C")


class VectorField:
    """Magnetotaxis: a direction, not a place.

    Preference falls with displacement along the field vector, so a worm that
    travels down-field is "toward". Distance to a point is meaningless here -
    the field has no centre on the plate.
    """

    kind = "vector_field"

    def __init__(self, direction_deg):
        if direction_deg is None:
            raise GeometryError(
                "A field direction is required. Without it there is no axis "
                "to score displacement along.")
        theta = np.radians(float(direction_deg))
        self.unit = np.asarray([np.cos(theta), np.sin(theta)], dtype=float)
        self.direction_deg = float(direction_deg)

    def preference(self, x_mm, y_mm):
        # Negated so that moving ALONG the field lowers the scalar, matching
        # the "preference falls when the animal approaches what it wants"
        # convention the other two geometries use.
        return -float(np.dot(np.asarray([x_mm, y_mm], dtype=float), self.unit))

    def describe(self):
        return f"vector field at {self.direction_deg:.1f} deg"


def resolve_time_off_op50_offset(
    *, elapsed_s=None, food_removal_clock=None, assay_start_clock=None,
):
    """Return the physiological-clock offset without inventing a zero."""
    if elapsed_s is not None and elapsed_s != "":
        value = float(elapsed_s)
        if value < 0:
            raise ValueError("Time off OP50 cannot be negative.")
        return value
    if food_removal_clock and assay_start_clock:
        parsed = []
        for value in (food_removal_clock, assay_start_clock):
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    parsed.append(datetime.strptime(str(value), fmt))
                    break
                except ValueError:
                    continue
            else:
                raise ValueError("Clock times must be HH:MM or HH:MM:SS.")
        delta = (parsed[1] - parsed[0]).total_seconds()
        return float(delta + 24 * 3600 if delta < 0 else delta)
    return None

def _initial_states(rows, opening_s=30.0, speed_threshold=0.05,
                    angular_velocity_threshold=30.0):
    grouped, output = {}, {}
    for row in rows:
        grouped.setdefault(
            (str(row["plate_id"]), str(row.get("worm_id"))), []).append(row)
    for key, group in grouped.items():
        group = sorted(group, key=lambda item: float(item["time_s"]))
        start = float(group[0]["time_s"])
        opening = [row for row in group
                   if float(row["time_s"]) <= start + float(opening_s)]
        if len(opening) < 3 or float(opening[-1]["time_s"]) - start < opening_s / 2:
            output[key] = "unclassified"
            continue
        speeds, turns = [], []
        for left, right in zip(opening, opening[1:]):
            dt = float(right["time_s"]) - float(left["time_s"])
            if dt <= 0:
                continue
            speeds.append(np.hypot(
                float(right["x_mm"]) - float(left["x_mm"]),
                float(right["y_mm"]) - float(left["y_mm"])) / dt)
            turns.append(abs(float(wrap_degrees(
                float(right["heading_deg"]) -
                float(left["heading_deg"])))) / dt)
        output[key] = (
            "roaming" if speeds and np.median(speeds) >= speed_threshold
            and np.median(turns) <= angular_velocity_threshold
            else "dwelling" if speeds else "unclassified")
    return output

def build_segment_covariates(
    tracks, orientation_segments, departure_rows, plate_food_offset_s,
    *, per_worm_food_offsets_s=None, initial_state_window_s=30.0,
    dwell_speed_threshold_mm_s=0.02, spine_quality_threshold=0.7,
    pick_state=None,
):
    """Keep full-resolution predictors; summaries are downstream."""
    departures = {str(row.get("worm_id")): row for row in departure_rows}
    initial = _initial_states(tracks, opening_s=initial_state_window_s)
    lookup = {
        (str(row["plate_id"]), str(row.get("worm_id")), float(row["time_s"])):
            dict(row) for row in orientation_segments}
    per_worm_food_offsets_s = per_worm_food_offsets_s or {}
    grouped = {}
    for row in tracks:
        grouped.setdefault(
            (str(row["plate_id"]), str(row.get("worm_id"))), []).append(row)
    output, events = [], []
    for key, group in grouped.items():
        group = sorted(group, key=lambda item: float(item["time_s"]))
        run_length = 0.0
        for index, row in enumerate(group):
            time_s = float(row["time_s"])
            enriched = lookup.get((key[0], key[1], time_s))
            if enriched is None:
                continue
            dt = distance = angular_velocity = 0.0
            if index:
                previous = group[index - 1]
                dt = time_s - float(previous["time_s"])
                if dt > 0:
                    distance = float(np.hypot(
                        float(row["x_mm"]) - float(previous["x_mm"]),
                        float(row["y_mm"]) - float(previous["y_mm"])))
                    angular_velocity = float(wrap_degrees(
                        float(row["heading_deg"]) -
                        float(previous["heading_deg"]))) / dt
            velocity = row.get("forward_velocity_mm_s")
            velocity = float(velocity) if velocity is not None else (
                distance / dt if dt > 0 else 0.0)
            reversing = bool(row.get("reversing", velocity < 0))
            run_length = 0.0 if reversing else run_length + distance
            departure = departures.get(key[1], {})
            committed = departure.get("committed_departure_s")
            worm_offset = per_worm_food_offsets_s.get(
                key[1], plate_food_offset_s)
            spine_quality = row.get("spine_quality")
            event_candidate = bool(row.get(
                "reorientation_event", abs(angular_velocity) >= 90))
            mode = None
            if event_candidate:
                if spine_quality is None or float(spine_quality) < spine_quality_threshold:
                    mode = "unclassified"
                elif bool(row.get("omega_turn", False)):
                    mode = "omega_turn"
                elif reversing and bool(row.get(
                        "turning", abs(angular_velocity) >= 30)):
                    mode = "reversal_then_turn_pirouette"
                elif reversing:
                    mode = "reversal"
                else:
                    mode = "shallow_gradual_turn"
                events.append({
                    "plate_id": key[0], "worm_id": key[1], "time_s": time_s,
                    "turning_mode": mode, "spine_quality": spine_quality,
                    "validation_level": "computational_regression"})
            enriched.update({
                "assay_elapsed_s": time_s,
                "time_off_op50_s": (
                    None if worm_offset is None else float(worm_offset) + time_s),
                "forward_velocity_mm_s": velocity,
                "absolute_angular_velocity_deg_s": abs(angular_velocity),
                "signed_track_curvature_deg_s": angular_velocity,
                "turning_frequency_hz": (
                    float(row.get("turning", abs(angular_velocity) >= 30)) / dt
                    if dt > 0 else 0.0),
                "reversal_rate_hz": float(reversing) / dt if dt > 0 else 0.0,
                "run_length_mm": run_length,
                "dwell": velocity >= 0 and
                    abs(velocity) < dwell_speed_threshold_mm_s,
                "time_since_committed_departure_s": (
                    None if committed is None or time_s < float(committed)
                    else time_s - float(committed)),
                "initial_state": initial.get(key, "unclassified"),
                "pick_state": (
                    pick_state.get(key[1]) if isinstance(pick_state, dict)
                    else pick_state),
                "turning_mode": mode,
            })
            output.append(enriched)
    return output, events

def regime_comparison(segment_rows, source_xy_mm=None, min_worms_per_regime=3,
                      rotation_tolerance_deg=30.0,
                      concentration_tolerance=0.2, geometry=None):
    """Plate-first internal field-flip analog with explicit thin-cell refusal.

    `geometry` is any stimulus geometry (see PointSource, LinearGradient,
    VectorField). Passing `source_xy_mm` instead is the original call and is
    exactly equivalent to PointSource(source_xy_mm) - distance to a point -
    which is why every pre-existing caller is unaffected.

    A worm is "toward" if its PREFERENCE SCALAR fell over the track: it ended
    nearer the condition it prefers than it started. For a point source that
    is distance to the spot, which is what this function always computed; for
    a thermal gradient it is |T(x) - T_cultivation|, which no point on the
    plate can express, because the preferred temperature may lie outside the
    gradient entirely.
    """
    if geometry is None:
        if source_xy_mm is None:
            raise ValueError(
                "regime_comparison needs either a geometry or a source "
                "position. Without one, 'toward' has no definition and the "
                "split would be arbitrary.")
        geometry = PointSource(source_xy_mm)
    worms = {}
    for row in segment_rows:
        worms.setdefault(
            (str(row["plate_id"]), str(row["worm_id"])), []).append(row)
    by_plate = {}
    for (plate, worm), rows in worms.items():
        rows = sorted(rows, key=lambda item: float(item["time_s"]))
        start = geometry.preference(rows[0]["x_mm"], rows[0]["y_mm"])
        end = geometry.preference(rows[-1]["x_mm"], rows[-1]["y_mm"])
        regime = "toward" if start > end else "away"
        by_plate.setdefault(plate, {"toward": [], "away": []})[regime].append(
            {"worm_id": worm, "rows": rows})
    results = {}
    for plate, regimes in by_plate.items():
        summary = {}
        for name, members in regimes.items():
            angles = [row["angle_to_vector_deg"] for member in members
                      for row in member["rows"]
                      if row.get("angle_to_vector_deg") is not None]
            curvature = [row["signed_track_curvature_deg_s"]
                         for member in members for row in member["rows"]]
            summary[name] = {
                "n_worms": len(members), "held_angle": mean_resultant(angles),
                "mean_signed_track_curvature_deg_s": (
                    float(np.mean(curvature)) if curvature else None)}
        if min(summary["toward"]["n_worms"],
               summary["away"]["n_worms"]) < min_worms_per_regime:
            results[plate] = {
                "status": "withheld",
                "reason": "Too few worms in one regime for comparison.",
                "regimes": summary}
            continue
        toward, away = summary["toward"]["held_angle"], summary["away"]["held_angle"]
        separation = abs(float(wrap_degrees(
            away["mean_angle_deg"] - toward["mean_angle_deg"])))
        rotation_error = abs(180.0 - separation)
        c1 = summary["toward"]["mean_signed_track_curvature_deg_s"]
        c2 = summary["away"]["mean_signed_track_curvature_deg_s"]
        chirality = c1 is not None and c2 is not None and (
            c1 == 0 or c2 == 0 or np.sign(c1) == np.sign(c2))
        concentration_difference = abs(
            toward["resultant_length"] - away["resultant_length"])
        results[plate] = {
            "status": "computed", "regimes": summary,
            "concentration_difference": concentration_difference,
            "concentrations_comparable":
                concentration_difference <= concentration_tolerance,
            "preferred_angle_separation_deg": separation,
            "rotation_error_from_180_deg": rotation_error,
            "rotation_not_reflection_supported":
                rotation_error <= rotation_tolerance_deg,
            "chirality_conserved": bool(chirality),
            "decisive_internal_field_flip_analog": bool(
                concentration_difference <= concentration_tolerance and
                rotation_error <= rotation_tolerance_deg and chirality)}
    computed = [row for row in results.values()
                if row["status"] == "computed"]
    return {
        "inferential_unit": "plate", "per_plate": results,
        "plates_computed": len(computed),
        "plates_withheld": len(results) - len(computed),
        "across_plate": {
            "status": "computed" if len(computed) >= 2 else "withheld",
            "reason": None if len(computed) >= 2 else
                "At least two qualifying plates are required.",
            "mean_rotation_error_deg": (
                float(np.mean([row["rotation_error_from_180_deg"]
                               for row in computed]))
                if len(computed) >= 2 else None),
            "fraction_conserved_chirality": (
                float(np.mean([row["chirality_conserved"]
                               for row in computed]))
                if len(computed) >= 2 else None)}}
