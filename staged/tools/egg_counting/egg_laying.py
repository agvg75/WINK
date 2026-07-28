"""Dynamic egg-laying candidate detection with persistence and camera-shift correction."""
from __future__ import annotations
from pathlib import Path
import sys,json,cv2,numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent/"movie"))
sys.path.insert(0,str(HERE.parents[1]/"app"))
from movie_reader import open_movie
from acquisition import AcquisitionMetadata
from egg_counter import detect_eggs,gray8
from segmentation_review import find_accepted_config,segment_frame
from decision_transparency import write_decision_manifest

def analyze(source,fps,um_per_px,roi_points,output_dir=None,tolerance=.5,
            min_persistence_s=.4,max_match_um=25,
            calibration_method="two_point_calibration",progress=None,
            egg_length_um=50,egg_width_um=30):
    fps=float(fps)
    acquisition=AcquisitionMetadata(
        fps,"declared",float(um_per_px),calibration_method,
        None,"not_applicable").validate()
    min_frames=max(2,int(round(min_persistence_s*fps)))
    gate=max_match_um/float(um_per_px)
    mov=open_movie(source)
    reviewed_segmentation=find_accepted_config(source,"dynamic_egg_laying")
    tracks=[];active={};next_id=1;prev=None;shift=np.zeros(2);frame_rows=[]
    for fi in range(mov.n_frames):
        raw=mov.get_frame(fi);im=gray8(raw)
        if prev is not None:
            try:
                d,_=cv2.phaseCorrelate(prev.astype(np.float32),im.astype(np.float32));shift+=np.asarray(d)
            except Exception:pass
        moved=[(x+shift[0],y+shift[1]) for x,y in roi_points] if roi_points else None
        det=detect_eggs(im,um_per_px,moved,tolerance=tolerance,
                        length_um=float(egg_length_um),width_um=float(egg_width_um))
        if reviewed_segmentation is not None and len(det):
            extent=segment_frame(raw,fi,reviewed_segmentation)
            keep=[
                bool(extent[int(round(y)),int(round(x))])
                if 0 <= int(round(y)) < extent.shape[0]
                and 0 <= int(round(x)) < extent.shape[1] else False
                for x,y in det[["x","y"]].to_numpy()]
            det=det[np.asarray(keep,bool)].reset_index(drop=True)
        coords=det[["x","y"]].to_numpy()-shift if len(det) else np.empty((0,2));used=set()
        for tid,s in list(active.items()):
            if len(coords):
                dist=np.linalg.norm(coords-np.asarray(s["last"]),axis=1);j=int(np.argmin(dist))
                if dist[j]<=gate and j not in used:
                    s["last"]=coords[j].tolist();s["last_frame"]=fi;s["hits"].append(fi);s["raw_x"]=float(det.iloc[j].x);s["raw_y"]=float(det.iloc[j].y);used.add(j)
        for j,p in enumerate(coords):
            if j in used:continue
            active[next_id]={"track_id":next_id,"first_frame":fi,"last_frame":fi,"hits":[fi],"last":p.tolist(),"raw_x":float(det.iloc[j].x),"raw_y":float(det.iloc[j].y)};next_id+=1
        for tid,s in list(active.items()):
            if fi-s["last_frame"]>max(2,min_frames):tracks.append(s);del active[tid]
        frame_rows.append(dict(frame=fi,time_s=fi/fps,camera_shift_x_px=shift[0],camera_shift_y_px=shift[1],egg_candidates=len(det)))
        prev=im
        if progress and fi%10==0:progress(fi+1,mov.n_frames)
    tracks.extend(active.values());mov.close();rows=[]
    for s in tracks:
        consecutive=max(np.diff([-999]+s["hits"]+[999]).tolist()) if False else len(s["hits"])
        confirmed=len(s["hits"])>=min_frames and s["last_frame"]-s["first_frame"]<=len(s["hits"])+max(2,min_frames)
        decision_basis=f"hits={len(s['hits'])}; minimum_required_hits={min_frames}; first_frame={s['first_frame']}; last_frame={s['last_frame']}; match_radius_um={max_match_um}"
        rows.append(dict(**{k:s[k] for k in ["track_id","first_frame","last_frame","raw_x","raw_y"]},hits=len(s["hits"]),confirmed_persistent=confirmed,
                         event_candidate=bool(confirmed and s["first_frame"]>=min_frames),event_time_s=s["first_frame"]/fps,
                         automatic_decision="persistent_new_egg_candidate" if bool(confirmed and s["first_frame"]>=min_frames) else "tracked_object_not_event",
                         decision_basis=decision_basis))
    tr=pd.DataFrame(rows);events=tr[tr.event_candidate].copy() if len(tr) else tr.copy()
    if len(events):events["accepted"]=True;events["review_status"]="unreviewed_candidate";events["decision_status"]="needs_human_review"
    out=Path(output_dir) if output_dir else Path(source).parent/f"{Path(source).stem}_egg_laying_results";out.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(frame_rows).to_csv(out/"frame_qc.csv",index=False);tr.to_csv(out/"egg_object_tracks.csv",index=False);events.to_csv(out/"automatic_event_candidates.csv",index=False)
    meta={**acquisition.as_columns(),"minimum_persistence_s":min_persistence_s,
          "expected_egg_length_um":float(egg_length_um),
          "expected_egg_width_um":float(egg_width_um),
          "automatic_event_candidates":len(events),"camera_motion_correction":"phase correlation",
          "calibration_method":calibration_method,
          "segmentation_review_applied":bool(reviewed_segmentation),
          "note":"Candidates are not final events until visual review."}
    (out/"analysis_metadata.json").write_text(json.dumps(meta,indent=2),encoding="utf-8")
    try:
        write_decision_manifest(out,"dynamic_egg_laying",
            method_note=("Dynamic egg laying treats egg-like detections as object tracks first.  A proposed laying event is created only when "
                         "a new egg-like object persists for the configured number of frames after the initial baseline window, with camera motion "
                         "estimated by phase correlation.  These are candidates until human review."),
            summary={**meta,"egg_object_tracks":int(len(tr)),"confirmed_persistent_tracks":int(tr.confirmed_persistent.sum()) if len(tr) else 0,
                     "event_candidates_requiring_review":int(len(events)),"minimum_required_hits":int(min_frames),
                     "match_radius_um":float(max_match_um),"process_sidebar_intent":"Future UI: show these gates live while analysis runs, with timing and rejected-step counts."},
            decision_files={"frame_qc_csv":"frame_qc.csv","egg_object_tracks_csv":"egg_object_tracks.csv",
                            "automatic_event_candidates_csv":"automatic_event_candidates.csv","metadata_json":"analysis_metadata.json"},
            fields={"confirmed_persistent":"Object survived the persistence gate.",
                    "event_candidate":"Persistent object first appeared after the baseline window.",
                    "automatic_decision":"Readable automatic label assigned before review.",
                    "decision_basis":"Plain-text threshold values and hit counts used for the decision.",
                    "review_status":"unreviewed_candidate until a human reviews/edits the event."},
            caveats=["Egg-like objects in adjacent frames are distinct observations; library learning can assist but should not silently copy same-image coordinates.",
                     "Crowded worms, moving larvae, and focus/illumination shifts can create persistent false positives."])
    except Exception as e:
        (out/"decision_transparency_error.txt").write_text(str(e),encoding="utf-8")
    return events,out
