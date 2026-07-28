from pathlib import Path
import json
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from capability_gate import (
    DEFAULT_REQUIREMENTS, capability_menu, gate_recording,
    proxies_from_probe_report)
from departure_clock import apply_release_gate, summarize_departures
from failure_library import FailureContext, FailureLibrary
from test_shared_services_tier0 import complete_acquisition


def test_departure_clock_preserves_release_columns_and_censors():
    tracks = pd.DataFrame([
        {"track_id": 1, "frame": i, "time_s": i, "x": x, "y": 0,
         "inside_start": inside}
        for i, (x, inside) in enumerate(
            [(0, True), (2, False), (3, False), (0, True), (4, False)])] + [
        {"track_id": 2, "frame": i, "time_s": i, "x": 0, "y": 0,
         "inside_start": True} for i in range(5)])
    gated = apply_release_gate(tracks)
    assert gated[gated.track_id == 1].origin_release_type.eq(
        "observed_exit").all()
    summary = summarize_departures(
        gated, [[-1, -1], [1, -1], [1, 1], [-1, 1]],
        minimum_commitment_s=1)
    never = summary[summary.worm_id == "2"].iloc[0]
    assert bool(never.departure_censored)
    assert pd.isna(never.committed_departure_s)


def test_probe_consumer_routes_to_population():
    proxies = proxies_from_probe_report(
        {"fps": 5, "bit_depth": 8, "lossy": False},
        worm_length_px=35, worm_width_px=4, contrast_ratio=1.3,
        saturation_fraction=0, focus_score=1, occluded_fraction=.1,
        compression_artifact_score=0)
    menu = capability_menu(gate_recording(proxies, DEFAULT_REQUIREMENTS))
    assert "population_centroid_speed" in menu["passing_metrics"]
    assert menu["alternative_route"]


def test_failure_fixture_and_silent_triage(tmp_path):
    library = FailureLibrary(tmp_path / "failures")
    evidence = tmp_path / "frame.txt"
    evidence.write_text("pixels", encoding="utf-8")
    silent = library.capture(FailureContext(
        "tool", "1", complete_acquisition(), "missed_event", None, 4, {},
        "expected event", 3, "tool_failure"), [evidence])
    library.capture(FailureContext(
        "tool", "1", complete_acquisition(), "crash", None, 4, {},
        "visible crash", 3, "tool_failure"))
    fixture = library.convert_to_regression_fixture(
        silent, tmp_path / "fixtures")
    assert (fixture / "fixture.json").is_file()
    assert library.triage()[0]["category"] == "missed_event"
