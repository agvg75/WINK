"""T4: depth, velocity, stalls, and censored no-penetration outcomes."""
from __future__ import annotations

from collections import defaultdict
import numpy as np


def analyze_burrowing(rows, *, minimum_progress_um: float,
                      stall_velocity_um_s: float) -> dict:
    grouped = defaultdict(list)
    for row in rows:
        grouped[(str(row["plate_id"]), str(row["worm_id"]),
                 float(row["resistance"]))].append(row)
    worms = []
    for (plate, worm, resistance), values in grouped.items():
        values.sort(key=lambda row: float(row["time_s"]))
        time = np.asarray([row["time_s"] for row in values], dtype=float)
        depth = np.asarray([row["depth_um"] for row in values], dtype=float)
        if len(time) < 2 or np.any(np.diff(time) <= 0):
            raise ValueError("Each burrowing track needs increasing times.")
        velocity = np.gradient(depth, time)
        penetration = float(np.nanmax(depth) - depth[0])
        penetrated = penetration >= minimum_progress_um
        worms.append({
            "plate_id": plate, "worm_id": worm, "resistance": resistance,
            "maximum_depth_um": float(np.nanmax(depth)),
            "mean_vertical_velocity_um_s": (
                float(np.nanmean(velocity)) if penetrated else None),
            "stall_fraction": float(np.mean(
                np.abs(velocity) <= stall_velocity_um_s)),
            "penetration_event_observed": penetrated,
            "censored_depth_um": None if penetrated else float(np.nanmax(depth)),
            "no_penetration_not_averaged_as_zero_velocity": not penetrated})
    plates = []
    for plate, resistance in sorted({
            (row["plate_id"], row["resistance"]) for row in worms}):
        selected = [row for row in worms
                    if row["plate_id"] == plate
                    and row["resistance"] == resistance]
        plates.append({
            "plate_id": plate, "resistance": resistance,
            "within_plate_worm_count": len(selected),
            "penetration_fraction": sum(
                row["penetration_event_observed"] for row in selected) /
                len(selected)})
    return {"inferential_unit": "plate", "worm_observations": worms,
            "plate_summaries": plates,
            "validation_level": "computational_regression",
            "validation_stamp": {
                "level": "computational_regression",
                "tool_name": "graded_resistance_burrowing",
                "tool_version": "0.1.0",
                "metric": "plate_penetration_and_stall"}}
