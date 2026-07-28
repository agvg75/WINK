from pathlib import Path
import sys,cv2,numpy as np,tifffile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"tools"/"egg_counting"))
from egg_laying import analyze
folder=ROOT/"tests"/"egg_laying_synthetic";folder.mkdir(exist_ok=True)
for i in range(80):
 im=np.full((180,260),190,np.uint8);cv2.ellipse(im,(70,80),(25,15),10,0,360,60,3)
 if i>=30:cv2.ellipse(im,(170,95),(25,15),-15,0,360,60,3)
 tifffile.imwrite(folder/f"f{i:03d}.tif",im)
e,out=analyze(folder,10,1.0,[(10,10),(250,10),(250,170),(10,170)],folder/"results",tolerance=.35,min_persistence_s=.4)
assert len(e)>=1,e
assert any(abs(e.event_time_s-3.0)<.5),e
print("EGG_LAYING_SYNTHETIC_PASS",len(e),out)
