"""Shared, assay-aware acquisition and safe-proxy guidance.

Floors are conservative starting points for planning and must be technically
validated for each microscope/strain.  Quantitative intensity tools never
recommend lossy conversion of their measurement channels.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssayProfile:
    name: str
    smallest_feature: str
    min_feature_px: int
    recommended_fps: str
    analysis_floor_fps: float | None
    spatial_guidance: str
    intensity_guidance: str
    proxy_guidance: str


PROFILES = {
    "Population swimming / modality": AssayProfile(
        "Population swimming / modality","worm body",25,"20 fps (retain >=4 samples for a 5-Hz event)",20,
        "Acquire so the smallest worm is >=25 px long; >=60 px is preferred when ordered spines/modality are required.",
        "8-bit grayscale is sufficient for geometry; avoid clipping and uneven illumination.",
        "Centroid/ellipse first pass may use the lowest scale leaving >=25 px per worm; detailed spines should retain >=60 px."),
    "Single-worm crawling/swimming kinematics": AssayProfile(
        "Single-worm crawling/swimming kinematics","worm width",8,"10 fps crawling; >=20 fps swimming/foraging",20,
        "Aim for >=150 px body length and >=8 px body width.",
        "8-bit grayscale is sufficient for geometry; lossless is preferred when subtle edges matter.",
        "Registration may use a proxy; spine/curvature should meet the body-length and width floors."),
    "AFD neuronal tracking": AssayProfile(
        "AFD neuronal tracking","labelled soma",8,"Match calcium kinetics; usually >=10-20 fps",10,
        "Keep the soma >=8-12 px across and the worm >=150 px long.",
        "Use lossless 12/16-bit data for quantitative fluorescence. MP4 is geometry-only.",
        "Camera registration/navigation may be downsampled; fluorescence must be measured on original pixels."),
    "RGBCaMP": AssayProfile(
        "RGBCaMP","body width / muscle band",8,"Match calcium kinetics; usually >=10-20 fps",10,
        "Aim for >=150 px body length and >=8 px width with registered channels.",
        "Use lossless 12/16-bit fluorescence channels; do not convert quantitative channels to MP4/8-bit.",
        "DIC tracking/navigation may use proxies; segment fluorescence statistics remain original-resolution."),
    "Pharyngeal pumping": AssayProfile(
        "Pharyngeal pumping","pharyngeal motion",12,"At least 30 fps",30,
        "Aim for >=250 px pharynx length and >=12 px across the moving boundary.",
        "8-bit can support motion; use higher bit depth when fluorescence/intensity is measured.",
        "Navigation may be downsampled; event detection must retain the motion boundary and >=30 fps."),
    "Population centroid assays / basal slowing": AssayProfile(
        "Population centroid assays / basal slowing","worm body",25,"At least 3 fps for speed; >=10 fps for bending",3,
        "Acquire the smallest worm at >=25 px length with strong foreground/background separation.",
        "8-bit grayscale is sufficient for centroid motion.",
        "A low-resolution centroid proxy is appropriate if every worm stays above 25 px."),
    "Egg laying": AssayProfile(
        "Egg laying","new egg",8,"At least 5-10 fps for event timing",5,
        "Acquire eggs at >=8 px diameter and the vulval region clearly enough for review.",
        "8-bit geometry is acceptable; retain lossless/high bit depth for fluorescence.",
        "Navigation/centroid screening may use proxies only while eggs remain >=8 px."),
    "Endpoint egg counting": AssayProfile(
        "Endpoint egg counting","egg oval and local rim",12,"Static image or first frame; fps not applicable",None,
        "Acquire eggs so the short axis is >=8-12 px and the surrounding rim/background is visible; include enough empty local background around each egg for contrast scoring.",
        "8-bit DIC/brightfield can work if local bright/dark egg edges are preserved. Avoid compression, saturation, or strong uneven illumination that makes debris egg-like.",
        "Detection may run on a contrast-enhanced preview, but final reviewed coordinates should remain tied to the original image/stack frame."),
    "Defecation / pBoc": AssayProfile(
        "Defecation / pBoc","tail-tip axial motion",6,"10-20 fps is usually enough; preserve timestamps",10,
        "Best recordings are zoomed on one fairly stationary worm with the tail tip visible for the whole cycle. Crowded plates, crawling through larvae, and worms leaving frame are high-QC-cost cases.",
        "8-bit phase/DIC can work when the tail taper is visible against agar; improve contrast before attempting full automation.",
        "Navigation/background subtraction may be downsampled, but tail-tip correction and pBoc amplitude should use original pixels near the user-confirmed tail rail."),
    "Foraging / nose tracking": AssayProfile(
        "Foraging / nose tracking","nose tip",4,"20 fps preferred for rapid head sweeps",20,
        "Keep the head/nose tip in frame and avoid dense bacteria or debris near the nose. A clear head/tail initialization helps the tracker avoid locking onto the tail or food patches.",
        "8-bit geometry is sufficient if the nose/background edge is visible; uneven illumination can help edge polarity but can also create false targets.",
        "Use a downsampled navigator for ROI planning, then measure the accepted nose trajectory on original frames."),
    "Nonstriated muscle morphology": AssayProfile(
        "Nonstriated muscle morphology","muscle strand",3,"Static image/z-stack; fps not applicable",None,
        "Acquire the thinnest strand at >=3-5 px and sample z densely enough to avoid broken projections.",
        "Use lossless 12/16-bit channels for intensity, puncta, colocalization, and degeneration metrics.",
        "Preview may be downsampled; segmentation, strand vectors, puncta, and force estimates use original pixels."),
}


def show_acquisition_advisor(parent):
    import tkinter as tk
    from tkinter import ttk
    win=tk.Toplevel(parent);win.title("WINK acquisition and processing advisor");win.geometry("780x500");win.transient(parent)
    selected=tk.StringVar(value=next(iter(PROFILES)))
    top=ttk.Frame(win);top.pack(fill="x",padx=12,pady=12)
    ttk.Label(top,text="Assay").pack(side="left")
    box=ttk.Combobox(top,textvariable=selected,values=list(PROFILES),state="readonly",width=48);box.pack(side="left",padx=8)
    text=tk.Text(win,wrap="word",font=("Segoe UI",10),padx=12,pady=12);text.pack(fill="both",expand=True,padx=12,pady=(0,12))
    def refresh(_event=None):
        p=PROFILES[selected.get()]
        content=(f"{p.name}\n\nACQUIRE\n{p.spatial_guidance}\nFrame rate: {p.recommended_fps}.\n\n"
                 f"INTENSITY / FILE FORMAT\n{p.intensity_guidance}\n\nSAFE PROCESSING PROXY\n{p.proxy_guidance}\n\n"
                 "Rule: reduce resolution or frame rate only when the smallest required feature and fastest required event remain above these floors. "
                 "WINK should preserve original timestamps and measure quantitative intensity on original pixels. Start with the recommendation, inspect QC, and rerun one level higher when outlines or events are inadequate.\n\n"
                 "These are conservative provisional starting points, not substitutes for assay-specific technical validation.")
        text.configure(state="normal");text.delete("1.0","end");text.insert("1.0",content);text.configure(state="disabled")
    box.bind("<<ComboboxSelected>>",refresh);refresh()
    ttk.Button(win,text="Close",command=win.destroy).pack(pady=(0,12))
    return win
