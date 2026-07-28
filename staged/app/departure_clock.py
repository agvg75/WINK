"""Shared release-gate identity and departure-clock service.

The legacy release columns are intentionally preserved byte-for-byte by
``apply_release_gate``. New committed-departure/dwell outputs are emitted as a
separate table by ``summarize_departures``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from departure_roi import analyze_departure


def apply_release_gate(tracks: pd.DataFrame) -> pd.DataFrame:
    tracks = tracks.copy()
    tracks["origin_exit_observed"] = False
    tracks["origin_release_type"] = "not_released"
    tracks["analysis_active"] = False
    for _, group in tracks.groupby("track_id"):
        ordered = group.sort_values("frame")
        transitions = ordered[
            ordered.inside_start.shift(
                fill_value=ordered.inside_start.iloc[0]) &
            ~ordered.inside_start]
        if len(transitions):
            exit_frame = int(transitions.frame.iloc[0])
            tracks.loc[ordered.index, "origin_exit_observed"] = True
            tracks.loc[ordered.index, "origin_release_type"] = "observed_exit"
            tracks.loc[
                ordered[ordered.frame >= exit_frame].index,
                "analysis_active"] = True
        elif not bool(ordered.inside_start.iloc[0]):
            tracks.loc[ordered.index, "origin_release_type"] = (
                "inferred_first_seen_outside")
            tracks.loc[ordered.index, "analysis_active"] = True
    return tracks


def summarize_departures(
    tracks: pd.DataFrame, start_polygon, *,
    time_since_food_at_start_s: float | None = None,
    minimum_commitment_s: float = 2.0,
) -> pd.DataFrame:
    polygon = np.asarray(start_polygon, dtype=float)
    center = np.mean(polygon, axis=0)
    rows = []
    for track_id, group in tracks.groupby("track_id"):
        ordered = group.sort_values("time_s")
        radial = np.hypot(ordered.x - center[0], ordered.y - center[1])
        # Basal slowing has no independent droplet-clear signal. The release
        # gate's first individually observable frame is retained explicitly.
        clear = np.ones(len(ordered), dtype=bool)
        result = analyze_departure(
            str(track_id), ordered.time_s.to_numpy(),
            ordered.inside_start.to_numpy(), radial.to_numpy(),
            droplet_clear=clear,
            minimum_commitment_s=minimum_commitment_s,
            minimum_outward_progress=0,
            time_since_food_at_recording_start_s=time_since_food_at_start_s)
        row = result.as_dict()
        row["wall_clock_at_committed_departure_s"] = (
            result.committed_departure_s)
        row["time_since_committed_departure_at_end_s"] = (
            None if result.committed_departure_s is None
            else result.censor_time_s - result.committed_departure_s)
        row["validation_level"] = "computational_regression"
        rows.append(row)
    return pd.DataFrame(rows)
