# WINK Lab Tools v11.121 — no-DIC GCaMP triage, and a segmentation that was erasing the animal

Adds two prototype tools for Pmyo-3 GCaMP recordings that have no DIC channel,
and — while validating them against real lab data — found that the segmentation
they depend on was discarding most of the animal.

## The segmentation finding

`flatten_and_segment` estimates the background with a Gaussian of
`BG_SIGMA = 25` px. On these recordings the worm is roughly **15–25 px wide**,
so the background estimate follows the animal and subtracts it away, leaving
only the brightest core.

Measured on real frames from
`Pmyo-3_GCaMP2/RNAi/.../AVG6_egl-19`:

| frame | intensity threshold | body, corrected | gain |
|---|---|---|---|
| 0 | 2,787 px | **32,209 px** | 11.6× |
| 528 | 2,840 | **32,343** | 11.4× |
| 1728 (coiled) | 3,276 | **17,523** | 5.3× |

At sigma 25 the segmentation did not merely under-cover the worm — on one frame
the largest component it returned was **background noise along a frame edge**.
At sigma 50 whole animals appear, including a fully coiled one. Above ~75 it
collapses back to the bright hook on some frames.

There is a second, deeper problem that sigma alone does not fix. Pmyo-3 GCaMP
brightness varies along the body **with muscle calcium** — the signal being
measured. Any intensity threshold therefore captures a different fraction of
the animal frame to frame, and mask area becomes confounded with the biology.
Conserved-area calibration assumes the opposite.

`segment_body_and_signal()` addresses both: a background sigma that does not
eat the animal, and three-population multi-Otsu splitting background / body /
elevated signal. It returns a **body mask for morphology** and a **signal mask
for calcium within that body**.

It is **opt-in** and sits alongside `flatten_and_segment`. Changing that
default would silently alter every existing result. The sigma is validated on
one dataset — check `mask_width_profile()` on your own frames before a batch
run, exactly as the original handoff says of `CLOSE_PX`.

## An unvalidated classification is no longer asserted

The coil / self-overlap branch was implemented from the published method but had
never been validated: every attempt to build a test case failed, and the one
real candidate turned out to be a two-worm collision.

A frame matching that signature now returns **`unverified_shape_change`**, not
`coiled_self_overlap`. The evidence and the coil hypothesis are kept in the
note — nothing is discarded — and the note warns that a collision has been
mistaken for a coil before. `evaluate_frame(..., enable_coil=True)` restores the
old behaviour for anyone deliberately testing it, and the regression suite fails
loudly if the branch is enabled without a real fixture.

Real coiled frames **do** exist in the data and are now saved as fixtures. What
is still missing is a straight-then-coiled pair of the *same* animal; the two
candidates found are from different acquisitions.

## Folders are not recordings

The single folder `AVG6_egl-19` contains **17 separate acquisitions** of ~107
frames each — `204231`, `204300`, `204329`, … `205153` — concatenated only by
filename sort. `AVG6_L4440` holds 16.

So "frame 528" of that folder is frame 104 of the fifth acquisition, and any
analysis treating the folder as one continuous sequence is comparing different
animals. This confirms and enlarges a suspicion recorded in the original
handoff. Usefully, the filename timestamps mark the boundaries exactly, which
would make a reliable detector — unlike the existing area-jump heuristic, which
its own author records as catching 2 of many real identity changes.

## Regression suite

`tests/test_gcamp_recoverable.py` — 31 checks covering self-consistency,
partial exit, collision, degradation, lost frames, session independence and
cross-contamination, the unverified-coil behaviour, and body/signal separation
against three real archived frames.

The synthetic fixtures test the **classifier**, not the segmentation; that
boundary is deliberate and documented. Two of them failed on first run and the
classifier was right both times — stacking two worms doubles area without
lengthening the longest path, and debris at a frame border genuinely looks like
a partial exit. Both were errors in the fixtures.

## Scope

`gcamp_triage.py` and `gcamp_recoverable.py` are in
`tools/single_channel_gcamp/` as separate modules. Nothing was merged into
`gcamp.py`, and `flatten_and_segment`'s defaults never reach the DIC pipeline.
Neither tool is wired into the hub; they are triage utilities, not replacements
for Track one worm or the supervised segmentation workbench, and they remain
below Experimental grade.
