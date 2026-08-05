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

MEASURED ON REAL DATA, AND IT INVERTED THE ADVICE ABOVE.
Run on the hand-curated Fiji extraction (`tests/parity/golden_input/
WormRGBCaMP_extracted_w1.csv`, one worm, 135 frames at 5 fps, 48 hemisegments),
the statistic in trouble is the MEAN, not the max:

  green_mean vs roi_area_px    median r = -0.34, |r| > 0.3 in 27 of 48
  green_max  vs roi_area_px    median r = -0.02, |r| > 0.3 in 11 of 48

and when the apparent calcium-curvature coupling is re-tested holding ROI area
fixed, 10 of the 22 relationships found with the mean largely disappear
(mean |r| 0.46 -> 0.24), against 1 of 13 for the max (0.41 -> 0.33).

The reason is visible in the same file: the median hemisegment ROI is 28 PIXELS
and its area swings 2.9x within a recording. At that size a band that is part
muscle and part dark non-muscle tissue has a mean dominated by how much dark
tissue happened to be included, which is exactly what changes as the animal
bends. The max, being set by the brightest muscle pixel, is comparatively
insulated. The synthetic fixture had homogeneous pixels and so showed the
opposite - it was measuring sampling noise in a uniform ROI, which is not the
situation.

AND THE CONFOUND HAS OPPOSITE SIGN ON THE TWO SIDES:

  ventral   area vs curvature   median r = -0.55   (20 of 24 negative)
  dorsal    area vs curvature   median r = +0.61   (21 of 24 positive)

which is the geometry - bending shrinks the ROI on the inside and grows it on
the outside. That makes a DORSAL-VERSUS-VENTRAL calcium comparison against
curvature the single analysis most exposed to this, because the artefact
produces the same antiphase pattern that alternating contraction would.

WHAT IS NOT YET KNOWN: the Fiji extraction has no median or p90 column, so the
two statistics expected to be most robust could not be tested on real data at
all. Re-extracting with tools/hemisegments.py, which computes them, is the way
to settle it.
"""
from __future__ import annotations

import numpy as np

STATS = ("mean", "median", "p90", "max", "min")

# Measured on WormRGBCaMP_extracted_w1.csv - ONE worm, 135 frames. Real, and
# not yet general: it establishes that the confound is present and material in
# this lab's data, not how large it is in every recording.
REAL_DATA_FINDINGS = {
    "source": "tests/parity/golden_input/WormRGBCaMP_extracted_w1.csv",
    "scope": "1 worm, 135 frames at 5 fps, 48 hemisegments, condition 1G",
    "median_roi_area_px": 28,
    "roi_area_swing": "2.9x within a hemisegment",
    "mean_vs_area_median_r": -0.34,
    "max_vs_area_median_r": -0.02,
    "curvature_relationships_lost_to_area": {"mean": "10 of 22", "max": "1 of 13"},
    "area_vs_curvature_by_side": {"ventral": -0.55, "dorsal": +0.61},
    "conclusion": (
        "On this data the MEAN is the compromised statistic and the max is "
        "comparatively robust - the reverse of what a homogeneous synthetic "
        "ROI predicts. Do not report a mean against a postural variable "
        "without area_control()."),
    "untested": ("median and p90 are absent from the Fiji extraction, so the "
                 "two expected to be most robust have never been checked on "
                 "real data."),
}


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


def relaxed_brightness(rows, channel="green", stat="max",
                       curv_col="seg_curv_deg", quantile=0.33,
                       absolute_curv_deg=None, area_key="roi_area_px"):
    """Brightness during RELAXATION - the elevated-resting-calcium measure.

    Relaxation is read from POSTURE, not from calcium: the frames in the bottom
    `quantile` of local |curvature|. That is what keeps the measure honest -
    selecting relaxed frames by low calcium and then reporting calcium in them
    would be circular, and `worm_kinetics.contraction_state` already avoids it
    the same way.

    THREE WAYS TO SUMMARISE, AND ONE OF THEM IS BIASED BY RECORDING LENGTH.

      mean_of_frame_max    the average of the per-frame maxima. n-independent.
      median_of_frame_max  the same, robust. n-independent.
      single_max           the largest value seen in ANY relaxed frame. This is
                           an extreme of extremes: it grows with the NUMBER of
                           relaxed frames, so an animal that spends more time
                           relaxed scores higher for that reason alone.

    The last one matters for a genotype comparison specifically. Dystrophic
    animals move less, so they have MORE relaxed frames, so a single-max
    measure is inflated in exactly the group expected to show the effect. The
    count is returned alongside so the two can be checked against each other,
    and the summary says so rather than leaving it to be noticed.

    ABSOLUTE OR RELATIVE THRESHOLD. With `quantile`, "relaxed" is the bottom
    third of THIS animal's own curvature range - so a stiff animal's relaxed
    frames may be more bent than a mobile animal's. Within one animal that is
    the right normalisation; ACROSS genotypes it means the two groups are not
    being held at the same posture. Pass `absolute_curv_deg` to threshold at a
    fixed bend instead, and compare the two.
    """
    key = f"{channel}_{stat}"
    v = np.array([r.get(key, np.nan) for r in rows], float)
    c = np.abs(np.array([r.get(curv_col, np.nan) for r in rows], float))
    a = np.array([r.get(area_key, np.nan) for r in rows], float)
    ok = np.isfinite(v) & np.isfinite(c)
    if ok.sum() < 20:
        raise BrightnessError(
            f"Only {int(ok.sum())} frames have both {key} and {curv_col}. A "
            f"relaxed-state measure over so few is describing a handful of "
            f"postures, not a resting level.")

    if absolute_curv_deg is not None:
        sel = ok & (c <= float(absolute_curv_deg))
        rule = f"|{curv_col}| <= {absolute_curv_deg} deg (absolute)"
    else:
        thr = float(np.quantile(c[ok], quantile))
        sel = ok & (c <= thr)
        rule = (f"bottom {quantile:.0%} of this animal's own |{curv_col}|, "
                f"i.e. <= {thr:.2f} deg")
    n_rel = int(sel.sum())
    if n_rel < 10:
        raise BrightnessError(
            f"Only {n_rel} relaxed frames under {rule}. Widen the threshold or "
            f"record longer; a resting level from fewer is one posture.")

    vr = v[sel]
    out = {
        "channel": channel, "statistic": stat, "relaxation_rule": rule,
        "n_relaxed_frames": n_rel,
        "n_frames_total": int(ok.sum()),
        "fraction_relaxed": round(n_rel / max(int(ok.sum()), 1), 4),
        "mean_of_frame_max": round(float(np.mean(vr)), 4),
        "median_of_frame_max": round(float(np.median(vr)), 4),
        "single_max": round(float(np.max(vr)), 4),
        "relaxed_roi_area_median": (round(float(np.nanmedian(a[sel])), 2)
                                    if np.isfinite(a).any() else None),
        "all_frames_roi_area_median": (round(float(np.nanmedian(a[ok])), 2)
                                       if np.isfinite(a).any() else None),
        "prefer": "median_of_frame_max",
        "why": ("mean_of_frame_max and median_of_frame_max do not depend on how "
                "many relaxed frames there were. single_max does: it is the "
                "largest of n draws and grows with n, so an animal that spends "
                "more time relaxed scores higher for that reason alone. In a "
                "genotype comparison that inflates whichever group moves less, "
                "which is the dystrophic one."),
        "posture_not_calcium": (
            "Relaxed frames were chosen by curvature, so this is not circular: "
            "calcium was not used to decide which frames count as resting."),
    }
    if absolute_curv_deg is None:
        out["threshold_is_relative"] = (
            "The threshold is this animal's own bottom "
            f"{quantile:.0%}, so a stiff animal's 'relaxed' frames may be more "
            "bent than a mobile animal's. Within one animal that is the right "
            "normalisation; across genotypes it means the groups are not held "
            "at the same posture. Re-run with absolute_curv_deg to check.")
    return out


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
