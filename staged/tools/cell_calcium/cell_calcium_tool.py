"""Calcium and probe measurements in cultured human muscle cells.

Built for the lab's shRNA knockdown layout: a calcium channel, an mCherry
channel marking transfected cells, and untransfected cells in the same field
acting as the internal control. It also covers the other probes in use -
Fura-2, Fluo-4, mitochondrial oxidation indicators, antibody staining - by
asking which probe was used and refusing the measurements that probe cannot
support, rather than computing them anyway.

The tool runs in three steps deliberately. Step 1 says what the data can
support BEFORE anything is measured, because the useful answer for the pilot
dataset was "eight of nine measurements are impossible here", and that answer
is worth having before a morning is spent on the ninth.
"""
from __future__ import annotations

import csv
import json
import sys
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "app")]

import cell_calcium as cc                    # noqa: E402
import cell_calcium_images as cci            # noqa: E402
from process_ui import CockpitApp            # noqa: E402

TOOL_NAME = "Cultured cell calcium (probe-aware)"
TOOL_VERSION = "0.1.0"


class App(CockpitApp):
    def __init__(self):
        super().__init__(TOOL_NAME, geometry="1180x800",
                         process_title="Cultured cell calcium")
        self.v = {
            "folder": tk.StringVar(value=""),
            "probe": tk.StringVar(value="fluo-4"),
            "bit_depth": tk.StringVar(value="8"),
            "n_frames": tk.StringVar(value="1"),
            "signal_suffix": tk.StringVar(value="_ch00"),
            "marker_suffix": tk.StringVar(value="_ch01"),
            "seg_suffix": tk.StringVar(value=""),
            "threshold": tk.StringVar(value="8"),
        }
        self.result = None
        self.capability = None
        self._build_controls()
        self._build_center()
        self.set_status("Choose the folder holding one subfolder per "
                        "condition, then run step 1.")

    # -- controls ------------------------------------------------------
    def _build_controls(self):
        c = self.controls
        ttk.Button(c, text="Choose data folder...",
                   command=self._choose).pack(fill="x", pady=(2, 2))
        ttk.Entry(c, textvariable=self.v["folder"]).pack(fill="x", pady=(0, 6))
        ttk.Label(c, text="One subfolder per condition; the folder names "
                          "become the condition labels.",
                  wraplength=205, justify="left",
                  foreground="#555555").pack(fill="x", pady=(0, 6))

        ttk.Separator(c, orient="horizontal").pack(fill="x", pady=4)
        row = ttk.Frame(c); row.pack(fill="x", pady=2)
        ttk.Label(row, text="Probe", width=13).pack(side="left")
        ttk.Combobox(row, textvariable=self.v["probe"], width=14,
                     values=sorted(cc.PROBES),
                     state="readonly").pack(side="right")
        self.probe_note = ttk.Label(c, wraplength=205, justify="left",
                                    foreground="#555555", text="")
        self.probe_note.pack(fill="x", pady=(2, 6))
        self.v["probe"].trace_add("write", lambda *_: self._show_probe_note())
        self._show_probe_note()

        for label, key in (("Bit depth", "bit_depth"),
                           ("Frames per cell", "n_frames"),
                           ("Signal suffix", "signal_suffix"),
                           ("Marker suffix", "marker_suffix"),
                           ("Segment suffix", "seg_suffix"),
                           ("Cell threshold", "threshold")):
            row = ttk.Frame(c); row.pack(fill="x", pady=1)
            ttk.Label(row, text=label, width=13).pack(side="left")
            ttk.Entry(row, textvariable=self.v[key], width=12).pack(side="right")
        ttk.Label(c, text="Leave 'Segment suffix' blank if there is no DIC or "
                          "nuclear channel; cells are then found from both "
                          "fluorescence channels, which biases the sample "
                          "towards bright cells.",
                  wraplength=205, justify="left",
                  foreground="#8a5a00").pack(fill="x", pady=(4, 6))

        ttk.Separator(c, orient="horizontal").pack(fill="x", pady=4)
        ttk.Button(c, text="1. What can this data support?",
                   command=self.run_capability).pack(fill="x", pady=2)
        ttk.Button(c, text="2. Measure cells",
                   command=self.run_measure).pack(fill="x", pady=2)
        ttk.Button(c, text="3. Save results",
                   command=self.save_results).pack(fill="x", pady=2)

    def _build_center(self):
        self.text = tk.Text(self.center, wrap="word", height=40,
                            font=("Consolas", 9))
        bar = ttk.Scrollbar(self.center, orient="vertical",
                            command=self.text.yview)
        self.text.configure(yscrollcommand=bar.set)
        self.text.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self._say("Step 1 reports what the recording can support before "
                  "anything is measured.\n\nOn the lab's pilot images it "
                  "reported that eight of nine calcium measurements were "
                  "impossible, which is the answer worth having first.")

    def _show_probe_note(self):
        try:
            spec = cc.PROBES[cc.normalise_probe(self.v["probe"].get())]
        except cc.CalciumError:
            self.probe_note.config(text="")
            return
        kind = ("ratiometric" if spec["ratiometric"] else "single wavelength")
        rev = "reversible" if spec["reversible"] else "IRREVERSIBLE"
        live = "live" if spec["live"] else "FIXED"
        self.probe_note.config(
            text=f"{spec['readout']}; {kind}; {rev}; {live}."
                 f"\n\n{spec['note']}")

    def _say(self, text, clear=True):
        if clear:
            self.text.delete("1.0", "end")
        self.text.insert("end", text)
        self.text.see("1.0")

    def _choose(self):
        d = filedialog.askdirectory(title="Folder holding the condition "
                                          "subfolders", parent=self)
        if d:
            self.v["folder"].set(d)

    # -- step 1 --------------------------------------------------------
    def run_capability(self):
        probe = self.v["probe"].get()
        n_frames = int(float(self.v["n_frames"].get() or 1))
        bits = int(float(self.v["bit_depth"].get() or 8))
        cap = cc.check_recording(n_frames=n_frames, probe=probe,
                                 bit_depth=bits)
        design = cc.check_two_channel_design(
            signal_channel=self.v["signal_suffix"].get(),
            marker_channel=self.v["marker_suffix"].get(),
            segmentation_channel=self.v["seg_suffix"].get() or None)
        self.capability = {"recording": cap, "design": design}

        lines = [f"PROBE: {probe}  ({cap['readout']})",
                 f"{cap['n_frames']} frame(s), {cap['bit_depth']}-bit\n"]
        ok = [k for k, m in cap["measurements"].items() if m["supported"]]
        no = [k for k, m in cap["measurements"].items() if not m["supported"]]
        lines.append(f"SUPPORTED ({len(ok)}): "
                     + (", ".join(ok) if ok else "none") + "\n")
        if no:
            lines.append(f"NOT SUPPORTED ({len(no)}):")
            for k in no:
                lines.append(f"  {k}")
                for f in cap["measurements"][k]["fails"]:
                    lines.append(f"      - {f}")
            lines.append("")
        for w in cap["warnings"] + design["warnings"]:
            lines.append(f"! {w}\n")
        for n in design["notes"]:
            lines.append(f"  {n}\n")
        self._say("\n".join(lines))
        self.log("Capability checked",
                 f"{len(ok)} supported, {len(no)} not", status="info")
        self.set_status(f"{len(ok)} of {len(ok) + len(no)} measurements "
                        f"supported by this recording.")

    # -- step 2 --------------------------------------------------------
    def run_measure(self):
        import tifffile
        folder = self.v["folder"].get()
        if not folder:
            messagebox.showwarning("No folder", "Choose a data folder first.",
                                   parent=self)
            return
        seg_suffix = self.v["seg_suffix"].get() or None
        pairs, unpaired = cci.load_field_pairs(
            folder,
            signal_suffix=self.v["signal_suffix"].get(),
            marker_suffix=self.v["marker_suffix"].get(),
            segmentation_suffix=seg_suffix)
        if not pairs:
            messagebox.showwarning(
                "Nothing found",
                "No paired channel files. Check the channel suffixes.",
                parent=self)
            return
        thresh = float(self.v["threshold"].get() or 8)
        sat_level = 2 ** int(float(self.v["bit_depth"].get() or 8)) - 1

        fields, field_warnings = [], []
        for cond, stem, chans in pairs:
            sig = tifffile.imread(chans[self.v["signal_suffix"].get()])
            mrk = tifffile.imread(chans[self.v["marker_suffix"].get()])
            seg = (tifffile.imread(chans[seg_suffix])
                   if seg_suffix and seg_suffix in chans else None)
            m = cci.measure_field(sig, mrk, threshold=thresh,
                                  segmentation=seg, saturation_level=sat_level)
            field_warnings.extend(f"{cond}/{stem}: {w}" for w in m["warnings"])
            if m["n_cells"]:
                fields.append({"field": stem, "condition": cond,
                               "signal": m["signal"], "marker": m["marker"]})
        res = cci.analyse_fields(fields)
        self.result = {"analysis": res, "unpaired": unpaired,
                       "field_warnings": field_warnings,
                       "capability": self.capability}
        self._report(res, unpaired, field_warnings)

    def _report(self, res, unpaired, field_warnings):
        lines = []
        n_cells = len(res["cells"])
        n_pos = sum(1 for c in res["cells"] if c["transfected"])
        lines.append(f"{len(res['per_field'])} usable field(s), {n_cells} "
                     f"cells measured, {n_pos} marker-positive "
                     f"({100 * n_pos / max(n_cells, 1):.1f}%)\n")
        if "null" in res:
            nl = res["null"]
            lines.append(
                f"NULL - untransfected cells against their own field median:\n"
                f"  n={nl['n']}, median {nl['median']:.2f}, "
                f"5-95% {nl['p5']:.2f} to {nl['p95']:.2f}\n"
                f"  A treated cell has to sit outside that band to mean\n"
                f"  anything. It is cell-to-cell variation with no treatment.\n")
        lines.append("TRANSFECTED CELLS, each normalised to its own field:")
        lines.append(f"  {'condition':16s} {'cells':>5s} {'fields':>6s} "
                     f"{'median':>7s} {'IQR':>13s} {'in null band':>13s}")
        for cond, s in sorted(res["by_condition"].items()):
            band = ("-" if s["inside_null_band"] is None
                    else f"{s['inside_null_band']}/{s['n_transfected_cells']}")
            iqr = "%.2f-%.2f" % (s["iqr"][0], s["iqr"][1])
            lines.append(
                f"  {cond[:16]:16s} {s['n_transfected_cells']:5d} "
                f"{s['n_fields']:6d} {s['median_normalised']:7.3f} "
                f"{iqr:>13s} {band:>13s}")
        lines.append("")
        bleeds = [f["bleedthrough_r"] for f in res["per_field"]
                  if f["bleedthrough_r"] is not None]
        if bleeds:
            lines.append(f"Bleed-through r across fields: median "
                         f"{np.median(bleeds):+.2f} (positive = suspect)\n")
        for w in res["warnings"]:
            lines.append(f"! {w}\n")
        seen = set()
        for f in res["per_field"]:
            for w in f["warnings"]:
                if w not in seen:
                    seen.add(w)
                    lines.append(f"! {w}\n")
        if res["skipped"]:
            lines.append(f"Skipped {len(res['skipped'])} field(s):")
            lines.extend("    " + s for s in res["skipped"][:12])
            lines.append("")
        if unpaired:
            lines.append(f"Unpaired file(s): {len(unpaired)}")
            lines.extend("    " + s for s in unpaired[:8])
            lines.append("")
        for w in field_warnings[:8]:
            lines.append(f"! {w}")
        lines.append("\n" + res["note"])
        self._say("\n".join(lines))
        self.log("Cells measured",
                 f"{n_cells} cells, {n_pos} transfected", status="edit")
        self.set_status(f"{n_cells} cells across {len(res['per_field'])} "
                        f"fields; {n_pos} marker-positive.")

    # -- step 3 --------------------------------------------------------
    def save_results(self):
        if not self.result:
            messagebox.showwarning("Nothing to save", "Run step 2 first.",
                                   parent=self)
            return
        out_dir = Path(self.v["folder"].get()) / "cell_calcium_results"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        cells = self.result["analysis"]["cells"]
        csv_path = out_dir / f"cells_{stamp}.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(cells[0]) if cells else
                               ["field", "condition", "transfected"])
            w.writeheader()
            w.writerows(cells)
        summary = dict(self.result["analysis"])
        summary.pop("cells", None)
        json_path = out_dir / f"summary_{stamp}.json"
        json_path.write_text(json.dumps(
            {"tool": TOOL_NAME, "version": TOOL_VERSION,
             "probe": self.v["probe"].get(),
             "bit_depth": self.v["bit_depth"].get(),
             "cell_threshold": self.v["threshold"].get(),
             "segmentation_channel": self.v["seg_suffix"].get() or None,
             "written_utc": stamp, "summary": summary,
             "capability": self.result.get("capability")},
            indent=2, default=str), encoding="utf-8")
        self.log("Results saved", str(out_dir), status="edit")
        messagebox.showinfo("Saved", f"{csv_path}\n{json_path}", parent=self)


if __name__ == "__main__":
    App().mainloop()
