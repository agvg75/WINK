"""Propose body-wall myocyte boundaries in a confocal stack, for a human to judge.

WHAT THIS IS FOR. Myocyte morphometry currently needs a hand-drawn boundary per
cell, which is the slow step and the one nobody enjoys. This proposes those
boundaries from the image so the job becomes correcting rather than drawing.

WHAT IT IS NOT. It does not measure anything and it does not decide where a
myocyte ends. Every line it draws is a proposal, and the moment proposals are
shown, marks made against them stop being clean ground truth - so if unassisted
marks are still being collected for validation, collect them BEFORE opening a
stack in here.

HOW IT WORKS, and why it is not the obvious thing. A myocyte boundary is not an
intensity edge - phalloidin labels actin, so both sides of a border are bright.
What marks a boundary is where fibres END: actin inserts at the edge of a cell,
and at the two ends of a cell many fibres converge on a point. So boundaries are
found from traced individual fibres, not from brightness.

ACCURACY, MEASURED against hand marks on two fields and stated plainly because
a number with no provenance invites more trust than it has earned:
    midbody   83.5% of hand-marked boundary within 2 um, median error 0.99 um
    head      57.9%,                                     median error 1.37 um
Both are single fields from one animal each. The midbody figure is out-of-sample
(that field informed no design choice); the head figure is not. Expect worse on
anything unlike them, and check the overlay before trusting any of it.
"""
from __future__ import annotations

import json
import re
import sys
import traceback
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
for extra in (ROOT / "tools", ROOT / "app"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

TOOL_NAME = "myocyte_boundary_proposer"
TOOL_VERSION = "1.0"

# Order matters: "anterior to vulva" is a MIDBODY field and would otherwise be
# caught by the head pattern's "anterior".
REGION_PATTERNS = (
    ("midbody", r"anterior to vulva|midbody|vulva|medial|\bmid\b"),
    ("head", r"\bhead\b|\banterior\b|pharyn"),
    ("posterior", r"\btail\b|posterior"),
)


def infer_region(*names):
    """Guess head / midbody / posterior from file and series names.

    The lab records the region in its file names, so this is reading a fact
    rather than predicting one. It still returns None when nothing matches,
    because guessing a region silently would change the analysis parameters
    with no outward sign.

    Underscores become spaces first. In a regular expression "_" is a WORD
    character, so \\bhead\\b does NOT match inside "ventral_head" - and the miss
    is silent, falling back to defaults that are wrong for the region. The
    lab's file names are underscore-delimited throughout, so this is the
    normal case rather than an edge one.
    """
    blob = " ".join(str(n) for n in names if n).lower()
    blob = re.sub(r"[_\-]+", " ", blob)
    for region, pattern in REGION_PATTERNS:
        if re.search(pattern, blob):
            return region
    return None


def analyse(stack, series_name="", file_name="", region=None, z_half=8,
            n_seams=8, use_vertices=True):
    """Run the detector on a loaded ConfocalStack. Returns a result dict.

    Raises ValueError with a reason a human can act on when the stack carries
    no channel of aligned fibrous signal - measuring anyway would report
    whatever channel has the most texture, typically transmitted light, as
    muscle architecture.
    """
    import fibre_orientation as fo
    import fibre_trace as ft

    channel, report = fo.pick_actin_channel(stack.array)
    if channel is None:
        raise ValueError(
            report.get("refusal", "No channel carries aligned fibrous signal.")
            + "\n\nPer-channel numbers:\n"
            + "\n".join(
                f"  ch{c['channel']}: p99={c['p99']:.0f} "
                f"coherence={c['coherence']:.3f} - {c.get('rejected_because')}"
                for c in report["channels"]))

    if region is None:
        region = infer_region(file_name, series_name)
    dz, dy, dx = stack.voxel_size_um
    nz = stack.n_z
    z0 = max(nz // 2 - z_half, 0)
    z1 = min(nz // 2 + z_half, nz)
    vol = stack.channel(channel)[z0:z1].astype(float)
    proj = vol.max(axis=0)
    H, W = proj.shape

    angles, coherence = fo.orientation_volume(vol, sigma=1.5, rho=6.0)
    ev = ft.boundary_evidence(proj, angles, coherence, dx, region=region)
    seams, scores = fo.trace_seams(
        ev["combined"], n_seams=n_seams,
        min_separation_px=max(int(2.5 / dx), 3), max_slope=1)

    vertices, pairs, linked = np.empty((0, 2)), [], []
    if use_vertices:
        vote, _ = ft.convergence_vote(angles, coherence, dx, reach_um=25.0)
        m = int(6.0 / dx)
        if m > 0:
            vote[:, :m] = 0; vote[:, -m:] = 0
            vote[:m, :] = 0; vote[-m:, :] = 0
        vertices, vscores = ft.find_vertices(vote, dx, min_separation_um=8.0,
                                             max_vertices=40)
        pairs = ft.pair_vertices(vertices, vscores, angles, coherence, dx,
                                 min_length_um=15.0, max_length_um=140.0,
                                 max_offset_um=14.0)
        for p in pairs:
            (ay, ax), (by, bx) = p["a"], p["b"]
            if ax > bx:
                (ay, ax), (by, bx) = (by, bx), (ay, ax)
            if bx - ax < 8:
                continue
            guide = np.interp(np.arange(W), [ax, bx], [ay, by])
            path, sc = fo.trace_seam_guided(ev["combined"], guide, prior_um=6.0,
                                            um_per_px=dx, max_slope=2,
                                            x0=ax, x1=bx)
            linked.append({"x0": int(ax), "x1": int(bx), "y": path,
                           "score": float(sc),
                           "length_um": float(p["length_um"])})

    return {
        "projection": proj, "evidence": ev, "channel": channel,
        "channel_report": report, "region": region,
        "voxel_size_um": (dz, dy, dx), "z_range": (z0, z1), "n_z": nz,
        "seams": seams, "seam_scores": scores,
        "vertices": vertices, "pairs": pairs, "linked": linked,
        "min_segment_um": ev.get("min_segment_um"),
        "n_endpoints": ev.get("n_endpoints"),
    }


def provenance(result, source, series_index, series_name):
    dz, dy, dx = result["voxel_size_um"]
    return {
        "tool": TOOL_NAME, "tool_version": TOOL_VERSION,
        "source": str(source), "series_index": series_index,
        "series_name": series_name,
        "region": result["region"],
        "region_source": "inferred from name" if result["region"] else "unknown",
        "actin_channel": int(result["channel"]),
        "voxel_size_um": {"z": dz, "y": dy, "x": dx},
        "z_range_used": list(result["z_range"]), "n_z_total": result["n_z"],
        "min_segment_um": result["min_segment_um"],
        "n_fibre_endpoints": result["n_endpoints"],
        "n_seams": len(result["seams"]),
        "n_vertices": int(len(result["vertices"])),
        "n_vertex_linked": len(result["linked"]),
        "cue_combiner": result["evidence"].get("combiner"),
        "these_are_proposals": True,
        "measured_anything": False,
        "accuracy_note": (
            "Against hand marks on single fields: midbody 83.5% within 2 um "
            "(median 0.99 um, out-of-sample); head 57.9% (median 1.37 um, "
            "in-sample). One animal per region. Check the overlay."),
    }


def write_outputs(out_dir, base, result, prov):
    """CSV of proposed boundary paths, an overlay PNG, and provenance JSON."""
    import csv
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dz, dy, dx = result["voxel_size_um"]
    proj = result["projection"]
    H, W = proj.shape

    csv_path = out_dir / f"{base}_boundary_proposals.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["path_id", "kind", "x_px", "y_px", "x_um", "y_um", "score"])
        for i, (p, sc) in enumerate(zip(result["seams"], result["seam_scores"])):
            for x in range(W):
                w.writerow([f"seam_{i}", "free", x, int(p[x]),
                            f"{x * dx:.4f}", f"{p[x] * dy:.4f}", f"{sc:.5f}"])
        for j, seg in enumerate(result["linked"]):
            for k, x in enumerate(range(seg["x0"], seg["x1"])):
                w.writerow([f"linked_{j}", "vertex_linked", x, int(seg["y"][k]),
                            f"{x * dx:.4f}", f"{seg['y'][k] * dy:.4f}",
                            f"{seg['score']:.5f}"])

    vtx_path = out_dir / f"{base}_vertices.csv"
    with vtx_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["vertex_id", "y_px", "x_px", "y_um", "x_um"])
        for i, (vy, vx) in enumerate(np.asarray(result["vertices"])):
            w.writerow([i, int(vy), int(vx), f"{vy * dy:.4f}", f"{vx * dx:.4f}"])

    fig, ax = plt.subplots(figsize=(min(W / 110, 22), max(H / 110, 2.4)), dpi=130)
    ax.imshow(proj, cmap="gray", vmax=np.percentile(proj, 99.5),
              extent=[0, W * dx, H * dy, 0], aspect="auto")
    xs = np.arange(W)
    for p in result["seams"]:
        ax.plot(xs * dx, p * dy, lw=1.2, color="#4DD0E1")
    for seg in result["linked"]:
        ax.plot(np.arange(seg["x0"], seg["x1"]) * dx, seg["y"] * dy, lw=1.2,
                color="#7CFC00")
    if len(result["vertices"]):
        v = np.asarray(result["vertices"])
        ax.plot(v[:, 1] * dx, v[:, 0] * dy, "x", ms=7, color="#FF3B3B", mew=1.6)
    ax.set_title(f"{base} - PROPOSALS, not measurements  "
                 f"(region: {result['region'] or 'unknown'}, "
                 f"ch{result['channel']})", fontsize=9, loc="left")
    ax.set_xlabel("um", fontsize=8)
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    png_path = out_dir / f"{base}_boundary_overlay.png"
    fig.savefig(png_path, dpi=130, facecolor="white")
    plt.close(fig)

    prov_path = out_dir / f"{base}_provenance.json"
    prov_path.write_text(json.dumps(prov, indent=2), encoding="utf-8")
    return {"csv": csv_path, "vertices": vtx_path, "overlay": png_path,
            "provenance": prov_path}


# --------------------------------------------------------------------------- #
# Tk interface
# --------------------------------------------------------------------------- #
def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    import confocal_loader as cl

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("Myocyte boundary proposer")
            self.geometry("1180x760")
            self.path = None
            self.series = []
            self.stack = None
            self.result = None
            self._build()

        def _build(self):
            top = ttk.Frame(self, padding=8)
            top.pack(fill="x")
            ttk.Button(top, text="Open stack...", command=self.open_file
                       ).pack(side="left")
            self.lbl_file = ttk.Label(top, text="no file loaded")
            self.lbl_file.pack(side="left", padx=10)

            mid = ttk.Frame(self, padding=(8, 0))
            mid.pack(fill="both", expand=True)
            left = ttk.Frame(mid)
            left.pack(side="left", fill="y")
            ttk.Label(left, text="Series (one acquisition = one animal)"
                      ).pack(anchor="w")
            self.series_list = tk.Listbox(left, width=54, height=14,
                                          exportselection=False)
            self.series_list.pack(fill="y", expand=False, pady=4)

            opts = ttk.LabelFrame(left, text="Options", padding=6)
            opts.pack(fill="x", pady=6)
            ttk.Label(opts, text="Region").grid(row=0, column=0, sticky="w")
            self.region_var = tk.StringVar(value="auto")
            ttk.Combobox(opts, textvariable=self.region_var, width=14,
                         values=("auto", "midbody", "head", "posterior"),
                         state="readonly").grid(row=0, column=1, sticky="w")
            self.vert_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(opts, text="also link vertex pairs",
                            variable=self.vert_var).grid(row=1, column=0,
                                                         columnspan=2, sticky="w")
            ttk.Button(left, text="Propose boundaries", command=self.run
                       ).pack(fill="x", pady=(2, 4))
            ttk.Button(left, text="Save proposals...", command=self.save
                       ).pack(fill="x")

            self.info = tk.Text(left, width=54, height=13, wrap="word")
            self.info.pack(fill="both", expand=True, pady=6)
            self.info.insert("1.0",
                             "Proposals only. Nothing here is a measurement, "
                             "and no myocyte boundary is decided by this tool.\n\n"
                             "If unassisted marks are still being collected as "
                             "validation data, collect them BEFORE viewing "
                             "proposals for that stack.")
            self.info.configure(state="disabled")

            self.canvas_frame = ttk.Frame(mid)
            self.canvas_frame.pack(side="left", fill="both", expand=True,
                                   padx=(8, 0))
            self.canvas = None

        def _say(self, text):
            self.info.configure(state="normal")
            self.info.delete("1.0", "end")
            self.info.insert("1.0", text)
            self.info.configure(state="disabled")

        def open_file(self):
            p = filedialog.askopenfilename(
                title="Open a confocal stack",
                filetypes=[("Confocal stacks",
                            "*.lif *.czi *.nd2 *.tif *.tiff"), ("All", "*.*")])
            if not p:
                return
            self.path = Path(p)
            self.lbl_file.configure(text=self.path.name)
            self.series_list.delete(0, "end")
            try:
                self.series = cl.list_series(self.path)
            except Exception as exc:
                messagebox.showerror("Could not read the file", str(exc))
                return
            for s in self.series:
                z, c, y, x = s.shape_zcyx
                tag = "" if z > 1 else "  [single plane - not a stack]"
                self.series_list.insert("end", f"[{s.index}] {s.name}  "
                                               f"{z}z x {c}c x {y} x {x}{tag}")
            self._say(f"{len(self.series)} series. Each is a separate "
                      f"acquisition, so a file usually holds several animals - "
                      f"pick one.\n\nRegion will be read from the file and "
                      f"series names unless you override it.")

        def run(self):
            sel = self.series_list.curselection()
            if not sel:
                messagebox.showinfo("Pick a series",
                                    "Select one series first. A file holds "
                                    "several acquisitions and they are not "
                                    "interchangeable.")
                return
            info = self.series[sel[0]]
            if info.shape_zcyx[0] <= 1:
                messagebox.showwarning(
                    "Single plane",
                    "That series has one z plane, so it is an exported "
                    "snapshot rather than a stack. Fibre orientation is "
                    "computed per plane and depth carries the convergence "
                    "cue, so results would not mean what they usually do.")
                return
            try:
                self.stack = cl.load_stack(self.path, series=info.index)
            except Exception as exc:
                messagebox.showerror("Could not load", str(exc))
                return
            region = None if self.region_var.get() == "auto" else self.region_var.get()
            try:
                self.result = analyse(self.stack, series_name=info.name,
                                      file_name=self.path.name, region=region,
                                      use_vertices=self.vert_var.get())
            except ValueError as exc:
                messagebox.showwarning("Refused", str(exc))
                self._say(str(exc))
                return
            except Exception:
                messagebox.showerror("Failed", traceback.format_exc())
                return
            r = self.result
            warn = "\n".join(f"! {w}" for w in self.stack.preflight_warnings())
            self._say(
                f"region: {r['region'] or 'UNKNOWN - name matched nothing'}\n"
                f"actin channel: ch{r['channel']}\n"
                f"z planes used: {r['z_range'][0]}-{r['z_range'][1]} of {r['n_z']}\n"
                f"fibre endpoints: {r['n_endpoints']}  "
                f"(min segment {r['min_segment_um']} um)\n"
                f"proposals: {len(r['seams'])} free paths, "
                f"{len(r['linked'])} vertex-linked, "
                f"{len(r['vertices'])} vertices\n\n"
                f"These are PROPOSALS. Check every one against the image.\n"
                + (f"\n{warn}" if warn else ""))
            self._draw()

        def _draw(self):
            import matplotlib
            matplotlib.use("TkAgg")
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure

            for w in self.canvas_frame.winfo_children():
                w.destroy()
            r = self.result
            dz, dy, dx = r["voxel_size_um"]
            proj = r["projection"]
            H, W = proj.shape
            fig = Figure(figsize=(8, 6), dpi=100)
            ax = fig.add_subplot(111)
            ax.imshow(proj, cmap="gray", vmax=np.percentile(proj, 99.5),
                      extent=[0, W * dx, H * dy, 0], aspect="auto")
            xs = np.arange(W)
            for p in r["seams"]:
                ax.plot(xs * dx, p * dy, lw=1.1, color="#4DD0E1")
            for seg in r["linked"]:
                ax.plot(np.arange(seg["x0"], seg["x1"]) * dx, seg["y"] * dy,
                        lw=1.1, color="#7CFC00")
            if len(r["vertices"]):
                v = np.asarray(r["vertices"])
                ax.plot(v[:, 1] * dx, v[:, 0] * dy, "x", ms=6, color="#FF3B3B",
                        mew=1.4)
            ax.set_title("PROPOSALS - cyan free, green vertex-linked, "
                         "red x vertices", fontsize=9, loc="left")
            ax.set_xlabel("um", fontsize=8)
            ax.tick_params(labelsize=7)
            fig.tight_layout()
            self.canvas = FigureCanvasTkAgg(fig, master=self.canvas_frame)
            self.canvas.draw()
            self.canvas.get_tk_widget().pack(fill="both", expand=True)

        def save(self):
            if not self.result:
                messagebox.showinfo("Nothing to save", "Propose boundaries first.")
                return
            d = filedialog.askdirectory(title="Where should the proposals go?")
            if not d:
                return
            sel = self.series_list.curselection()
            info = self.series[sel[0]]
            base = f"{self.path.stem}_s{info.index}"
            prov = provenance(self.result, self.path, info.index, info.name)
            try:
                written = write_outputs(d, base, self.result, prov)
            except Exception:
                messagebox.showerror("Could not save", traceback.format_exc())
                return
            messagebox.showinfo(
                "Saved",
                "\n".join(str(v) for v in written.values())
                + "\n\nThe CSV holds PROPOSALS. Nothing was measured.")

    App().mainloop()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    run_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
