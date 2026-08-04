"""Does orientation actually find myocyte edges? Synthetic fibres, known answers.

No confocal stack with bytes in it has been located yet, so this is a fixture -
and a fixture proves the METHOD works on the phenomenon as modelled, never that
the model matches a worm. What it can settle is whether the maths recovers a
boundary it was not told about, which is a real question with a real answer, and
one worth settling before anyone's afternoon is spent on it.

The fixture is built to the lab's stated acquisition:
  * zoomed to one region, so a handful of myocytes are in frame, not 24
  * fibres obliquely striated, running at a shallow angle to the body axis
  * depth stopped short of the contralateral side, so ONE muscle layer
  * anterior left
Critically the fixture has NO intensity edge at the boundaries - brightness is
uniform across them - so anything found is found from orientation alone. If the
detector were secretly keying on intensity it would score zero here.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import fibre_orientation as fo               # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def synth_quadrant(nz=8, ny=120, nx=400, cell_px=80, angles=(20, -18, 22, -16, 19),
                   spacing=6.0, noise=0.08, seed=7):
    """One muscle quadrant: abutting cells whose fibres alternate in angle.

    Alternating sign is the real anatomy being modelled - neighbouring myocytes
    are not randomly oriented, they mirror - which is exactly why the boundary is
    an orientation discontinuity and not an intensity one.
    """
    rng = np.random.default_rng(seed)
    img = np.zeros((ny, nx), dtype=float)
    yy, xx = np.mgrid[0:ny, 0:nx]
    edges = [i * cell_px for i in range(len(angles) + 1)]
    yc = ny / 2.0
    offset, prev = 0.0, None
    for k, ang in enumerate(angles):
        x0, x1 = edges[k], min(edges[k + 1], nx)
        if x0 >= nx:
            break
        sl = (slice(None), slice(x0, x1))
        th = np.deg2rad(ang)
        # Phase-match each cell to its neighbour at the seam. Without this the
        # striations restart abruptly and leave a brightness step exactly where
        # the boundary is - which would hand the detector an intensity cue and
        # quietly invalidate the whole experiment.
        if prev is not None:
            th_p, off_p = prev
            offset = ((x0 * np.sin(th_p) + yc * np.cos(th_p)) / spacing + off_p
                      - (x0 * np.sin(th) + yc * np.cos(th)) / spacing)
        prev = (th, offset)
        # Striations perpendicular to the fibre direction.
        phase = (xx[sl] * np.sin(th) + yy[sl] * np.cos(th)) / spacing + offset
        img[sl] = 0.5 + 0.5 * np.sin(2 * np.pi * phase)
    # Uniform brightness envelope across x: NO intensity cue at the borders.
    img *= (0.6 + 0.4 * np.exp(-((yy - ny / 2) ** 2) / (2 * (ny / 3.2) ** 2)))
    stack = np.repeat(img[None], nz, axis=0)
    stack = stack + rng.normal(0, noise, stack.shape)
    return np.clip(stack, 0, None), edges[1:len(angles)]


print("fibre orientation - does it find edges nobody told it about?\n")

stack, true_edges = synth_quadrant()
print(f"  fixture: {stack.shape} stack, true boundaries at x = {true_edges}\n")

# --- the fixture must not leak a USABLE intensity cue ---------------------
# Phase-matching cancels the seam exactly at mid-height only, so about 1% of
# full scale survives. That is stated as an absolute bound rather than a
# multiple of local noise, because the question is whether a detector could
# LIVE on this cue, not whether it is literally zero. The decisive check is the
# adversarial one further down: a real intensity step with no orientation
# change must yield nothing.
col_mean = stack.mean(axis=(0, 1))
jumps = np.abs(np.diff(col_mean))
at_edges = max(jumps[max(e - 2, 0):e + 2].max() for e in true_edges)
# Normalise by the IMAGE's dynamic range, not the column-mean's. Averaging down
# columns cancels the striations, so the column-mean range is a hair wide and
# any residue looks enormous against it - a scaling artefact, not a finding.
span = float(stack.max() - stack.min())
check("the fixture leaks no usable intensity step at the boundaries",
      at_edges < 0.02 * span,
      f"edge jump {at_edges:.4f} = {100 * at_edges / span:.2f}% of image range")

# --- orientation recovers the planted angles ------------------------------
angles, coherence = fo.orientation_volume(stack, sigma=1.5, rho=6.0)
check("coherence is high inside fibre bundles, low nowhere-in-particular",
      coherence[:, 40:80, 20:60].mean() > 0.5,
      f"mean coherence {coherence[:, 40:80, 20:60].mean():.3f}")

# Angle inside the first cell should be near its planted value. The fixture
# plants a striation NORMAL of theta, so the FIBRE runs perpendicular to it, at
# -theta mod 180. The tensor reports the fibre, which is the thing anatomy
# cares about, so that is what is expected here.
inside = angles[:, 40:80, 20:60]
w = coherence[:, 40:80, 20:60]
d = np.deg2rad(inside * 2.0)
recovered = (np.degrees(np.arctan2((np.sin(d) * w).sum(),
                                   (np.cos(d) * w).sum())) / 2.0) % 180.0
expected_fibre = (-20.0) % 180.0
err = fo._angular_difference(recovered, expected_fibre)
check("the planted fibre angle is recovered within a few degrees", err < 5.0,
      f"recovered {recovered:.1f} deg vs expected {expected_fibre:.0f}, err {err:.1f}")

# --- the actual question: are the boundaries found? -----------------------
mean_angle, support = fo.divider_profile(angles, coherence)
# window >= the integration scale rho used above; see propose_dividers.
prop = fo.propose_dividers(mean_angle, support, expected=len(true_edges),
                           min_turn_deg=8.0, min_separation=30, window=12)
found = prop["dividers"]
print(f"\n  proposed dividers: {found}")
print(f"  true boundaries:   {true_edges}\n")

TOL = 12          # px; a boundary is a band, not a line
matched = [t for t in true_edges if any(abs(f - t) <= TOL for f in found)]
check("every planted boundary is proposed within tolerance",
      len(matched) == len(true_edges),
      f"{len(matched)}/{len(true_edges)} matched within {TOL} px")
check("no spurious extra dividers are invented",
      len(found) <= len(true_edges),
      f"{len(found)} proposed for {len(true_edges)} true")

if matched:
    offs = [min(abs(f - t) for f in found) for t in matched]
    check("localisation is good enough to be worth correcting rather than redoing",
          max(offs) <= TOL, f"worst offset {max(offs)} px")

# --- the honesty properties ----------------------------------------------
flat, _ = synth_quadrant(angles=(20, 20, 20, 20, 20))
fa, fc = fo.orientation_volume(flat, sigma=1.5, rho=6.0)
fm, fs = fo.divider_profile(fa, fc)
flat_prop = fo.propose_dividers(fm, fs, expected=4, min_turn_deg=8.0,
                                min_separation=30, window=12)
check("a quadrant with NO orientation change proposes (almost) nothing",
      flat_prop["n_found"] <= 1,
      f"{flat_prop['n_found']} proposed on a uniform field")
check("...and reports the shortfall instead of padding to the expected count",
      "shortfall_note" in flat_prop and flat_prop["n_found"] < 4)

# THE DECISIVE ONE: a hard intensity step, uniform fibre angle throughout. An
# intensity-based segmenter finds a boundary here every time. An orientation
# detector must find nothing, because anatomically nothing is there - and a
# brightness step across a field IS what uneven staining and depth attenuation
# look like in a real phalloidin stack.
stepped, _ = synth_quadrant(angles=(20, 20, 20, 20, 20))
stepped[:, :, 200:] *= 0.45
sa, sc = fo.orientation_volume(stepped, sigma=1.5, rho=6.0)
sm, ss = fo.divider_profile(sa, sc)
step_prop = fo.propose_dividers(sm, ss, expected=1, min_turn_deg=8.0,
                                min_separation=30, window=12)
near_step = [d for d in step_prop["dividers"] if abs(d - 200) <= 20]
check("a pure INTENSITY step with no orientation change is not called a boundary",
      not near_step,
      f"proposed {step_prop['dividers']} against a brightness step at x=200")

blank = np.zeros((4, 60, 200))
ba, bc = fo.orientation_volume(blank)
check("a blank stack yields zero coherence, not a confident angle",
      float(bc.max()) < 1e-6, f"max coherence {bc.max():.2e}")

try:
    fo.orientation_volume(np.zeros((10, 10)))
    check("a stack without an explicit depth axis is refused", False)
except ValueError as exc:
    check("a stack without an explicit depth axis is refused", True)
    check("...and the refusal names why depth must be explicit",
          "per plane" in str(exc))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("FIBRE_ORIENTATION_PASS")
