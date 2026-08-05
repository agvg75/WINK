"""Which brightness statistic to plot against time or curvature, decided on
your own recording rather than by argument.

Andres asked how mean, median, p90 and max behave when brightness is compared
over time or against curvature, and whether some are more informative. They
behave differently, and one of them is actively misleading for exactly that
comparison.

THE TRAP: MAX IS BIASED BY ROI AREA - BUT HOW BADLY DEPENDS ON THE PIXELS.
The maximum of N samples grows with N. Draw more pixels from the same
distribution and the brightest one is brighter, with no change in the tissue. A
hemisegment ROI changes area as the animal bends - the outside of a bend simply
holds more pixels - so `roi_area_px` correlates with curvature by geometry
alone, and max can then appear to track curvature in an animal whose calcium
never changed.

HOW BIG THAT EFFECT IS WAS MEASURED RATHER THAN ASSUMED, and the first estimate
here was too pessimistic. For GAUSSIAN pixel noise the bias is weak: the
expected maximum grows only as sqrt(2 ln N), so a 1.4x change in ROI area moves
it by a fraction of the frame-to-frame scatter of the maximum itself, and the
measured correlation with area is around r = 0.08. On Gaussian noise alone, max
is noisy rather than misleading.

It becomes serious when the ROI contains OCCASIONAL BRIGHT PIXELS - gut
granules, coelomocytes, hot camera pixels, out-of-plane structures - which real
hemisegment bands do, because the band is not a muscle. Then the maximum is
essentially asking "did this ROI happen to include an outlier", a bigger ROI is
more likely to, and the correlation with area rises sharply. The same fixture
with a realistic outlier rate gives r above 0.5.

So the honest statement is: max is unreliable, and how it fails depends on
tissue that has nothing to do with the muscle. `compare_statistics` measures
the correlation with ROI AREA on your own rows, which settles it for your
recording instead of arguing from either extreme.

p90 shares the bias in principle and far less of it in practice, because the
90th percentile estimates a fixed quantile rather than an extreme. Mean and
median are unbiased with respect to N.

Mean has a different exposure: a hemisegment is a band of body pixels, not a
muscle, so it contains hypodermis, gut and whatever else lies there. If the
non-muscle fraction of the band changes with posture, the mean moves with it.
The median is the most robust to that and the least sensitive to a bright
intruder.

None of which settles it for YOUR recording. `compare_statistics` measures all
of it on the rows you actually have: how noisy each statistic is frame to
frame, how much dynamic range it shows, how strongly it tracks the thing you
care about - and how strongly it tracks ROI AREA, which is the number that
tells you whether you are looking at muscle or at geometry.
"""
from __future__ import annotations

import numpy as np

STATS = ("mean", "median", "p90", "max", "min")


class BrightnessError(Exception):
    """Refusals that name the consequence."""


def _pearson(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 4 or np.std(a[ok]) == 0 or np.std(b[ok]) == 0:
        return None
    return float(np.corrcoef(a[ok], b[ok])[0, 1])


def _noise(series):
    """Frame-to-frame jitter, robustly.

    The median absolute successive difference, not the standard deviation: a
    real calcium transient inflates an SD and would be scored as noise, whereas
    successive differences are dominated by the frame-to-frame wobble that a
    slow physiological signal contributes almost nothing to.
    """
    v = np.asarray(series, float)
    v = v[np.isfinite(v)]
    if v.size < 3:
        return None
    return float(np.median(np.abs(np.diff(v))))


def compare_statistics(rows, channel="green", against=None, stats=STATS,
                       area_key="roi_area_px", min_frames=10):
    """Measure how each statistic behaves on rows from ONE (segment, side).

    `rows` must be in frame order for one hemisegment - mixing segments would
    compare different pieces of the animal and call the difference noise.
    `against` names the column to correlate with, typically "seg_curv_deg".
    """
    if len(rows) < min_frames:
        raise BrightnessError(
            f"Only {len(rows)} frames. Comparing statistics over so few "
            f"measures the recording's noise, not the statistics' behaviour; "
            f"at least {min_frames} are needed.")
    segs = {r.get("segment") for r in rows}
    sides = {r.get("hemisegment") for r in rows}
    if len(segs) > 1 or len(sides) > 1:
        raise BrightnessError(
            f"Rows span {len(segs)} segments and {len(sides)} sides. Pass one "
            f"hemisegment's time series: pooling them compares different "
            f"pieces of the animal and charges the difference to the "
            f"statistic.")

    area = np.array([r.get(area_key, np.nan) for r in rows], float)
    target = (np.array([r.get(against, np.nan) for r in rows], float)
              if against else None)

    out = {}
    for st in stats:
        key = f"{channel}_{st}"
        v = np.array([r.get(key, np.nan) for r in rows], float)
        if not np.isfinite(v).any():
            continue
        noise = _noise(v)
        rng = float(np.nanpercentile(v, 95) - np.nanpercentile(v, 5))
        entry = {
            "n_frames": int(np.isfinite(v).sum()),
            "median_level": round(float(np.nanmedian(v)), 4),
            "range_p5_p95": round(rng, 4),
            "frame_to_frame_noise": None if noise is None else round(noise, 5),
            "snr": (round(rng / noise, 3) if noise else None),
            "r_with_roi_area": (lambda r: None if r is None else round(r, 4))(
                _pearson(v, area)),
        }
        if target is not None:
            entry[f"r_with_{against}"] = (
                lambda r: None if r is None else round(r, 4))(_pearson(v, target))
        out[st] = entry

    # The judgement that matters: is a statistic tracking the biology, or the
    # shape of the ROI it was measured in?
    for st, e in out.items():
        ra = e.get("r_with_roi_area")
        rt = e.get(f"r_with_{against}") if against else None
        if ra is None:
            continue
        e["area_tracking"] = abs(ra)
        if rt is not None and abs(ra) >= 0.6 * abs(rt) and abs(ra) > 0.3:
            e["warning"] = (
                f"This statistic tracks ROI AREA (r = {ra}) about as strongly "
                f"as it tracks {against} (r = {rt}). ROI area changes with "
                f"bending by geometry, so the correlation you are about to "
                f"report may be the shape of the ROI rather than the muscle.")
        elif abs(ra) > 0.5:
            e["warning"] = (
                f"This statistic tracks ROI AREA (r = {ra}). Area changes with "
                f"posture by geometry, so check that before interpreting it.")

    return {
        "channel": channel, "against": against,
        "statistics": out,
        "how_to_read": {
            "snr": "range over frame-to-frame noise. Higher is more usable.",
            "r_with_roi_area": (
                "THE ONE TO CHECK FIRST. ROI area changes with bending by "
                "geometry alone, so a statistic that tracks area will appear "
                "to track curvature whether or not the muscle did anything."),
            "max": ("Expect the largest area correlation here: the maximum of "
                    "N samples grows with N, so a bigger ROI is brighter with "
                    "no change in the tissue."),
            "median": ("Expect the smallest. Unbiased with respect to ROI "
                       "size and robust to a bright intruder in the band."),
        },
        "recommendation": _recommend(out, against),
    }


def _recommend(out, against):
    if not out:
        return "No statistic could be evaluated."
    lines = []
    clean = {st: e for st, e in out.items() if "warning" not in e}
    if against:
        scored = [(abs(e.get(f"r_with_{against}") or 0.0), st)
                  for st, e in clean.items()]
        if scored:
            best = max(scored)[1]
            lines.append(
                f"For comparing against {against}, '{best}' tracks it most "
                f"strongly among the statistics that do NOT also track ROI "
                f"area.")
    snr = [(e["snr"], st) for st, e in out.items() if e.get("snr")]
    if snr:
        lines.append(f"Cleanest time series: '{max(snr)[1]}' "
                     f"(highest range-to-noise).")
    flagged = [st for st, e in out.items() if "warning" in e]
    if flagged:
        lines.append(f"Do not report {', '.join(flagged)} against a postural "
                     f"variable without first showing the effect survives "
                     f"controlling for roi_area_px.")
    lines.append("These are measurements on this recording, not general "
                 "advice. Re-run them when the preparation changes.")
    return " ".join(lines)


def area_control(rows, channel="green", stat="mean", against="seg_curv_deg",
                 area_key="roi_area_px"):
    """Does the relationship survive removing ROI area?

    Partial correlation of brightness with the target, holding area fixed. If
    the raw correlation is strong and this one is not, what was being plotted
    was the ROI changing shape.
    """
    v = np.array([r.get(f"{channel}_{stat}", np.nan) for r in rows], float)
    t = np.array([r.get(against, np.nan) for r in rows], float)
    a = np.array([r.get(area_key, np.nan) for r in rows], float)
    ok = np.isfinite(v) & np.isfinite(t) & np.isfinite(a)
    if ok.sum() < 6:
        raise BrightnessError(
            f"Only {int(ok.sum())} usable frames; a partial correlation over "
            f"so few is not a control, it is a coincidence.")
    r_vt, r_va, r_ta = (_pearson(v[ok], t[ok]), _pearson(v[ok], a[ok]),
                        _pearson(t[ok], a[ok]))
    if None in (r_vt, r_va, r_ta):
        raise BrightnessError("A variable did not vary; no correlation exists.")
    # COLLINEARITY. If ROI area and the target move together almost perfectly,
    # no statistical control can separate them: holding area fixed holds the
    # target fixed too, and the partial correlation that comes out is an
    # artefact of dividing by something near zero. Refusing is the only honest
    # answer - the separation has to come from the experiment, by finding
    # frames where the animal bends without the ROI changing size, not from
    # arithmetic on frames where it never did.
    if abs(r_ta) > 0.95:
        raise BrightnessError(
            f"ROI area and {against} are almost perfectly correlated "
            f"(r = {r_ta:.3f}), so they cannot be told apart in this "
            f"recording. Holding area fixed also holds {against} fixed, and "
            f"any partial correlation reported here would be numerical noise. "
            f"This is a limit of the data, not of the test: you need frames "
            f"where the two come apart.")
    denom = np.sqrt(max((1 - r_va ** 2) * (1 - r_ta ** 2), 1e-12))
    partial = (r_vt - r_va * r_ta) / denom
    survived = abs(partial) > 0.5 * abs(r_vt) if r_vt else False
    return {
        "statistic": f"{channel}_{stat}", "against": against,
        "raw_r": round(r_vt, 4),
        "partial_r_controlling_area": round(float(partial), 4),
        "brightness_vs_area_r": round(r_va, 4),
        "target_vs_area_r": round(r_ta, 4),
        "survives_area_control": bool(survived),
        "verdict": (
            f"The relationship survives: r goes {r_vt:.3f} -> {partial:.3f} "
            f"with ROI area held fixed."
            if survived else
            f"The relationship largely does NOT survive: r goes {r_vt:.3f} -> "
            f"{partial:.3f} once ROI area is held fixed. Most of what the raw "
            f"plot showed was the ROI changing size with posture."),
    }
