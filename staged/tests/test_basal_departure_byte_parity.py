"""Byte-parity gate for the legacy basal-slowing track export."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "app"), str(ROOT / "tools" / "basal_slowing")]
import basal_slowing as bs
from departure_clock import apply_release_gate


def legacy_release_gate(tracks):
    """Frozen pre-extraction implementation from basal_slowing.analyze."""
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


def test_extracted_release_gate_is_byte_identical_to_frozen_legacy():
    table = pd.DataFrame({
        "track_id": [2, 1, 1, 2, 3, 3],
        "frame": [0, 0, 1, 1, 0, 1],
        "inside_start": [True, True, False, True, False, False],
        "x": [0., 0., 2., 0., 3., 4.],
        "y": [0.] * 6,
    })
    old = legacy_release_gate(table).to_csv(index=False).encode("utf-8")
    new = apply_release_gate(table).to_csv(index=False).encode("utf-8")
    assert old == new
