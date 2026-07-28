"""T5, T10, and T11 track-derived state analyses."""
from __future__ import annotations

from collections import defaultdict
import numpy as np


def area_restricted_search(events, *, removal_from_food_s: float,
                           bin_width_s: float = 60) -> dict:
    """Plate-first reversal/omega rates after food removal."""
    grouped = defaultdict(list)
    for event in events:
        grouped[str(event["plate_id"])].append(event)
    plates = []
    for plate, values in grouped.items():
        end = max(float(row["time_s"]) for row in values)
        bins = np.arange(removal_from_food_s, end + bin_width_s, bin_width_s)
        rows = []
        for start in bins:
            selected = [row for row in values
                        if start <= float(row["time_s"]) < start + bin_width_s]
            observed = sum(row["event_type"] in {"reversal", "omega"}
                           for row in selected)
            observable_minutes = sum(
                float(row.get("observable_duration_s", 0))
                for row in selected) / 60
            rows.append({
                "time_since_food_removal_s": start - removal_from_food_s,
                "event_rate_per_min": (
                    None if observable_minutes == 0
                    else observed / observable_minutes),
                "event_count": observed})
        finite = [row["event_rate_per_min"] for row in rows
                  if row["event_rate_per_min"] is not None]
        plates.append({
            "plate_id": plate, "timecourse": rows,
            "local_search_elevation": (
                None if len(finite) < 2 else finite[0] - finite[-1]),
            "flat_no_local_search_is_valid": True})
    return {"inferential_unit": "plate", "plate_summaries": plates,
            "validation_level": "computational_regression"}


def roaming_dwelling(rows, speed_threshold=None, angular_threshold=None) -> dict:
    """Transparent two-state classifier; single-state output is valid."""
    grouped = defaultdict(list)
    for row in rows:
        grouped[(str(row["plate_id"]), str(row["worm_id"]))].append(row)
    worms = []
    for (plate, worm), values in grouped.items():
        values.sort(key=lambda row: float(row["time_s"]))
        speed = np.asarray([row["speed_um_s"] for row in values], dtype=float)
        angular = np.abs(np.asarray(
            [row["angular_velocity_deg_s"] for row in values], dtype=float))
        s_cut = float(np.median(speed)) if speed_threshold is None else float(
            speed_threshold)
        a_cut = float(np.median(angular)) if angular_threshold is None else float(
            angular_threshold)
        state = np.where((speed >= s_cut) & (angular <= a_cut),
                         "roaming", "dwelling")
        times = np.asarray([row["time_s"] for row in values], dtype=float)
        dt = np.diff(times, append=times[-1] + (
            np.median(np.diff(times)) if len(times) > 1 else 0))
        transitions = int(np.sum(state[1:] != state[:-1]))
        worms.append({
            "plate_id": plate, "worm_id": worm,
            "fraction_roaming": float(np.sum(dt[state == "roaming"]) /
                                      max(np.sum(dt), 1e-9)),
            "fraction_dwelling": float(np.sum(dt[state == "dwelling"]) /
                                       max(np.sum(dt), 1e-9)),
            "transition_count": transitions,
            "single_state_valid": transitions == 0})
    return {"inferential_unit": "plate", "worm_observations": worms,
            "validation_level": "computational_regression"}


def quiescence(rows, *, speed_threshold_um_s: float,
               minimum_bout_s: float) -> dict:
    grouped = defaultdict(list)
    for row in rows:
        grouped[(str(row["plate_id"]), str(row["worm_id"]))].append(row)
    worms = []
    for (plate, worm), values in grouped.items():
        values.sort(key=lambda row: float(row["time_s"]))
        times = np.asarray([row["time_s"] for row in values], dtype=float)
        quiet = np.asarray(
            [row["speed_um_s"] <= speed_threshold_um_s for row in values])
        dt = np.diff(times, append=times[-1] + (
            np.median(np.diff(times)) if len(times) > 1 else 0))
        starts = np.flatnonzero(quiet & np.r_[True, ~quiet[:-1]])
        ends = np.flatnonzero(quiet & np.r_[~quiet[1:], True])
        durations = [float(np.sum(dt[start:end + 1]))
                     for start, end in zip(starts, ends)]
        accepted = [duration for duration in durations
                    if duration >= minimum_bout_s]
        worms.append({
            "plate_id": plate, "worm_id": worm,
            "fraction_quiescent": float(sum(accepted) / max(np.sum(dt), 1e-9)),
            "bout_count": len(accepted), "bout_durations_s": accepted,
            "zero_quiescence_valid": len(accepted) == 0})
    return {"inferential_unit": "plate", "worm_observations": worms,
            "validation_level": "computational_regression"}
