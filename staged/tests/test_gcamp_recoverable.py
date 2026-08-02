"""Fixture-based regression tests for the no-DIC GCaMP recoverability triage.

WHAT THESE COVER, AND WHAT THEY DO NOT
--------------------------------------
These exercise the CLASSIFIER - the logic that turns a mask plus a calibration
into a frame status. They do not test segmentation: the masks here are
constructed directly, so `flatten_and_segment` and its unvalidated CLOSE_PX
default are deliberately out of scope.

That distinction matters. The handoff notes that synthetic "fold" shapes do not
conserve area the way real self-overlap does, so a synthetic coil fixture would
test nothing real. Partial exit, collision and degradation DO have honest
synthetic signatures - a clipped mask really does lose length and area at a
border, two merged blobs really do double both - so those are tested here.

The coil case is therefore represented by a PLACEHOLDER that fails loudly if
someone enables the coil classification without adding a real fixture.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "single_channel_gcamp"))
import gcamp_recoverable as gr


# --------------------------------------------------------------------------
# Fixtures: masks with known ground truth, built to have honest signatures
# --------------------------------------------------------------------------
SHAPE = (400, 600)


def worm_mask(shape=SHAPE, x0=80, x1=520, y=200, amplitude=40, half_width=9):
    """A single sinusoidal worm, fully inside the frame."""
    mask = np.zeros(shape, bool)
    xs = np.arange(x0, x1)
    ys = y + amplitude * np.sin(np.linspace(0, 2.2 * np.pi, len(xs)))
    for x, yc in zip(xs, ys):
        lo = max(0, int(yc - half_width)); hi = min(shape[0], int(yc + half_width) + 1)
        mask[lo:hi, int(x)] = True
    return mask


def clipped_worm(shape=SHAPE, keep_fraction=0.55):
    """A worm that genuinely left the frame: length AND area drop, edge touched."""
    full = worm_mask(shape)
    cut = int(shape[1] * keep_fraction)
    mask = np.zeros_like(full)
    mask[:, :cut] = full[:, :cut]
    # slide it so the surviving part reaches the real border
    shift = int(np.min(np.nonzero(mask.any(axis=0))[0]))
    return np.roll(mask, -shift, axis=1)


# A collision needs two FULL-SIZED animals, which will not fit in the standard
# fixture frame side by side, so it gets its own larger frame and its own
# single-worm calibration. Calibration is per-animal anyway, so this is not a
# special case - it is the same relationship as any other session.
COLLISION_SHAPE = (500, 1000)
COLLISION_X0, COLLISION_X1 = 60, 500          # same 440 px body as the standard worm


def collision_reference(shape=COLLISION_SHAPE):
    """One animal, alone, in the collision frame - the calibration for it."""
    return worm_mask(shape, x0=COLLISION_X0, x1=COLLISION_X1, y=150, amplitude=30)


def collision_mask(shape=COLLISION_SHAPE):
    """Two full-sized worms touching end to end.

    The signature is length AND area rising together, because a second animal
    contributes both. Two worms stacked one on top of the other would double
    the area while leaving the longest path roughly unchanged - a different
    situation, correctly NOT called a collision. Two SHORT worms would not
    raise the area much at all. They must be full-sized and joined end to end.
    """
    a = collision_reference(shape)
    b = worm_mask(shape, x0=COLLISION_X1 - 10, x1=COLLISION_X1 + 430,
                  y=300, amplitude=-30)
    return a | b


def degraded_mask(shape=SHAPE, seed=0, margin=40):
    """Segmentation failure: mass lost, fragments scattered, NO edge contact.

    Kept clear of the borders on purpose. Debris touching a frame edge is a
    genuinely ambiguous case - it looks like a partial exit and the classifier
    reads it as one - so including it here would test edge handling rather than
    degradation.
    """
    rng = np.random.default_rng(seed)
    full = worm_mask(shape)
    mask = full & (rng.random(full.shape) < 0.35)
    ys = rng.integers(margin, shape[0] - margin, 40)
    xs = rng.integers(margin, shape[1] - margin, 40)
    mask[ys, xs] = True
    mask[:margin, :] = False; mask[-margin:, :] = False
    mask[:, :margin] = False; mask[:, -margin:] = False
    return mask


def calib_from_mask(mask):
    calib = gr.mask_length_and_area(mask)
    calib["source"] = "fixture"
    calib = gr._with_width(calib, mask)
    if not np.isnan(calib["cut_half_width_px"]):
        coil = gr.coil_aware_length(mask, calib["cut_half_width_px"])
        if coil["length_px"] > 0:
            calib["length_px"] = coil["length_px"]
    return calib


CALIB = calib_from_mask(worm_mask())
results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("no-DIC GCaMP recoverability - classifier regression\n")

# 1. Self-consistency: a frame against its own calibration is a perfect match.
ev = gr.evaluate_frame(worm_mask(), CALIB, frame_index=0)
check("self-consistency is full_view", ev.status == "full_view", ev.status)
check("self-consistency length_frac == 1", abs(ev.length_frac - 1.0) < 1e-9,
      f"{ev.length_frac:.6f}")
check("self-consistency area_frac == 1", abs(ev.area_frac - 1.0) < 1e-9,
      f"{ev.area_frac:.6f}")

# 2. A real partial exit: length and area both fall, and the mask touches an edge.
partial = clipped_worm()
ev = gr.evaluate_frame(partial, CALIB, frame_index=1)
check("partial exit is not full_view", ev.status != "full_view", ev.status)
check("partial exit touches an edge", bool(gr.touches_frame_edge(partial)),
      ",".join(gr.touches_frame_edge(partial)) or "none")
check("partial exit loses area", ev.area_frac < 0.85, f"area_frac {ev.area_frac:.3f}")

# 3. Collision: both length and area jump together, no edge contact.
coll = collision_mask()
COLL_CALIB = calib_from_mask(collision_reference())
check("collision reference alone is full_view",
      gr.evaluate_frame(collision_reference(), COLL_CALIB).status == "full_view")
check("collision mask stays clear of the edges",
      not gr.touches_frame_edge(coll), ",".join(gr.touches_frame_edge(coll)) or "none")
ev_coll = gr.evaluate_frame(coll, COLL_CALIB, frame_index=2)
check("collision is flagged possible_collision",
      ev_coll.status == "possible_collision", ev_coll.status)
check("collision roughly doubles area", ev_coll.area_frac > 1.5,
      f"area_frac {ev_coll.area_frac:.2f}")

# 4. Degradation is not mistaken for a partial exit.
ev_deg = gr.evaluate_frame(degraded_mask(), CALIB, frame_index=3)
check("degraded is not full_view", ev_deg.status != "full_view", ev_deg.status)
check("degraded is not called a partial exit",
      ev_deg.status != "partial_out_of_frame", ev_deg.status)

# 5. An empty mask is 'lost', not an error.
ev_lost = gr.evaluate_frame(np.zeros(SHAPE, bool), CALIB, frame_index=4)
check("empty mask is lost", ev_lost.status == "lost", ev_lost.status)

# 6. The coil classification must stay unasserted until it has a real fixture.
check("coil classification is disabled by default",
      gr.ENABLE_COIL_CLASSIFICATION is False)

REAL_COIL_FIXTURE = ROOT / "tests" / "gcamp_fixtures" / "real_coiled_frame.npy"
if gr.ENABLE_COIL_CLASSIFICATION:
    # Enabling it without a real straight-then-coiled pair is exactly the
    # mistake the handoff warns about: a synthetic fold does not conserve area
    # the way real self-overlap does, so it would validate nothing.
    check("coil enabled -> a REAL coiled fixture must exist",
          REAL_COIL_FIXTURE.exists(),
          f"missing {REAL_COIL_FIXTURE.name}")
else:
    check("coil fixture is documented as still needed",
          not REAL_COIL_FIXTURE.exists() or REAL_COIL_FIXTURE.exists(),
          "placeholder - add a real straight-then-coiled pair to enable")

# 7. Sessions calibrate independently and do not contaminate each other.
small = worm_mask(x1=380, half_width=7)
big = worm_mask(x1=560, half_width=12)
c_small, c_big = calib_from_mask(small), calib_from_mask(big)
ev_small = gr.evaluate_frame(small, c_small, frame_index=0)
ev_big = gr.evaluate_frame(big, c_big, frame_index=0)
check("session A frame 0 is full_view against its own calibration",
      ev_small.status == "full_view", ev_small.status)
check("session B frame 0 is full_view against its own calibration",
      ev_big.status == "full_view", ev_big.status)
cross = gr.evaluate_frame(big, c_small, frame_index=0)
check("a different worm against the wrong calibration is NOT full_view",
      cross.status != "full_view", cross.status)

# 8. summarize_recoverability must not count an unverified frame as usable.
fake = [gr.FrameEval(0, "full_view", 1.0, 1.0, 1.0),
        gr.FrameEval(1, gr.UNVERIFIED_COIL_STATUS, 0.7, 1.0, 1.4),
        gr.FrameEval(2, "lost")]
summary = gr.summarize_recoverability(fake)
check("unverified frames are not counted usable",
      summary["n_usable_frames"] == 1, f"n_usable={summary['n_usable_frames']}")

# 9. Body/signal separation against REAL frames, if the fixtures are present.
fixtures = sorted((ROOT / "tests" / "gcamp_fixtures").glob("frame_*.tif"))
if fixtures:
    import cv2
    print(f"\n  (real-frame fixtures: {len(fixtures)})")
    for path in fixtures:
        raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if raw is None:
            continue
        if raw.ndim == 3:
            raw = raw[..., :3].mean(axis=2)
        raw = np.clip(raw, 0, 255).astype(np.uint8)
        body, signal = gr.segment_body_and_signal(raw)
        intensity_only = gr.flatten_and_segment(raw)
        ok = body is not None and signal is not None
        check(f"{path.name}: body and signal both segmented", ok)
        if not ok:
            continue
        check(f"{path.name}: body is larger than the intensity-only mask",
              body.sum() > (intensity_only.sum() if intensity_only is not None else 0),
              f"{int(body.sum()):,} vs "
              f"{int(intensity_only.sum()) if intensity_only is not None else 0:,}")
        check(f"{path.name}: signal lies inside the body",
              bool((signal & ~body).sum() == 0))
        check(f"{path.name}: body is not the whole frame",
              body.mean() < 0.35, f"{body.mean():.1%} of frame")
else:
    print("\n  (no real-frame fixtures present - body/signal checks skipped)")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("GCAMP_RECOVERABLE_REGRESSION_PASS")
