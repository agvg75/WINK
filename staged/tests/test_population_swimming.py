from pathlib import Path
import sys
import json
import cv2
import numpy as np
import tifffile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"/"population_swimming"))
from population_swimming import (analyze,link_detections,classify_modality_windows,
                                 windows_to_bouts,SPINE_POINTS,_point_in_any_roi,
                                 _centroid_frequency)
import pandas as pd

folder=ROOT/"tests"/"population_swimming_synthetic"; folder.mkdir(exist_ok=True)
for i in range(120):
    im=np.full((180,240),30000,np.uint16)
    for off,phase in [(0,0),(70,1.2)]:
        x=35+i+off//4; y=int(55+off+10*np.sin(2*np.pi*1.5*i/20+phase))
        cv2.ellipse(im,(x%220+10,y),(12,4),20*np.sin(2*np.pi*1.5*i/20+phase),0,360,8000,-1)
    tifffile.imwrite(folder/f"frame_{i:04d}.tif",im)
summary,out=analyze(folder,20,2.0,folder/"results",min_area=40,max_area=600,max_link_px=35)
assert len(summary)>=2,summary
assert (summary.coverage_fraction>.5).any(),summary
# Two animals approach, cross, and continue. Identities should follow momentum,
# not swap to whichever post-crossing point is nearest the old position.
cross=[]
for f in range(21):
    cross += [dict(frame=f,x=20+5*f,y=50,area_px=100),
              dict(frame=f,x=120-5*f,y=54,area_px=100)]
linked=link_detections(pd.DataFrame(cross),max_link_px=12)
directions=linked.groupby("track_id").apply(lambda g: np.sign(g.sort_values("frame").x.iloc[-1]-g.sort_values("frame").x.iloc[0]),include_groups=False)
assert len(linked.track_id.unique())==2,linked
assert set(directions)=={-1,1},directions
# A long merged blob must not erase the two incoming trajectories. After the
# split, identities should continue forward rather than bounce/swap.
merged=[]
for f in range(8):
    merged += [dict(frame=f,x=20+4*f,y=48,area_px=100,elongation=3),
               dict(frame=f,x=100-4*f,y=52,area_px=100,elongation=3)]
for f in range(8,21):
    merged.append(dict(frame=f,x=60,y=50,area_px=230,elongation=1.1))
for f in range(21,29):
    merged += [dict(frame=f,x=60+4*(f-20),y=48,area_px=100,elongation=3),
               dict(frame=f,x=60-4*(f-20),y=52,area_px=100,elongation=3)]
continued=link_detections(pd.DataFrame(merged),max_link_px=15,max_gap_frames=4,
                          crossing_memory_frames=30)
long_tracks=continued.groupby("track_id").filter(lambda g: g.frame.min()==0)
directions=long_tracks.groupby("track_id").apply(
    lambda g: np.sign(g.sort_values("frame").x.iloc[-1]-g.sort_values("frame").x.iloc[0]),
    include_groups=False)
assert {-1,1}.issubset(set(directions)),directions
# Modality proposals are conservative and use both frequency and curvature
# topology. A high-frequency single-sign C wave should propose swimming.
rows=[]
fps=20
for frame in range(120):
    phase=np.sin(2*np.pi*1.2*frame/fps)
    curve=(.08+.025*phase)*np.ones(SPINE_POINTS)
    rows.append(dict(track_id=1,frame=frame,time_s=frame/fps,x=frame*.4,y=40,
        speed_um_s=120,area_px=120,elongation=3,curvature_json=json.dumps(curve.tolist()),
        midbody_curvature_px_inv=float(curve[12])))
modal=classify_modality_windows(pd.DataFrame(rows),fps)
assert len(modal)>0,modal
assert (modal.proposed_modality=="swimming").mean()>.5,modal
bouts=windows_to_bouts(modal,fps)
assert len(bouts)>=1 and bouts.proposed_modality.iloc[0]=="swimming",bouts
roi=[{"shape":"rectangle","polygon":[[10,10],[30,10],[30,30],[10,30]]}]
assert _point_in_any_roi(20,20,roi)
assert not _point_in_any_roi(40,20,roi)
# Centroid oscillation should recover the movie-clock frequency while the
# animal also translates across the field.
fps=30; frames=np.arange(300)
centroid=pd.DataFrame({"frame":frames,"x":2*frames/fps,
                       "y":40+8*np.sin(2*np.pi*1.4*frames/fps)})
assert abs(_centroid_frequency(centroid,fps)-1.4)<.12
# Range selection keeps original source-frame coordinates.
ranged,ranged_out=analyze(folder,20,2.0,folder/"range_results",min_area=40,
                          max_area=600,max_link_px=35,start_frame=21,end_frame=80)
ranged_tracks=pd.read_csv(ranged_out/"detections_and_tracks.csv")
ranged_meta=json.loads((ranged_out/"analysis_metadata.json").read_text())
assert ranged_tracks.frame.min()>=20 and ranged_tracks.frame.max()<=79
assert ranged_meta["n_frames"]==60 and ranged_meta["source_frame_start_1_based"]==21
print("POPULATION_SWIMMING_SYNTHETIC_PASS",len(summary),out)
