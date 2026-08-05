"""Which end of the spine is the head - the one thing Fiji still decides for us.

WHY THIS MODULE EXISTS. `population_swimming._ordered_spine` already produces a
good midline, and `_orient_spines` already keeps its two ends CONSISTENT from
frame to frame. What neither does is say which end is the head. Consistency is
not identity: a track can be perfectly stable end-to-end and still be labelled
backwards for its whole length.

That distinction is not cosmetic. Get it wrong and segment 0 is the tail rather
than the head, so every anterior-posterior gradient reverses; the calcium wave
that travels head-to-tail is reported as travelling tail-to-head; and the
dorsal/ventral assignment, which is derived by taking left and right relative to
the head-to-tail direction, swaps sides. One boolean silently inverts three
different results, and each of them still looks entirely plausible.

So the head call is made ONCE PER TRACK, not per frame. Frame-to-frame
orientation is already consistent, so a per-frame vote would only add noise to a
decision the geometry has already made; and a call that flips mid-track produces
a discontinuity no downstream analysis can detect.

THE CUES, and why only two of them are allowed to vote:

  taper (weighted)   The tail tapers to a fine whip; the head is blunt. This is
                     static, needs one frame, and does not care what the animal
                     is doing. The strongest cue we have.
  motion (weighted)  Worms translate head-first far more often than not, so the
                     leading end during sustained movement is the head. Reliable
                     when the animal is actually going somewhere, useless when
                     it is stationary, and actively wrong during a reversal -
                     which is why it is scored over the whole track and reports
                     the fraction of moving frames that agreed.
  wiggle (NOT weighted, diagnostic only)  On a crawling worm the head sweeps
                     more than the tail while foraging. On a SWIMMING worm the
                     tail whips at least as hard, so the cue inverts exactly in
                     the preparation this lab uses most. It is computed and
                     reported because it is informative when it agrees, but it
                     is not allowed to move the answer.

A cue that is right most of the time is worth having; a cue that is wrong in a
known, common condition is worth reporting and not trusting. Confidence comes
from how strongly the weighted cues agree, and is meant to be fed to
`app/confidence_gate` so that spans with an uncertain head call can be excluded
rather than quietly analysed backwards.
"""
from __future__ import annotations

import numpy as np


class HeadTailError(Exception):
    """Refusals that name the consequence."""


def _noisy_or(mags):
    """Combine INDEPENDENT evidence for one binary question.

    Two agreeing cues should be more convincing than either alone. Averaging
    their magnitudes does the opposite - a strong cue paired with a weaker one
    that agrees comes out below the strong cue by itself, which is the wrong
    direction for corroboration. Only valid for cues that fail independently;
    applied to two views of the same measurement it inflates the result.
    """
    p = 1.0
    for m in mags:
        p *= 1.0 - min(float(abs(m)), 0.99)
    return 1.0 - p


def _combine_independent(scores):
    """Signed combination of independent cue scores. Returns (sign, magnitude)."""
    vals = [float(v) for v in scores.values() if v is not None]
    if not vals:
        return 0, 0.0
    sign = 1 if sum(vals) > 0 else -1
    support = [v for v in vals if np.sign(v) == sign]
    oppose = [v for v in vals if np.sign(v) != sign]
    return sign, max(0.0, _noisy_or(support) - _noisy_or(oppose))


def width_profile(mask, spine, max_radius_px=60, step=0.5):
    """Body width perpendicular to the midline at each spine point.

    Marching outward along the normal until the mask ends measures the animal
    rather than its bounding box, which is what makes the taper of the tail
    visible at all. Points whose normal leaves the image are returned as NaN
    instead of a truncated width, because a worm touching the frame edge would
    otherwise look like it tapers there.
    """
    m = np.asarray(mask, dtype=bool)
    sp = np.asarray(spine, dtype=float)
    if sp.ndim != 2 or sp.shape[1] != 2 or sp.shape[0] < 3:
        raise HeadTailError(
            f"A spine must be (N, 2) with at least 3 points; got {sp.shape}.")
    h, w = m.shape

    # central-difference tangent, so the normal at each point uses both sides
    tan = np.gradient(sp, axis=0)
    norm = np.hypot(tan[:, 0], tan[:, 1])
    norm[norm == 0] = 1.0
    tan = tan / norm[:, None]
    perp = np.column_stack([-tan[:, 1], tan[:, 0]])   # (x, y) ordering

    widths = np.full(sp.shape[0], np.nan)
    radii = np.arange(step, max_radius_px, step)
    for i in range(sp.shape[0]):
        total, ran_off = 0.0, False
        for sign in (1.0, -1.0):
            reach = 0.0
            for r in radii:
                x = sp[i, 0] + sign * perp[i, 0] * r
                y = sp[i, 1] + sign * perp[i, 1] * r
                xi, yi = int(round(x)), int(round(y))
                if xi < 0 or yi < 0 or xi >= w or yi >= h:
                    ran_off = True
                    break
                if not m[yi, xi]:
                    break
                reach = r
            total += reach
        if not ran_off:
            widths[i] = total
    return widths


def _taper_terms(rel, thresh=0.85):
    """Taper LENGTH and TIP bluntness for one half, ordered from the tip inward.

    Length is where the body first reaches `thresh` of its midbody width, as a
    fraction of the half it was measured over. Tip is the relative width at the
    very end.
    """
    n = rel.size
    idx = np.flatnonzero(np.isfinite(rel) & (rel >= thresh))
    if idx.size == 0:
        length, reached = 1.0, False
    else:
        length, reached = float(idx[0]) / max(n - 1, 1), True
    tip = float(rel[0]) if np.isfinite(rel[0]) else np.nan
    slope = (thresh - tip) / max(length, 1e-6) if np.isfinite(tip) else np.nan
    return length, tip, slope, reached


def taper_cue(widths, thresh=0.85):
    """Score in [-1, 1]: positive means END 0 is the head.

    BOTH ENDS TAPER - that is the point, and comparing terminal widths alone
    misses it. Per Andres: the TAIL taper is LONG and SHALLOW and comes to a
    POINT; the HEAD taper is SHORT, STEEP and ROUND. So the discriminating
    information is in the SHAPE of the width profile, not its terminal value: a
    steep head taper can make the last few percent of the head as narrow as the
    tail, and a cue built on mean terminal width would then read the two ends as
    nearly identical and decide on noise.

    Two terms vote, and they are close to independent:
      length  how far from the tip the body reaches full width. Short = head.
      tip     relative width at the very end. Blunt = head, pointed = tail.

    Slope is computed and reported but does NOT vote: it is (thresh - tip) /
    length, so it is fully determined by the other two and voting with it would
    simply count them twice.
    """
    v = np.asarray(widths, dtype=float)
    n = v.size
    if n < 8:
        return None, {"reason": f"only {n} spine points; too few to see a taper"}
    mid = np.nanmedian(v[n // 3: 2 * n // 3])
    if not np.isfinite(mid) or mid <= 0:
        return None, {"reason": "midbody width could not be measured"}
    rel = v / mid
    half = max(n // 2, 4)
    L0, T0, S0, R0 = _taper_terms(rel[:half], thresh)
    L1, T1, S1, R1 = _taper_terms(rel[::-1][:half], thresh)
    if not (np.isfinite(T0) and np.isfinite(T1)):
        return None, {"reason": ("a tip width could not be measured (the animal "
                                 "may touch the frame edge)")}

    # end0 is the head if its taper is SHORTER and its tip is BLUNTER
    s_len = (L1 - L0) / (L1 + L0) if (L1 + L0) > 0 else 0.0
    s_tip = (T0 - T1) / (T0 + T1) if (T0 + T1) > 0 else 0.0
    score = float((s_len + s_tip) / 2.0)
    return score, {
        "end0_taper_length_frac": round(L0, 4), "end1_taper_length_frac": round(L1, 4),
        "end0_tip_rel_width": round(T0, 4), "end1_tip_rel_width": round(T1, 4),
        "end0_slope": round(float(S0), 4), "end1_slope": round(float(S1), 4),
        "slope_reported_not_weighted": True,
        "why_slope_not_weighted": ("slope is (threshold - tip) / length, so it "
                                   "is determined by the two terms that do "
                                   "vote and would only count them twice"),
        "length_term": round(float(s_len), 4), "tip_term": round(float(s_tip), 4),
        "midbody_width_px": round(float(mid), 3),
        "both_ends_reached_full_width": bool(R0 and R1),
    }


def _looks_like_transmitted(image, dark_fraction_max=0.45):
    """Is this DIC/brightfield rather than fluorescence?

    Fluorescence has a genuinely dark background - most of the frame is near
    zero. Transmitted light has none: the medium is lit, so almost nothing is
    dark. The pharynx cue only means anything on transmitted light, and running
    it on a GCaMP frame would score whichever end happened to be brighter.
    """
    a = np.asarray(image, dtype=float)
    hi = float(np.percentile(a, 99.5))
    if hi <= 0:
        return False, 1.0
    dark = float(np.mean(a < 0.15 * hi))
    return dark <= dark_fraction_max, dark


def pharynx_cue(image, spine, mask, end_fraction=0.2, radius_px=12.0,
                um_per_px=None, pharynx_length_um=100.0):
    """Score in [-1, 1]: positive means END 0 carries the pharynx.

    Per Andres: the head contains the pharynx and it is normally VISIBLE IN DIC
    - this lab scores pharyngeal pumping from exactly these movies - while the
    tail has no comparable structure. So the anterior end has internal texture
    the posterior end does not, and texture is measurable without recognising
    the organ.

    Contrast is normalised by local mean intensity, so it measures structure
    rather than illumination; an unevenly lit field would otherwise favour
    whichever end sat in the brighter part of the frame.

    REFUSES ON FLUORESCENCE. There the pharynx has no reason to be the textured
    end, and on a GCaMP recording this would simply score whichever end was
    brighter and call it a head.
    """
    img = np.asarray(image, dtype=float)
    m = np.asarray(mask, dtype=bool)
    sp = np.asarray(spine, dtype=float)
    if img.shape != m.shape:
        raise HeadTailError(
            f"Image {img.shape} and mask {m.shape} describe different frames.")

    ok, dark = _looks_like_transmitted(img)
    if not ok:
        return None, {"reason": (f"this frame looks like fluorescence "
                                 f"({dark:.0%} of it is dark background), and "
                                 f"the pharynx is only reliably visible in "
                                 f"transmitted light. On fluorescence this cue "
                                 f"would score whichever end was brighter."),
                      "dark_fraction": round(dark, 4)}

    gy, gx = np.gradient(img)
    grad = np.hypot(gy, gx)
    h, w = img.shape
    yy, xx = np.mgrid[0:h, 0:w]
    n = sp.shape[0]
    k = max(int(round(n * end_fraction)), 2)

    # MEASURE THE INTERIOR, NOT THE OUTLINE. The pharynx is internal structure,
    # but a gradient taken over the whole mask is dominated by the body edge -
    # and the tail, being thin, has far more edge per unit area than anywhere
    # else. Left uncorrected the tail scores as the most "textured" part of the
    # animal, and the cue quietly turns into a second, worse taper detector
    # instead of the independent evidence it is supposed to be.
    from scipy import ndimage as ndi
    interior = ndi.binary_erosion(m, iterations=2)
    if not interior.any():
        interior = m
    body_level = float(np.mean(img[interior])) if interior.any() else 0.0

    def _band_pixels(points):
        sel = np.zeros((h, w), bool)
        for px, py in points:
            sel |= (xx - px) ** 2 + (yy - py) ** 2 <= radius_px ** 2
        sel &= interior
        return sel if sel.sum() >= 20 else None

    def texture(points):
        sel = _band_pixels(points)
        if sel is None:
            return None
        level = float(np.mean(img[sel]))
        if level <= 0:
            return None
        return float(np.mean(grad[sel]) / level)

    def brightness(points):
        """Mean intensity relative to the whole body.

        Per Andres: in transmitted light the pharynx makes the HEAD LIGHTER
        than the region behind it, while the tail looks like the rest of the
        body. That is an INTENSITY fact, independent of the structural one that
        `texture` measures - different physics, so the two can corroborate.
        """
        sel = _band_pixels(points)
        if sel is None or body_level <= 0:
            return None
        return float(np.mean(img[sel]) / body_level)

    # WITHOUT A SCALE: compare the terminal fifth of each end. Works, but it is
    # not specific - gut granules, debris or a smear score as texture too.
    if not um_per_px:
        a, b = texture(sp[:k]), texture(sp[-k:])
        if a is None or b is None:
            return None, {"reason": "too few pixels inside the mask at one end"}
        denom = a + b
        score = float((a - b) / denom) if denom > 0 else 0.0
        return score, {
            "end0_texture": round(a, 5), "end1_texture": round(b, 5),
            "dark_fraction": round(dark, 4), "used_scale": False,
            "caveat": ("no um_per_px was given, so this is generic texture: "
                       "anything structured near an end scores, whether or not "
                       "it is a pharynx. Pass the scale to test for a pharynx "
                       "rather than for texture."),
        }

    # WITH A SCALE: use the pharynx's KNOWN LENGTH. This is what transfers from
    # the confocal pharynx work - not its lumen and bulb detectors, which need
    # a magnification these freely-moving movies do not have, but the anatomy
    # those detectors established. The pharynx runs roughly one fixed physical
    # length back from the anterior tip and then STOPS at the isthmus/intestine
    # junction. So the diagnostic signature is not "textured" but "textured for
    # about a pharynx length and then not" - a step that dirt, gut contents and
    # uneven illumination do not produce, because none of them know where the
    # pharynx ends.
    seg = np.linalg.norm(np.diff(sp, axis=0), axis=1)
    arc = np.r_[0.0, np.cumsum(seg)] * float(um_per_px)
    total = float(arc[-1])
    L = float(pharynx_length_um)
    if total < 2.2 * L:
        return None, {"reason": (f"the traced body is only {total:.0f} um long, "
                                 f"too short to hold a {L:.0f} um pharynx and "
                                 f"an equal length behind it for comparison"),
                      "body_length_um": round(total, 1)}

    def band(from_end, lo, hi):
        d = arc if from_end == 0 else (total - arc)
        idx = np.flatnonzero((d >= lo) & (d < hi))
        return sp[idx] if idx.size >= 2 else None

    conf = {"texture": {}, "brightness": {}}
    parts = {}
    for end in (0, 1):
        near, behind = band(end, 0.0, L), band(end, L, 2.0 * L)
        if near is None or behind is None:
            return None, {"reason": (f"end {end} did not yield two "
                                     f"{L:.0f} um bands to compare")}
        for what, fn in (("texture", texture), ("brightness", brightness)):
            vn, vb = fn(near), fn(behind)
            if vn is None or vb is None:
                # Too thin to have an interior at all - most likely the very tip
                # of the tail. Scored as NO EVIDENCE (0), not as an extreme
                # value: reading "nothing measurable here" as "nothing there"
                # would make the thin end look pharynx-free by construction and
                # turn this back into a taper detector.
                conf[what][end] = 0.0
                parts[f"end{end}_{what}_unmeasurable"] = True
                continue
            conf[what][end] = (vn - vb) / (vn + vb) if (vn + vb) > 0 else 0.0
            parts[f"end{end}_{what}_first_{int(L)}um"] = round(vn, 5)
            parts[f"end{end}_{what}_next_{int(L)}um"] = round(vb, 5)
            parts[f"end{end}_{what}_confinement"] = round(float(conf[what][end]), 4)

    sub = {what: float(np.clip(c[0] - c[1], -1.0, 1.0)) for what, c in conf.items()}
    sign, mag = _combine_independent(sub)
    score = float(sign * mag)
    return score, {
        **parts,
        "texture_score": round(sub["texture"], 4),
        "brightness_score": round(sub["brightness"], 4),
        "dark_fraction": round(dark, 4),
        "used_scale": True,
        "body_length_um": round(total, 1),
        "pharynx_length_um": L,
        "measure": (
            "Two features CONFINED to the first pharynx length of each end, "
            "each compared with the equal length just behind it. STRUCTURE "
            "(texture) and INTENSITY (the head reads lighter than the body "
            "behind it, while the tail matches the body) are different "
            "physics, so they are combined as independent evidence rather "
            "than averaged. Measuring confinement rather than absolute value "
            "is what makes this a test for a pharynx: debris, gut contents and "
            "uneven illumination raise both bands together and cancel."),
    }


def motion_cue(spines, min_speed_px=0.5, min_straightness=0.15, min_net_px=5.0):
    """Score in [-1, 1]: positive means END 0 led the direction of travel.

    Only frames where the animal actually moved contribute. A stationary worm
    would otherwise contribute pure noise with the same weight as a swimming
    one, and enough of it would outvote the frames that carry the information.

    AND THE ANIMAL MUST ACTUALLY HAVE GONE SOMEWHERE. An undulating worm that
    is not translating - swimming against a tether, or thrashing in a drop -
    still shifts its centroid every single frame as the body wave passes
    through it, and those shifts are large enough to clear any per-frame speed
    threshold. Nothing about them points at the head. So the cue is gated on
    STRAIGHTNESS, the net displacement over the track divided by the total path
    the centroid travelled: near 1 the animal went somewhere, near 0 it wobbled
    in place and this cue has nothing to say.
    """
    valid = [np.asarray(s, dtype=float) for s in spines if s is not None]
    if len(valid) < 3:
        return None, {"reason": f"only {len(valid)} usable spines"}

    centres = np.array([s.mean(axis=0) for s in valid])
    path = float(np.sum(np.linalg.norm(np.diff(centres, axis=0), axis=1)))
    net = float(np.linalg.norm(centres[-1] - centres[0]))
    straightness = net / path if path > 0 else 0.0
    if net < min_net_px or straightness < min_straightness:
        return None, {
            "reason": (f"the animal did not go anywhere - net displacement "
                       f"{net:.1f} px along {path:.1f} px of path "
                       f"(straightness {straightness:.2f}). An undulating worm "
                       f"shifts its centroid every frame without translating, "
                       f"and reading those shifts as a direction of travel "
                       f"would point at whichever end the body wave happened "
                       f"to favour."),
            "net_displacement_px": round(net, 2),
            "path_length_px": round(path, 2),
            "straightness": round(straightness, 4)}

    votes, speeds = [], []
    prev = valid[0]
    for cur in valid[1:]:
        if cur.shape != prev.shape:
            prev = cur
            continue
        step = cur.mean(axis=0) - prev.mean(axis=0)
        speed = float(np.hypot(*step))
        if speed >= min_speed_px:
            # unit vector from the body centre toward end 0
            axis = cur[0] - cur.mean(axis=0)
            a_norm = np.hypot(*axis)
            if a_norm > 0:
                votes.append(float(np.dot(step, axis) / (speed * a_norm)))
                speeds.append(speed)
        prev = cur

    if len(votes) < 3:
        return None, {"reason": (f"only {len(votes)} frames exceeded "
                                 f"{min_speed_px} px of movement - the animal "
                                 f"was too still for direction to mean anything")}
    v = np.asarray(votes)
    return float(np.mean(v)), {
        "n_moving_frames": int(v.size),
        "fraction_agreeing": round(float(np.mean(np.sign(v) == np.sign(np.mean(v)))), 4),
        "mean_speed_px": round(float(np.mean(speeds)), 3),
        "net_displacement_px": round(net, 2),
        "straightness": round(straightness, 4),
    }


def wiggle_cue(spines):
    """DIAGNOSTIC ONLY. Positive means end 0 swept more than end 1.

    Deliberately not weighted in the decision. A crawling worm sweeps its head
    while foraging, but a swimming worm whips its tail at least as hard, so this
    cue inverts in the preparation this lab images most. Reported because
    agreement with the weighted cues is reassuring and disagreement is worth
    seeing; never allowed to decide.
    """
    valid = [np.asarray(s, dtype=float) for s in spines if s is not None]
    if len(valid) < 5:
        return None, {"reason": f"only {len(valid)} usable spines"}
    n = valid[0].shape[0]
    k = max(int(round(n * 0.15)), 2)

    def terminal_angles(which):
        out = []
        for s in valid:
            if s.shape[0] != n:
                continue
            seg = s[:k] if which == 0 else s[-k:][::-1]
            body = s.mean(axis=0)
            v = seg[0] - body
            out.append(np.arctan2(v[1], v[0]))
        return np.unwrap(np.asarray(out)) if len(out) > 2 else None

    a, b = terminal_angles(0), terminal_angles(1)
    if a is None or b is None:
        return None, {"reason": "too few consistent spines"}
    sa, sb = float(np.std(np.diff(a))), float(np.std(np.diff(b)))
    denom = sa + sb
    score = float((sa - sb) / denom) if denom > 0 else 0.0
    return score, {"end0_sweep_rad": round(sa, 4), "end1_sweep_rad": round(sb, 4),
                   "weighted": False,
                   "why_not_weighted": ("the head sweeps more when crawling but "
                                        "the tail whips at least as hard when "
                                        "swimming, so this cue inverts in the "
                                        "preparation used most here")}


WEIGHTS = {"taper": 0.45, "pharynx": 0.35, "motion": 0.20}


def identify_head(spines, masks=None, images=None, min_confidence=0.35,
                  um_per_px=None):
    """One head call for the whole track, with a confidence and every cue shown.

    Returns a dict with `head_end` (0 or 1, or None when refused), `confidence`
    in [0, 1], the per-cue scores, and - when the call is weak or the cues
    disagree - an explicit statement of what will be wrong downstream if it is
    used anyway.

    The confidence is the weighted agreement of the cues that could be
    evaluated, reduced when they point in opposite directions. It is meant for
    `app/confidence_gate`, so that a recording whose head call is uncertain can
    be dropped rather than analysed backwards.
    """
    spines = list(spines)
    if not spines:
        raise HeadTailError("No spines supplied; there is nothing to orient.")

    cues, detail = {}, {}

    if masks is not None:
        per_frame = []
        for s, m in zip(spines, masks):
            if s is None or m is None:
                continue
            try:
                sc, info = taper_cue(width_profile(m, s))
            except HeadTailError:
                continue
            if sc is not None:
                per_frame.append(sc)
                detail.setdefault("taper", info)
        if per_frame:
            # median over frames: a single frame where the tail is occluded or
            # crosses the body reads as blunt, and a mean would carry it
            cues["taper"] = float(np.median(per_frame))
            detail["taper"]["n_frames_scored"] = len(per_frame)
        else:
            detail["taper"] = {"reason": "no frame yielded a usable width profile"}
    else:
        detail["taper"] = {"reason": "no masks supplied, so width was not measured"}

    if images is not None and masks is not None:
        per_frame = []
        for s, m, im in zip(spines, masks, images):
            if s is None or m is None or im is None:
                continue
            try:
                sc, info = pharynx_cue(im, s, m, um_per_px=um_per_px)
            except HeadTailError:
                continue
            if sc is None:
                detail.setdefault("pharynx", info)
                break        # a refusal applies to the whole recording
            per_frame.append(sc)
            detail.setdefault("pharynx", info)
        if per_frame:
            cues["pharynx"] = float(np.median(per_frame))
            detail["pharynx"]["n_frames_scored"] = len(per_frame)
    else:
        detail["pharynx"] = {"reason": ("no transmitted-light frames supplied, "
                                        "so the pharynx was not looked for")}

    m_score, m_info = motion_cue(spines)
    detail["motion"] = m_info
    if m_score is not None:
        cues["motion"] = m_score

    w_score, w_info = wiggle_cue(spines)
    detail["wiggle"] = w_info
    if w_score is not None:
        detail["wiggle"]["score"] = round(w_score, 4)

    if not cues:
        return {
            "head_end": None, "confidence": 0.0, "cues": {}, "detail": detail,
            "refused": True,
            "why": ("None of the taper, pharynx or motion cues could be "
                    "evaluated. Without one of them the end labels are "
                    "arbitrary, and "
                    "using them would reverse every anterior-posterior gradient "
                    "and swap dorsal for ventral while still looking plausible."),
        }

    total_w = sum(WEIGHTS[k] for k in cues)
    combined = sum(WEIGHTS[k] * cues[k] for k in cues) / total_w
    head_end = 0 if combined > 0 else 1

    # Agreement: cues pointing the same way keep the confidence, cues pointing
    # opposite ways cut it. With one cue there is nothing to agree with, so the
    # magnitude alone carries it - and is capped, because a single unopposed
    # cue should never read as certain.
    if len(cues) > 1:
        signs = [np.sign(v) for v in cues.values()]
        agree = float(np.mean([s == np.sign(combined) for s in signs]))
        confidence = float(abs(combined)) * agree
    else:
        confidence = min(float(abs(combined)), 0.7)

    out = {
        "head_end": int(head_end),
        "confidence": round(confidence, 4),
        "cues": {k: round(float(v), 4) for k, v in cues.items()},
        "cues_that_voted": sorted(cues),
        "detail": detail,
        "refused": False,
        "decided_once_per_track": True,
        "note": ("The head is decided once for the whole track. Frame-to-frame "
                 "orientation is already consistent, so a per-frame vote would "
                 "add noise to a decision the geometry has settled, and a call "
                 "that flipped mid-track would leave a discontinuity nothing "
                 "downstream could detect."),
    }
    if confidence < min_confidence:
        out["low_confidence"] = True
        out["why"] = (
            f"Confidence {confidence:.2f} is below {min_confidence}. If this "
            f"call is wrong, segment 0 is the tail, every anterior-posterior "
            f"gradient reverses, a head-to-tail calcium wave is reported as "
            f"travelling tail-to-head, and dorsal and ventral are swapped - "
            f"all without anything looking broken. Gate on this rather than "
            f"reading the result.")
    if len(cues) > 1 and len({np.sign(v) for v in cues.values()}) > 1:
        out["cues_disagree"] = True
    return out


VENTRAL_WEIGHTS = {"excursion": 0.6, "vulva": 0.4}


def signed_curvature(spine):
    """Signed curvature along a HEAD-FIRST spine, positive for one turn sense.

    The sign is what carries dorsal/ventral, and it is defined only once the
    spine is ordered head first: reversing a curve's parameterisation negates
    its signed curvature. That is exactly why a wrong head call inverts dorsal
    and ventral rather than merely mislabelling the ends.
    """
    s = np.asarray(spine, dtype=float)
    if s.ndim != 2 or s.shape[0] < 4:
        raise HeadTailError(
            f"Need at least 4 spine points for signed curvature; got {s.shape}.")
    t = np.diff(s, axis=0)
    n = np.linalg.norm(t, axis=1, keepdims=True)
    n[n == 0] = 1.0
    t = t / n
    # z-component of the cross product of consecutive tangents: the turn sense
    cross = t[:-1, 0] * t[1:, 1] - t[:-1, 1] * t[1:, 0]
    dot = np.clip(np.sum(t[:-1] * t[1:], axis=1), -1.0, 1.0)
    ang = np.arctan2(cross, dot)
    step = np.maximum((n[:-1, 0] + n[1:, 0]) / 2.0, 1e-6)
    k = ang / step
    return np.r_[k[0], k, k[-1]]


def vulva_cue(spines, head_end, window=(0.42, 0.58),
              flanks=((0.24, 0.40), (0.60, 0.76)), min_frames=20):
    """Score in [-1, 1]: positive means the POSITIVE curvature sense is ventral.

    Per Andres: building the vulva required apoptosis of body-wall myocytes, so
    an adult hermaphrodite has a real gap in its ventral musculature at one
    precise point near mid-body - and it bends differently there ventrally than
    dorsally. A structural landmark, not a behavioural tendency.

    This is INDEPENDENT of the excursion-depth asymmetry in `identify_ventral`,
    and deliberately so. Each bending sense is compared against ITS OWN flanking
    regions rather than against the other side, so a global tendency to bend
    deeper one way divides out and what remains is purely local. Two cues that
    would fail for different reasons are worth far more than two that would fail
    together.

    ADULT HERMAPHRODITES ONLY. Larvae have not built a vulva yet and males never
    do, so on either this measures nothing and would return whichever side
    happened to bend less at mid-body. The caller must assert the stage; there
    is no attempt to guess it here.
    """
    curves = []
    for s in spines:
        if s is None:
            continue
        try:
            curves.append(signed_curvature(apply_head_call(s, head_end)))
        except HeadTailError:
            continue
    if len(curves) < min_frames:
        return None, {"reason": (f"only {len(curves)} usable frames; the local "
                                 f"difference is small and needs at least "
                                 f"{min_frames} to rise out of tracing noise")}

    K = np.vstack([c for c in curves if c.size == curves[0].size])
    n = K.shape[1]

    def band(lo, hi):
        return K[:, int(n * lo):max(int(n * hi), int(n * lo) + 1)]

    win = band(*window)
    flank = np.hstack([band(*flanks[0]), band(*flanks[1])])

    def depth(a, sign):
        v = a[np.sign(a) == sign]
        v = np.abs(v[np.isfinite(v)])
        return float(np.percentile(v, 95)) if v.size >= 20 else None

    out = {}
    d = {}
    for region, a in (("vulva", win), ("flanks", flank)):
        for sign, name in ((1, "positive"), (-1, "negative")):
            v = depth(a, sign)
            out[f"{name}_at_{region}"] = None if v is None else round(v, 6)
            if v is None:
                return None, {"reason": (f"the {name} bending sense had too "
                                         f"few samples at the {region} to "
                                         f"compare"), **out}
            d[(region, sign)] = v

    def side_asym(region):
        p, n = d[(region, 1)], d[(region, -1)]
        return (p - n) / (p + n) if (p + n) > 0 else 0.0

    # DIFFERENCE IN DIFFERENCES. Comparing each sense against its own flanks
    # looked like it isolated the local effect, but it does not: curvature
    # magnitude varies ALONG the body simply because of where the travelling
    # wave's peaks happen to fall, and that positional bias survives the
    # comparison. A worm with no vulval gap at all then scores as strongly as
    # one with a gap, in whichever direction the wave happened to favour.
    #
    # So compare the two senses AT THE SAME POSITION, and ask how much that
    # side asymmetry SHRINKS at mid-body relative to the flanks. A positional
    # bias moves both senses together and cancels; only a genuine one-sided
    # local weakness survives.
    a_win, a_flank = side_asym("vulva"), side_asym("flanks")
    score = float(np.clip(a_flank - a_win, -1.0, 1.0))

    out["side_asymmetry_at_vulva"] = round(float(a_win), 4)
    out["side_asymmetry_at_flanks"] = round(float(a_flank), 4)
    out["vulva_effect"] = round(score, 4)
    out["adult_hermaphrodite_only"] = True
    out["measure"] = (
        "difference in differences: the ventral-minus-dorsal bend depth at "
        "mid-body, minus the same quantity in the flanking regions. A "
        "positional bias in curvature affects both senses equally and cancels; "
        "a one-sided local weakness does not.")
    return score, out


# Both dorsoventral cues are read off MOVEMENT, and per Andres both are clearest
# in swimming - in crawling or burrowing they are expected to be too subtle. So
# outside swimming the prior that the asymmetry is simply invisible is stronger,
# and the evidence required to overturn it goes up. This scales the confidence
# threshold rather than refusing outright: a crawling animal that shows the
# asymmetry unmistakably is still allowed to say so.
GAIT_STRINGENCY = {"swimming": 1.0, "crawling": 2.0, "burrowing": 2.0,
                   None: 1.5, "unknown": 1.5}


def identify_ventral(spines, head_end, head_confidence=None,
                     body_range=(0.25, 0.85), min_frames=20,
                     min_confidence=0.30, adult_hermaphrodite=False,
                     gait=None):
    """Which bending sense is VENTRAL, from the depth asymmetry of the bends.

    Per Andres: there is a dorsoventral asymmetry during movement, clearest in
    swimming - VENTRAL excursions are deeper along the length of the body than
    dorsal ones. So once the head is known, the sign of curvature is defined,
    and the side that reaches deeper is the ventral side. No stain, no marker,
    no user click.

    Depth is compared as the 95th percentile of bending magnitude on each side
    rather than the mean, because the asymmetry Andres describes is in how far
    the deep bends GO. Means are dominated by the many shallow bends the two
    sides share and would wash the difference out.

    Only the middle of the body is used. The head sweeps on its own during
    foraging and the tail is thin and noisy to trace, and neither contributes
    to the locomotor asymmetry this reads.

    THE HEAD CALL PROPAGATES. Reversing the spine negates signed curvature, so
    if the head is wrong then ventral and dorsal are exactly swapped - not
    degraded, INVERTED. The returned confidence is therefore multiplied by the
    head confidence: a dorsoventral call can never be more trustworthy than the
    head call it rests on.
    """
    if head_end is None:
        raise HeadTailError(
            "Dorsal and ventral cannot be assigned without a head call. The "
            "sign of curvature is defined only for a head-first spine, so "
            "assigning sides now would produce a labelling that is either "
            "right or exactly inverted, with nothing to say which.")

    curves = []
    for s in spines:
        if s is None:
            continue
        try:
            k = signed_curvature(apply_head_call(s, head_end))
        except HeadTailError:
            continue
        n = k.size
        lo, hi = int(n * body_range[0]), int(n * body_range[1])
        if hi - lo >= 3:
            curves.append(k[lo:hi])
    if len(curves) < min_frames:
        return {
            "ventral_sign": None, "confidence": 0.0, "refused": True,
            "why": (f"Only {len(curves)} usable frames. The dorsoventral "
                    f"asymmetry is a property of sustained movement, and over "
                    f"a handful of frames the deepest bend on each side is "
                    f"whichever way the animal happened to be bending. At "
                    f"least {min_frames} frames are needed."),
        }

    allk = np.concatenate(curves)
    allk = allk[np.isfinite(allk)]
    pos, neg = allk[allk > 0], -allk[allk < 0]
    if pos.size < 20 or neg.size < 20:
        return {
            "ventral_sign": None, "confidence": 0.0, "refused": True,
            "why": ("The animal bent essentially one way only "
                    f"({pos.size} positive and {neg.size} negative samples), "
                    "so there is no asymmetry to compare. A coiled or paralysed "
                    "animal looks like this, and so does a tracking failure."),
        }

    dp = float(np.percentile(pos, 95))
    dn = float(np.percentile(neg, 95))
    denom = dp + dn
    asym = (dp - dn) / denom if denom > 0 else 0.0

    vcues, vdetail = {"excursion": float(asym)}, {}
    if adult_hermaphrodite:
        vs, vinfo = vulva_cue(spines, head_end)
        vdetail["vulva"] = vinfo
        if vs is not None:
            vcues["vulva"] = float(vs)
    else:
        vdetail["vulva"] = {"reason": ("not asserted to be an adult "
                                       "hermaphrodite, so the vulval gap was "
                                       "not looked for")}

    tw = sum(VENTRAL_WEIGHTS[k] for k in vcues)
    combined = sum(VENTRAL_WEIGHTS[k] * vcues[k] for k in vcues) / tw
    ventral_sign = 1 if combined > 0 else -1

    # COMBINE AS INDEPENDENT EVIDENCE, NOT AS AN AVERAGE. The excursion cue and
    # the vulva cue answer the same binary question by different routes - the
    # difference-in-differences removes the global asymmetry the first one
    # measures - so two agreeing cues should be MORE convincing than either
    # alone. Averaging their magnitudes does the opposite: a strong cue paired
    # with a weaker one that agrees comes out lower than the strong cue by
    # itself, which is the wrong direction for corroborating evidence.
    #
    # Noisy-OR gives the right behaviour, and it is only licensed because the
    # two cues are independent by construction. The head cues are NOT combined
    # this way: taper and pharynx both read the anatomy of the same end, so a
    # badly segmented head degrades both together and treating them as
    # independent would inflate the result.
    _, raw = _combine_independent(vcues)
    hc = 1.0 if head_confidence is None else float(head_confidence)
    confidence = raw * hc

    out = {
        "ventral_sign": int(ventral_sign),
        "confidence": round(confidence, 4),
        "asymmetry": round(float(asym), 4),
        "cues": {k: round(v, 4) for k, v in vcues.items()},
        "cue_detail": vdetail,
        "raw_confidence_before_head": round(raw, 4),
        "head_confidence_applied": None if head_confidence is None else round(hc, 4),
        "deep_bend_positive": round(dp, 6),
        "deep_bend_negative": round(dn, 6),
        "n_frames": len(curves),
        "refused": False,
        "convention": ("ventral_sign is the sign of signed_curvature() on a "
                       "head-first spine for which the bend is VENTRAL. The "
                       "hemisegment on that side of the midline is ventral; "
                       "the other is dorsal."),
        "depends_on_head_call": ("Reversing the spine negates signed curvature, "
                                 "so an incorrect head call does not degrade "
                                 "this result - it inverts it. The confidence "
                                 "is multiplied by the head confidence for "
                                 "exactly that reason."),
        "clearest_in_swimming": ("The asymmetry Andres describes is most "
                                 "evident in swimming; on a crawling animal "
                                 "expect a smaller separation and a lower "
                                 "confidence here."),
    }
    stringency = GAIT_STRINGENCY.get(gait, 1.5)
    effective_min = min_confidence * stringency
    out["gait"] = gait
    out["confidence_threshold_used"] = round(float(effective_min), 4)
    if stringency > 1.0:
        out["gait_note"] = (
            f"Both dorsoventral cues are read off movement and are clearest in "
            f"SWIMMING. For gait '{gait}' the asymmetry is expected to be too "
            f"subtle to resolve, so the threshold was raised from "
            f"{min_confidence} to {effective_min:.2f} rather than the result "
            f"being taken at face value. An animal that shows it unmistakably "
            f"anyway still passes.")

    if confidence < effective_min:
        out["low_confidence"] = True
        out["why"] = (
            f"Confidence {confidence:.2f} is below {effective_min:.2f}. Read this "
            f"as THE ASYMMETRY WAS NOT VISIBLE, not as a shallow one: a "
            f"recording too coarse or too brief to resolve the difference is "
            f"far more likely than an animal whose dorsoventral asymmetry is "
            f"genuinely absent. Using it anyway would put dorsal and ventral "
            f"hemisegments the wrong way round, which does not look like an "
            f"error - it looks like a result with the sides swapped.")
    return out


def reconcile_ventral(calls, min_confidence=0.30):
    """Cross-check dorsoventral calls across animals; disagreement means error.

    The asymmetry is a fact of the animal's anatomy and gait, not a phenotype
    that varies between individuals. Andres's judgement, and it sets the right
    prior: a movie too coarse or too brief to RESOLVE the asymmetry is entirely
    expected, while a mutant that REVERSES it would be extraordinary.

    That makes disagreement diagnostic rather than interesting. A wrong head
    call inverts the dorsoventral sign exactly - see `identify_ventral` - so an
    animal whose sign opposes its cohort is far more likely to have had its head
    misidentified than to be biologically reversed.

    FLAGS, DOES NOT CORRECT. Silently flipping the minority would make this
    machinery incapable of ever showing a real reversal, which is precisely the
    finding that would matter most if it were ever true. The minority is
    reported with what to check.
    """
    usable = [c for c in calls
              if c and not c.get("refused") and c.get("ventral_sign") is not None
              and c.get("confidence", 0.0) >= min_confidence]
    if len(usable) < 3:
        return {"n_usable": len(usable), "n_given": len(calls),
                "majority_sign": None, "minority": [], "checked": False,
                "why": (f"Only {len(usable)} animals had a usable dorsoventral "
                        f"call, which is too few for a disagreement to mean "
                        f"anything. At least 3 are needed.")}

    signs = np.array([c["ventral_sign"] for c in usable])
    majority = int(np.sign(signs.sum())) or 1
    minority = [i for i, c in enumerate(usable) if c["ventral_sign"] != majority]
    return {
        "n_usable": len(usable), "n_given": len(calls),
        "majority_sign": majority,
        "fraction_agreeing": round(float(np.mean(signs == majority)), 4),
        "minority": minority,
        "checked": True,
        "corrected": False,
        "interpretation": (
            f"{len(minority)} of {len(usable)} animals disagree with the "
            f"cohort. Because a wrong head call inverts the dorsoventral sign "
            f"exactly, check the HEAD call on those animals first - a "
            f"misidentified head is far more likely than a reversed animal."
            if minority else
            "All usable animals agree, which is what a correct head call and a "
            "resolvable asymmetry should produce."),
        "not_corrected_on_purpose": (
            "The minority is flagged, never flipped. Silently correcting to the "
            "majority would make a genuine reversal permanently invisible, and "
            "that is the one result here that would be worth reporting."),
    }


def apply_head_call(spine, head_end):
    """Return the spine ordered head-first, given the track's head call."""
    s = np.asarray(spine, dtype=float)
    if head_end is None:
        raise HeadTailError(
            "The head end was not determined, so the spine cannot be ordered "
            "head-first. Ordering it arbitrarily would produce anterior-"
            "posterior results that are reversed but look normal.")
    return s if int(head_end) == 0 else s[::-1]
