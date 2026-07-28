import json
import sys
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "population_swimming"))
from population_swimming import analyze


def test_population_swimming_accepts_streamed_mp4(tmp_path):
    movie_path = tmp_path / "population.mp4"
    writer = cv2.VideoWriter(
        str(movie_path), cv2.VideoWriter_fourcc(*"mp4v"), 20, (240, 180))
    if not writer.isOpened():
        raise RuntimeError("Test runtime cannot create the MP4 fixture.")
    rng = np.random.default_rng(4)
    background = np.uint8(np.clip(125 + rng.normal(0, 4, (180, 240)), 0, 255))
    for frame in range(60):
        image = background.copy()
        cv2.ellipse(image, (30 + 2 * frame, 70), (18, 5),
                    frame * 8, 0, 360, 45, -1)
        writer.write(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR))
    writer.release()

    summary, output = analyze(movie_path, 20, 2.0, min_area=20,
                              max_area=2000, sample_background=9)
    metadata = json.loads((output / "analysis_metadata.json").read_text())
    assert len(summary) >= 1
    assert metadata["input_source_kind"] == "video"
    assert metadata["n_frames"] == 60
    assert output.name == "population_population_swimming_results"
