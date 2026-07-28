from pathlib import Path
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "basal_slowing"))
import basal_slowing as bs


fps = 10.0
n = 300
frame = np.arange(n)
x = 5.0 + frame
y = np.full(n, 50.0)
frequency = np.where(frame < 115, 1.0, 0.5)
angle = 30 * np.sin(2 * np.pi * frequency * frame / fps)
detections = pd.DataFrame({
    "frame": frame, "x": x, "y": y, "area_px": 160,
    "axis_angle_deg": angle % 180, "elongation": 4.0, "edge": False,
    "spine_valid": True, "spine_length_px": 30.0,
    "midbody_curvature_px_inv": angle / 300.0,
    "spine_x_json": "", "spine_y_json": "", "curvature_json": "",
    "fraction_inside_lawn_1": np.where((x >= 120) & (x <= 250), 1.0, 0.0),
})

original_detect = bs._detect
original_list = bs.list_frames
bs._detect = lambda files, *args, **kwargs: (
    detections.copy(), np.zeros((100, 350), dtype=np.uint8))
bs.list_frames = lambda folder: [Path(folder) / f"{i:04d}.jpg"
                                 for i in range(n)]
try:
    with tempfile.TemporaryDirectory() as folder:
        events, tracks, out = bs.analyze(
            folder, fps, 2.0,
            start_roi=[[0, 0], [15, 0], [15, 100], [0, 100]],
            lawn_rois=[[[120, 0], [250, 0], [250, 100], [120, 100]]],
            output_dir=Path(folder) / "out",
            before_s=8, after_s=8, outside_buffer_px=5,
            min_window_fraction=.7, minimum_worm_fraction_inside=.5)
        assert len(events) == 1
        event = events.iloc[0]
        assert event.track_birth_type == "start_roi_exit"
        assert event.automatic_eligible
        assert event.encounter_number == 1
        assert np.isfinite(event.exit_time_s)
        assert abs(event.before_body_axis_frequency_proxy_hz - 1.0) < .15
        assert abs(event.after_body_axis_frequency_proxy_hz - .5) < .15
        assert Path(out, "paired_entry_events.csv").exists()
        assert Path(out, "analysis_metadata.json").exists()
finally:
    bs._detect = original_detect
    bs.list_frames = original_list

# A lost-and-refound worm moving in one aligned direction is one animal.
tracklets = pd.DataFrame({
    "track_id": [1] * 10 + [2] * 10,
    "frame": list(range(10)) + list(range(13, 23)),
    "x": list(range(10)) + list(range(13, 23)),
    "y": [20.0] * 20,
})
stitched, stitch_log = bs.stitch_tracklets(
    tracklets, max_gap_frames=10, max_distance_px=20,
    max_heading_change_deg=30)
assert stitched.track_id.nunique() == 1
assert stitched.original_track_id.nunique() == 2
assert stitched.track_stitched.all()
assert len(stitch_log) == 1

print("basal slowing synthetic regression passed")
