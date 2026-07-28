from pathlib import Path
import sys,cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"tools"/"egg_counting"))
from egg_counter import detect_eggs
im=np.full((240,320),190,np.uint8)
for xy,a in [((80,80),15),((180,90),-20),((150,180),35)]:
 cv2.ellipse(im,xy,(25,15),a,0,360,65,3)
d=detect_eggs(im,1.0,[(20,20),(300,20),(300,220),(20,220)],tolerance=.35)
assert len(d)>=3,d
assert all(d.length_um.between(32.5,67.5))
print("EGG_COUNTER_SYNTHETIC_PASS",len(d))
