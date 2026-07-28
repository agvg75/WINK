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
print("POPULATION_ORIENTATION_PASS",out)
