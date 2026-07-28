from pathlib import Path
import sys,cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"tools"/"morphology"))
from nonstriated_morphology import analyze
im=np.zeros((220,320),np.uint8)
for x in [80,120,160,200]:cv2.line(im,(x,170),(x+25,55),180,5)
cv2.line(im,(60,175),(245,175),150,7);cv2.circle(im,(250,100),25,210,4)
roi=[(40,35),(290,35),(290,195),(40,195)];orientation={"anterior_posterior":"left_to_right","dorsal_ventral":"dorsal_up","orientation_source":"reused_saved_default"}
base=ROOT/"tests"/"nonstriated_morphology_output"
for mode in ["uterine","somatointestinal","anal_depressor"]:
 compartments={"anterior_um1":[(40,35),(130,35),(130,195),(40,195)],"anterior_um2":[(130,35),(180,35),(180,195),(130,195)],"posterior_um1":[(180,35),(230,35),(230,195),(180,195)],"posterior_um2":[(230,35),(290,35),(290,195),(230,195)]} if mode=="uterine" else None
 rec,out=analyze(im,mode,.5,roi,orientation,[(80,170),(105,55)] if mode=="anal_depressor" else None,base/mode,"synthetic",compartment_rois=compartments)
 assert rec["segmented_area_um2"]>0 and (out/"segmentation_overlay.png").exists()
 assert (out/"strand_vectors.csv").exists()
 if mode=="uterine":assert (out/"uterine_regions.csv").exists()
 assert np.isnan(rec["composite_damage_score"])
if not 70<abs(rec["force_vector_angle_deg"])<120:raise AssertionError(rec)
print("NONSTRIATED_MORPHOLOGY_PASS")
