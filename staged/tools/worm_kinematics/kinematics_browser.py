"""
kinematics_browser.py
=====================
Single Recording Kinematics Browser for the standalone student tool.

A focused variant of results_browser.ResultsBrowser that shows ONLY the posture
views (body wave, locomotion, foraging, dampening, and their figures), with no
greyed-out calcium or coupling columns. It reuses the parent's entire rendering,
copy, and export machinery and the shared AnalysisResult contract, so nothing is
reimplemented: it swaps the analysis path (run_one_kinematics) and the view set.

Launch: double-click Browse_Worm_Kinematics.bat (file picker, then this window,
via the pinned venv, no terminal). Direct run for testing:
    python kinematics_browser.py <csv_path>

Cannot run here without the pipeline and venv; run it in the pinned environment.
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "tools" / "rgbcamp" / "pipeline"
if not (PIPELINE / "results_browser.py").exists():
    raise ImportError(f"Canonical RGBCaMP pipeline not found: {PIPELINE}")
sys.path.insert(0, str(PIPELINE))

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
import pandas as pd

import results_browser as rb
import run_one_kinematics


# --------------------------------------------------------------------------- #
# Two new posture views (foraging, dampening) plus their figures, in the same
# ViewDef vocabulary the parent browser already renders.
# --------------------------------------------------------------------------- #
def _foraging_valid(r) -> bool:
    # show whenever a head-swing amplitude was computed, even if the frequency
    # was undersampled (the amplitude is still valid; the caveat flags the rest)
    return rb._has_col_nonnull(r, "foraging_descriptors", "rms_deg")


FORAGING_VIEW = rb.ViewDef(
    key="foraging_descriptors", label="Foraging (head swing)",
    domain="Kinematics", kind="table",
    n_label="one summary per recording (n_frames)",
    metric_cols=["rms_deg", "p2p_deg", "dominant_freq_hz", "hilbert_freq_hz",
                 "band_power_frac"],
    caveat=("Head swing only, measured from the per-frame head bend, which sits "
            "outside the body-wave segmentation because the head forages rather "
            "than undulates. Amplitude (rms_deg, p2p_deg) is valid whenever the "
            "head was tracked. Frequency is Nyquist limited: if the recording is "
            "marked undersampled, the frame rate cannot see the head swing and "
            "the frequency is not trustworthy even though the amplitude is. "
            "Requires the head_bend_deg column from the kinematics extractor; "
            "without it this view does not appear."),
    is_valid=_foraging_valid,
)

DAMPENING_VIEW = rb.ViewDef(
    key="posterior_dampening", label="Posterior dampening (bend amplitude head to tail)",
    domain="Kinematics", kind="table",
    n_label="one summary per recording (n_segments)",
    metric_cols=["slope_per_bodylen", "norm_slope", "space_constant", "pa_ratio",
                 "fit_r2", "coherence"],
    caveat=("Anterior to posterior fall in body-bend amplitude, computed as a "
            "spatial fit over the SAME per-segment envelope the undulation and "
            "locomotion views use, not a separate estimator. A negative slope and "
            "a posterior over anterior ratio below one mean the wave weakens "
            "toward the tail. Honesty guard: if no coherent body wave is found the "
            "whole view is absent rather than a slope fit to noise. This is the "
            "metric to compare across wild type and dystrophic animals."),
    is_valid=rb._validity_fn("resolved_flag", "posterior_dampening"),
)

DAMPENING_FIG = rb.ViewDef(
    key="fig_posterior_dampening", label="Posterior dampening profile",
    domain="Kinematics", kind="figure",
    caveat=("Bend amplitude against body position (0 = head, 1 = tail). This is "
            "the spatial curve the dampening slope is fit to."),
    is_valid=rb._validity_fn("figure", "fig_posterior_dampening"),
)

HEADBEND_FIG = rb.ViewDef(
    key="fig_head_bend", label="Head-swing trace (foraging)",
    domain="Kinematics", kind="figure",
    caveat=("Head-bend angle over time, the raw foraging trace the amplitude and "
            "frequency summarise. Reading the trace directly is the honest check "
            "on whether the frame rate resolves the swing."),
    is_valid=rb._validity_fn("figure", "fig_head_bend"),
)


def build_kinematics_catalog() -> list:
    return rb.build_kinematics_views() + [FORAGING_VIEW, DAMPENING_VIEW,
                                          DAMPENING_FIG, HEADBEND_FIG]


class KinematicsBrowser(rb.ResultsBrowser):
    """Kinematics-only browser. Reimplements __init__ (to call the kinematics
    analysis and set a kinematics-only catalog) and _build_tree (to show only
    the Kinematics domain); every other behaviour is inherited unchanged."""

    def __init__(self, csv_path: Path):
        tk.Tk.__init__(self)                      # init the Tk root directly
        self.title(f"Worm Kinematics Results Browser: {Path(csv_path).name}")
        self.geometry("1150x720")

        self._current_view = None
        self._current_table_full = None
        self._current_image_path = None
        self._tk_image = None
        self.csv_path = Path(csv_path)

        try:
            self.result = run_one_kinematics.analyse_one_kinematics(csv_path)
        except Exception:
            messagebox.showerror(
                "Worm Kinematics Browser: load failed",
                f"Could not analyse:\n{csv_path}\n\n{traceback.format_exc()[-1500:]}")
            self.destroy()
            return

        self.view_catalog = build_kinematics_catalog()
        self._build_layout()
        self._add_segment_explorer_button()
        self._build_tree()

    def _add_segment_explorer_button(self):
        parent = self.banner.master
        button = ttk.Button(
            parent,
            text="Curvature kymograph and segment explorer",
            command=self._open_segment_explorer,
        )
        button.pack(fill=tk.X, padx=6, pady=(2, 5), before=self.content)

    @staticmethod
    def _parse_segments(text: str, available: list[int]) -> list[int]:
        selected = set()
        for token in text.replace(" ", "").split(","):
            if not token:
                continue
            if "-" in token:
                left, right = token.split("-", 1)
                selected.update(range(int(left), int(right) + 1))
            else:
                selected.add(int(token))
        result = sorted(s for s in selected if s in available)
        if not result:
            raise ValueError(
                f"No valid segments selected. Available segments are "
                f"{available[0]} through {available[-1]}.")
        return result

    def _load_curvature_data(self) -> pd.DataFrame:
        data = pd.read_csv(self.csv_path)
        required = {"frame", "segment", "seg_curv_deg"}
        missing = sorted(required - set(data.columns))
        if missing:
            raise ValueError(
                "The recording CSV does not contain the curvature columns needed "
                f"for segment exploration. Missing: {', '.join(missing)}")
        if "needs_help" in data.columns:
            data = data[pd.to_numeric(data["needs_help"], errors="coerce").fillna(1) == 0]
        data["frame"] = pd.to_numeric(data["frame"], errors="coerce")
        data["segment"] = pd.to_numeric(data["segment"], errors="coerce")
        data["seg_curv_deg"] = pd.to_numeric(data["seg_curv_deg"], errors="coerce")
        if "time_s" not in data.columns:
            fps = pd.to_numeric(data.get("fps"), errors="coerce").dropna()
            fps_value = float(fps.iloc[0]) if len(fps) and fps.iloc[0] > 0 else 1.0
            data["time_s"] = (data["frame"] - data["frame"].min()) / fps_value
        else:
            data["time_s"] = pd.to_numeric(data["time_s"], errors="coerce")
        data = data.dropna(subset=["frame", "segment", "seg_curv_deg", "time_s"])
        if data.empty:
            raise ValueError("No reviewed curvature measurements remain after QC.")
        data["segment"] = data["segment"].astype(int)
        return data

    def _open_segment_explorer(self):
        try:
            data = self._load_curvature_data()
        except Exception as exc:
            messagebox.showerror("Segment explorer", str(exc))
            return

        available = sorted(data["segment"].unique().tolist())
        window = tk.Toplevel(self)
        window.title(f"Curvature segment explorer: {self.csv_path.name}")
        window.geometry("720x310")
        ttk.Label(
            window,
            text="Curvature kymograph and individual segment traces",
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w", padx=14, pady=(12, 3))
        ttk.Label(
            window,
            text=(
                "Enter segments as a range or list, for example 18-23 or "
                "3,4,5. Segment 0 is the head and the highest segment is the tail."
            ),
            wraplength=680,
            justify="left",
        ).pack(anchor="w", padx=14)

        row = ttk.Frame(window)
        row.pack(fill="x", padx=14, pady=12)
        ttk.Label(row, text="Segments").pack(side="left")
        default = (
            f"{max(available[0], available[-1] - 5)}-{available[-1]}"
            if len(available) > 1 else str(available[0])
        )
        segment_text = tk.StringVar(value=default)
        ttk.Entry(row, textvariable=segment_text, width=25).pack(side="left", padx=8)

        status = tk.Text(window, height=8, wrap="word")
        status.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        def selection():
            return self._parse_segments(segment_text.get(), available)

        def plot():
            try:
                segments = selection()
                self._plot_curvature_explorer(data, segments)
                status.insert("end", f"Plotted segments {segments}.\n")
                status.see("end")
            except Exception as exc:
                messagebox.showerror("Plot curvature", str(exc), parent=window)

        def export():
            try:
                segments = selection()
                folder = filedialog.askdirectory(
                    title="Choose a folder for segment curvature tables",
                    parent=window)
                if not folder:
                    return
                paths = self._export_segment_curvature(data, segments, Path(folder))
                status.insert(
                    "end",
                    "Exported:\n" + "\n".join(str(path) for path in paths) + "\n")
                status.see("end")
            except Exception as exc:
                messagebox.showerror("Export curvature", str(exc), parent=window)

        buttons = ttk.Frame(window)
        buttons.pack(fill="x", padx=14, pady=(0, 8))
        ttk.Button(buttons, text="Plot kymograph and traces", command=plot).pack(side="left")
        ttk.Button(buttons, text="Export selected data and statistics",
                   command=export).pack(side="left", padx=8)

    def _plot_curvature_explorer(self, data: pd.DataFrame, segments: list[int]):
        import matplotlib.pyplot as plt

        pivot = data.pivot_table(
            index="segment", columns="time_s", values="seg_curv_deg", aggfunc="mean")
        selected = data[data["segment"].isin(segments)]
        time_summary = selected.groupby("time_s")["seg_curv_deg"].agg(
            ["mean", "std", "count"]).reset_index()

        fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
        values = pivot.to_numpy(dtype=float)
        limit = float(np.nanpercentile(np.abs(values), 98)) if np.isfinite(values).any() else 1.0
        limit = max(limit, 1.0)
        ax0.imshow(
            values, aspect="auto", origin="lower",
            extent=[
                float(pivot.columns.min()), float(pivot.columns.max()),
                float(pivot.index.min()), float(pivot.index.max()),
            ],
            cmap="RdBu_r", vmin=-limit, vmax=limit,
        )
        for segment in segments:
            ax0.axhline(segment, color="gold", lw=0.8, alpha=0.8)
        ax0.set_ylabel("segment (0 = head)")
        ax0.set_title("Signed-curvature kymograph, selected segments in gold")

        for segment, group in selected.groupby("segment"):
            group = group.sort_values("time_s")
            ax1.plot(group["time_s"], group["seg_curv_deg"], lw=0.9,
                     alpha=0.55, label=f"segment {segment}")
        t = time_summary["time_s"].to_numpy(dtype=float)
        mean = time_summary["mean"].to_numpy(dtype=float)
        sd = time_summary["std"].fillna(0).to_numpy(dtype=float)
        ax1.plot(t, mean, color="black", lw=2, label="selected-segment mean")
        ax1.fill_between(t, mean - sd, mean + sd, color="black", alpha=0.15,
                         label="mean plus or minus SD")
        ax1.axhline(0, color="#777", lw=0.8)
        ax1.set_xlabel("time (s)")
        ax1.set_ylabel("signed curvature (deg)")
        ax1.set_title(f"Curvature over time: segments {segments}")
        ax1.legend(loc="upper right", fontsize=8, ncol=2)
        fig.tight_layout()
        plt.show()

    def _export_segment_curvature(
            self, data: pd.DataFrame, segments: list[int], folder: Path) -> list[Path]:
        folder.mkdir(parents=True, exist_ok=True)
        stem = self.csv_path.stem
        selected = data[data["segment"].isin(segments)].copy()
        selected = selected.sort_values(["segment", "time_s"])

        raw_path = folder / f"{stem}_segments_curvature.csv"
        selected.to_csv(raw_path, index=False)

        per_segment = selected.groupby("segment")["seg_curv_deg"].agg(
            n="count", mean_deg="mean", sd_deg="std",
            min_deg="min", max_deg="max")
        rms = selected.groupby("segment")["seg_curv_deg"].apply(
            lambda values: float(np.sqrt(np.nanmean(np.square(values)))))
        per_segment["rms_deg"] = rms
        pooled = pd.DataFrame([{
            "segment": "pooled_selected_segments",
            "n": int(selected["seg_curv_deg"].count()),
            "mean_deg": float(selected["seg_curv_deg"].mean()),
            "sd_deg": float(selected["seg_curv_deg"].std()),
            "min_deg": float(selected["seg_curv_deg"].min()),
            "max_deg": float(selected["seg_curv_deg"].max()),
            "rms_deg": float(np.sqrt(np.nanmean(np.square(selected["seg_curv_deg"])))),
        }])
        summary = pd.concat([per_segment.reset_index(), pooled], ignore_index=True)
        summary_path = folder / f"{stem}_segments_summary.csv"
        summary.to_csv(summary_path, index=False)

        timecourse = selected.groupby("time_s")["seg_curv_deg"].agg(
            mean_curvature_deg="mean", sd_curvature_deg="std",
            n_segments="count").reset_index()
        time_path = folder / f"{stem}_segments_timecourse_mean_sd.csv"
        timecourse.to_csv(time_path, index=False)
        return [raw_path, summary_path, time_path]

    def _build_tree(self):
        node = self.tree.insert("", "end", text="Kinematics", open=True, tags=("domain",))
        any_shown = False
        for v in self.view_catalog:
            try:
                ok = v.is_valid(self.result)
            except Exception:
                ok = False
            if not ok:
                continue
            self.tree.insert(node, "end", text=v.label, tags=("view", v.key))
            any_shown = True
        if not any_shown:
            self.tree.insert(node, "end",
                             text="(nothing valid: check the midline in Fiji and re-export)",
                             tags=("placeholder",))
        self.tree.tag_configure("placeholder", foreground="#888")


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"ERROR: {csv_path} does not exist"); sys.exit(1)
    app = KinematicsBrowser(csv_path)
    app.mainloop()


if __name__ == "__main__":
    main()
