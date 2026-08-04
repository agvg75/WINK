"""Identity-free population orientation, configuration 1."""
from __future__ import annotations
import json,sys
from dataclasses import replace
from pathlib import Path
import cv2,numpy as np,pandas as pd

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"movie"))
sys.path.insert(0,str(HERE.parents[1]/"app"))
from movie_reader import open_movie
from acquisition import AcquisitionMetadata
from orientation_plate_stats import reduce_plate
from segmentation_review import find_accepted_config,segment_frame

def gray8(a,limits=None):
    if a.ndim==3:a=cv2.cvtColor(a,cv2.COLOR_RGB2GRAY)
    a=a.astype(np.float32)
    lo,hi=limits or np.percentile(a,[.2,99.8])
    return np.uint8(np.clip((a-lo)*255/max(hi-lo,1),0,255)),(float(lo),float(hi))

def circle(shape,center,r):
    y,x=np.ogrid[:shape[0],:shape[1]]
    return (x-center[0])**2+(y-center[1])**2<=r*r

def area_gate_diagnostics(areas,min_area,max_area):
    """What the area gates actually admitted, and whether they look wrong.

    The gates are in SOURCE pixels and this module exposes them nowhere, so a
    recording at a different magnification is silently emptied or silently
    flooded and the result still looks like a result. Recording the gates and
    the distribution they were applied to is the minimum needed to tell those
    apart afterwards; the warning names the likely cause rather than leaving it
    to be inferred from a preference index computed over nothing.
    """
    out={"area_gate_min_px":int(min_area),"area_gate_max_px":int(max_area),
         "objects_detected_total":int(len(areas))}
    if not areas:
        out["area_gate_warning"]=("No objects were detected at all, so the area "
                                  "gates were never exercised and every count "
                                  "below is zero for a reason unrelated to "
                                  "behaviour.")
        return out
    a=np.asarray(areas,dtype=float)
    inside=(a>=min_area)&(a<=max_area)
    frac=float(inside.mean())
    out.update(objects_within_gates=int(inside.sum()),
               objects_within_gates_fraction=round(frac,4),
               object_area_median_px=float(np.median(a)),
               object_area_p05_px=float(np.percentile(a,5)),
               object_area_p95_px=float(np.percentile(a,95)))
    reasons=[]
    median=float(np.median(a))
    if frac < 0.25:
        reasons.append("the gates admitted only %.1f%% of detected objects" % (100*frac))
    if median > max_area:
        reasons.append("the median detected object is %.0f px, above the "
                       "maximum of %d - the animals are probably larger than "
                       "these gates expect" % (median, max_area))
    elif median < min_area:
        reasons.append("the median detected object is %.0f px, below the "
                       "minimum of %d - the animals are probably smaller than "
                       "these gates expect" % (median, min_area))
    if reasons:
        out["area_gate_warning"]=("; ".join(reasons)
                                  + ". Area gates are in SOURCE pixels, so a "
                                    "recording at a different magnification "
                                    "needs different values.")
    return out


def analyze(source,plate_id,fps,um_per_px,stimulus,control,release,roi_radius_px,
            output_dir=None,arrival_count=1,min_area=2,max_area=150,persistence_cutoff=.8,
            n_worms_on_plate=None,progress=None):
    if not str(plate_id).strip():raise ValueError("plate_id is required")
    if fps<=0 or um_per_px<=0:raise ValueError("Declared FPS and scale must be positive")
    acquisition=AcquisitionMetadata(float(fps),"declared",float(um_per_px),"two_point_calibration",None,"not_applicable").validate()
    mov=open_movie(source); n=mov.n_frames
    ids=np.unique(np.linspace(0,n-1,min(31,n)).astype(int))
    raw=[mov.get_frame(int(i)) for i in ids]; allpix=np.concatenate([np.asarray(x).reshape(-1)[::500] for x in raw])
    limits=tuple(np.percentile(allpix,[.2,99.8])); bg=np.median(np.stack([gray8(x,limits)[0] for x in raw]),axis=0).astype(np.uint8)
    reviewed=find_accepted_config(source,"population_orientation")
    reviewed_diff=replace(reviewed,feature="gray") if reviewed else None
    sm=circle(bg.shape,stimulus,roi_radius_px); cm=circle(bg.shape,control,roi_radius_px)
    prev=np.zeros_like(bg,bool); times=[]; angle_weights=[]; angle_values=[]; radial_values=[]
    # Every detected component's area, BEFORE gating. The gates are in source
    # pixels, so values that suit one magnification silently discard the animals
    # at another - and this module exposes them nowhere, so nobody can tell.
    # Collecting the distribution lets the run say afterwards whether its own
    # gates admitted anything sensible.
    all_component_areas=[]
    for fi in range(n):
        im,_=gray8(mov.get_frame(fi),limits); d=cv2.GaussianBlur(cv2.absdiff(im,bg),(3,3),0)
        if reviewed_diff:m=np.uint8(segment_frame(d,fi,reviewed_diff))*255
        else:_,m=cv2.threshold(d,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        m=cv2.morphologyEx(m,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
        count_s=count_c=0; static_px=np.zeros_like(prev); persistence=[]
        nc,lab,stats,cents=cv2.connectedComponentsWithStats(m)
        for k in range(1,nc):
            area=stats[k,cv2.CC_STAT_AREA]
            all_component_areas.append(int(area))
            if not min_area<=area<=max_area:continue
            obj=lab==k; inter=np.logical_and(obj,prev).sum(); union=np.logical_or(obj,prev).sum(); iou=float(inter/union) if union else 0
            persistence.append(iou)
            if iou>persistence_cutoff:static_px|=obj;continue
            x,y=cents[k]; count_s+=int(sm[int(y),int(x)]); count_c+=int(cm[int(y),int(x)])
        worm=(m>0)&~static_px; total=max(int(worm.sum()),1)
        ys,xs=np.where(worm); ang=(np.degrees(np.arctan2(-(ys-release[1]),xs-release[0]))%360) if len(xs) else np.array([])
        rad=np.hypot(xs-release[0],ys-release[1])*um_per_px/1000 if len(xs) else np.array([])
        angle_values.extend(ang.tolist()); angle_weights.extend([1]*len(ang))
        radial_values.extend(rad.tolist())
        times.append(dict(plate_id=plate_id,frame=fi,time_s=fi/fps,stimulus_blob_count=count_s,control_blob_count=count_c,
            stimulus_pixel_occupancy=float(worm[sm].sum()/total),control_pixel_occupancy=float(worm[cm].sum()/total),
            worm_pixel_count=int(worm.sum()),radial_mean_mm=float(np.mean(rad)) if len(rad) else np.nan,
            angular_resultant_x=float(np.mean(np.cos(np.deg2rad(ang)))) if len(ang) else np.nan,
            angular_resultant_y=float(np.mean(np.sin(np.deg2rad(ang)))) if len(ang) else np.nan,
            persistence_iou_mean=float(np.mean(persistence)) if persistence else np.nan,static_artifact_objects=int(sum(x>persistence_cutoff for x in persistence))))
        prev=m>0
        if progress and fi%10==0:progress(fi+1,n)
    mov.close(); tc=pd.DataFrame(times)
    pref=(tc.stimulus_pixel_occupancy-tc.control_pixel_occupancy)/(tc.stimulus_pixel_occupancy+tc.control_pixel_occupancy).replace(0,np.nan)
    tc["preference_index_pixel_occupancy"]=pref
    arrival=tc.loc[tc.stimulus_blob_count>=arrival_count,"time_s"]
    plate=reduce_plate(plate_id,angle_values,angle_weights,n_worms_on_plate)
    plate.update(acquisition.as_columns())
    plate.update(
        stimulus_x=stimulus[0],stimulus_y=stimulus[1],control_x=control[0],control_y=control[1],release_x=release[0],release_y=release[1],
        roi_radius_px=float(roi_radius_px),arrival_time_s=None if arrival.empty else float(arrival.iloc[0]),
        mean_preference_index=float(pref.mean()),preferred_primary_measure="pixel_occupancy",
        blob_counts="descriptive_only_fragmentation_sensitive",persistence_iou_cutoff=persistence_cutoff)
    plate.update(area_gate_diagnostics(all_component_areas,min_area,max_area))
    out=Path(output_dir) if output_dir else Path(source).parent/f"{Path(source).stem}_{plate_id}_orientation_results";out.mkdir(parents=True,exist_ok=True)
    tc.to_csv(out/"plate_timecourse.csv",index=False);pd.DataFrame([plate]).to_csv(out/"plate_resultant.csv",index=False)
    bins=np.arange(0,361,15);pd.DataFrame({"angle_bin_start_deg":bins[:-1],"worm_pixel_count":np.histogram(angle_values,bins)[0]}).to_csv(out/"angular_distribution.csv",index=False)
    rmax=max(radial_values+[.5]); rbins=np.arange(0,rmax+.5,.5);pd.DataFrame({"radius_bin_start_mm":rbins[:-1],"worm_pixel_count":np.histogram(radial_values,rbins)[0]}).to_csv(out/"radial_distribution.csv",index=False)
    (out/"analysis_metadata.json").write_text(json.dumps(plate,indent=2),encoding="utf-8")
    return plate,out
