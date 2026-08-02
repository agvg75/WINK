"""Shared student workbench for T7 thermotaxis, T8 magnetotaxis, and T9 chemotaxis."""
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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "app")]

from acquisition import AcquisitionMetadata
from capability_gate import (
    MetricRequirement, RecordingProxies, evaluate_metric)
from chemotaxis import analyze_chemotaxis_tracks, endpoint_index
from departure_roi import analyze_departure
from failure_library import FailureLibrary
from magnetotaxis import analyze_magnetotaxis
from run_feedback import RunFeedbackStore, prompt_post_run_feedback
from stimulus_fields import (
    ChemicalProvider, MagnetProvider, NullProvider, ThermalLinearProvider,
    ThermalRadialProvider)
from thermotaxis import analyze_thermotaxis

TRACK_COLUMNS = {
    "plate_id", "time_s", "x_mm", "y_mm", "heading_deg"}
VERSIONS = {"magnetotaxis": "0.2.0", "thermotaxis": "0.1.0",
            "chemotaxis": "0.1.0"}
DISPLAY = {
    "magnetotaxis": "Magnetotaxis",
    "thermotaxis": "Thermotaxis",
    "chemotaxis": "Chemotaxis and avoidance",
}


def configuration_template(assay):
    common = {
        "stimulus_orientations_deg": {"plate_1": 0, "plate_2": 90},
        "source_xy_mm": [0, 0],
        "endpoint_only": False,
    }
    if assay == "magnetotaxis":
        return {
            **common,
            "provider": {
                "shape": "disc", "dimensions_mm": [50.8, 6.35],
                "remanence_t": 1.32,
                "magnetization_direction_xyz": [0, 0, 1],
                "position_xyz_mm": [0, 0, 6.35],
                "distance_uncertainty_mm": 0.25,
                "earth_field_xyz_t": [0.000020, 0, -0.000045],
            },
            "state": {
                "humidity_percent": 45, "worm_age": "adult day 1",
                "genotype": "N2", "time_since_food_removal_s": 300,
                "food_removal_clock": None, "assay_start_clock": None,
                "per_worm_food_removal_offsets_s": {},
                "initial_state_window_s": 30, "pick_state": None},
            "magnetic_pulse": {
                "applied": False, "magnitude_mt": None,
                "duration_s": None, "time_relative_to_recording_s": None},
            "analysis_tier": "plate_state",
        }
    if assay == "thermotaxis":
        return {
            **common, "geometry": "radial",
            "provider": {
                "type": "radial", "source_xy_mm": [0, 0],
                "slope_c_per_mm": 0.5, "uncertainty_c_per_mm": 0.05},
            "cultivation_temperature_c": 20, "feeding_state": "fed",
            "spatial_temperature_calibration": {
                "method": "measured probe map", "units": "degC/mm"},
            "absolute_temperature_calibrated": False,
        }
    return {
        **common,
        "provider": {
            "source_xy_mm": [0, 0], "model": "gaussian",
            "amplitude": 1, "sigma_mm": 5, "relative_uncertainty": 0.5},
        "endpoint_counts": {"toward": 0, "away": 0, "neutral": 0},
    }


def load_tracks(path):
    table = pd.read_csv(path)
    missing = sorted(TRACK_COLUMNS - set(table.columns))
    if missing:
        raise ValueError("Track CSV is missing: " + ", ".join(missing))
    if table.empty:
        raise ValueError("Track CSV is empty.")
    if "worm_id" not in table:
        table["worm_id"] = None
    return table


def build_provider(assay, config):
    values = config["provider"]
    if assay == "magnetotaxis":
        return MagnetProvider(**values)
    if assay == "thermotaxis":
        if values["type"] == "linear":
            return ThermalLinearProvider(
                values["direction_xy"], values["slope_c_per_mm"],
                values.get("uncertainty_c_per_mm", 0))
        if values["type"] == "radial":
            return ThermalRadialProvider(
                values["source_xy_mm"], values["slope_c_per_mm"],
                values.get("uncertainty_c_per_mm", 0))
        raise ValueError("Thermal provider type must be linear or radial.")
    if values.get("model") != "gaussian":
        raise ValueError("The current chemical provider supports gaussian model.")
    source = np.asarray(values["source_xy_mm"], dtype=float)
    amplitude = float(values["amplitude"])
    sigma = float(values["sigma_mm"])

    def model(x, y, time_s):
        distance2 = float(np.sum((np.asarray([x, y]) - source) ** 2))
        return amplitude * np.exp(-distance2 / (2 * sigma**2))

    return ChemicalProvider(
        source, model, values.get("relative_uncertainty", 0.5))


def track_rows(table):
    return [{
        "plate_id": str(row.plate_id),
        "worm_id": None if pd.isna(row.worm_id) else str(row.worm_id),
        "time_s": float(row.time_s), "x_mm": float(row.x_mm),
        "y_mm": float(row.y_mm), "heading_deg": float(row.heading_deg),
    } for row in table.itertuples()]


def departure_results(table, config):
    required = {"inside_start_roi", "radial_distance", "droplet_clear"}
    if not required.issubset(table.columns) or table.worm_id.isna().all():
        return []
    results = []
    for (plate, worm), group in table.groupby(["plate_id", "worm_id"]):
        group = group.sort_values("time_s")
        results.append(analyze_departure(
            f"{plate}:{worm}", group.time_s, group.inside_start_roi,
            group.radial_distance, droplet_clear=group.droplet_clear,
            time_since_food_at_recording_start_s=config.get(
                "state", {}).get("time_since_food_removal_s")))
    return results


def plot_field_and_tracks(provider, table, title):
    xmin, xmax = float(table.x_mm.min()), float(table.x_mm.max())
    ymin, ymax = float(table.y_mm.min()), float(table.y_mm.max())
    if xmin == xmax:
        xmin, xmax = xmin - 1, xmax + 1
    if ymin == ymax:
        ymin, ymax = ymin - 1, ymax + 1
    xs = np.linspace(xmin, xmax, 18)
    ys = np.linspace(ymin, ymax, 18)
    magnitude = np.zeros((len(ys), len(xs)))
    u = np.zeros_like(magnitude)
    v = np.zeros_like(magnitude)
    for iy, y in enumerate(ys):
        for ix, x in enumerate(xs):
            sample = provider.sample(x, y)
            magnitude[iy, ix] = sample.magnitude
            vector = (
                sample.direction_xyz[:2]
                if sample.direction_xyz is not None
                else sample.gradient_xy)
            u[iy, ix], v[iy, ix] = vector
    fig, axis = plt.subplots(figsize=(9, 7))
    contour = axis.contourf(xs, ys, magnitude, levels=15, alpha=0.65)
    fig.colorbar(contour, ax=axis, label="Provider magnitude")
    axis.quiver(xs, ys, u, v, color="white", alpha=0.8)
    for plate, group in table.groupby("plate_id"):
        axis.plot(group.x_mm, group.y_mm, linewidth=1, label=str(plate))
    axis.set_aspect("equal")
    axis.legend(loc="best")
    axis.set_title(title + "\nReview field placement and tracked trajectories")
    axis.set_xlabel("Plate x (mm)")
    axis.set_ylabel("Plate y (mm)")
    plt.show()


class App(tk.Tk):
    def __init__(self, assay):
        super().__init__()
        self.assay = assay
        self.title(DISPLAY[assay] + " orientation workbench")
        self.geometry("880x560")
        defaults = {
            "tracks": "", "config": "", "fps": "3", "scale": "20",
            "exposure": "5", "bit_depth": "12", "duration": "1800",
            "worm_length": "1000",
        }
        self.v = {key: tk.StringVar(value=value)
                  for key, value in defaults.items()}
        self.status = tk.StringVar(
            value="Choose a reviewed track CSV and assay configuration JSON.")
        # Tk discards callback errors to stderr under pythonw, so a failing
        # button looks like one that does nothing. Report them instead.
        try:
            from process_ui import install_error_reporting
            install_error_reporting(
                self, status=lambda m: self.status.set("Action failed: " + m))
        except Exception:
            pass
        fields = [
            ("Track CSV", "tracks"), ("Configuration JSON", "config"),
            ("FPS", "fps"), ("Scale (µm/pixel)", "scale"),
            ("Exposure (ms)", "exposure"), ("Bit depth", "bit_depth"),
            ("Duration (s)", "duration"),
            ("Expected worm length (µm)", "worm_length"),
        ]
        for row, (label, key) in enumerate(fields):
            ttk.Label(self, text=label).grid(
                row=row, column=0, padx=10, pady=7, sticky="w")
            ttk.Entry(self, textvariable=self.v[key], width=62).grid(
                row=row, column=1, padx=5, pady=7)
            if key in {"tracks", "config"}:
                ttk.Button(
                    self, text="Choose",
                    command=lambda k=key: self.v[k].set(
                        filedialog.askopenfilename(
                            filetypes=[("CSV", "*.csv")] if k == "tracks"
                            else [("JSON", "*.json")]))).grid(
                                row=row, column=2, padx=8)
        ttk.Button(
            self, text="Create configuration template",
            command=self.write_template).grid(
                row=9, column=0, padx=12, pady=10, sticky="ew")
        ttk.Button(
            self, text="Review field and analyze",
            command=self.run).grid(
                row=9, column=1, padx=12, pady=10, sticky="ew")
        ttk.Label(
            self, textvariable=self.status, wraplength=840).grid(
                row=10, column=0, columnspan=3, padx=12, pady=12, sticky="w")

    def write_template(self):
        destination = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile=f"{self.assay}_configuration.json",
            filetypes=[("JSON", "*.json")])
        if destination:
            Path(destination).write_text(
                json.dumps(configuration_template(self.assay), indent=2),
                encoding="utf-8")
            self.v["config"].set(destination)

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
            table = load_tracks(self.v["tracks"].get())
            config = json.loads(
                Path(self.v["config"].get()).read_text(encoding="utf-8"))
            provider = build_provider(self.assay, config)
            plot_field_and_tracks(provider, table, DISPLAY[self.assay])
            if not messagebox.askyesno(
                    "Accept field and tracks?",
                    "Are the stimulus field placement and reviewed trajectories "
                    "correct? Choose No to stop without analysis.", parent=self):
                return
            length_px = float(self.v["worm_length"].get()) / float(
                self.v["scale"].get())
            gate = evaluate_metric(
                RecordingProxies(
                    length_px, max(1, length_px / 12),
                    float(self.v["fps"].get()), 1.3, 0,
                    int(self.v["bit_depth"].get()), 1,
                    float(table.get("occluded", pd.Series(False)).mean()), 0),
                MetricRequirement(
                    "tracked_orientation", min_length_px=25, min_fps=2,
                    min_contrast_ratio=1.15, max_occluded_fraction=0.5))
            failures = FailureLibrary(
                RunFeedbackStore().root / "failures")
            rows = track_rows(table)
            if self.assay == "magnetotaxis":
                state = config["state"]
                result = analyze_magnetotaxis(
                    tracks=rows, provider=provider,
                    acquisition=self.acquisition(), gate_decision=gate,
                    failure_library=failures,
                    departure_results=departure_results(table, config),
                    humidity_percent=state["humidity_percent"],
                    worm_age=state["worm_age"], genotype=state["genotype"],
                    time_since_food_removal_s=state[
                        "time_since_food_removal_s"],
                    food_removal_clock=state.get("food_removal_clock"),
                    assay_start_clock=state.get("assay_start_clock"),
                    per_worm_food_removal_offsets_s=state.get(
                        "per_worm_food_removal_offsets_s"),
                    initial_state_window_s=state.get(
                        "initial_state_window_s", 30),
                    pick_state=state.get("pick_state"),
                    magnetic_pulse=config["magnetic_pulse"],
                    source_xy_mm=config["source_xy_mm"],
                    stimulus_orientations_deg=config.get(
                        "stimulus_orientations_deg"),
                    endpoint_only=bool(config.get("endpoint_only", False)),
                    analysis_tier=config.get("analysis_tier", "plate_state"))
            elif self.assay == "thermotaxis":
                result = analyze_thermotaxis(
                    tracks=rows, provider=provider,
                    acquisition=self.acquisition(), gate_decision=gate,
                    failure_library=failures,
                    cultivation_temperature_c=config[
                        "cultivation_temperature_c"],
                    feeding_state=config["feeding_state"],
                    spatial_temperature_calibration=config[
                        "spatial_temperature_calibration"],
                    geometry=config["geometry"],
                    source_xy_mm=config.get("source_xy_mm"),
                    stimulus_orientations_deg=config.get(
                        "stimulus_orientations_deg"),
                    endpoint_only=bool(config.get("endpoint_only", False)),
                    absolute_temperature_calibrated=bool(config.get(
                        "absolute_temperature_calibrated", False)))
            else:
                result = analyze_chemotaxis_tracks(
                    tracks=rows, provider=provider,
                    acquisition=self.acquisition(), gate_decision=gate,
                    failure_library=failures,
                    source_xy_mm=config["source_xy_mm"],
                    stimulus_orientations_deg=config.get(
                        "stimulus_orientations_deg"))
                counts = config.get("endpoint_counts", {})
                result["endpoint_index"] = endpoint_index(
                    int(counts.get("toward", 0)),
                    int(counts.get("away", 0)),
                    int(counts.get("neutral", 0)))
            source = Path(self.v["tracks"].get())
            output = source.parent / (source.stem + f"_{self.assay}")
            output.mkdir(parents=True, exist_ok=True)
            result_path = output / f"{self.assay}_reviewed.json"
            result_path.write_text(
                json.dumps(result, indent=2), encoding="utf-8")
            pd.DataFrame(result.get("segments", [])).to_csv(
                output / "reviewed_orientation_segments.csv", index=False)
            self.status.set(f"Reviewed results saved: {output}")
            messagebox.showinfo(
                DISPLAY[self.assay] + " complete",
                f"Reviewed plate-level results saved:\n{output}",
                parent=self)
            prompt_post_run_feedback(
                tool_name=DISPLAY[self.assay],
                tool_version=VERSIONS[self.assay], run_id=output.name,
                acquisition=self.acquisition(),
                parameters={"configuration": config,
                            "track_row_count": len(table)},
                parent=self, evidence_paths=[result_path])
        except Exception as exc:
            messagebox.showerror(
                DISPLAY[self.assay], str(exc), parent=self)


def main(assay=None):
    if assay is None:
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--assay", required=True,
            choices=sorted(DISPLAY))
        assay = parser.parse_args().assay
    App(assay).mainloop()


if __name__ == "__main__":
    main()
