"""Synthetic smoke test for automatic pharyngeal-pumping analysis."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "pharyngeal_pumping" / "pumping_tool.py"
spec = importlib.util.spec_from_file_location("pumping_tool_test", TOOL)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

fps = 30.0
duration = 6.0
n = int(fps * duration)

with tempfile.TemporaryDirectory() as tmp:
    paths = []
    for i in range(n):
        frame = np.full((96, 128), 145, np.uint8)
        dx = int(round(1.2 * np.sin(2 * np.pi * .25 * i / fps)))
        cx, cy = 64 + dx, 48
        cv2.ellipse(frame, (cx, cy), (22, 15), 0, 0, 360, 105, -1)
        # A dark "grinder/lumen" feature oscillating at 2 Hz.
        pump = np.sin(2 * np.pi * 2.0 * i / fps)
        cv2.ellipse(frame, (cx + int(round(4 * pump)), cy), (5, 8),
                    0, 0, 360, 45, -1)
        frame = cv2.GaussianBlur(frame, (3, 3), .6)
        path = Path(tmp) / f"synthetic-{i:04d}.png"
        cv2.imwrite(str(path), frame)
        paths.append(path)

    settings = {
        "movement_px": 3.0,
        "minimum_match": 0.35,
        "template_update_match": 0.70,
        "focus_fraction": 0.30,
        "contrast_fraction": 0.35,
        "search_fraction": 0.45,
        "bridge_frames": 2,
        "minimum_segment_s": 1.0,
        "minimum_pump_interval_s": 0.13,
        "pump_sensitivity": 0.65,
        "pumping_bout_gap_s": 2.0,
        "isolated_pump_window_s": 1.0,
    }
    result = module.automatic_analysis(
        paths, (38, 29, 90, 67), fps, settings)
    assert result.usable.mean() > .80, result.usable.mean()
    assert 8 <= len(result.peaks) <= 16, len(result.peaks)
    print(
        f"PUMPING_SMOKE_PASS usable={result.usable.mean():.3f} "
        f"pumps={len(result.peaks)} expected_about=12")
