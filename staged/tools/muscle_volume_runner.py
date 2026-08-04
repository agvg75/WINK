"""Measure marked muscle volume, headless, and render what was measured.

Reads a boundary sidecar and its stack; writes the volume table, the mask, a
rotating 3D movie of the fitted surfaces, and provenance. Instantiates no
viewer, which is what lets it run on any station months later without anyone
re-marking - the same split as neurite_trace_runner.

THE MOVIE IS NOT DECORATION. The slab model assumes a gently concave sheet, and
its failures are three-dimensional: a fold, a surface drifting out of the muscle
layer, an exclusion that should have been drawn and was not. On a single slice
those look like nothing. Rotating, they are obvious. That is the same reason the
other WINK movies exist - put the thing where it cannot be missed - and it
delivers on every machine, with no GPU and no new dependency.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(ROOT / "app"), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import muscle_boundary as mb                 # noqa: E402
import movie_core as mc                      # noqa: E402

TOOL_NAME = "Muscle volume runner"
TOOL_VERSION = "0.1.0"


# --------------------------------------------------------------------------- #
# Measurement
# --------------------------------------------------------------------------- #
def measure(regions, shape_zcyx, voxel_size_um, voxel_source="unknown"):
    """One row per region. Raises on any region that cannot be measured."""
    rows = []
    for region in regions:
        row = mb.measure_region(region, shape_zcyx, voxel_size_um)
        # Volume goes as the CUBE of lateral scale, so a defaulted voxel size is
        # wrong by a large factor and looks entirely plausible. Provenance for
        # it belongs in the CSV, not only the JSON, because the CSV is what
        # someone reads.
        row["voxel_size_source"] = voxel_source
        rows.append(row)
    return rows


def write_outputs(out_dir, base, rows, masks, provenance):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}

    import csv
    csv_path = out_dir / f"{base}_muscle_volume.csv"
    if rows:
        fields = sorted({k for r in rows for k in r})
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow({k: (json.dumps(v) if isinstance(v, dict) else v)
                            for k, v in r.items()})
        written["csv"] = csv_path

    if masks:
        try:
            import tifffile
            for name, mask in masks.items():
                p = out_dir / f"{base}_muscle_mask_{name}.tif"
                tifffile.imwrite(str(p), mask.astype(np.uint8) * 255)
                written.setdefault("masks", []).append(p)
        except Exception as exc:                       # noqa: BLE001
            provenance["mask_write_error"] = str(exc)

    prov_path = out_dir / f"{base}_muscle_volume_provenance.json"
    prov_path.write_text(json.dumps(provenance, indent=2, default=str),
                         encoding="utf-8")
    written["provenance"] = prov_path
    return written


# --------------------------------------------------------------------------- #
# The rotating surface movie
# --------------------------------------------------------------------------- #
class _SurfaceSpin(mc.MovieSource):
    """Rotates the fitted surfaces so the slab model can be judged in 3D.

    Static frames are drawn once; only the view angle changes per frame, which
    is what keeps this cheap enough to run anywhere.
    """

    base = "muscle_surfaces"
    fps = 20.0

    def __init__(self, regions, shape_zcyx, voxel_size_um, rows,
                 n_frames=120, stride=8):
        self.regions = regions
        self.shape_zcyx = shape_zcyx
        self.voxel_size_um = voxel_size_um
        self.rows = {r["region"]: r for r in rows}
        self.n_frames = int(n_frames)
        self.stride = int(stride)

    def frame_label(self, index):
        return "azimuth %d deg" % int(360.0 * index / max(self.n_frames, 1))

    def build_figure(self, **_):
        import matplotlib.pyplot as plt

        nz, _, ny, nx = [int(v) for v in self.shape_zcyx]
        vz, vy, vx = [float(v) for v in self.voxel_size_um]
        fig = plt.figure(figsize=(9.0, 7.4), dpi=110)
        fig.patch.set_facecolor("white")
        ax = fig.add_subplot(111, projection="3d")

        colours = ("#2C7BB6", "#D7191C", "#2CA02C", "#9467BD")
        for i, region in enumerate(self.regions):
            colour = colours[i % len(colours)]
            upper = mb._interpolate_between_planes(
                mb._surface_curve(region, "upper", nx), nx)
            lower = mb._interpolate_between_planes(
                mb._surface_curve(region, "lower", nx), nx)
            zs = sorted(set(upper) & set(lower))
            if not zs:
                continue
            # A fitted sheet drawn as scattered points reads as noise. These
            # ARE surfaces - y as a function of (x, z) - so draw them as
            # surfaces: a fold or a drift out of the muscle layer is visible in
            # the sheet and invisible in a point cloud.
            cols = np.arange(0, nx, max(1, self.stride))
            zz = np.asarray(zs, dtype=float)
            X = np.tile(cols * vx, (len(zs), 1))
            Zg = np.tile((zz * vz)[:, None], (1, len(cols)))
            for surf, alpha, shade in ((upper, 0.75, colour),
                                       (lower, 0.40, colour)):
                Y = np.vstack([surf[z][cols] for z in zs]) * vy
                if not np.isfinite(Y).any():
                    continue
                ax.plot_surface(X, Y, Zg, color=shade, alpha=alpha,
                                linewidth=0, antialiased=True,
                                rstride=1, cstride=1, shade=True)
            # The marked planes themselves, so sparse marking is visible as
            # sparse: a viewer should see which planes a student actually
            # judged and which are interpolation between them.
            for z in region.marked_planes("upper"):
                row = upper.get(z)
                if row is None:
                    continue
                good = np.isfinite(row[cols])
                if good.any():
                    ax.plot(cols[good] * vx, row[cols][good] * vy,
                            np.full(good.sum(), z * vz),
                            lw=1.6, color="#111111", alpha=0.8)
            # exclusions, so the student can see WHERE the model was refused
            for e in region.exclusions:
                poly = np.asarray(e.polygon, dtype=float)
                if len(poly) < 3:
                    continue
                ax.plot(poly[:, 0] * vx, poly[:, 1] * vy,
                        np.full(len(poly), int(e.z) * vz),
                        lw=1.2, color="#C1440E", alpha=0.9)

        ax.set_xlabel("x (um)", fontsize=8)
        ax.set_ylabel("y (um)", fontsize=8)
        ax.set_zlabel("z (um)", fontsize=8)
        ax.tick_params(labelsize=7)
        # z is stretched for legibility. At true physical aspect a 24-plane
        # stack against a 200 px field is a flat sliver and the sheet cannot be
        # judged. Same decision as the neurite viewer, and captioned for the
        # same reason: a stretched axis that does not say so is a lie.
        span_xy = max(nx * vx, ny * vy)
        z_span = max(nz * vz, 1e-6)
        z_stretch = max(1.0, round(span_xy / (3.0 * z_span), 1))
        ax.set_box_aspect((nx * vx, ny * vy, z_span * z_stretch))
        self._z_stretch = z_stretch

        summary = "   |   ".join(
            "%s %.0f um3 (%.0f%% excluded)"
            % (n, r["volume_um3"], 100 * r["excluded_fraction"])
            for n, r in self.rows.items()) or "no measurable region"
        fig.text(0.02, 0.965, summary, fontsize=8.5, color="#22303A")
        fig.text(0.02, 0.045,
                 "upper surface solid, lower faint   |   black lines are the "
                 "planes actually marked; everything between them is linear "
                 "interpolation   |   exclusions outlined in orange",
                 fontsize=7.5, color="#5E6E76")
        # Only claim a stretch when there is one. A caption reading "1.0x -
        # NOT to scale" trains people to ignore the caption, which is exactly
        # what it must not do on the stacks that ARE stretched.
        stretch = getattr(self, "_z_stretch", 1.0)
        z_note = ("z stretched %.1fx for legibility - NOT to scale" % stretch
                  if stretch > 1.005 else "z shown to scale")
        fig.text(0.02, 0.018,
                 "%s   |   measured over the marked extent only   |   %s %s "
                 "renders, measures nothing"
                 % (z_note, TOOL_NAME, TOOL_VERSION),
                 fontsize=7.5, color="#5E6E76")

        dyn = {"ax": ax}
        return fig, dyn, {"ax": ax}

    def update(self, fig, dyn, ctx, index):
        # Only the viewing angle changes. Nothing measured moves.
        ctx["ax"].view_init(elev=22.0,
                            azim=360.0 * index / max(self.n_frames, 1))

    def dynamic_artists(self, dyn):
        # A 3-D axes cannot be blitted piecewise; the core falls back to a full
        # redraw per frame, which is affordable because the frames are few.
        return []

    def provenance(self, ctx, options):
        return {"view": "rotating 3D surfaces", "n_frames": self.n_frames}


def render_surface_movie(regions, shape_zcyx, voxel_size_um, rows, out_path,
                         n_frames=120, progress=None):
    """Rotating movie of the fitted surfaces. Returns (path, provenance)."""
    source = _SurfaceSpin(regions, shape_zcyx, voxel_size_um, rows,
                          n_frames=n_frames)
    return mc.render(source, out_path, progress=progress,
                     tool_name=TOOL_NAME, tool_version=TOOL_VERSION)


# --------------------------------------------------------------------------- #
# Review evidence: every region, side by side
# --------------------------------------------------------------------------- #
def projection_figure(region, shape_zcyx, voxel_size_um, row=None, volume=None):
    """XZ and YZ projections of one region with its boundaries drawn.

    This is the evidence a human inspects. At scale - hundreds of regions on one
    sheet - a boundary that grabbed the pharynx instead of the muscle is obvious
    in a way it never is reviewing one stack at a time. Mass inspection is the
    right tool for gross failures.

    What it is NOT: independent measurement. Confirming a boundary that looks
    plausible is still anchored by the proposal, and confirmation bias operates
    exactly on 'looks plausible'. Error detection and ground truth are different
    jobs; this does the first.
    """
    import matplotlib.pyplot as plt

    nz, _, ny, nx = [int(v) for v in shape_zcyx]
    vz, vy, vx = [float(v) for v in voxel_size_um]
    fig, (ax_xz, ax_yz) = plt.subplots(1, 2, figsize=(9.0, 3.4), dpi=110)
    fig.patch.set_facecolor("white")

    upper = mb._interpolate_between_planes(
        mb._surface_curve(region, "upper", nx), nx)
    lower = mb._interpolate_between_planes(
        mb._surface_curve(region, "lower", nx), nx)
    zs = sorted(set(upper) & set(lower))
    marked = set(region.marked_planes("upper")) | set(region.marked_planes("lower"))

    # XZ: the sheet seen along y. Depth is where the slab model lives or dies.
    for z in zs:
        good = np.isfinite(upper[z]) & np.isfinite(lower[z])
        if not good.any():
            continue
        cols = np.where(good)[0]
        style = dict(lw=1.6, alpha=0.95) if z in marked else dict(lw=0.7, alpha=0.4)
        ax_xz.plot(cols * vx, np.full(cols.size, z * vz),
                   color="#2C7BB6" if z in marked else "#9BC4E2", **style)
    ax_xz.set_xlabel("x (um)", fontsize=8)
    ax_xz.set_ylabel("z (um)", fontsize=8)
    ax_xz.set_title("depth extent  (bold = marked, faint = interpolated)",
                    fontsize=8, loc="left", color="#3E4F58")
    ax_xz.invert_yaxis()

    # YZ: thickness along the sheet, which is what the volume integrates.
    for z in zs:
        good = np.isfinite(upper[z]) & np.isfinite(lower[z])
        if not good.any():
            continue
        cols = np.where(good)[0]
        ax_yz.fill_between(cols * vx, lower[z][cols] * vy, upper[z][cols] * vy,
                           color="#2C7BB6",
                           alpha=0.55 if z in marked else 0.12, lw=0)
    for e in region.exclusions:
        poly = np.asarray(e.polygon, dtype=float)
        if len(poly) >= 3:
            ax_yz.plot(np.append(poly[:, 0], poly[0, 0]) * vx,
                       np.append(poly[:, 1], poly[0, 1]) * vy,
                       lw=1.2, color="#C1440E")
    ax_yz.set_xlabel("x (um)", fontsize=8)
    ax_yz.set_ylabel("y (um)", fontsize=8)
    ax_yz.set_title("slab thickness, exclusions in orange", fontsize=8,
                    loc="left", color="#3E4F58")
    ax_yz.invert_yaxis()

    for ax in (ax_xz, ax_yz):
        ax.tick_params(labelsize=7)

    head = region.name
    if row:
        head += ("   %.0f um3   %.0f%% excluded   %d/%d planes marked"
                 % (row["volume_um3"], 100 * row["excluded_fraction"],
                    row["n_planes_marked_upper"], row["n_planes_measured"]))
    fig.suptitle(head, fontsize=9.5, x=0.01, ha="left", color="#22303A")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return fig


def write_projections(out_dir, base, regions, shape_zcyx, voxel_size_um, rows):
    """One evidence image per region, plus a contact sheet of all of them."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    by_name = {r["region"]: r for r in rows}
    paths = {}
    for region in regions:
        fig = projection_figure(region, shape_zcyx, voxel_size_um,
                                by_name.get(region.name))
        p = out_dir / f"{base}_projection_{region.name}.png"
        fig.savefig(p, dpi=110, facecolor="white")
        plt.close(fig)
        paths[region.name] = p

    sheet = None
    if paths:
        n = len(paths)
        cols = min(3, n)
        rows_n = (n + cols - 1) // cols
        sheet_fig, axes = plt.subplots(rows_n, cols,
                                       figsize=(5.0 * cols, 2.1 * rows_n))
        axes = np.atleast_1d(axes).ravel()
        for ax, (name, p) in zip(axes, sorted(paths.items())):
            ax.imshow(plt.imread(p))
            ax.axis("off")
        for ax in axes[len(paths):]:
            ax.axis("off")
        sheet_fig.tight_layout()
        sheet = out_dir / f"{base}_projection_sheet.png"
        sheet_fig.savefig(sheet, dpi=110, facecolor="white")
        plt.close(sheet_fig)
    return paths, sheet


# --------------------------------------------------------------------------- #
# Batch audit contract
# --------------------------------------------------------------------------- #
def audit_items(rows, evidence, stratum_keys=None, module_version=TOOL_VERSION):
    """Emit app/batch_audit.py's per-item contract so this module can be sampled.

    CONFIDENCE HERE MEANS MARKING DENSITY: the fraction of measured planes a
    human actually judged. A region measured from 2 marked planes across 40 is
    mostly interpolation, and that is the honest thing to rank on - it is not a
    claim about correctness, and it is UNCALIBRATED until audits accumulate and
    the calibration pipeline can check whether 0.9 really means 90% acceptable.
    Until then it orders items for review; it does not license skipping any.
    """
    items = []
    for r in rows:
        measured = max(int(r.get("n_planes_measured", 1)), 1)
        marked = max(int(r.get("n_planes_marked_upper", 0)),
                     int(r.get("n_planes_marked_lower", 0)))
        confidence = min(1.0, marked / float(measured))
        items.append({
            "item_id": r["region"],
            "confidence": round(confidence, 4),
            "confidence_meaning": "fraction of measured planes marked by a human",
            "confidence_calibrated": False,
            "abstained": False,
            "abstain_reason": None,
            "stratum_keys": dict(stratum_keys or {}, region=r["region"]),
            "evidence_path": str(evidence.get(r["region"], "")) or None,
            "module_name": TOOL_NAME,
            "module_version": module_version,
        })
    return items
