"""Shared reviewed-track workbench for T3/T4/T5/T6/T10/T11."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "app"), str(ROOT / "tools" / "behavioral_states"),
    str(ROOT / "tools" / "burrowing"),
    str(ROOT / "tools" / "longitudinal_performance")]

from acquisition import AcquisitionMetadata
from capability_gate import (
    MetricRequirement, RecordingProxies, evaluate_metric)
from failure_library import FailureLibrary
from performance import analyze_longitudinal_decline, analyze_swimming_fatigue
from burrowing import analyze_burrowing
from states import area_restricted_search, quiescence, roaming_dwelling
from run_feedback import RunFeedbackStore, prompt_post_run_feedback
from track_input_adapters import adapt_existing_track_csv
from results_summary import table_review_summary

DISPLAY = {
    "swimming_fatigue": "Swimming fatigue and endurance",
    "healthspan": "Longitudinal decline (healthspan)",
    "search": "Area-restricted search",
    "roaming_dwelling": "Roaming versus dwelling",
    "quiescence": "Quiescence and sleep",
    "burrowing": "Burrowing against graded resistance",
}
VERSION = "0.1.0"
REQUIRED = {
    "swimming_fatigue": {
        "plate_id", "worm_id", "time_s", "thrash_frequency_hz",
        "amplitude_body_lengths"},
    "healthspan": {
        "cohort_id", "plate_id", "adult_age_days", "measurement"},
    "search": {
        "plate_id", "time_s", "event_type", "observable_duration_s"},
    "roaming_dwelling": {
        "plate_id", "worm_id", "time_s", "speed_um_s",
        "angular_velocity_deg_s"},
    "quiescence": {
        "plate_id", "worm_id", "time_s", "speed_um_s"},
    "burrowing": {
        "plate_id", "worm_id", "resistance", "time_s", "depth_um"},
}


def config_template(assay):
    values = {
        "swimming_fatigue": {
            "minimum_recording_s": 180, "review_metric": "thrash_frequency_hz"},
        "healthspan": {
            "measurement_name": "speed_um_s", "expected_age_unit": "days"},
        "search": {
            "removal_from_food_s": 0, "bin_width_s": 60},
        "roaming_dwelling": {
            "speed_threshold_um_s": None,
            "angular_threshold_deg_s": None},
        "quiescence": {
            "speed_threshold_um_s": 1, "minimum_bout_s": 10,
            "minimum_recording_s": 1800},
        "burrowing": {
            "minimum_progress_um": 50, "stall_velocity_um_s": 2,
            "resistance_units": "declared medium stiffness"},
    }
    return values[assay]


def load_table(path, assay):
    table = pd.read_csv(path)
    table = adapt_existing_track_csv(table, assay, path)
    missing = sorted(REQUIRED[assay] - set(table.columns))
    if missing:
        raise ValueError("Input CSV is missing: " + ", ".join(missing))
    if table.empty:
        raise ValueError("Input CSV is empty.")
    return table


def plot_review(table, assay):
    fig, axis = plt.subplots(figsize=(10, 6))
    values={"swimming_fatigue":("thrash_frequency_hz","amplitude_body_lengths"),
            "healthspan":("measurement",),"search":(),
            "roaming_dwelling":("speed_um_s","angular_velocity_deg_s"),
            "quiescence":("speed_um_s",),"burrowing":("depth_um",)}[assay]
    fig.text(.01,.985,table_review_summary(table,values),va="top",fontsize=8)
    if assay == "swimming_fatigue":
        for (plate, worm), group in table.groupby(["plate_id", "worm_id"]):
            axis.plot(group.time_s, group.thrash_frequency_hz, marker=".",
                      label=f"{plate}:{worm}")
        axis.set_ylabel("Thrash frequency (Hz)")
        axis.set_xlabel("Bout time (s)")
    elif assay == "healthspan":
        for (cohort, plate), group in table.groupby(["cohort_id", "plate_id"]):
            axis.plot(group.adult_age_days, group.measurement, marker="o",
                      label=f"{cohort}:{plate}")
        axis.set_ylabel("Declared measurement")
        axis.set_xlabel("Adult age (days)")
    elif assay == "search":
        for plate, group in table.groupby("plate_id"):
            event = group.event_type.isin(["reversal", "omega"]).astype(int)
            axis.step(group.time_s, event, where="mid", label=str(plate))
        axis.set_ylabel("Reviewed reversal/omega event")
        axis.set_xlabel("Time (s)")
    elif assay in {"roaming_dwelling", "quiescence"}:
        for (plate, worm), group in table.groupby(["plate_id", "worm_id"]):
            axis.plot(group.time_s, group.speed_um_s,
                      label=f"{plate}:{worm}")
        axis.set_ylabel("Speed (µm/s)")
        axis.set_xlabel("Time (s)")
    else:
        for (plate, worm, resistance), group in table.groupby(
                ["plate_id", "worm_id", "resistance"]):
            axis.plot(group.time_s, group.depth_um,
                      label=f"{plate}:{worm} R={resistance}")
        axis.set_ylabel("Depth (µm)")
        axis.set_xlabel("Time (s)")
    axis.set_title(DISPLAY[assay] + "\nReview identities, gaps, and proposed input")
    if table.groupby(list(REQUIRED[assay] & {
            "plate_id", "worm_id", "cohort_id"})).ngroups <= 20:
        axis.legend(fontsize=7)
    plt.tight_layout(rect=(0,0,1,.95))
    plt.show()


def analyze(assay, table, config, acquisition, gate, failures):
    rows = table.to_dict("records")
    if assay == "swimming_fatigue":
        return analyze_swimming_fatigue(
            rows, acquisition, gate, failure_library=failures)
    if assay == "healthspan":
        return analyze_longitudinal_decline(rows)
    if assay == "search":
        return area_restricted_search(
            rows, removal_from_food_s=float(config["removal_from_food_s"]),
            bin_width_s=float(config["bin_width_s"]))
    if assay == "roaming_dwelling":
        return roaming_dwelling(
            rows, speed_threshold=config.get("speed_threshold_um_s"),
            angular_threshold=config.get("angular_threshold_deg_s"))
    if assay == "quiescence":
        duration = float(table.time_s.max() - table.time_s.min())
        if duration < float(config["minimum_recording_s"]):
            return {
                "status": "refused",
                "reason": (
                    f"recording is {duration:g} s; quiescence requires at "
                    f"least {config['minimum_recording_s']} s")}
        return quiescence(
            rows, speed_threshold_um_s=float(
                config["speed_threshold_um_s"]),
            minimum_bout_s=float(config["minimum_bout_s"]))
    return analyze_burrowing(
        rows, minimum_progress_um=float(config["minimum_progress_um"]),
        stall_velocity_um_s=float(config["stall_velocity_um_s"]))


class App(tk.Tk):
    def __init__(self, assay):
        super().__init__()
        self.assay = assay
        self.title(DISPLAY[assay])
        self.geometry("840x640")
        defaults = {
            "source": "", "config": "", "fps": "20", "scale": "2",
            "exposure": "2", "bit_depth": "12", "duration": "300",
            "worm_length": "1000", "start_s": "", "end_s": "",
        }
        self.v = {key: tk.StringVar(value=value)
                  for key, value in defaults.items()}
        self.status = tk.StringVar(
            value="Choose a reviewed input table and configuration.")
        # Tk discards callback errors to stderr under pythonw, so a failing
        # button looks like one that does nothing. Report them instead.
        try:
            from process_ui import install_error_reporting
            install_error_reporting(
                self, status=lambda m: self.status.set("Action failed: " + m))
        except Exception:
            pass
        fields = [
            ("Reviewed input CSV", "source"), ("Configuration JSON", "config"),
            ("FPS", "fps"), ("Scale (µm/pixel)", "scale"),
            ("Exposure (ms)", "exposure"), ("Bit depth", "bit_depth"),
            ("Recording duration (s)", "duration"),
            ("Expected worm length (µm)", "worm_length"),
        ]
        fields.extend([
            ("Analyze from time (s; blank = first)", "start_s"),
            ("Analyze through time (s; blank = last)", "end_s"),
        ])
        for row, (label, key) in enumerate(fields):
            ttk.Label(self, text=label).grid(
                row=row, column=0, padx=10, pady=7, sticky="w")
            ttk.Entry(self, textvariable=self.v[key], width=58).grid(
                row=row, column=1, padx=5, pady=7)
            if key in {"source", "config"}:
                ttk.Button(
                    self, text="Choose",
                    command=lambda k=key: self.v[k].set(
                        filedialog.askopenfilename(
                            filetypes=[("CSV", "*.csv")] if k == "source"
                            else [("JSON", "*.json")]))).grid(
                                row=row, column=2, padx=8)
        ttk.Button(
            self, text="Create configuration template",
            command=self.write_config).grid(
                row=11, column=0, padx=12, pady=12, sticky="ew")
        ttk.Button(
            self, text="Review and analyze", command=self.run).grid(
                row=11, column=1, padx=12, pady=12, sticky="ew")
        ttk.Label(
            self, textvariable=self.status, wraplength=800).grid(
                row=12, column=0, columnspan=3, padx=12, pady=12, sticky="w")

    def write_config(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile=f"{self.assay}_configuration.json",
            filetypes=[("JSON", "*.json")])
        if path:
            Path(path).write_text(
                json.dumps(config_template(self.assay), indent=2),
                encoding="utf-8")
            self.v["config"].set(path)

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

    def run(self):
        try:
            table = load_table(self.v["source"].get(), self.assay)
            original_rows=len(table);selected_range=None
            if "time_s" in table:
                start=float(self.v["start_s"].get()) if self.v["start_s"].get().strip() else float(table.time_s.min())
                end=float(self.v["end_s"].get()) if self.v["end_s"].get().strip() else float(table.time_s.max())
                if end<start:raise ValueError("End time must be at or after start time.")
                table=table[(table.time_s>=start)&(table.time_s<=end)].copy()
                if table.empty:raise ValueError("The selected time range contains no rows.")
                selected_range={"start_s":start,"end_s":end,"original_rows":original_rows,"selected_rows":len(table)}
            config = json.loads(
                Path(self.v["config"].get()).read_text(encoding="utf-8"))
            plot_review(table, self.assay)
            if not messagebox.askyesno(
                    "Accept reviewed input?",
                    "Are identities, gaps, events, and measurement columns "
                    "acceptable for analysis?", parent=self):
                return
            length_px = float(self.v["worm_length"].get()) / float(
                self.v["scale"].get())
            requirement = MetricRequirement(
                self.assay, min_length_px=25, min_fps=2,
                min_contrast_ratio=1.1)
            if self.assay == "quiescence":
                requirement = MetricRequirement(
                    self.assay, min_length_px=20, min_fps=1,
                    min_contrast_ratio=1.05)
            gate = evaluate_metric(
                RecordingProxies(
                    length_px, max(1, length_px / 12),
                    float(self.v["fps"].get()), 1.3, 0,
                    int(self.v["bit_depth"].get()), 1, 0, 0),
                requirement)
            failures = FailureLibrary(
                RunFeedbackStore().root / "failures")
            result = analyze(
                self.assay, table, config, self.acquisition(), gate, failures)
            source = Path(self.v["source"].get())
            output = source.parent / (source.stem + f"_{self.assay}")
            output.mkdir(parents=True, exist_ok=True)
            result_path = output / f"{self.assay}_reviewed.json"
            payload = {
                **self.acquisition().stamped(DISPLAY[self.assay], VERSION),
                "capability_gate": gate.as_dict(),
                "configuration": config,"selected_time_range":selected_range, **result}
            result_path.write_text(
                json.dumps(payload, indent=2), encoding="utf-8")
            self.status.set(f"Reviewed result saved: {result_path}")
            if result.get("status") == "refused":
                messagebox.showerror(
                    "Measurement refused", result["reason"], parent=self)
            else:
                messagebox.showinfo(
                    DISPLAY[self.assay] + " complete",
                    f"Reviewed result saved:\n{result_path}", parent=self)
            prompt_post_run_feedback(
                tool_name=DISPLAY[self.assay], tool_version=VERSION,
                run_id=output.name, acquisition=self.acquisition(),
                parameters={"configuration": config, "input_rows": len(table),
                            "selected_time_range":selected_range},
                parent=self, evidence_paths=[result_path])
        except Exception as exc:
            messagebox.showerror(DISPLAY[self.assay], str(exc), parent=self)


def main(assay=None):
    if assay is None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--assay", choices=sorted(DISPLAY), required=True)
        assay = parser.parse_args().assay
    App(assay).mainloop()


if __name__ == "__main__":
    main()
