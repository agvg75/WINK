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
# Resolution used for DETECTION, per region. Measured against the hand-marked
# fields - recall, then time on a cropped field:
#     scale   midbody              head
#     1.00    80.1%  23.3s         45.8%   7.5s
#     0.75    74.3%   9.4s         46.9%   4.5s
#     0.50    69.0%   4.8s         56.0%   1.7s
#     0.35    68.0%   2.2s         59.7%   1.0s
# Midbody loses 11 points at half scale; head GAINS 14, because downsampling
# averages away the speckle that fragments its fibres - the same noise the
# 2 um minimum-segment filter compensates for there. So this is the fourth
# parameter that wants opposite values by region, and a single default would
# be wrong for one of them whichever way it went.
DETECT_SCALE = {"midbody": 1.0, "head": 0.5, "posterior": 0.5, None: 0.75}

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
            n_seams=8, use_vertices=True, auto_rotate=True,
            detect_scale=None, progress=None):
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

    say = progress or (lambda _frac, _msg: None)
    if region is None:
        region = infer_region(file_name, series_name)
    dz, dy, dx = stack.voxel_size_um
    nz = stack.n_z
    z0 = max(nz // 2 - z_half, 0)
    z1 = min(nz // 2 + z_half, nz)
    vol = stack.channel(channel)[z0:z1].astype(float)

    # Work in the ANIMAL's frame. Everything below is stated "along the body
    # axis" - the seam tracer walks image columns one pixel of y at a time -
    # so a worm mounted diagonally makes it walk across background and return
    # confident nonsense. Rotating first is not cosmetic; it is the assumption
    # the rest of the code has always made, finally made true.
    frame = {"rotated": False, "reason": "auto-rotation not requested"}
    transform = None
    if auto_rotate:
        import animal_frame as afr
        try:
            vol, transform, frame = afr.align(vol)
            # Trim the padding rotation added. Without this a seam spanning the
            # full width crosses empty canvas and maps to coordinates outside
            # the source image - and it is also the crop this tool otherwise
            # lacks, so the analysis runs on the animal, not the whole field.
            vol, transform = afr.trim_to_tissue(vol, transform,
                                                um_per_px=stack.voxel_size_um[2])
            frame["trimmed_to"] = transform.get("cropped_shape")
        except afr.FrameError as exc:
            frame = {"rotated": False, "reason": f"not rotated: {exc}"}
            transform = None

    # DETECTION RESOLUTION. The ridge filter is ~70% of the wall clock and
    # scales with pixel count, so this is the difference between four minutes
    # and one. It is not free accuracy-wise, and which way it costs depends on
    # the region - see DETECT_SCALE.
    if detect_scale is None:
        detect_scale = DETECT_SCALE.get(region, DETECT_SCALE[None])
    detect_scale = float(detect_scale)
    scale_note = ""
    if abs(detect_scale - 1.0) > 1e-6:
        from scipy import ndimage as ndi
        say(0.25, f"downsampling to {detect_scale:.2f} for detection")
        vol = np.stack([ndi.zoom(p, detect_scale, order=1) for p in vol])
        dx = dx / detect_scale
        dy = dy / detect_scale
        scale_note = (f"detected at {detect_scale:.2f} scale; positions are "
                      f"reported at full resolution")
        if transform is not None:
            transform = dict(transform, detect_scale=detect_scale)

    proj = vol.max(axis=0)
    H, W = proj.shape

    say(0.35, "measuring fibre orientation")
    angles, coherence = fo.orientation_volume(vol, sigma=1.5, rho=6.0)
    say(0.5, "tracing individual fibres (the slow part)")
    ev = ft.boundary_evidence(proj, angles, coherence, dx, region=region)
    say(0.8, "tracing boundaries")
    seams, scores = fo.trace_seams(
        ev["combined"], n_seams=n_seams,
        min_separation_px=max(int(2.5 / dx), 3), max_slope=1)

    vertices, pairs, linked = np.empty((0, 2)), [], []
    if use_vertices:
        say(0.85, "finding myocyte ends")
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
        "frame": frame, "transform": transform,
        "detect_scale": detect_scale, "scale_note": scale_note,
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
        "frame": {k: v for k, v in (result.get("frame") or {}).items()},
        "analysed_in_animal_frame": bool((result.get("frame") or {}).get("rotated")),
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

    # Positions are written in BOTH frames. The rotated frame is where the
    # analysis happened; the original is where the file's own coordinates live,
    # and a boundary that cannot be pointed at in the source image is not much
    # use to anyone checking it.
    tf = result.get("transform")
    afr = None
    if tf is not None:
        import animal_frame as afr

    def to_source(ys, xs):
        if tf is None or afr is None:
            return list(zip(ys, xs))
        pts = afr.points_to_original(np.stack([ys, xs], axis=1), tf)
        return [(p[0], p[1]) for p in pts]

    csv_path = out_dir / f"{base}_boundary_proposals.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["path_id", "kind", "x_px", "y_px", "x_um", "y_um",
                    "source_x_px", "source_y_px", "score"])
        for i, (p, sc) in enumerate(zip(result["seams"], result["seam_scores"])):
            xs = np.arange(W)
            src = to_source(np.asarray(p, dtype=float), xs.astype(float))
            for x in range(W):
                sy, sx = src[x]
                w.writerow([f"seam_{i}", "free", x, int(p[x]),
                            f"{x * dx:.4f}", f"{p[x] * dy:.4f}",
                            f"{sx:.2f}", f"{sy:.2f}", f"{sc:.5f}"])
        for j, seg in enumerate(result["linked"]):
            xs = np.arange(seg["x0"], seg["x1"], dtype=float)
            src = to_source(np.asarray(seg["y"], dtype=float), xs)
            for k, x in enumerate(range(seg["x0"], seg["x1"])):
                sy, sx = src[k]
                w.writerow([f"linked_{j}", "vertex_linked", x, int(seg["y"][k]),
                            f"{x * dx:.4f}", f"{seg['y'][k] * dy:.4f}",
                            f"{sx:.2f}", f"{sy:.2f}", f"{seg['score']:.5f}"])

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


def write_review(out_dir, base, state):
    """Write the reviewed boundaries, the correction log, and the measurements.

    Three files rather than one, because they mean different things. The
    measurements are what a human approved; the review JSON is the full state
    including rejections; the correction log is the record of how far the
    detector was off, which is TUNING data - agreement with a proposal a
    reviewer was shown is not independent validation of it.
    """
    import csv
    import json

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    review_path = out_dir / f"{base}_review.json"
    review_path.write_text(json.dumps(state.to_dict(), indent=2),
                           encoding="utf-8")

    rows = state.measure()
    meas_path = out_dir / f"{base}_reviewed_boundaries.csv"
    with meas_path.open("w", newline="", encoding="utf-8") as fh:
        if rows:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        else:
            fh.write("no boundaries survived review\n")

    log_path = out_dir / f"{base}_corrections.csv"
    with log_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["n", "intent", "description", "timestamp"])
        for n, e in enumerate(state.correction_log, 1):
            w.writerow([n, e["intent"], e["description"], e["timestamp"]])

    prov_path = out_dir / f"{base}_review_provenance.json"
    prov_path.write_text(json.dumps(state.to_provenance(), indent=2),
                         encoding="utf-8")
    return {"review": review_path, "measurements": meas_path,
            "corrections": log_path, "review_provenance": prov_path}


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
            self.state = None          # review state; None until proposals exist
            self.selected = None
            self.drag = None
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
            self.run_btn = ttk.Button(left, text="Propose boundaries",
                                      command=self.run)
            self.run_btn.pack(fill="x", pady=(2, 4))
            # Created here but only packed while working, so an idle window
            # does not carry a permanently empty progress bar.
            self.progress = ttk.Progressbar(left, mode="determinate", maximum=100)
            self.save_btn = ttk.Button(left, text="Save proposals and review...",
                                       command=self.save)
            self.save_btn.pack(fill="x")

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
            self._run_in_background(info, region)

        def _run_in_background(self, info, region):
            """Detection takes minutes; it must not run on the UI thread.

            Previously it did, so the window stopped repainting and Windows
            marked it 'Not Responding' - indistinguishable from a crash, and
            the honest answer to "is it still working?" was unavailable to the
            person asking it. The worker only ever posts messages back through
            a queue; Tk is touched from the main thread alone, because calling
            into it from a worker fails intermittently rather than reliably.
            """
            import queue
            import threading

            self.progress_q = queue.Queue()
            self.cancelled = threading.Event()
            self._show_busy(True)

            def report(frac, msg):
                self.progress_q.put(("progress", frac, msg))

            def work():
                try:
                    res = analyse(self.stack, series_name=info.name,
                                  file_name=self.path.name, region=region,
                                  use_vertices=self.vert_var.get(),
                                  progress=report)
                    self.progress_q.put(("done", res, None))
                except ValueError as exc:
                    self.progress_q.put(("refused", None, str(exc)))
                except Exception:
                    self.progress_q.put(("error", None, traceback.format_exc()))

            threading.Thread(target=work, daemon=True).start()
            self.after(80, self._poll_progress)

        def _show_busy(self, busy):
            state = "disabled" if busy else "normal"
            for w in (self.run_btn, self.save_btn):
                try:
                    w.configure(state=state)
                except Exception:
                    pass
            if busy:
                self.progress.configure(value=0)
                self.progress.pack(fill="x", pady=(2, 4))
            else:
                self.progress.pack_forget()

        def _poll_progress(self):
            import queue
            try:
                while True:
                    kind, a, b = self.progress_q.get_nowait()
                    if kind == "progress":
                        self.progress.configure(value=max(2, int(a * 100)))
                        self._say(f"Working... {int(a * 100)}%\n\n{b}\n\n"
                                  f"Detection takes from a few seconds to a "
                                  f"few minutes depending on field size and "
                                  f"region. The window stays responsive.")
                    elif kind == "done":
                        self.result = a
                        self.state = None
                        self.selected = None
                        self.drag = None
                        self._show_busy(False)
                        self._finish_run()
                        return
                    elif kind == "refused":
                        self._show_busy(False)
                        messagebox.showwarning("Refused", b)
                        self._say(b)
                        return
                    else:
                        self._show_busy(False)
                        messagebox.showerror("Failed", b)
                        return
            except queue.Empty:
                pass
            self.after(80, self._poll_progress)

        def _finish_run(self):
            r = self.result
            warn = "\n".join(f"! {w}" for w in self.stack.preflight_warnings())
            fr = r.get("frame") or {}
            self._say(
                f"frame: {fr.get('reason', 'n/a')}"
                + (f"  (axis {fr.get('axis_angle_deg')} deg, "
                   f"elongation {fr.get('elongation')})" if fr.get("axis_angle_deg")
                   is not None else "") + "\n"
                f"region: {r['region'] or 'UNKNOWN - name matched nothing'}\n"
                f"actin channel: ch{r['channel']}\n"
                f"z planes used: {r['z_range'][0]}-{r['z_range'][1]} of {r['n_z']}\n"
                f"detection scale: {r.get('detect_scale', 1.0):.2f}"
                + (f"  ({r['scale_note']})" if r.get("scale_note") else "") + "\n"
                f"fibre endpoints: {r['n_endpoints']}  "
                f"(min segment {r['min_segment_um']} um)\n"
                f"proposals: {len(r['seams'])} free paths, "
                f"{len(r['linked'])} vertex-linked, "
                f"{len(r['vertices'])} vertices\n\n"
                f"These are PROPOSALS. Check every one against the image.\n"
                + (f"\n{warn}" if warn else ""))
            self._draw()

        def _start_review(self):
            """Seed the review state from the proposals, thinned to control points.

            The traced paths carry one point per image column - two thousand of
            them - which nobody can edit. They are thinned to control points a
            human can actually grab. The full-resolution path is NOT what gets
            reviewed, because a boundary a reviewer cannot move is a boundary
            they will accept by default.
            """
            import myocyte_review_state as mrs

            r = self.result
            dz, dy, dx = r["voxel_size_um"]
            H, W = r["projection"].shape
            step = max(W // 24, 1)
            proposals = []
            for i, p in enumerate(r["seams"]):
                xs = list(range(0, W, step))
                if xs[-1] != W - 1:
                    xs.append(W - 1)
                proposals.append((f"seam_{i}", [(x, float(p[x])) for x in xs]))
            for j, seg in enumerate(r["linked"]):
                xs = list(range(seg["x0"], seg["x1"], step)) or [seg["x0"]]
                if xs[-1] != seg["x1"] - 1:
                    xs.append(seg["x1"] - 1)
                proposals.append((f"linked_{j}",
                                  [(x, float(seg["y"][x - seg["x0"]])) for x in xs]))
            self.state = mrs.MyocyteReviewState(
                (H, W), dx, self.path, self._series_name(), r["region"],
                f"{TOOL_NAME} {TOOL_VERSION}")
            self.state.add_proposals(proposals)
            self.selected = None
            self.drag = None

        def _series_name(self):
            sel = self.series_list.curselection()
            return self.series[sel[0]].name if sel else ""

        def _draw(self):
            import matplotlib
            matplotlib.use("TkAgg")
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure

            if getattr(self, "state", None) is None:
                self._start_review()
            for w in self.canvas_frame.winfo_children():
                w.destroy()
            r = self.result
            dz, dy, dx = r["voxel_size_um"]
            proj = r["projection"]
            H, W = proj.shape
            fig = Figure(figsize=(8, 6), dpi=100)
            self.ax = fig.add_subplot(111)
            self.fig = fig
            self._render()
            self.canvas = FigureCanvasTkAgg(fig, master=self.canvas_frame)
            self.canvas.mpl_connect("button_press_event", self._on_press)
            self.canvas.mpl_connect("motion_notify_event", self._on_motion)
            self.canvas.mpl_connect("button_release_event", self._on_release)
            self.canvas.mpl_connect("key_press_event", self._on_key)
            self.canvas.draw()
            w = self.canvas.get_tk_widget()
            w.pack(fill="both", expand=True)
            w.focus_set()

        STATUS_COLOUR = {"proposed": "#4DD0E1", "edited": "#FFD166",
                         "accepted": "#7CFC00", "rejected": "#FF5E5B"}

        def _render(self):
            r = self.result
            dz, dy, dx = r["voxel_size_um"]
            proj = r["projection"]
            H, W = proj.shape
            ax = self.ax
            ax.clear()
            ax.imshow(proj, cmap="gray", vmax=np.percentile(proj, 99.5),
                      extent=[0, W * dx, H * dy, 0], aspect="auto")
            for b in self.state.boundaries.values():
                pts = np.asarray(b.points, dtype=float)
                col = self.STATUS_COLOUR.get(b.status, "#FFFFFF")
                sel = (b.boundary_id == self.selected)
                ls = "--" if b.status == "rejected" else "-"
                ax.plot(pts[:, 0] * dx, pts[:, 1] * dy, ls, lw=2.2 if sel else 1.2,
                        color=col, alpha=0.55 if b.status == "rejected" else 1.0)
                if sel:
                    ax.plot(pts[:, 0] * dx, pts[:, 1] * dy, "o", ms=5,
                            mfc="none", mec=col, mew=1.4)
            s = self.state.summary()
            ax.set_title(
                f"{s['by_status'].get('proposed', 0)} unjudged   "
                f"{s['by_status'].get('accepted', 0)} accepted   "
                f"{s['by_status'].get('edited', 0)} edited   "
                f"{s['by_status'].get('rejected', 0)} rejected"
                + (f"   |  selected: {self.selected}" if self.selected else
                   "   |  click a boundary to select"),
                fontsize=9, loc="left")
            ax.set_xlabel("um", fontsize=8)
            ax.tick_params(labelsize=7)
            self.fig.tight_layout()

        def _nearest(self, ex, ey):
            """(boundary_id, point_index, distance_um) nearest to a click."""
            dz, dy, dx = self.result["voxel_size_um"]
            best = (None, -1, 1e9)
            for b in self.state.boundaries.values():
                pts = np.asarray(b.points, dtype=float)
                d = np.hypot(pts[:, 0] * dx - ex, pts[:, 1] * dy - ey)
                i = int(np.argmin(d))
                if d[i] < best[2]:
                    best = (b.boundary_id, i, float(d[i]))
            return best

        def _on_press(self, event):
            if event.inaxes is not self.ax or event.xdata is None:
                return
            bid, idx, dist = self._nearest(event.xdata, event.ydata)
            if bid is None or dist > 6.0:
                self.selected = None
                self._render(); self.canvas.draw_idle()
                return
            self.selected = bid
            if event.button == 1 and dist <= 2.5:
                self.drag = (bid, idx)
            self._render(); self.canvas.draw_idle()

        def _on_motion(self, event):
            if not self.drag or event.inaxes is not self.ax or event.xdata is None:
                return
            bid, idx = self.drag
            dz, dy, dx = self.result["voxel_size_um"]
            b = self.state.boundaries[bid]
            b.points[idx] = (b.points[idx][0], float(event.ydata / dy))
            self._render(); self.canvas.draw_idle()

        def _on_release(self, event):
            """Commit the drag AS AN INTENT, so it reaches the correction log.

            The drag itself moved the point directly for responsiveness; if it
            stopped there the edit would never be logged and the review would
            claim a human approved something no record could show them doing.
            """
            import myocyte_review_state as mrs

            if not self.drag:
                return
            bid, idx = self.drag
            self.drag = None
            b = self.state.boundaries[bid]
            x, y = b.points[idx]
            orig = b.proposed_points[idx] if b.proposed_points else None
            b.points[idx] = orig if orig else (x, y)   # rewind, then apply
            try:
                self.state.apply_intent(mrs.MovePoint(boundary_id=bid, index=idx,
                                                      x=x, y=y))
            except mrs.ReviewError as exc:
                messagebox.showwarning("Refused", str(exc))
            self._render(); self.canvas.draw_idle()
            self._refresh_info()

        def _on_key(self, event):
            import myocyte_review_state as mrs

            if not self.selected:
                return
            bid = self.selected
            try:
                if event.key in ("a", "A"):
                    self.state.apply_intent(mrs.AcceptBoundary(boundary_id=bid))
                elif event.key in ("r", "R"):
                    self._reject(bid)
                elif event.key in ("i", "I") and event.xdata is not None:
                    dz, dy, dx = self.result["voxel_size_um"]
                    _, idx, _ = self._nearest(event.xdata, event.ydata)
                    self.state.apply_intent(mrs.InsertPoint(
                        boundary_id=bid, index=idx + 1,
                        x=float(event.xdata / dx), y=float(event.ydata / dy)))
                elif event.key in ("x", "X") and event.xdata is not None:
                    _, idx, _ = self._nearest(event.xdata, event.ydata)
                    self.state.apply_intent(mrs.RemovePoint(boundary_id=bid,
                                                            index=idx))
            except mrs.ReviewError as exc:
                messagebox.showwarning("Refused", str(exc))
            self._render(); self.canvas.draw_idle()
            self._refresh_info()

        def _reject(self, bid):
            import myocyte_review_state as mrs

            win = tk.Toplevel(self)
            win.title("Why is this boundary wrong?")
            ttk.Label(win, text="Reasons are counted across students, so they\n"
                                "come from a fixed list rather than free text.",
                      padding=8).pack()
            var = tk.StringVar(value=mrs.REJECT_REASONS[0])
            for reason in mrs.REJECT_REASONS:
                ttk.Radiobutton(win, text=reason.replace("_", " "),
                                variable=var, value=reason).pack(anchor="w",
                                                                 padx=14)

            def go():
                try:
                    self.state.apply_intent(mrs.RejectBoundary(
                        boundary_id=bid, reason=var.get()))
                except mrs.ReviewError as exc:
                    messagebox.showwarning("Refused", str(exc))
                win.destroy()
                self._render(); self.canvas.draw_idle()
                self._refresh_info()

            ttk.Button(win, text="Reject", command=go).pack(pady=8)
            win.transient(self)
            win.grab_set()

        def _refresh_info(self):
            s = self.state.summary()
            self._say(
                f"region: {self.result['region'] or 'UNKNOWN'}   "
                f"ch{self.result['channel']}\n\n"
                f"REVIEW\n"
                f"  unjudged {s['by_status'].get('proposed', 0)}   "
                f"accepted {s['by_status'].get('accepted', 0)}   "
                f"edited {s['by_status'].get('edited', 0)}   "
                f"rejected {s['by_status'].get('rejected', 0)}\n"
                f"  {s['n_intents']} recorded changes\n\n"
                f"CLICK a boundary to select it, DRAG a point to move it.\n"
                f"  A  accept as proposed\n"
                f"  R  reject (asks why)\n"
                f"  I  insert a point at the cursor\n"
                f"  X  remove the nearest point\n\n"
                f"Every change is logged. Corrections are anchored by the\n"
                f"proposal, so they are tuning data - not clean ground truth.")

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
                if getattr(self, "state", None) is not None:
                    written.update(write_review(d, base, self.state))
            except Exception:
                messagebox.showerror("Could not save", traceback.format_exc())
                return
            s = self.state.summary() if getattr(self, "state", None) else {}
            unjudged = s.get("by_status", {}).get("proposed", 0)
            tail = ("\n\nEvery boundary was judged." if not unjudged else
                    f"\n\nWARNING: {unjudged} boundaries were never judged. "
                    f"They are saved as 'proposed' and must NOT be measured "
                    f"as though a human had approved them.")
            messagebox.showinfo(
                "Saved",
                "\n".join(str(v) for v in written.values()) + tail)

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
