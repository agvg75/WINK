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
