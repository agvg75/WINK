"""Head/tail and dorsal/ventral identification on synthetic worms we designed.

THE CHECK THAT MATTERS is symmetry. A sign error is self-consistent - it
answers "end 0" every time and every internal comparison agrees - so a fixture
with the head at end 0 cannot catch it. The same worm is therefore run again
reversed, and the answer must follow. Same class of bug as the animal_frame
rotation sign, which a round trip could not catch either.

The worm's shape follows Andres's anatomy: BOTH ends taper, but the tail taper
is long, shallow and comes to a point while the head taper is short, steep and
round. A fixture with a simply-thinner tail would let a cruder cue pass.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import head_tail as ht   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("head/tail and dorsal/ventral - regression\n")

H, W, N = 170, 380, 25
# Head: tip 3.5 px, full width by index 3 - SHORT, STEEP, ROUND.
# Tail: declines from index 13 all the way to 0.8 px - LONG, SHALLOW, POINTED.
RADII = np.interp(np.arange(N), [0, 1, 3, 13, 24], [3.5, 5.5, 7.0, 7.0, 0.8])


def _disc(mask, x, y, r):
    y0, y1 = max(int(y - r - 1), 0), min(int(y + r + 2), mask.shape[0])
    x0, x1 = max(int(x - r - 1), 0), min(int(x + r + 2), mask.shape[1])
    if y1 <= y0 or x1 <= x0:
        return
    sy, sx = np.ogrid[y0:y1, x0:x1]
    mask[y0:y1, x0:x1] |= (sx - x) ** 2 + (sy - y) ** 2 <= r * r


def make_worm(shift=0.0, phase=0.0, wavelength=120.0, amp=18.0, skew=1.0,
              vulva=0.0, deep_side=-1):
    """Spine ordered HEAD FIRST (index 0 = head) plus its filled mask.

    `skew` deepens excursions to the `deep_side` - the global dorsoventral
    asymmetry. `vulva` shallows that SAME side, but only near mid-body, standing
    in for the gap left in the ventral musculature by the apoptosis that built
    the vulva. Both act on the same side, as they do in the animal.

    NOTE: shifting the phase does NOT swap which side is deep - the skew follows
    the sign of the wave, not its position. Flipping the asymmetry needs
    `deep_side`, which is why the earlier version of this fixture could not test
    what it claimed to.
    """
    x = np.linspace(60, 260, N) + shift
    wave = np.sin(2 * np.pi * x / wavelength + phase)
    on_deep = (wave < 0) if deep_side < 0 else (wave > 0)
    wave = np.where(on_deep, wave * skew, wave)
    if vulva:
        g = np.exp(-0.5 * ((np.arange(N) - 12.0) / 2.0) ** 2)
        wave = np.where(on_deep, wave * (1.0 - vulva * g), wave)
    spine = np.column_stack([x, 85 + amp * wave])
    mask = np.zeros((H, W), bool)
    t, td = np.linspace(0, 1, N), np.linspace(0, 1, 400)
    for xi, yi, ri in zip(np.interp(td, t, spine[:, 0]),
                          np.interp(td, t, spine[:, 1]),
                          np.interp(td, t, RADII)):
        _disc(mask, xi, yi, ri)
    return spine, mask


def dic_image(mask, spine, textured_end=0):
    """A transmitted-light frame with a pharynx at one end.

    The pharynx does two things, per Andres: it gives the head internal
    STRUCTURE, and it makes the head read LIGHTER than the body behind it. The
    tail matches the rest of the body. Both are planted here, and the pharynx
    stops after a pharynx length rather than fading down the body - that step
    is what the confinement measure looks for.
    """
    rng = np.random.default_rng(0)
    img = 0.55 + 0.02 * rng.standard_normal((H, W))
    img[mask] = 0.44
    k = max(int(round(N * 0.2)), 2)
    pts = spine[:k] if textured_end == 0 else spine[-k:]
    for j, (px, py) in enumerate(pts):
        _band = np.zeros((H, W), bool)
        _disc(_band, px, py, 6.0)
        img[_band & mask] = 0.80 if j % 2 == 0 else 0.50   # lighter, and striped
    return img


# The worm travels HEAD FIRST. Index 0 sits at low x, so head-first means
# translating toward NEGATIVE x.
frames = [make_worm(shift=-1.5 * k, phase=0.25 * k) for k in range(20)]
spines = [s for s, _ in frames]
masks = [m for _, m in frames]

# --- taper: the shape of the profile, not the terminal width --------------
wp = ht.width_profile(masks[0], spines[0])
check("a width profile is measured along the whole spine",
      np.isfinite(wp).all(), f"{np.nanmin(wp):.1f}-{np.nanmax(wp):.1f} px")

t_score, t_info = ht.taper_cue(wp)
check("the taper cue identifies the head", t_score > 0.2, f"score {t_score:.3f}")
check("...because the tail taper is much longer",
      t_info["end1_taper_length_frac"] > 2 * t_info["end0_taper_length_frac"],
      f"head {t_info['end0_taper_length_frac']:.2f} vs "
      f"tail {t_info['end1_taper_length_frac']:.2f} of the half")
check("...and the head tip is blunter while the tail comes to a point",
      t_info["end0_tip_rel_width"] > 3 * t_info["end1_tip_rel_width"],
      f"{t_info['end0_tip_rel_width']:.2f} vs {t_info['end1_tip_rel_width']:.2f}")
check("...with the head taper steeper", t_info["end0_slope"] > t_info["end1_slope"],
      f"{t_info['end0_slope']:.2f} vs {t_info['end1_slope']:.2f}")
check("...and slope reported but not voting, since it is derived",
      t_info["slope_reported_not_weighted"] is True)
# both terms must independently point the same way, or the fixture is doing
# the work that the cue is supposed to do
check("both voting terms agree on their own",
      t_info["length_term"] > 0 and t_info["tip_term"] > 0,
      f"length {t_info['length_term']:.2f}, tip {t_info['tip_term']:.2f}")

# --- the pharynx ----------------------------------------------------------
dic = dic_image(masks[0], spines[0], textured_end=0)
p_score, p_info = ht.pharynx_cue(dic, spines[0], masks[0])
check("the pharynx cue finds the textured end", p_score > 0.2,
      f"score {p_score:.3f}")
check("...and inverts when the texture is at the other end",
      ht.pharynx_cue(dic_image(masks[0], spines[0], textured_end=1),
                     spines[0], masks[0])[0] < -0.2)

# With a scale, the cue tests for a PHARYNX rather than for texture: the
# feature must be CONFINED to about a pharynx length and then stop.
UM = 3.0        # ~600 um body, and the planted pharynx spans ~100 um
ps, pinfo = ht.pharynx_cue(dic, spines[0], masks[0], um_per_px=UM)
check("with a scale the cue measures confinement, not texture",
      pinfo["used_scale"] is True and ps > 0.2, f"score {ps:.3f}")
check("...from structure AND intensity, which are different physics",
      pinfo["texture_score"] > 0 and pinfo["brightness_score"] > 0,
      f"texture {pinfo['texture_score']:.3f}, "
      f"brightness {pinfo['brightness_score']:.3f}")
check("...the head reading lighter than the body just behind it",
      pinfo["end0_brightness_confinement"] > pinfo["end1_brightness_confinement"],
      f"{pinfo['end0_brightness_confinement']:.3f} vs "
      f"{pinfo['end1_brightness_confinement']:.3f}")
# Symmetry: the SAME physical worm indexed backwards must invert the score.
# (Planting a pharynx in the tapered tail instead would test an animal that
# cannot exist, and the geometry rather than the cue would carry the answer.)
check("...and inverts when the same worm is indexed from the other end",
      ht.pharynx_cue(dic, spines[0][::-1], masks[0], um_per_px=UM)[0] < -0.2)

# SPECIFICITY: debris smeared along the whole body is textured and light, but
# it is not confined to one end, so it must not read as a pharynx.
dirty = 0.55 + 0.02 * np.random.default_rng(1).standard_normal((H, W))
dirty[masks[0]] = 0.44
for j, (px, py) in enumerate(spines[0]):
    _b = np.zeros((H, W), bool)
    _disc(_b, px, py, 6.0)
    dirty[_b & masks[0]] = 0.80 if j % 2 == 0 else 0.50
d_score, _ = ht.pharynx_cue(dirty, spines[0], masks[0], um_per_px=UM)
check("texture smeared along the whole body does not read as a pharynx",
      abs(d_score) < abs(ps) / 2.0, f"{d_score:.3f} smeared vs {ps:.3f} confined")

check("without a scale the cue says it is only measuring texture",
      "test for a pharynx rather than for texture" in p_info["caveat"])

fluor = np.zeros((H, W))
fluor[masks[0]] = 0.8
f_score, f_info = ht.pharynx_cue(fluor, spines[0], masks[0])
check("the pharynx cue refuses on fluorescence", f_score is None)
check("...saying it would only score the brighter end",
      "whichever end was brighter" in f_info["reason"],
      f"dark fraction {f_info['dark_fraction']}")

# --- motion ---------------------------------------------------------------
m_score, m_info = ht.motion_cue(spines)
check("the motion cue points at the leading end", m_score > 0.5,
      f"score {m_score:.3f} over {m_info['n_moving_frames']} moving frames")

w_score, w_info = ht.wiggle_cue(spines)
check("the wiggle cue is reported but marked as not weighted",
      w_info["weighted"] is False and "swimming" in w_info["why_not_weighted"])

# --- the decision ---------------------------------------------------------
images = [dic_image(m, s, 0) for s, m in frames]
call = ht.identify_head(spines, masks, images, um_per_px=UM)
check("the head is identified", call["head_end"] == 0,
      f"head_end={call['head_end']}, confidence {call['confidence']}")
check("...from all three weighted cues",
      call["cues_that_voted"] == ["motion", "pharynx", "taper"])
check("...with usable confidence", call["confidence"] > 0.35,
      f"{call['confidence']}")
check("...and the wiggle cue did not vote", "wiggle" not in call["cues"])

# --- THE SYMMETRY CHECK ---------------------------------------------------
rev = ht.identify_head([s[::-1] for s in spines], masks,
                       [dic_image(m, s, 0) for s, m in frames], um_per_px=UM)
check("reversing the spine reverses the answer", rev["head_end"] == 1,
      f"head_end={rev['head_end']}")
check("...with the same confidence, since it is the same worm",
      abs(rev["confidence"] - call["confidence"]) < 0.05,
      f"{rev['confidence']} vs {call['confidence']}")

# --- an animal undulating WITHOUT translating -----------------------------
still = [make_worm(shift=0.0, phase=1.0 * k, wavelength=380.0, amp=26.0)
         for k in range(20)]
s_still = [s for s, _ in still]
ms, mi = ht.motion_cue(s_still)
check("an animal undulating in place gives no motion cue", ms is None,
      f"straightness {mi.get('straightness')}")
check("...saying it went nowhere rather than returning a number",
      "did not go anywhere" in mi["reason"])
check("...and the centroid did move, so a speed test alone would have passed",
      mi["path_length_px"] > 10.0,
      f"{mi['path_length_px']} px of path, {mi['net_displacement_px']} px net")

nothing = ht.identify_head(s_still, masks=None)
check("with no masks, no images and no travel the call is refused",
      nothing["refused"] is True and nothing["head_end"] is None)
check("...naming what would silently invert",
      "swap dorsal for ventral" in nothing["why"])

# --- DORSAL / VENTRAL -----------------------------------------------------
# Ventral excursions are DEEPER. skew > 1 deepens the negative-y side.
swim = [make_worm(shift=-0.4 * k, phase=0.55 * k, amp=17.0, skew=1.7)
        for k in range(30)]
sw_spines = [s for s, _ in swim]
v = ht.identify_ventral(sw_spines, head_end=0, head_confidence=call["confidence"])
check("a dorsoventral call is made from the bend asymmetry",
      v["refused"] is False and v["ventral_sign"] in (1, -1),
      f"sign {v['ventral_sign']}, confidence {v['confidence']}")
check("...and the deeper side is the one that was made deeper",
      abs(v["asymmetry"]) > 0.1, f"asymmetry {v['asymmetry']}")

# deepen the OTHER side: the call must follow the asymmetry, not the fixture
other = [make_worm(shift=-0.4 * k, phase=0.55 * k, amp=17.0, skew=1.7,
                   deep_side=+1) for k in range(30)]
v_other = ht.identify_ventral([s for s, _ in other], head_end=0,
                              head_confidence=call["confidence"])
check("deepening the other side flips the dorsoventral call",
      v_other["ventral_sign"] == -v["ventral_sign"],
      f"{v['ventral_sign']} -> {v_other['ventral_sign']}")

v_rev = ht.identify_ventral(sw_spines, head_end=1,
                            head_confidence=call["confidence"])
check("a wrong head call INVERTS dorsal and ventral, not degrades them",
      v_rev["ventral_sign"] == -v["ventral_sign"],
      f"{v['ventral_sign']} -> {v_rev['ventral_sign']}")
check("...which is why the head confidence multiplies in",
      v["confidence"] < v["raw_confidence_before_head"],
      f"{v['raw_confidence_before_head']} -> {v['confidence']}")

sym = [make_worm(shift=-0.4 * k, phase=0.55 * k, amp=17.0, skew=1.0)
       for k in range(30)]
v_sym = ht.identify_ventral([s for s, _ in sym], head_end=0,
                            head_confidence=call["confidence"])
check("a symmetric swimmer yields a low-confidence call",
      v_sym.get("low_confidence") is True or v_sym["refused"] is True,
      f"confidence {v_sym['confidence']}")
check("...read as the asymmetry being invisible, not absent",
      "not visible" in v_sym.get("why", "").lower()
      or "was not visible" in v_sym.get("why", ""))

try:
    ht.identify_ventral(sw_spines, head_end=None)
    check("dorsal/ventral without a head call is refused", False)
except ht.HeadTailError as exc:
    check("dorsal/ventral without a head call is refused", True)
    check("...naming that it would be right or exactly inverted",
          "exactly inverted" in str(exc))

short = ht.identify_ventral(sw_spines[:5], head_end=0)
check("too few frames for a dorsoventral call is refused",
      short["refused"] is True and "sustained movement" in short["why"])

# --- the vulva: a local landmark, not a global tendency -------------------
# Ventral bending is deeper overall (skew) but locally impaired at mid-body
# where the myocytes were lost (vulva). Both mark the SAME side.
adult = [make_worm(shift=-0.4 * k, phase=0.55 * k, amp=17.0, skew=1.7,
                   vulva=0.55) for k in range(30)]
a_spines = [s for s, _ in adult]
vc, vinfo = ht.vulva_cue(a_spines, head_end=0)
check("the vulva cue finds a local deficit on one side", vc is not None
      and abs(vc) > 0.1, f"score {vc:.3f}" if vc is not None else "None")
check("...and it is the ventral side, agreeing with the excursion cue",
      np.sign(vc) == v["ventral_sign"],
      f"vulva {np.sign(vc):+.0f} vs excursion {v['ventral_sign']:+d}")
check("...localised: the side asymmetry SHRINKS at mid-body",
      abs(vinfo["side_asymmetry_at_vulva"]) < abs(vinfo["side_asymmetry_at_flanks"]),
      f"{vinfo['side_asymmetry_at_flanks']:.3f} in the flanks -> "
      f"{vinfo['side_asymmetry_at_vulva']:.3f} at the vulva")
check("...and it is stated to be adult hermaphrodites only",
      vinfo["adult_hermaphrodite_only"] is True)

# A worm with the global asymmetry but NO vulval notch must not produce one.
no_vulva = [make_worm(shift=-0.4 * k, phase=0.55 * k, amp=17.0, skew=1.7)
            for k in range(30)]
nv, _ = ht.vulva_cue([s for s, _ in no_vulva], head_end=0)
check("a worm with no vulval notch shows a much weaker local deficit",
      nv is not None and abs(nv) < abs(vc) / 2.0,
      f"{nv:.3f} without vs {vc:.3f} with")

va = ht.identify_ventral(a_spines, head_end=0, head_confidence=call["confidence"],
                         adult_hermaphrodite=True)
check("both dorsoventral cues vote when the stage is asserted",
      sorted(va["cues"]) == ["excursion", "vulva"])
check("...agreeing, so confidence exceeds the excursion cue alone",
      va["confidence"] > ht.identify_ventral(
          a_spines, head_end=0, head_confidence=call["confidence"])["confidence"],
      f"{va['confidence']} with vulva")
check("the vulva cue is not used unless the stage is asserted",
      "not asserted to be an adult" in
      ht.identify_ventral(a_spines, head_end=0)["cue_detail"]["vulva"]["reason"])

# --- gait: these cues are a swimming measurement --------------------------
swum = ht.identify_ventral(a_spines, head_end=0, head_confidence=call["confidence"],
                           adult_hermaphrodite=True, gait="swimming")
crawled = ht.identify_ventral(a_spines, head_end=0, head_confidence=call["confidence"],
                              adult_hermaphrodite=True, gait="crawling")
check("crawling demands more evidence than swimming for the same data",
      crawled["confidence_threshold_used"] > swum["confidence_threshold_used"],
      f"{swum['confidence_threshold_used']} -> "
      f"{crawled['confidence_threshold_used']}")
check("...saying the asymmetry is expected to be too subtle there",
      "too subtle to resolve" in crawled["gait_note"])
check("...and the measured value itself is unchanged, only the bar moved",
      crawled["confidence"] == swum["confidence"])
check("an unstated gait sits between the two",
      ht.identify_ventral(a_spines, head_end=0, adult_hermaphrodite=True
                          )["confidence_threshold_used"] > 0.3)

# --- cohort reconciliation ------------------------------------------------
good = dict(ventral_sign=1, confidence=0.6, refused=False)
bad = dict(ventral_sign=-1, confidence=0.6, refused=False)
rec = ht.reconcile_ventral([good, good, good, bad, good])
check("a cohort agrees on a majority sign", rec["majority_sign"] == 1,
      f"{rec['fraction_agreeing']:.0%} agree")
check("...and the odd animal out is flagged", rec["minority"] == [3])
check("...pointing at the head call as the likely cause",
      "check the HEAD call" in rec["interpretation"])
check("...without silently correcting it", rec["corrected"] is False
      and "permanently invisible" in rec["not_corrected_on_purpose"])
check("a cohort too small to disagree meaningfully is not checked",
      ht.reconcile_ventral([good, bad])["checked"] is False)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("HEAD_TAIL_PASS")
