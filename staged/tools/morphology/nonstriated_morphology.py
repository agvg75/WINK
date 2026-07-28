"""Transparent feature extraction for nonstriated muscle morphology.

This module does not emit a biological damage score before WT/dystrophic/rescue
reference distributions are available. It can return no segmentation.
"""
from __future__ import annotations
import json,sys,cv2,numpy as np,pandas as pd
from pathlib import Path
from skimage.morphology import skeletonize, remove_small_objects
from skimage.filters import sato
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"app"))
from acquisition import AcquisitionMetadata

MODES={"pharynx","uterine","somatointestinal","anal_depressor"}

def gray8(a):
    if a.ndim==3:a=cv2.cvtColor(a,cv2.COLOR_RGB2GRAY)
    a=a.astype(np.float32);lo,hi=np.percentile(a,[.2,99.8]);return np.uint8(np.clip((a-lo)*255/max(hi-lo,1),0,255))

def roi_mask(shape,points):
    if isinstance(points,np.ndarray) and points.shape[:2]==tuple(shape[:2]):return (points>0).astype(np.uint8)*255
    m=np.zeros(shape,np.uint8);cv2.fillPoly(m,[np.round(points).astype(np.int32)],255);return m

def body_angle(v,ap,dv):
    dx,dy=float(v[0]),float(v[1]);
    if ap=="right_to_left":dx=-dx
    if dv=="dorsal_up":dy=-dy
    else:dy=dy
    return float(np.degrees(np.arctan2(dy,dx)))

def segment_strands(image,roi_points,response_percentile=82.0,min_object_px=18,
                    ridge_max_sigma=5):
    """Segment bright, elongated muscle strands despite brighter compact blobs."""
    im=gray8(image);roi=roi_mask(im.shape,roi_points)>0
    if not np.any(roi):raise ValueError("The analysis ROI is empty")
    # Remove slow illumination variation, then detect bright ridges at several widths.
    bg=cv2.GaussianBlur(im,(0,0),max(8.0,float(ridge_max_sigma)*3.0))
    local=np.maximum(im.astype(np.float32)-bg.astype(np.float32),0)/255.0
    response=sato(local,sigmas=range(1,max(2,int(ridge_max_sigma))+1),black_ridges=False)
    values=response[roi]
    positive=values[values>0]
    threshold=float(np.percentile(positive,float(response_percentile))) if positive.size else np.inf
    seg=(response>=threshold)&roi
    seg=remove_small_objects(seg,max_size=max(1,int(min_object_px)-1))
    seg=cv2.morphologyEx(seg.astype(np.uint8),cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))>0
    # Reject isolated, compact puncta/nuclei; retain elongated or networked objects.
    n,lab,stats,_=cv2.connectedComponentsWithStats(seg.astype(np.uint8))
    clean=np.zeros_like(seg)
    for i in range(1,n):
        area=int(stats[i,cv2.CC_STAT_AREA]);w=int(stats[i,cv2.CC_STAT_WIDTH]);h=int(stats[i,cv2.CC_STAT_HEIGHT])
        comp=(lab==i).astype(np.uint8);contours,_=cv2.findContours(comp,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
        per=sum(cv2.arcLength(c,True) for c in contours);circularity=4*np.pi*area/max(per*per,1)
        aspect=max(w,h)/max(1,min(w,h))
        if area>=1200 or aspect>=1.65 or circularity<=.58:clean|=(lab==i)
    seg=clean
    return im,seg,response,threshold

def strand_vectors(seg,min_length_px=12):
    """Return endpoint/junction-to-endpoint/junction chord vectors from a skeleton."""
    sk=skeletonize(seg);k=np.ones((3,3),np.uint8)
    degree=cv2.filter2D(sk.astype(np.uint8),-1,k)-sk.astype(np.uint8)
    nodes=sk&(degree!=2);node_zone=cv2.dilate(nodes.astype(np.uint8),np.ones((3,3),np.uint8))>0
    edges=sk&~node_zone;vectors=[];distance=cv2.distanceTransform(seg.astype(np.uint8),cv2.DIST_L2,5)
    n,lab,stats,_=cv2.connectedComponentsWithStats(edges.astype(np.uint8),8)
    for i in range(1,n):
        ys,xs=np.where(lab==i)
        if len(xs)<float(min_length_px):continue
        xy=np.c_[xs,ys].astype(float);center=xy.mean(0)
        if len(xy)>1:
            _,_,vh=np.linalg.svd(xy-center,full_matrices=False);axis=vh[0];proj=(xy-center)@axis
            p0=xy[np.argmin(proj)];p1=xy[np.argmax(proj)]
        else:continue
        chord=float(np.hypot(*(p1-p0)))
        if chord<float(min_length_px)*.65:continue
        widths=2*distance[ys,xs]
        vectors.append(dict(x0=int(round(p0[0])),y0=int(round(p0[1])),x1=int(round(p1[0])),y1=int(round(p1[1])),
                            length_px=float(len(xs)),median_width_px=float(np.median(widths))))
    return sk,vectors

def analyze(image,mode,um_per_px,roi_points,orientation,vector_points=None,output_dir=None,stem="image",
            response_percentile=82,min_object_px=18,ridge_max_sigma=5,min_vector_length_px=12,
            compartment_rois=None):
    if mode not in MODES:raise ValueError("Unknown tissue mode")
    if mode=="pharynx":raise ValueError("Pharynx uses the anchored deformable-template workflow in the same tool; freehand generic analysis is refused.")
    acquisition=AcquisitionMetadata(None,"not_applicable",float(um_per_px),"two_point_calibration",None,"not_applicable").validate()
    im=gray8(image);roi=roi_mask(im.shape,roi_points);vals=im[roi>0]
    if not len(vals):raise ValueError("The analysis ROI is empty")
    if mode=="uterine":
        im,seg,response,threshold=segment_strands(image,roi_points,response_percentile,min_object_px,ridge_max_sigma);seg=seg.astype(np.uint8)
    else:
        threshold=max(float(cv2.threshold(vals,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)[0]),float(np.percentile(vals,60)))
        seg=((im>=threshold)&(roi>0)).astype(np.uint8);seg=cv2.morphologyEx(seg,cv2.MORPH_OPEN,np.ones((3,3),np.uint8));seg=cv2.morphologyEx(seg,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    n,labels,stats,_=cv2.connectedComponentsWithStats(seg)
    areas=stats[1:,cv2.CC_STAT_AREA] if n>1 else np.array([]);area=int(seg.sum())
    if area<5:raise ValueError("No defensible fluorescent muscle segmentation was found")
    sk,vectors=strand_vectors(seg>0,min_vector_length_px);neighbors=cv2.filter2D(sk.astype(np.uint8),-1,np.ones((3,3),np.uint8))-sk.astype(np.uint8)
    endpoints=int(np.sum(sk&(neighbors==1)));branchpoints=int(np.sum(sk&(neighbors>=3)))
    dist=cv2.distanceTransform(seg,cv2.DIST_L2,5);thickness=2*dist[sk]
    ys,xs=np.where(sk);xy=np.c_[xs,ys];cov=np.cov(xy.T);ev,evec=np.linalg.eigh(cov);major=evec[:,np.argmax(ev)]
    principal=body_angle(major,orientation["anterior_posterior"],orientation["dorsal_ventral"])
    gx=cv2.Sobel(im,cv2.CV_32F,1,0);gy=cv2.Sobel(im,cv2.CV_32F,0,1);theta=np.arctan2(gy[seg>0],gx[seg>0])+np.pi/2;w=np.hypot(gx[seg>0],gy[seg>0]);z=np.sum(w*np.exp(2j*theta))/max(np.sum(w),1)
    contours,_=cv2.findContours(seg,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE);per=sum(cv2.arcLength(c,True) for c in contours)
    largest=float(areas.max()/areas.sum()) if len(areas) and areas.sum() else np.nan
    saturation=float(np.mean(vals>=254));snr=float((np.mean(im[seg>0])-np.mean(im[(roi>0)&(seg==0)]))/max(np.std(im[(roi>0)&(seg==0)]),1)) if np.any((roi>0)&(seg==0)) else np.nan
    rec={**acquisition.as_columns(),"tissue_mode":mode,"segmented_area_um2":area*um_per_px**2,"component_count":int(len(areas)),
         "largest_component_fraction":largest,"skeleton_length_um":float(sk.sum()*um_per_px),"skeleton_endpoints":endpoints,"skeleton_branchpoints":branchpoints,
         "median_thickness_um":float(np.median(thickness)*um_per_px),"thickness_cv":float(np.std(thickness)/max(np.mean(thickness),1e-9)),
         "boundary_irregularity":float(per**2/(4*np.pi*area)),"principal_axis_deg_from_ap":principal,"fiber_orientation_coherence":float(abs(z)),
         "saturated_fraction_in_roi":saturation,"signal_to_background":snr,"segmentation_threshold_8bit":threshold,"orientation_source":orientation["orientation_source"],
         "anterior_posterior":orientation["anterior_posterior"],"dorsal_ventral":orientation["dorsal_ventral"],"composite_damage_score":np.nan,
         "composite_score_reason":"requires calibrated WT, dystrophic, and rescue reference distributions"}
    rec.update(segmentation_method="multiscale_bright_ridge" if mode=="uterine" else "intensity_threshold",
               ridge_response_percentile=float(response_percentile) if mode=="uterine" else np.nan,
               vector_count=len(vectors),vector_min_length_um=float(min_vector_length_px*um_per_px),
               segmentation_qc="review_required" if len(areas)>60 or endpoints>250 or branchpoints>500 else "passed_automatic_checks")
    if mode=="anal_depressor":
        if vector_points is None or len(vector_points)!=2:rec.update(force_vector_angle_deg=np.nan,force_vector_length_um=np.nan,force_vector_gate_reason="attachment and insertion not marked")
        else:
            v=np.subtract(vector_points[1],vector_points[0]);rec.update(force_vector_angle_deg=body_angle(v,orientation["anterior_posterior"],orientation["dorsal_ventral"]),force_vector_length_um=float(np.hypot(*v)*um_per_px),force_vector_gate_reason="measured")
    out=Path(output_dir) if output_dir else Path.cwd()/f"{stem}_{mode}_morphology";out.mkdir(parents=True,exist_ok=True)
    pd.DataFrame([rec]).to_csv(out/"morphology_features.csv",index=False);(out/"morphology_features.json").write_text(json.dumps(rec,indent=2,allow_nan=True),encoding="utf-8")
    vrows=[]
    for i,v in enumerate(vectors,1):
        dx=v["x1"]-v["x0"];dy=v["y1"]-v["y0"]
        vrows.append({"vector_id":i,**v,"length_um":v["length_px"]*um_per_px,
                      "median_width_um":v["median_width_px"]*um_per_px,
                      "angle_deg_from_ap":body_angle((dx,dy),orientation["anterior_posterior"],orientation["dorsal_ventral"]),
                      "capacity_weight":v["length_px"]*v["median_width_px"]})
    pd.DataFrame(vrows).to_csv(out/"strand_vectors.csv",index=False)
    if mode=="uterine" and compartment_rois:
        region_rows=[]
        for label,points in compartment_rois.items():
            rm=roi_mask(im.shape,points)>0;region_seg=(seg>0)&rm;region_sk=sk&rm
            selected=[row for row in vrows if rm[int(np.clip(round((row["y0"]+row["y1"])/2),0,rm.shape[0]-1)),int(np.clip(round((row["x0"]+row["x1"])/2),0,rm.shape[1]-1))]]
            area_px=int(region_seg.sum());length_px=int(region_sk.sum());count=len(selected)
            status="no_detectable_network" if count==0 or length_px<max(10,min_vector_length_px) else ("weak_or_fragmented" if count<2 else "network_detected")
            region_rows.append(dict(region=label,detection_status=status,segmented_area_um2=area_px*um_per_px**2,
                                    skeleton_length_um=length_px*um_per_px,vector_count=count,
                                    summed_capacity_weight=sum(r["capacity_weight"] for r in selected),
                                    review_note="Detection status is observational, not a biological absence call."))
        pd.DataFrame(region_rows).to_csv(out/"uterine_regions.csv",index=False)
    overlay=cv2.cvtColor(im,cv2.COLOR_GRAY2BGR);overlay[seg>0]=(0,150,0);overlay[sk]=(255,255,0)
    for v in vectors:cv2.arrowedLine(overlay,(v["x0"],v["y0"]),(v["x1"],v["y1"]),(0,255,255),1,cv2.LINE_AA,tipLength=.12)
    cv2.imwrite(str(out/"segmentation_overlay.png"),overlay)
    return rec,out
