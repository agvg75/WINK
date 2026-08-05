"""Which plane to shoot at, decided at the microscope rather than afterwards.

Andres: can something tell Mackenzie what depth to shoot for while she is
filming? His guess was to maximise red or blue, and the guess is right for a
reason worth stating: THE MOST SUSCEPTIBLE CHANNEL IS THE BEST FOCUS SIGNAL.
Cytoplasmic green fills the cell and barely changes as the plane moves, so it
cannot guide anything. An organellar label is a thin structure within that
volume, so its signal changes steeply with depth - and a steep response is
precisely what a focusing criterion needs.

BUT NOT RAW BRIGHTNESS ALONE, because brightness also rises with laser power,
gain, exposure and a bleaching-free specimen. Turn the laser up and every plane
looks better. Three measures are reported instead, and only the first is immune
to the acquisition settings:

  sharpness   spatial frequency content inside the animal. A plane that cuts
              structure produces edges; one that skims produces haze. This is
              the honest focus signal - it does not move when the gain does.
  symmetry    how evenly the two sides are lit. At the right depth in a laterally
              mounted animal both quadrant pairs are sampled comparably; a tilted
              or off-centre plane favours one. This catches a fault that
              brightness and sharpness both miss, because a badly tilted plane
              can be bright and sharp on the side it happens to catch.
  signal      median intensity in the susceptible channel. Andres's criterion,
              kept because it is the one that is visible live on the scope's own
              display, but ranked below sharpness for the reason above.

WHAT THIS CANNOT DO from a single frame is tell her which WAY to move. A quality
score says how good the current plane is, not whether the better one is above or
below. `sweep()` handles that: take three or five planes a micron or two apart,
and the shape of the curve says where the peak lies - including when the peak is
outside the range sampled, which is the case most worth knowing and the one a
single frame cannot reveal.
"""
from __future__ import annotations

import numpy as np

FOCUS_CHANNELS = ("red", "blue")     # the susceptible ones - see the docstring


class FocusError(Exception):
    """Refusals that name the consequence."""


def sharpness(image, mask=None):
    """Edge energy inside the animal, normalised by its own brightness.

    Normalised because a raw gradient sum rises with the laser, which would
    make 'sharper' and 'brighter' the same measurement and defeat the point of
    having both.
    """
    img = np.asarray(image, dtype=float)
    if img.ndim != 2:
        raise FocusError(f"Need a single-plane image; got shape {img.shape}.")
    gy, gx = np.gradient(img)
    g = np.hypot(gy, gx)
    if mask is not None:
        m = np.asarray(mask, dtype=bool)
        if m.shape != img.shape:
            raise FocusError(
                f"Mask {m.shape} does not match the image {img.shape}; "
                f"measuring focus through the wrong pixels would rank planes "
                f"by what was in the background.")
        if m.sum() < 25:
            return None
        level = float(np.mean(img[m]))
        return float(np.mean(g[m]) / level) if level > 0 else None
    level = float(np.mean(img))
    return float(np.mean(g) / level) if level > 0 else None


def side_symmetry(image, mask, spine):
    """How evenly the two sides of the midline are lit. 1.0 is even.

    Catches what brightness and sharpness both miss: a tilted plane can be
    bright and sharp on whichever side it happens to catch, and look excellent
    while half the animal is being sectioned badly.
    """
    import sys
    from pathlib import Path
    tools = Path(__file__).resolve().parents[1] / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    try:
        import hemisegments as hs
    except ImportError:                                    # pragma: no cover
        raise FocusError("hemisegments unavailable")

    a = hs.assign(mask, spine, n_seg=8, profile="uniform")
    img = np.asarray(image, dtype=float)
    vals = {}
    for s in (1, -1):
        sel = (a["side"] == s) & (a["segment"] >= 0)
        if sel.sum() >= 25:
            vals[s] = float(np.median(img[sel]))
    if len(vals) < 2:
        return None
    lo, hi = sorted(vals.values())
    return float(lo / hi) if hi > 0 else None


def frame_quality(images, mask, spine=None, focus_channels=FOCUS_CHANNELS):
    """Score one plane. Says how good it is, NOT which way to move."""
    out = {"channels": {}}
    for ch, img in images.items():
        e = {"sharpness": sharpness(img, mask)}
        m = np.asarray(mask, bool)
        e["signal"] = (round(float(np.median(np.asarray(img, float)[m])), 3)
                       if m.sum() else None)
        if spine is not None:
            try:
                e["symmetry"] = side_symmetry(img, mask, spine)
            except FocusError:
                e["symmetry"] = None
        out["channels"][ch] = e

    usable = [c for c in focus_channels
              if c in out["channels"]
              and out["channels"][c].get("sharpness") is not None]
    if usable:
        out["focus_score"] = round(
            float(np.mean([out["channels"][c]["sharpness"] for c in usable])), 5)
        out["scored_on"] = usable
    else:
        out["focus_score"] = None
        out["scored_on"] = []
        out["why"] = ("No susceptible channel was measurable. Green alone "
                      "cannot guide focus: it fills the cell and barely "
                      "changes as the plane moves.")
    sym = [out["channels"][c].get("symmetry") for c in usable
           if out["channels"][c].get("symmetry") is not None]
    out["symmetry"] = round(float(np.mean(sym)), 4) if sym else None
    out["single_frame_limit"] = (
        "This says how good the current plane is, not whether a better one is "
        "above or below it. Use sweep() for direction.")
    return out


def sweep(planes, focus_channels=FOCUS_CHANNELS, min_planes=3):
    """Score several planes and say where the best one is - or that it is outside.

    `planes` is a sequence of (z, images, mask, spine). Three or five planes a
    micron or two apart is enough.

    THE CASE THAT MATTERS MOST is a peak at the edge of the range sampled. It
    means the true optimum was never visited, and a naive 'pick the best'
    would hand back the best of a bad set with no indication that it was. A
    single frame cannot reveal this at all, which is the whole reason to sweep.
    """
    if len(planes) < min_planes:
        raise FocusError(
            f"Only {len(planes)} planes. Direction cannot be inferred from "
            f"fewer than {min_planes}, and picking the brightest of two is a "
            f"coin toss dressed as a measurement.")
    scored = []
    for z, images, mask, spine in planes:
        q = frame_quality(images, mask, spine, focus_channels)
        scored.append({"z": float(z), **q})
    usable = [s for s in scored if s["focus_score"] is not None]
    if not usable:
        raise FocusError("No plane could be scored; check the channel names.")

    best = max(usable, key=lambda s: s["focus_score"])
    zs = [s["z"] for s in usable]
    at_edge = best["z"] in (min(zs), max(zs)) and len(usable) > 2
    direction = None
    if at_edge:
        direction = "deeper" if best["z"] == max(zs) else "shallower"

    return {
        "planes": scored,
        "best_z": best["z"],
        "best_score": best["focus_score"],
        "scored_on": best["scored_on"],
        "symmetry_at_best": best.get("symmetry"),
        "peak_at_edge": bool(at_edge),
        "guidance": (
            f"The best plane sampled is at z = {best['z']:g}, but it sits at "
            f"the EDGE of the range. The true optimum is probably further "
            f"{direction} - extend the sweep before committing."
            if at_edge else
            f"z = {best['z']:g} is the best plane and the peak is inside the "
            f"range sampled, so the optimum was bracketed."),
        "symmetry_note": (
            None if best.get("symmetry") is None else
            f"Sides differ by {1 - best['symmetry']:.0%} at this plane. "
            + ("Even enough to compare the two sides."
               if best["symmetry"] > 0.8 else
               "Uneven - the plane is tilted or off-centre relative to the "
               "animal. Left-right comparisons from this mount will not be "
               "safe, whatever the focus score says.")),
        "why_not_brightness": (
            "Ranked on SHARPNESS, not brightness. Brightness rises with laser "
            "power, gain and exposure, so turning the laser up makes every "
            "plane look better; edge energy normalised by level does not move "
            "when the gain does."),
    }
