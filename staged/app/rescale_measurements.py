"""Correct measurements written at the wrong scale, without re-measuring.

Backlog #17. A confocal scale bar 904 px long and printed "49.2 um" was read
against a Known-length box defaulting to 1.0 mm, giving 1.10619 um/px instead
of 0.05442 - a factor of 20.3. The calibration UI now requires two explicit
clicks so this cannot recur, but rows written before that fix carry the error.

RE-MEASUREMENT IS NOT NEEDED, AND THAT IS THE WHOLE POINT. The morphometry
stores geometry in PIXELS - area_px2, feret_px, perimeter_px - and converts to
microns on the way out. Pixel geometry does not depend on the scale, so the
outlines somebody drew are still exactly right. Only the conversion was wrong,
and a conversion can be redone arithmetically. Asking Andres to re-outline
myocytes he has already outlined would be throwing away good work to fix a
multiplication.

EACH COLUMN SCALES BY ITS OWN POWER, and getting this wrong is the obvious way
to make things worse rather than better:

    length      x k        (um, per um)
    area        x k^2      (um2)
    per-length  x 1/k      (per um)
    per-area    x 1/k^2    (per um2)
    ratios      unchanged  (aspect ratio, circularity, solidity, anisotropy)
    counts      unchanged  (sarc_number)

A COLUMN THIS DOES NOT RECOGNISE IS LEFT ALONE AND REPORTED, never guessed at.
Silently scaling a column whose units are misread is how a corrected file
becomes worse than the original - and unlike the original, it would look
authoritative.

THE ORIGINAL FILE IS NEVER OVERWRITTEN. A corrected copy is written alongside
and the correction is recorded in it, so a reader a year from now can tell a
corrected file from an original at a glance rather than by remembering.
"""
from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path

# The specific error this was written for.
WRONG_UM_PX = 1.10619
RIGHT_UM_PX = 0.05442

# Suffix -> power of the scale factor. Order matters: the longest suffix must
# be tested first, or "_per_um2" is matched by "_um2".
POWERS = (
    ("_per_um2", -2),
    ("_per_um", -1),
    ("_um2", 2),
    ("_um", 1),
    ("_px2", 0),
    ("_px", 0),
)

# Columns that carry no length units at all. Listed explicitly rather than
# inferred, so an unfamiliar name is reported rather than assumed harmless.
DIMENSIONLESS = {
    "aspect_ratio", "circularity", "solidity", "anisotropy",
    "sarc_number", "sarc_cv", "sarc_mode", "sarc_quality", "calib_flag",
    "sarc_parallel_proxy", "wave_n_seeded", "wave_n_manual",
    "wave_n_relabelled", "myocyte_id", "length_fraction",
}

# Degrees are not lengths; scaling an angle would silently rotate the result.
ANGLE_HINTS = ("_deg", "_angle", "_rad")


class RescaleError(Exception):
    """Refusals that name the consequence."""


def power_for(column):
    """How this column scales, or None if it cannot be determined."""
    name = column.strip()
    low = name.lower()
    if low in DIMENSIONLESS:
        return 0
    if any(h in low for h in ANGLE_HINTS):
        return 0
    if low in {"um_px", "um_per_px", "scale_um_px"}:
        return "scale"
    for suffix, power in POWERS:
        if low.endswith(suffix):
            return power
    return None


def plan(columns, wrong_um_px=WRONG_UM_PX, right_um_px=RIGHT_UM_PX):
    """What would change, before anything does."""
    if not wrong_um_px or not right_um_px:
        raise RescaleError(
            "Both the wrong and the correct scale are required. A correction "
            "that guesses one of them produces numbers that look precise and "
            "are not.")
    k = float(right_um_px) / float(wrong_um_px)
    scaled, unchanged, unknown = {}, [], []
    for col in columns:
        p = power_for(col)
        if p is None:
            unknown.append(col)
        elif p == "scale":
            scaled[col] = "scale"
        elif p == 0:
            unchanged.append(col)
        else:
            scaled[col] = k ** p
    return {
        "factor": k, "wrong_um_px": float(wrong_um_px),
        "right_um_px": float(right_um_px),
        "scaled": scaled, "unchanged": unchanged, "unknown": unknown,
        "why": (f"Lengths change by {k:.5f}x, areas by {k ** 2:.6f}x. A "
                f"{k:.5f} factor means the original values were "
                f"{1 / k:.1f}x too large."),
        "unknown_note": (
            f"{len(unknown)} column(s) could not be classified and will be "
            f"COPIED UNCHANGED: {', '.join(unknown)}. Guessing at a column "
            f"whose units are unclear is how a corrected file becomes worse "
            f"than the original while looking authoritative."
            if unknown else None),
    }


def rescale_csv(src, dest=None, *, wrong_um_px=WRONG_UM_PX,
                right_um_px=RIGHT_UM_PX, dry_run=True, note=""):
    """Write a corrected copy. The original is never touched."""
    src = Path(src)
    if not src.exists():
        raise RescaleError(f"{src} is not there.")
    with src.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise RescaleError(
            f"{src} has no rows. An empty corrected file would be "
            f"indistinguishable from a successful correction of nothing.")

    p = plan(rows[0].keys(), wrong_um_px, right_um_px)
    dest = Path(dest) if dest else src.with_name(
        src.stem + "_rescaled" + src.suffix)

    out_rows = []
    n_changed = 0
    for row in rows:
        new = dict(row)
        for col, factor in p["scaled"].items():
            raw = (row.get(col) or "").strip()
            if not raw:
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            if factor == "scale":
                new[col] = f"{float(right_um_px):.12g}"
            else:
                new[col] = f"{value * factor:.12g}"
            n_changed += 1
        # Marked in the data, not only in a sidecar. A corrected file that
        # loses its provenance on being copied is a corrected file that will
        # eventually be mistaken for an original.
        new["rescaled_from_um_px"] = f"{float(wrong_um_px):.12g}"
        new["rescaled_to_um_px"] = f"{float(right_um_px):.12g}"
        new["rescaled_utc"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
        if note:
            new["rescaled_note"] = note
        out_rows.append(new)

    result = {**p, "source": str(src), "dest": str(dest),
              "n_rows": len(rows), "n_values_changed": n_changed,
              "dry_run": bool(dry_run)}
    if dry_run:
        result["note"] = "Nothing written. Re-run with dry_run=False."
        return result

    with Path(dest).open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        writer.writeheader()
        writer.writerows(out_rows)
    result["note"] = f"Wrote {dest}. The original is unchanged."
    return result


# Typical scales by imaging modality. Confocal work sits near 0.05 um/px;
# plate-scale behavioural rigs sit near 1-5.
MODALITY_SCALES = {
    "confocal": (0.01, 0.5),
    "plate": (0.5, 20.0),
}


def looks_miscalibrated(um_px, modality=None, *, sarcomere_um=None,
                        sarc_lo=0.8, sarc_hi=6.0):
    """Is this recording miscalibrated? The scale ALONE cannot tell you.

    A CORRECTION OF MY OWN REASONING, found by testing. I first screened on
    the morphometry's CHECK_CALIBRATION band of 0.8-6.0 um, assuming it was a
    band for the scale. It is not - the morphometry applies it to mean
    SARCOMERE LENGTH in microns. And the bad value here, 1.10619 um/px, sits
    comfortably INSIDE 0.8-6.0. Screening scales against that band would have
    passed the very error this module exists to correct.

    The reason is worth stating: 1.1 um/px is a perfectly ordinary plate-scale
    calibration. Nothing about the number is wrong. It is only wrong for a
    CONFOCAL image, where 0.05 is expected. So a scale is suspicious relative
    to a declared modality and not on its own.

    WHAT ACTUALLY CAUGHT IT was the biology: sarcomere lengths came out about
    twenty times too long, which is why `sarcomere_um` is accepted here and is
    the more reliable signal. A measured quantity that lands outside its
    biological range is evidence; a plausible-looking scale is not.
    """
    try:
        value = float(um_px)
    except (TypeError, ValueError):
        return {"suspicious": True, "basis": "unparseable",
                "why": f"{um_px!r} is not a number, so nothing downstream "
                       f"that multiplies by it can be trusted."}
    if value <= 0:
        return {"suspicious": True, "basis": "non_positive",
                "why": "A scale must be positive."}

    out = {"um_px": value, "modality": modality, "suspicious": False,
           "basis": None, "why": None}

    # The reliable signal: a measured quantity outside its biological range.
    if sarcomere_um is not None:
        try:
            sarc = float(sarcomere_um)
        except (TypeError, ValueError):
            sarc = None
        if sarc and (sarc < sarc_lo or sarc > sarc_hi):
            out.update({
                "suspicious": True, "basis": "sarcomere_length",
                "why": (f"Mean sarcomere length is {sarc:g} um, outside the "
                        f"{sarc_lo}-{sarc_hi} um range sarcomeres occupy. "
                        f"This is the check that caught the original error - "
                        f"a measured quantity landing outside its biological "
                        f"range is evidence, where a plausible-looking scale "
                        f"is not.")})
            return out

    if modality:
        band = MODALITY_SCALES.get(str(modality).lower())
        if band is None:
            raise RescaleError(
                f"Unknown modality {modality!r}. Known: "
                f"{sorted(MODALITY_SCALES)}. Guessing which band applies "
                f"would decide whether a scale is an error or routine.")
        lo, hi = band
        if not lo <= value <= hi:
            out.update({
                "suspicious": True, "basis": "modality_mismatch",
                "why": (f"{value:g} um/px is outside the {lo}-{hi} um/px "
                        f"expected for {modality} imaging. A bar printed in "
                        f"um and read as mm gives roughly a 20x error, which "
                        f"is what this module corrects.")})
        return out

    out.update({
        "basis": "indeterminate",
        "why": (f"{value:g} um/px cannot be judged on its own. It is an "
                f"ordinary plate-scale calibration and a badly wrong confocal "
                f"one, and nothing about the number distinguishes those. Pass "
                f"a modality, or better a measured sarcomere length.")})
    return out
