"""S5: per-worm departure clocks, dwell, re-entry, and censoring."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class DepartureResult:
    worm_id: str
    droplet_clearance_s: float | None
    first_excursion_s: float | None
    committed_departure_s: float | None
    departure_censored: bool
    censor_time_s: float
    reentry_count: int
    central_dwell_s: float
    time_since_food_at_departure_s: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def analyze_departure(
    worm_id: str,
    times_s,
    inside_start_roi,
    radial_distance,
    *,
    droplet_clear,
    minimum_commitment_s: float = 2.0,
    minimum_outward_progress: float = 0.0,
    time_since_food_at_recording_start_s: float | None = None,
) -> DepartureResult:
    """Analyze reviewed tracks without treating one boundary wobble as departure."""
    times = np.asarray(times_s, dtype=float)
    inside = np.asarray(inside_start_roi, dtype=bool)
    radial = np.asarray(radial_distance, dtype=float)
    clear = np.asarray(droplet_clear, dtype=bool)
    if not (len(times) == len(inside) == len(radial) == len(clear)) or len(times) < 2:
        raise ValueError("Departure inputs must be equal-length with >=2 frames.")
    if np.any(np.diff(times) <= 0):
        raise ValueError("times_s must be strictly increasing.")
    dt = np.diff(times, append=times[-1] + np.median(np.diff(times)))
    central_dwell = float(np.sum(dt[inside]))
    clear_indices = np.flatnonzero(clear)
    clearance = float(times[clear_indices[0]]) if clear_indices.size else None
    exit_indices = np.flatnonzero(inside[:-1] & ~inside[1:]) + 1
    first_excursion = float(times[exit_indices[0]]) if exit_indices.size else None
    reentries = int(np.sum((~inside[:-1]) & inside[1:]))

    committed = None
    for index in exit_indices:
        end_time = times[index] + minimum_commitment_s
        end = int(np.searchsorted(times, end_time, side="left"))
        if end >= len(times):
            continue
        remains_outside = not np.any(inside[index:end + 1])
        progress = radial[end] - radial[index]
        if remains_outside and progress > minimum_outward_progress:
            committed = float(times[index])
            break
    food_clock = (
        None if committed is None or time_since_food_at_recording_start_s is None
        else float(time_since_food_at_recording_start_s) + committed)
    return DepartureResult(
        str(worm_id), clearance, first_excursion, committed,
        committed is None, float(times[-1]), reentries, central_dwell, food_clock)


def survival_rows(results: list[DepartureResult]) -> list[dict]:
    """Return event/censor rows suitable for Kaplan-Meier or Cox analysis."""
    return [{
        "worm_id": result.worm_id,
        "duration_s": (result.committed_departure_s
                       if result.committed_departure_s is not None
                       else result.censor_time_s),
        "event_observed": not result.departure_censored,
    } for result in results]
