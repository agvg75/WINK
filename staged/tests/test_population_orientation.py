from pathlib import Path
import sys,cv2,numpy as np,tifffile,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"tools"/"population_orientation"))
from population_orientation import analyze
folder=ROOT/"tests"/"orientation_synthetic";folder.mkdir(exist_ok=True)
for i in range(80):
 im=np.full((120,180),30000,np.uint16);cv2.circle(im,(25+i,60),3,5000,-1);cv2.circle(im,(90,20),3,5000,-1);tifffile.imwrite(folder/f"f{i:03d}.tif",im)
r,out=analyze(folder,"plate_A",10,100,(120,60),(30,60),(20,60),15,folder/"results",n_worms_on_plate=20)
tc=pd.read_csv(out/"plate_timecourse.csv")
assert r["inferential_unit"]=="plate" and r["n_worms_on_plate"]==20
assert "persistence_iou_mean" in tc and "stimulus_pixel_occupancy" in tc
assert (out/"angular_distribution.csv").exists()
assert (out/"radial_distribution.csv").exists()

# --- area gates: recorded, and checked against what was actually detected ---
# min_area/max_area are in SOURCE pixels and this module exposes them nowhere,
# so a recording at a different magnification is silently emptied and the
# result still looks like a result. The run must now record the gates it used
# and say when they did not fit.
from population_orientation import area_gate_diagnostics
assert r["area_gate_min_px"] == 2 and r["area_gate_max_px"] == 150,     "the gates actually used must be recorded in the output"
assert "objects_detected_total" in r,     "the number of objects the gates were applied to must be recorded"

# FINDING, 2026-08-04: this synthetic fixture detects ZERO objects. The asserts
# above it pass anyway because they only check that files exist and columns are
# present, so the detection and gating path in this suite has never actually
# been exercised. The new diagnostics are what surfaced it. Left asserted as-is
# rather than quietly loosened: if the fixture is ever fixed to contain
# detectable animals this line fails and someone tightens the checks below it.
assert r["objects_detected_total"] == 0,     "fixture behaviour changed - it now detects objects, so tighten these checks"
assert "never exercised" in r["area_gate_warning"],     "a run that detected nothing must SAY so rather than reporting zeros as a result"

fits = area_gate_diagnostics([5, 10, 20, 40, 60, 80], 2, 150)
assert "area_gate_warning" not in fits,     "gates that fit must NOT warn, or the warning becomes noise people ignore"
assert fits["objects_within_gates_fraction"] == 1.0

too_big = area_gate_diagnostics([900, 1100, 1300, 1500], 2, 150)
assert "area_gate_warning" in too_big
assert "larger than" in too_big["area_gate_warning"]
assert "magnification" in too_big["area_gate_warning"],     "the warning must name the likely cause, not just the symptom"

too_small = area_gate_diagnostics([1, 1, 1, 1], 40, 2500)
assert "smaller than" in too_small["area_gate_warning"]

empty = area_gate_diagnostics([], 2, 150)
assert "never exercised" in empty["area_gate_warning"],     "no detections at all must be distinguished from gates that excluded things"

print("POPULATION_ORIENTATION_PASS",out)
