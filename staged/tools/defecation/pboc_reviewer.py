"""Interactive movie, signal, tracking, and event review for pBoc analysis."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import cv2
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageTk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from pboc_review import ReviewState

# Result tables are read through read_table. Under pandas 3 a numeric column
# holding one stray non-numeric cell reads as StringDtype, and numpy then
# refuses np.isfinite on it - aborting an analysis with an error that names
# numpy internals rather than the column at fault. The import is guarded
# because these modules are launched several different ways and sys.path is
# not identical in all of them; a hard import would turn a latent dtype
# problem into a tool that will not start.
try:
    from table_io import read_table as _read_table
except Exception:                                    # pragma: no cover
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "app"))
        from table_io import read_table as _read_table
    except Exception:
        _read_table = None


def read_table(path, **kwargs):
    """pandas.read_csv with the pandas-3 dtype trap handled where available."""
    import pandas as _pd
    if _read_table is not None:
        return _read_table(path, **kwargs)
    return _pd.read_csv(path, **kwargs)



COLORS = {
    "pending": "#d98c00", "accepted": "#16833a", "rejected": "#b11f2e",
    "manual": "#7349a8",
}


class PBOCReviewer(tk.Toplevel):
    def __init__(self, parent, summary, folder, output, paths):
        super().__init__(parent)
        self.title("WINK pBoc visual review")
        self.geometry("1280x850")
        self.minsize(1050, 700)
        self.summary = summary
        self.folder, self.output = Path(folder), Path(output)
        self.paths = list(paths)
        scan_path = self.output / f"{summary['recording']}_full_scan.csv"
        scan = read_table(scan_path)
        review_path = self.output / f"{summary['recording']}_pboc_review.json"
        self.state = ReviewState(summary, scan, folder, self.paths, review_path)
        self.frame = 0
        self.event_index = 0
        self.playing = False
        self.photo = None
        self._setting_slider = False
        self.overlays = self._load_overlays()
        self.show_mask = tk.BooleanVar(value=True)
        self.show_center = tk.BooleanVar(value=True)
        self.show_ends = tk.BooleanVar(value=True)
        self.show_regions = tk.BooleanVar(value=True)
        self.show_distractors = tk.BooleanVar(value=True)
        self.show_status = tk.BooleanVar(value=True)
        self.speed = tk.DoubleVar(value=1.0)
        self.note = tk.StringVar()
        self._build()
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._select_event(0)

    def _load_overlays(self):
        path = self.output / f"{self.summary['recording']}_tracking_overlays.json.gz"
        if not path.is_file(): return []
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle).get("frames", [])

    def _build(self):
        toolbar = ttk.Frame(self); toolbar.pack(fill="x", padx=8, pady=6)
        for text, command in [
            ("|< Event", lambda: self._event_step(-1)), ("< Frame", lambda: self._step(-1)),
            ("Play/Pause", self._toggle_play), ("Frame >", lambda: self._step(1)),
            ("Event >|", lambda: self._event_step(1))]:
            ttk.Button(toolbar, text=text, command=command).pack(side="left", padx=2)
        ttk.Label(toolbar, text="Speed").pack(side="left", padx=(10, 2))
        ttk.Combobox(toolbar, textvariable=self.speed, state="readonly", width=5,
                     values=(.25, .5, 1, 2, 4)).pack(side="left")
        for label, variable in [("Mask", self.show_mask), ("Centerline", self.show_center),
                                ("Head/tail", self.show_ends), ("A/P regions", self.show_regions),
                                ("Distractors", self.show_distractors),
                                ("QC", self.show_status)]:
            ttk.Checkbutton(toolbar, text=label, variable=variable,
                            command=self._draw_frame).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Shortcuts", command=self._help).pack(side="right")

        body = ttk.Panedwindow(self, orient="horizontal"); body.pack(fill="both", expand=True, padx=8)
        view = ttk.Frame(body); detail = ttk.Frame(body, width=360)
        body.add(view, weight=4); body.add(detail, weight=2)
        self.image_label = ttk.Label(view, anchor="center"); self.image_label.pack(fill="both", expand=True)
        self.frame_label = ttk.Label(view); self.frame_label.pack(fill="x")
        self.slider = tk.Scale(view, from_=0, to=max(0, len(self.paths)-1), orient="horizontal",
                               showvalue=False, command=self._slider, resolution=1)
        self.slider.pack(fill="x")

        self.qc_label = ttk.Label(detail, wraplength=340, justify="left")
        self.qc_label.pack(fill="x", pady=(4, 8))
        self.event_box = tk.Listbox(detail, height=11, font=("Consolas", 9))
        self.event_box.pack(fill="x"); self.event_box.bind("<<ListboxSelect>>", self._list_select)
        self.details = ttk.Label(detail, wraplength=340, justify="left")
        self.details.pack(fill="x", pady=7)
        ttk.Label(detail, text="Review note").pack(anchor="w")
        ttk.Entry(detail, textvariable=self.note).pack(fill="x", pady=(0, 6))
        decisions = ttk.Frame(detail); decisions.pack(fill="x")
        for text, decision in [("Accept", "accepted"), ("Reject", "rejected"), ("Pending", "pending")]:
            ttk.Button(decisions, text=text, command=lambda d=decision:self._decision(d)).pack(side="left", padx=2)
        edits = ttk.Frame(detail); edits.pack(fill="x", pady=5)
        for text, command in [("Add event", self._add), ("Set peak", self._set_peak),
                              ("Set recovery", self._set_recovery), ("Clear recovery", self._clear_recovery),
                              ("Delete manual", self._delete_manual)]:
            ttk.Button(edits, text=text, command=command).pack(fill="x", pady=1)
        actions = ttk.Frame(detail); actions.pack(fill="x", pady=8)
        ttk.Button(actions, text="Save review", command=self._save).pack(side="left")
        ttk.Button(actions, text="Finalize review", command=self._finalize).pack(side="right")
        ttk.Button(
            detail, text="Tracking wrong: reseed full worm and rerun",
            command=self._reseed).pack(fill="x", pady=(0, 6))

        plot_frame = ttk.Frame(self); plot_frame.pack(fill="both", padx=8, pady=5)
        self.figure = Figure(figsize=(11, 2.2), dpi=100)
        self.axis = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.mpl_connect("button_press_event", self._plot_click)
        self._refresh_plot()

    def _bind_keys(self):
        self.bind("<space>", lambda _: self._toggle_play())
        self.bind("<Left>", lambda e: self._step(-10 if e.state & 1 else -1))
        self.bind("<Right>", lambda e: self._step(10 if e.state & 1 else 1))
        self.bind("<Prior>", lambda _: self._event_step(-1)); self.bind("<Next>", lambda _: self._event_step(1))
        self.bind("a", lambda _: self._decision("accepted")); self.bind("r", lambda _: self._decision("rejected"))
        self.bind("p", lambda _: self._decision("pending")); self.bind("n", lambda _: self._add())
        self.bind("k", lambda _: self._set_peak()); self.bind("v", lambda _: self._set_recovery())
        self.bind("<Control-s>", lambda _: self._save())

    def _current_event(self):
        return self.state.events[self.event_index] if self.state.events else None

    def _select_event(self, index):
        if not self.state.events: self._show_frame(0); return
        self.event_index = max(0, min(len(self.state.events)-1, index))
        event = self._current_event(); self.note.set(event.get("review_note", ""))
        self.frame = int(event["reviewed_peak_frame"])
        self._refresh_events(); self._show_frame(self.frame)

    def _event_step(self, delta): self._select_event(self.event_index + delta)
    def _step(self, delta): self._show_frame(self.frame + delta)
    def _slider(self, value):
        if not self._setting_slider:
            self._show_frame(int(float(value)), set_slider=False)
    def _plot_click(self, event):
        if event.xdata is not None: self._show_frame(round(event.xdata * self.state.fps))

    def _show_frame(self, frame, set_slider=True):
        self.frame = max(0, min(len(self.paths)-1, int(frame)))
        if set_slider:
            self._setting_slider = True
            try: self.slider.set(self.frame)
            finally: self._setting_slider = False
        self._draw_frame(); self._refresh_details(); self._refresh_plot_cursor()

    def _draw_frame(self):
        if not self.paths: return
        array = cv2.imread(str(self.paths[self.frame]), cv2.IMREAD_GRAYSCALE)
        lo, hi = np.percentile(array, (.5, 99.5)); gray=np.uint8(np.clip((array-lo)*255/max(hi-lo,1),0,255))
        image = Image.fromarray(gray).convert("RGB"); draw = ImageDraw.Draw(image)
        overlay = self.overlays[self.frame] if self.frame < len(self.overlays) else {}
        if self.show_mask.get() and overlay.get("outline"):
            draw.line([tuple(p) for p in overlay["outline"]]+[tuple(overlay["outline"][0])], fill=(255,180,0), width=2)
        points = overlay.get("centerline") or []
        if self.show_center.get() and points: draw.line([tuple(p) for p in points], fill=(0,255,255), width=2)
        if self.show_ends.get() and points:
            r=5; draw.ellipse((points[0][0]-r,points[0][1]-r,points[0][0]+r,points[0][1]+r),fill=(0,255,0)); draw.ellipse((points[-1][0]-r,points[-1][1]-r,points[-1][0]+r,points[-1][1]+r),fill=(255,0,0))
        if self.show_regions.get() and len(points)>=25:
            draw.line([tuple(p) for p in points[:6]], fill=(80,160,255), width=5); draw.line([tuple(p) for p in points[19:25]], fill=(255,80,200), width=5)
        if self.show_distractors.get():
            for distractor in overlay.get("distractors", []):
                doutline = distractor.get("outline") or []
                dcenter = distractor.get("centerline") or []
                color = (190, 50, 255) if distractor.get("usable") else (255, 40, 120)
                if doutline:
                    draw.line([tuple(p) for p in doutline] + [tuple(doutline[0])],
                              fill=color, width=3)
                if dcenter:
                    draw.line([tuple(p) for p in dcenter], fill=color, width=2)
                    draw.text(tuple(dcenter[0]), str(distractor.get("episode_id", "D")),
                              fill=color, stroke_width=2, stroke_fill=(0, 0, 0))
        usable = bool(self.state.scan.iloc[self.frame]["usable"])
        if self.show_status.get() and not usable: draw.rectangle((0,0,image.width-1,image.height-1),outline=(255,0,0),width=8)
        event=self._current_event()
        if event and self.frame==event.get("reviewed_peak_frame"): draw.text((10,10),"PEAK",fill=(255,255,0),stroke_width=2,stroke_fill=(0,0,0))
        if event and self.frame==event.get("reviewed_recovery_frame"): draw.text((10,35),"RECOVERY",fill=(0,255,255),stroke_width=2,stroke_fill=(0,0,0))
        image.thumbnail((850,510),Image.Resampling.LANCZOS); self.photo=ImageTk.PhotoImage(image); self.image_label.configure(image=self.photo)
        warning = overlay.get("identity_warning")
        reason = f" — {warning.replace('_', ' ')}" if warning else ""
        self.frame_label.configure(text=f"Frame {self.frame}/{len(self.paths)-1}     {self.frame/self.state.fps:.3f} s     {'USABLE' if usable else 'UNUSABLE TRACKING'}{reason}")

    def _refresh_events(self):
        self.event_box.delete(0,"end")
        for event in self.state.events:
            source="M" if event.get("provenance")=="manual" else "A"
            self.event_box.insert("end",f"{source} {event['reviewed_peak_frame']:5d} {event['decision'][:8]:8s} {event['event_id']}")
        if self.state.events:
            self.event_box.selection_clear(0,"end"); self.event_box.selection_set(self.event_index); self.event_box.see(self.event_index)

    def _list_select(self,_=None):
        selected=self.event_box.curselection()
        if selected:self._select_event(selected[0])

    def _refresh_details(self):
        event=self._current_event(); qc=self.state.usable_summary()
        distractors = self.summary.get("distractor_tracking", [])
        distractor_text = ""
        if distractors:
            distractor_text = "\nMoving distractors: " + ", ".join(
                f"{item['episode_id']} {100*item['usable_fraction']:.1f}% tracked"
                for item in distractors)
        self.qc_label.configure(text=(f"Usable {qc['usable_frames']}/{qc['total_frames']} ({qc['usable_percentage']:.1f}%)\nRuns: {qc['continuous_usable_runs']}   longest: {qc['longest_usable_run_frames']} frames{distractor_text}"))
        if not event:return
        warning=self.state.tracking_warning(event)
        self.details.configure(text=(f"Event: {event['event_id']} ({event['provenance']})\nAuto peak: {event.get('auto_peak_frame')} / {event.get('auto_peak_time_s')} s\nReviewed peak: {event.get('reviewed_peak_frame')} / {event.get('reviewed_peak_time_s'):.3f} s\nAuto recovery: {event.get('auto_recovery_frame')} / {event.get('auto_recovery_time_s')} s\nReviewed recovery: {event.get('reviewed_recovery_frame')} / {event.get('reviewed_recovery_time_s')} s\nPeak z: {event.get('peak_z')}   Decision: {event['decision']}\n{warning}"))

    def _refresh_plot(self):
        ax=self.axis; ax.clear(); t=self.state.scan.time_s.to_numpy(); z=self.state.scan.score_z.to_numpy(float); usable=self.state.scan.usable.astype(bool).to_numpy()
        ax.plot(t,z,color="#333",lw=.8); ax.axhline(self.summary["settings"]["contraction_z"],color="#999",ls="--",lw=.8)
        start=None
        for i,value in enumerate(np.r_[~usable,False]):
            if value and start is None:start=i
            if not value and start is not None:ax.axvspan(t[start],t[min(i-1,len(t)-1)],color="red",alpha=.13);start=None
        for event in self.state.events:
            color=COLORS["manual"] if event.get("provenance")=="manual" else COLORS[event["decision"]]
            ax.axvline(event["reviewed_peak_time_s"],color=color,lw=1.4,alpha=.9)
            if event.get("reviewed_recovery_time_s") is not None:ax.plot(event["reviewed_recovery_time_s"],self.state.value_at(event["reviewed_recovery_frame"],"score_z"),"v",color=color)
        ax.set_ylabel("score_z"); ax.set_xlabel("time (s)"); self.cursor=ax.axvline(self.frame/self.state.fps,color="blue",lw=1); self.figure.tight_layout(); self.canvas.draw_idle()

    def _refresh_plot_cursor(self):
        if hasattr(self,"cursor"):self.cursor.set_xdata([self.frame/self.state.fps]*2);self.canvas.draw_idle()

    def _decision(self,value):
        event=self._current_event()
        if event:self.state.update(event,decision=value,note=self.note.get());self._refresh_events();self._refresh_plot();self._refresh_details()
    def _add(self):
        event=self.state.add(self.frame);self.event_index=self.state.events.index(event);self._select_event(self.event_index);self._refresh_plot()
    def _set_peak(self):
        event=self._current_event()
        if event:self.state.update(event,peak=self.frame,note=self.note.get());self.event_index=self.state.events.index(event);self._refresh_events();self._refresh_plot();self._refresh_details()
    def _set_recovery(self):
        event=self._current_event()
        if event:self.state.update(event,recovery=self.frame,note=self.note.get());self._refresh_plot();self._refresh_details()
    def _clear_recovery(self):
        event=self._current_event()
        if event:self.state.update(event,recovery=None,note=self.note.get());self._refresh_plot();self._refresh_details()
    def _delete_manual(self):
        event=self._current_event()
        if not event:return
        try:self.state.delete_manual(event);self.event_index=max(0,self.event_index-1);self._select_event(self.event_index);self._refresh_plot()
        except ValueError as exc:messagebox.showerror("Cannot delete",str(exc),parent=self)
    def _save(self):self.state.save();messagebox.showinfo("Review saved",f"Atomic JSON review saved:\n{self.state.review_path}",parent=self)
    def _finalize(self):
        pending=sum(e["decision"]=="pending" for e in self.state.events)
        if pending and not messagebox.askyesno("Pending candidates",f"{pending} candidates remain pending. Finalization will refuse rhythm statistics. Continue?",parent=self):return
        result=self.state.finalize(); table=pd.DataFrame(self.state.events); table[table.decision=="accepted"].sort_values("reviewed_peak_frame").to_csv(self.output/f"{self.summary['recording']}_final_reviewed_events.csv",index=False)
        (self.output/f"{self.summary['recording']}_rhythm_statistics.json").write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
        messagebox.showinfo("Review finalized",("Statistics saved." if result["eligible"] else "Statistics unavailable:\n- "+"\n- ".join(result["ineligibility_reasons"])),parent=self)
    def _toggle_play(self):self.playing=not self.playing;self._play_tick()
    def _play_tick(self):
        if not self.playing:return
        if self.frame>=len(self.paths)-1:self.playing=False;return
        self._step(1);self.after(max(15,int(1000/self.state.fps/max(self.speed.get(),.01))),self._play_tick)
    def _help(self):messagebox.showinfo("Keyboard shortcuts","Space play/pause\nLeft/Right one frame; Shift ten\nPage Up/Down events\nA accept, R reject, P pending\nN add, K set peak, V set recovery\nCtrl+S save",parent=self)
    def _reseed(self):
        if not messagebox.askyesno(
                "Reanalyze tracking",
                "The current events depend on the current tracking. Close this "
                "review, mark head, tail, and the complete worm again, then rerun "
                "the full analysis? Existing review JSON is retained.", parent=self):
            return
        parent = self.master
        self.state.save(); self.destroy()
        parent._seed()
        if parent.outline and messagebox.askyesno(
                "Run corrected tracking", "Run the complete pBoc analysis now?",
                parent=parent):
            parent._start()
    def _close(self):self.state.save();self.destroy()
