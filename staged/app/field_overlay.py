"""The modelled stimulus field, the tracks, and the movie frame, in one image.

Andres: "Outputs should include the stimulus field model superimposed by tracks
all overlaid on movie (for all stimuli and configurations)."

WHY THIS IS THE OUTPUT THAT MATTERS. Every other check in this toolset asks
whether the numbers are self-consistent. This one is the only place a person
can see whether the MODEL IS POINTED AT THE RIGHT PLACE - whether the magnet in
the model sits where the magnet in the dish sits, whether the odour spot is the
bright blob or ten millimetres left of it. A field model with the source in the
wrong place produces a complete, plausible, entirely wrong analysis, and no
amount of internal consistency will reveal it. Looking will.

IT WORKS FOR ANY PROVIDER, deliberately. The provider interface already gives
magnitude, direction and gradient at a point, so nothing here needs to know
which assay it is drawing. A new geometry gets its overlay for free, which is
the whole reason the provider interface exists.

TIME IS HONOURED. A field that sweeps or rotates is drawn as it was AT THAT
FRAME, because the point of the picture is to show what the animal was in.
Drawing a static snapshot of an oscillating field would be a picture of
something that never happened.
"""
from __future__ import annotations

import numpy as np


class OverlayError(Exception):
    """Refusals that name the consequence."""


def image_to_plate(x_px, y_px, mm_per_px, origin_px=(0.0, 0.0)):
    return ((np.asarray(x_px, dtype=float) - origin_px[0]) * mm_per_px,
            (np.asarray(y_px, dtype=float) - origin_px[1]) * mm_per_px)


def plate_to_image(x_mm, y_mm, mm_per_px, origin_px=(0.0, 0.0)):
    return (np.asarray(x_mm, dtype=float) / mm_per_px + origin_px[0],
            np.asarray(y_mm, dtype=float) / mm_per_px + origin_px[1])


def sample_grid(provider, shape_px, mm_per_px, origin_px=(0.0, 0.0),
                step_px=24, time_s=0.0, quantity="magnitude"):
    """Sample any provider across the frame, in image coordinates.

    Returns arrays ready to draw: pixel centres, the scalar field, and the
    in-plane vector. `quantity` picks what the scalar means - "magnitude" for
    field strength, "gradient" for how steeply it changes, which is the one
    that matters for a donut or a point source and is flat by construction for
    a coil.
    """
    if mm_per_px <= 0:
        raise OverlayError(
            "A positive mm/px is required to place the field on the image. "
            "Without it the model and the picture are in different units and "
            "the overlay would look right while being wrong.")
    if quantity not in {"magnitude", "gradient"}:
        raise OverlayError("quantity must be 'magnitude' or 'gradient'.")
    h, w = int(shape_px[0]), int(shape_px[1])
    step = max(2, int(step_px))
    xs = np.arange(step // 2, w, step, dtype=float)
    ys = np.arange(step // 2, h, step, dtype=float)
    scalar = np.zeros((len(ys), len(xs)), dtype=float)
    u = np.zeros_like(scalar)
    v = np.zeros_like(scalar)
    for iy, ypx in enumerate(ys):
        for ix, xpx in enumerate(xs):
            xmm, ymm = image_to_plate(xpx, ypx, mm_per_px, origin_px)
            s = provider.sample(float(xmm), float(ymm), float(time_s))
            gx, gy = s.gradient_xy
            scalar[iy, ix] = (s.magnitude if quantity == "magnitude"
                              else float(np.hypot(gx, gy)))
            vec = (s.direction_xyz[:2] if s.direction_xyz is not None
                   else (gx, gy))
            u[iy, ix], v[iy, ix] = float(vec[0]), float(vec[1])
    return {"x_px": xs, "y_px": ys, "scalar": scalar, "u": u, "v": v,
            "quantity": quantity, "time_s": float(time_s)}


def draw(frame, provider, tracks=None, *, mm_per_px, origin_px=(0.0, 0.0),
         time_s=0.0, annotation=None, quantity="magnitude", step_px=24,
         ax=None, title="", trail_s=None, fps=None):
    """Compose frame + field + tracks. Returns the matplotlib axes.

    `tracks` is any iterable of row dicts with x_mm, y_mm, time_s and worm_id.
    `annotation` is a stimulus_annotation dict, drawn as the person placed it -
    so the picture shows BOTH what was declared and what the model made of it,
    and a mismatch between them is visible rather than inferred.
    """
    import matplotlib.pyplot as plt

    frame = np.asarray(frame)
    if frame.ndim not in (2, 3):
        raise OverlayError(
            f"A frame must be 2D or 3D, got shape {frame.shape}. Overlaying "
            f"onto something that is not an image would place the field "
            f"against nothing to check it against.")
    if ax is None:
        _fig, ax = plt.subplots(figsize=(9, 7))
    ax.imshow(frame, cmap=None if frame.ndim == 3 else "gray")

    grid = sample_grid(provider, frame.shape[:2], mm_per_px, origin_px,
                       step_px=step_px, time_s=time_s, quantity=quantity)
    # Contour the scalar so the eye reads WHERE the field is strong, and quiver
    # the direction so it reads WHICH WAY - one alone is not enough to spot a
    # misplaced source.
    if np.ptp(grid["scalar"]) > 0:
        ax.contour(grid["x_px"], grid["y_px"], grid["scalar"], levels=8,
                   linewidths=0.8, alpha=0.75)
    else:
        # A perfectly flat scalar is not a failure - it is what a uniform
        # field looks like - so say so instead of drawing nothing.
        ax.text(0.02, 0.02, f"{grid['quantity']} is uniform across the frame",
                transform=ax.transAxes, color="w", fontsize=8,
                bbox={"facecolor": "k", "alpha": 0.5, "pad": 2})
    ax.quiver(grid["x_px"], grid["y_px"], grid["u"], -grid["v"],
              color="white", alpha=0.7, width=0.002)

    if annotation:
        _draw_annotation(ax, annotation, mm_per_px, origin_px)

    if tracks is not None:
        rows = [r for r in tracks]
        if trail_s is not None:
            rows = [r for r in rows
                    if 0 <= time_s - float(r["time_s"]) <= float(trail_s)]
        by_worm = {}
        for r in rows:
            by_worm.setdefault(str(r.get("worm_id")), []).append(r)
        for worm, group in sorted(by_worm.items()):
            group.sort(key=lambda r: float(r["time_s"]))
            px, py = plate_to_image([r["x_mm"] for r in group],
                                    [r["y_mm"] for r in group],
                                    mm_per_px, origin_px)
            ax.plot(px, py, linewidth=1.0, alpha=0.9)
            ax.plot(px[-1], py[-1], marker="o", markersize=3)

    ax.set_xticks([])
    ax.set_yticks([])
    bits = [title] if title else []
    if hasattr(provider, "describe"):
        bits.append(provider.describe())
    if getattr(provider, "is_time_varying", False):
        bits.append(f"t = {time_s:.1f} s"
                    + (f" ({time_s * fps:.0f} fr)" if fps else ""))
    ax.set_title("\n".join(bits), fontsize=9)
    return ax


def _draw_annotation(ax, annotation, mm_per_px, origin_px):
    """What the person drew, on top of what the model made of it."""
    kind = annotation.get("kind")
    if kind in {"point", "roi", "circle"}:
        cx, cy = plate_to_image(*annotation["center_mm"], mm_per_px, origin_px)
        ax.plot(cx, cy, marker="+", markersize=12, color="#FFD400", mew=2)
        r_mm = annotation.get("radius_mm")
        if r_mm:
            circle = __import__("matplotlib").patches.Circle(
                (float(cx), float(cy)), float(r_mm) / mm_per_px, fill=False,
                color="#FFD400", linewidth=1.4,
                linestyle="-" if kind == "circle" else "--")
            ax.add_patch(circle)
    elif kind == "line":
        x1, y1 = plate_to_image(*annotation["start_mm"], mm_per_px, origin_px)
        x2, y2 = plate_to_image(*annotation["end_mm"], mm_per_px, origin_px)
        ax.plot([x1, x2], [y1, y2], color="#FFD400", linewidth=1.6)


def check_placement(provider, annotation, tolerance_mm=1.0):
    """Does the model's source sit where the person said it does?

    The one failure this whole overlay exists to catch, made checkable as well
    as visible - a picture is only looked at when someone remembers to look.
    """
    declared = annotation.get("center_mm")
    if declared is None:
        return {"checked": False,
                "why": "This annotation declares a direction, not a place, so "
                       "there is no source position to compare."}
    modelled = None
    if hasattr(provider, "center"):
        modelled = [float(provider.center[0]), float(provider.center[1])]
    elif hasattr(provider, "position_m"):
        modelled = [provider.position_m[0] * 1000, provider.position_m[1] * 1000]
    elif hasattr(provider, "source"):
        src = np.asarray(getattr(provider, "source"), dtype=float).ravel()
        if src.size >= 2:
            modelled = [float(src[0]), float(src[1])]
    if modelled is None:
        return {"checked": False,
                "why": f"{type(provider).__name__} does not expose a source "
                       f"position to compare against."}
    off = float(np.hypot(modelled[0] - declared[0], modelled[1] - declared[1]))
    ok = off <= float(tolerance_mm)
    return {
        "checked": True, "offset_mm": round(off, 4),
        "declared_mm": declared, "modelled_mm": modelled,
        "agrees": ok,
        "why": (None if ok else
                f"The model puts the source {off:.2f} mm from where it was "
                f"drawn. A misplaced source produces a complete and entirely "
                f"plausible analysis that is simply wrong, and nothing "
                f"downstream will contradict it."),
    }
