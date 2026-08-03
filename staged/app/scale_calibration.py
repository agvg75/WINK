"""Shared spatial-calibration helper: turn microscope/camera settings into
micrometres-per-pixel, or measure it directly from the image.

Three ways to get um/px, in increasing authority:

1. Optical estimate - pick the scope (fixes objective + C-mount adapter), the
   zoom, and the camera (fixes sensor pixel pitch):

       total_magnification = objective * zoom * c_mount_adapter
       um_per_px = pixel_pitch_um * binning / total_magnification

   This only applies to camera+microscope combinations; a webcam imaging a
   plate directly, or a scope-less IR rig, has no such optics, so the optical
   path is disabled for those and only the scale bar applies.

2. Raw scale bar - draw a line of known length on the image; um/px is measured
   directly and needs neither optics nor pixel pitch.  This is ground truth.

3. Worm-length sanity check - trace an adult and compare to ~1.14 mm.

Presets for the lab's scopes and cameras are baked in and can be extended; user
additions persist in a small JSON under the user's home so they survive updates.

The optical estimate is only a predictor - nominal objective/zoom/adapter values
and rounded sensor specs can be a few percent off - so a stage-micrometer or the
scale bar should remain the authority.  The module is deliberately free of any
tool-specific state so every module can share it.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

# Reference length of an adult C. elegans hermaphrodite, for the sanity check.
ADULT_WORM_MM = 1.14

# --- built-in presets ------------------------------------------------------
# objective: fixed objective for this body, or None when the objective is
#   chosen from `objectives`.  cmount: camera-side adapter factor.  has_zoom:
#   continuous zoom body.  optical: False means no microscope optics (direct
#   imaging) so only the scale bar can calibrate it.
DEFAULT_SCOPES = {
    "Olympus SZX12 - A (1x obj)": {
        "objective": 1.0, "cmount": 0.5, "has_zoom": True,
        "zoom_range": [0.7, 9.0], "optical": True,
        "note": "Zoom knob shows 7-90; divide by 10 for the factor."},
    "Olympus SZX12 - B (0.5x obj)": {
        "objective": 0.5, "cmount": 0.5, "has_zoom": True,
        "zoom_range": [0.7, 9.0], "optical": True,
        "note": "Zoom knob shows 7-90; divide by 10 for the factor."},
    "Zeiss Axioscope (inverted)": {
        "objective": None, "objectives": [10.0, 20.0, 40.0, 90.0],
        "cmount": 1.0, "has_zoom": False, "optical": True,
        "note": "Confirm the C-mount adapter factor (often 0.5x or 0.63x)."},
    "(none / direct imaging)": {
        "objective": 1.0, "cmount": 1.0, "has_zoom": False,
        "optical": False,
        "note": "No microscope optics; calibrate with the scale bar."},
}

DEFAULT_CAMERAS = {
    "Point Grey Flycap2": {"pixel_um": 4.6, "binning": 1, "optical": True},
    "HDMI 4K (Olympus B)": {
        "pixel_um": 2.4, "binning": 1, "optical": True,
        "note": "HDMI capture may rescale/crop the sensor - prefer the scale "
                "bar and treat the optical value as a check only."},
    "QImaging optiMOS": {"pixel_um": 6.5, "binning": 1, "optical": True},
    "ELP SVPro 1080P webcam": {
        "pixel_um": 2.8, "binning": 1, "optical": False,
        "note": "Used directly on plates; no scope - scale bar only."},
    "Basler (Tierpsy IR)": {
        "pixel_um": 1.85, "binning": 1, "optical": False,
        "note": "IR rig, no scope - scale bar only."},
}


def _user_presets_path() -> Path:
    return Path.home() / ".wink" / "scale_presets.json"


def load_presets() -> dict:
    """Return {'scopes': {...}, 'cameras': {...}} = defaults + user additions."""
    scopes = {k: dict(v) for k, v in DEFAULT_SCOPES.items()}
    cameras = {k: dict(v) for k, v in DEFAULT_CAMERAS.items()}
    try:
        raw = json.loads(_user_presets_path().read_text(encoding="utf-8"))
        for k, v in (raw.get("scopes") or {}).items():
            scopes[k] = dict(v)
        for k, v in (raw.get("cameras") or {}).items():
            cameras[k] = dict(v)
    except Exception:
        pass
    return {"scopes": scopes, "cameras": cameras}


def save_user_preset(kind: str, name: str, values: dict) -> bool:
    """Persist a user scope/camera preset ('scopes' or 'cameras'). Best-effort."""
    if kind not in ("scopes", "cameras") or not name:
        return False
    path = _user_presets_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        data.setdefault("scopes", {})
        data.setdefault("cameras", {})
        data[kind][str(name)] = dict(values)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


# --- pure computation ------------------------------------------------------
def total_magnification(objective, zoom, cmount) -> float:
    return float(objective) * float(zoom) * float(cmount)


def optical_um_per_px(pixel_um, objective, zoom, cmount, binning=1) -> float:
    """um/px = sensor pixel pitch * binning / total optical magnification."""
    mag = total_magnification(objective, zoom, cmount)
    if mag <= 0:
        raise ValueError("Total magnification must be positive.")
    return float(pixel_um) * float(binning) / mag


def scalebar_um_per_px(length_px, known_length, unit="mm") -> float:
    """um/px from a drawn line of a known real length."""
    length_px = float(length_px)
    if length_px <= 0:
        raise ValueError("The drawn line has zero pixel length.")
    known_um = float(known_length) * (1000.0 if unit == "mm" else 1.0)
    if known_um <= 0:
        raise ValueError("The known length must be greater than zero.")
    return known_um / length_px


def worm_length_check(measured_px, um_per_px, expected_mm=ADULT_WORM_MM,
                      tolerance=0.15):
    """Compare a traced worm length to the expected adult length.

    Returns (measured_mm, ratio, ok).  ``ok`` is False when the measured length
    departs from ``expected_mm`` by more than ``tolerance`` (fractional).
    """
    measured_mm = float(measured_px) * float(um_per_px) / 1000.0
    ratio = measured_mm / float(expected_mm) if expected_mm else float("nan")
    ok = abs(ratio - 1.0) <= float(tolerance)
    return measured_mm, ratio, ok


def polyline_length_px(points) -> float:
    """Summed segment length of a clicked polyline [(x,y), ...]."""
    total = 0.0
    for (x0, y0), (x1, y1) in zip(points[:-1], points[1:]):
        total += ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    return total


# --- scale-bar auto-detection ----------------------------------------------
# Many confocal exports burn a scale bar + text label into a corner of the
# image (e.g. a thin white line reading "36.8 um"). This finds the LINE's
# pixel length automatically - a person still reads the printed number
# themselves and types it into "Known length" (this repo has no OCR
# dependency installed; reading the text itself would need one - see the
# module note below). What this replaces is clicking the two ends by hand.
#
# The bar is found by its own defining property: within its row(s), its
# bright pixels form ONE long, essentially unbroken run, unlike printed text
# (each character is short and separated by gaps) or real tissue signal
# (bright but not perfectly contiguous over tens-to-hundreds of pixels).
# Validated against three real confocal exports (a thin 1px line easy to
# miss by eye - see tests/test_scale_calibration.py) rather than assumed.
SCALE_BAR_CORNERS = ("bottom_left", "bottom_right", "top_left", "top_right")


def _corner_region(gray, corner, margin_frac, band_frac):
    h, w = gray.shape[:2]
    y_band = int(h * band_frac)
    x_margin = int(w * margin_frac)
    if corner == "bottom_left":
        region, oy, ox = gray[h - y_band:, :x_margin], h - y_band, 0
    elif corner == "bottom_right":
        region, oy, ox = gray[h - y_band:, w - x_margin:], h - y_band, w - x_margin
    elif corner == "top_left":
        region, oy, ox = gray[:y_band, :x_margin], 0, 0
    elif corner == "top_right":
        region, oy, ox = gray[:y_band, w - x_margin:], 0, w - x_margin
    else:
        raise ValueError(f"Unknown corner {corner!r}")
    return region, oy, ox


def _longest_run(row_mask):
    """(run_length, start_index) of the longest contiguous True run."""
    best = 0; best_start = 0; cur = 0; cur_start = 0
    for i, v in enumerate(row_mask):
        if v:
            if cur == 0:
                cur_start = i
            cur += 1
            if cur > best:
                best = cur; best_start = cur_start
        else:
            cur = 0
    return best, best_start


def detect_scale_bar_px(gray, corners=SCALE_BAR_CORNERS, margin_frac=0.35,
                        band_frac=0.2, min_length_px=15, min_solidity=0.9,
                        min_brightness=100.0):
    """Find a burned-in scale bar's pixel length, searching `corners` in
    order and returning the first solid match (bottom-left first, matching
    where this lab's confocal exports put it).

    `min_solidity` (run_length / total_bright_pixels_in_that_row) rejects
    rows that are bright but not one clean unbroken line - text and real
    tissue signal both fail this, a printed bar does not.

    Returns a dict with length_px and the bar's endpoints in FULL-IMAGE
    pixel coordinates, plus which corner and how solid the match was - or
    None if nothing in any searched corner looks like a real bar. This is a
    pixel LENGTH only; the real-world value is still read off the image by
    a person and typed into the known-length field, since no OCR dependency
    is installed in this environment.
    """
    gray = np.asarray(gray)
    if gray.ndim == 3:
        gray = gray[..., :3].mean(axis=2)
    for corner in corners:
        region, oy, ox = _corner_region(gray, corner, margin_frac, band_frac)
        if region.size == 0:
            continue
        rmax = float(region.max())
        if rmax < min_brightness:
            continue
        mask = region > 0.6 * rmax
        best = None
        for y in range(mask.shape[0]):
            row = mask[y]
            total = int(row.sum())
            if total < min_length_px:
                continue
            run, start = _longest_run(row)
            if run < min_length_px:
                continue
            solidity = run / total
            if solidity < min_solidity:
                continue
            if best is None or run > best["length_px"]:
                best = {"length_px": run, "y": y, "x1": start,
                        "x2": start + run - 1, "solidity": solidity}
        if best is not None:
            return {
                "length_px": float(best["length_px"]),
                "x1": float(ox + best["x1"]), "y1": float(oy + best["y"]),
                "x2": float(ox + best["x2"]), "y2": float(oy + best["y"]),
                "corner": corner, "solidity": float(best["solidity"]),
            }
    return None
