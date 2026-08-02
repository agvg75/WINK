# Handoff: Pmyo-3 GCaMP (no-DIC, blue-only) triage + recoverability tools

Two prototype scripts, built and hand-tested outside the Hub, not yet
wired into `app/lab_hub.py` or given a real Fiji/tracker integration.
Both are triage/pre-flight tools, not replacements for Track one worm or
the supervised segmentation workbench. Status per the manual's own
ladder: **regression-tested by hand against real frames, not yet
Experimental-grade** (no fixture-based test suite, no broad validation
set).

## Files

- `gcamp_triage.py` — batch triage across a folder of movies. Downsamples
  for cheap blob detection, links candidate blobs into tracks across
  sampled frames, classifies each movie as `workable` /
  `needs_review_distractor` / `not_workable`. ROI support mirrors the
  pharyngeal-pumping ROI pattern; distractor logic mirrors pBoc's
  explicit-annotation-over-silent-resolution philosophy.

- `gcamp_recoverable.py` — the harder case: high-zoom, single-channel,
  no-DIC frames where the worm fills much of the frame and needs
  background flattening instead of DIC-based tracking. Implements:
  - `flatten_and_segment()` — background subtraction + adaptive threshold
    + morphological closing. **CLOSE_PX default (15) is unvalidated
    per-dataset** — it corrupted a width model on one real test frame
    when left at an earlier default of 41. Always sanity-check
    `mask_width_profile()` output before trusting a batch run.
  - Conserved-length/area calibration (`calibrate_from_polygon`,
    `calibrate_from_auto_segmentation`), same pattern as Track one worm's
    user-drawn outline and pBoc's three-outline calibration.
  - `evaluate_frame()` — classifies each frame as `full_view` /
    `partial_out_of_frame` / `coiled_self_overlap` / `possible_collision`
    / `degraded` / `lost` against that calibration.
  - `coil_aware_length()` — distance-transform cutting + skeleton-graph
    longest-path length, adapted from Layana Castro, Puchalt &
    Sánchez-Salmerón (2020), *Sci Rep* 10:22247 (MIT-licensed reference
    implementation: github.com/playanaC/Skeletonization). Reimplemented
    from the published method, not ported.
  - `Session` / `FrameSource` / `run_sessions()` — mark start/end frame
    ranges so each continuous single-worm stretch gets its own
    independent calibration. Required for any historical data where a
    folder may contain more than one worm (see below).
  - `generate_review_contact_sheet()` — paginated labeled thumbnail grids
    for fast manual session-boundary marking on unsorted historical data.

## What's actually validated (tested against real frames, not synthetic)

- Self-consistency: a frame evaluated against its own calibration reads
  `full_view` with length_frac/area_frac == 1.0 exactly.
- `degraded` classification: correctly separates real segmentation
  failure (heavy blur test) from a real partial exit.
- `possible_collision` classification: **validated against real data** —
  a genuine two-worm collision in a real frame sequence (frames where
  length AND area both roughly doubled together, no edge contact) was
  correctly flagged and NOT confused with coiling or a partial exit.
- Session independence: two sessions run back-to-back produce
  independently-calibrated, non-contaminating results (confirmed by each
  session's frame 0 reading exactly `full_view` against its own
  calibration).

## What's NOT validated — do not represent these as working

- `coiled_self_overlap`: implemented per the published method, but every
  attempt to construct a valid test case failed (synthetic "fold" tests
  don't conserve area the way real self-overlap does; the one real
  candidate frame turned out to be a collision, not a coil, once
  checked). **Needs a real same-worm straight-then-coiled frame pair**
  before this can be trusted.
- `partial_out_of_frame`: background flattening loses real signal in
  roughly the outer 50–75px of the frame regardless of border handling
  tried so far (`BORDER_REPLICATE` did not fully fix it). A worm
  genuinely crossing the true edge may not reliably get flagged as
  touching it. Needs a smaller-sigma or edge-specific local segmentation
  pass.
- `suggest_session_boundaries()`: tested honestly weak — on a real batch
  of different-sized worms, it only caught 2 of the many actual identity
  changes (area jump alone isn't a reliable signal when worm sizes are
  similar). Treat as a minor hint, not a real automatic boundary-finder.
  Manual marking via the contact sheet is the primary path.

## Known real-data finding worth carrying forward

Testing against an actual lab frame sequence
(`fc2_save_2020-09-22-204440-*`) surfaced that this specific historical
batch contains **different individual worms across the sequence, not one
continuous recording** — discovered because two "clean, simple" frames
gave inconsistent conserved-length ratios (0.71–0.77) against each other,
which is why the session/calibration-boundary system exists. Going
forward, one-worm-per-folder acquisition removes the need for manual
session marking entirely (a whole folder becomes a single default
session). Historical data should be assumed mixed until proven otherwise.

## Suggested integration path

1. Do NOT merge `flatten_and_segment`'s defaults into any pipeline that
   also handles the existing DIC-based movies — this is a distinct
   no-DIC code path per the manual's photometry-firewall pattern (see
   "RGBCaMP retains its Fiji/manual-midline default and cannot receive
   this DIC map through the photometry firewall").
2. `Session`/`FrameSource` is the more broadly reusable piece — consider
   whether it belongs as a shared utility rather than living only in this
   script, since "a folder contains more than one identity" is a general
   problem, not specific to GCaMP.
3. Before promoting anything past Experimental status: build a small
   fixture-based regression test set (a handful of frames with known
   ground truth for full/partial/coiled/collision), per the manual's own
   validation-level requirements — none of what's here has that yet, it's
   been validated ad hoc against whatever real frames were available in
   this session.
4. The coil branch specifically should probably stay disabled/unexposed
   until a real test case is found; shipping an unverified classification
   label is worse than not having the label.
