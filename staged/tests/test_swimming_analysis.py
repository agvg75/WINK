from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "worm_kinematics"))
from swimming_analysis import analyze_csv

out = ROOT / "tests" / "swimming_synthetic_output"
out.mkdir(exist_ok=True)
fps, hz, n, segments = 30.0, 1.7, 600, 24
rows = []
for frame in range(n):
    t = frame / fps
    for seg in range(segments):
        rows.append(dict(worm_id="synthetic", frame=frame, time_s=t, segment=seg,
                         seg_curv_deg=20*np.sin(2*np.pi*hz*t - seg*0.18),
                         body_length_px=500, fps=fps, needs_help=(250 <= frame < 260),
                         assay_mode="swimming", exposure_ms=2.0,
                         fps_source="declared", um_per_px=2.35,
                         um_per_px_source="declared", exposure_source="declared"))
csv = out / "synthetic_swim.csv"
pd.DataFrame(rows).to_csv(csv, index=False)
summary, result_dir = analyze_csv(csv, out / "results")
assert abs(summary["frequency_hz"] - hz) < 0.12, summary
assert 0.97 < summary["usable_fraction"] < 0.99, summary
assert summary["swimming_fraction_of_usable"] > 0.95, summary
assert summary["dv_outputs_supported"] is True
full_range, _ = analyze_csv(csv, out / "full_range_results", start_frame=0,
                            end_frame=n-1)
assert full_range["frequency_hz"] == summary["frequency_hz"]
assert full_range["usable_fraction"] == summary["usable_fraction"]
partial, _ = analyze_csv(csv, out / "partial_results", start_frame=60,
                         end_frame=239)
assert partial["selected_frame_start"] == 60 and partial["selected_frame_end"] == 239
print("SWIMMING_SYNTHETIC_PASS", summary["frequency_hz"], result_dir)
