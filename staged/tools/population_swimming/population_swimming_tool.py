import threading
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider,Button
import numpy as np
import pandas as pd
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"app"))
from population_swimming import analyze,list_frames,read_gray,summarize_tracks
from roi_editor import draw_rois
from acquisition import AcquisitionMetadata
from acquisition_advisor import PROFILES
from run_feedback import prompt_post_run_feedback
from results_summary import population_track_summary
from process_ui import CockpitApp

class App(CockpitApp):
    def __init__(self):
        super().__init__("Population Swimming + Modality Review",geometry="1220x800",process_title="Population swimming / crawling")
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
        self.roi_mode=tk.StringVar(value="none");self.roi_records=[]
        self._build_controls();self._build_center()
        self.status.trace_add("write",lambda *_:self.set_status(self.status.get()));self.set_status(self.status.get())

    def _build_controls(self):
        c=self.controls
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
        perf=ttk.LabelFrame(c,text="Performance (rescaled to source coordinates)");perf.pack(fill="x",pady=6)
        pr=ttk.Frame(perf);pr.pack(fill="x",padx=6,pady=3);ttk.Label(pr,text="Detection resolution").pack(side="left");ttk.Combobox(pr,textvariable=self.detection_resolution,values=("Auto: lowest safe resolution","Original resolution","50% proxy","25% proxy (fastest)"),state="readonly",width=22).pack(side="right")
        for text,var in (("Adaptive background samples",self.adaptive_background),("Fast wrMTrck-style first pass",self.fast_first_pass),("Single-pass background (experimental; verify track count)",self.single_pass_background),("Cache decoded proxy locally (experimental)",self.cache_two_pass_proxy),("Low-resolution background (experimental; verify tracks)",self.low_resolution_background),("Pipe only selected background frames (experimental)",self.selective_background_decode),("Use decoder-ready 8-bit grayscale directly (recommended)",self.direct_uint8_proxy)):
            ttk.Checkbutton(perf,text=text,variable=var).pack(anchor="w",padx=6,pady=1)
        roi=ttk.LabelFrame(c,text="Optional spatial filtering (default: full frame)");roi.pack(fill="x",pady=6)
        rr=ttk.Frame(roi);rr.pack(fill="x",padx=6,pady=3);ttk.Label(rr,text="ROI action").pack(side="left");ttk.Combobox(rr,textvariable=self.roi_mode,values=("none","include","exclude"),state="readonly",width=10).pack(side="right")
        rb=ttk.Frame(roi);rb.pack(fill="x",padx=6,pady=3);ttk.Button(rb,text="Draw / replace ROIs",command=self.draw_optional_rois).pack(side="left");self.roi_label=ttk.Label(rb,text="0 ROIs");self.roi_label.pack(side="left",padx=8);ttk.Button(rb,text="Clear",command=self.clear_rois).pack(side="right")
        self.go=ttk.Button(c,text="Analyze population",command=self.start);self.go.pack(fill="x",pady=(8,2))
        ttk.Button(c,text="Resume existing results review",command=self.resume_review).pack(fill="x",pady=2)

    def _build_center(self):
        ttk.Label(self.center,text="Population swimming / crawling + modality review",font=("Segoe UI",12,"bold")).pack(anchor="w",padx=6,pady=(6,2))
        ttk.Label(self.center,wraplength=520,justify="left",foreground="#444444",text="Analyze a population recording, then review tracks and locomotion bouts in the pop-up windows. Include keeps detections whose centroids are inside any ROI; exclude suppresses detections inside any ROI. Shapes: oval/circle, rectangle, or polygon. Uncertain behavioral evidence is never forced into a class.").pack(anchor="w",padx=6,pady=4)
        ttk.Separator(self.center,orient="horizontal").pack(fill="x",padx=6,pady=6)
        ttk.Label(self.center,textvariable=self.status,wraplength=520,justify="left").pack(anchor="w",padx=6,pady=4)

    def _scale_value(self):
        try:return float(self.scale.get())
        except (TypeError,ValueError):return None
    def _current_frame(self):
        try:
            files=list_frames(self.source.get());img=read_gray(files[0]);files.close();return img
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
                probe=list_frames(selected)
                width,height=int(probe.movie.width),int(probe.movie.height);probe.close()
                typical_area=float(np.sqrt(minarea*maxarea))
                resolution=1.0
                if max(width,height)>=1800:
                    for candidate in (0.25,0.5,1.0):
                        if minarea*candidate*candidate>=8 and typical_area*candidate*candidate>=64:
                            resolution=candidate;break
                proxy_fps=float(self.fps.get());profile=PROFILES["Population swimming / modality"]
                messagebox.showinfo("WINK performance recommendation",
                    f"Recommended detection resolution: {int(resolution*100)}%\n\n"
                    f"Source: {width} x {height}; expected typical accepted object: about {typical_area*resolution*resolution:.0f} proxy pixels.\n"
                    f"Declared rate: {proxy_fps:.2f} fps. {profile.recommended_fps}; this recording should not be temporally reduced below {profile.analysis_floor_fps:g} fps.\n\n"
                    "If outlines or spines look poor, rerun one level higher. Original resolution remains the control.")
            else:
                resolution={"Original resolution":1.0,"50% proxy":0.5,"25% proxy (fastest)":0.25}[choice]
            args=(self.source.get(),float(self.fps.get()),float(self.scale.get()),None,int(self.minarea.get()),int(self.maxarea.get()),start_frame,end_frame,resolution,bool(self.adaptive_background.get()),bool(self.fast_first_pass.get()),bool(self.single_pass_background.get()),bool(self.cache_two_pass_proxy.get()),bool(self.low_resolution_background.get()),bool(self.selective_background_decode.get()),bool(self.direct_uint8_proxy.get()))
            if self.roi_mode.get()!="none" and not self.roi_records:
                if messagebox.askyesno("No ROI drawn","Include/Exclude was selected, but no ROI was drawn.\n\nContinue with the full frame instead?"):
                    self.roi_mode.set("none")
                else:raise ValueError("Draw at least one ROI or set ROI action to none.")
        except ValueError as exc: messagebox.showerror("Inputs",str(exc)); return
        self.go.state(["disabled"]); self.status.set("Indexing and analyzing in the background...")
        threading.Thread(target=self._run,args=(args,),daemon=True).start()
    def _run(self,args):
        try:
            source,fps,scale,output,minarea,maxarea,start_frame,end_frame,resolution,adaptive_background,fast_first_pass,single_pass_background,cache_two_pass_proxy,low_resolution_background,selective_background_decode,direct_uint8_proxy=args
            summary,out=analyze(source,fps,scale,output,minarea,maxarea,
                progress=lambda i,n,phase="Processing":self.after(
                    0,self.status.set,
                    f"{phase}: {float(i):.1f} of {n}..." if float(i)%1
                    else f"{phase}: {int(i)} of {n}..."),
                start_frame=start_frame,end_frame=end_frame,
                roi_records=self.roi_records,roi_mode=self.roi_mode.get(),
                detection_scale=resolution,adaptive_background_sampling=adaptive_background,
                fast_first_pass=fast_first_pass,single_pass_background=single_pass_background,
                cache_two_pass_proxy=cache_two_pass_proxy,
                low_resolution_background=low_resolution_background,
                selective_background_decode=selective_background_decode,
                direct_uint8_proxy=direct_uint8_proxy)
            self.after(0,self.review,summary,out)
        except Exception as e: self.after(0,self.fail,str(e))
    def review(self,summary,out):
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
        fig,ax=plt.subplots(); fig.subplots_adjust(bottom=.19); lines={}; selected=[]; undo=[]
        rescue_requested={"value":False}
        edit_path=out/"track_stitch_edits.json"
        edits=json.loads(edit_path.read_text(encoding="utf-8")) if edit_path.exists() else []
        for tid,g in tracks.groupby("track_id"):
            line,=ax.plot(g.x,g.y,lw=1,color="green" if accepted[int(tid)] else "orange",picker=5); lines[line]=int(tid)
        ax.invert_yaxis();ax.set_aspect("equal")
        summary_text=fig.text(.02,.97,population_track_summary(summary,accepted),va="top",fontsize=9)
        ax.set_title("Click = accept/reject. Shift-click two fragments, then Stitch. Close to save.")
        save_ax=fig.add_axes([.32,.035,.12,.06]);save_button=Button(save_ax,"Save progress")
        rescue_ax=fig.add_axes([.46,.035,.20,.06]);rescue_button=Button(rescue_ax,"Lock good + rescue rest")
        stitch_ax=fig.add_axes([.69,.035,.12,.06]);stitch_button=Button(stitch_ax,"Stitch")
        undo_ax=fig.add_axes([.84,.035,.12,.06]);undo_button=Button(undo_ax,"Undo stitch")
        def save_progress(_event=None):
            tracks.to_csv(out/"reviewed_detections_and_tracks.csv",index=False)
            (out/"track_stitch_edits.json").write_text(json.dumps(edits,indent=2),encoding="utf-8")
            summary.to_csv(out/"track_summary_after_stitching.csv",index=False)
            saved=summary.copy();saved["accepted"]=saved.track_id.map(accepted).fillna(False)
            saved["review_status"]=np.where(saved.accepted,"accepted","rejected")
            saved.to_csv(out/"reviewed_track_summary.csv",index=False)
            self.status.set(f"Track-review progress saved: {out}")
        def redraw():
            nonlocal lines
            for line in list(lines): line.remove()
            lines={}
            for tid,g in tracks.groupby("track_id"):
                color="#22d3ee" if int(tid) in selected else ("green" if accepted.get(int(tid),False) else "orange")
                line,=ax.plot(g.x,g.y,lw=2 if int(tid) in selected else 1,color=color,picker=5);lines[line]=int(tid)
            summary_text.set_text(population_track_summary(summary,accepted));fig.canvas.draw_idle()
        def pick(event):
            tid=lines[event.artist]
            if event.mouseevent.key == "shift":
                if tid in selected:selected.remove(tid)
                elif len(selected)<2:selected.append(tid)
                redraw();return
            accepted[tid]=not accepted.get(tid,False);redraw();save_progress()
        def stitch(_event):
            nonlocal tracks,summary
            if len(selected)!=2:
                messagebox.showinfo("Stitch tracks","Shift-click exactly two track fragments first.");return
            groups=[tracks[tracks.track_id==tid].sort_values("frame") for tid in selected]
            groups.sort(key=lambda g:g.frame.min());first,second=groups
            if int(first.frame.max())>=int(second.frame.min()):
                messagebox.showerror("Stitch tracks","These tracks overlap in time, so they cannot safely be the same animal.");return
            gap=int(second.frame.min()-first.frame.max());distance=float(np.hypot(second.x.iloc[0]-first.x.iloc[-1],second.y.iloc[0]-first.y.iloc[-1]))
            if not messagebox.askyesno("Confirm stitch",f"Join track {int(first.track_id.iloc[0])} to {int(second.track_id.iloc[0])}?\n\nGap: {gap} frames; endpoint distance: {distance:.1f} px"):
                return
            undo.append((tracks.copy(),summary.copy(),accepted.copy(),edits.copy()))
            keep=int(first.track_id.iloc[0]);drop=int(second.track_id.iloc[0]);tracks.loc[tracks.track_id==drop,"track_id"]=keep
            accepted[keep]=accepted.get(keep,False) or accepted.get(drop,False);accepted.pop(drop,None)
            tracks,summary=summarize_tracks(tracks,float(self.fps.get()),float(self.scale.get()),analyzed_frame_count)
            edits.append({"kept_track_id":keep,"merged_track_id":drop,"gap_frames":gap,"endpoint_distance_px":distance})
            selected.clear();redraw();save_progress()
        def undo_stitch(_event):
            nonlocal tracks,summary,accepted,edits
            if not undo:return
            tracks,summary,accepted,edits=undo.pop();selected.clear();redraw();save_progress()
        def request_rescue(_event):
            save_progress()
            approved=[tid for tid,value in accepted.items() if value]
            if not approved:
                messagebox.showinfo("Rescue unresolved tracks",
                                    "Approve at least one good track before locking it.")
                return
            rescue_requested["value"]=True
            plt.close(fig)
        save_button.on_clicked(save_progress);rescue_button.on_clicked(request_rescue)
        stitch_button.on_clicked(stitch);undo_button.on_clicked(undo_stitch)
        fig.canvas.mpl_connect("pick_event",pick);plt.show()
        save_progress()
        if rescue_requested["value"]:
            self.start_rescue_pass(out,tracks,accepted,metadata)
            return
        reviewed=summary.copy();reviewed["accepted"]=reviewed.track_id.map(accepted).fillna(False);reviewed["review_status"]=np.where(reviewed.accepted,"accepted","rejected")
        reviewed.to_csv(Path(out)/"reviewed_track_summary.csv",index=False)
        self.review_modalities(Path(out),set(reviewed.loc[reviewed.accepted,"track_id"].astype(int)),tracks)
        self.go.state(["!disabled"]); self.status.set(f"Complete: {len(summary)} candidate tracks, {int(reviewed.accepted.sum())} accepted. Results: {out}"); messagebox.showinfo("Complete",self.status.get())
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
        use_alternate=messagebox.askyesno(
            "Rescue unresolved tracks",
            f"Saved {len(locked_ids)} approved track(s) as locked.\n\n"
            "Rerun the unresolved remainder with the experimental initial-segment "
            "single-pass background?\n\n"
            "Choose No to keep the locked file and continue corrections manually. "
            "The robust two-pass result remains untouched.")
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
        threading.Thread(
            target=self._run_rescue_pass,
            args=(rescue_out,locked,metadata,out),
            daemon=True,
        ).start()

    def _run_rescue_pass(self,rescue_out,locked,metadata,parent_out):
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
                locked_tracks=locked,locked_exclusion_radius_px=40.0)
            (Path(new_out)/"rescue_provenance.json").write_text(json.dumps({
                "parent_results":str(parent_out),
                "method":"experimental_initial_segment_single_pass_background",
                "locked_track_ids":sorted(locked.track_id.astype(int).unique().tolist()),
            },indent=2),encoding="utf-8")
            self.after(0,self.review,summary,new_out)
        except Exception as exc:
            self.after(0,self.fail,str(exc))

    def resume_review(self):
        folder=filedialog.askdirectory(title="Choose a population swimming results folder")
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
            roi_path=out/"analysis_rois.json"
            if roi_path.exists():self.roi_records=json.loads(roi_path.read_text(encoding="utf-8")).get("rois",[])
            self.roi_label.config(text=f"{len(self.roi_records)} ROI(s)")
            summary_path=out/"track_summary_after_stitching.csv"
            summary=pd.read_csv(summary_path if summary_path.exists() else out/"track_summary.csv")
            self.review(summary,out)
        except Exception as exc:messagebox.showerror("Resume review",str(exc))

    def draw_optional_rois(self):
        try:
            files=list_frames(self.source.get());image=read_gray(files[0])
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

    def review_modalities(self,out,accepted_tracks,tracks):
        path=out/"modality_bouts_for_review.csv"
        bouts=pd.read_csv(path)
        if bouts.empty:
            return
        bouts=bouts[bouts.track_id.astype(int).isin(accepted_tracks)].copy()
        if bouts.empty:
            return
        dialog=tk.Toplevel(self);dialog.title("Review proposed locomotion bouts");dialog.geometry("1120x520");dialog.transient(self)
        ttk.Label(dialog,text="Select one or more bouts, then confirm the proposal, relabel it, or reject it. Low-confidence and uncertain bouts deserve priority.").pack(anchor="w",padx=10,pady=8)
        columns=("bout","track","start","end","proposal","confidence","frequency","speed","status","final")
        tree=ttk.Treeview(dialog,columns=columns,show="headings",selectmode="extended")
        labels=("Bout","Track","Start (s)","End (s)","Proposal","Confidence","Hz","um/s","Review","Final label")
        widths=(55,55,75,75,95,80,65,80,85,90)
        for col,label,width in zip(columns,labels,widths):
            tree.heading(col,text=label);tree.column(col,width=width,anchor="center")
        for index,row in bouts.iterrows():
            tree.insert("", "end", iid=str(index), values=(int(row.bout_id),int(row.track_id),f"{row.start_time_s:.2f}",f"{row.end_time_s:.2f}",
                row.proposed_modality,f"{row.confidence:.2f}",f"{row.bend_frequency_hz:.2f}",f"{row.median_speed_um_s:.1f}",
                row.review_status,row.reviewed_modality))
        tree.pack(fill="both",expand=True,padx=10)
        controls=ttk.Frame(dialog);controls.pack(fill="x",padx=10,pady=10)
        choice=tk.StringVar(value="swimming")
        ttk.Combobox(controls,textvariable=choice,values=("swimming","crawling","burrowing","uncertain"),state="readonly",width=14).pack(side="left",padx=4)
        def update(status,label=None):
            for iid in tree.selection():
                idx=int(iid);bouts.at[idx,"review_status"]=status
                bouts.at[idx,"reviewed_modality"]=label if label is not None else ""
                values=list(tree.item(iid,"values"));values[-2]=status;values[-1]=label or "";tree.item(iid,values=values)
        ttk.Button(controls,text="Confirm proposal",command=lambda:update("confirmed",None)).pack(side="left",padx=4)
        ttk.Button(controls,text="Relabel",command=lambda:update("relabeled",choice.get())).pack(side="left",padx=4)
        ttk.Button(controls,text="Reject / exclude",command=lambda:update("rejected",None)).pack(side="left",padx=4)
        def preview(_event=None):
            selected=tree.selection()
            if not selected:
                messagebox.showinfo("Preview","Select a bout first.");return
            row=bouts.loc[int(selected[0])]
            self.preview_bout(row,tracks)
        ttk.Button(controls,text="Visual preview",command=preview).pack(side="left",padx=12)
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
            dialog.destroy()
        ttk.Button(controls,text="Save review",command=save).pack(side="right",padx=4)
        dialog.protocol("WM_DELETE_WINDOW",save);dialog.grab_set();self.wait_window(dialog)

    def preview_bout(self,bout,tracks):
        files=list_frames(self.source.get())
        track=tracks[(tracks.track_id.astype(int)==int(bout.track_id)) &
                     (tracks.frame>=int(bout.start_frame)) & (tracks.frame<=int(bout.end_frame))].copy()
        if track.empty:
            messagebox.showerror("Preview","No tracked frames are available for this bout.");return
        frames=track.frame.astype(int).tolist();lookup=track.set_index(track.frame.astype(int))
        fig,ax=plt.subplots(figsize=(10,7));plt.subplots_adjust(bottom=.20)
        slider_ax=fig.add_axes([.16,.08,.58,.04]);slider=Slider(slider_ax,"Frame",0,len(frames)-1,valinit=0,valstep=1)
        play_ax=fig.add_axes([.78,.065,.10,.065]);play=Button(play_ax,"Play")
        state={"running":False};timer=fig.canvas.new_timer(interval=max(25,int(1000/float(self.fps.get()))))
        def draw(index):
            frame=frames[int(index)];row=lookup.loc[frame]
            if isinstance(row,pd.DataFrame):row=row.iloc[0]
            ax.clear();ax.imshow(read_gray(files[frame]),cmap="gray")
            ax.plot(track.x,track.y,color="#22d3ee",lw=1,alpha=.55)
            try:
                sx=json.loads(row.spine_x_json);sy=json.loads(row.spine_y_json)
                ax.plot(sx,sy,color="#facc15",lw=2.2);ax.plot(sx[0],sy[0],"o",color="#ff4fd8",ms=5)
            except (TypeError,ValueError,json.JSONDecodeError):
                pass
            ax.plot(row.x,row.y,"o",color="lime",ms=4)
            ax.set_title(f"Track {int(bout.track_id)} | proposed {bout.proposed_modality} | {row.time_s:.2f} s\n"
                         f"yellow=spine, magenta=oriented end, cyan=bout trajectory")
            ax.set_axis_off();fig.canvas.draw_idle()
        slider.on_changed(draw)
        def tick():
            if not state["running"]:return
            next_value=int(slider.val)+1
            if next_value>=len(frames):next_value=0
            slider.set_val(next_value);timer.start()
        timer.add_callback(tick)
        def toggle(_event):
            state["running"]=not state["running"];play.label.set_text("Pause" if state["running"] else "Play")
            if state["running"]:timer.start()
        play.on_clicked(toggle);draw(0);plt.show();files.close()
    def fail(self,e): self.go.state(["!disabled"]); self.status.set("Analysis stopped."); messagebox.showerror("Population swimming",e)
if __name__=="__main__": App().mainloop()
