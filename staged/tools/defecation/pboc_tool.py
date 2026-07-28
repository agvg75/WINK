"""Student-facing pBoc cycle analysis launcher."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np
from PIL import Image, ImageTk


HERE = Path(__file__).resolve().parent
ENGINE = HERE / "pboc_engine.py"
sys.path.insert(0, str(HERE.parent / "movie"))
sys.path.insert(0, str(HERE.parents[1] / "app"))
from image_sequence import discover_images, read_image, sequence_provenance
from movie_reader import open_movie
from pboc_reviewer import PBOCReviewer
from distractor_preflight import DistractorPreflight
from process_ui import ProcessLog, collect_image_points, CockpitApp


class PBOCCalibrationNavigator(tk.Toplevel):
    """Scrollable three-anchor calibration without requiring frame numbers."""
    LABELS = [
        ("baseline", "last full-length frame BEFORE pBoc starts"),
        ("peak", "frame of MAXIMUM pBoc contraction"),
        ("recovered", "first frame AFTER full length is restored"),
    ]

    def __init__(self, parent, paths, trace_callback):
        super().__init__(parent)
        self.title("Navigate and calibrate one pBoc")
        self.geometry("1120x820")
        self.paths=list(paths);self.trace_callback=trace_callback
        self.frame=0;self.photo=None;self.anchors=[];self.accepted=False
        self.bind("<Left>",lambda e:self._show(self.frame-(10 if e.state&1 else 1)))
        self.bind("<Right>",lambda e:self._show(self.frame+(10 if e.state&1 else 1)))
        ttk.Label(self,text="Scroll to each biological landmark, then trace it in place.",
                  font=("Segoe UI",15,"bold")).pack(anchor="w",padx=10,pady=(8,2))
        self.prompt=ttk.Label(self,wraplength=1080,justify="left")
        self.prompt.pack(anchor="w",padx=10,pady=(0,6))
        self.image=ttk.Label(self,anchor="center");self.image.pack(fill="both",expand=True,padx=10)
        self.slider=ttk.Scale(self,from_=0,to=max(0,len(self.paths)-1),command=self._slide)
        self.slider.pack(fill="x",padx=10,pady=6)
        bar=ttk.Frame(self);bar.pack(fill="x",padx=10,pady=(0,10))
        ttk.Button(bar,text="< Frame",command=lambda:self._show(self.frame-1)).pack(side="left")
        ttk.Button(bar,text="Frame >",command=lambda:self._show(self.frame+1)).pack(side="left",padx=5)
        ttk.Button(bar,text="Trace current landmark",command=self._trace).pack(side="left",padx=16)
        ttk.Button(bar,text="Cancel",command=self.destroy).pack(side="right")
        self.info=ttk.Label(bar);self.info.pack(side="right",padx=12)
        self._show(0)

    def _slide(self,value):
        self._show(int(round(float(value))),set_slider=False)

    def _show(self,frame,set_slider=True):
        self.frame=max(0,min(len(self.paths)-1,int(frame)))
        if set_slider:self.slider.set(self.frame)
        array=read_image(self.paths[self.frame],grayscale=True).astype(float)
        lo,hi=np.percentile(array,[0.5,99.5]);shown=np.clip((array-lo)*255/max(hi-lo,1),0,255).astype(np.uint8)
        image=Image.fromarray(shown);image.thumbnail((1060,650),Image.Resampling.LANCZOS)
        self.photo=ImageTk.PhotoImage(image);self.image.configure(image=self.photo)
        key,description=self.LABELS[len(self.anchors)]
        self.prompt.configure(text=f"Next: {description}. Use arrows or the slider, then choose Trace current landmark.")
        self.info.configure(text=f"Frame {self.frame+1}/{len(self.paths)} | anchors {len(self.anchors)}/3")

    def _trace(self):
        key,description=self.LABELS[len(self.anchors)]
        if self.anchors and self.frame<=self.anchors[-1]["frame"]:
            messagebox.showerror("Anchor order","Choose a later frame than the preceding anchor.",parent=self);return
        image=read_image(self.paths[self.frame],grayscale=True).astype(float)
        anchor=self.trace_callback(image,self.frame,description)
        if anchor is None:return
        anchor["state"]=key;self.anchors.append(anchor)
        if len(self.anchors)==3:
            self.accepted=True;self.destroy();return
        self._show(min(len(self.paths)-1,self.frame+1))


class App(CockpitApp):
    def __init__(self):
        super().__init__("Defecation Cycle Analysis", geometry="1200x760",
                         process_title="pBoc defecation")
        self.folder = tk.StringVar()
        self.output = tk.StringVar()
        self.fps = tk.StringVar(value="7.5")
        self.scale = tk.StringVar(value="2.35")
        self.exposure = tk.StringVar(value="5.0")
        self.minimum = tk.StringVar(value="30")
        self.maximum = tk.StringVar(value="90")
        self.contraction = tk.StringVar(value="2.5")
        self.head = None
        self.tail = None
        self.outline = None
        self.pboc_anchors = None
        self.source_path = None
        self.source_cache_meta = None
        self.distractors_reviewed = False
        self.distractor_path = None
        self._frames = None
        self._frame = 0
        self._cal_on = False
        self._cal_stage = None
        self._cal_anchors = []
        self._cal_head = None
        self._cal_tail = None
        self._cal_outline = []
        self._cal_cid = None
        self._build()

    def _build(self):
        c = self.controls

        def entry_row(label, var):
            row = ttk.Frame(c); row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=22).pack(side="left")
            e = ttk.Entry(row, textvariable=var); e.pack(side="right", fill="x", expand=True)
            return e

        srow = ttk.Frame(c); srow.pack(fill="x", pady=2)
        ttk.Label(srow, text="Source", width=22).pack(side="left")
        ttk.Entry(srow, textvariable=self.folder).pack(side="right", fill="x", expand=True)
        sb = ttk.Frame(c); sb.pack(fill="x", pady=(0, 4))
        ttk.Button(sb, text="File / stack / movie...", command=self._choose_source_file).pack(side="left", padx=2)
        ttk.Button(sb, text="Folder...", command=self._choose_folder).pack(side="left", padx=2)

        orow = ttk.Frame(c); orow.pack(fill="x", pady=2)
        ttk.Label(orow, text="Output folder", width=22).pack(side="left")
        ttk.Entry(orow, textvariable=self.output).pack(side="right", fill="x", expand=True)
        ttk.Button(c, text="Choose output...", command=self._choose_output).pack(fill="x", pady=(0, 4))

        entry_row("FPS", self.fps)
        entry_row("Micrometers per pixel", self.scale)
        self.add_scale_button(self._current_frame, self._apply_scale,
                              initial=self._scale_value,
                              text="Calibrate scale (scope / bar)...").pack(fill="x", pady=(0, 4))
        entry_row("Exposure time (ms)", self.exposure)
        entry_row("Minimum period (s)", self.minimum)
        entry_row("Maximum period (s)", self.maximum)
        entry_row("Contraction threshold (z)", self.contraction)

        ttk.Separator(c, orient="horizontal").pack(fill="x", pady=6)
        ttk.Button(c, text="1. Calibrate one pBoc (3 outlines)", command=self._seed).pack(fill="x", pady=2)
        ttk.Button(c, text="2. Review moving distractors", command=self._distractors).pack(fill="x", pady=2)
        self.run_button = ttk.Button(c, text="3. Analyze recording", command=self._start)
        self.run_button.pack(fill="x", pady=2)

        ttk.Label(self.center, text="pBoc defecation cycle analysis",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=6, pady=(6, 2))
        ttk.Label(self.center, wraplength=560, justify="left", foreground="#444444",
                  text=("Identify the tracked worm once (Calibrate). The program measures "
                        "posterior axial motion, anterior control motion, recovery, and "
                        "cadence. Every proposed event requires human review; the period "
                        "bounds only order review, never accept or reject events.")).pack(
            anchor="w", padx=6, pady=(0, 4))
        self.center_fig = Figure(figsize=(5.4, 3.4), dpi=100)
        self.center_ax = self.center_fig.add_subplot(111); self.center_ax.set_axis_off()
        self.center_canvas = FigureCanvasTkAgg(self.center_fig, master=self.center)
        self.center_canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self.center_ax.text(0.5, 0.5, "Choose a source; the first frame appears here.",
                            ha="center", va="center", fontsize=10, color="#888888")
        self.center_canvas.draw()
        nav = ttk.Frame(self.center); nav.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Button(nav, text="< frame", command=lambda: self._step_frame(-1)).pack(side="left")
        ttk.Button(nav, text="frame >", command=lambda: self._step_frame(1)).pack(side="left", padx=4)
        self._frame_slider = ttk.Scale(nav, from_=0, to=1, orient="horizontal", command=self._slide_frame)
        self._frame_slider.pack(side="left", fill="x", expand=True, padx=6)
        self._frame_label = ttk.Label(nav, text=""); self._frame_label.pack(side="left")
        self.status = tk.Text(self.center, height=9, wrap="word")
        self.status.pack(fill="x", padx=6, pady=(0, 6))
        self._log(
            "The 30 and 90 second defaults only order manual review. They never "
            "accept, reject, count, or establish a biological period. Adjust the "
            "review window for unusually fast or slow mutants.\n"
        )

    def _scale_value(self):
        try:
            return float(self.scale.get())
        except (TypeError, ValueError):
            return None

    def _current_frame(self):
        try:
            return read_image(self._first_image())
        except Exception:
            return None

    def _apply_scale(self, res):
        self.scale.set(f"{float(res['um_per_px']):.5f}")
        self._log(f"Scale set: {float(res['um_per_px']):.4f} um/pixel ({res.get('details','')})\n")

    def _load_source(self):
        try:
            self._frames = discover_images(Path(self.folder.get()))
        except Exception:
            self._frames = None; return
        self._frame = 0
        try:
            self._frame_slider.configure(to=max(0, len(self._frames) - 1)); self._frame_slider.set(0)
        except Exception:
            pass
        self._display_frame(0)

    def _display_frame(self, index):
        if not self._frames:
            return
        self._frame = max(0, min(len(self._frames) - 1, int(index)))
        try:
            im = read_image(self._frames[self._frame], grayscale=True).astype(float)
            lo, hi = np.percentile(im, [0.5, 99.5]); im = np.clip((im - lo) / max(hi - lo, 1), 0, 1)
        except Exception as exc:
            self.set_status(f"Could not load frame: {exc}"); return
        self.center_ax.clear(); self.center_ax.imshow(im, cmap="gray"); self.center_ax.set_axis_off()
        title = f"Frame {self._frame + 1}/{len(self._frames)}"
        if self._cal_on:
            key, _desc = PBOCCalibrationNavigator.LABELS[len(self._cal_anchors)]
            title += f"   |   landmark {len(self._cal_anchors)+1}/3: {key}"
            if self._cal_head:
                self.center_ax.plot(self._cal_head[0], self._cal_head[1], "o", color="#00e0ff", ms=7)
            if self._cal_tail:
                self.center_ax.plot(self._cal_tail[0], self._cal_tail[1], "o", color="#ff4fd8", ms=7)
            if self._cal_outline:
                xs = [p[0] for p in self._cal_outline]; ys = [p[1] for p in self._cal_outline]
                self.center_ax.plot(xs, ys, "-o", color="#ffcc00", ms=3, lw=1)
        self.center_ax.set_title(title, fontsize=9)
        try:
            self._frame_slider.set(self._frame)
        except Exception:
            pass
        self._frame_label.configure(text=f"{self._frame + 1}/{len(self._frames)}")
        self.center_canvas.draw()

    def _step_frame(self, delta):
        if self._frames:
            self._display_frame(self._frame + delta)

    def _slide_frame(self, value):
        if not self._frames:
            return
        f = max(0, min(len(self._frames) - 1, int(round(float(value)))))
        if f != self._frame:
            self._display_frame(f)

    def _source_row(self, parent, row):
        ttk.Label(parent, text="Source").grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=self.folder, width=66).grid(
            row=row, column=1, sticky="ew", padx=8, pady=5
        )
        buttons = ttk.Frame(parent)
        buttons.grid(row=row, column=2, sticky="e")
        ttk.Button(buttons, text="Choose file/stack/movie...", command=self._choose_source_file).pack(side="left")
        ttk.Button(buttons, text="Choose folder...", command=self._choose_folder).pack(side="left", padx=(4, 0))
        parent.columnconfigure(1, weight=1)

    def _path_row(self, parent, row, label, variable, command):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=variable, width=66).grid(
            row=row, column=1, sticky="ew", padx=8, pady=5
        )
        ttk.Button(parent, text="Choose...", command=command).grid(row=row, column=2)
        parent.columnconfigure(1, weight=1)

    def _choose_source_file(self):
        value = filedialog.askopenfilename(
            title="Choose TIFF stack, movie, or still image",
            filetypes=[
                ("Supported image/video", "*.tif *.tiff *.png *.jpg *.jpeg *.bmp *.pgm *.mp4 *.avi *.mov *.mkv *.webm *.m4v"),
                ("TIFF stacks", "*.tif *.tiff"),
                ("Movies", "*.mp4 *.avi *.mov *.mkv *.webm *.m4v"),
                ("All files", "*.*"),
            ])
        if not value:
            return
        try:
            self._prepare_output_default()
            frame_folder = self._materialize_source_file(Path(value))
            self.folder.set(str(frame_folder))
            self.source_path = str(Path(value))
            self._after_source_selected()
        except Exception as exc:
            messagebox.showerror("Open source", str(exc), parent=self)

    def _choose_folder(self):
        value = filedialog.askdirectory(
            title="Choose a numbered image sequence (TIFF, PNG, JPEG, BMP, PGM)")
        if value:
            self.folder.set(value)
            self.source_path = value
            self.source_cache_meta = None
            self._prepare_output_default()
            self._after_source_selected()

    def _prepare_output_default(self):
        if not self.output.get():
            self.output.set(str(Path.home() / "Documents" / "LabToolsResults" / "Defecation"))

    def _source_cache_root(self):
        return Path(self.output.get()) / "_frame_cache"

    def _source_cache_key(self, source: Path):
        stat = source.stat()
        identity = f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
        return hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]

    def _to_uint8_gray(self, frame):
        array = np.asarray(frame)
        if array.ndim == 3:
            array = array[..., :3].mean(axis=2)
        array = np.asarray(array, dtype=float)
        if array.size == 0:
            return array.astype(np.uint8)
        lo, hi = np.percentile(array, [0.2, 99.8])
        if hi <= lo:
            lo, hi = float(np.min(array)), float(np.max(array))
        if hi <= lo:
            return np.zeros(array.shape, dtype=np.uint8)
        return np.clip((array - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)

    def _materialize_source_file(self, source: Path):
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(source)
        root = self._source_cache_root()
        root.mkdir(parents=True, exist_ok=True)
        key = self._source_cache_key(source)
        cache = root / f"{source.stem}_{key}"
        manifest = cache / "source_manifest.json"
        if manifest.exists():
            try:
                meta = json.loads(manifest.read_text(encoding="utf-8"))
                if (meta.get("source") == str(source.resolve())
                        and meta.get("size") == source.stat().st_size
                        and meta.get("mtime_ns") == source.stat().st_mtime_ns
                        and meta.get("frames_written", 0) > 0):
                    self.source_cache_meta = meta
                    self._log(f"Using cached frame folder: {cache}\n")
                    return cache
            except Exception:
                pass
        cache.mkdir(parents=True, exist_ok=True)
        movie = open_movie(source)
        try:
            self._log(
                f"Preparing defecation source: {movie.source_kind}, "
                f"{movie.n_frames} frame(s), {movie.width}x{movie.height}. "
                "This is a one-time frame-cache step.\n")
            written = 0
            for index, frame in enumerate(movie.frames()):
                image = Image.fromarray(self._to_uint8_gray(frame))
                image.save(cache / f"frame_{index:06d}.png")
                written += 1
                if written == 1 or written % 100 == 0:
                    self._log(f"  cached {written} frame(s)...\n")
                    self.update_idletasks()
            if written <= 0:
                raise ValueError(f"No frames could be decoded from {source}")
            meta = {
                "schema_version": 1,
                "source": str(source.resolve()),
                "source_kind": movie.source_kind,
                "size": source.stat().st_size,
                "mtime_ns": source.stat().st_mtime_ns,
                "frames_written": written,
                "width": movie.width,
                "height": movie.height,
                "fps": movie.fps,
                "cache_folder": str(cache),
                "note": "8-bit grayscale frame cache for pBoc geometry/motion analysis",
            }
            manifest.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            self.source_cache_meta = meta
            self._log(f"Frame cache ready: {written} frame(s) in {cache}\n")
            if movie.fps and (not self.fps.get() or self.fps.get() == "7.5"):
                self.fps.set(f"{float(movie.fps):.6g}")
                self._log(f"FPS was read from the movie container: {self.fps.get()}\n")
            return cache
        finally:
            try:
                movie.close()
            except Exception:
                pass

    def _after_source_selected(self):
            self._load_source()
            session=self._calibration_session_path()
            if session.exists() and messagebox.askyesno(
                    "Resume pBoc calibration?",
                    "A saved three-outline calibration exists for this recording. Resume it?",
                    parent=self):
                try:
                    document=json.loads(session.read_text(encoding="utf-8"))
                    self.pboc_anchors=document["pboc_anchors"]
                    self.head=tuple(self.pboc_anchors[0]["head_xy"])
                    self.tail=tuple(self.pboc_anchors[0]["tail_xy"])
                    self.outline=[tuple(point) for point in self.pboc_anchors[0]["outline_xy"]]
                    self._log(f"Resumed saved pBoc calibration: {session.name}\n")
                except Exception as exc:
                    messagebox.showerror("Resume calibration",str(exc),parent=self)

    def _choose_output(self):
        value = filedialog.askdirectory(title="Choose output folder")
        if value:
            self.output.set(value)

    def _distractors(self):
        try:
            paths = discover_images(Path(self.folder.get()))
            output = Path(self.output.get())
            output.mkdir(parents=True, exist_ok=True)
            name = Path(self.folder.get()).name.replace(" ", "_")
            self.distractor_path = output / f"{name}_distractor_annotations.json"
            dialog = DistractorPreflight(self, paths, self.distractor_path)
            self.wait_window(dialog)
            if dialog.accepted:
                self.distractors_reviewed = True
                self._log(
                    f"Moving-distractor preflight saved {len(dialog.episodes)} "
                    f"episode(s): {self.distractor_path.name}\n")
        except Exception as exc:
            messagebox.showerror("Distractor preflight", str(exc), parent=self)

    def _first_image(self):
        return discover_images(Path(self.folder.get()))[0]

    def _calibration_session_path(self):
        folder=Path(self.folder.get())
        return folder/"NIKE_Review_Sessions"/f"{folder.name.replace(' ','_')}_pboc_calibration.json"

    def _seed(self):
        if not self._frames:
            self._load_source()
        if not self._frames:
            messagebox.showerror("Calibration", "Choose a source recording first.")
            return
        self._cal_on = True
        self._cal_anchors = []
        self._cal_begin_anchor()

    def _cal_begin_anchor(self):
        self._cal_head = None; self._cal_tail = None; self._cal_outline = []; self._cal_stage = "head"
        if self._cal_cid is None:
            self._cal_cid = self.center_canvas.mpl_connect("button_press_event", self._cal_click)
        self._display_frame(self._frame)
        self._cal_prompt()

    def _cal_prompt(self):
        key, desc = PBOCCalibrationNavigator.LABELS[len(self._cal_anchors)]
        stage = {"head": "click the HEAD",
                 "tail": "click the TAIL tip",
                 "outline": "trace the OUTLINE (left-click around the worm, right-click to finish)"}[self._cal_stage]
        self.set_status(f"Landmark {len(self._cal_anchors)+1}/3 - {desc}. Scroll to the frame, then {stage}. "
                        "Right-click cancels while marking head/tail.")

    def _cal_click(self, event):
        if not self._cal_on:
            return
        if event.button == 3:
            if self._cal_stage == "outline":
                self._cal_finish_outline()
            else:
                self._cal_cancel()
            return
        if event.inaxes != self.center_ax or event.xdata is None:
            return
        x, y = float(event.xdata), float(event.ydata)
        if self._cal_stage == "head":
            self._cal_head = (x, y); self._cal_stage = "tail"; self._display_frame(self._frame); self._cal_prompt()
        elif self._cal_stage == "tail":
            self._cal_tail = (x, y); self._cal_stage = "outline"; self._display_frame(self._frame); self._cal_prompt()
        elif self._cal_stage == "outline":
            self._cal_outline.append((x, y)); self._display_frame(self._frame)

    def _cal_finish_outline(self):
        if len(self._cal_outline) < 3:
            self.set_status("Outline needs at least 3 points; keep left-clicking, then right-click to finish.")
            return
        if self._cal_anchors and self._frame <= self._cal_anchors[-1]["frame"]:
            self.set_status("Pick a LATER frame than the previous landmark before finishing.")
            return
        key, _ = PBOCCalibrationNavigator.LABELS[len(self._cal_anchors)]
        self._cal_anchors.append({"frame": int(self._frame), "head_xy": list(self._cal_head),
                                  "tail_xy": list(self._cal_tail),
                                  "outline_xy": [list(p) for p in self._cal_outline], "state": key})
        if len(self._cal_anchors) >= 3:
            self._cal_complete()
            return
        self._frame = min(len(self._frames) - 1, self._frame + 1)
        self._cal_begin_anchor()

    def _cal_complete(self):
        self._cal_finish_mode()
        anchors = self._cal_anchors
        self.pboc_anchors = anchors
        self.head = tuple(anchors[0]["head_xy"])
        self.tail = tuple(anchors[0]["tail_xy"])
        self.outline = [tuple(p) for p in anchors[0]["outline_xy"]]
        try:
            session = self._calibration_session_path(); session.parent.mkdir(parents=True, exist_ok=True)
            session.write_text(json.dumps({"schema_version": 1, "pboc_anchors": anchors}, indent=2), encoding="utf-8")
        except Exception as exc:
            self._log(f"Could not save calibration session: {exc}\n")
        fi = [a["frame"] for a in anchors]
        try:
            fps = float(self.fps.get())
            self._log(f"Calibrated pBoc on frames {fi[0]+1}, {fi[1]+1}, and {fi[2]+1}: "
                      f"contraction {(fi[1]-fi[0])/fps:.3f}s; recovery {(fi[2]-fi[1])/fps:.3f}s.\n")
        except Exception:
            self._log(f"Calibrated pBoc on frames {fi[0]+1}, {fi[1]+1}, {fi[2]+1}.\n")
        self.set_status("pBoc calibration complete. Review distractors, then Analyze.")

    def _cal_cancel(self):
        self._cal_finish_mode()
        self.set_status("Calibration canceled.")
        self._display_frame(self._frame)

    def _cal_finish_mode(self):
        self._cal_on = False; self._cal_stage = None
        cid = getattr(self, "_cal_cid", None)
        if cid is not None:
            try:
                self.center_canvas.mpl_disconnect(cid)
            except Exception:
                pass
        self._cal_cid = None

    def _start(self):
        if (self.head is None or self.tail is None or not self.outline
                or not self.pboc_anchors):
            messagebox.showerror(
                "Calibration required", "Trace baseline, peak, and recovered pBoc frames first.")
            return
        if not self.distractors_reviewed or self.distractor_path is None:
            messagebox.showerror(
                "Distractor review required",
                "Review moving distractors first. If none are present, choose "
                "No distractors / clear all, then Save and use.")
            return
        try:
            folder = Path(self.folder.get())
            output = Path(self.output.get())
            output.mkdir(parents=True, exist_ok=True)
            fps = float(self.fps.get())
            scale = float(self.scale.get())
            exposure = float(self.exposure.get())
            minimum = float(self.minimum.get())
            maximum = float(self.maximum.get())
            threshold = float(self.contraction.get())
            if not (fps > 0 and scale > 0 and exposure > 0 and 0 < minimum < maximum):
                raise ValueError("FPS, scale, exposure, or period limits are not valid.")
            source_info = sequence_provenance(discover_images(folder))
            if self.source_path:
                source_info["original_source"] = self.source_path
            if self.source_cache_meta:
                source_info["frame_cache"] = self.source_cache_meta
            (output / "source_format_provenance.json").write_text(
                json.dumps(source_info, indent=2), encoding="utf-8")
            if source_info["lossy_compression_present"]:
                self._log(
                    "JPEG/WebP frames are accepted for geometry and motion. "
                    "Their pixel intensities are not quantitative.\n")
            seed_path = output / f"{folder.name.replace(' ', '_')}_tracking_seed.json"
            seed_path.write_text(json.dumps({
                "head_xy": list(self.head), "tail_xy": list(self.tail),
                "outline_xy": [list(point) for point in self.outline],
                "source_frame": int(self.pboc_anchors[0]["frame"]),
                "coordinate_space": "source_pixels",
                "pboc_anchors": self.pboc_anchors,
            }, indent=2), encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("Settings", str(exc))
            return

        name = folder.name.replace(" ", "_")
        command = [
            sys.executable, str(ENGINE), str(folder),
            "--name", name,
            "--fps", str(fps),
            "--um-per-px", str(scale),
            "--exposure-ms", str(exposure),
            "--fps-source", "declared",
            "--scale-source", "declared",
            "--exposure-source", "declared",
            "--head-x", str(self.head[0]),
            "--head-y", str(self.head[1]),
            "--tail-x", str(self.tail[0]),
            "--tail-y", str(self.tail[1]),
            "--seed-outline-json", str(seed_path),
            "--distractor-annotations-json", str(self.distractor_path),
            "--contraction-z", str(threshold),
            "--min-period", str(minimum),
            "--max-period", str(maximum),
            "--output-dir", str(output),
        ]
        self.run_button.state(["disabled"])
        self._log("Analysis started. Large recordings may take several minutes.\n")
        threading.Thread(
            target=self._run, args=(command, output, folder, name), daemon=True
        ).start()

    def _run(self, command, output, folder, name):
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, errors="replace"
            )
            self.after(0, self._log, result.stdout[-6000:])
            if result.returncode:
                self.after(0, self._log, "\nERROR\n" + result.stderr[-4000:])
            else:
                self.after(
                    0, self._log,
                    f"\nFinished. Review tables were saved in:\n{output}\n"
                )
                summary = output / f"{name}_full_scan.json"
                self.after(0, self._open_reviewer, summary, folder)
        except Exception as exc:
            self.after(0, self._log, f"\nAnalysis failed: {exc}\n")
        finally:
            self.after(0, lambda: self.run_button.state(["!disabled"]))

    def _log(self, text):
        self.status.insert("end", text)
        self.status.see("end")

    def _open_reviewer(self, summary_path: Path, folder: Path):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror("Review", f"Could not open candidate list:\n{exc}")
            return
        PBOCReviewer(
            self, summary, folder, summary_path.parent,
            discover_images(folder))


class Reviewer(tk.Toplevel):
    def __init__(self, parent, summary: dict, folder: Path, output: Path):
        super().__init__(parent)
        self.title("Review pBoc candidates")
        self.geometry("980x720")
        self.summary = summary
        self.folder = folder
        self.output = output
        self.fps = float(summary["fps"])
        self.paths = sorted(folder.glob("*.tif")) or sorted(folder.glob("*.tiff"))
        self.events = [dict(event, decision="unreviewed", source="automatic")
                       for event in summary.get("events", [])]
        self.index = 0
        self.photo = None
        self._build()
        self._refresh_list()
        self._show()

    def _build(self):
        ttk.Label(
            self, text="Human review is required",
            font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        ttk.Label(
            self,
            text=(
                "Cadence notes only order attention. They do not accept, reject, "
                "count, or establish a biological period."
            ),
            wraplength=930, justify="left").pack(anchor="w", padx=12)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=8)
        left = ttk.Frame(body, width=330)
        left.pack(side="left", fill="y")
        self.listbox = tk.Listbox(left, width=48, font=("Consolas", 9))
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._select)
        ttk.Button(left, text="Add missed event...", command=self._add_missed).pack(
            fill="x", pady=(6, 0))

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.image = ttk.Label(right)
        self.image.pack(fill="both", expand=True)
        self.details = ttk.Label(right, text="", wraplength=600, justify="left")
        self.details.pack(fill="x", pady=6)
        decisions = ttk.Frame(right)
        decisions.pack(fill="x")
        for text, value in [
            ("Accept pBoc", "accepted"),
            ("Reject", "rejected"),
            ("Uncertain", "uncertain"),
        ]:
            ttk.Button(
                decisions, text=text,
                command=lambda value=value: self._decide(value)
            ).pack(side="left", padx=(0, 6))
        ttk.Button(decisions, text="Save reviewed events", command=self._save).pack(
            side="right")

    def _refresh_list(self):
        self.listbox.delete(0, "end")
        for event in self.events:
            frame = int(event["peak_frame"])
            note = event.get("review_note", "manual")
            decision = event.get("decision", "unreviewed")
            self.listbox.insert(
                "end",
                f"{frame:6d}  {frame/self.fps:8.2f}s  "
                f"{decision:10s}  {note}")
        if self.events:
            self.index = min(self.index, len(self.events) - 1)
            self.listbox.selection_set(self.index)

    def _select(self, _event=None):
        selected = self.listbox.curselection()
        if selected:
            self.index = selected[0]
            self._show()

    def _show(self):
        if not self.events or not self.paths:
            return
        event = self.events[self.index]
        frame = max(0, min(len(self.paths) - 1, int(event["peak_frame"])))
        with Image.open(self.paths[frame]) as source:
            array = np.asarray(source, dtype=float)
        lo, hi = np.percentile(array, [0.5, 99.5])
        shown = np.clip((array - lo) * 255 / max(hi - lo, 1), 0, 255).astype("uint8")
        picture = Image.fromarray(shown)
        picture.thumbnail((620, 500), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(picture)
        self.image.configure(image=self.photo)
        self.details.configure(text=(
            f"Frame {frame}, time {frame/self.fps:.3f} s\n"
            f"Axial-flow score z: {event.get('peak_z', 'manual')}\n"
            f"Recovery found: {event.get('has_recovery', 'manual')}\n"
            f"Review note: {event.get('review_note', 'manual addition')}\n"
            f"Decision: {event.get('decision', 'unreviewed')}"
        ))

    def _decide(self, value):
        if not self.events:
            return
        self.events[self.index]["decision"] = value
        self._refresh_list()
        self._show()

    def _add_missed(self):
        frame = simpledialog.askinteger(
            "Add missed event",
            f"Frame number (0 to {max(0, len(self.paths)-1)}):",
            parent=self, minvalue=0, maxvalue=max(0, len(self.paths)-1))
        if frame is None:
            return
        self.events.append({
            "peak_frame": frame,
            "peak_time_s": frame / self.fps,
            "peak_z": np.nan,
            "has_recovery": "not_assessed",
            "review_note": "manual_addition",
            "decision": "accepted",
            "source": "manual",
        })
        self.events.sort(key=lambda event: int(event["peak_frame"]))
        self.index = next(
            i for i, event in enumerate(self.events)
            if int(event["peak_frame"]) == frame and event["source"] == "manual")
        self._refresh_list()
        self._show()

    def _save(self):
        path = self.output / f"{self.summary['recording']}_reviewed_events.csv"
        fields = [
            "event_number", "peak_frame", "peak_time_s", "decision", "source",
            "peak_z", "has_recovery", "recovery_frame", "review_note",
            "fps", "fps_source", "um_per_px", "um_per_px_source",
            "exposure_ms", "exposure_source",
        ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for number, event in enumerate(self.events, 1):
                writer.writerow({
                    "event_number": number,
                    "peak_frame": event["peak_frame"],
                    "peak_time_s": event.get(
                        "peak_time_s", int(event["peak_frame"]) / self.fps),
                    "decision": event.get("decision", "unreviewed"),
                    "source": event.get("source", "automatic"),
                    "peak_z": event.get("peak_z", np.nan),
                    "has_recovery": event.get("has_recovery", ""),
                    "recovery_frame": event.get("recovery_frame", ""),
                    "review_note": event.get("review_note", ""),
                    "fps": self.summary["fps"],
                    "fps_source": self.summary["fps_source"],
                    "um_per_px": self.summary["um_per_px"],
                    "um_per_px_source": self.summary["um_per_px_source"],
                    "exposure_ms": self.summary["exposure_ms"],
                    "exposure_source": self.summary["exposure_source"],
                })
        messagebox.showinfo(
            "Review saved",
            f"Reviewed decisions saved to:\n{path}\n\n"
            "Unreviewed candidates remain explicitly labelled unreviewed.",
            parent=self)


if __name__ == "__main__":
    App().mainloop()
