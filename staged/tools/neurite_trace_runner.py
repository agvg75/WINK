"""Trace, measure and export neurites from an annotation sidecar.

This is the half of the confocal workflow that needs no viewer. It opens a
sidecar written by the annotation viewer, re-reads the stack beside it, and
does the actual computation: tubeness filtering, path search through the
marked anchors, length, radius and volume - then writes a CSV.

Because it is pure computation it runs on any station in the fleet, and it
can be run again months later with a different expected radius or sigma
without anyone re-marking anything. That is the whole reason marking and
measuring were split.

Also usable from a command line, for batch work:

    python tools/neurite_trace_runner.py path/to/stack_series0.neurites.json
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import confocal_loader as cl               # noqa: E402
import neurite_annotation as na            # noqa: E402
from process_ui import CockpitApp          # noqa: E402

# A neurite is a few voxels across; this is the starting guess for the
# tubeness scale, expressed in lateral pixels so it travels between stacks.
DEFAULT_RADIUS_LATERAL_PX = 3.0


def resolve_stack(sidecar_path, payload):
    """Find the stack a sidecar was made against, beside the sidecar."""
    identity = payload.get("stack_identity", {})
    name = identity.get("name")
    if not name:
        raise na.AnnotationError(
            f"{Path(sidecar_path).name} does not record which stack it was "
            f"made from, so there is nothing to trace against.")
    candidate = Path(sidecar_path).parent / name
    if not candidate.exists():
        raise na.AnnotationError(
            f"The sidecar was made against '{name}', which is not beside it "
            f"in {Path(sidecar_path).parent}.\n\nMove the sidecar next to its "
            f"stack, or copy the stack here - tracing against a different "
            f"file would silently produce the wrong lengths.")
    return candidate, int(identity.get("series_index", 0))


def trace_sidecar(sidecar_path, radius_um=None, strict=True):
    """Load a sidecar, load its stack, trace everything. No GUI anywhere."""
    sidecar_path = Path(sidecar_path)
    _, payload = na.load_annotations(sidecar_path, None)
    stack_path, series = resolve_stack(sidecar_path, payload)
    stack = cl.load_stack(stack_path, series=series, require_calibration=False)
    identity = na.stack_identity(stack_path, series, stack.array.shape,
                                 stack.voxel_size_um)
    annotations, payload = na.load_annotations(sidecar_path, identity,
                                              strict=strict)
    if radius_um is None:
        vox = stack.voxel_size_um
        if vox is None:
            raise na.AnnotationError(
                "This stack has no voxel size, so neither the tracing scale "
                "nor any length it produced would be meaningful.")
        radius_um = float(vox[1]) * DEFAULT_RADIUS_LATERAL_PX
    results = na.trace_annotations(stack, annotations, radius_um=radius_um)
    return results, stack, payload, radius_um


def write_csv(path, results, stack_metadata):
    rows = na.results_to_rows(results, stack_metadata)
    if not rows:
        return None
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


class TraceRunner(CockpitApp):
    def __init__(self):
        super().__init__("WINK - Trace Marked Neurites", geometry="960x640",
                         controls_label="Sidecar and settings",
                         hood_label="Hood: process and notes")
        self.results = None
        self.stack = None
        self.sidecar = None
        self._build_controls()
        self._build_center()
        self.set_help(
            "Trace from marks somebody already made",
            "This tool does the measuring, not the marking. It reads a "
            "sidecar file made in the annotation viewer and computes the "
            "path, length, radius and volume for every neurite in it. It "
            "needs no viewer and no 3D graphics, so it runs on any station - "
            "and running it again with a different expected radius costs no "
            "re-marking.",
            ["Choose the .neurites.json sidecar. Its stack must sit beside it.",
             "Leave the radius blank unless you know the neurite is unusually "
             "thick or thin; the default is 3 lateral pixels.",
             "Trace, then export the CSV.",
             "The raw automatic length is reported next to the corrected one, "
             "so you can see how much the anchors changed."])
        self.set_status("Choose an annotation sidecar to trace.")

    def _build_controls(self):
        c = self.controls
        ttk.Button(c, text="Choose sidecar...",
                   command=self._choose).pack(fill="x", pady=(0, 6))
        self.sidecar_label = ttk.Label(c, text="no sidecar chosen",
                                       wraplength=240)
        self.sidecar_label.pack(anchor="w", pady=(0, 6))

        ttk.Label(c, text="expected radius (um, blank = auto)").pack(anchor="w")
        self.radius_var = tk.StringVar(value="")
        ttk.Entry(c, textvariable=self.radius_var, width=12).pack(fill="x")

        ttk.Button(c, text="trace", command=self._trace).pack(fill="x", pady=(8, 2))
        ttk.Button(c, text="export CSV...", command=self._export).pack(fill="x",
                                                                       pady=2)

    def _build_center(self):
        self.table = tk.Text(self.center, wrap="none", height=24)
        self.table.pack(fill="both", expand=True)
        self.table.insert("1.0", "No results yet.\n")
        self.table.configure(state="disabled")

    def _choose(self):
        path = filedialog.askopenfilename(
            title="Choose an annotation sidecar",
            filetypes=[("Neurite sidecar", "*.neurites.json"),
                       ("JSON", "*.json"), ("All files", "*.*")], parent=self)
        if not path:
            return
        self.sidecar = Path(path)
        self.sidecar_label.configure(text=self.sidecar.name)
        self.log("Sidecar chosen", self.sidecar.name)
        self.set_status("Press 'trace'.")

    def _trace(self):
        if self.sidecar is None:
            messagebox.showwarning("No sidecar",
                                   "Choose a .neurites.json sidecar first.", parent=self)
            return
        radius = self.radius_var.get().strip()
        try:
            radius_um = float(radius) if radius else None
        except ValueError:
            messagebox.showwarning(
                "Radius not a number",
                f"'{radius}' is not a number. Leave it blank to use the "
                f"default of {DEFAULT_RADIUS_LATERAL_PX:.0f} lateral pixels.", parent=self)
            return
        try:
            with self.process_log.timed("Trace", self.sidecar.name):
                self.results, self.stack, payload, used = trace_sidecar(
                    self.sidecar, radius_um=radius_um)
        except na.AnnotationError as exc:
            self.log("Refused", str(exc).splitlines()[0], status="failed")
            messagebox.showerror("Cannot trace this sidecar", str(exc), parent=self)
            return
        self.log("Radius used", f"{used:.3f} um")
        if payload.get("written_on_station"):
            self.log("Marked on", str(payload["written_on_station"]))
        for note in self.stack.preflight_warnings():
            self.log("Preflight", note, status="warn")
        self._show_results()
        self.set_status(f"Traced {len(self.results)} neurite(s). Export the CSV "
                        f"when you are happy with it.")

    def _show_results(self):
        header = (f"{'neurite':<12}{'label':<16}{'length um':>11}"
                  f"{'raw um':>10}{'anchors':>9}{'radius um':>11}"
                  f"{'volume um3':>12}")
        lines = [header, "-" * len(header)]
        for r in self.results:
            lines.append(
                f"{r['neurite_id']:<12}{(r['label'] or '-'):<16}"
                f"{r['length_um']:>11.2f}{r['raw_length_um']:>10.2f}"
                f"{r['n_anchors']:>9}{r.get('median_radius_um', 0):>11.3f}"
                f"{r.get('volume_um3', 0):>12.2f}")
        lines += ["", "'raw um' is the automatic path with the anchors ignored.",
                  "A large gap between the two means the correction mattered.",
                  "", self.results[0].get("radius_note", "")]
        self.table.configure(state="normal")
        self.table.delete("1.0", "end")
        self.table.insert("1.0", "\n".join(lines))
        self.table.configure(state="disabled")

    def _export(self):
        if not self.results:
            messagebox.showwarning("Nothing to export", "Trace something first.", parent=self)
            return
        default = self.sidecar.with_suffix("").name + "_traced.csv"
        path = filedialog.asksaveasfilename(
            title="Export traced neurites", defaultextension=".csv",
            initialfile=default, filetypes=[("CSV", "*.csv")], parent=self)
        if not path:
            return
        write_csv(path, self.results, self.stack.metadata)
        self.log("Exported", str(path), status="ok")
        self.set_status(f"Wrote {Path(path).name}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sidecar", nargs="?",
                        help="a .neurites.json sidecar; omit for the window")
    parser.add_argument("--radius-um", type=float, default=None)
    parser.add_argument("--csv", default=None, help="where to write results")
    args = parser.parse_args(argv)

    if not args.sidecar:
        TraceRunner().mainloop()
        return 0
    results, stack, _payload, used = trace_sidecar(args.sidecar,
                                                   radius_um=args.radius_um)
    print(f"radius {used:.3f} um, {len(results)} neurite(s)")
    for r in results:
        print(f"  {r['neurite_id']:<12} {r['length_um']:>9.2f} um  "
              f"(raw {r['raw_length_um']:.2f}, {r['n_anchors']} anchor(s))")
    out = args.csv or str(Path(args.sidecar).with_suffix("")) + "_traced.csv"
    write_csv(out, results, stack.metadata)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
