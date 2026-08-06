"""Can this recording give spines, or only centroids?

Andres's workflow: scroll to a frame where the worms are no longer piled up,
trace one or more midlines by hand, and let the program decide what is
recoverable. Centroids always are and give a first pass; spines are opt-in and
are what allow turning strategy and body orientation relative to the field.

The property under test is that the verdict always arrives with its reasons,
because the reasons are what let someone change the acquisition. A bare
"centroids only" tells a student nothing they can act on.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import numpy as np          # noqa: E402
import tractability as tr   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("tractability - regression\n")


def synth(width_px=8, length_px=200, contrast=120, y=100, x0=20,
          shape=(240, 400), noise=2.0, seed=0):
    """A dark worm on a bright field, drawn as a horizontal bar.

    WITH NOISE, deliberately. A noiseless background makes contrast-to-noise
    undefined, and a synthetic image that cannot fail the contrast check is
    not testing it.
    """
    rng = np.random.default_rng(seed)
    img = np.full(shape, 200.0) + rng.normal(0, noise, shape)
    half = width_px / 2.0
    img[int(y - half):int(y + half) + 1, x0:x0 + length_px] -= contrast
    trace = [[x, y] for x in range(x0 + 2, x0 + length_px - 2, 10)]
    return img, trace


# --- a good recording -------------------------------------------------------
img, trace = synth()
stats = tr.trace_stats([trace], frame=img, um_per_px=10.0)
check("the traced length is measured in pixels",
      abs(stats["length_px"]["median"] - 190) < 2,
      f"{stats['length_px']['median']:.0f} px")
check("...and converted to microns when a scale is given",
      "length_um" in stats)
check("body width is measured from profiles across the trace",
      abs(stats["width_px"]["median"] - 9) <= 2,
      f"{stats['width_px']['median']:.1f} px for an 8 px bar")

good = tr.assess(stats, n_seg=24)
check("a well resolved worm supports spines", good["spine_recoverable"] is True)
check("...and says what that enables",
      any("orientation relative to the field" in e for e in good["enables"]))
check("...with the reasons, not just a verdict", len(good["reasons"]) >= 2)
check("centroids are recoverable either way",
      good["centroid_recoverable"] is True)

# --- too thin to have a centre ----------------------------------------------
thin_img, thin_trace = synth(width_px=2)
thin = tr.assess(tr.trace_stats([thin_trace], frame=thin_img))
check("a two-pixel worm cannot yield a midline",
      thin["spine_recoverable"] is False)
check("...naming that there is no interior to find the centre of",
      any("no interior" in b for b in thin["blockers"]))
check("...and suggesting what to change",
      any("higher magnification" in b for b in thin["blockers"]),
      "a bare refusal tells a student nothing they can act on")
check("...while still allowing the centroid first pass",
      thin["centroid_recoverable"] is True and
      "speed" in " ".join(thin["enables"]))

# --- too short for the segments asked for -----------------------------------
short_img, short_trace = synth(length_px=60)
short = tr.assess(tr.trace_stats([short_trace], frame=short_img), n_seg=24)
check("a short worm cannot carry 24 segments",
      short["spine_recoverable"] is False)
check("...naming the speckle panel this project already shipped",
      any("speckle" in b for b in short["blockers"]),
      "the failure this module exists to predict rather than discover")
check("...and saying how many segments WOULD fit",
      short["max_supported_n_seg"] is not None and
      any(str(short["max_supported_n_seg"]) in b for b in short["blockers"]))
check("the same worm supports spines at fewer segments",
      tr.assess(tr.trace_stats([short_trace], frame=short_img),
                n_seg=6)["spine_recoverable"] is True,
      "the limit is per-segment resolution, not length alone")

# --- worms still in a pile ---------------------------------------------------
img2 = np.full((240, 400), 200.0) + np.random.default_rng(1).normal(
    0, 2.0, (240, 400))
img2[98:107, 20:220] -= 120
img2[105:114, 20:220] -= 120
a = [[x, 102] for x in range(25, 215, 10)]
b = [[x, 109] for x in range(25, 215, 10)]
pile = tr.assess(tr.trace_stats([a, b], frame=img2))
check("two animals closer than a body width block spines",
      pile["spine_recoverable"] is False)
check("...naming that the midline runs from one worm into the other",
      any("into the other" in x for x in pile["blockers"]))
check("...and pointing at the scrubber, which is the fix",
      any("what the scrubber is for" in x for x in pile["blockers"]),
      "scroll to a frame where they have separated")

# --- low contrast ------------------------------------------------------------
faint_img, faint_trace = synth(contrast=3)
faint = tr.assess(tr.trace_stats([faint_trace], frame=faint_img))
check("a barely visible worm blocks spines",
      faint["spine_recoverable"] is False)
check("...naming that an unreliable boundary cannot be thinned",
      any("cannot be thinned" in x for x in faint["blockers"]))

# --- the distinction that is easy to lose ------------------------------------
check("the centroid tier says heading is not orientation",
      "substitutes heading for orientation" in
      thin["the_distinction_that_matters"])
check("...and that reversals come out backwards",
      "reversals backwards" in thin["the_distinction_that_matters"],
      "the body points one way while the track goes the other")
check("the spine tier says orientation survives reversals",
      "through" in good["the_distinction_that_matters"] and
      "reversals" in good["the_distinction_that_matters"])
check("the centroid tier lists what it PREVENTS, not only what it allows",
      any("omega" in p for p in thin["prevents"]))

# --- planning ---------------------------------------------------------------
p1 = tr.plan(thin, wants_orientation=True)
check("centroids run regardless", p1["run_centroids"] is True)
check("...and spines are not offered when unrecoverable",
      p1["offer_spines"] is False)
check("a goal that needs spines is refused with the reason attached",
      "does not support them" in p1["warnings"][0] and
      "no interior" in p1["warnings"][0])
check("...while saying the first pass is still valid for what it covers",
      "still valid for" in p1["warnings"][0])

p2 = tr.plan(good, wants_turning=True)
check("spines are offered but not assumed when recoverable",
      p2["offer_spines"] is True and "opt-in" in p2["warnings"][0],
      "per Andres, the user clicks to have them computed")
check("no warning at all when nothing extra was asked for",
      tr.plan(good)["warnings"] == [])

# --- refusals ---------------------------------------------------------------
try:
    tr.trace_stats([])
    check("assessing with no traces is refused", False)
except tr.TractabilityError as exc:
    check("assessing with no traces is refused", True)
    check("...naming that the point is to measure THIS recording",
          "rather than assume a typical one" in str(exc))
try:
    tr.trace_stats([[[5, 5]]], frame=img)
    check("a single-point trace is refused", False)
except tr.TractabilityError as exc:
    check("a single-point trace is refused", True)
    check("...naming that length decides the segment question",
          "carry the requested segments" in str(exc) or "length" in str(exc))
try:
    tr.trace_stats([[[5, 5], [9, 5]]], frame=np.full((240, 400), 200.0))
    check("a trace on empty background is refused", False)
except tr.TractabilityError as exc:
    check("a trace on empty background is refused", True)
    check("...naming that width decides whether a midline can be fitted",
          "width is what decides" in str(exc))

bright_img, bright_trace = synth(contrast=-120)
check("a worm bright on dark is measured too, not scored zero",
      abs(tr.trace_stats([bright_trace],
                         frame=bright_img)["width_px"]["median"] - 9) <= 2,
      "dark-on-bright and bright-on-dark are both common here")

# --- the contrast estimator must not be circular ----------------------------
# Whole-image standard deviation includes the worm, so a faint animal on a
# clean field lowers the denominator as fast as the numerator and scores as
# HIGH contrast. A 3-count worm measured 7.4 sd that way before MAD.
faint_stats = tr.trace_stats([faint_trace], frame=faint_img)
check("a faint worm scores LOW contrast, not high",
      faint_stats["contrast_sd"] < tr.MIN_CONTRAST,
      f"{faint_stats['contrast_sd']:.1f} sd")
check("a clear worm scores high contrast",
      stats["contrast_sd"] > 20, f"{stats['contrast_sd']:.1f} sd")
check("noise is estimated from the background, not the whole image",
      abs(faint_stats["background_noise"] - 2.0) < 0.5,
      "MAD ignores the animal because the animal is the outlier")

flat = np.full((240, 400), 200.0)
flat[96:105, 20:220] -= 120
flat_stats = tr.trace_stats([[[x, 100] for x in range(22, 218, 10)]],
                            frame=flat)
check("a noiseless background gives no contrast ratio, not a huge one",
      flat_stats["contrast_sd"] is None)
check("...naming that a denoised real image is suspicious",
      "removes the only reference" in flat_stats["contrast_note"],
      "normal for a synthetic image, suspicious for a real one")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("TRACTABILITY_PASS")
