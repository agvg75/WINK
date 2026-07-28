from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"/"population_orientation"))
from orientation_plate_stats import reduce_plate,analyse_plates,rayleigh,axial_rayleigh

plates=[reduce_plate(f"p{i}",[350+i,0+i,10+i],n_worms=40) for i in range(6)]
r=analyse_plates(plates,expected_deg=0)
assert r["n_plates"]==6 and r["pooled_worm_test"]=="REFUSED"
assert r["n_worms_per_plate"]["p0"]==40
axial=np.array([0,180]*20,dtype=float)
_,directional_p=rayleigh(axial);_,axial_p=axial_rayleigh(axial)
assert directional_p>.5 and axial_p<1e-6,(directional_p,axial_p)
assert "plate_level_axial_rayleigh_p" in r and "plate_axis_orientation_deg" in r
try:
    analyse_plates([plates[0],plates[0]])
    raise AssertionError("duplicate plates accepted")
except ValueError: pass
print("ORIENTATION_PLATE_STATS_PASS",r["plate_level_v_p"])
