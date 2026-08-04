import threading
import time
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import matplotlib
from matplotlib.widgets import Slider,LassoSelector
from matplotlib.path import Path as MplPath
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg,NavigationToolbar2Tk
import numpy as np
import pandas as pd
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"app"))
# The arithmetic behind "Measure a worm" lives in app/worm_area_probe.py, which
# was lifted FROM this file so every module derives area gates the same way.
# tests/test_worm_area_probe.py recomputes the legacy formulas inline and
# asserts the probe reproduces them exactly, so the two cannot silently drift.
import worm_area_probe as wap
from population_swimming import (analyze,list_frames,read_gray,summarize_tracks,
                                 recompute_from_detections,
                                 SPINE_METHODS,SPINE_METHOD_DEFAULT,
                                 MANUAL_POINT_COLUMN)

# Menu label <-> engine value. The label carries the trade-off so the choice is
# not a bare jargon word in a dropdown.
SPINE_METHOD_LABELS={
    "morphological":"Standard skeleton (current default)",
    "thinning":"Connected thinning (thick or blurred worms)",
}
SPINE_LABEL_TO_METHOD={label:method for method,label in SPINE_METHOD_LABELS.items()}

# One stable colour per track so several animals can be told apart at a glance.
# tab20 is categorical: neighbouring ids get clearly different hues.
_TRACK_PALETTE=[matplotlib.colormaps["tab20"](i/20.0) for i in range(20)]


def track_colour(track_id):
    return _TRACK_PALETTE[int(track_id)%len(_TRACK_PALETTE)]


# How much of each track to draw, relative to the frame on screen. A whole
# track over a long recording is a scribble; a short trail shows heading and
# makes the moment a track jumps to the wrong animal obvious.
TRAIL_OPTIONS={"Full track":0,"10 frames":10,"20 frames":20,"50 frames":50,
               "100 frames":100,"250 frames":250}
TRAIL_DEFAULT="Full track"
from roi_editor import draw_rois
from acquisition import AcquisitionMetadata
from acquisition_advisor import PROFILES
from run_feedback import prompt_post_run_feedback
from results_summary import population_track_summary
import cv2
from process_ui import CockpitApp,ProcessLog,collect_image_points,apply_wink_theme
from virtual_frame_stack import ProxyFrameStack
import worm_reference as wr
import substrate_texture as st

class App(CockpitApp):
    def __init__(self):
        super().__init__("Population tracking",geometry="1220x800",process_title="Population tracking")
        self.source=tk.StringVar(value=(sys.argv[1] if len(sys.argv)>1 else "")); self.fps=tk.StringVar(value="20"); self.scale=tk.StringVar(value="2.0")
        self.start_frame=tk.StringVar(value="1");self.end_frame=tk.StringVar(value="")
        self.minarea=tk.StringVar(value="40"); self.maxarea=tk.StringVar(value="2500"); self.status=tk.StringVar(value="Choose an MP4/movie, TIFF stack, or folder of sequential images.")
        self.detection_resolution=tk.StringVar(value="Auto: lowest safe resolution")
        self.adaptive_background=tk.BooleanVar(value=True)
        self.fast_first_pass=tk.BooleanVar(value=True)
        self.single_pass_background=tk.BooleanVar(value=False)
        self.cache_two_pass_proxy=tk.BooleanVar(value=False)
        self.low_resolution_background=tk.BooleanVar(value=False)
        self.selective_background_decode=tk.BooleanVar(value=False)
        self.direct_uint8_proxy=tk.BooleanVar(value=True)
        self.spine_method=tk.StringVar(value=SPINE_METHOD_LABELS[SPINE_METHOD_DEFAULT])
        self.max_link_px=tk.StringVar(value="60")
        self.marked_animals=None
        # Calibration cross-checks. Blank/unset means "not stated", which is
        # different from a wrong value - checks that need them simply do not run.
        self.stage=tk.StringVar(value="AD1")
        self.vessel=tk.StringVar(value="")
        self.locomotion_mode=tk.StringVar(value="crawling")
        self._traced_length_px=None
        self._scale_estimates=[]
        self.roi_mode=tk.StringVar(value="none");self.roi_records=[]
        self._build_controls();self._build_center()
        # Callback-exception reporting is inherited from CockpitApp.
        self.status.trace_add("write",lambda *_:self.set_status(self.status.get()));self.set_status(self.status.get())

    def _build_controls(self):
        # Two control pages in the one cockpit panel: the setup form, and the
        # review actions. Only one is packed at a time, so review happens in
        # this window rather than in a separate one.
        self.controls_setup=ttk.Frame(self.controls);self.controls_setup.pack(fill="both",expand=True)
        self.controls_review=ttk.Frame(self.controls)
        c=self.controls_setup
        def labeled(label,var,width=17):
            row=ttk.Frame(c);row.pack(fill="x",pady=2);ttk.Label(row,text=label,width=width).pack(side="left");ttk.Entry(row,textvariable=var).pack(side="right",fill="x",expand=True)
        srow=ttk.Frame(c);srow.pack(fill="x",pady=2);ttk.Label(srow,text="Recording source",width=17).pack(side="left");ttk.Entry(srow,textvariable=self.source).pack(side="right",fill="x",expand=True)
        pick=ttk.Frame(c);pick.pack(fill="x",pady=(0,4))
        ttk.Button(pick,text="Movie / stack",command=lambda:self.source.set(filedialog.askopenfilename(title="Choose a movie or TIFF stack",filetypes=[("Movies and stacks","*.mp4 *.avi *.mov *.mkv *.webm *.m4v *.tif *.tiff"),("All files","*.*")]) or self.source.get())).pack(side="left",padx=2)
        ttk.Button(pick,text="Image folder",command=lambda:self.source.set(filedialog.askdirectory(title="Choose a folder of sequential images") or self.source.get())).pack(side="left",padx=2)
        labeled("Declared FPS",self.fps);labeled("Scale (um/pixel)",self.scale)
        self.add_scale_button(self._current_frame,self._apply_scale,initial=self._scale_value,text="Calibrate scale (scope / bar)...").pack(fill="x",pady=(0,4))
        labeled("Start frame (1-based)",self.start_frame);labeled("End frame (blank=last)",self.end_frame)
        labeled("Min object area (px)",self.minarea);labeled("Max object area (px)",self.maxarea)
        ttk.Button(c,text="Measure a worm to set these...",command=self.measure_worm).pack(fill="x",pady=(0,2))
        ttk.Button(c,text="Mark all animals in a frame...",command=self.mark_animals).pack(fill="x",pady=(0,2))
        labeled("Max link (px/frame)",self.max_link_px)
        ttk.Label(c,wraplength=300,justify="left",foreground="#5E6E76",
                  text=("How far one animal may travel between frames, in source pixels. "
                        "Too large and the tracker welds separate animals into one track "
                        "with long straight jumps across the plate. Measure a worm also "
                        "sets this from the observed motion.")).pack(anchor="w",pady=(0,4))
        ttk.Label(c,wraplength=300,justify="left",foreground="#5E6E76",
                  text=("Areas are in SOURCE pixels, so the right value depends on your "
                        "magnification - on a 4K recording a worm is thousands of pixels, "
                        "not tens. Click one animal and WINK reads the area the detector "
                        "actually gives it.")).pack(anchor="w",pady=(0,4))
        perf=ttk.LabelFrame(c,text="Performance (rescaled to source coordinates)");perf.pack(fill="x",pady=6)
        pr=ttk.Frame(perf);pr.pack(fill="x",padx=6,pady=3);ttk.Label(pr,text="Detection resolution").pack(side="left");ttk.Combobox(pr,textvariable=self.detection_resolution,values=("Auto: lowest safe resolution","Original resolution","50% proxy","25% proxy (fastest)"),state="readonly",width=22).pack(side="right")
        for text,var in (("Adaptive background samples",self.adaptive_background),("Fast wrMTrck-style first pass",self.fast_first_pass),("Single-pass background (experimental; verify track count)",self.single_pass_background),("Cache decoded proxy locally (experimental)",self.cache_two_pass_proxy),("Low-resolution background (experimental; verify tracks)",self.low_resolution_background),("Pipe only selected background frames (experimental)",self.selective_background_decode),("Use decoder-ready 8-bit grayscale directly (recommended)",self.direct_uint8_proxy)):
            ttk.Checkbutton(perf,text=text,variable=var).pack(anchor="w",padx=6,pady=1)
        cal=ttk.LabelFrame(c,text="Calibration cross-checks (optional)");cal.pack(fill="x",pady=6)
        sr=ttk.Frame(cal);sr.pack(fill="x",padx=6,pady=3)
        ttk.Label(sr,text="Stage").pack(side="left")
        ttk.Combobox(sr,textvariable=self.stage,state="readonly",width=18,
                     values=[wr.STAGE_LABELS[s] for s in wr.STAGE_ORDER]).pack(side="right")
        self.stage.set(wr.STAGE_LABELS["AD1"])
        vr=ttk.Frame(cal);vr.pack(fill="x",padx=6,pady=3)
        ttk.Label(vr,text="Vessel").pack(side="left")
        ttk.Combobox(vr,textvariable=self.vessel,state="readonly",width=24,
                     values=[""]+[wr.VESSEL_LABELS[v] for v in wr.VESSEL_ORDER]).pack(side="right")
        mr=ttk.Frame(cal);mr.pack(fill="x",padx=6,pady=3)
        ttk.Label(mr,text="Expected mode").pack(side="left")
        ttk.Combobox(mr,textvariable=self.locomotion_mode,state="readonly",width=14,
                     values=("crawling","swimming","burrowing")).pack(side="right")
        ttk.Button(cal,text="Trace a worm to set the scale...",command=self.trace_worm).pack(fill="x",padx=6,pady=2)
        ttk.Button(cal,text="Check the scale against the vessel...",command=self.check_vessel).pack(fill="x",padx=6,pady=(0,2))
        ttk.Label(cal,wraplength=300,justify="left",foreground="#5E6E76",
                  text=("Frame rate and scale are declared by hand and nothing verifies "
                        "them. Both scale reported speed; frame rate alone scales "
                        "frequency, so a rate that is wrong by 4x makes every Hz wrong "
                        "by 4x. Tracing one animal of a known stage, or measuring a "
                        "vessel of known size, gives an independent estimate. Leave "
                        "Vessel blank if none is visible.")).pack(anchor="w",padx=6,pady=(0,4))
        spine=ttk.LabelFrame(c,text="Spine extraction (affects curvature and bend frequency)");spine.pack(fill="x",pady=6)
        sr=ttk.Frame(spine);sr.pack(fill="x",padx=6,pady=3)
        ttk.Label(sr,text="Skeleton").pack(side="left")
        ttk.Combobox(sr,textvariable=self.spine_method,
                     values=[SPINE_METHOD_LABELS[m] for m in SPINE_METHODS],
                     state="readonly",width=26).pack(side="right")
        ttk.Label(spine,wraplength=300,justify="left",foreground="#5E6E76",
                  text=("The standard skeleton is the historical default and keeps older "
                        "results reproducible, but it can break into pieces on masks more "
                        "than a few pixels thick - producing a partial spine or none. "
                        "Connected thinning always yields one unbroken curve. The two are "
                        "NOT interchangeable: spine, curvature and bend frequency depend "
                        "on the choice, and the method used is recorded in "
                        "analysis_metadata.json. Compare both on one recording before "
                        "changing what you report.")).pack(anchor="w",padx=6,pady=(0,4))
        roi=ttk.LabelFrame(c,text="Optional spatial filtering (default: full frame)");roi.pack(fill="x",pady=6)
        rr=ttk.Frame(roi);rr.pack(fill="x",padx=6,pady=3);ttk.Label(rr,text="ROI action").pack(side="left");ttk.Combobox(rr,textvariable=self.roi_mode,values=("none","include","exclude"),state="readonly",width=10).pack(side="right")
        rb=ttk.Frame(roi);rb.pack(fill="x",padx=6,pady=3);ttk.Button(rb,text="Draw / replace ROIs",command=self.draw_optional_rois).pack(side="left");self.roi_label=ttk.Label(rb,text="0 ROIs");self.roi_label.pack(side="left",padx=8);ttk.Button(rb,text="Clear",command=self.clear_rois).pack(side="right")
        self.go=ttk.Button(c,text="Analyze population",command=self.start);self.go.pack(fill="x",pady=(8,2))
        ttk.Button(c,text="Resume existing results review",command=self.resume_review).pack(fill="x",pady=2)
        ttk.Button(c,text="Correct the scale or FPS of a finished run...",command=self.recompute_run).pack(fill="x",pady=2)

    def _build_center(self):
        self.page_setup=ttk.Frame(self.center);self.page_setup.pack(fill="both",expand=True)
        self.page_review=ttk.Frame(self.center)
        p=self.page_setup
        ttk.Label(p,text="Population tracking - swimming, crawling and burrowing",font=("Segoe UI",12,"bold")).pack(anchor="w",padx=6,pady=(6,2))
        ttk.Label(p,wraplength=520,justify="left",foreground="#444444",text="Analyze a population recording, then review tracks and locomotion bouts here in this window: the movie plays underneath the tracks so you can see whether a track follows a real animal. Include keeps detections whose centroids are inside any ROI; exclude suppresses detections inside any ROI. Shapes: oval/circle, rectangle, or polygon. Uncertain behavioral evidence is never forced into a class.").pack(anchor="w",padx=6,pady=4)
        ttk.Separator(p,orient="horizontal").pack(fill="x",padx=6,pady=6)
        ttk.Label(p,textvariable=self.status,wraplength=520,justify="left").pack(anchor="w",padx=6,pady=4)

    # -- in-window review surface -------------------------------------------
    def _show_page(self,name):
        for page in (self.page_setup,self.page_review):
            page.pack_forget()
        for panel in (self.controls_setup,self.controls_review):
            panel.pack_forget()
        if name=="review":
            self.page_review.pack(fill="both",expand=True)
            self.controls_review.pack(fill="both",expand=True)
        else:
            self.page_setup.pack(fill="both",expand=True)
            self.controls_setup.pack(fill="both",expand=True)

    def _ensure_review_surface(self):
        """One matplotlib canvas in the centre pane, reused by both stages."""
        if getattr(self,"review_fig",None) is not None:
            return
        holder=ttk.Frame(self.page_review);holder.pack(fill="both",expand=True)
        self.review_fig=Figure(figsize=(8.4,6.2),dpi=100)
        self.review_ax=self.review_fig.add_subplot(111)
        self.review_canvas=FigureCanvasTkAgg(self.review_fig,master=holder)
        self.review_canvas.get_tk_widget().pack(fill="both",expand=True)
        self.review_toolbar=NavigationToolbar2Tk(self.review_canvas,holder,pack_toolbar=False)
        self.review_toolbar.update();self.review_toolbar.pack(fill="x")
        self.review_table_holder=ttk.Frame(self.page_review)
        self._proxy=None;self._proxy_token=0

    def _clear_review_controls(self):
        for child in self.controls_review.winfo_children():
            try:child.destroy()
            except Exception:pass

    def _control_button(self,text,command):
        button=ttk.Button(self.controls_review,text=str(text),command=command)
        button.pack(fill="x",padx=4,pady=3);return button

    def _control_label(self,text,wraplength=260):
        label=ttk.Label(self.controls_review,text=str(text),wraplength=wraplength,justify="left")
        label.pack(anchor="w",fill="x",padx=4,pady=3);return label

    def _control_separator(self):
        ttk.Separator(self.controls_review,orient="horizontal").pack(fill="x",padx=4,pady=6)

    def _release_proxy(self):
        proxy=getattr(self,"_proxy",None)
        self._proxy=None
        if proxy is not None:
            try:proxy.close()
            except Exception:pass

    def _build_proxy_async(self,on_ready):
        """Decode a low-resolution, frame-addressable copy in the background.

        Random access into a compressed movie re-decodes from the start of the
        file (seconds per frame on a 4K clip). One streaming pass into this
        proxy makes scrubbing and playback instant. Tracks stay visible while
        it builds; the frames appear underneath them when it is ready.
        """
        self._proxy_token+=1;token=self._proxy_token
        self._release_proxy()
        source=self.source.get()
        def work():
            files=None
            try:
                files=list_frames(source,fast=True)
                stack=ProxyFrameStack.build(
                    files.proxy_frames,files.movie.width,files.movie.height,len(files),
                    max_side=720,
                    progress=lambda done,total,phase:self.after(
                        0,self.status.set,f"{phase}: {done} of {total}..."))
                shape=(int(files.movie.height),int(files.movie.width))
            except Exception as exc:
                self.after(0,self._proxy_failed,token,str(exc));return
            finally:
                if files is not None:
                    try:files.close()
                    except Exception:pass
            self.after(0,self._proxy_ready,token,stack,shape,on_ready)
        threading.Thread(target=work,daemon=True).start()

    def _proxy_ready(self,token,stack,shape,on_ready):
        if token!=self._proxy_token:
            try:stack.close()
            except Exception:pass
            return
        self._proxy=stack;self._proxy_shape=shape
        self.log("Preview proxy ready",f"{len(stack)} frames at {stack.shape[2]}x{stack.shape[1]} (scale {stack.scale:.3f})",status="done")
        self.status.set("Preview frames ready - scrub or play beneath the tracks.")
        try:on_ready()
        except Exception:pass

    def _proxy_failed(self,token,message):
        if token!=self._proxy_token:return
        self._proxy=None
        self.log("Preview proxy unavailable",message,status="failed")
        self.status.set("Review running without movie frames: "+message)

    # -- measure one worm to set the area gates -----------------------------
    MEASURE_MIN_FACTOR=0.40      # curled/foreshortened or younger animals
    MEASURE_MAX_FACTOR=5.0       # two animals briefly touching
    MEASURE_BACKGROUND_SAMPLES=15

    # -- calibration cross-checks -------------------------------------------
    def _stage_key(self):
        label=self.stage.get()
        for key,text in wr.STAGE_LABELS.items():
            if text==label:return key
        return label if label in wr.STAGE_LENGTH_UM else "AD1"

    def _vessel_key(self):
        label=(self.vessel.get() or "").strip()
        if not label:return None
        for key,text in wr.VESSEL_LABELS.items():
            if text==label:return key
        return label if label in wr.VESSELS else None

    def _offer_scale(self,route,implied,detail):
        """Show an independent estimate beside the declared value, and offer it."""
        self._scale_estimates=[e for e in self._scale_estimates if e["route"]!=route]
        self._scale_estimates.append({"route":route,"um_per_px":float(implied),
                                      "detail":detail})
        try:declared=float(self.scale.get())
        except (TypeError,ValueError):declared=None
        ratio=(implied/declared) if declared else None
        message=(f"{detail}\n\n"
                 f"    implied scale   {implied:.3f} um/px\n"
                 +(f"    declared scale  {declared:.3f} um/px\n"
                   f"    ratio           {ratio:.2f}x\n\n" if declared else "\n")
                 +"Use the implied value?\n\n"
                 "Either way the estimate is recorded with the results, so a "
                 "disagreement stays visible later even if it is not acted on now.")
        self.log(f"Scale estimate: {route}",
                 f"{implied:.3f} um/px ({detail})"
                 +(f"; declared {declared:.3f} um/px, ratio {ratio:.2f}x" if declared else ""),
                 status="info")
        if messagebox.askyesno("Scale cross-check",message,parent=self):
            self.scale.set(f"{implied:.4f}")
            self.status.set(f"Scale set from {route}: {implied:.3f} um/px.")
        else:
            self.status.set(f"{route} estimate recorded but not applied.")

    def trace_worm(self):
        """Trace one animal head to tail; its stage gives an independent scale."""
        stage=self._stage_key()
        image=self._current_frame()
        if image is None:
            messagebox.showerror("Trace a worm","Choose a valid recording first.",parent=self);return
        typical,_,_=wr.stage_length_um(stage)
        points=collect_image_points(
            self,image,title="Trace a worm, head to tail",
            instructions=(f"Click along one animal from head to tail - several points "
                          f"around the bends, not just the two ends. A "
                          f"{wr.STAGE_LABELS.get(stage,stage)} is taken to be about "
                          f"{typical:,.0f} um long, which converts the traced pixel "
                          f"length into micrometres per pixel."),
            mode="polyline",min_points=2,
            process_log=ProcessLog("Worm trace for scale"))
        if not points:
            self.status.set("Worm trace cancelled.");return
        pts=np.asarray(points,float)
        length_px=float(np.sum(np.hypot(*np.diff(pts,axis=0).T)))
        if length_px<=1:
            messagebox.showerror("Trace a worm","That trace is too short to measure.",parent=self);return
        self._traced_length_px=length_px
        implied=wr.scale_from_trace(length_px,stage)
        self._offer_scale("worm_trace",implied,
                          f"Traced {length_px:,.0f} px along a "
                          f"{wr.STAGE_LABELS.get(stage,stage)} (~{typical:,.0f} um)")

    def check_vessel(self):
        """Measure a vessel of known size: whole rim if visible, else an arc."""
        vessel=self._vessel_key()
        if not vessel:
            messagebox.showinfo("Vessel check",
                "Choose the vessel type first - it is blank by default because "
                "not every recording contains one.",parent=self);return
        image=self._current_frame()
        if image is None:
            messagebox.showerror("Vessel check","Choose a valid recording first.",parent=self);return
        label=wr.VESSEL_LABELS.get(vessel,vessel)
        diameter=wr.detect_vessel_diameter_px(image,scale=1.0)
        if diameter and messagebox.askyesno(
                "Vessel check",
                f"A circular feature {diameter:,.0f} px across was detected.\n\n"
                f"Is that the {label}?\n\n"
                "Choose No to click points along the rim instead - which also "
                "works when only part of the vessel is in frame.",parent=self):
            implied=wr.scale_from_vessel(diameter,vessel)
            self._offer_scale("vessel_rim",implied,
                              f"{label} detected at {diameter:,.0f} px across")
            return
        points=collect_image_points(
            self,image,title=f"Click along the {label} rim",
            instructions=("Click three or more points along the visible rim. The "
                          "whole vessel does not need to be in frame - an arc "
                          "determines the circle - but a longer arc gives a much "
                          "better estimate than a short, nearly straight one."),
            mode="points",min_points=3,
            process_log=ProcessLog("Vessel rim for scale"))
        if not points:
            self.status.set("Vessel check cancelled.");return
        got=wr.scale_from_arc(points,vessel,image_scale=1.0)
        if got is None:
            messagebox.showerror("Vessel check",
                "Those points do not define a circle. Try again with points "
                "spread further along the rim.",parent=self);return
        implied,diameter,span,confidence=got
        if confidence=="poor":
            messagebox.showwarning("Vessel check",
                f"Those points span only {span:.0f} degrees of the rim. A short, "
                "nearly straight arc barely constrains the radius, so this "
                "estimate is weak - it is recorded, but treat it with caution.",
                parent=self)
        self._offer_scale("vessel_arc",implied,
                          f"{label} fitted from a {span:.0f} degree arc "
                          f"({diameter:,.0f} px across, {confidence} fit)")

    def _detection_preview(self,title):
        """Background-subtracted view of one frame, with its components.

        Shared by 'Measure a worm' and 'Mark all animals' so both anchor on
        exactly what the detector sees. Returns
        (scale, frame, background, labels, stats) or None.
        """
        source=self.source.get().strip()
        if not source:
            messagebox.showerror(title,"Choose a recording first.",parent=self);return None
        self.status.set("Sampling frames...");self.update_idletasks()
        try:
            files=list_frames(source,fast=True)
        except Exception as exc:
            messagebox.showerror(title,f"Could not open the recording.\n\n{exc}",parent=self);return None
        try:
            scale=0.25 if max(files.movie.width,files.movie.height)>=1800 else 1.0
            total=max(2,len(files))
            idx=np.unique(np.linspace(0,total-1,min(self.MEASURE_BACKGROUND_SAMPLES,total)).astype(int))
            samples=[np.asarray(f) for f in files.sampled_proxy_frames(idx,scale)]
            if len(samples)<2:
                raise ValueError("Could not decode enough frames to build a background.")
        except Exception as exc:
            files.close()
            messagebox.showerror(title,f"Could not sample the recording.\n\n{exc}",parent=self);return None
        files.close()
        background=np.median(np.stack(samples),axis=0).astype(np.uint8)
        chosen=samples[len(samples)//2]
        diff=cv2.GaussianBlur(cv2.absdiff(chosen,background),(3,3),0)
        _,mask=cv2.threshold(diff,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        count,labels,stats,_=cv2.connectedComponentsWithStats(mask)
        if count<2:
            messagebox.showinfo(title,"No moving objects were found in the sampled frame.",
                                parent=self);return None
        return scale,chosen,background,labels,stats

    def mark_animals(self):
        """Click every animal you can see (or as many as you like).

        Marking is allowed to be partial - the count is then a FLOOR, not the
        population - so the tool asks which it was and records the answer rather
        than assuming.
        """
        prepared=self._detection_preview("Mark animals")
        if prepared is None:return
        scale,chosen,background,labels,stats=prepared
        points=collect_image_points(
            self,chosen,title="Mark animals",
            instructions=("Click once on each animal you can see. Each click leaves a "
                          "numbered marker, so you can tell which ones you have already "
                          "done. You do not have to mark them all - Finish when done."),
            mode="points",min_points=1,
            process_log=ProcessLog("Mark animals for the area gates and expected count"))
        if not points:
            self.status.set("Animal marking cancelled.");return
        seen,areas,duplicates,misses=[],[],0,0
        for x,y in points:
            row=int(np.clip(y,0,labels.shape[0]-1));col=int(np.clip(x,0,labels.shape[1]-1))
            label=int(labels[row,col])
            if label<=0:
                misses+=1;continue
            if label in seen:
                duplicates+=1;continue
            seen.append(label);areas.append(float(stats[label,cv2.CC_STAT_AREA]))
        if not areas:
            messagebox.showinfo("Mark animals",
                "None of your clicks landed on a detected object. Try clicking directly "
                "on the animals' bodies.",parent=self);return
        areas=np.array(sorted(areas));source_areas=areas/(scale*scale)
        low=max(1.0,round(float(source_areas.min())*0.7))
        high=round(float(source_areas.max())*2.5)
        notes=[]
        if duplicates:notes.append(f"{duplicates} click(s) landed on an animal you had already marked and were ignored")
        if misses:notes.append(f"{misses} click(s) missed every detected object and were ignored")
        exhaustive=messagebox.askyesno("Mark animals",
            f"You marked {len(areas)} distinct animal(s).\n\n"
            f"Did you mark EVERY animal visible in this frame?\n\n"
            "Yes - the count is the population, and WINK will flag when tracking "
            "finds a different number.\n"
            "No  - the count is treated as a minimum only.",parent=self)
        self.marked_animals={"count":int(len(areas)),"exhaustive":bool(exhaustive),
                             "source_areas":[float(a) for a in source_areas],
                             "detection_scale_used":float(scale)}
        message=(f"{len(areas)} animal(s) marked"
                 +(" (you said this is all of them)" if exhaustive else " (a subset)")+".\n\n"
                 f"Their detected areas span {source_areas.min():,.0f} - "
                 f"{source_areas.max():,.0f} source px.\n\n"
                 f"Suggested gates from that spread:\n"
                 f"    Min object area   {low:,.0f}\n"
                 f"    Max object area   {high:,.0f}\n\n"
                 +("".join(f"NOTE: {n}.\n" for n in notes))
                 +"\nApply these values?")
        if not messagebox.askyesno("Mark animals",message,parent=self):
            self.status.set(f"{len(areas)} animal(s) marked; gates not changed.");return
        self.minarea.set(str(int(low)));self.maxarea.set(str(int(high)))
        self.log("Animals marked",
                 f"{len(areas)} distinct animal(s) "
                 +("(stated complete)" if exhaustive else "(subset only)")
                 +f"; areas {source_areas.min():,.0f}-{source_areas.max():,.0f} source px; "
                 f"gates set to {low:,.0f}-{high:,.0f}."
                 +("".join(f" {n}." for n in notes)),status="done")
        self.status.set(f"Marked {len(areas)} animal(s); area gates set to {low:,.0f} - {high:,.0f}.")

    def measure_worm(self):
        """Click one worm; read the area the DETECTOR gives it, and set gates.

        Deliberately not the area of a hand-drawn outline: a traced outline is
        systematically more generous than the thresholded mask, and it is the
        mask the area gates are compared against. Clicking only says *which*
        object is a worm; the number comes from the detector.
        """
        source=self.source.get().strip()
        if not source:
            messagebox.showerror("Measure a worm","Choose a recording first.",parent=self);return
        self.status.set("Sampling frames to measure a worm...");self.update_idletasks()
        try:
            files=list_frames(source,fast=True)
        except Exception as exc:
            messagebox.showerror("Measure a worm",f"Could not open the recording.\n\n{exc}",parent=self);return
        try:
            scale=0.25 if max(files.movie.width,files.movie.height)>=1800 else 1.0
            total=max(2,len(files))
            idx=np.unique(np.linspace(0,total-1,min(self.MEASURE_BACKGROUND_SAMPLES,total)).astype(int))
            samples=[np.asarray(f) for f in files.sampled_proxy_frames(idx,scale)]
            if len(samples)<2:
                raise ValueError("Could not decode enough frames to build a background.")
            background=np.median(np.stack(samples),axis=0).astype(np.uint8)
            chosen=samples[len(samples)//2]
        except Exception as exc:
            files.close()
            messagebox.showerror("Measure a worm",f"Could not sample the recording.\n\n{exc}",parent=self);return
        files.close()
        try:
            labels,stats=wap.detect_objects(chosen,background)
        except ValueError as exc:
            messagebox.showinfo("Measure a worm",str(exc),parent=self);return
        self.status.set("Click on one worm in the frame.")
        points=collect_image_points(
            self,chosen,title="Measure a worm",
            instructions=("Click once on a single animal - the middle of its body is best. "
                          "WINK reads the detected object under your click, not the click itself, "
                          "so precision is not required. Avoid two animals that are touching."),
            mode="points",min_points=1,max_points=1,
            process_log=ProcessLog("Measure a worm for the area gates"))
        if not points:
            self.status.set("Worm measurement cancelled.");return
        px,py=float(points[0][0]),float(points[0][1])
        label=wap.object_at(labels,stats,px,py)
        described=wap.describe(stats,label,scale)
        proxy_area=described["proxy_area_px"]
        source_area=described["source_area_px"]
        span_px=described["span_source_px"]
        thickness_proxy=described["thickness_proxy_px"]
        # Measure how far worm-sized objects actually travel between frames.
        # max_link_px was hard-coded at 60 source px; on this class of recording
        # animals move a few px per frame, and an over-large gate lets the
        # tracker weld separate animals together with long straight jumps.
        link_suggestion=None
        try:
            probe=list_frames(source,fast=True)
            try:
                pair_idx=np.unique(np.linspace(0,max(2,len(probe))-1,60).astype(int))
                seq=[np.asarray(f) for f in probe.sampled_proxy_frames(pair_idx,scale)]
            finally:
                probe.close()
            # p95 of observed motion with headroom, shared with every other
            # module through the probe. Returns None when too few frames
            # resolve, rather than a guessed number.
            link_suggestion=wap.estimate_link_px(seq,background,proxy_area,scale)
        except Exception:
            link_suggestion=None
        all_areas=described["all_areas_proxy"]
        percentile=described["percentile_of_objects"]
        gates=wap.suggest_gates(described,self.MEASURE_MIN_FACTOR,
                                self.MEASURE_MAX_FACTOR)
        low,high,kept=gates["min_area"],gates["max_area"],gates["kept_objects"]
        thin_warning=("\n\nWARNING: at this detection resolution the animal is only about "
                      f"{thickness_proxy:.1f} px thick. Below ~3 px the standard skeleton "
                      "fragments and spines become unreliable - prefer 50% or original "
                      "resolution, or the connected-thinning skeleton.") if thickness_proxy<3.5 else ""
        message=(f"Detected object under your click:\n\n"
                 f"    area          {source_area:,.0f} source px  ({proxy_area:,.0f} px at {int(scale*100)}%)\n"
                 f"    bounding span {span_px:,.0f} source px\n"
                 f"    thickness     about {thickness_proxy:.1f} px at {int(scale*100)}%\n\n"
                 f"It is larger than {percentile:.0f}% of the {len(all_areas)} objects found in "
                 f"this frame.\n\n"
                 f"Suggested gates ({self.MEASURE_MIN_FACTOR:g}x to {self.MEASURE_MAX_FACTOR:g}x):\n"
                 f"    Min object area   {low:,.0f}\n"
                 f"    Max object area   {high:,.0f}\n\n"
                 f"That would keep {kept} of {len(all_areas)} objects in this frame.\n\n"
                 +(f"Max link: {link_suggestion:,.0f} px/frame (currently "
                   f"{self.max_link_px.get()}). Objects of this size move about "
                   f"{link_suggestion/3.0:,.0f} px between frames here; a gate far above "
                   f"that lets the tracker jump between different animals.\n\n"
                   if link_suggestion else "")
                 +f"Apply these values?{thin_warning}")
        if percentile<60:
            message=("NOTE: the object you clicked is smaller than most objects in the frame, "
                     "which usually means a noise blob was clicked rather than an animal. "
                     "Check the numbers below before applying.\n\n")+message
        if not messagebox.askyesno("Measure a worm",message,parent=self):
            self.status.set("Measured worm not applied.");return
        self.minarea.set(str(int(low)));self.maxarea.set(str(int(high)))
        if link_suggestion:
            self.max_link_px.set(str(int(link_suggestion)))
        self.log("Worm measured",
                 f"detected area {source_area:,.0f} source px (p{percentile:.0f} of objects in frame); "
                 f"area gates set to {low:,.0f}-{high:,.0f} source px; "
                 f"about {thickness_proxy:.1f} px thick at {int(scale*100)}% detection scale.",
                 status="done")
        self.status.set(f"Area gates set from a measured worm: {low:,.0f} - {high:,.0f} source px.")

    def _ask_detection_resolution(self,recommended,width,height,typical_area,proxy_fps,profile):
        """Recommend a detection resolution and let the user actually change it.

        Returns the chosen scale, or None if cancelled.  The old version was an
        information-only dialog: it named a recommendation and then applied it
        whatever the user thought, with no control except cancelling the run.
        """
        options=((1.0,"Original resolution - slowest, the control"),
                 (0.5,"50% proxy"),
                 (0.25,"25% proxy - fastest"))
        dialog=tk.Toplevel(self);apply_wink_theme(dialog)
        dialog.title("Detection resolution")
        try:
            screen_w=dialog.winfo_screenwidth();screen_h=dialog.winfo_screenheight()
        except Exception:
            screen_w,screen_h=1366,768
        win_w=max(520,min(620,screen_w-80));win_h=max(360,min(430,screen_h-120))
        dialog.geometry(f"{win_w}x{win_h}+{max(0,(screen_w-win_w)//2)}+{max(0,(screen_h-win_h)//3)}")
        dialog.minsize(min(520,win_w),min(360,win_h))
        try:dialog.resizable(True,True)
        except Exception:pass
        result={"value":None}
        ttk.Label(dialog,text=f"Recommended: {int(recommended*100)}%",
                  font=("Segoe UI",11,"bold")).pack(anchor="w",padx=12,pady=(12,4))
        ttk.Label(dialog,wraplength=win_w-40,justify="left",text=(
            f"Source: {width} x {height}; expected typical accepted object about "
            f"{typical_area*recommended*recommended:.0f} proxy pixels.\n"
            f"Declared rate: {proxy_fps:.2f} fps. {profile.recommended_fps}; this "
            f"recording should not be temporally reduced below "
            f"{profile.analysis_floor_fps:g} fps.\n\n"
            "Detection coordinates are rescaled back to source pixels either way. "
            "A lower resolution is dramatically faster but detects smaller objects "
            "less reliably. Original resolution remains the control; if outlines or "
            "spines look poor, rerun one level higher.")).pack(anchor="w",padx=12,pady=4)
        selection=tk.DoubleVar(value=recommended)
        box=ttk.LabelFrame(dialog,text="Run this analysis at");box.pack(fill="x",padx=12,pady=8)
        for value,label in options:
            text=label+("   (recommended)" if value==recommended else "")
            ttk.Radiobutton(box,text=text,value=value,variable=selection).pack(anchor="w",padx=10,pady=2)
        row=ttk.Frame(dialog);row.pack(fill="x",padx=12,pady=(4,12))
        def accept():
            result["value"]=float(selection.get());dialog.destroy()
        def cancel():
            result["value"]=None;dialog.destroy()
        ttk.Button(row,text="Cancel",command=cancel).pack(side="right",padx=4)
        ttk.Button(row,text="Run analysis",command=accept).pack(side="right",padx=4)
        dialog.protocol("WM_DELETE_WINDOW",cancel);dialog.grab_set()
        try:
            dialog.lift();dialog.focus_force()
        except Exception:pass
        self.wait_window(dialog)
        return result["value"]

    def _spine_method(self):
        return SPINE_LABEL_TO_METHOD.get(self.spine_method.get(),SPINE_METHOD_DEFAULT)

    def _scale_value(self):
        try:return float(self.scale.get())
        except (TypeError,ValueError):return None
    def _current_frame(self):
        try:
            files=list_frames(self.source.get(),fast=True);img=read_gray(files[0]);files.close();return img
        except Exception:return None
    def _apply_scale(self,res):
        self.scale.set(f"{float(res['um_per_px']):.5f}");self.status.set(f"Scale set: {float(res['um_per_px']):.4f} um/pixel ({res.get('details','')})");self.log("Scale calibrated",f"{float(res['um_per_px']):.4f} um/px",status="edit")
    def start(self):
        try:
            if not self.source.get().strip(): raise ValueError("Choose a movie, stack, or image folder.")
            start_frame=int(self.start_frame.get())
            end_frame=int(self.end_frame.get()) if self.end_frame.get().strip() else None
            if start_frame<1:raise ValueError("Start frame must be 1 or greater.")
            if end_frame is not None and end_frame<start_frame:raise ValueError("End frame must be at or after the start frame.")
            selected=Path(self.source.get())
            if selected.is_dir():
                movies=[p for p in selected.iterdir() if p.suffix.lower() in {".mp4",".avi",".mov",".mkv",".webm",".m4v"}]
                if movies:raise ValueError(f"This folder contains {len(movies)} separate movies, not sequential image frames. Use Movie / stack and select one recording. WINK will not silently combine independent animals.")
            choice=self.detection_resolution.get();minarea=int(self.minarea.get());maxarea=int(self.maxarea.get())
            if choice.startswith("Auto"):
                probe=list_frames(selected,fast=True)   # dimensions only, no count
                width,height=int(probe.movie.width),int(probe.movie.height);probe.close()
                typical_area=float(np.sqrt(minarea*maxarea))
                resolution=1.0
                if max(width,height)>=1800:
                    for candidate in (0.25,0.5,1.0):
                        if minarea*candidate*candidate>=8 and typical_area*candidate*candidate>=64:
                            resolution=candidate;break
                proxy_fps=float(self.fps.get());profile=PROFILES["Population swimming / modality"]
                chosen=self._ask_detection_resolution(resolution,width,height,typical_area,proxy_fps,profile)
                if chosen is None:
                    self.status.set("Analysis cancelled at the resolution step.");return
                resolution=chosen
            else:
                resolution={"Original resolution":1.0,"50% proxy":0.5,"25% proxy (fastest)":0.25}[choice]
            args=(self.source.get(),float(self.fps.get()),float(self.scale.get()),None,int(self.minarea.get()),int(self.maxarea.get()),start_frame,end_frame,resolution,bool(self.adaptive_background.get()),bool(self.fast_first_pass.get()),bool(self.single_pass_background.get()),bool(self.cache_two_pass_proxy.get()),bool(self.low_resolution_background.get()),bool(self.selective_background_decode.get()),bool(self.direct_uint8_proxy.get()),self._spine_method(),float(self.max_link_px.get()))
            if self.roi_mode.get()!="none" and not self.roi_records:
                if messagebox.askyesno("No ROI drawn","Include/Exclude was selected, but no ROI was drawn.\n\nContinue with the full frame instead?"):
                    self.roi_mode.set("none")
                else:raise ValueError("Draw at least one ROI or set ROI action to none.")
        except ValueError as exc: messagebox.showerror("Inputs",str(exc)); return
        self.go.state(["disabled"]); self.status.set("Indexing and analyzing in the background...")
        threading.Thread(target=self._run,args=(args,),daemon=True).start()
    # Why each analysis phase exists, in the hood, so a student can see what the
    # module is doing and why - not just that something is running.
    PHASE_NOTES={
        "Indexing frames":"Counting the frames exactly. A blank end frame means 'to the last frame', so this number sets coverage_fraction and cannot be an estimate.",
        "Building background proxy":"Decoding a reduced-resolution copy for the background estimate. Detection coordinates are rescaled back to source pixels, so the proxy costs resolution in the background only.",
        "Building robust background samples":"Median over frames sampled across the whole recording. Anything that never moves is scene, not animal, and is subtracted before detection. Sampling widely stops a worm that pauses from being baked into the background.",
        "Building single-pass background":"Experimental: background estimated from an initial segment instead of the whole recording. Faster, but the track count must be verified against the robust two-pass result.",
        "Fast detection and linking measurements":"wrMTrck-style pass: threshold against the background, keep components inside the area gates, then link them frame to frame by position, heading and speed.",
        "Linking trajectories":"Joining detections into tracks. Crossings are resolved by continuation of motion rather than nearest neighbour, so identities survive an overlap.",
        "Selecting tracks for detailed spines":"Skipping fragments shorter than 3 s, sparsely detected (<55% coverage) or >5% collision frames: they cannot yield a reported frequency, so a skeleton would cost time without adding a measurement.",
        "Detailed spines":"Skeleton per selected frame, resampled to an ordered spine. Advances one unit per track, so the counter moves slowly even when it is working. Cost scales with worm area x thickness, so it is cheap on a 25% proxy and can dominate the whole run at original resolution.",
        "Skipped scene-spanning artifact":"A thin artifact spanning a huge bounding box. Skeletonization scales with the crop, not the animal, so this frame is skipped rather than allowed to monopolise the run.",
        "Detailed spines for eligible tracks":"Finishing the skeleton pass over the tracks that passed the eligibility gate.",
        "Orienting spines and calculating summaries":"Choosing a consistent head-to-tail direction per track, then deriving speed, coverage, bend frequency and QC flags.",
        "Classifying locomotion modality":"Scoring 4 s overlapping windows on curvature topology, bend frequency, speed and wave lag. Every bout stays a proposal until a human confirms it.",
        "Writing tracks and summary tables":"Saving detections_and_tracks.csv and track_summary.csv. Every track is written, accepted or not: rejection is a review decision, not a silent filter.",
        "Writing modality proposals and metadata":"Saving the CSVs, the metadata manifest that records every threshold used, and the per-phase timings.",
    }

    def _analysis_progress(self,i,n,phase="Processing"):
        """Status line every tick; ONE hood entry per phase, accumulating time.

        Phases interleave - the spine pass alternates between its per-frame and
        per-track labels once per track - so a phase that reappears resumes its
        existing row instead of adding a duplicate.
        """
        text=(f"{phase}: {float(i):.1f} of {n}..." if float(i)%1
              else f"{phase}: {int(i)} of {n}...")
        self.status.set(text)
        key=str(phase).split(":")[0].strip()
        previous=getattr(self,"_phase_key",None)
        if key==previous:
            return
        now=time.perf_counter()
        rows=getattr(self,"_phase_rows",None)
        if rows is None:
            rows=self._phase_rows={}
        started=getattr(self,"_phase_started",None)
        if previous is not None and started is not None and previous in rows:
            row=rows[previous]
            row["elapsed_s"]=round(float(row.get("elapsed_s") or 0.0)+(now-started),2)
            row["status"]="done"
        self._phase_key=key;self._phase_started=now
        if key in rows:
            rows[key]["status"]="running"
        else:
            self.process_log.add(key,self.PHASE_NOTES.get(key,""),status="running")
            rows[key]=self.process_log.steps[-1]
        self.refresh_hood()

    def _run(self,args):
        try:
            self._phase_key=None;self._phase_started=None;self._phase_rows={}
            source,fps,scale,output,minarea,maxarea,start_frame,end_frame,resolution,adaptive_background,fast_first_pass,single_pass_background,cache_two_pass_proxy,low_resolution_background,selective_background_decode,direct_uint8_proxy,spine_method,max_link_px=args
            summary,out=analyze(source,fps,scale,output,minarea,maxarea,
                progress=lambda i,n,phase="Processing":self.after(
                    0,self._analysis_progress,i,n,phase),
                start_frame=start_frame,end_frame=end_frame,
                roi_records=self.roi_records,roi_mode=self.roi_mode.get(),
                detection_scale=resolution,adaptive_background_sampling=adaptive_background,
                fast_first_pass=fast_first_pass,single_pass_background=single_pass_background,
                cache_two_pass_proxy=cache_two_pass_proxy,
                low_resolution_background=low_resolution_background,
                selective_background_decode=selective_background_decode,
                direct_uint8_proxy=direct_uint8_proxy,spine_method=spine_method,
                max_link_px=max_link_px)
            self.after(0,self.review,summary,out,True)
        except Exception as e: self.after(0,self.fail,str(e))
    # Files a review writes. After a NEW analysis they describe the previous
    # run, and loading them silently discards everything just computed.
    PRIOR_REVIEW_FILES=("reviewed_detections_and_tracks.csv",
                        "track_summary_after_stitching.csv",
                        "reviewed_track_summary.csv",
                        "track_stitch_edits.json",
                        "reviewed_modality_bouts.csv",
                        "reviewed_modality_summary.csv")

    def _archive_prior_review(self,out):
        """Move a previous review out of the way after a fresh analysis.

        The results folder is derived from the recording, so re-analysing the
        same movie lands in the same folder. review() prefers
        reviewed_detections_and_tracks.csv when it exists - which is correct
        when resuming, and silently discards the new run when it is not.
        Archived rather than deleted: the earlier review is still evidence.
        """
        out=Path(out)
        present=[name for name in self.PRIOR_REVIEW_FILES if (out/name).exists()]
        if not present:
            return []
        stamp=time.strftime("%Y%m%dT%H%M%S")
        folder=out/f"superseded_review_{stamp}"
        folder.mkdir(parents=True,exist_ok=True)
        moved=[]
        for name in present:
            try:
                (out/name).replace(folder/name);moved.append(name)
            except Exception:
                pass
        if moved:
            (folder/"README.txt").write_text(
                "These files are a review of an EARLIER analysis of the same recording.\n"
                "A new analysis was run, so they were moved aside: keeping them in place\n"
                "would have made the review reload the old tracks and discard the new\n"
                "detections. Nothing was deleted.\n",encoding="utf-8")
            self.log("Superseded review archived",
                     f"{len(moved)} file(s) from an earlier review of this recording moved to "
                     f"{folder.name}; this review uses the detections just computed.",
                     status="info")
        return moved

    def review(self,summary,out,fresh=False):
        if fresh:
            self._archive_prior_review(out)
        self.status.set("Analysis complete. Building the track review window...");self.update_idletasks()
        out=Path(out)
        track_path=out/"reviewed_detections_and_tracks.csv"
        summary_path=out/"track_summary_after_stitching.csv"
        tracks=pd.read_csv(track_path if track_path.exists() else out/"detections_and_tracks.csv")
        if summary_path.exists():summary=pd.read_csv(summary_path)
        accepted={int(r.track_id):not bool(r.needs_review) for _,r in summary.iterrows()}
        reviewed_path=out/"reviewed_track_summary.csv"
        if reviewed_path.exists():
            prior=pd.read_csv(reviewed_path)
            accepted.update({int(r.track_id):bool(r.accepted) for _,r in prior.iterrows()})
        metadata=json.loads((Path(out)/"analysis_metadata.json").read_text(encoding="utf-8"))
        accepted.update({int(track_id):True
                         for track_id in metadata.get("locked_track_ids",[])})
        analyzed_frame_count=int(metadata.get("n_frames",int(tracks.frame.max())+1))
        lines={}; selected=[]; undo=[]
        rescue_requested={"value":False}
        edit_path=out/"track_stitch_edits.json"
        edits=json.loads(edit_path.read_text(encoding="utf-8")) if edit_path.exists() else []
        self._ensure_review_surface()
        self._release_proxy()
        fig,ax=self.review_fig,self.review_ax
        ax.clear()
        view={"image":None,"marks":None,"slider":None,"slider_ax":None,
              "frame":0,"playing":False,"play_button":None,"timer":None,
              "editing":False,"edit_track":None,"focus":None,"manual":None,"labels":[],
              "lasso":None}
        if MANUAL_POINT_COLUMN not in tracks:
            tracks[MANUAL_POINT_COLUMN]=False
        tracks[MANUAL_POINT_COLUMN]=tracks[MANUAL_POINT_COLUMN].fillna(False).astype(bool)
        def wb_status(text):
            self.status.set(text)
        self.log("Load reviewed tracks",f"{len(tracks)} detection rows across {int(tracks.track_id.nunique())} candidate track(s) over {analyzed_frame_count} analyzed frames.",status="done")
        self.log("Restore prior review",f"{sum(1 for value in accepted.values() if value)} track(s) start accepted; {len(edits)} prior stitch edit(s) reloaded.",status="done")
        self._calibration_review(out,summary,metadata)
        marked=self.marked_animals
        if marked and marked.get("count"):
            found=int(tracks.track_id.nunique())
            expected=int(marked["count"])
            if marked.get("exhaustive"):
                verdict=("matches" if found==expected else
                         f"{'MORE' if found>expected else 'FEWER'} tracks than animals")
                self.log("Expected animal count",
                         f"you marked {expected} animal(s) and said that was all of them; "
                         f"tracking produced {found} track(s) - {verdict}. "
                         +("More tracks than animals usually means fragmentation; fewer "
                           "means animals were merged or missed."
                           if found!=expected else "Counts agree."),
                         status="info" if found==expected else "warning")
            else:
                self.log("Expected animal count",
                         f"you marked {expected} animal(s) as a subset, so at least that "
                         f"many should exist; tracking produced {found} track(s).",
                         status="info" if found>=expected else "warning")
        self.log("Human review","Click a track to accept/reject. Shift-click two fragments, then Stitch. Movie frames load underneath in the background.",status="ready")
        groups={int(tid):g.sort_values("frame") for tid,g in tracks.groupby("track_id")}
        def visible_span(g):
            """Whole track, or only the last `trail` frames up to the current one."""
            trail=int(view.get("trail") or 0)
            if trail<=0:return g
            hi=int(view["frame"]);lo=hi-trail
            return g[(g.frame>=lo)&(g.frame<=hi)]
        def apply_trail():
            """Cheap per-frame update: reset line data, no re-plotting."""
            if int(view.get("trail") or 0)<=0:return
            for line,tid in lines.items():
                g=groups.get(int(tid))
                if g is None:continue
                v=visible_span(g)
                line.set_data(v.x.to_numpy(float),v.y.to_numpy(float))
        def style_for(tid):
            """Accepted animals each get their own colour; rejected fade back."""
            tid=int(tid)
            if tid in selected:
                return track_colour(tid),2.6,1.0
            if accepted.get(tid,False):
                return track_colour(tid),1.6,0.95
            return "#9aa5ab",0.9,0.55
        for tid,g in groups.items():
            colour,width,alpha=style_for(tid)
            v=visible_span(g)
            line,=ax.plot(v.x,v.y,lw=width,color=colour,alpha=alpha,picker=5,zorder=3)
            lines[line]=int(tid)
        ax.set_aspect("equal")
        # Frame the FULL source frame straight away. Autoscaling to the tracks
        # alone draws a rectangle around wherever worms happened to be, which
        # reads as though the analysis had cropped the frame - it has not; ROIs
        # filter detections by centroid against the real polygon.
        source_w=int(metadata.get("source_frame_width") or 0)
        source_h=int(metadata.get("source_frame_height") or 0)
        if source_w>0 and source_h>0:
            ax.set_xlim(0,source_w);ax.set_ylim(source_h,0)
        else:
            ax.invert_yaxis()
        # Show the ROI the run actually used, so what was included/excluded is
        # visible rather than inferred from where the tracks are.
        roi_path=out/"analysis_rois.json"
        if roi_path.exists():
            try:
                roi_blob=json.loads(roi_path.read_text(encoding="utf-8"))
                roi_mode=str(roi_blob.get("mode","none"))
                colour="#22c55e" if roi_mode=="include" else "#ef4444"
                for record in roi_blob.get("rois",[]):
                    polygon=np.asarray(record.get("polygon",[]),float)
                    if len(polygon)>=3:
                        closed=np.vstack([polygon,polygon[:1]])
                        ax.plot(closed[:,0],closed[:,1],color=colour,lw=1.2,
                                ls="--",alpha=.85,zorder=2)
                if roi_blob.get("rois"):
                    self.log("ROI shown on review",
                             f"{len(roi_blob['rois'])} {roi_mode} ROI(s) drawn as a dashed outline; "
                             "detections were filtered by centroid against the exact polygon.",
                             status="info")
            except Exception:
                pass
        ax.set_title("Click = accept/reject. Shift-click two fragments, then Stitch.")
        def draw_frame():
            """Show proxy frame `view['frame']` under the tracks, plus a marker
            per track at that frame so a track can be matched to an animal."""
            proxy=self._proxy
            if proxy is None or not len(proxy):return
            index=max(0,min(int(view["frame"]),len(proxy)-1))
            apply_trail()
            height,width=self._proxy_shape
            if view["image"] is None:
                view["image"]=ax.imshow(proxy[index],cmap="gray",
                                        extent=[0,width,height,0],aspect="equal",zorder=0)
                ax.set_xlim(0,width);ax.set_ylim(height,0)
            else:
                view["image"].set_data(proxy[index])
            here=tracks[tracks.frame==index]
            offsets=(here[["x","y"]].to_numpy(float) if len(here)
                     else np.empty((0,2),float))
            colors=["#22d3ee" if int(t) in selected else ("lime" if accepted.get(int(t),False) else "orange")
                    for t in here.track_id] if len(here) else []
            if view["marks"] is None:
                view["marks"]=ax.scatter(offsets[:,0] if len(offsets) else [],
                                         offsets[:,1] if len(offsets) else [],
                                         s=46,facecolors="none",linewidths=1.8,
                                         edgecolors=colors or "none",zorder=4)
            else:
                view["marks"].set_offsets(offsets)
                view["marks"].set_edgecolors(colors or "none")
            # A big, unmistakable dot on the track being inspected, plus the id
            # beside every animal, so the frame where a track jumps to the wrong
            # animal can be found and split exactly there.
            focus=(here[here.track_id.astype(int).isin(selected)][["x","y"]].to_numpy(float)
                   if len(here) and selected else np.empty((0,2),float))
            if view["focus"] is None:
                view["focus"]=ax.scatter(focus[:,0] if len(focus) else [],
                                         focus[:,1] if len(focus) else [],
                                         s=210,marker="o",facecolors="#ff2fd0",
                                         edgecolors="white",linewidths=2.0,
                                         alpha=.95,zorder=6)
            else:
                view["focus"].set_offsets(focus)
            manual_here=(here[here[MANUAL_POINT_COLUMN].astype(bool)][["x","y"]].to_numpy(float)
                         if len(here) and MANUAL_POINT_COLUMN in here else np.empty((0,2),float))
            if view["manual"] is None:
                view["manual"]=ax.scatter(manual_here[:,0] if len(manual_here) else [],
                                          manual_here[:,1] if len(manual_here) else [],
                                          s=150,marker="D",facecolors="none",
                                          edgecolors="#facc15",linewidths=2.0,zorder=7)
            else:
                view["manual"].set_offsets(manual_here)
            for artist in view["labels"]:
                try:artist.remove()
                except Exception:pass
            view["labels"]=[]
            for _,row in here.iterrows():
                tid=int(row.track_id)
                view["labels"].append(ax.text(
                    float(row.x)+14,float(row.y)-14,str(tid),
                    color="#ff2fd0" if tid in selected else "white",
                    fontsize=10 if tid in selected else 8,
                    fontweight="bold" if tid in selected else "normal",
                    zorder=8,clip_on=True,
                    bbox=dict(boxstyle="round,pad=0.15",facecolor="black",
                              edgecolor="none",alpha=.45)))
            focus_note=(f"  |  track {', '.join(str(t) for t in selected)} highlighted"
                        if selected else "  |  shift-click a track to highlight it")
            ax.set_title(f"Frame {index+1} of {len(proxy)}{focus_note}")
            self.review_canvas.draw_idle()
        def on_slider(value):
            view["frame"]=int(value);draw_frame()
        def frames_ready():
            """Called once the background proxy pass finishes."""
            proxy=self._proxy
            if proxy is None or not len(proxy):return
            fig.subplots_adjust(bottom=.13)
            view["slider_ax"]=fig.add_axes([.15,.035,.64,.035])
            view["slider"]=Slider(view["slider_ax"],"Frame",0,max(0,len(proxy)-1),
                                  valinit=0,valstep=1)
            view["slider"].on_changed(on_slider)
            if view["play_button"] is not None:
                view["play_button"].state(["!disabled"])
            draw_frame()
        def tick():
            proxy=self._proxy
            if not view["playing"] or proxy is None or not len(proxy):return
            view["frame"]=(int(view["frame"])+1)%len(proxy)
            if view["slider"] is not None:
                view["slider"].set_val(view["frame"])
            else:
                draw_frame()
            view["timer"]=self.after(max(20,int(1000/max(1.0,float(self.fps.get() or 20)))),tick)
        def toggle_play():
            proxy=self._proxy
            if proxy is None or not len(proxy):return
            view["playing"]=not view["playing"]
            if view["play_button"] is not None:
                view["play_button"].config(text="Pause" if view["playing"] else "Play frames")
            if view["playing"]:tick()
            elif view["timer"] is not None:
                try:self.after_cancel(view["timer"])
                except Exception:pass
                view["timer"]=None
        def stop_play():
            view["playing"]=False
            if view["timer"] is not None:
                try:self.after_cancel(view["timer"])
                except Exception:pass
                view["timer"]=None
        def save_progress(_event=None):
            tracks.to_csv(out/"reviewed_detections_and_tracks.csv",index=False)
            (out/"track_stitch_edits.json").write_text(json.dumps(edits,indent=2),encoding="utf-8")
            summary.to_csv(out/"track_summary_after_stitching.csv",index=False)
            saved=summary.copy();saved["accepted"]=saved.track_id.map(accepted).fillna(False)
            saved["review_status"]=np.where(saved.accepted,"accepted","rejected")
            saved.to_csv(out/"reviewed_track_summary.csv",index=False)
            self.status.set(f"Track-review progress saved: {out}")
        def redraw():
            nonlocal lines,groups
            for line in list(lines): line.remove()
            lines={}
            groups={int(tid):g.sort_values("frame") for tid,g in tracks.groupby("track_id")}
            for tid,g in groups.items():
                colour,width,alpha=style_for(tid)
                v=visible_span(g)
                line,=ax.plot(v.x,v.y,lw=width,color=colour,alpha=alpha,picker=5,zorder=3)
                lines[line]=int(tid)
            summary_label.config(text=population_track_summary(summary,accepted))
            draw_frame();self.review_canvas.draw_idle()
        def pick(event):
            tid=lines.get(event.artist)
            if tid is None:return
            if view["editing"]:return          # clicks are placing points, not judging
            if event.mouseevent.key == "shift":
                if tid in selected:selected.remove(tid)
                else:selected.append(tid)          # any number, not just two
                self.log("Track selected" if tid in selected else "Track deselected",
                         f"track {tid}; {len(selected)} selected: "
                         +(", ".join(str(t) for t in sorted(selected)) or "none"),status="review")
                redraw();return
            accepted[tid]=not accepted.get(tid,False);redraw();save_progress()
            self.log("Accepted track" if accepted[tid] else "Rejected track",f"track {tid}",status="review")
        def stitch(_event=None):
            nonlocal tracks,summary
            if len(selected)<2:
                messagebox.showinfo("Stitch tracks",
                    "Shift-click two or more track fragments first (or use Lasso select).",
                    parent=self);return
            groups=[tracks[tracks.track_id==tid].sort_values("frame") for tid in selected]
            groups=[g for g in groups if len(g)]
            groups.sort(key=lambda g:g.frame.min())
            for earlier,later in zip(groups,groups[1:]):
                if int(earlier.frame.max())>=int(later.frame.min()):
                    messagebox.showerror("Stitch tracks",
                        f"Tracks {int(earlier.track_id.iloc[0])} and "
                        f"{int(later.track_id.iloc[0])} overlap in time, so they cannot "
                        "safely be the same animal.",parent=self);return
            steps=[]
            for earlier,later in zip(groups,groups[1:]):
                steps.append((int(later.frame.min()-earlier.frame.max()),
                              float(np.hypot(later.x.iloc[0]-earlier.x.iloc[-1],
                                             later.y.iloc[0]-earlier.y.iloc[-1]))))
            order=[int(g.track_id.iloc[0]) for g in groups]
            detail="\n".join(f"    {a} -> {b}: gap {gap} frames, {dist:.0f} px"
                             for (a,b),(gap,dist) in zip(zip(order,order[1:]),steps))
            if not messagebox.askyesno("Confirm stitch",
                f"Join {len(order)} fragments into one animal, in time order?\n\n"
                f"    {' -> '.join(str(o) for o in order)}\n\n{detail}\n\n"
                f"All become track {order[0]}.",parent=self):
                return
            undo.append((tracks.copy(),summary.copy(),accepted.copy(),edits.copy()))
            keep=order[0]
            for drop in order[1:]:
                tracks.loc[tracks.track_id==drop,"track_id"]=keep
                accepted[keep]=accepted.get(keep,False) or accepted.get(drop,False)
                accepted.pop(drop,None)
            resummarise()
            edits.append({"kept_track_id":keep,"merged_track_ids":order[1:],
                          "gaps_frames":[g for g,_ in steps],
                          "endpoint_distances_px":[d for _,d in steps]})
            selected.clear();redraw();save_progress()
            self.log("Stitched fragments",
                     f"{len(order)} fragments merged into track {keep}: "
                     +" -> ".join(str(o) for o in order),status="edit")
        def toggle_lasso():
            if view.get("lasso") is not None:
                try:view["lasso"].disconnect_events()
                except Exception:pass
                view["lasso"]=None
                lasso_button.config(text="Lasso select tracks")
                wb_status("Track review: click a track to accept or reject it.")
                return
            def on_lasso(vertices):
                if len(vertices)<3:return
                path=MplPath(vertices)
                inside=path.contains_points(tracks[["x","y"]].to_numpy(float))
                hit=sorted({int(t) for t in tracks.loc[inside,"track_id"]})
                selected.clear();selected.extend(hit)
                self.log("Lasso selection",
                         f"{len(hit)} track(s) enclosed: "
                         +(", ".join(str(t) for t in hit) or "none"),status="review")
                toggle_lasso();redraw()
            view["lasso"]=LassoSelector(ax,onselect=on_lasso)
            lasso_button.config(text="Cancel lasso")
            wb_status("Draw around the tracks you want to select, then Stitch or Delete them.")
        def fill_gaps(_event=None):
            nonlocal tracks
            if len(selected)!=1:
                messagebox.showinfo("Fill gaps","Shift-click exactly one track first.",parent=self);return
            tid=int(selected[0])
            group=tracks[tracks.track_id==tid].sort_values("frame")
            detected=group[~group[MANUAL_POINT_COLUMN].astype(bool)]
            if len(detected)<2:
                messagebox.showinfo("Fill gaps","That track has too few detected points to bridge.",parent=self);return
            frames=detected.frame.astype(int).to_numpy()
            gaps=[(int(a),int(b)) for a,b in zip(frames,frames[1:]) if b-a>1]
            if not gaps:
                messagebox.showinfo("Fill gaps",f"Track {tid} has no gaps between detected frames.",parent=self);return
            missing=sum(b-a-1 for a,b in gaps)
            if not messagebox.askyesno("Fill gaps",
                f"Track {tid} has {len(gaps)} gap(s) totalling {missing} frame(s).\n\n"
                "Insert a straight-line point at every missing frame?\n\n"
                "These are interpolated, not observed: they are flagged manual_point "
                "and are excluded from speed, coverage, frequency and curvature. They "
                "only carry identity across the gap.",parent=self):
                return
            undo.append((tracks.copy(),summary.copy(),accepted.copy(),edits.copy()))
            template=group.sort_values("frame").iloc[-1].to_dict()
            new_rows=[]
            for a,b in gaps:
                start=detected[detected.frame==a].iloc[0];end=detected[detected.frame==b].iloc[0]
                for frame in range(a+1,b):
                    t=(frame-a)/float(b-a)
                    row=dict(template)
                    row.update({"track_id":tid,"frame":frame,
                                "time_s":frame/max(1e-6,float(self.fps.get())),
                                "x":float(start.x+(end.x-start.x)*t),
                                "y":float(start.y+(end.y-start.y)*t),
                                "spine_valid":False,"spine_x_json":"","spine_y_json":"",
                                "curvature_json":"","midbody_curvature_px_inv":np.nan,
                                "spine_skip_reason":"manual_gap_fill",
                                "step_px":np.nan,"speed_um_s":np.nan,
                                MANUAL_POINT_COLUMN:True})
                    new_rows.append(row)
            tracks=pd.concat([tracks,pd.DataFrame(new_rows)],ignore_index=True)
            resummarise();redraw();save_progress()
            edits.append({"gap_filled_track_id":tid,"gaps":gaps,"points_added":len(new_rows)})
            self.log("Gaps filled",
                     f"track {tid}: {len(new_rows)} interpolated point(s) across {len(gaps)} gap(s); "
                     "identity only, excluded from every measurement.",status="edit")
        def undo_stitch(_event=None):
            nonlocal tracks,summary,accepted,edits
            if not undo:return
            tracks,summary,accepted,edits=undo.pop();selected.clear();redraw();save_progress()
            self.log("Undid stitch",f"{len(edits)} stitch edit(s) remain.",status="edit")
        def resummarise():
            nonlocal tracks,summary
            tracks,summary=summarize_tracks(tracks,float(self.fps.get()),
                                            float(self.scale.get()),analyzed_frame_count)
        def toggle_edit():
            if view["editing"]:
                view["editing"]=False;view["edit_track"]=None
                edit_button.config(text="Add missing points to a track")
                wb_status("Track review: click a track to accept or reject it.")
                redraw();return
            if len(selected)!=1:
                messagebox.showinfo("Add missing points",
                    "Shift-click exactly one track first, then press this to start "
                    "adding points to it.",parent=self);return
            view["editing"]=True;view["edit_track"]=int(selected[0])
            edit_button.config(text="Stop adding points")
            wb_status(f"Adding points to track {view['edit_track']}: scrub to a frame, "
                      "then click where the animal is. Points you place carry identity "
                      "only - they never contribute to a measurement.")
            self.log("Manual point mode",
                     f"track {view['edit_track']}; placed points are flagged manual_point "
                     "and excluded from speed, coverage, frequency and curvature.",
                     status="edit")
            redraw()
        def add_manual_point(event):
            nonlocal tracks
            if not view["editing"] or event.inaxes is not ax:return
            if event.button!=1 or event.xdata is None or event.ydata is None:return
            if getattr(self.review_toolbar,"mode",""):return      # zoom/pan active
            tid=int(view["edit_track"]);frame=int(view["frame"])
            group=tracks[tracks.track_id==tid]
            if group.empty:return
            template=group.sort_values("frame").iloc[-1].to_dict()
            template.update({"track_id":tid,"frame":frame,
                             "time_s":frame/max(1e-6,float(self.fps.get())),
                             "x":float(event.xdata),"y":float(event.ydata),
                             "spine_valid":False,"spine_x_json":"","spine_y_json":"",
                             "curvature_json":"","midbody_curvature_px_inv":np.nan,
                             "spine_skip_reason":"manual_point",
                             "step_px":np.nan,"speed_um_s":np.nan,
                             MANUAL_POINT_COLUMN:True})
            undo.append((tracks.copy(),summary.copy(),accepted.copy(),edits.copy()))
            tracks=tracks[~((tracks.track_id==tid)&(tracks.frame==frame))]
            tracks=pd.concat([tracks,pd.DataFrame([template])],ignore_index=True)
            resummarise();redraw();save_progress()
            self.log("Manual point added",
                     f"track {tid}, frame {frame} at ({event.xdata:.0f}, {event.ydata:.0f}); "
                     "identity only, not a measurement.",status="edit")
        def delete_selected(_event=None):
            nonlocal tracks
            if not selected:
                messagebox.showinfo("Delete track","Shift-click one or two tracks first.",parent=self);return
            victims=[int(t) for t in selected]
            if not messagebox.askyesno("Delete track",
                f"Remove track(s) {', '.join(str(v) for v in victims)} entirely?\n\n"
                "Their detections are dropped from the reviewed outputs. The original "
                "detections_and_tracks.csv is not modified.",parent=self):
                return
            undo.append((tracks.copy(),summary.copy(),accepted.copy(),edits.copy()))
            tracks=tracks[~tracks.track_id.isin(victims)]
            for victim in victims:accepted.pop(victim,None)
            edits.append({"deleted_track_ids":victims})
            selected.clear();resummarise();redraw();save_progress()
            self.log("Deleted track(s)",", ".join(str(v) for v in victims),status="edit")
        def split_here(_event=None):
            nonlocal tracks
            if len(selected)!=1:
                messagebox.showinfo("Split track","Shift-click exactly one track first.",parent=self);return
            tid=int(selected[0]);frame=int(view["frame"])
            group=tracks[tracks.track_id==tid]
            if group.empty or not (group.frame.min()<frame<=group.frame.max()):
                messagebox.showinfo("Split track",
                    f"Scrub to a frame inside track {tid} "
                    f"({int(group.frame.min())}-{int(group.frame.max())}) first.",parent=self);return
            undo.append((tracks.copy(),summary.copy(),accepted.copy(),edits.copy()))
            new_id=int(tracks.track_id.max())+1
            tracks.loc[(tracks.track_id==tid)&(tracks.frame>=frame),"track_id"]=new_id
            accepted[new_id]=accepted.get(tid,False)
            edits.append({"split_track_id":tid,"new_track_id":new_id,"at_frame":frame})
            selected.clear();resummarise();redraw();save_progress()
            self.log("Split track",f"track {tid} split at frame {frame}; tail became track {new_id}.",status="edit")
        def request_rescue(_event=None):
            save_progress()
            approved=[tid for tid,value in accepted.items() if value]
            if not approved:
                messagebox.showinfo("Rescue unresolved tracks",
                                    "Approve at least one good track before locking it.",
                                    parent=self)
                return
            rescue_requested["value"]=True
            finish()
        def finish(_event=None):
            """What used to happen when the review window was closed."""
            stop_play();save_progress()
            if rescue_requested["value"]:
                self._release_proxy()
                self._show_page("setup")
                self.start_rescue_pass(out,tracks,accepted,metadata)
                return
            # Keep the proxy: the bout stage previews off the same frames.
            reviewed=summary.copy();reviewed["accepted"]=reviewed.track_id.map(accepted).fillna(False);reviewed["review_status"]=np.where(reviewed.accepted,"accepted","rejected")
            reviewed.to_csv(Path(out)/"reviewed_track_summary.csv",index=False)
            self.log("Track review complete",f"{int(reviewed.accepted.sum())} of {len(summary)} tracks accepted.",status="done")
            self.review_modalities(Path(out),set(reviewed.loc[reviewed.accepted,"track_id"].astype(int)),tracks,
                                   on_done=lambda:self._finish_run(out,summary,reviewed))
        self.status.set("Track review: click a track to accept or reject it. Movie frames are loading underneath...")
        self._clear_review_controls()
        self._control_label("Track review")
        summary_label=self._control_label(population_track_summary(summary,accepted))
        self._control_separator()
        trail_row=ttk.Frame(self.controls_review);trail_row.pack(fill="x",padx=4,pady=3)
        ttk.Label(trail_row,text="Trail").pack(side="left")
        trail_choice=tk.StringVar(value=TRAIL_DEFAULT)
        def on_trail(_event=None):
            view["trail"]=TRAIL_OPTIONS.get(trail_choice.get(),0)
            redraw()
        trail_box=ttk.Combobox(trail_row,textvariable=trail_choice,
                               values=list(TRAIL_OPTIONS),state="readonly",width=14)
        trail_box.pack(side="right");trail_box.bind("<<ComboboxSelected>>",on_trail)
        view["trail"]=TRAIL_OPTIONS.get(TRAIL_DEFAULT,0)
        view["play_button"]=self._control_button("Play frames",toggle_play)
        view["play_button"].state(["disabled"])
        self._control_button("Save progress",save_progress)
        self._control_separator()
        self._control_label("Edit tracks  (shift-click any number to select)")
        lasso_button=self._control_button("Lasso select tracks",toggle_lasso)
        self._control_button("Stitch selected into one",stitch)
        edit_button=self._control_button("Add missing points to a track",toggle_edit)
        self._control_button("Fill gaps in selected track",fill_gaps)
        self._control_button("Split at current frame",split_here)
        self._control_button("Delete selected track(s)",delete_selected)
        self._control_button("Undo last edit",undo_stitch)
        self._control_label("Points you place carry identity across frames the detector "
                            "missed. They are flagged manual_point and are excluded from "
                            "speed, coverage, frequency and curvature - only detected "
                            "positions are ever measured.")
        self._control_separator()
        self._control_button("Confirm calibration for the lab library",self.confirm_calibration)
        self._control_button("Lock good + rescue rest",request_rescue)
        self._control_button("Continue to bout review",finish)
        fig.canvas.mpl_connect("pick_event",pick)
        fig.canvas.mpl_connect("button_press_event",add_manual_point)
        self._show_page("review")
        self.review_canvas.draw_idle()
        self._build_proxy_async(frames_ready)

    def _calibration_review(self,out,summary,metadata):
        """Compare this run against reference ranges, and store what was inferred.

        The provenance is written whether or not anything looked wrong, and
        whether or not the student acts on it, so returning to the dataset later
        shows which estimates existed and what disagreed at the time.
        """
        out=Path(out)
        try:declared_scale=float(self.scale.get())
        except (TypeError,ValueError):declared_scale=None
        try:declared_fps=float(self.fps.get())
        except (TypeError,ValueError):declared_fps=None
        stage=self._stage_key();vessel=self._vessel_key()
        mode=self.locomotion_mode.get() or "crawling"

        speed=freq=None
        try:
            eligible=summary[summary.eligible_for_frequency.astype(bool)] if "eligible_for_frequency" in summary else summary
            speed=float(pd.to_numeric(eligible.mean_speed_um_s,errors="coerce").median())
            freq=float(pd.to_numeric(eligible.spine_bend_frequency_hz,errors="coerce").median())
        except Exception:
            pass
        if speed is not None and not np.isfinite(speed):speed=None
        if freq is not None and not np.isfinite(freq):freq=None

        container_fps=metadata.get("fps_from_container") or metadata.get("container_fps")
        warnings=wr.review(length_px=self._traced_length_px,um_per_px=declared_scale,
                           stage=stage,speed_um_s=speed,freq_hz=freq,mode=mode,
                           declared_fps=declared_fps,container_fps=container_fps)
        for warning in warnings:
            self.log(f"Check: {warning.subject}",
                     f"{warning.observed} vs {warning.expected}. {warning.message}",
                     status="warning")
        if not warnings:
            self.log("Calibration checks","Nothing looked out of range for "
                     f"{wr.STAGE_LABELS.get(stage,stage)} {mode}.",status="done")

        substrate=None
        try:
            background=out/"background_reference.png"
            if background.exists():
                substrate=st.read_substrate(st.substrate_metrics(
                    cv2.imread(str(background),cv2.IMREAD_GRAYSCALE)))
        except Exception:
            substrate=None
        if substrate:
            self.log("Substrate reading",
                     f"{substrate['label']} ({substrate['confidence']}). {substrate['basis']}",
                     status="info")

        provenance=wr.calibration_provenance(
            declared_um_per_px=declared_scale,declared_fps=declared_fps,
            container_fps=container_fps,stage=stage,vessel=vessel,
            estimates=list(self._scale_estimates),warnings=warnings,
            confirmed=False,substrate=substrate,
            notes=f"expected locomotion mode: {mode}")
        provenance["measured"]={"median_speed_um_s":speed,"median_bend_hz":freq,
                                "traced_worm_length_px":self._traced_length_px}
        try:
            (out/"calibration_provenance.json").write_text(
                json.dumps(provenance,indent=2),encoding="utf-8")
        except Exception:
            pass
        self._pending_calibration=(provenance,out,stage,mode,speed,freq,declared_scale,declared_fps)
        return warnings

    def confirm_calibration(self):
        """Record this run in the lab library as a trusted example.

        Only confirmed runs shape the lab's own reference ranges - otherwise a
        run with a mistaken frame rate would teach the library that the mistake
        is normal.
        """
        pending=getattr(self,"_pending_calibration",None)
        if not pending:
            messagebox.showinfo("Confirm calibration",
                "Run an analysis first - there is nothing to confirm yet.",parent=self);return
        provenance,out,stage,mode,speed,freq,scale,fps=pending
        if not messagebox.askyesno("Confirm calibration",
            f"Record this run as a trusted example?\n\n"
            f"    stage    {wr.STAGE_LABELS.get(stage,stage)}\n"
            f"    mode     {mode}\n"
            f"    scale    {scale if scale else '-'} um/px\n"
            f"    fps      {fps if fps else '-'}\n"
            f"    speed    {f'{speed:,.0f} um/s' if speed else '-'}\n"
            f"    bend     {f'{freq:.2f} Hz' if freq else '-'}\n\n"
            "Confirm only if the frame rate and scale are right. Confirmed runs "
            "become part of this lab's own reference ranges, so a run confirmed "
            "in error teaches the mistake to every later check.",parent=self):
            return
        wr.record_observation(module="population_tracking",run_id=Path(out).name,
                              stage=stage,mode=mode,
                              length_px=self._traced_length_px,um_per_px=scale,
                              speed_um_s=speed,freq_hz=freq,declared_fps=fps,
                              confirmed=True,warnings=[])
        provenance["confirmed_by_user"]=True
        try:
            (Path(out)/"calibration_provenance.json").write_text(
                json.dumps(provenance,indent=2),encoding="utf-8")
        except Exception:
            pass
        summary=wr.library_summary()
        self.log("Calibration confirmed",
                 f"recorded to the lab library; it now holds "
                 f"{summary['observations_confirmed']} confirmed observation(s) "
                 f"({summary['observations_excluded']} excluded).",status="done")
        self.status.set("Calibration confirmed and recorded in the lab library.")

    def _finish_run(self,out,summary,reviewed):
        """Tail of a completed run: status, feedback prompt, back to setup."""
        self._release_proxy()
        self._show_page("setup")
        self.go.state(["!disabled"])
        self.status.set(f"Complete: {len(summary)} candidate tracks, {int(reviewed.accepted.sum())} accepted. Results: {out}")
        messagebox.showinfo("Complete",self.status.get(),parent=self)
        acquisition=AcquisitionMetadata(float(self.fps.get()),"declared",float(self.scale.get()),"declared",None,"not_applicable",compression="unknown",channel_identity="brightfield",anatomical_orientation="unknown")
        evidence=[Path(out)/name for name in ("analysis_metadata.json","reviewed_track_summary.csv","reviewed_modality_bouts.csv") if (Path(out)/name).exists()]
        prompt_post_run_feedback(tool_name="Population swimming + modality review",tool_version="1.0.0",run_id=Path(out).name,acquisition=acquisition,parameters={"minimum_object_area_px":int(self.minarea.get()),"maximum_object_area_px":int(self.maxarea.get()),"roi_mode":self.roi_mode.get(),"start_frame":int(self.start_frame.get()),"end_frame":self.end_frame.get().strip() or "last"},parent=self,evidence_paths=evidence)

    def start_rescue_pass(self,out,tracks,accepted,metadata):
        out=Path(out)
        locked_ids=sorted(int(tid) for tid,value in accepted.items() if value)
        locked=tracks[tracks.track_id.astype(int).isin(locked_ids)].copy()
        locked.to_csv(out/"locked_approved_tracks.csv",index=False)
        (out/"locked_tracks_manifest.json").write_text(json.dumps({
            "locked_track_ids":locked_ids,
            "locked_rows":int(len(locked)),
            "source_results":str(out),
            "rule":"Locked tracks are preserved exactly; rescue detections within 40 source pixels are suppressed.",
        },indent=2),encoding="utf-8")
        current=str(metadata.get("spine_skeleton_method",SPINE_METHOD_DEFAULT))
        escalate="thinning" if current=="morphological" else current
        escalation_note=("" if escalate==current else
                         "\n\nThe rerun will also switch the skeleton from the standard "
                         "method to connected thinning, which does not fragment on thick "
                         "masks. Rescued tracks are therefore NOT directly comparable with "
                         "the locked ones; the method is recorded in each result folder.")
        use_alternate=messagebox.askyesno(
            "Rescue unresolved tracks",
            f"Saved {len(locked_ids)} approved track(s) as locked.\n\n"
            "Rerun the unresolved remainder with the experimental initial-segment "
            "single-pass background?"
            f"{escalation_note}\n\n"
            "Choose No to keep the locked file and continue corrections manually. "
            "The robust two-pass result remains untouched.",
            parent=self)
        if not use_alternate:
            self.go.state(["!disabled"])
            self.status.set(f"Locked approved tracks saved for manual continuation: {out}")
            return
        pass_number=2
        while (out/f"rescue_pass_{pass_number}").exists():
            pass_number+=1
        rescue_out=out/f"rescue_pass_{pass_number}"
        self.status.set("Rerunning unresolved regions with alternate background...")
        self.go.state(["disabled"])
        self.log("Rescue pass",
                 f"Locked {len(locked_ids)} approved track(s); rerunning the remainder"
                 +(f" with the {escalate} skeleton." if escalate!=current else "."),
                 status="running")
        threading.Thread(
            target=self._run_rescue_pass,
            args=(rescue_out,locked,metadata,out,escalate),
            daemon=True,
        ).start()

    def _run_rescue_pass(self,rescue_out,locked,metadata,parent_out,spine_method=SPINE_METHOD_DEFAULT):
        try:
            summary,new_out=analyze(
                metadata["input_source"],float(metadata["fps"]),float(metadata["um_per_px"]),
                output_dir=rescue_out,min_area=int(metadata.get("min_area_px",40)),
                max_area=int(metadata.get("max_area_px",2500)),
                progress=lambda i,n,phase="Rescue":self.after(
                    0,self.status.set,f"{phase}: {float(i):.1f} of {n}..."),
                roi_records=self.roi_records,roi_mode=self.roi_mode.get(),
                start_frame=int(metadata.get("source_frame_start_1_based",1)),
                end_frame=int(metadata.get("source_frame_end_1_based",metadata["n_frames"])),
                detection_scale=float(metadata.get("detection_scale",0.5)),
                adaptive_background_sampling=bool(metadata.get("adaptive_background_sampling",True)),
                fast_first_pass=True,single_pass_background=True,
                cache_two_pass_proxy=False,low_resolution_background=False,
                selective_background_decode=False,direct_uint8_proxy=True,
                locked_tracks=locked,locked_exclusion_radius_px=40.0,
                spine_method=spine_method)
            (Path(new_out)/"rescue_provenance.json").write_text(json.dumps({
                "parent_results":str(parent_out),
                "method":"experimental_initial_segment_single_pass_background",
                "parent_spine_skeleton_method":str(metadata.get("spine_skeleton_method",SPINE_METHOD_DEFAULT)),
                "rescue_spine_skeleton_method":str(spine_method),
                "comparability":("Rescued tracks were extracted with a different skeleton "
                                 "method than the locked ones; curvature and bend frequency "
                                 "are not directly comparable between them."
                                 if str(spine_method)!=str(metadata.get("spine_skeleton_method",SPINE_METHOD_DEFAULT))
                                 else "Same skeleton method as the parent run."),
                "locked_track_ids":sorted(locked.track_id.astype(int).unique().tolist()),
            },indent=2),encoding="utf-8")
            self.after(0,self.review,summary,new_out,True)
        except Exception as exc:
            self.after(0,self.fail,str(exc))

    def resume_review(self):
        folder=filedialog.askdirectory(title="Choose a population tracking results folder")
        if not folder:return
        out=Path(folder);metadata_path=out/"analysis_metadata.json"
        if not metadata_path.exists() or not (out/"detections_and_tracks.csv").exists():
            messagebox.showerror("Resume review","That folder does not contain population-swimming results.");return
        try:
            metadata=json.loads(metadata_path.read_text(encoding="utf-8"))
            self.source.set(str(metadata["input_source"]));self.fps.set(str(metadata["fps"]));self.scale.set(str(metadata["um_per_px"]))
            self.start_frame.set(str(metadata.get("source_frame_start_1_based",1)))
            end=metadata.get("source_frame_end_1_based");self.end_frame.set("" if end is None else str(end))
            self.roi_mode.set(str(metadata.get("roi_mode","none")))
            method=str(metadata.get("spine_skeleton_method",SPINE_METHOD_DEFAULT))
            self.spine_method.set(SPINE_METHOD_LABELS.get(method,SPINE_METHOD_LABELS[SPINE_METHOD_DEFAULT]))
            roi_path=out/"analysis_rois.json"
            if roi_path.exists():self.roi_records=json.loads(roi_path.read_text(encoding="utf-8")).get("rois",[])
            self.roi_label.config(text=f"{len(self.roi_records)} ROI(s)")
            summary_path=out/"track_summary_after_stitching.csv"
            summary=pd.read_csv(summary_path if summary_path.exists() else out/"track_summary.csv")
            self.review(summary,out)
        except Exception as exc:messagebox.showerror("Resume review",str(exc))

    def recompute_run(self):
        """Correct a finished run's declared scale or frame rate, without re-detecting.

        Detection, linking and spines depend only on pixels and frame numbers,
        so they are reused as-is. Everything that depends on the declared
        parameters is re-derived - not rescaled, because the modality
        classifier compares frequency against fixed thresholds.
        """
        folder=filedialog.askdirectory(title="Choose the results folder to correct",
                                       parent=self)
        if not folder:return
        out=Path(folder)
        if not (out/"detections_and_tracks.csv").exists():
            messagebox.showerror("Correct a run",
                "That folder has no detections_and_tracks.csv, so there is nothing "
                "to recompute from.",parent=self);return
        metadata={}
        try:
            metadata=json.loads((out/"analysis_metadata.json").read_text(encoding="utf-8"))
        except Exception:
            pass
        old_fps=metadata.get("fps");old_scale=metadata.get("um_per_px")
        dialog=tk.Toplevel(self);apply_wink_theme(dialog)
        dialog.title("Correct scale or frame rate")
        try:
            screen_w=dialog.winfo_screenwidth();screen_h=dialog.winfo_screenheight()
        except Exception:
            screen_w,screen_h=1366,768
        win_w=max(520,min(600,screen_w-80));win_h=max(340,min(430,screen_h-120))
        dialog.geometry(f"{win_w}x{win_h}+{max(0,(screen_w-win_w)//2)}+{max(0,(screen_h-win_h)//3)}")
        try:dialog.resizable(True,True)
        except Exception:pass
        ttk.Label(dialog,text=out.name,font=("Segoe UI",10,"bold")).pack(anchor="w",padx=12,pady=(12,2))
        ttk.Label(dialog,wraplength=win_w-40,justify="left",text=(
            f"This run was analysed with "
            f"{old_fps if old_fps else 'an unrecorded'} fps and "
            f"{old_scale if old_scale else 'an unrecorded'} um/pixel.\n\n"
            "Detection, linking and spines are reused unchanged - they depend only "
            "on pixels and frame numbers. Track summaries and modality proposals "
            "are recomputed, because the classifier compares frequency against "
            "fixed thresholds and cannot simply be rescaled.\n\n"
            "The original run is not modified; results go to a new folder beside "
            "it. Any review already done there does not carry over.")).pack(
            anchor="w",padx=12,pady=4)
        new_fps=tk.StringVar(value=str(old_fps or self.fps.get()))
        new_scale=tk.StringVar(value=str(old_scale or self.scale.get()))
        reason=tk.StringVar(value="")
        for label,var in (("Corrected FPS",new_fps),("Corrected um/pixel",new_scale),
                          ("Reason (recorded)",reason)):
            row=ttk.Frame(dialog);row.pack(fill="x",padx=12,pady=3)
            ttk.Label(row,text=label,width=20).pack(side="left")
            ttk.Entry(row,textvariable=var).pack(side="right",fill="x",expand=True)
        result={"go":False}
        buttons=ttk.Frame(dialog);buttons.pack(fill="x",padx=12,pady=(8,12))
        def go():
            result["go"]=True;dialog.destroy()
        ttk.Button(buttons,text="Cancel",command=dialog.destroy).pack(side="right",padx=4)
        ttk.Button(buttons,text="Recompute",command=go).pack(side="right",padx=4)
        dialog.grab_set()
        try:
            dialog.lift();dialog.focus_force()
        except Exception:pass
        self.wait_window(dialog)
        if not result["go"]:
            self.status.set("Correction cancelled.");return
        try:
            fps=float(new_fps.get());scale=float(new_scale.get())
        except (TypeError,ValueError):
            messagebox.showerror("Correct a run","FPS and um/pixel must be numbers.",parent=self);return
        self.go.state(["disabled"])
        self.status.set("Recomputing from the saved detections...")
        self.log("Correcting a finished run",
                 f"{out.name}: fps {old_fps} -> {fps}, um/px {old_scale} -> {scale}. "
                 "Detection is reused; summaries and modality proposals are re-derived.",
                 status="running")
        threading.Thread(target=self._run_recompute,args=(out,fps,scale,reason.get()),
                         daemon=True).start()

    def _run_recompute(self,out,fps,scale,reason):
        try:
            summary,new_out=recompute_from_detections(
                out,fps,scale,reason=reason,
                progress=lambda i,n,phase="Recomputing":self.after(
                    0,self.status.set,f"{phase}: {i} of {n}..."))
            self.fps.set(f"{fps:g}");self.scale.set(f"{scale:g}")
            self.after(0,self.review,summary,new_out,True)
        except Exception as exc:
            self.after(0,self.fail,str(exc))

    def draw_optional_rois(self):
        try:
            files=list_frames(self.source.get(),fast=True);image=read_gray(files[0])
        except Exception as exc:
            messagebox.showerror("ROIs",f"Choose a valid movie, stack, or image folder first.\n\n{exc}");return
        try:
            records=draw_rois(image,title="Draw optional spatial-filter ROIs — scroll to verify the useful scene",
                              allow_line=False,default_shape="Rectangle",label_prefix="Filter",
                              frame_count=len(files),frame_loader=lambda i: read_gray(files[int(i)]),
                              allow_empty=True)
        finally:
            files.close()
        if records is not None:
            self.roi_records=records;self.roi_label.config(text=f"{len(records)} ROI(s)")
            if self.roi_mode.get()=="none":self.roi_mode.set("exclude")
    def clear_rois(self):
        self.roi_records=[];self.roi_mode.set("none");self.roi_label.config(text="0 ROIs")

    def review_modalities(self,out,accepted_tracks,tracks,on_done=None):
        path=out/"modality_bouts_for_review.csv"
        bouts=pd.read_csv(path)
        if bouts.empty:
            if on_done:on_done()
            return
        bouts=bouts[bouts.track_id.astype(int).isin(accepted_tracks)].copy()
        if bouts.empty:
            if on_done:on_done()
            return
        # Before any bout is reviewed these columns are empty, so pandas reads
        # reviewed_modality as float64 - and writing "swimming" into a float
        # column raises TypeError on pandas >= 3.0. The exception surfaced only
        # on stderr, which pythonw discards, so Confirm/Relabel/Reject silently
        # did nothing. Coerce to object up front.
        for column in ("review_status","reviewed_modality"):
            if column not in bouts:
                bouts[column]=""
            bouts[column]=bouts[column].fillna("").astype("object")
        # The bout list is a table, so it lives under the review canvas in the
        # centre pane rather than in its own window; selecting a bout previews
        # it on that same canvas.
        self._ensure_review_surface()
        for child in self.review_table_holder.winfo_children():
            try:child.destroy()
            except Exception:pass
        self.review_table_holder.pack(fill="x",padx=4,pady=(0,4))
        self.log("Bout review",f"{len(bouts)} proposed bout(s) across {int(bouts.track_id.nunique())} accepted track(s).",status="ready")
        columns=("bout","track","start","end","proposal","confidence","frequency","speed","status","final")
        tree=ttk.Treeview(self.review_table_holder,columns=columns,show="headings",selectmode="extended",height=8)
        labels=("Bout","Track","Start (s)","End (s)","Proposal","Confidence","Hz","um/s","Review","Final label")
        widths=(55,55,75,75,95,80,65,80,85,90)
        for col,label,width in zip(columns,labels,widths):
            tree.heading(col,text=label);tree.column(col,width=width,anchor="center")
        for index,row in bouts.iterrows():
            tree.insert("", "end", iid=str(index), values=(int(row.bout_id),int(row.track_id),f"{row.start_time_s:.2f}",f"{row.end_time_s:.2f}",
                row.proposed_modality,f"{row.confidence:.2f}",f"{row.bend_frequency_hz:.2f}",f"{row.median_speed_um_s:.1f}",
                row.review_status,row.reviewed_modality))
        scroll=ttk.Scrollbar(self.review_table_holder,orient="vertical",command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left",fill="both",expand=True);scroll.pack(side="right",fill="y")
        choice=tk.StringVar(value="swimming")
        def update(status,label=None):
            for iid in tree.selection():
                idx=int(iid);bouts.at[idx,"review_status"]=status
                bouts.at[idx,"reviewed_modality"]=label if label is not None else ""
                values=list(tree.item(iid,"values"));values[-2]=status;values[-1]=label or "";tree.item(iid,values=values)
            self.log(f"Bout marked {status}",f"{len(tree.selection())} bout(s)"+(f" as {label}" if label else ""),status="review")
        def preview(_event=None):
            selected=tree.selection()
            if not selected:
                messagebox.showinfo("Preview","Select a bout first.",parent=self);return
            self.preview_bout(bouts.loc[int(selected[0])],tracks)
        tree.bind("<<TreeviewSelect>>",preview)
        tree.bind("<Double-1>",preview)
        def save():
            final=np.where(bouts.review_status=="confirmed",bouts.proposed_modality,
                  np.where(bouts.review_status=="relabeled",bouts.reviewed_modality,""))
            bouts["final_modality"]=final
            bouts.to_csv(out/"reviewed_modality_bouts.csv",index=False)
            included=bouts[bouts.final_modality!=""].copy()
            if len(included):
                aggregate=included.groupby("final_modality").agg(
                    bout_count=("bout_id","count"),total_duration_s=("duration_s","sum"),
                    mean_bout_duration_s=("duration_s","mean"),mean_bend_frequency_hz=("bend_frequency_hz","mean"),
                    mean_speed_um_s=("median_speed_um_s","mean")).reset_index()
                total=aggregate.total_duration_s.sum()
                aggregate["fraction_of_reviewed_time"]=aggregate.total_duration_s/total if total else np.nan
            else:
                aggregate=pd.DataFrame(columns=["final_modality","bout_count","total_duration_s","mean_bout_duration_s",
                                                "mean_bend_frequency_hz","mean_speed_um_s","fraction_of_reviewed_time"])
            aggregate.to_csv(out/"reviewed_modality_summary.csv",index=False)
            self.log("Bout review saved",f"{int((bouts.final_modality!='').sum())} of {len(bouts)} bout(s) carry a final label.",status="done")
            self._stop_bout_playback()
            self.review_table_holder.pack_forget()
            if on_done:on_done()
        self._clear_review_controls()
        self._control_label("Bout review")
        self._control_label("Select a bout to preview it above: yellow = spine, magenta = oriented end, cyan = bout trajectory. Low-confidence and uncertain bouts deserve priority.")
        self._control_separator()
        ttk.Combobox(self.controls_review,textvariable=choice,values=("swimming","crawling","burrowing","uncertain"),state="readonly",width=14).pack(fill="x",padx=4,pady=3)
        self._control_button("Confirm proposal",lambda:update("confirmed",None))
        self._control_button("Relabel as selected",lambda:update("relabeled",choice.get()))
        self._control_button("Reject / exclude",lambda:update("rejected",None))
        self._control_separator()
        self._bout_play_button=self._control_button("Play bout",self._toggle_bout_playback)
        self._bout_play_button.state(["disabled"])
        self._control_button("Save review and finish",save)
        self._show_page("review")

    def _stop_bout_playback(self):
        state=getattr(self,"_bout_view",None)
        if not state:return
        state["playing"]=False
        if state.get("timer") is not None:
            try:self.after_cancel(state["timer"])
            except Exception:pass
            state["timer"]=None
        button=getattr(self,"_bout_play_button",None)
        if button is not None:
            try:button.config(text="Play bout")
            except Exception:pass

    def _toggle_bout_playback(self):
        state=getattr(self,"_bout_view",None)
        if not state or not state.get("frames"):return
        state["playing"]=not state["playing"]
        button=getattr(self,"_bout_play_button",None)
        if button is not None:
            button.config(text="Pause" if state["playing"] else "Play bout")
        if state["playing"]:self._bout_tick()

    def _bout_tick(self):
        state=getattr(self,"_bout_view",None)
        if not state or not state.get("playing"):return
        state["index"]=(int(state["index"])+1)%len(state["frames"])
        self._draw_bout_frame()
        state["timer"]=self.after(max(25,int(1000/max(1.0,float(self.fps.get() or 20)))),self._bout_tick)

    def _draw_bout_frame(self):
        state=getattr(self,"_bout_view",None)
        proxy=self._proxy
        if not state or proxy is None or not len(proxy):return
        ax=self.review_ax;ax.clear()
        frame=state["frames"][int(state["index"])%len(state["frames"])]
        row=state["lookup"].loc[frame]
        if isinstance(row,pd.DataFrame):row=row.iloc[0]
        height,width=self._proxy_shape
        ax.imshow(proxy[max(0,min(int(frame),len(proxy)-1))],cmap="gray",
                  extent=[0,width,height,0],aspect="equal",zorder=0)
        track=state["track"]
        ax.plot(track.x,track.y,color="#22d3ee",lw=1,alpha=.55,zorder=2)
        try:
            sx=json.loads(row.spine_x_json);sy=json.loads(row.spine_y_json)
            ax.plot(sx,sy,color="#facc15",lw=2.2,zorder=3);ax.plot(sx[0],sy[0],"o",color="#ff4fd8",ms=5,zorder=4)
        except (TypeError,ValueError,json.JSONDecodeError):
            pass
        ax.plot(row.x,row.y,"o",color="lime",ms=4,zorder=4)
        bout=state["bout"]
        ax.set_title(f"Track {int(bout.track_id)} | proposed {bout.proposed_modality} | {row.time_s:.2f} s\n"
                     f"yellow=spine, magenta=oriented end, cyan=bout trajectory")
        ax.set_xlim(0,width);ax.set_ylim(height,0);ax.set_axis_off()
        self.review_canvas.draw_idle()

    def preview_bout(self,bout,tracks,parent=None):
        """Preview one bout on the shared centre canvas, off the proxy stack."""
        track=tracks[(tracks.track_id.astype(int)==int(bout.track_id)) &
                     (tracks.frame>=int(bout.start_frame)) & (tracks.frame<=int(bout.end_frame))].copy()
        if track.empty:
            self.status.set(f"Bout on track {int(bout.track_id)} has no tracked frames to preview.");return
        self._stop_bout_playback()
        frames=track.frame.astype(int).tolist()
        self._bout_view={"bout":bout,"track":track,"frames":frames,
                         "lookup":track.set_index(track.frame.astype(int)),
                         "index":0,"playing":False,"timer":None}
        self.log("Bout preview",
                 f"track {int(bout.track_id)}, source frames {int(bout.start_frame)}-{int(bout.end_frame)}; "
                 f"{len(frames)} tracked frame(s); proposed {bout.proposed_modality} at confidence {float(bout.confidence):.2f}.",
                 status="info")
        button=getattr(self,"_bout_play_button",None)
        if self._proxy is None:
            self.status.set("Preview frames are still decoding; the bout will draw when they are ready.")
            self._build_proxy_async(self._draw_bout_frame);return
        if button is not None:button.state(["!disabled"])
        self._draw_bout_frame()
    def fail(self,e): self.go.state(["!disabled"]); self.status.set("Analysis stopped."); messagebox.showerror("Population tracking",e)
if __name__=="__main__": App().mainloop()
