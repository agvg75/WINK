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


def taper_cue(widths, end_fraction=0.2):
    """Score in [-1, 1]: positive means END 0 is the head (end 1 is thinner).

    Terminal widths are normalised by the midbody width so the score means the
    same thing on a large adult and a small larva, and so it cannot be moved by
    the magnification.
    """
    v = np.asarray(widths, dtype=float)
    n = v.size
    k = max(int(round(n * end_fraction)), 2)
    mid = np.nanmedian(v[n // 3: 2 * n // 3])
    if not np.isfinite(mid) or mid <= 0:
        return None, {"reason": "midbody width could not be measured"}
    a = np.nanmedian(v[:k]) / mid
    b = np.nanmedian(v[-k:]) / mid
    if not (np.isfinite(a) and np.isfinite(b)):
        return None, {"reason": "a terminal width could not be measured "
                                "(the animal may touch the frame edge)"}
    denom = a + b
    score = float((a - b) / denom) if denom > 0 else 0.0
    return score, {"end0_rel_width": round(float(a), 4),
                   "end1_rel_width": round(float(b), 4),
                   "midbody_width_px": round(float(mid), 3)}


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


WEIGHTS = {"taper": 0.65, "motion": 0.35}


def identify_head(spines, masks=None, min_confidence=0.35):
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
            "why": ("Neither the taper nor the motion cue could be evaluated. "
                    "Without one of them the end labels are arbitrary, and "
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


def apply_head_call(spine, head_end):
    """Return the spine ordered head-first, given the track's head call."""
    s = np.asarray(spine, dtype=float)
    if head_end is None:
        raise HeadTailError(
            "The head end was not determined, so the spine cannot be ordered "
            "head-first. Ordering it arbitrarily would produce anterior-"
            "posterior results that are reversed but look normal.")
    return s if int(head_end) == 0 else s[::-1]
