"""Student-facing T1 mechanosensation/habituation track-table workflow."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "app")]

from acquisition import AcquisitionMetadata
from capability_gate import (
    MetricRequirement, RecordingProxies, evaluate_metric)
from failure_library import FailureLibrary
from mechanosensation import (
    TOOL_NAME, TOOL_VERSION, TrialRecord, analyze_habituation)
from reversal_core import ReversalEvent, score_stimulus
from run_feedback import RunFeedbackStore, prompt_post_run_feedback

REQUIRED_COLUMNS = {
    "plate_id", "worm_id", "stimulus_id", "time_s", "velocity_bl_s",
    "stimulus_time_s", "prior_state", "trial_number", "front_end",
}


import numpy as np


def _finite(series):
    if series is None:
        return np.empty(0, dtype=float)
    v = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    return v[np.isfinite(v)]


def _safe_mean(series):
    v = _finite(series)
    return float(np.mean(v)) if v.size else float("nan")


def _robust_amplitude(series):
    """Head-bend amplitude = robust peak-to-peak (95th - 5th percentile, deg)."""
    v = _finite(series)
    if v.size < 2:
        return float("nan")
    return float(np.percentile(v, 95) - np.percentile(v, 5))


def _path_tortuosity(cx, cy):
    """Spine-independent 'quirkiness' fallback: centroid path length / net
    displacement over the window (1 = straight, higher = wigglier)."""
    x = pd.to_numeric(cx, errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(cy, errors="coerce").to_numpy(dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if x.size < 2:
        return float("nan")
    path = float(np.sum(np.hypot(np.diff(x), np.diff(y))))
    net = float(np.hypot(x[-1] - x[0], y[-1] - y[0]))
    if net <= 1e-9:
        return float("nan")
    return path / net


def _box_aspect_ratio(seg_x, seg_y):
    """Tierpsy-style quirkiness for ONE frame: major/minor axis ratio of the
    worm's oriented bounding box, from the spine points via PCA (straight worm
    -> large, coiled worm -> near 1)."""
    x = pd.to_numeric(seg_x, errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(seg_y, errors="coerce").to_numpy(dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if x.size < 3:
        return float("nan")
    cov = np.cov(np.column_stack([x, y]), rowvar=False)
    vals = np.clip(np.linalg.eigvalsh(cov), 0, None)  # ascending: [minor, major]
    if vals[0] <= 1e-9:
        return float("nan")
    return float(np.sqrt(vals[1] / vals[0]))


def reversal_window_metrics(table, before_s=3.0, response_s=5.0, after_s=3.0):
    """Per-trial before/during/after descriptive metrics.

    Additive and independent of the reversal scoring: returns one row per trial
    with mean crawling velocity, head-bend amplitude, Tierpsy-style quirkiness
    (box aspect ratio), and path tortuosity in the pre-stimulus (before), the
    response (during), and the post (after) windows, plus response-minus-baseline
    changes.  Missing columns degrade gracefully to NaN.
    """
    keys = ["plate_id", "worm_id", "stimulus_id"]
    have_bend = "head_bend_deg" in table.columns
    have_quirk = "quirkiness" in table.columns
    have_centroid = {"centroid_x", "centroid_y"}.issubset(table.columns)
    rows = []
    for _, g in table.groupby(keys, sort=False):
        first = g.iloc[0]
        t0 = float(first["stimulus_time_s"])
        tt = pd.to_numeric(g["time_s"], errors="coerce").to_numpy(dtype=float)

        def window(lo, hi):
            return g[(tt >= t0 + lo) & (tt < t0 + hi)]

        row = {
            "plate_id": first["plate_id"], "worm_id": first["worm_id"],
            "stimulus_id": first["stimulus_id"],
            "trial_number": (int(first["trial_number"])
                             if "trial_number" in g else None),
            "stimulus_time_s": t0,
            "front_end": first.get("front_end", ""),
            "stimulus_location": first.get("stimulus_location", ""),
            "design": first.get("design", ""),
        }
        wins = {}
        for name, (lo, hi) in (("before", (-before_s, 0.0)),
                               ("during", (0.0, response_s)),
                               ("after", (response_s, response_s + after_s))):
            w = window(lo, hi)
            wins[name] = w
            row[f"mean_velocity_bl_s_{name}"] = _safe_mean(w.get("velocity_bl_s"))
            row[f"head_bend_amplitude_deg_{name}"] = (
                _robust_amplitude(w["head_bend_deg"]) if have_bend
                else float("nan"))
            row[f"quirkiness_box_ratio_{name}"] = (
                _safe_mean(w.get("quirkiness")) if have_quirk else float("nan"))
            row[f"path_tortuosity_{name}"] = (
                _path_tortuosity(w.get("centroid_x"), w.get("centroid_y"))
                if have_centroid else float("nan"))
        # Stop vs reverse: a response can be a pause WITHOUT a reversal.  Flag
        # whether the animal actually reversed in the response window, and
        # whether it merely slowed/stopped (dropped below half its pre-stimulus
        # forward speed) without going backward.
        rev_thr = 0.05
        during_v = _finite(wins["during"].get("velocity_bl_s"))
        before_v = _finite(wins["before"].get("velocity_bl_s"))
        min_during = float(np.min(during_v)) if during_v.size else float("nan")
        reversed_during = bool(during_v.size and min_during <= -rev_thr)
        base_fwd = float(np.mean(before_v)) if before_v.size else float("nan")
        mean_during = row["mean_velocity_bl_s_during"]
        row["min_velocity_bl_s_during"] = min_during
        row["reversed_during"] = reversed_during
        row["stopped_not_reversed"] = bool(
            (not reversed_during) and np.isfinite(base_fwd)
            and base_fwd > rev_thr and np.isfinite(mean_during)
            and mean_during < 0.5 * base_fwd)
        row["velocity_change_during_minus_before"] = (
            row["mean_velocity_bl_s_during"] - row["mean_velocity_bl_s_before"])
        row["head_bend_amplitude_change_during_minus_before"] = (
            row["head_bend_amplitude_deg_during"]
            - row["head_bend_amplitude_deg_before"])
        rows.append(row)
    return pd.DataFrame(rows)


def _load_track_frames(path):
    """Load a Track-one-worm export as a per-frame table with signed centroid
    velocity (body lengths/s) and, when the spine was exported, per-frame
    quirkiness.  Shared by the stimulus-aligned and spontaneous paths."""
    raw = pd.read_csv(path)
    required = {
        "worm_id", "frame", "time_s", "centroid_x", "centroid_y",
        "head_x", "head_y", "tail_x", "tail_y", "body_length_px",
    }
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ValueError(
            "The CSV is neither a stimulus table nor a Track one worm export. "
            "Missing tracking columns: " + ", ".join(missing))
    frames = raw.sort_values("time_s").groupby("frame", as_index=False).first()
    for column in required - {"worm_id"}:
        frames[column] = pd.to_numeric(frames[column], errors="coerce")
    dt = frames.time_s.diff().to_numpy()
    dx = frames.centroid_x.diff().to_numpy()
    dy = frames.centroid_y.diff().to_numpy()
    hx = (frames.head_x - frames.tail_x).to_numpy()
    hy = (frames.head_y - frames.tail_y).to_numpy()
    norm = (hx * hx + hy * hy) ** .5
    frames["velocity_bl_s"] = (
        (dx * hx + dy * hy) / norm / dt / frames.body_length_px.to_numpy())
    if {"seg_x", "seg_y"}.issubset(raw.columns):
        quirk = (raw.groupby("frame")[["seg_x", "seg_y"]]
                 .apply(lambda g: _box_aspect_ratio(g["seg_x"], g["seg_y"]))
                 .rename("quirkiness").reset_index())
        frames = frames.merge(quirk, on="frame", how="left")
    return frames


def detect_spontaneous_reversals(times_s, velocity_bl_s, *,
                                 reversal_threshold_bl_s=0.05,
                                 min_reversal_s=0.25):
    """Find spontaneous reversals in a signed-velocity trace.

    A reversal is a run of backward motion (velocity below
    ``-reversal_threshold_bl_s``) lasting at least ``min_reversal_s``.  Returns a
    list of dicts with onset_s, peak_reverse_velocity_bl_s, duration_s, and
    reversal_length_bl.  Works from centroid-derived velocity, so it does not
    need clean spines.
    """
    t = np.asarray(times_s, dtype=float)
    v = np.asarray(velocity_bl_s, dtype=float)
    n = v.size
    thr = abs(reversal_threshold_bl_s)
    events = []
    i = 0
    while i < n:
        if np.isfinite(v[i]) and v[i] <= -thr:
            start = i
            j = i
            while j + 1 < n and (not np.isfinite(v[j + 1]) or v[j + 1] < 0):
                j += 1
            seg = np.array(
                [k for k in range(start, j + 1) if np.isfinite(v[k])])
            if seg.size >= 2:
                duration = float(t[seg[-1]] - t[seg[0]])
                if duration >= min_reversal_s:
                    dt = np.diff(t[seg], append=t[seg[-1]])
                    length = float(np.sum(np.maximum(0.0, -v[seg]) * dt))
                    events.append({
                        "onset_s": float(t[seg[0]]),
                        "peak_reverse_velocity_bl_s": float(np.max(-v[seg])),
                        "duration_s": duration,
                        "reversal_length_bl": length})
            i = j + 1
        else:
            i += 1
    return events


def track_export_to_trials(path, stimulus_times_s, plate_id, front_end,
                           blackout_s=0.0, stimulus_location="not_applicable",
                           design="single_trial"):
    """Convert a reviewed Track-one-worm export into the C1 trial schema.

    ``blackout_s`` (optional) marks the frames from each stimulus onset to
    ``onset + blackout_s`` as artifact frames, so the pick-in-view interval is
    excluded from scoring while latency stays anchored to the entered stimulus
    time.  ``stimulus_location`` (anterior/posterior) is carried through for
    harsh-touch trials, where posterior stimuli are expected to evoke a forward
    escape rather than a reversal.

    ``design`` controls how repeated stimuli are treated:
      * ``single_trial`` / ``habituation_series`` keep the SAME worm identity
        across stimuli (dependent trials on one animal: order and inter-stimulus
        interval are preserved so the response can be compared across trials);
      * ``sequential_independent`` assigns a DISTINCT worm identity per stimulus
        (independent animals stimulated one after another).
    """
    frames = _load_track_frames(path)
    rows = []
    previous = None
    for trial, onset in enumerate(stimulus_times_s, start=1):
        window = frames[
            (frames.time_s >= onset - 3) & (frames.time_s <= onset + 6)].copy()
        if len(window) < 2:
            raise ValueError(
                f"Stimulus {onset:g} s has fewer than two observable frames.")
        before = frames[frames.time_s < onset].tail(1)
        velocity = float(before.velocity_bl_s.iloc[0]) if len(before) else 0.0
        prior = "reversing" if velocity < -.05 else (
            "paused" if abs(velocity) < .02 else "forward")
        window["plate_id"] = str(plate_id)
        window["stimulus_id"] = f"stimulus_{trial}"
        window["stimulus_time_s"] = float(onset)
        window["prior_state"] = prior
        window["trial_number"] = trial
        window["front_end"] = front_end
        window["stimulus_location"] = str(stimulus_location)
        window["design"] = str(design)
        if design == "sequential_independent":
            # Each stimulus is a different animal: give it its own identity so
            # trials are treated as independent replicates, not a habituation
            # series on one worm.
            window["worm_id"] = f"worm_{trial}"
        if blackout_s and float(blackout_s) > 0:
            # Exclude the pick-in-view interval from scoring; latency stays
            # measured from the entered stimulus onset.
            window["artifact_frame"] = (
                (window.time_s >= onset) &
                (window.time_s < onset + float(blackout_s)))
        window["isi_s"] = None if previous is None else onset - previous
        rows.append(window)
        previous = onset
    return pd.concat(rows, ignore_index=True)


def load_track_table(path: str | Path) -> pd.DataFrame:
    table = pd.read_csv(path)
    missing = sorted(REQUIRED_COLUMNS - set(table.columns))
    if missing:
        raise ValueError("Track table is missing: " + ", ".join(missing))
    if table.empty:
        raise ValueError("Track table is empty.")
    return table


def propose_trials(table: pd.DataFrame) -> list[TrialRecord]:
    records = []
    keys = ["plate_id", "worm_id", "stimulus_id"]
    for (_, _, _), group in table.groupby(keys, sort=False):
        first = group.iloc[0]
        artifact = (
            group.index[group.get("artifact_frame", False).astype(bool)].tolist()
            if "artifact_frame" in group else [])
        # score_stimulus expects positions within this group, not dataframe labels.
        artifact = [
            index for index, value in enumerate(
                group.get("artifact_frame", pd.Series(False, index=group.index)))
            if bool(value)]
        event = score_stimulus(
            worm_id=str(first.worm_id), plate_id=str(first.plate_id),
            stimulus_id=str(first.stimulus_id),
            times_s=group.time_s.to_numpy(),
            signed_velocity_body_lengths_s=group.velocity_bl_s.to_numpy(),
            stimulus_time_s=float(first.stimulus_time_s),
            prior_state=str(first.prior_state),
            artifact_frame_indices=artifact)
        records.append(TrialRecord(
            str(first.plate_id), int(first.trial_number),
            None if "isi_s" not in group or pd.isna(first.get("isi_s"))
            else float(first.isi_s),
            event, str(first.front_end),
            None if "artifact_amplitude" not in group or pd.isna(
                first.get("artifact_amplitude"))
            else float(first.artifact_amplitude),
            str(first.get("phase", "habituation"))))
    return records


class ReviewDialog(tk.Toplevel):
    def __init__(self, parent, records):
        super().__init__(parent)
        self.title("Review proposed mechanosensory events")
        self.geometry("1120x570")
        self.records = list(records)
        self.accepted = False
        ttk.Label(
            self, text="Select rows and correct response or event type. "
                       "Already-reversing worms remain excluded.").pack(
                anchor="w", padx=10, pady=8)
        columns = (
            "index", "plate", "worm", "trial", "front", "prior",
            "response", "type", "latency", "length", "peak")
        self.tree = ttk.Treeview(
            self, columns=columns, show="headings", selectmode="extended")
        labels = (
            "#", "Plate", "Worm", "Trial", "Front end", "Prior state",
            "Response", "Event type", "Latency", "Length BL", "Peak BL/s")
        widths = (40, 75, 75, 50, 120, 85, 75, 125, 70, 75, 75)
        for column, label, width in zip(columns, labels, widths):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10)
        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=10, pady=8)
        for label, command in (
            ("Response: yes", lambda: self.set_response("yes")),
            ("Response: no", lambda: self.set_response("no")),
            ("Exclude", lambda: self.set_response("excluded")),
            ("Type: reversal", lambda: self.set_type("reversal")),
            ("Type: forward acceleration",
             lambda: self.set_type("forward_acceleration")),
        ):
            ttk.Button(controls, text=label, command=command).pack(
                side="left", padx=3)
        ttk.Button(
            controls, text="Accept reviewed table", command=self.finish).pack(
                side="right")
        self.refresh()
        self.transient(parent)
        self.grab_set()

    def refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, record in enumerate(self.records):
            event = record.event
            self.tree.insert("", "end", iid=str(index), values=(
                index, record.plate_id, event.worm_id, record.trial_number,
                record.stimulus_front_end, event.prior_state, event.response,
                event.event_type or "", event.latency_s,
                event.reversal_length_body_lengths,
                event.peak_reversal_velocity_body_lengths_s))

    def selected(self):
        return [int(item) for item in self.tree.selection()]

    def set_response(self, response):
        for index in self.selected():
            event = self.records[index].event
            if event.prior_state == "reversing" and response != "excluded":
                continue
            if response == "no":
                event = replace(
                    event, response="no", exclusion_reason=None,
                    event_type=None, latency_s=None,
                    reversal_length_body_lengths=0,
                    peak_reversal_velocity_body_lengths_s=0, duration_s=0)
            elif response == "excluded":
                event = replace(
                    event, response="excluded",
                    exclusion_reason="observer excluded after review",
                    event_type=None, latency_s=None,
                    reversal_length_body_lengths=None,
                    peak_reversal_velocity_body_lengths_s=None,
                    duration_s=None)
            else:
                event = replace(
                    event, response="yes", exclusion_reason=None,
                    event_type=event.event_type or "reversal")
            self.records[index] = replace(self.records[index], event=event)
        self.refresh()

    def set_type(self, event_type):
        for index in self.selected():
            event = self.records[index].event
            if event.response == "yes":
                self.records[index] = replace(
                    self.records[index],
                    event=replace(event, event_type=event_type))
        self.refresh()

    def finish(self):
        self.accepted = True
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Evoked mechanosensation with habituation")
        self.geometry("940x650")
        defaults = {
            "tracks": "", "baseline": "", "fps": "30", "scale": "4",
            "exposure": "2", "bit_depth": "12",
            "duration": "120", "worm_length": "1000", "plate": "plate_1",
            "stimulus_times": "10, 20, 30", "front_end": "nose_touch",
            "stimulus_location": "anterior", "blackout": "0",
            "design": "single_trial",
        }
        self.v = {key: tk.StringVar(value=value)
                  for key, value in defaults.items()}
        self.status = tk.StringVar(
            value="Step 1: track a movie (its kinematics load here "
                  "automatically). Or load an existing tracking CSV below.")
        # Drop-down choices for the category fields (blank values stay Entry).
        self._choices = {
            "design": ["single_trial", "habituation_series",
                       "sequential_independent", "spontaneous"],
            "front_end": ["nose_touch", "gentle_body_touch",
                          "harsh_body_touch", "population_tap"],
            "stimulus_location": ["anterior", "posterior", "not_applicable"],
        }
        fields = [
            ("Tracking CSV (auto-filled after tracking; or Choose)", "tracks"),
            ("Matched baseline CSV (optional)", "baseline"),
            ("Plate ID", "plate"),
            ("Design (single / habituation series / independent animals)",
             "design"),
            ("Stimulus times in seconds", "stimulus_times"),
            ("Stimulus type", "front_end"),
            ("Stimulus location (harsh touch only)", "stimulus_location"),
            ("Blackout window after stimulus (s, 0 = off)", "blackout"),
            ("FPS", "fps"), ("Scale (µm/pixel)", "scale"),
            ("Exposure (ms)", "exposure"), ("Bit depth", "bit_depth"),
            ("Recording duration (s)", "duration"),
            ("Expected worm length (µm)", "worm_length"),
        ]
        for row, (label, key) in enumerate(fields):
            ttk.Label(self, text=label).grid(
                row=row, column=0, padx=10, pady=7, sticky="w")
            if key in self._choices:
                ttk.Combobox(
                    self, textvariable=self.v[key], width=59,
                    state="readonly", values=self._choices[key]).grid(
                        row=row, column=1, padx=5, pady=7)
            else:
                ttk.Entry(self, textvariable=self.v[key], width=62).grid(
                    row=row, column=1, padx=5, pady=7)
            if key in {"tracks", "baseline"}:
                ttk.Button(
                    self, text="Choose",
                    command=lambda k=key: self.v[k].set(
                        filedialog.askopenfilename(
                            filetypes=[("CSV", "*.csv")]))).grid(
                                row=row, column=2, padx=8)
        action_row = len(fields)
        ttk.Button(self, text="1. Track a movie (auto-loads result)",
                   command=self.launch_tracker).grid(
            row=action_row, column=0, padx=12, pady=(12, 4), sticky="ew")
        ttk.Button(self, text="2. Mark stimuli on movie",
                   command=self.mark_stimuli).grid(
            row=action_row, column=1, columnspan=2, padx=12, pady=(12, 4),
            sticky="ew")
        ttk.Button(
            self, text="3. Propose, review, and analyze",
            command=self.run).grid(
                row=action_row + 1, column=0, columnspan=3, padx=12,
                pady=(4, 12), sticky="ew")
        ttk.Label(
            self, textvariable=self.status, wraplength=810).grid(
                row=action_row + 2, column=0, columnspan=3, padx=12, pady=12,
                sticky="w")

    def launch_tracker(self):
        """Track a movie, then auto-load the kinematics result (no manual CSV).

        Opens the single-worm DIC tracker on a chosen recording and, when it
        closes, fills the tracking field with the ``*_kinematics_*.csv`` it wrote
        next to the movie.  Manual CSV selection remains as a fallback below.
        """
        movie = filedialog.askopenfilename(
            title="Choose the recording to track (movie, TIFF stack, or one "
                  "image of a numbered sequence)",
            filetypes=[("Movies, stacks and images",
                        "*.avi *.mp4 *.mov *.mkv *.tif *.tiff *.jpg *.jpeg "
                        "*.png"),
                       ("All files", "*.*")])
        if not movie:
            return
        self._movie_path = movie
        self._track_folder = Path(movie).parent
        self._pre_track_csvs = set(self._track_folder.glob("*_kinematics_*.csv"))
        tracker = (ROOT / "tools" / "worm_kinematics" / "dic_tracker" /
                   "run_dic_kinematics.py")
        try:
            # Mechanosensation assays introduce a probe/pick that enters the
            # frame to touch the worm; default the border-object rejection on so
            # the tracker prefers the worm over that intruder.
            self._tracker_proc = subprocess.Popen(
                [sys.executable, str(tracker), movie, "--ignore-border-objects"])
        except Exception as exc:
            messagebox.showerror(
                "Tracker", f"Could not start the worm tracker.\n\n{exc}",
                parent=self)
            return
        self.status.set(
            "Tracking opened in the worm-tracker window: seed the head, review "
            "the spines, then Finalize (press s). The kinematics result will "
            "load here automatically when the tracker closes.")
        self.after(1500, self._poll_tracker)

    def _poll_tracker(self):
        proc = getattr(self, "_tracker_proc", None)
        if proc is None:
            return
        if proc.poll() is None:
            self.after(1500, self._poll_tracker)
            return
        folder = getattr(self, "_track_folder", None)
        if folder is None:
            return
        produced = sorted(
            folder.glob("*_kinematics_*.csv"), key=lambda p: p.stat().st_mtime)
        fresh = [c for c in produced
                 if c not in getattr(self, "_pre_track_csvs", set())]
        chosen = fresh or produced
        if not chosen:
            self.status.set(
                "No kinematics CSV was found next to the recording. If you "
                "finalized the track (press s), check the folder; otherwise "
                "load a CSV manually below.")
            return
        newest = chosen[-1]
        self.v["tracks"].set(str(newest))
        self.status.set(
            f"Loaded tracking result: {newest.name}. Set the stimulus times, "
            "then click 'Propose, review, and analyze'.")

    def mark_stimuli(self):
        """Scrub the movie and mark each stimulus frame; fills 'Stimulus times'."""
        movie = getattr(self, "_movie_path", "") or filedialog.askopenfilename(
            title="Choose the recording to mark stimuli on",
            filetypes=[("Movies, stacks and images",
                        "*.avi *.mp4 *.mov *.mkv *.tif *.tiff *.jpg *.jpeg "
                        "*.png"), ("All files", "*.*")])
        if not movie:
            return
        try:
            import matplotlib
            matplotlib.use("TkAgg")
            import matplotlib.pyplot as plt
            from matplotlib.widgets import Slider
            sys.path.insert(0, str(ROOT / "tools" / "movie"))
            import movie_reader
        except Exception as exc:
            messagebox.showerror(
                "Mark stimuli", f"Could not open the movie viewer.\n\n{exc}",
                parent=self)
            return
        try:
            fps = float(self.v["fps"].get())
        except ValueError:
            fps = 30.0
        fps = fps if fps > 0 else 30.0
        for km in ("keymap.fullscreen", "keymap.save", "keymap.grid",
                   "keymap.grid_minor", "keymap.back", "keymap.forward",
                   "keymap.home", "keymap.xscale", "keymap.yscale"):
            try:
                plt.rcParams[km] = []
            except Exception:
                pass
        m = movie_reader.open_movie(movie)
        nfr = int(m.n_frames)

        def gray(fr):
            fr = np.asarray(fr)
            return fr[..., :3].mean(axis=2) if fr.ndim == 3 else fr

        state = {"frame": 0, "marks": []}
        fig, ax = plt.subplots(figsize=(10, 7))
        fig.subplots_adjust(bottom=0.16)
        im = ax.imshow(gray(m.get_frame(0)), cmap="gray")
        ax.set_axis_off()
        slider_ax = fig.add_axes([0.13, 0.06, 0.74, 0.035])
        slider = Slider(slider_ax, "Frame", 0, max(1, nfr - 1),
                        valinit=0, valstep=1)

        def title():
            i = state["frame"]
            ts = ", ".join(f"{f/fps:.2f}" for f in sorted(set(state["marks"])))
            ax.set_title(
                f"Frame {i+1}/{nfr}  (t={i/fps:.2f}s)    m/space=mark, u=undo, "
                f"arrows=step, PgUp/PgDn=±10\nmarked (s): {ts or 'none'}",
                fontsize=9)

        def show(i):
            state["frame"] = int(max(0, min(nfr - 1, i)))
            im.set_data(gray(m.get_frame(state["frame"])))
            title()
            fig.canvas.draw_idle()

        def goto(i):
            slider.set_val(max(0, min(nfr - 1, int(i))))

        slider.on_changed(lambda v: show(int(round(v))))

        def on_key(e):
            if e.key in ("m", " "):
                state["marks"].append(state["frame"])
                title(); fig.canvas.draw_idle()
            elif e.key == "u" and state["marks"]:
                state["marks"].pop()
                title(); fig.canvas.draw_idle()
            elif e.key == "right":
                goto(state["frame"] + 1)
            elif e.key == "left":
                goto(state["frame"] - 1)
            elif e.key == "pagedown":
                goto(state["frame"] + 10)
            elif e.key == "pageup":
                goto(state["frame"] - 10)
        fig.canvas.mpl_connect("key_press_event", on_key)
        try:
            win = fig.canvas.manager.window
            win.wm_state("normal")
            sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
            ww, wh = min(1050, sw - 120), min(760, sh - 140)
            win.geometry(
                f"{ww}x{wh}+{max(0, (sw-ww)//2)}+{max(0, (sh-wh)//4)}")
        except Exception:
            pass
        title()
        plt.show()
        try:
            m.close()
        except Exception:
            pass
        times = sorted({round(f / fps, 3) for f in state["marks"]})
        if times:
            self.v["stimulus_times"].set(", ".join(str(t) for t in times))
            self.status.set(
                f"Marked {len(times)} stimulus time(s): "
                f"{', '.join(str(t) for t in times)} s.")

    def input_table(self, path):
        header = pd.read_csv(path, nrows=2)
        if REQUIRED_COLUMNS.issubset(header.columns):
            return load_track_table(path)
        times = [float(item.strip()) for item in
                 self.v["stimulus_times"].get().split(",") if item.strip()]
        if not times:
            raise ValueError("Enter at least one stimulus time in seconds.")
        try:
            blackout = float(self.v["blackout"].get() or 0)
        except ValueError:
            blackout = 0.0
        return track_export_to_trials(
            path, times, self.v["plate"].get(), self.v["front_end"].get(),
            blackout_s=blackout,
            stimulus_location=self.v["stimulus_location"].get(),
            design=self.v["design"].get())

    def acquisition(self):
        return AcquisitionMetadata(
            float(self.v["fps"].get()), "declared",
            float(self.v["scale"].get()), "declared",
            float(self.v["exposure"].get()), "declared",
            bit_depth=int(self.v["bit_depth"].get()),
            compression="unknown",
            recording_duration_s=float(self.v["duration"].get()),
            channel_identity="brightfield",
            anatomical_orientation="head_left",
            declared_worm_length_um=float(self.v["worm_length"].get()))

    def run_spontaneous(self):
        """Spontaneous design: no stimulus -- auto-detect every reversal."""
        try:
            path = Path(self.v["tracks"].get())
            if not path.exists():
                raise ValueError(
                    "Choose a tracking CSV (or track a movie first).")
            frames = _load_track_frames(str(path))
            events = detect_spontaneous_reversals(
                frames["time_s"].to_numpy(), frames["velocity_bl_s"].to_numpy())
            times = pd.to_numeric(frames["time_s"], errors="coerce").to_numpy()
            duration_s = float(np.nanmax(times) - np.nanmin(times))
            rate = (len(events) / duration_s * 60.0
                    if duration_s > 0 else float("nan"))
            output = path.parent / (path.stem + "_mechanosensation")
            output.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(events).to_csv(
                output / "spontaneous_reversals.csv", index=False)
            summary = {
                "design": "spontaneous",
                "recording_duration_s": duration_s,
                "reversal_count": len(events),
                "reversals_per_min": rate,
                "mean_reversal_duration_s": (
                    float(np.mean([e["duration_s"] for e in events]))
                    if events else None),
                "mean_peak_reverse_velocity_bl_s": (
                    float(np.mean([e["peak_reverse_velocity_bl_s"]
                                   for e in events])) if events else None),
                "mean_reversal_length_bl": (
                    float(np.mean([e["reversal_length_bl"] for e in events]))
                    if events else None),
            }
            (output / "spontaneous_summary.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8")
            self.status.set(
                f"Spontaneous reversals: {len(events)} "
                f"({rate:.2f}/min). Saved: {output}")
            messagebox.showinfo(
                "Spontaneous reversals",
                f"Detected {len(events)} spontaneous reversals "
                f"({rate:.2f}/min) over {duration_s:.1f} s.\n\n"
                f"Saved to:\n{output}", parent=self)
        except Exception as exc:
            messagebox.showerror("Spontaneous reversals", str(exc), parent=self)

    def run(self):
        if self.v["design"].get() == "spontaneous":
            self.run_spontaneous()
            return
        try:
            table = self.input_table(self.v["tracks"].get())
            records = propose_trials(table)
            dialog = ReviewDialog(self, records)
            self.wait_window(dialog)
            if not dialog.accepted:
                return
            baseline_records = []
            if self.v["baseline"].get():
                baseline_records = [
                    record.event for record in propose_trials(
                        load_track_table(self.v["baseline"].get()))]
            length_px = float(self.v["worm_length"].get()) / float(
                self.v["scale"].get())
            gate = evaluate_metric(
                RecordingProxies(
                    length_px, max(1, length_px / 12),
                    float(self.v["fps"].get()), 1.3, 0,
                    int(self.v["bit_depth"].get()), 1, 0, 0),
                MetricRequirement(
                    "reversal_response_and_kinematics",
                    min_length_px=50, min_fps=10,
                    min_contrast_ratio=1.15))
            failures = FailureLibrary(
                RunFeedbackStore().root / "failures")
            result = analyze_habituation(
                dialog.records, baseline_records, self.acquisition(), gate,
                failure_library=failures)
            source = Path(self.v["tracks"].get())
            output = source.parent / (source.stem + "_mechanosensation")
            output.mkdir(parents=True, exist_ok=True)
            result_path = output / "mechanosensation_reviewed.json"
            result_path.write_text(
                json.dumps(result, indent=2), encoding="utf-8")
            pd.DataFrame(result.get("trial_series", [])).to_csv(
                output / "plate_trial_series.csv", index=False)
            # Additive per-trial descriptive metrics (before/during/after crawl
            # velocity, head-bend amplitude, quirkiness, tortuosity). Does not
            # affect the reversal scoring above; NaN where columns are absent.
            try:
                metrics_df = reversal_window_metrics(table)
                if not metrics_df.empty:
                    metrics_df.to_csv(
                        output / "reversal_window_metrics.csv", index=False)
            except Exception:
                pass
            self.status.set(f"Reviewed results saved: {output}")
            messagebox.showinfo(
                "Mechanosensation complete",
                f"Reviewed plate-first results saved:\n{output}",
                parent=self)
            prompt_post_run_feedback(
                tool_name=TOOL_NAME, tool_version=TOOL_VERSION,
                run_id=output.name, acquisition=self.acquisition(),
                parameters={
                    "reviewed_trial_count": len(dialog.records),
                    "front_ends": sorted({
                        row.stimulus_front_end for row in dialog.records})},
                parent=self, evidence_paths=[result_path])
        except Exception as exc:
            messagebox.showerror("Mechanosensation", str(exc), parent=self)


if __name__ == "__main__":
    App().mainloop()
