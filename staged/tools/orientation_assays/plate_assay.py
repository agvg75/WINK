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

NEXT ROUND - PRESENTATION, NOT ASSAY (Andres, 2026-08-05). The three
geometries here are one presentation each, and that is the wrong axis. Any of
these assays can be run several ways:

  - RADIAL rather than linear, with the stimulus homogeneous at one end
  - a POINT SOURCE
  - for magnetotaxis specifically: a linear field in a Helmholtz-style cage
    versus a single N42 magnet, which are a uniform field and a steep
    near-field dipole respectively

"The stimulus presentation changes the geometry dramatically." So geometry
belongs to the PRESENTATION, not to the assay - thermotaxis-radial and
chemotaxis-radial share a geometry that thermotaxis-linear does not. The
current three classes are the presentations this lab runs most, not a
taxonomy, and naming them after assays would be a mistake to bake in. When
this is built, expect the config to name a presentation and the assay to
supply only what the stimulus IS.

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

# Andres: "Time off food also affects other assays. Basically any assay where
# worms are off food. Basal slowing becomes enhanced basal slowing after
# [~30] minutes off food."
#
# The threshold is not cosmetic - it changes which behaviour is being measured
# and which pathway produces it. Sawin, Ranganathan & Horvitz (2000) report
# basal slowing in well-fed animals (dopamine-dependent) and ENHANCED slowing
# after food deprivation (serotonin-dependent). Crossing it mid-experiment
# means the early and late plates are not measuring the same thing.
#
# A PARAMETER, NOT A CONSTANT, because it is an empirical figure that belongs
# to the assay and the strain rather than to the software.
ENHANCED_SLOWING_S = 30 * 60


def food_state(offset_s, threshold_s=ENHANCED_SLOWING_S):
    """Which feeding regime an animal is in, given time off food.

    Returns "unknown" rather than assuming "fed" when nothing was recorded.
    Defaulting to fed would silently assert the most common case, and the
    plates that break an experiment are the unusual ones.
    """
    if offset_s is None or offset_s == "":
        return {
            "regime": "unknown", "time_off_food_s": None,
            "threshold_s": threshold_s,
            "why": ("Time off food was not recorded, so the feeding regime "
                    "is unknown. It is not assumed to be 'fed' - that would "
                    "assert the common case over exactly the plates most "
                    "likely to be anomalous."),
        }
    value = float(offset_s)
    past = value >= threshold_s
    return {
        "regime": "food_deprived" if past else "recently_fed",
        "time_off_food_s": value,
        "threshold_s": threshold_s,
        "minutes_off_food": round(value / 60.0, 1),
        "why": (f"{value / 60.0:.1f} min off food, "
                f"{'past' if past else 'short of'} the "
                f"{threshold_s / 60.0:.0f} min threshold. "
                + ("Enhanced slowing is expected here; comparing these plates "
                   "with recently-fed ones compares two different behaviours "
                   "produced by two different pathways."
                   if past else
                   "Basal slowing is expected. Plates that cross the "
                   "threshold mid-experiment change regime partway through.")),
    }


def population_layer(
    *, tracks, segments, geometry=None, departure_rows=(),
    time_since_food_removal_s=None, food_removal_clock=None,
    assay_start_clock=None, per_worm_food_offsets_s=None,
    initial_state_window_s=30.0, pick_state=None, min_worms_per_regime=3,
    enhanced_slowing_s=ENHANCED_SLOWING_S, stimulus=None,
    n_placed=None, n_tracked=None, plate_area_cm2=None,
):
    """Everything a plate-migration assay gets for free. One call per assay.

    This is the point of the whole exercise: chemotaxis and thermotaxis each
    call this once and receive the time-off-food clock, the movement state at
    plate opening, per-segment covariates and the toward/away split - all of
    which existed only inside magnetotaxis. Wiring the four functions into
    each assay separately would have rebuilt the duplication this removes.

    NOTHING HERE IS SILENTLY OPTIONAL. A missing food clock does not simply
    omit a column; it records that the column is missing and what that costs,
    because "time_off_op50_s: null" in a results file is indistinguishable
    from a worm that was never off food.
    """
    out = {"geometry": geometry.describe() if geometry else None,
           "geometry_kind": getattr(geometry, "kind", None),
           "warnings": []}

    food_offset_s = resolve_time_off_op50_offset(
        elapsed_s=time_since_food_removal_s,
        food_removal_clock=food_removal_clock,
        assay_start_clock=assay_start_clock)
    out["time_off_op50_at_start_s"] = food_offset_s
    out["food_state"] = food_state(food_offset_s,
                                   threshold_s=enhanced_slowing_s)
    # A plate that STARTS below the threshold and ENDS above it changed
    # behavioural regime partway through, which no single label can express.
    if food_offset_s is not None and tracks:
        last_s = max(float(r.get("time_s", 0)) for r in tracks)
        if (food_offset_s < enhanced_slowing_s <= food_offset_s + last_s):
            crossing = (enhanced_slowing_s - food_offset_s)
            out["food_state"]["crosses_threshold_at_s"] = crossing
            out["warnings"].append(
                f"This plate crosses the {enhanced_slowing_s / 60:.0f} min "
                f"food-deprivation threshold {crossing / 60:.1f} min into the "
                f"recording, so it is recently-fed at the start and food-"
                f"deprived at the end. A single regime label would be wrong "
                f"for one half of it; split the analysis or note the change.")
    if food_offset_s is None:
        out["warnings"].append(
            "No time off OP50 was given, so every covariate row carries a "
            "null food clock. Worms change behaviour steadily after removal "
            "from food, so plates run at different delays are not comparable "
            "and the difference will look like a treatment effect.")

    out["initial_states"] = {
        f"{k[0]}|{k[1]}": v for k, v in sorted(
            _initial_states(tracks, opening_s=initial_state_window_s).items())}

    rows, events = build_segment_covariates(
        tracks, segments, list(departure_rows), food_offset_s,
        per_worm_food_offsets_s=per_worm_food_offsets_s,
        initial_state_window_s=initial_state_window_s,
        pick_state=pick_state)
    out["covariate_rows"] = rows
    out["covariate_events"] = events

    if geometry is None:
        out["regimes"] = None
        out["warnings"].append(
            "No stimulus geometry was supplied, so worms were not split into "
            "toward and away. The covariates above are still valid; only the "
            "directional comparison is missing.")
    else:
        out["regimes"] = regime_comparison(
            segments, geometry=geometry,
            min_worms_per_regime=min_worms_per_regime)

    # A gradient whose preferred temperature is off the plate still produces a
    # perfectly good-looking index, which is exactly why it is checked here
    # rather than left for someone to notice.
    if hasattr(geometry, "within_range"):
        rng = geometry.within_range()
        out["stimulus_range_check"] = rng
        if not rng["within"]:
            out["warnings"].append(rng["why"])

    if stimulus is not None or getattr(geometry, "kind", None) == "point_source":
        out["stimulus"] = describe_stimulus(stimulus)
        out["warnings"].extend(out["stimulus"]["warnings"])

    # n tracked is OBSERVED, never declared - counting the distinct worm ids
    # in the data is the only way the declared and actual numbers can disagree,
    # and that disagreement is the whole point.
    observed = len({(str(r.get("plate_id")), str(r.get("worm_id")))
                    for r in tracks})
    out["population"] = population_size(
        n_placed=n_placed,
        n_tracked=observed if n_tracked is None else n_tracked,
        plate_area_cm2=plate_area_cm2)
    out["warnings"].extend(out["population"]["warnings"])
    return out


# Andres: chemotaxis "should also request stimulus nature and concentration
# (diacetyl, ethanol, OP50 etc)."
#
# A chemotaxis index of 0.4 means nothing without them. Diacetyl is attractive
# at low concentration and repulsive at high; the same compound and the same
# animal give opposite signs, so an index recorded without concentration cannot
# be compared with anything, including a repeat of itself.
STIMULUS_FIELDS = ("compound", "concentration", "concentration_units")


# Andres: "Another variable that matters: number of animals in assay."
#
# It matters twice over, and the second way is the dangerous one.
#
# FIRST, DENSITY IS A TREATMENT. Worms on a plate are not independent - they
# leave tracks others follow, deplete what they walk through, and at high
# density their pheromone environment changes what they do. Twenty animals and
# two hundred on the same plate are two different experiments.
#
# SECOND, AND WORSE: n PLACED and n TRACKED are different numbers, and the gap
# between them is not noise. Worms that crawled off the agar, died, burrowed,
# or were never detected are missing from the index - and they are not missing
# at random, because the ones that leave are disproportionately the ones that
# were moving fastest and furthest. An index computed over the survivors alone
# is a survivorship-biased estimate that looks completely normal.
def population_size(n_placed=None, n_tracked=None, plate_area_cm2=None,
                    min_recovery=0.8):
    """Declared vs observed animals, and what the gap between them costs."""
    out = {"n_placed": n_placed, "n_tracked": n_tracked, "warnings": []}
    if n_placed is None:
        out["warnings"].append(
            "The number of animals placed on the plate was not recorded, so "
            "there is no way to tell how many are missing from the results. "
            "Worms that crawl off, burrow or die are not lost at random - "
            "the ones that leave are disproportionately the fastest and "
            "furthest travelling, so an index over the survivors is biased "
            "in the direction of the effect being measured.")
        return out
    n_placed = int(n_placed)
    if n_placed <= 0:
        raise ValueError(
            f"n_placed={n_placed} is not a count of animals. A zero or "
            f"negative population would make every per-animal rate infinite "
            f"or negative.")
    if plate_area_cm2:
        out["density_per_cm2"] = round(n_placed / float(plate_area_cm2), 3)
    if n_tracked is None:
        out["warnings"].append(
            f"{n_placed} animals were placed but the number actually tracked "
            f"was not recorded, so recovery cannot be checked.")
        return out
    n_tracked = int(n_tracked)
    out["recovery"] = round(n_tracked / n_placed, 3)
    out["n_missing"] = n_placed - n_tracked
    if n_tracked > n_placed:
        out["warnings"].append(
            f"{n_tracked} animals were tracked but only {n_placed} were "
            f"placed. Either the count is wrong or the tracker is splitting "
            f"one animal into several, which inflates every per-animal "
            f"statistic downstream.")
    elif out["recovery"] < min_recovery:
        out["warnings"].append(
            f"Only {n_tracked} of {n_placed} animals were tracked "
            f"({out['recovery']:.0%}). The {out['n_missing']} missing are not "
            f"a random sample - animals that crawl off or burrow are "
            f"disproportionately the fastest and furthest travelling, so the "
            f"index over the remainder is biased toward the effect being "
            f"measured. Find out where they went before trusting it.")
    return out


def describe_stimulus(stimulus):
    """Record what the worms were offered. Warn, do not refuse.

    Deliberately not a hard refusal: someone re-analysing an old plate whose
    notebook is lost should still be able to run it, with the gap recorded.
    Refusing outright would push people to type a placeholder, and an invented
    concentration is worse than an acknowledged missing one.
    """
    given = dict(stimulus or {})
    missing = [f for f in STIMULUS_FIELDS
               if given.get(f) in (None, "", [])]
    out = {"given": given, "missing": missing,
           "complete": not missing, "warnings": []}
    if not given:
        out["warnings"].append(
            "No stimulus was recorded. A chemotaxis index is uninterpretable "
            "without the compound and its concentration - diacetyl attracts "
            "at low concentration and repels at high, so the same compound "
            "and the same animal can give opposite signs.")
    elif missing:
        out["warnings"].append(
            f"The stimulus record is missing: {', '.join(missing)}. "
            f"Without concentration in particular the index cannot be "
            f"compared with another plate, including a repeat of this one.")
    return out


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
