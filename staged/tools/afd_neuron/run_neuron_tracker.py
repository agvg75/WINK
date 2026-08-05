"""
run_neuron_tracker.py
=====================
Runs the anterior sensory-neuron tracker. RUNS IN THE LAB TOOLS PYTHON
ENVIRONMENT, NOT FIJI. Launch with Track_Neuron.bat.

Flow: pick a movie -> fps + field angle -> click the soma, trace the worm
outline (Enter) -> it tracks -> a REVIEW WINDOW opens so you can step through,
jump to flagged frames, and correct any of them -> it saves the CSV + overlay.

Review window keys:
  left / right : previous / next frame
  n            : jump to the next frame flagged for review
  f            : fix this frame (click the soma, then click the outline, Enter)
  t            : re-track forward from this frame (after a fix)
  s or close   : save and finish
"""
import os, sys, csv, datetime, json, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "app"
MOVIE_TOOL = ROOT / "tools" / "movie"
sys.path.insert(0, str(MOVIE_TOOL))
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import numpy as np
except ModuleNotFoundError:
    # started by the wrong Python (no scientific libraries)
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk(); r.withdraw()
        messagebox.showerror("Wrong Python environment",
            "This tool needs the Lab tools Python environment.\n\n"
            "Start it with Track_Neuron.bat, or from the Lab Tools hub opened via "
            "Launch_Lab_Hub.bat. Do not double-click the .py file directly.\n\n"
            "If it still fails, run Setup_Lab_Tools.bat once on this computer, then "
            "Install_Extra_Libraries.bat.")
        r.destroy()
    except Exception:
        print("This tool needs the Lab tools Python environment (numpy is missing).")
    raise SystemExit

from tracker_review_session import load_tracker_session, save_tracker_session
from virtual_frame_stack import DiskBackedFrameStack


def _performance_options(parent):
    """Explicit, reversible accelerations; measurements always use source pixels."""
    import tkinter as tk
    from tkinter import ttk
    result={"registration_proxy":True,"local_segmentation":True,
            "adaptive_background_sampling":True}
    win=tk.Toplevel(parent);win.title("Optional performance settings");win.transient(parent);win.grab_set()
    ttk.Label(win,text="Time-saving options",font=("TkDefaultFont",11,"bold")).pack(anchor="w",padx=14,pady=(12,4))
    ttk.Label(win,text="These affect geometry processing only. Fluorescence is always measured from original pixels.\nRun again with options off to compare the saved timing reports.",wraplength=560).pack(anchor="w",padx=14,pady=(0,8))
    variables={}
    labels=[("registration_proxy","Low-resolution proxy for camera registration"),
            ("local_segmentation","Process a moving worm-local box after seeding"),
            ("adaptive_background_sampling","Adapt background sample count to image size")]
    for key,label in labels:
        variables[key]=tk.BooleanVar(value=result[key]);ttk.Checkbutton(win,text=label,variable=variables[key]).pack(anchor="w",padx=18,pady=3)
    accepted={"value":False}
    def finish():
        accepted["value"]=True
        for key,var in variables.items():result[key]=bool(var.get())
        win.destroy()
    ttk.Button(win,text="Continue",command=finish).pack(pady=12);win.protocol("WM_DELETE_WINDOW",win.destroy)
    parent.wait_window(win)
    return result if accepted["value"] else None


def _load_green(path, crop=None,source_indices=None,progress_callback=None):
    """Load all frames as a (T,H,W) green-channel array. If the user picked ONE
    image of a numbered sequence, read the whole folder it sits in, keeping only
    images matching THAT image's size."""
    import movie_reader
    m = movie_reader.open_movie(path)
    ref_shape = None
    if getattr(m, "source_kind", "") == "single_image":
        ref_shape = next(iter(m.frames())).shape[:2]
        m.close()
        m = movie_reader.open_numbered_image_sequence(path)
    full_shape = ref_shape or (int(m.height), int(m.width))
    if crop is None:
        crop=(0,0,full_shape[1],full_shape[0])
    x0,y0,x1,y1=[int(v) for v in crop]
    target_shape=(y1-y0,x1-x0)
    wanted=(list(range(int(m.n_frames))) if source_indices is None else sorted(set(int(i) for i in source_indices)))
    if len(wanted)*target_shape[0]*target_shape[1]*4>2_000_000_000:
        return DiskBackedFrameStack.from_movie(m,crop=crop,channel="green",source_indices=wanted,progress_callback=progress_callback)
    output = np.empty((len(wanted), *target_shape), dtype=np.float32);wanted_set=set(wanted)
    kept = 0

    def green(fr):
        if fr.ndim not in (2, 3) or (fr.ndim == 3 and fr.shape[2] not in (3, 4)):
            return None
        if ref_shape is not None and fr.shape[:2] != ref_shape:
            return None
        if fr.shape[:2] != full_shape:
            return None
        selected = fr[..., 1] if fr.ndim == 3 and fr.shape[2] >= 3 else (
            fr if fr.ndim == 2 else fr[..., 0])
        return np.asarray(selected[y0:y1,x0:x1], dtype=np.float32)

    if getattr(m, "source_kind", "") == "image_sequence":
        workers = min(6, max(2, (os.cpu_count() or 2) // 2))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            decoded = pool.map(
                lambda index: green(m.get_frame(index)),
                wanted)
            for j,fr in enumerate(decoded):
                if fr is not None:
                    output[kept] = fr
                    kept += 1
                if progress_callback:progress_callback(j+1,len(wanted),"Loading selected frames")
    else:
        for source_index,source in enumerate(m.frames()):
            if source_index not in wanted_set:continue
            fr = green(source)
            if fr is not None:
                output[kept] = fr
                kept += 1
            if progress_callback:progress_callback(kept,len(wanted),"Loading selected frames")
            if kept>=len(wanted):break
    m.close()
    if not kept:
        return np.empty((0, 1, 1), np.float32)
    return output[:kept]

class ProgressDialog:
    def __init__(self,parent):
        import tkinter as tk
        from tkinter import ttk
        self.cancelled=False;self.started=datetime.datetime.now();self.window=tk.Toplevel(parent);self.window.title("WINK neuronal analysis progress");self.window.geometry("560x190");self.window.protocol("WM_DELETE_WINDOW",self.cancel)
        self.phase=tk.StringVar(value="Preparing…");self.detail=tk.StringVar(value="The window remains open while WINK works.")
        ttk.Label(self.window,textvariable=self.phase,font=("TkDefaultFont",11,"bold")).pack(fill="x",padx=12,pady=(14,4));self.bar=ttk.Progressbar(self.window,maximum=100);self.bar.pack(fill="x",padx=12,pady=7);ttk.Label(self.window,textvariable=self.detail,wraplength=530).pack(fill="x",padx=12);ttk.Button(self.window,text="Cancel safely",command=self.cancel).pack(pady=10);self.window.update()
    def cancel(self):self.cancelled=True;self.phase.set("Canceling safely after the current frame…")
    def update(self,current,total,phase):
        if self.cancelled:raise InterruptedError("Analysis canceled by user")
        total=max(1,int(total));self.bar["value"]=100*int(current)/total;elapsed=(datetime.datetime.now()-self.started).total_seconds();self.phase.set(phase);self.detail.set(f"{int(current):,} of {total:,} ({100*int(current)/total:.1f}%) — elapsed {elapsed:.0f} s");self.window.update()
    def close(self):
        try:self.window.destroy()
        except Exception:pass


class Reviewer:
    """Step through frames, jump to flagged ones, correct any frame by hand."""
    def __init__(self, tr, G, plt, session_path, source):
        self.tr = tr; self.G = G; self.plt = plt; self.i = 0
        self.session_path=Path(session_path); self.source=source
        self.interval_start=None; self.active_interval=None; self.finalized=False
        from matplotlib.widgets import Slider,Button
        self.fig, self.ax = plt.subplots(figsize=(11, 7));self.fig.subplots_adjust(bottom=.17)
        slider_ax=self.fig.add_axes([.18,.065,.58,.035]);self.slider=Slider(slider_ax,"Analyzed frame",1,self.tr.T,valinit=1,valstep=1);self.slider.on_changed(self._slider_changed)
        jump_ax=self.fig.add_axes([.78,.05,.14,.06]);self.jump_button=Button(jump_ax,"Jump to frame…");self.jump_button.on_clicked(self.jump_to_frame)
        self.fig.canvas.mpl_connect("key_press_event", self.on_key)
        self.fig.canvas.mpl_connect("close_event", self._close_as_wip)
        self.draw()

    def _slider_changed(self,value):
        index=int(round(value))-1
        if index!=self.i:self.i=max(0,min(self.tr.T-1,index));self.draw(update_slider=False)

    def jump_to_frame(self,_event=None):
        from tkinter import simpledialog
        parent=getattr(self.fig.canvas.manager,"window",None);initial=int(self.tr.source_indices[self.i])+1
        value=simpledialog.askinteger("Jump to source frame","Source frame number:",initialvalue=initial,minvalue=1,maxvalue=int(self.tr.source_indices[-1])+1,parent=parent)
        if value is None:return
        self.i=int(np.argmin(np.abs(self.tr.source_indices-(value-1))));self.draw()

    def save_progress(self):
        save_tracker_session(self.session_path,self.tr,tool="neuron_tracker",source=self.source)

    def _close_as_wip(self,_event=None):
        if not self.finalized:self.save_progress()

    def draw(self,update_slider=True):
        self.ax.clear(); i = self.i; s = self.tr.state[i]
        self.ax.imshow(self.G[i], cmap="gray")
        if s["path"] is not None:
            self.ax.plot(s["path"][:, 0], s["path"][:, 1], "y-", lw=1)
        self.ax.plot(s["soma"][0], s["soma"][1], "c+", ms=14, mew=2)
        if s["nose"][0] == s["nose"][0]:
            self.ax.plot([s["soma"][0], s["nose"][0]], [s["soma"][1], s["nose"][1]], "r-", lw=1.5)
            self.ax.plot(s["nose"][0], s["nose"][1], "r.", ms=12)
        flag = "   *** NEEDS REVIEW ***" if s["needs_help"] else ""
        suggested = "   *** SUGGESTED ANCHOR ***" if s.get("suggested_manual_anchor") else ""
        reason = s.get("reconstruction_reason", "") if s["needs_help"] else ""
        nhelp = sum(1 for st in self.tr.state if st and st["needs_help"])
        source_frame=int(self.tr.source_indices[i])+1
        title = (f"source frame {source_frame}   analyzed frame {i+1}/{self.tr.T}   [{s['provenance']}]{flag}{suggested}    "
                 f"({nhelp} flagged)\n")
        if reason:
            title += reason+"\n"
        if self.interval_start is not None:
            title += f"Interval start: frame {self.interval_start+1}; move to end and press e.\n"
        elif self.active_interval is not None:
            lo, hi = self.active_interval
            title += (f"BOUNDED EDIT: frames {lo+1}-{hi+1}; f adds an anchor only "
                      "inside this interval; c closes bounded editing.\n")
        title += ("arrows: move   n: next flagged   a: suggested anchor   f: fix/add anchor\n"
                  "b/e: bounded interval   c: close interval   w: save progress   q/close: save & exit   s: finalize")
        self.ax.set_title(title)
        self.ax.axis("off")
        if update_slider and int(round(self.slider.val))!=self.i+1:self.slider.set_val(self.i+1)
        self.fig.canvas.draw_idle()

    def on_key(self, e):
        if e.key == "right": self.i = min(self.tr.T-1, self.i+1); self.draw()
        elif e.key == "left": self.i = max(0, self.i-1); self.draw()
        elif e.key == "n":
            flags = [j for j in range(self.tr.T) if self.tr.state[j]["needs_help"]]
            after = [j for j in flags if j > self.i]
            if after: self.i = after[0]
            elif flags: self.i = flags[0]
            self.draw()
        elif e.key == "f": self.fix()
        elif e.key == "a":
            anchor = self.tr.next_suggested_anchor(self.i)
            if anchor is not None: self.i = anchor
            self.draw()
        elif e.key == "t": self.tr.retrack_from(self.i); self.save_progress(); self.draw()
        elif e.key == "b":
            self.interval_start=self.i; self.active_interval=None; self.draw()
        elif e.key == "e":
            if self.interval_start is not None:
                lo,hi=sorted((self.interval_start,self.i))
                self.active_interval=(lo,hi)
                self.tr.reanalyze_interval(lo,hi)
                self.interval_start=None; self.save_progress(); self.draw()
        elif e.key == "c":
            self.interval_start=None; self.active_interval=None; self.draw()
        elif e.key == "w": self.save_progress(); self.draw()
        elif e.key == "q": self.save_progress(); self.plt.close(self.fig)
        elif e.key == "s": self.save_progress(); self.finalized=True; self.plt.close(self.fig)

    def fix(self):
        i = self.i
        self.ax.set_title(f"FIX frame {i+1}:  click the NEURON SOMA   (right-click = undo,  Enter = confirm)")
        self.fig.canvas.draw()
        spts = self.fig.ginput(0, timeout=0)
        if not spts: self.draw(); return
        sx, sy = spts[-1]
        self.ax.set_title(f"FIX frame {i+1}:  click the WORM OUTLINE   (right-click = undo,  Enter = finish)")
        self.fig.canvas.draw()
        verts = self.fig.ginput(0, timeout=0)
        bounded=(self.active_interval is not None
                 and self.active_interval[0] <= i <= self.active_interval[1])
        self.tr.recompute_frame(
            i, soma=(sx, sy),
            outline_verts=(verts if len(verts) >= 3 else None),
            reconstruct_bounds=(self.active_interval if bounded else None))
        if not bounded:
            # A hand correction has to reach the frames AFTER it. Without this
            # the fix applied to the frame on screen and every later frame kept
            # tracking from the state that was wrong, so the correction looked
            # like it had worked while the recording was unchanged past it.
            # Inside a bounded edit the interval is deliberately the whole
            # scope, so nothing outside it is touched - same rule as
            # run_dic_kinematics.
            self.tr.retrack_from(i)
        self.save_progress()
        self.draw()

    def run(self):
        self.plt.show()          # blocks until the window is closed


def _seed(G, plt,frame_index=0,title_prefix=""):
    """Seed on frame 1: draw an oval INSIDE the soma, then trace the worm outline.
    The oval gives the cell's measured size and brightness profile (a soma is a
    blob, not a pixel); the outline gives area, length, and the soma-to-nose arc."""
    from skimage.draw import polygon2mask
    fig, ax = plt.subplots(figsize=(11, 7)); ax.imshow(G[frame_index], cmap="gray")
    ax.set_title(title_prefix+"STEP 1: click several points INSIDE the SOMA (an oval within the cell)\n"
                 "right-click = undo last,   Enter = finish")
    fig.canvas.draw()
    spts = plt.ginput(0, timeout=0)
    if not spts:
        plt.close(fig); return None, None, None
    if len(spts) >= 3:
        soma_mask = polygon2mask(G.shape[1:], np.array([(y, x) for (x, y) in spts]))
        import scipy.ndimage as _ndi
        cy, cx = _ndi.center_of_mass(soma_mask)
        soma = (float(cx), float(cy))
        ax.plot([p[0] for p in spts]+[spts[0][0]], [p[1] for p in spts]+[spts[0][1]], "c-", lw=1.5)
    else:
        soma_mask = None; soma = spts[-1]          # single click: radius stays default
    ax.plot(soma[0], soma[1], "c+", ms=16, mew=3)
    ax.set_title(title_prefix+"STEP 2: click around the WORM OUTLINE.    right-click = undo last,   Enter = finish")
    fig.canvas.draw()
    verts = plt.ginput(0, timeout=0)
    plt.close(fig)
    return soma, verts, soma_mask


def _save(tr, path, crop=(0,0,0,0)):
    save_started=time.perf_counter()
    rows = tr.export_rows()
    x0,y0,_,_=crop
    for row in rows:
        for key in ("soma_x","body_centroid_x","nose_x"):
            if row.get(key)==row.get(key):row[key]+=x0
        for key in ("soma_y","body_centroid_y","nose_y"):
            if row.get(key)==row.get(key):row[key]+=y0
        row["analysis_crop_x0_px"]=x0;row["analysis_crop_y0_px"]=y0
    base = Path(path).stem; stamp = datetime.date.today().strftime("%Y%m%d")
    out_csv = Path(path).with_name(f"{base}_neurontrack_{stamp}.csv")
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader()
        for r in rows: w.writerow({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})
    import matplotlib.pyplot as plt
    idx = [0, tr.T//2, tr.T-1]
    fig, axs = plt.subplots(1, len(idx), figsize=(6*len(idx), 4))
    if len(idx) == 1: axs = [axs]
    for a, i in zip(axs, idx):
        s = tr.state[i]; a.imshow(tr.G[i], cmap="gray"); a.axis("off")
        a.set_title(f"frame {i+1} ({s['provenance']})")
        if s["path"] is not None: a.plot(s["path"][:, 0], s["path"][:, 1], "y-", lw=1)
        a.plot(s["soma"][0], s["soma"][1], "c+", ms=14, mew=2)
        if s["nose"][0] == s["nose"][0]:
            a.plot([s["soma"][0], s["nose"][0]], [s["soma"][1], s["nose"][1]], "r-", lw=1.5)
    out_png = Path(path).with_name(f"{base}_neurontrack_{stamp}_overlay.png")
    fig.tight_layout(); fig.savefig(out_png, dpi=110); plt.close(fig)
    return out_csv, out_png, time.perf_counter()-save_started


def main():
    import tkinter as tk
    from tkinter import filedialog, simpledialog, messagebox
    import matplotlib; matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    import neuron_tracker

    root = tk.Tk(); root.withdraw()
    path = filedialog.askopenfilename(title="Choose a movie or TIFF stack",
        filetypes=[("Movies and stacks", "*.avi *.mp4 *.mov *.mkv *.tif *.tiff"), ("All files", "*.*")])
    if not path: return
    fps = simpledialog.askfloat("Metadata", "Frames per second:", initialvalue=30.0, minvalue=0.1)
    if fps is None: return
    um_per_px = simpledialog.askfloat(
        "Required spatial calibration",
        "Micrometres per pixel (must be greater than zero):\n\n"
        "Use the calibration for this camera and magnification. Cancel and "
        "calibrate with a stage micrometer if unknown.",
        initialvalue=1.0, minvalue=0.000001)
    if um_per_px is None:
        return
    exposure_ms = simpledialog.askfloat(
        "Exposure", "Exposure time in milliseconds:",
        initialvalue=10.0, minvalue=0.000001)
    if exposure_ms is None:
        return
    field_angle = simpledialog.askfloat("Metadata", "Field angle (deg, 0 = up/north):", initialvalue=0.0) or 0.0
    performance_options=_performance_options(root)
    if performance_options is None:return
    run_started=time.perf_counter();timings={}
    try:
        import movie_reader
        from roi_editor import draw_roi
        from frame_range_selector import select_frame_ranges
        preview_movie=movie_reader.open_movie(path)
        first=preview_movie.get_frame(0);full_h,full_w=first.shape[:2]
        total_frames=int(preview_movie.n_frames);preview_movie.close()
        shown=first[...,1] if first.ndim==3 and first.shape[2]>=3 else first
        record=None
        while record is None:
            record=draw_roi(shown,
                "OPTIONAL working region: draw around the worm and all expected movement\n"
                "Accept ROI commits it; Use full frame skips cropping; Cancel returns here without reloading the movie.",
                allow_line=False,default_shape="Rectangle",allow_full_frame=True)
            if record is None:
                if not messagebox.askyesno("Working region not accepted",
                    "The ROI window was canceled. Reopen it?\n\nChoose No to continue with the full frame; the loaded movie will not be discarded."):
                    record={"shape":"full_frame","geometry":{"x0":0,"y0":0,"x1":full_w-1,"y1":full_h-1}}
        geometry=record["geometry"]
        margin=24
        x0=max(0,int(np.floor(min(geometry["x0"],geometry["x1"])-margin)))
        y0=max(0,int(np.floor(min(geometry["y0"],geometry["y1"])-margin)))
        x1=min(full_w,int(np.ceil(max(geometry["x0"],geometry["x1"])+margin)))
        y1=min(full_h,int(np.ceil(max(geometry["y0"],geometry["y1"])+margin)))
        crop=(x0,y0,x1,y1)
        range_movie=movie_reader.open_movie(path)
        ranges=select_frame_ranges(root,range_movie,"Neuronal tracker: choose one or more analysis ranges")
        range_movie.close()
        if ranges is None:return
        selected_indices=[i for a,b in ranges for i in range(a,b+1)]
        estimated=int(len(selected_indices)*(y1-y0)*(x1-x0)*4)
        if estimated>2_000_000_000:
            messagebox.showinfo("Using virtual stack",
                f"Your selection is valid. A normal in-memory float array would use {estimated/2**30:.1f} GiB.\n\n"
                f"WINK will therefore use a temporary disk-backed stack (about {estimated/4/2**30:.1f} GiB for this 8-bit movie). "
                "This may take a few minutes, but RAM use will remain bounded. The temporary file is removed when the tracker closes.")
        if messagebox.askyesno("Worm detection preview",
                "Open the threshold and segmentation workbench before tracking?\n\nThis is recommended when artifacts confuse the worm detector. It changes body geometry only; neuronal fluorescence values remain measured from the original pixels."):
            import subprocess
            launcher=ROOT/"tools"/"segmentation_review_tool.py"
            subprocess.run([sys.executable,str(launcher),str(path),"--tool","neuron_tracker_geometry"],check=False)
        from segmentation_review import find_accepted_config
        segmentation_config=find_accepted_config(path,"neuron_tracker_geometry")
        progress=ProgressDialog(root)
        phase=time.perf_counter();G = _load_green(path,crop=crop,source_indices=selected_indices,progress_callback=progress.update)
        timings["movie_decode_and_selected_frame_load_s"]=time.perf_counter()-phase
    except Exception as e:
        if 'progress' in locals():progress.close()
        messagebox.showerror("Load failed", str(e)); return
    if G.shape[0] < 3:
        messagebox.showerror("Too few frames", "Need a multi-frame movie/stack."); return

    actual_source_indices=list(getattr(G,"source_indices",selected_indices[:len(G)]))
    try:
        tr = neuron_tracker.NeuronTracker(
            G, fps=fps, field_angle=field_angle, um_per_px=um_per_px,
            exposure_ms=exposure_ms,segmentation_config=segmentation_config,
            source_indices=actual_source_indices,progress_callback=progress.update,
            **performance_options)
        timings.update(tr.timings)
    except Exception as exc:
        progress.close()
        try:G.close()
        except Exception:pass
        messagebox.showerror("Tracker preparation failed",str(exc));return
    selected=Path(path).resolve(); recording_key=selected.stem
    source={"recording_key":recording_key,"first_frame":selected.name,
            "last_frame":selected.name,"frame_count":len(G),"analysis_crop_xyxy":list(crop),
            "source_frame_ranges":[[a+1,b+1] for a,b in ranges],"source_frame_indices_1based":[i+1 for i in actual_source_indices]}
    session_path=selected.parent/"NIKE_Review_Sessions"/f"{recording_key}_neuron_review.json"
    resumed=False
    if session_path.exists() and messagebox.askyesno(
            "Resume review?","Resume the saved neuron/body review session for this recording?"):
        try:
            load_tracker_session(session_path,tr,tool="neuron_tracker",source=source);resumed=True
        except Exception as exc:
            messagebox.showerror("Resume failed",str(exc));return
    if not resumed:
        local_starts=[];cursor=0
        for a,b in ranges:local_starts.append((cursor,a,b));cursor+=b-a+1
        seeds={}
        for number,(local_start,a,b) in enumerate(local_starts,1):
            soma,verts,soma_mask=_seed(G,plt,local_start,f"RANGE {number}/{len(local_starts)} — source frames {a+1}-{b+1}\n")
            if soma is None or verts is None or len(verts)<3:
                progress.close();messagebox.showerror("Seeding",f"Range {number} needs a soma and at least 3 outline points.");return
            from skimage.draw import polygon2mask
            mask=polygon2mask(G.shape[1:],np.array([(y,x) for (x,y) in verts]));seeds[local_start]=(soma,mask,soma_mask)
        soma,outline_mask,soma_mask=seeds.pop(0)
        try:tr.track_all(soma,outline_mask,soma_mask=soma_mask,range_seeds=seeds);timings.update(tr.timings)
        except Exception as exc:
            progress.close();save_tracker_session(session_path,tr,tool="neuron_tracker",source=source)
            messagebox.showerror("Tracking stopped",f"Progress was saved.\n\n{exc}");return
        save_tracker_session(session_path,tr,tool="neuron_tracker",source=source)
    progress.close()

    prof = tr.soma_profile
    pmsg = (f"Soma measured from your oval: radius {prof['radius_px']:.1f}px, "
            f"peak {prof['peak']:.0f}, mean {prof['mean']:.0f}, min {prof['minimum']:.0f}\n\n"
            if prof else "Soma radius: default (draw an oval next time to measure it)\n\n")
    messagebox.showinfo("Review",
        pmsg +
        "A review window will open.\n\n"
        "Step with the arrow keys, press n to jump to flagged frames, f to fix one\n"
        "(oval inside the soma, then the outline, Enter), t to re-track forward, and\n"
        "use b/e to set trusted interval boundaries, f to add intervening anchors,\n"
        "c to close bounded editing, w to save progress, q/close to save and exit,\n"
        "or s to finalize. Saved sessions can be resumed later.")
    reviewer=Reviewer(tr,G,plt,session_path,source);reviewer.run()
    if not reviewer.finalized:
        messagebox.showinfo("Progress saved",f"Review progress saved:\n{session_path}")
        if getattr(G,"is_virtual_stack",False):G.close()
        return

    out_csv, out_png, export_seconds = _save(tr, path,crop=crop)
    timings["measurement_and_export_s"]=export_seconds
    timings["processing_total_excluding_manual_review_s"]=sum(v for k,v in timings.items() if k not in ("tracker_initialization_s",))
    timings["wall_clock_total_including_manual_review_s"]=time.perf_counter()-run_started
    timing_path=out_csv.with_name(out_csv.stem+"_timing.json")
    timing_path.write_text(json.dumps({"tool":"afd_neuron_tracker","source":str(Path(path).resolve()),
        "source_frames_analyzed":len(actual_source_indices),"crop_xyxy":list(crop),
        "performance_options":performance_options,"timings_seconds":{k:round(float(v),4) for k,v in timings.items()}},indent=2),encoding="utf-8")
    if getattr(G,"is_virtual_stack",False):G.close()
    nhelp = sum(1 for s in tr.state if s and s["needs_help"])
    ref = tr.reference
    messagebox.showinfo("Saved",
        f"Frames: {tr.T}\nReference length: {ref['length_px']:.0f}px, "
        f"soma-to-nose: {ref['soma_nose_arc_px']:.0f}px\n"
        f"Frames still flagged: {nhelp}\nProcessing time: {timings['processing_total_excluding_manual_review_s']:.1f} s\n\nSaved:\n{out_csv.name}\n{out_png.name}\n{timing_path.name}")
    try: os.startfile(str(out_csv.parent))
    except Exception: pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        Path(__file__).with_suffix(".log").write_text(traceback.format_exc(), encoding="utf-8")
        try:
            import tkinter as tk; from tkinter import messagebox
            r = tk.Tk(); r.withdraw(); messagebox.showerror("Neuron tracker error", traceback.format_exc()[-1500:]); r.destroy()
        except Exception: pass
