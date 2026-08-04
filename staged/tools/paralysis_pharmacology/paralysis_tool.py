"""Student-facing T2 prod-observation review and plate survival export."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
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
from paralysis import (
    TOOL_NAME, TOOL_VERSION, ProdObservation, analyze_paralysis)
from run_feedback import RunFeedbackStore, prompt_post_run_feedback
from process_ui import CockpitApp

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


REQUIRED = {"plate_id", "worm_id", "time_s", "result", "drug"}


def load_observations(path):
    table = read_table(path)
    missing = sorted(REQUIRED - set(table.columns))
    if missing:
        raise ValueError("Observation table is missing: " + ", ".join(missing))
    observations = []
    for row in table.to_dict("records"):
        observations.append(ProdObservation(
            str(row["plate_id"]), str(row["worm_id"]), float(row["time_s"]),
            str(row["result"]).lower(), str(row["drug"]).lower(),
            None if pd.isna(row.get("concentration")) else float(
                row["concentration"]),
            None if pd.isna(row.get("excluded_reason"))
            else str(row["excluded_reason"])).validate())
    return observations


class Review(tk.Toplevel):
    def __init__(self, parent, observations):
        super().__init__(parent)
        self.title("Review prod observations")
        self.geometry("900x540")
        self.observations = list(observations)
        self.accepted = False
        self.tree = ttk.Treeview(
            self, columns=("i", "plate", "worm", "time", "drug", "result",
                           "reason"), show="headings", selectmode="extended")
        for column, width in zip(
                ("i", "plate", "worm", "time", "drug", "result", "reason"),
                (40, 90, 90, 80, 100, 100, 280)):
            self.tree.heading(column, text=column.title())
            self.tree.column(column, width=width, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=6)
        for label, result in (
                ("Moving", "moving"), ("Paralyzed", "paralyzed"),
                ("Exclude", "excluded")):
            ttk.Button(
                bar, text=label,
                command=lambda value=result: self.set_result(value)).pack(
                    side="left", padx=4)
        ttk.Button(bar, text="Accept reviewed table", command=self.finish).pack(
            side="right")
        self.refresh()
        self.transient(parent)
        self.grab_set()

    def refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, row in enumerate(self.observations):
            self.tree.insert("", "end", iid=str(index), values=(
                index, row.plate_id, row.worm_id, row.time_s, row.drug,
                row.result, row.excluded_reason or ""))

    def set_result(self, result):
        for item in self.tree.selection():
            index = int(item)
            reason = (
                "observer excluded after review" if result == "excluded"
                else None)
            self.observations[index] = replace(
                self.observations[index], result=result,
                excluded_reason=reason)
        self.refresh()

    def finish(self):
        self.accepted = True
        self.destroy()


class App(CockpitApp):
    def __init__(self):
        super().__init__("Neuromuscular paralysis pharmacology",
                         geometry="1080x640", process_title="Paralysis pharmacology")
        defaults = {
            "source": "", "duration": "7200", "bit_depth": "8",
            "channel": "observer prod scoring",
        }
        self.v = {key: tk.StringVar(value=value)
                  for key, value in defaults.items()}
        self.status = tk.StringVar(
            value="Choose a CSV of repeated prod observations.")
        self._build_controls()
        self._build_center()
        self.status.trace_add("write", lambda *_: self.set_status(self.status.get()))
        self.set_status(self.status.get())

    def _build_controls(self):
        c = self.controls

        def field(label, key):
            row = ttk.Frame(c); row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=24, wraplength=175, justify="left").pack(side="left")
            ttk.Entry(row, textvariable=self.v[key]).pack(side="right", fill="x", expand=True)

        srow = ttk.Frame(c); srow.pack(fill="x", pady=2)
        ttk.Label(srow, text="Observation CSV", width=24).pack(side="left")
        ttk.Entry(srow, textvariable=self.v["source"]).pack(side="right", fill="x", expand=True)
        ttk.Button(c, text="Choose CSV...",
                   command=lambda: self.v["source"].set(
                       filedialog.askopenfilename(filetypes=[("CSV", "*.csv")]) or self.v["source"].get())).pack(fill="x", pady=(0, 4))
        field("Assay duration (s)", "duration")
        field("Recorded bit depth", "bit_depth")
        field("Channel / scoring identity", "channel")
        ttk.Separator(c, orient="horizontal").pack(fill="x", pady=6)
        ttk.Button(c, text="Review and analyze plate curves", command=self.run).pack(fill="x", pady=2)

    def _build_center(self):
        ttk.Label(self.center, text="Neuromuscular paralysis pharmacology",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=6, pady=(6, 2))
        ttk.Label(self.center, wraplength=620, justify="left", foreground="#444444",
                  text=("Load a CSV of repeated prod observations (columns: plate_id, worm_id, "
                        "time_s, result, drug; optional concentration, excluded_reason). Review "
                        "each observation (Moving / Paralyzed / Exclude) in the review window, then "
                        "the tool exports plate-level fraction-moving and censored "
                        "time-to-paralysis curves. The plate is the unit of replication.")).pack(
            anchor="w", padx=6, pady=4)
        ttk.Separator(self.center, orient="horizontal").pack(fill="x", padx=6, pady=6)
        ttk.Label(self.center, textvariable=self.status, wraplength=620,
                  justify="left").pack(anchor="w", padx=6, pady=4)

    def acquisition(self):
        return AcquisitionMetadata(
            None, "not_applicable", None, "not_applicable",
            None, "not_applicable", bit_depth=int(self.v["bit_depth"].get()),
            compression="not_applicable",
            recording_duration_s=float(self.v["duration"].get()),
            channel_identity=self.v["channel"].get(),
            anatomical_orientation="not_applicable")

    def run(self):
        try:
            observations = load_observations(self.v["source"].get())
            dialog = Review(self, observations)
            self.wait_window(dialog)
            if not dialog.accepted:
                return
            gate = evaluate_metric(
                RecordingProxies(
                    None, None, None, None, None,
                    int(self.v["bit_depth"].get()), None, None, None),
                MetricRequirement("manual_prod_response", min_bit_depth=1))
            failures = FailureLibrary(
                RunFeedbackStore().root / "failures")
            result = analyze_paralysis(
                dialog.observations, self.acquisition(), gate,
                failure_library=failures)
            source = Path(self.v["source"].get())
            output = source.parent / (source.stem + "_paralysis")
            output.mkdir(parents=True, exist_ok=True)
            result_path = output / "paralysis_reviewed.json"
            result_path.write_text(
                json.dumps(result, indent=2), encoding="utf-8")
            pd.DataFrame(result.get("plate_fraction_moving_curves", [])).to_csv(
                output / "plate_fraction_moving_curves.csv", index=False)
            pd.DataFrame(result.get(
                "censored_worm_outcomes_for_plate_curves", [])).to_csv(
                    output / "censored_outcomes.csv", index=False)
            self.status.set(f"Reviewed plate curves saved: {output}")
            messagebox.showinfo(
                "Paralysis analysis complete",
                f"Reviewed plate-level curves saved:\n{output}", parent=self)
            prompt_post_run_feedback(
                tool_name=TOOL_NAME, tool_version=TOOL_VERSION,
                run_id=output.name, acquisition=self.acquisition(),
                parameters={
                    "observation_count": len(dialog.observations),
                    "drugs": sorted({row.drug for row in dialog.observations})},
                parent=self, evidence_paths=[result_path])
        except Exception as exc:
            messagebox.showerror("Paralysis pharmacology", str(exc), parent=self)


if __name__ == "__main__":
    App().mainloop()
