"""Scale-aware endpoint C. elegans egg candidate detector.

The detector is intentionally conservative.  Eggs are biologically boring in
the best possible way: in a given recording they are very similar ovals.  This
module therefore treats thresholding as a way to propose objects, but accepts
only objects that have egg-like size, aspect ratio, solidity, filled-ellipse
area, and rim contrast.  The GUI can pass a user-selected reference egg to make
the size gate recording-specific.
"""
from __future__ import annotations
import cv2,numpy as np,pandas as pd

def gray8(a):
    if a.ndim==3:a=cv2.cvtColor(a,cv2.COLOR_RGB2GRAY)
    a=a.astype(np.float32);lo,hi=np.percentile(a,[.5,99.5])
    return np.uint8(np.clip((a-lo)*255/max(hi-lo,1),0,255))

def polygon_mask(shape,points):
    m=np.zeros(shape,np.uint8)
    if points:cv2.fillPoly(m,[np.round(points).astype(np.int32)],255)
    else:m[:]=255
    return m

def _odd(n, minimum=15):
    n=max(minimum,int(round(n)))
    return n if n%2 else n+1

def _ellipse_masks(shape,x,y,major,minor,angle):
    """Return inner filled ellipse and thin rim masks in pixel coordinates."""
    center=(int(round(x)),int(round(y)))
    axes=(max(1,int(round(major/2))),max(1,int(round(minor/2))))
    inner=np.zeros(shape,np.uint8)
    cv2.ellipse(inner,center,axes,float(angle),0,360,255,-1)
    k=max(1,int(round(minor*.10)))
    dil=cv2.dilate(inner,np.ones((_odd(k,3),_odd(k,3)),np.uint8))
    ero=cv2.erode(inner,np.ones((_odd(k,3),_odd(k,3)),np.uint8))
    rim=cv2.subtract(dil,ero)
    return inner,rim

def _rim_score(im,x,y,major,minor,angle):
    inner,rim=_ellipse_masks(im.shape,x,y,major,minor,angle)
    if rim.sum()==0 or inner.sum()==0:return 0.0,0.0
    sobx=cv2.Sobel(im,cv2.CV_32F,1,0,ksize=3)
    soby=cv2.Sobel(im,cv2.CV_32F,0,1,ksize=3)
    grad=np.sqrt(sobx*sobx+soby*soby)
    rim_grad=float(np.mean(grad[rim>0]))/255.0
    # Eggs often have one darker edge and the opposite edge lighter.  Measure
    # whether the two halves across the minor axis differ, without requiring a
    # fixed bright-on-left/dark-on-right orientation.
    yy,xx=np.indices(im.shape)
    theta=np.deg2rad(angle)
    minor_axis=-np.sin(theta)*(xx-x)+np.cos(theta)*(yy-y)
    half_a=(rim>0)&(minor_axis>=0)
    half_b=(rim>0)&(minor_axis<0)
    if half_a.sum() and half_b.sum():
        polarity=abs(float(np.mean(im[half_a]))-float(np.mean(im[half_b])))/255.0
    else:
        polarity=0.0
    return rim_grad,polarity

def _intensity_context(im,x,y,major,minor,angle,roi=None):
    inner,_=_ellipse_masks(im.shape,x,y,major,minor,angle)
    k=max(3,int(round(minor*.45)))
    outer=cv2.dilate(inner,np.ones((_odd(k,3),_odd(k,3)),np.uint8))
    bg=(outer>0)&(inner==0)
    if roi is not None:bg&=(roi>0)
    if not np.any(inner>0):
        return 0.0,0.0,0.0,0.0,0.0
    vals=im[inner>0].astype(np.float32)
    mean_intensity=float(np.mean(vals))
    bg_mean=float(np.mean(im[bg].astype(np.float32))) if np.any(bg) else mean_intensity
    p10=float(np.percentile(vals,10));p90=float(np.percentile(vals,90))
    local_contrast=abs(mean_intensity-bg_mean)/255.0
    bright_contrast=max(0.0,(p90-bg_mean)/255.0)
    dark_contrast=max(0.0,(bg_mean-p10)/255.0)
    intensity_span=max(0.0,(p90-p10)/255.0)
    return mean_intensity,bg_mean,local_contrast,bright_contrast,dark_contrast,intensity_span

def detect_eggs(image,um_per_px,roi_points=None,length_um=50,width_um=30,tolerance=.25,
                min_solidity=.82,min_ellipse_fill=.55,max_ellipse_fill=1.18,
                min_rim_gradient=.045,min_aspect=1.15,max_aspect=2.60,
                length_um_min=None,length_um_max=None,width_um_min=None,width_um_max=None,
                min_mean_intensity=None,max_mean_intensity=None,
                min_local_contrast=None,min_bright_contrast=None,
                min_dark_contrast=None,min_intensity_span=None,
                reference_prototypes=None):
    """Return candidates; it can return zero and never converts candidates to counts."""
    im=gray8(image);roi=polygon_mask(im.shape,roi_points)
    blur=cv2.GaussianBlur(im,(5,5),0); candidates=[]
    exp_len_px=max(3,float(length_um)/float(um_per_px))
    exp_wid_px=max(3,float(width_um)/float(um_per_px))
    length_um_min=float(length_um_min) if length_um_min is not None else length_um*(1-tolerance)
    length_um_max=float(length_um_max) if length_um_max is not None else length_um*(1+tolerance)
    width_um_min=float(width_um_min) if width_um_min is not None else width_um*(1-tolerance)
    width_um_max=float(width_um_max) if width_um_max is not None else width_um*(1+tolerance)
    expected=np.pi*exp_len_px*exp_wid_px/4
    block=_odd(exp_len_px*2.5,15)
    kernels=[np.ones((3,3),np.uint8),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))]
    for polarity in (cv2.THRESH_BINARY,cv2.THRESH_BINARY_INV):
        b=cv2.adaptiveThreshold(blur,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,polarity,block,3)
        b=cv2.bitwise_and(b,roi)
        b=cv2.morphologyEx(b,cv2.MORPH_OPEN,kernels[0])
        b=cv2.morphologyEx(b,cv2.MORPH_CLOSE,kernels[1])
        contours,_=cv2.findContours(b,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            if len(c)<5:continue
            (x,y),(a,bw),angle=cv2.fitEllipse(c);major=max(a,bw);minor=min(a,bw)
            if major<=0 or minor<=0:continue
            L,W=major*um_per_px,minor*um_per_px
            if not length_um_min<=L<=length_um_max:continue
            if not width_um_min<=W<=width_um_max:continue
            aspect=major/minor
            if not min_aspect<=aspect<=max_aspect:continue
            area=float(cv2.contourArea(c))
            if area<max(8,expected*.25):continue
            hull=cv2.convexHull(c);hull_area=float(cv2.contourArea(hull))
            solidity=area/max(hull_area,1.0)
            ellipse_fill=area/max(np.pi*major*minor/4,1.0)
            if solidity<min_solidity:continue
            if not min_ellipse_fill<=ellipse_fill<=max_ellipse_fill:continue
            rim_gradient,edge_polarity=_rim_score(im,x,y,major,minor,angle)
            if rim_gradient<min_rim_gradient:continue
            mean_intensity,local_background,local_contrast,bright_contrast,dark_contrast,intensity_span=_intensity_context(im,x,y,major,minor,angle,roi)
            if min_mean_intensity is not None and mean_intensity<float(min_mean_intensity):continue
            if max_mean_intensity is not None and mean_intensity>float(max_mean_intensity):continue
            if min_local_contrast is not None and local_contrast<float(min_local_contrast):continue
            if min_bright_contrast is not None and bright_contrast<float(min_bright_contrast):continue
            if min_dark_contrast is not None and dark_contrast<float(min_dark_contrast):continue
            if min_intensity_span is not None and intensity_span<float(min_intensity_span):continue
            refs=reference_prototypes or []
            if refs:
                size_score=min(abs(L-float(r.get("length_um",length_um)))/max(float(r.get("length_um",length_um)),1e-6)+
                               abs(W-float(r.get("width_um",width_um)))/max(float(r.get("width_um",width_um)),1e-6)+
                               .35*abs(aspect-float(r.get("aspect_ratio",aspect)))/max(float(r.get("aspect_ratio",aspect)),1e-6)
                               for r in refs)
            else:
                size_score=abs(L-length_um)/length_um+abs(W-width_um)/width_um
            shape_score=abs(ellipse_fill-.82)+max(0,min_solidity-solidity)
            rim_bonus=min(.35,rim_gradient)+min(.20,edge_polarity)+min(.15,intensity_span)
            score=size_score+shape_score-rim_bonus
            candidates.append(dict(x=float(x),y=float(y),length_um=float(L),width_um=float(W),
                                   angle_deg=float(angle),score=float(score),aspect_ratio=float(aspect),
                                   solidity=float(solidity),ellipse_fill=float(ellipse_fill),
                                   rim_gradient=float(rim_gradient),edge_polarity=float(edge_polarity),
                                   mean_intensity=float(mean_intensity),local_background=float(local_background),
                                   local_contrast=float(local_contrast),bright_contrast=float(bright_contrast),
                                   dark_contrast=float(dark_contrast),intensity_span=float(intensity_span)))
    candidates.sort(key=lambda z:z["score"]); kept=[]
    gate=max(4,width_um/um_per_px*.75)
    for c in candidates:
        if all(np.hypot(c["x"]-k["x"],c["y"]-k["y"])>gate for k in kept):kept.append(c)
    return pd.DataFrame(kept,columns=["x","y","length_um","width_um","angle_deg","score",
                                      "aspect_ratio","solidity","ellipse_fill",
                                      "rim_gradient","edge_polarity","mean_intensity","local_background",
                                      "local_contrast","bright_contrast","dark_contrast","intensity_span"])
