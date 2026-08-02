# Findings against real Pmyo-3 GCaMP data

Follow-up to `HANDOFF_gcamp_no_dic_triage.md`, working through its suggested
integration path against
`L:\02_Duchenne Muscular Dystrophy\Kiley\Raw data\Pmyo-3_GCaMP2\RNAi`.

## Done

**Item 1 — no-DIC path kept distinct.** `gcamp_triage.py` and
`gcamp_recoverable.py` live in `tools/single_channel_gcamp/` as separate
modules. Nothing was merged into `gcamp.py`; `flatten_and_segment`'s defaults
never reach the DIC pipeline.

**Item 4 — the coil branch no longer asserts an unverified label.**
`ENABLE_COIL_CLASSIFICATION = False`. A frame matching the coil signature now
returns **`unverified_shape_change`**, keeping the evidence and the coil
hypothesis in its note, and warning that a two-worm collision has previously
been mistaken for one. `evaluate_frame(..., enable_coil=True)` restores the old
behaviour for anyone deliberately testing it.

**Item 3 — a fixture regression suite exists.**
`tests/test_gcamp_recoverable.py`, 19 checks: self-consistency (`length_frac`
and `area_frac` exactly 1.0), partial exit, collision, degradation, lost,
session independence and cross-contamination, plus the unverified-coil
behaviour and that unverified frames are not counted usable.

These exercise the **classifier**, not the segmentation - the masks are
constructed directly. That boundary is deliberate and is documented in the test
file.

Worth recording: two fixtures failed on first run and **the classifier was
right both times**. Stacking two worms doubled area without lengthening the
longest path, and was correctly refused as a collision. Scattering debris to
the frame borders correctly read as a partial exit. Both were fixture errors.

## Real coils exist, and cannot currently be measured

Scanning `AVG6_egl-19` (152 frames sampled at stride 12) found 11 frames
matching the coil signature. Two were inspected directly.

**Frame index 1728 is an unambiguous coil** - a single animal folded into a
closed loop. So the fixture the coil branch has always needed is findable in
this data.

**But the segmentation does not capture the animal.** In both inspected frames
the mask covers only the bright anterior hook while the raw frame plainly shows
much more body. The measured `area_frac` near 1.0 that triggered the coil
signature is therefore an artefact of what got segmented, not evidence that
area was conserved.

Two attempts to quantify the shortfall both failed, and the failures are
informative:

- Thresholding a few noise sigma above a flattened background returned ~95% of
  the frame - it segmented the noise.
- Otsu on the flattened image returned *less* than the default segmentation,
  so it is no ceiling either.

What can be stated: two defensible segmentations of the same frame disagree by
**1.3x to 2.6x** (frame 528: 2,840 px vs 1,102 px). An area that moves that
much with threshold choice is a soft foundation for conserved-area calibration.

### Why this is likely fundamental for this assay

Pmyo-3 GCaMP brightness varies along the body **with muscle calcium** - which is
the signal being measured. Any intensity threshold therefore captures a
different fraction of the animal from frame to frame, and the segmented area is
confounded with the biology under study. Conserved-area calibration assumes
mask area reflects the animal's size; here it partly reflects how much of the
animal is currently active.

This does not condemn the approach, but it does mean the coil branch cannot be
validated until segmentation captures whole animals - shape- or
continuity-based rather than purely intensity-thresholded, or accumulated over
frames so dim segments are not lost.

Fixture material is preserved in `tests/gcamp_fixtures/`: frames 0 (clean),
528 and 1728 (coil candidates), ready for when segmentation improves.

## The mixed-identity finding is confirmed and larger than described

The handoff suspected `fc2_save_2020-09-22-204440-*` contained different
individuals. It does, and the scale is worth stating: the single folder
`AVG6_egl-19` holds **17 separate acquisitions** of ~107 frames each -
`204231`, `204300`, `204329`, `204415`, `204440`, ... `205153` - concatenated
only by filename sort. `AVG6_L4440` holds 16.

So "index 528" is not frame 528 of a recording; it is frame 104 of the fifth
acquisition. Any analysis treating one of these folders as a continuous
sequence is comparing different animals.

This strengthens the case for item 2 (`Session`/`FrameSource` as a shared
utility), and it means every historical folder here needs session boundaries -
which, usefully, the filename timestamps supply exactly. An automatic
boundary-finder keyed on the acquisition prefix would be reliable, unlike
`suggest_session_boundaries()`'s area-jump heuristic, which the handoff already
records as weak.

## Not done

**Item 2 — `Session`/`FrameSource` promoted to a shared utility.** The
reasoning is sound and now better supported, but promoting a prototype that is
not yet Experimental-grade into shared space invites other modules to depend on
it. Recommend doing it together with a filename-prefix boundary detector, which
is the piece that would make it genuinely useful here.

**The coil fixture is still not usable.** Real coiled frames are identified and
saved, but until segmentation captures whole animals they cannot validate the
branch. The test suite fails loudly if anyone enables the coil classification
without a real fixture.
