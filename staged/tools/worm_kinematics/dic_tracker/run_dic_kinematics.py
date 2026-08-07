"""
run_dic_kinematics.py
=====================
Tracks ONE worm in a transmitted-light (DIC / Nomarski / brightfield) recording
and writes the per-frame, per-segment CSV that the kinematics analysis consumes
(run_one_kinematics.py -> undulation, locomotion, foraging, posterior dampening).

RUNS IN THE LAB TOOLS PYTHON ENVIRONMENT, NOT FIJI. Launch with
Track_DIC_Worm.bat, or from the Lab Tools hub.

Flow: pick a movie or image folder -> fps and scale -> click the HEAD, then trace
the worm outline -> it tracks -> a REVIEW WINDOW opens so you can step through,
jump to flagged frames, and correct them -> it saves
<name>_dickinematics_<date>.csv next to the movie.

Review keys:
  left/right : previous / next frame        n : next flagged frame
  a          : jump to suggested minimum-work anchor
  f          : fix/add an anchor here (click HEAD, then outline, Enter)
  t          : re-track forward from here   s or close : save
"""
import argparse, os, re, sys, csv, datetime, json, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP_DIR = ROOT / "app"
AFD_TOOL = ROOT / "tools" / "afd_neuron"
MOVIE_TOOL = ROOT / "tools" / "movie"
sys.path.insert(0, str(AFD_TOOL))
sys.path.insert(0, str(MOVIE_TOOL))
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import numpy as np
except ModuleNotFoundError:
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk(); r.withdraw()
        try:                      # error reporting
            from process_ui import install_error_reporting
            install_error_reporting(r)
        except Exception as _e:   # never break the tool for this
            print('error reporting unavailable:', _e)
        messagebox.showerror("Wrong Python environment",
            "This tool needs the Lab tools Python environment.\n\n"
            "Start it with Track_DIC_Worm.bat, or from the Lab Tools hub opened via "
            "Launch_Lab_Hub.bat. Do not double-click the .py file directly.\n\n"
            "If it still fails, run Setup_Lab_Tools.bat once on this computer, then "
            "Install_Extra_Libraries.bat.")
        r.destroy()
    except Exception:
        print("This tool needs the Lab tools Python environment (numpy is missing).")
    raise SystemExit

from tracker_review_session import (load_tracker_session,
                                    resume_or_start_fresh,
                                    save_tracker_session)
from virtual_frame_stack import DiskBackedFrameStack


def _recording_context(path, frame_count, crop=None):
    selected = Path(path).resolve()
    match = re.match(r"^(.*?[-_])(\d+)$", selected.stem)
    recording_key = match.group(1).rstrip("-_") if match else selected.stem
    if match:
        prefix = match.group(1)
        files = sorted(
            (candidate for candidate in selected.parent.iterdir()
             if candidate.is_file()
             and candidate.suffix.lower() == selected.suffix.lower()
             and re.fullmatch(re.escape(prefix)+r"\d+", candidate.stem)),
            key=lambda candidate: int(candidate.stem[len(prefix):]))
    else:
        files = [selected]
    source = {
        "recording_key": recording_key,
        "first_frame": files[0].name,
        "last_frame": files[-1].name,
        "frame_count": int(frame_count),
        "analysis_crop_xyxy": list(crop) if crop is not None else None,
    }
    session = selected.parent / "NIKE_Review_Sessions" / f"{recording_key}_single_worm_review.json"
    return recording_key, source, session


def _load_gray(path, crop=None):
    """Load every frame as greyscale via movie_reader (video, TIFF stack, or a
    folder of images). If the user picked ONE image of a sequence, read the whole
    folder it sits in, keeping only the numbered filename series selected by
    the user. Dimensions alone are insufficient because experiment folders
    commonly contain several same-camera recordings."""
    import movie_reader
    m = movie_reader.open_movie(path)
    note = ""
    ref_shape = None
    if getattr(m, "source_kind", "") == "single_image":
        first = next(iter(m.frames()))
        ref_shape = first.shape[:2]                  # the picked image's H,W
        m.close()
        selected = Path(path).resolve()
        match = re.match(r"^(.*?[-_])(\d+)$", selected.stem)
        prefix = match.group(1) if match else ""
        m = movie_reader.open_numbered_image_sequence(selected)
        note = f"read numbered series {prefix + '#'*len(match.group(2)) if match else selected.name}"
    full_shape = ref_shape or (int(m.height), int(m.width))
    if crop is None:crop=(0,0,full_shape[1],full_shape[0])
    x0,y0,x1,y1=[int(v) for v in crop]
    target_shape=(y1-y0,x1-x0)
    if int(m.n_frames)*target_shape[0]*target_shape[1]*4>2_000_000_000:
        return DiskBackedFrameStack.from_movie(m,crop=crop,channel="gray"),"disk-backed virtual stack (bounded RAM)"
    # One float32 allocation replaces the old list -> stack -> astype chain,
    # which could transiently hold two or three complete copies of a movie.
    output = np.empty((int(m.n_frames), *target_shape), dtype=np.float32)
    skipped = 0
    kept = 0

    def gray(fr):
        if fr.ndim not in (2, 3) or (fr.ndim == 3 and fr.shape[2] not in (3, 4)):
            return None
        if ref_shape is not None and fr.shape[:2] != ref_shape:
            return None
        if fr.shape[:2] != full_shape:
            return None
        if fr.ndim == 3:
            # Avoid numpy.mean's float64 intermediate for RGB input.
            return (np.add.reduce(fr[y0:y1,x0:x1,:3],axis=2,dtype=np.float32)
                    /np.float32(3.0))
        return np.asarray(fr[y0:y1,x0:x1], dtype=np.float32)

    if getattr(m, "source_kind", "") == "image_sequence":
        # Independent image files are safe to decode concurrently. A small
        # bound hides SMB/file-open latency without flooding a lab server.
        workers = min(6, max(2, (os.cpu_count() or 2) // 2))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            decoded = pool.map(
                lambda index: gray(m.get_frame(index)),
                range(int(m.n_frames)))
            for fr in decoded:
                if fr is None:
                    skipped += 1
                else:
                    output[kept] = fr
                    kept += 1
    else:
        # Video codecs and TIFF handles are intentionally read sequentially.
        for source in m.frames():
            fr = gray(source)
            if fr is None:
                skipped += 1
            else:
                output[kept] = fr
                kept += 1
    m.close()
    if not kept:
        return np.empty((0, 1, 1), np.float32), "no usable frames"
    if skipped:
        note += f" ({skipped} other file(s) in the folder ignored)"
    return output[:kept], note


def _require_positive_scale(simpledialog, messagebox):
    """Collect an honest calibration before any expensive movie load."""
    while True:
        value = simpledialog.askfloat(
            "Required spatial calibration",
            "Micrometres per pixel (must be greater than zero):\n\n"
            "Use the microscope/camera calibration for this magnification. "
            "If it is unknown, choose Cancel and calibrate with a stage "
            "micrometer before analysis.",
            initialvalue=1.0, minvalue=0.000001)
        if value is None:
            return None
        if np.isfinite(value) and value > 0:
            return float(value)
        messagebox.showerror(
            "Spatial calibration required",
            "Scale cannot be zero or blank. No physical kinematics can be "
            "reported without a positive micrometres-per-pixel calibration.")


class Reviewer:
    def __init__(self, tr, G, plt, session_path, source):
        self.tr = tr; self.G = G; self.plt = plt; self.i = 0
        self.session_path = Path(session_path); self.source = source
        self.interval_start = None; self.active_interval = None; self.finalized = False
        from matplotlib.widgets import Slider,Button
        self.fig, self.ax = plt.subplots(figsize=(11, 7));self.fig.subplots_adjust(bottom=.17)
        import display_range as _dr; _dr.name_window(self.fig, "Review the tracked spines - single worm")
        slider_ax=self.fig.add_axes([.18,.065,.58,.035]);self.slider=Slider(slider_ax,"Frame",1,self.tr.T,valinit=1,valstep=1);self.slider.on_changed(self._slider_changed)
        jump_ax=self.fig.add_axes([.78,.05,.14,.06]);self.jump_button=Button(jump_ax,"Jump to frame…");self.jump_button.on_clicked(self.jump_to_frame)
        self.fig.canvas.mpl_connect("key_press_event", self.on_key)
        self.fig.canvas.mpl_connect("close_event", self._close_as_wip)
        self._im = None
        self._overlays = []
        self._fit_window()
        self.draw()

    def _fit_window(self):
        """Force the review window to a screen-clamped, non-maximized size.

        Some Tk/HiDPI setups open the matplotlib window larger than the screen
        (its title-bar controls end up off-edge, so it cannot be resized without
        quitting).  This is called both now and, via ``after`` in ``run``, once
        the window has actually been mapped, because the backend can resize it on
        show and override an early geometry request.
        """
        try:
            win = self.fig.canvas.manager.window
            try:
                win.wm_state("normal")
            except Exception:
                pass
            sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
            ww, wh = min(1150, sw - 120), min(780, sh - 140)
            win.geometry(
                f"{ww}x{wh}+{max(0, (sw - ww) // 2)}+{max(0, (sh - wh) // 4)}")
        except Exception:
            pass

    def _slider_changed(self,value):
        index=int(round(value))-1
        if index!=self.i:self.i=max(0,min(self.tr.T-1,index));self.draw(update_slider=False)

    def jump_to_frame(self,_event=None):
        from tkinter import simpledialog
        parent=getattr(self.fig.canvas.manager,"window",None)
        value=simpledialog.askinteger("Jump to frame","Frame number:",initialvalue=self.i+1,minvalue=1,maxvalue=self.tr.T,parent=parent)
        if value is not None:self.i=value-1;self.draw()

    def save_progress(self):
        save_tracker_session(
            self.session_path, self.tr, tool="single_worm_tracker",
            source=self.source)

    def _close_as_wip(self, _event=None):
        if not self.finalized:
            self.save_progress()

    def draw(self,update_slider=True):
        i = self.i; s = self.tr.state[i]
        frame = self.G[i]
        # Reuse the image artist (set_data) instead of ax.clear()+imshow() every
        # frame; rebuilding the whole axes each step is what makes scrubbing slow.
        if self._im is None:
            self._im = self.ax.imshow(frame, cmap="gray")
            self.ax.axis("off")
        else:
            self._im.set_data(frame)
            try:
                fmin = float(np.min(frame)); fmax = float(np.max(frame))
                if fmax > fmin:
                    self._im.set_clim(fmin, fmax)
            except Exception:
                pass
        for _artist in self._overlays:
            try:
                _artist.remove()
            except Exception:
                pass
        self._overlays = []
        if s["pts"] is not None:
            p = s["pts"]
            self._overlays += self.ax.plot(p[:, 0], p[:, 1], "y-", lw=1.5)
            self._overlays += self.ax.plot(p[:, 0], p[:, 1], "y.", ms=3)
        if s["head"][0] == s["head"][0]:
            self._overlays += self.ax.plot(s["head"][0], s["head"][1], "c+", ms=16, mew=3)   # head
        if s["tail"][0] == s["tail"][0]:
            self._overlays += self.ax.plot(s["tail"][0], s["tail"][1], "r.", ms=10)          # tail
        flag = "   *** NEEDS REVIEW ***" if s["needs_help"] else ""
        suggested = "   *** SUGGESTED ANCHOR ***" if s.get("suggested_manual_anchor") else ""
        reason = s.get("reconstruction_reason", "") if s["needs_help"] else ""
        nh = sum(1 for st in self.tr.state if st and st["needs_help"])
        title = f"frame {i+1}/{self.tr.T}   [{s['provenance']}]{flag}{suggested}    ({nh} flagged)\n"
        if reason:
            title += reason+"\n"
        if self.interval_start is not None:
            title += (f"Interval start: frame {self.interval_start+1}; move to the end and "
                      "press e, or press f to fix the end anchor now.\n")
        elif self.active_interval is not None:
            lo, hi = self.active_interval
            title += (f"BOUNDED EDIT: frames {lo+1}-{hi+1}. f adds an anchor only "
                      "inside this interval; c closes bounded editing.\n")
        title += ("cyan + = head, red . = tail    arrows: move (PgUp/PgDn ±10)   n: next flagged   "
                  "a: suggested anchor   f: fix/add anchor   b/e: bounded interval   c: close interval\n"
                  "g: segmentation workbench + retrack   w: save progress   "
                  "q/close: save progress & exit   s: finalize CSV")
        self.ax.set_title(title)
        if update_slider and int(round(self.slider.val))!=self.i+1:self.slider.set_val(self.i+1)
        self.fig.canvas.draw_idle()

    def on_key(self, e):
        if e.key == "right": self.i = min(self.tr.T-1, self.i+1); self.draw()
        elif e.key == "left": self.i = max(0, self.i-1); self.draw()
        elif e.key in ("pagedown", "shift+right"): self.i = min(self.tr.T-1, self.i+10); self.draw()
        elif e.key in ("pageup", "shift+left"): self.i = max(0, self.i-10); self.draw()
        elif e.key == "home": self.i = 0; self.draw()
        elif e.key == "end": self.i = self.tr.T-1; self.draw()
        elif e.key == "n":
            f = [j for j in range(self.tr.T) if self.tr.state[j]["needs_help"]]
            after = [j for j in f if j > self.i]
            if after: self.i = after[0]
            elif f: self.i = f[0]
            self.draw()
        elif e.key == "f": self.fix()
        elif e.key == "a":
            anchor = self.tr.next_suggested_anchor(self.i)
            if anchor is not None: self.i = anchor
            self.draw()
        elif e.key == "t":
            self.tr.retrack_from(self.i); self.save_progress(); self.draw()
        elif e.key == "g":
            self.review_segmentation()
        elif e.key == "b":
            self.interval_start = self.i; self.active_interval = None; self.draw()
        elif e.key == "e":
            if self.interval_start is not None:
                lo, hi = sorted((self.interval_start, self.i))
                self.active_interval = (lo, hi)
                self.tr.reanalyze_interval(lo, hi)
                self.interval_start = None; self.save_progress(); self.draw()
        elif e.key == "c":
            self.interval_start = None; self.active_interval = None; self.draw()
        elif e.key == "w": self.save_progress(); self.draw()
        elif e.key == "q": self.save_progress(); self.plt.close(self.fig)
        elif e.key == "s":
            self.save_progress(); self.finalized = True; self.plt.close(self.fig)

    def fix(self):
        i = self.i
        # ``b`` followed by an end-frame ``f`` is the natural way reviewers
        # try to repair a bad span.  Previously only ``e`` activated the
        # interval, so that sequence silently performed an ordinary/global fix
        # and never reconstructed the selected middle frames.  Treat ``f`` as
        # both "finish interval" and "fix this boundary" while a start is
        # pending; the explicit b/e workflow remains available unchanged.
        if self.interval_start is not None:
            lo, hi = sorted((self.interval_start, i))
            self.active_interval = (lo, hi)
            self.interval_start = None
        self.ax.set_title(f"FIX frame {i+1}: click the HEAD   (right-click = undo, Enter = confirm)")
        self.fig.canvas.draw()
        hp = self.fig.ginput(0, timeout=0)
        if not hp: self.draw(); return
        head = hp[-1]
        self.ax.set_title(f"FIX frame {i+1}: click the WORM OUTLINE, or just press Enter to keep "
                          "the automatic one   (right-click = undo)")
        self.fig.canvas.draw()
        verts = self.fig.ginput(0, timeout=0)
        bounded = (self.active_interval is not None
                   and self.active_interval[0] <= i <= self.active_interval[1])
        self.tr.recompute_frame(
            i, head=head, outline_verts=(verts if len(verts) >= 3 else None),
            reconstruct_bounds=(self.active_interval if bounded else None))
        if not bounded:
            # Outside bounded-edit mode, retain the original forward retracking
            # workflow for a deliberately global correction.
            self.tr.retrack_from(i, stop_at_next_clip=True)
        self.save_progress()
        self.draw()

    def review_segmentation(self):
        """Run mask review in an isolated Tk process, then retrack."""
        import subprocess
        from tkinter import messagebox
        from segmentation_review import SegmentationConfig
        root = self.fig.canvas.manager.window
        save_dir = self.session_path.parent.parent
        source_path = (self.tr.segmentation_config.source
                       if self.tr.segmentation_config is not None else str(save_dir))
        result_path = save_dir / "nike_segmentation_review.json"
        previous_mtime = (
            result_path.stat().st_mtime_ns if result_path.exists() else None)
        launcher = ROOT / "tools" / "segmentation_review_tool.py"
        completed = subprocess.run(
            [sys.executable, str(launcher), str(source_path),
             "--tool", "track_one_worm"], check=False)
        current_mtime = (
            result_path.stat().st_mtime_ns if result_path.exists() else None)
        if completed.returncode != 0:
            messagebox.showerror(
                "Segmentation workbench",
                "The isolated segmentation workbench exited with an error.",
                parent=root)
            self.draw()
            return
        if current_mtime is None or current_mtime == previous_mtime:
            self.draw()
            return
        config = SegmentationConfig.load(result_path)
        self.tr.segmentation_config = config
        head_seed = self.tr.state[0]["head"] if self.tr.state[0] else None
        if head_seed is None or not np.all(np.isfinite(head_seed)):
            messagebox.showerror(
                "Retrack", "Frame 1 has no valid anatomical-head seed. "
                "Restart tracking and seed the head again.", parent=root)
            self.draw()
            return
        self.ax.set_title("Applying locked segmentation map and retracking...")
        self.fig.canvas.draw()
        self.tr.track_all(head_seed=head_seed)
        self.save_progress()
        self.i = 0
        self.draw()

    def run(self):
        # Re-apply the clamp after the window is actually mapped: the backend can
        # size/zoom the window on show and override the geometry set at init.
        try:
            win = self.fig.canvas.manager.window
            win.after(200, self._fit_window)
            win.after(800, self._fit_window)
        except Exception:
            pass
        self.plt.show()


def _seed(G, plt):
    from skimage.draw import polygon2mask
    import display_range
    fig, ax = plt.subplots(figsize=(11, 7.8))
    import display_range as _dr; _dr.name_window(fig, "Step 1 of 2: click the head, then draw the outline")
    frame = np.asarray(G[0])
    # BRIGHTNESS AND CONTROL OVER IT, because the outline drawn here sets the
    # reference length and area that every later frame is accepted against.
    # At default scaling a mid-grey worm on oblique-lit agar is close to
    # invisible, and an outline drawn around something unseen produces a
    # reference no real detection matches.
    picture = ax.imshow(frame, cmap="gray")
    fig.subplots_adjust(bottom=0.16)
    display_range.attach_sliders(fig, picture, frame, plt)
    ax.set_title("STEP 1: click the worm's HEAD (sets which end is anterior)\n"
                 "right-click = undo,   Enter = confirm\n"
                 "Use the Black/White sliders below if the worm is hard to see")
    fig.canvas.draw()
    hp = plt.ginput(0, timeout=0)
    if not hp:
        plt.close(fig); return None, None
    head = hp[-1]; ax.plot(head[0], head[1], "c+", ms=16, mew=3)
    ax.set_title("STEP 2: click around the WORM OUTLINE (sets its length and area)\n"
                 "right-click = undo last,   Enter = finish")
    fig.canvas.draw()
    verts = plt.ginput(0, timeout=0)
    plt.close(fig)
    mask = None
    if len(verts) >= 3:
        mask = polygon2mask(G.shape[1:], np.array([(y, x) for (x, y) in verts]))
    return head, mask


def _parse_frame_range(text, n_frames):
    """Parse a 1-based inclusive frame range into 0-based (start, end).

    Accepts ``"a-b"`` / ``"a:b"`` / ``"a to b"``, a single ``"a"`` (from a to the
    end), or blank/invalid (the whole movie).  Values are clamped to
    ``[1, n_frames]`` and ordered.
    """
    n = int(n_frames)
    if not text or not str(text).strip():
        return (0, n - 1)
    t = str(text).strip().lower().replace(" ", "").replace("to", "-").replace(":", "-")
    if "-" in t:
        a, _, b = t.partition("-")
        try:
            s, e = int(a), int(b)
        except ValueError:
            return (0, n - 1)
    else:
        try:
            s = int(t)
        except ValueError:
            return (0, n - 1)
        e = n
    s = max(1, min(n, s)); e = max(1, min(n, e))
    if e < s:
        s, e = e, s
    return (s - 1, e - 1)


class _ProgressWindow:
    """A window that EXISTS while the computation runs.

    THE BUG THIS FIXES. `_seed` ends with plt.close(fig); tracking then runs
    for minutes; the review window is not created until afterwards. So the
    window did not freeze or grey out - it CEASED TO EXIST, and from outside
    that is indistinguishable from a crash. Students concluded the tool had
    died and started over, which wastes the whole computation they were
    waiting on.

    A static "please wait" window would still look hung, so this is driven by
    a callback from the tracking loops and moves. Matplotlib is single
    threaded here, so flush_events() is what keeps the window painted while
    the same thread computes; that is enough for the window to look alive
    without moving tracking off-thread.
    """

    def __init__(self, plt, total, title="Tracking"):
        self.plt = plt
        self.total = max(int(total), 1)
        self.fig, self.ax = plt.subplots(figsize=(7.5, 2.4))
        self.fig.canvas.manager.set_window_title(title)
        self.ax.set_xlim(0, 1); self.ax.set_ylim(0, 1); self.ax.axis("off")
        self.bar = self.ax.barh([0.35], [0.0], height=0.28, left=0.02,
                                color="#3878c0")[0]
        self.ax.barh([0.35], [0.96], height=0.28, left=0.02,
                     color="#dddddd", zorder=0)
        self.text = self.ax.text(0.02, 0.78, "Starting...", fontsize=11)
        self.note = self.ax.text(
            0.02, 0.06,
            "This window stays open while the computation runs. "
            "It is not frozen - closing it will not stop the analysis.",
            fontsize=8, color="#666666")
        self.fig.tight_layout()
        self._last = -1.0
        self.fig.canvas.draw()
        self.plt.pause(0.001)

    def __call__(self, done, total=None, phase=""):
        total = max(int(total or self.total), 1)
        fraction = min(max(done / total, 0.0), 1.0)
        # Repaint on whole percents only. Redrawing every frame on a 9,000
        # frame recording would cost more than the tracking.
        if fraction - self._last < 0.01 and done + 1 < total:
            return
        self._last = fraction
        self.bar.set_width(0.96 * fraction)
        self.text.set_text(f"{phase or 'Working'}: frame {done + 1:,} of "
                           f"{total:,}   ({fraction * 100:.0f}%)")
        try:
            self.fig.canvas.draw_idle()
            self.fig.canvas.flush_events()
        except Exception:                                   # noqa: BLE001
            pass          # a closed window must never take the analysis down

    def close(self):
        try:
            self.plt.close(self.fig)
        except Exception:                                   # noqa: BLE001
            pass


def _inherited_interval(args, n_frames, messagebox=None):
    """The interval a calling tool handed over, as 0-based inclusive, or None.

    Returns None when no range was given, so the slider still runs for anyone
    launching the tracker directly.

    A RANGE THAT DOES NOT FIT THE RECORDING IS REFUSED, NOT CLAMPED. Silently
    trimming it would analyse a different span than the caller assessed and
    report it under the caller's numbers, which is the same corruption class
    as a misaligned state array: wrong, and indistinguishable from right.
    """
    start, end = getattr(args, "frame_start", None), getattr(args, "frame_end", None)
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise SystemExit(
            "--frame-start and --frame-end must be given together; a half "
            "specified range cannot be inherited.")
    first, last = int(start) - 1, int(end) - 1          # 1-based -> 0-based
    if first < 0 or last < first or last >= n_frames:
        message = (f"The calling tool asked for frames {start}-{end}, but "
                   f"this recording has {n_frames}. Nothing was analysed - "
                   f"the range was not trimmed to fit, because analysing a "
                   f"different span than the one that was assessed would "
                   f"report the wrong frames under the right label.")
        if messagebox is not None:
            messagebox.showerror("Inherited range does not fit", message)
        raise SystemExit(message)
    if last - first + 1 < 3:
        message = (f"The inherited interval {start}-{end} is under 3 frames, "
                   f"which is too short to track.")
        if messagebox is not None:
            messagebox.showerror("Inherited range too short", message)
        raise SystemExit(message)
    return first, last


def _choose_analysis_interval(G, plt):
    """Visually pick the frames to KEEP by scrolling the loaded movie.

    Replaces the old text ``askstring`` frame-range prompt, which asked for a
    range before the user could see or scroll the recording.  Shows the frames
    with a slider and Set start / Set end buttons; returns ``(start, end)``
    0-based inclusive, or ``None`` to keep the whole recording.
    """
    from matplotlib.widgets import Slider, Button
    n = int(G.shape[0])
    state = {"start": 0, "end": n - 1, "i": 0, "trimmed": False}
    import display_range
    fig, ax = plt.subplots(figsize=(11, 7.6))
    import display_range as _dr; _dr.name_window(fig, "Choose the frames to analyse")
    fig.subplots_adjust(bottom=0.30)
    first = np.asarray(G[0])
    im = ax.imshow(first, cmap="gray"); ax.axis("off")
    # The same brightness control as the seeding screen: choosing where a
    # recording starts and ends means seeing when the animal enters and
    # leaves, which default scaling can hide entirely.
    display_range.attach_sliders(fig, im, first, plt, bottom=0.005)

    def redraw():
        frame = np.asarray(G[state["i"]])
        im.set_data(frame)
        try:
            fmin, fmax = float(np.min(frame)), float(np.max(frame))
            if fmax > fmin:
                im.set_clim(fmin, fmax)
        except Exception:
            pass
        span = ("whole recording" if not state["trimmed"]
                else f"KEEP frames {state['start'] + 1}-{state['end'] + 1}")
        ax.set_title(
            f"Optional: choose the interval to KEEP.   Frame {state['i'] + 1}/{n}\n"
            f"Current selection: {span}\n"
            "Scroll with the slider or arrow keys (PgUp/PgDn = +/-10). "
            "Set start / Set end mark this frame.\n"
            "Keep all frames, or Use this interval, to continue.")
        fig.canvas.draw_idle()

    slider = Slider(fig.add_axes([0.15, 0.12, 0.6, 0.035]),
                    "Frame", 1, max(1, n), valinit=1, valstep=1)

    def on_slide(value):
        state["i"] = max(0, min(n - 1, int(round(value)) - 1)); redraw()
    slider.on_changed(on_slide)

    def set_start(_e=None):
        state["start"] = state["i"]
        if state["end"] < state["start"]:
            state["end"] = state["start"]
        state["trimmed"] = True; redraw()

    def set_end(_e=None):
        state["end"] = state["i"]
        if state["start"] > state["end"]:
            state["start"] = state["end"]
        state["trimmed"] = True; redraw()

    def keep_all(_e=None):
        state["start"], state["end"], state["trimmed"] = 0, n - 1, False
        plt.close(fig)

    def use_interval(_e=None):
        plt.close(fig)

    b_start = Button(fig.add_axes([0.15, 0.04, 0.14, 0.055]), "Set start")
    b_end = Button(fig.add_axes([0.31, 0.04, 0.14, 0.055]), "Set end")
    b_all = Button(fig.add_axes([0.55, 0.04, 0.17, 0.055]), "Keep all frames")
    b_use = Button(fig.add_axes([0.74, 0.04, 0.20, 0.055]), "Use this interval")
    b_start.on_clicked(set_start); b_end.on_clicked(set_end)
    b_all.on_clicked(keep_all); b_use.on_clicked(use_interval)
    # Keep references alive so the buttons keep working (matplotlib weakrefs).
    fig._interval_widgets = (slider, b_start, b_end, b_all, b_use)

    def on_key(e):
        cur = int(round(slider.val))
        if e.key == "right":
            slider.set_val(min(n, cur + 1))
        elif e.key == "left":
            slider.set_val(max(1, cur - 1))
        elif e.key == "pagedown":
            slider.set_val(min(n, cur + 10))
        elif e.key == "pageup":
            slider.set_val(max(1, cur - 10))
        elif e.key == "home":
            slider.set_val(1)
        elif e.key == "end":
            slider.set_val(n)
    fig.canvas.mpl_connect("key_press_event", on_key)

    redraw()
    plt.show()
    if not state["trimmed"] or (state["start"] == 0 and state["end"] == n - 1):
        return None
    return (state["start"], state["end"])


class _TimeRangedExclusion:
    """Per-frame exclusion mask assembled from time-ranged focus/exclude regions.

    ``DICWormTracker`` indexes ``exclusion_masks[i]`` for every frame ``i``.  Each
    region carries an inclusive 0-based ``[start, end]`` frame range; for a given
    frame the excluded area is the union of the exclude regions active then, plus
    everything OUTSIDE the union of the focus regions active then.  Masks are
    built on demand with a small cache, so a long movie needs no per-frame array
    stored up front.  A region active for the whole movie behaves exactly like a
    static mask.
    """
    def __init__(self, shape_hw, n_frames, focus_regions, exclude_regions):
        self._shape = tuple(int(v) for v in shape_hw)
        self._n = int(n_frames)
        self._focus = list(focus_regions)      # (inside_mask, start, end)
        self._exclude = list(exclude_regions)  # (mask, start, end)
        self._cache = {}

    def __len__(self):
        return self._n

    def __getitem__(self, index):
        i = int(index)
        cached = self._cache.get(i)
        if cached is not None:
            return cached
        excluded = np.zeros(self._shape, dtype=bool)
        active_focus = [m for (m, s, e) in self._focus if s <= i <= e]
        if active_focus:
            inside = np.zeros(self._shape, dtype=bool)
            for m in active_focus:
                inside |= m
            excluded |= ~inside
        for (m, s, e) in self._exclude:
            if s <= i <= e:
                excluded |= m
        if len(self._cache) > 48:
            self._cache.clear()
        self._cache[i] = excluded
        return excluded


class _FrameWindow:
    """0-based view of frames [start, end] (inclusive) of a larger stack.

    Lets the tracker analyse only part of a recording (skip a noisy lead-in or
    tail) without copying the movie.  Exposes the small surface the tracker uses:
    ``shape``, ``len``, integer/slice ``__getitem__``, and ``is_virtual_stack``.
    Only used for disk-backed stacks; an in-memory array is sliced directly.
    """
    def __init__(self, base, start, end):
        self._base = base
        self._start = int(start)
        self._n = int(end) - int(start) + 1
        h, w = int(base.shape[1]), int(base.shape[2])
        self.shape = (self._n, h, w)
        self.is_virtual_stack = getattr(base, "is_virtual_stack", False)

    def __len__(self):
        return self._n

    def __getitem__(self, index):
        if isinstance(index, slice):
            rng = range(*index.indices(self._n))
            return np.stack(
                [np.asarray(self._base[self._start + k]) for k in rng])
        idx = int(index)
        if idx < 0:
            idx += self._n
        return self._base[self._start + idx]


def _guidance_exclusion(G, plt, messagebox):
    """Optionally focus the worm search and/or exclude problem areas.

    Returns a per-frame exclusion sequence for ``DICWormTracker`` (consumed by
    its existing ``exclusion_masks`` parameter), or ``None`` to leave tracking
    exactly as before.  A focus region is applied by excluding everything
    OUTSIDE it; exclude regions are unioned in.  All masks are built in
    cropped-frame pixel coordinates, matching ``tracker.G``, by drawing on the
    already-cropped first frame ``G[0]``.
    """
    if not messagebox.askyesno(
            "Optional: focus or exclude regions",
            "Guide the worm search on this recording?\n\n"
            "You can draw ONE focus region (the search ignores everything "
            "outside it) and/or one or more exclude regions (debris, plate "
            "edge, other animals, bubbles).\n\n"
            "Choose No to track the full working region as before."):
        return None
    try:
        from roi_editor import draw_roi, draw_rois
        from skimage.draw import polygon2mask
        from tkinter import simpledialog
    except Exception as exc:
        messagebox.showwarning(
            "Guidance unavailable",
            f"Could not open the ROI editor ({exc}). Tracking the full "
            "working region instead.")
        return None
    shape_hw = tuple(int(v) for v in G.shape[1:])
    frame0 = np.asarray(G[0], dtype=np.float32)
    # Let the user scroll the whole recording while placing ROIs, so they can
    # see everywhere the worm travels before committing a focus/exclude region.
    n_frames = int(G.shape[0])

    def _loader(index):
        return np.asarray(G[int(index)], dtype=np.float32)

    focus_regions = []    # (inside_mask, start, end)
    exclude_regions = []  # (mask, start, end)

    focus = draw_roi(
        frame0,
        "OPTIONAL focus region: scroll the movie (Frame slider / < >) to see "
        "everywhere the worm travels, then draw around all of it.\n"
        "The search ignores everything OUTSIDE this shape.  "
        "Use full frame or Cancel to skip focusing.",
        allow_line=False, default_shape="Rectangle", allow_full_frame=True,
        frame_count=n_frames, frame_loader=_loader)
    if focus is not None and focus.get("shape") != "full_frame":
        verts = focus.get("polygon") or []
        if len(verts) >= 3:
            inside = polygon2mask(
                shape_hw, np.array([(y, x) for (x, y) in verts]))
            focus_regions.append((inside, 0, n_frames - 1))

    rois = draw_rois(
        frame0,
        "OPTIONAL exclude regions: scroll the movie to find problem areas "
        "(debris, plate edge, another animal, bubble); draw each and click Add "
        "ROI, then Finish.  You will set the frames each region applies to next. "
        "If you have none, click 'Finish / none' or Cancel.",
        allow_line=False, default_shape="Polygon", label_prefix="Exclude",
        allow_empty=True, frame_count=n_frames, frame_loader=_loader)
    if rois:
        for idx, record in enumerate(rois, 1):
            verts = record.get("polygon") or []
            if len(verts) < 3:
                continue
            region = polygon2mask(
                shape_hw, np.array([(y, x) for (x, y) in verts]))
            answer = simpledialog.askstring(
                f"Exclude region {idx}: active frames",
                f"Frames (1-{n_frames}) where exclude region {idx} should be "
                f"applied.\n\nExamples: '1-100', '250-{n_frames}', or leave "
                "blank for the whole movie.")
            start, end = _parse_frame_range(answer, n_frames)
            exclude_regions.append((region, start, end))

    if not focus_regions and not exclude_regions:
        return None
    guidance = _TimeRangedExclusion(
        shape_hw, n_frames, focus_regions, exclude_regions)
    # Reject a nonsensical setup where even the least-excluded frame hides the
    # whole image (e.g. a tiny focus region), rather than tracking nothing.
    step = max(1, n_frames // 8)
    coverages = [float(guidance[j].mean()) for j in range(0, n_frames, step)]
    if coverages and min(coverages) >= 0.99:
        messagebox.showwarning(
            "Everything excluded",
            "The focus/exclude regions would hide the whole frame on every "
            "sampled frame, so they were ignored. Tracking the full working "
            "region instead.")
        return None
    summary = []
    if focus_regions:
        summary.append("focus region (whole movie)")
    for idx, (_m, s, e) in enumerate(exclude_regions, 1):
        span = ("whole movie" if (s == 0 and e == n_frames - 1)
                else f"frames {s + 1}-{e + 1}")
        summary.append(f"exclude {idx}: {span}")
    messagebox.showinfo(
        "Search guidance applied",
        "Applied to tracking and any re-tracking:\n- " + "\n- ".join(summary))
    return guidance


def _setup_dialog(root, default_worm_id, default_ignore_border=False):
    """One consolidated setup form for assay mode, scale, and options.

    Replaces the old chain of ``simpledialog``/``askyesno`` pop-ups with a single
    window: assay mode is a drop-down, the rest are fields with sensible
    defaults, and the two acceleration options are check-boxes.  Returns a dict
    of validated values, or ``None`` if cancelled.
    """
    import tkinter as tk
    from tkinter import ttk, messagebox
    dlg = tk.Toplevel(root)
    dlg.title("Track one worm - setup")
    dlg.resizable(False, False)
    result = {"ok": False}

    assay = tk.StringVar(value="crawling")
    fps = tk.StringVar(value="30.0")
    scale = tk.StringVar(value="1.0")
    worm_id = tk.StringVar(value=str(default_worm_id) or "worm")
    exposure = tk.StringVar(value="5.0")
    reg_proxy = tk.BooleanVar(value=True)
    adaptive_bg = tk.BooleanVar(value=True)
    ignore_border = tk.BooleanVar(value=bool(default_ignore_border))

    frm = ttk.Frame(dlg, padding=14)
    frm.pack(fill="both", expand=True)
    frm.grid_columnconfigure(1, weight=1)
    ttk.Label(frm, text="Track one worm - recording setup",
              font=("Segoe UI", 12, "bold")).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

    def field(r, label, widget):
        ttk.Label(frm, text=label).grid(
            row=r, column=0, sticky="w", pady=4, padx=(0, 12))
        widget.grid(row=r, column=1, sticky="ew", pady=4)

    field(1, "Assay mode", ttk.Combobox(
        frm, textvariable=assay, state="readonly", width=18,
        values=["crawling", "swimming", "burrowing"]))
    field(2, "Frames per second", ttk.Entry(frm, textvariable=fps, width=20))
    field(3, "Micrometres per pixel", ttk.Entry(frm, textvariable=scale, width=20))

    def _calibrate():
        try:
            from scale_calibration_ui import ask_scale
        except Exception as exc:
            messagebox.showerror("Scale calibration", str(exc), parent=dlg)
            return
        try:
            current = float(scale.get())
        except (TypeError, ValueError):
            current = None
        res = ask_scale(dlg, frame=None, initial_um_per_px=current,
                        title="Scale & magnification")
        if res:
            scale.set(f"{res['um_per_px']:.5f}")
        try:
            dlg.grab_set()  # restore this dialog's modality after the nested one
        except Exception:
            pass

    ttk.Button(frm, text="Calibrate...", command=_calibrate).grid(
        row=3, column=2, sticky="w", padx=(8, 0), pady=4)
    field(4, "Worm ID", ttk.Entry(frm, textvariable=worm_id, width=20))
    field(5, "Exposure (ms)", ttk.Entry(frm, textvariable=exposure, width=20))
    ttk.Checkbutton(
        frm, text="Low-res proxy for camera registration (faster)",
        variable=reg_proxy).grid(row=6, column=0, columnspan=2, sticky="w",
                                 pady=(8, 2))
    ttk.Checkbutton(
        frm, text="Adaptive background sampling (off for a full comparison run)",
        variable=adaptive_bg).grid(row=7, column=0, columnspan=2, sticky="w",
                                   pady=2)
    ttk.Checkbutton(
        frm, text="Ignore large objects touching the frame edge (probe / pick)",
        variable=ignore_border).grid(row=8, column=0, columnspan=2, sticky="w",
                                     pady=2)
    ttk.Label(frm, text="Scale must be > 0. Click Calibrate... to compute it "
                        "from the scope, zoom, and camera, or measure it with a "
                        "scale bar; a stage micrometer is the authority.",
              foreground="#666666", wraplength=420).grid(
        row=9, column=0, columnspan=3, sticky="w", pady=(8, 6))

    def submit(_event=None):
        try:
            f = float(fps.get()); s = float(scale.get()); e = float(exposure.get())
        except ValueError:
            messagebox.showerror(
                "Invalid number",
                "Frames per second, scale, and exposure must be numbers.",
                parent=dlg)
            return
        if not (f > 0 and s > 0 and e > 0):
            messagebox.showerror(
                "Invalid value",
                "Frames per second, scale, and exposure must each be greater "
                "than zero.", parent=dlg)
            return
        result.update({
            "ok": True, "assay_mode": assay.get().strip().lower(),
            "fps": f, "um_per_px": s,
            "worm_id": worm_id.get().strip() or "worm", "exposure_ms": e,
            "registration_proxy": bool(reg_proxy.get()),
            "adaptive_background_sampling": bool(adaptive_bg.get()),
            "ignore_border_objects": bool(ignore_border.get())})
        dlg.destroy()

    btns = ttk.Frame(frm)
    btns.grid(row=10, column=0, columnspan=2, sticky="e", pady=(12, 0))
    ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="right", padx=4)
    ttk.Button(btns, text="Start", command=submit).pack(side="right", padx=4)

    dlg.bind("<Return>", submit)
    # Mirror tkinter.simpledialog.Dialog exactly: only make the dialog transient
    # to the parent when the parent is actually viewable.  The launcher root is
    # withdraw()n, so making the dialog transient to it would leave the dialog
    # invisible on Windows and hang the whole tool on wait_window (the symptom:
    # "click a file and nothing happens").  Skipping transient, then explicitly
    # deiconifying and grabbing, is the supported pattern.
    try:
        if root.winfo_viewable():
            dlg.transient(root)
    except Exception:
        pass
    try:
        dlg.update_idletasks()
        dlg.geometry(f"+{max(0, root.winfo_screenwidth() // 2 - 220)}+"
                     f"{max(0, root.winfo_screenheight() // 4)}")
    except Exception:
        pass
    try:
        dlg.deiconify()
        dlg.lift()
        dlg.update()  # map the window so it is visible and grab_set has a target
        dlg.grab_set()
    except Exception:
        pass
    try:
        dlg.focus_force()
    except Exception:
        pass
    root.wait_window(dlg)
    return result if result["ok"] else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source", nargs="?",
        help="Movie, TIFF stack, or one frame from a numbered image series.")
    # THE RANGE MUST BE INHERITED, NOT RE-ENTERED. A caller that has already
    # committed a frame range - the single-channel GCaMP tool does - used to
    # hand over only the recording path, so the range was chosen again here
    # with a slider. A slider cannot reliably land on an exact frame, and the
    # saved review state is indexed per frame, so "close enough" is a
    # mismatch. Passing the range removes the reproduction problem entirely.
    parser.add_argument(
        "--frame-start", type=int, default=None,
        help="First frame to analyse, 1-based inclusive. Given with "
             "--frame-end, the interval chooser is skipped and this exact "
             "range is used.")
    parser.add_argument(
        "--frame-end", type=int, default=None,
        help="Last frame to analyse, 1-based inclusive.")
    parser.add_argument(
        "--ignore-border-objects", action="store_true",
        help="Default the 'ignore large objects touching the frame edge' option "
             "on (used by the mechanosensation module, where a probe/pick "
             "enters the frame).")
    args = parser.parse_args(argv)
    import tkinter as tk
    from tkinter import filedialog, simpledialog, messagebox
    import matplotlib; matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    # The reviewer binds single letters (f=fix, s=finalize, g=segmentation,
    # c=close interval) and the arrow keys, which Matplotlib ALSO binds by
    # default (f=fullscreen, s=save, g=grid, left/c=back, right=forward).  Left
    # in place, pressing f both fixes the frame AND toggles fullscreen, blowing
    # the window up.  Clear the clashing default key maps for this tool.
    for _km in ("keymap.fullscreen", "keymap.save", "keymap.grid",
                "keymap.grid_minor", "keymap.back", "keymap.forward",
                "keymap.xscale", "keymap.yscale"):
        try:
            plt.rcParams[_km] = []
        except Exception:
            pass
    import worm_dic_tracker
    from segmentation_review import find_accepted_config

    root = tk.Tk(); root.withdraw()
    # A withdrawn root does not claim the Windows foreground, so its file dialog
    # and message boxes can open BEHIND the launching hub. Marking the root
    # topmost makes the dialogs it parents come to the front.
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    path = args.source or filedialog.askopenfilename(
        parent=root,
        title="Choose a movie or TIFF stack, or any one image of a numbered sequence",
        filetypes=[("Movies, stacks and images", "*.avi *.mp4 *.mov *.mkv *.tif *.tiff *.jpg *.jpeg *.png"),
                   ("All files", "*.*")])
    if not path: return
    # Validate every user-entered constant before paying the movie-load cost.
    setup = _setup_dialog(root, Path(path).stem,
                          default_ignore_border=bool(args.ignore_border_objects))
    if setup is None:
        return
    assay_mode = setup["assay_mode"]
    fps = setup["fps"]
    um_per_px = setup["um_per_px"]
    worm_id = setup["worm_id"]
    exposure_ms = setup["exposure_ms"]
    performance_options = {
        "registration_proxy": setup["registration_proxy"],
        "adaptive_background_sampling": setup["adaptive_background_sampling"]}
    run_started=time.perf_counter();timings={}
    try:
        import movie_reader
        from roi_editor import draw_roi
        preview_movie=movie_reader.open_movie(path);first=preview_movie.get_frame(0)
        full_h,full_w=first.shape[:2];total_frames=int(preview_movie.n_frames);preview_movie.close()
        estimated_full=total_frames*full_h*full_w*4
        crop=(0,0,full_w,full_h)
        if estimated_full>2_000_000_000:
            shown=(np.add.reduce(first[...,:3],axis=2,dtype=np.float32)/np.float32(3)
                   if first.ndim==3 else first)
            record=None
            while record is None:
                record=draw_roi(shown,
                    "OPTIONAL working region: draw around the worm and all expected movement\n"
                    "Accept ROI commits it; Use full frame skips cropping; Cancel returns here without reloading.",
                    allow_line=False,default_shape="Rectangle",allow_full_frame=True)
                if record is None and not messagebox.askyesno(
                        "Working region not accepted",
                        "The ROI window was canceled. Reopen it?\n\nChoose No to continue with the full frame; the loaded movie will not be discarded."):
                    record={"shape":"full_frame","geometry":{"x0":0,"y0":0,"x1":full_w-1,"y1":full_h-1}}
            g=record["geometry"];margin=24
            x0=max(0,int(np.floor(min(g["x0"],g["x1"])-margin)));y0=max(0,int(np.floor(min(g["y0"],g["y1"])-margin)))
            x1=min(full_w,int(np.ceil(max(g["x0"],g["x1"])+margin)));y1=min(full_h,int(np.ceil(max(g["y0"],g["y1"])+margin)))
            crop=(x0,y0,x1,y1);estimated_crop=total_frames*(y1-y0)*(x1-x0)*4
        selected_estimate=total_frames*(crop[3]-crop[1])*(crop[2]-crop[0])*4
        if selected_estimate>2_000_000_000:
            messagebox.showinfo("Using virtual stack",
                f"This selection would require {selected_estimate/2**30:.1f} GiB as a float array. WINK will use a temporary disk-backed stack instead. "
                "Loading may take a few minutes; RAM remains bounded and the temporary file is removed on exit.")
        phase=time.perf_counter();G, note = _load_gray(path,crop=crop)
        timings["movie_decode_and_load_s"]=time.perf_counter()-phase
    except Exception as e:
        messagebox.showerror("Load failed", str(e)); return
    if G.shape[0] < 3:
        messagebox.showerror("Too few frames",
            f"Only {G.shape[0]} frame(s) found.\n\n"
            "For a folder of single images, click any one of the numbered images and\n"
            "the whole sequence in that folder is read. Check that the folder holds\n"
            "the image series (and not just this one file).")
        return

    # W5: optional partial-interval analysis -- keep only a frame range so a
    # noisy lead-in or tail can be skipped.  Everything downstream (ROI guidance,
    # tracking, review) then operates on this window; the note records which
    # original frames were analysed.
    total_loaded = int(G.shape[0])
    inherited = _inherited_interval(args, total_loaded, messagebox)
    if inherited is not None:
        # A range was handed over by the caller. Do NOT ask again - asking is
        # what created the mismatch this fixes.
        interval = inherited
        note = ((note + "; ") if note else "") + \
            f"analysis interval {inherited[0] + 1}-{inherited[1] + 1} " \
            f"inherited from the calling tool"
    else:
        interval = _choose_analysis_interval(G, plt)
    if interval is None:
        a_start, a_end = 0, total_loaded - 1
    else:
        a_start, a_end = interval
    if a_start > 0 or a_end < total_loaded - 1:
        if getattr(G, "is_virtual_stack", False):
            G = _FrameWindow(G, a_start, a_end)
        else:
            G = G[a_start:a_end + 1]
        if int(G.shape[0]) < 3:
            messagebox.showerror(
                "Interval too short",
                "Choose an analysis interval of at least 3 frames.")
            return
        note = ((note + "; ") if note else "") + \
            f"analysing frames {a_start + 1}-{a_end + 1} of {total_loaded}"

    exclusion_masks = _guidance_exclusion(G, plt, messagebox)
    segmentation_config = find_accepted_config(path, "track_one_worm")
    tr = worm_dic_tracker.DICWormTracker(
        G, fps=fps, um_per_px=um_per_px, worm_id=worm_id,
        assay_mode=assay_mode,
        fps_source="declared",
        um_per_px_source="declared",
        exposure_ms=exposure_ms,
        exposure_source="declared",
        exclusion_masks=exclusion_masks,
        ignore_border_objects=setup.get("ignore_border_objects", False),
        segmentation_config=segmentation_config,**performance_options)
    timings.update(tr.timings)
    recording_key, source, session_path = _recording_context(path,len(G),crop=crop)
    # A saved session that does not fit is a reason to ignore it, not to end
    # the tool. This used to be `showerror(...); return`, which quit outright
    # while a fresh start was available the whole time.
    resumed = resume_or_start_fresh(
        session_path, tr, tool="single_worm_tracker", source=source,
        confirm=lambda title, message: messagebox.askyesno(title, message),
        inform=lambda title, message: messagebox.showinfo(title, message))
    if not resumed:
        head, outline = _seed(G, plt)
        if head is None:
            messagebox.showerror("Seeding", "Need a head click."); return
        # A WINDOW EXISTS FOR THE WHOLE COMPUTATION. The seeding figure was
        # closed just above and the review figure is not built until below,
        # so without this there is nothing on screen for minutes.
        watcher = _ProgressWindow(plt, tr.T, title="Tracking the worm")
        try:
            tr.track_all(head_seed=head, outline_mask=outline,
                         progress=watcher)
        finally:
            watcher.close()
        timings.update(tr.timings)
        save_tracker_session(
            session_path, tr, tool="single_worm_tracker", source=source)

    nh = sum(1 for s in tr.state if s["needs_help"])
    messagebox.showinfo("Review",
        f"Loaded {tr.T} frames{(' - ' + note) if note else ''}.\n"
        f"Assay mode: {assay_mode}.\n"
        f"Tracked into {tr.n_segments} body segments.\n"
        f"Detected {len(tr.reference['clip_starts'])} clip(s); each new clip is flagged "
        "for a fresh head assignment.\n"
        f"Reference length {tr.reference['length_px']:.0f}px.  Flagged for review: {nh}\n"
        f"Supervised segmentation map: "
        f"{'accepted and applied' if segmentation_config else 'not supplied; original detector used'}.\n\n"
        + (
            "Swimming mode: apparent length loss is a blur or truncation warning. "
            "Signed curvature remains available for frequency and wave analysis.\n\n"
            if assay_mode == "swimming" else
            "Burrowing mode: only visible intervals are measured. Occluded frames "
            "remain missing and require review.\n\n"
            if assay_mode == "burrowing" else
            "Crawling mode: existing lawn-tracking behavior and QC are preserved.\n\n"
        ) +
        "The review window supports interval reanalysis: b marks the beginning and e the end.\n"
        "Use f to correct/add an anchor, w to save progress, q/close to save and exit,\n"
        "or s to finalize the CSV. Saved sessions can be resumed later.")
    reviewer = Reviewer(tr, G, plt, session_path, source)
    reviewer.run()

    if not reviewer.finalized:
        messagebox.showinfo(
            "Progress saved",
            f"Review progress was saved without finalizing a CSV.\n\n{session_path}\n\n"
            "Launch the tracker and select any frame from this recording to resume.")
        if getattr(G,"is_virtual_stack",False):G.close()
        return

    export_started=time.perf_counter();rows = tr.export_rows()
    x0,y0,_,_=crop
    for row in rows:
        for key in ("seg_x","head_x","tail_x","centroid_x"):
            if row.get(key)==row.get(key):row[key]+=x0
        for key in ("seg_y","head_y","tail_y","centroid_y"):
            if row.get(key)==row.get(key):row[key]+=y0
        row["analysis_crop_x0_px"]=x0;row["analysis_crop_y0_px"]=y0
    stamp = datetime.date.today().strftime("%Y%m%d")
    out_csv = Path(path).with_name(
        f"{recording_key}_{assay_mode}_kinematics_{stamp}.csv")
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    timings["measurement_and_export_s"]=time.perf_counter()-export_started
    timings["processing_total_excluding_manual_review_s"]=sum(v for k,v in timings.items() if k!="tracker_initialization_s")
    timings["wall_clock_total_including_manual_review_s"]=time.perf_counter()-run_started
    timing_path=out_csv.with_name(out_csv.stem+"_timing.json")
    timing_path.write_text(json.dumps({"tool":"dic_single_worm_tracker","source":str(Path(path).resolve()),
        "performance_options":performance_options,"crop_xyxy":list(crop),
        "timings_seconds":{k:round(float(v),4) for k,v in timings.items()}},indent=2),encoding="utf-8")

    nh = sum(1 for s in tr.state if s["needs_help"])
    messagebox.showinfo("Saved",
        f"{len(rows)} rows ({tr.T} frames x {tr.n_segments} segments)\n"
        f"Frames still flagged: {nh}\nProcessing time: {timings['processing_total_excluding_manual_review_s']:.1f} s\n\nSaved:\n{out_csv.name}\n{timing_path.name}\n\n"
        "Next: run the kinematics analysis on this CSV\n"
        "(Lab Tools hub > Analyse one worm's kinematics).")
    if getattr(G,"is_virtual_stack",False):G.close()
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
            r = tk.Tk(); r.withdraw()
            messagebox.showerror("DIC tracker error", traceback.format_exc()[-1500:]); r.destroy()
        except Exception: pass
