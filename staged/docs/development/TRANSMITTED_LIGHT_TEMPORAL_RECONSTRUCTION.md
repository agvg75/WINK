# Transmitted-light temporal reconstruction

The single-worm DIC kinematics tracker, pBoc tracker, and AFD/neuron body
tracker share the following safeguards:

- clip-local camera translation is estimated before temporal-background
  comparison;
- failed runs have no hard-coded frame-count limit;
- trusted flanking spines are compared in body-length units, and reconstruction
  is attempted when centroid translation is no more than half a body length and
  the aligned postures satisfy the shared agreement gate;
- intervals that cannot be bridged suggest their midpoint as a manual anchor;
  each added anchor recursively subdivides only the still-unsafe interval, and
  users may add optional anchors on any frame;
- inferred geometry retains raw geometry and is labeled
  `inferred_between_neighbors`;
- isolated endpoint jumps may be stabilized without changing the rest of the
  measured spine;
- one-sided gaps remain flagged for manual review and receive a suggested
  uncertainty-halving anchor.

For numbered still-image recordings, selecting one image loads only its shared
recording prefix and numeric suffix. Image dimensions are not used to combine
separate recordings because multiple experiments commonly share camera size.

## Resumable review and user-selected intervals

Single-animal Python reviewers save versioned work-in-progress state, including
manual anchors, inferred spines, flags, reference geometry, and provenance.
Closing a review window saves without finalizing; reopening the same recording
offers to restore the session. Users may flag an unrecognized bad interval with
**b** on a trusted beginning spine and **e** on a trusted ending spine. Those
two boundary spines remain anchors and reconstruction is limited to frames
strictly between them. Bounded-edit mode remains active after **e**: **f** adds
as many intervening manual anchors as needed, **a** visits the next suggested
midpoint, and **c** closes bounded editing. Neither reconstruction nor an **f**
anchor in this mode can retrack geometry outside **b...e**. This applies to the
single-worm DIC and anterior-neuron/body Python reviewers. The pBoc calibration
navigator already uses explicit saved landmark anchors; the RGBCaMP Fiji
reviewer uses its independent reference-frame and manual-midline workflow
rather than the **b/e** reviewer interface.

After an initial interpolation, every additional **f** anchor invalidates the
old non-manual interpolation inside the active interval. All existing manual
anchors and the **b/e** boundaries remain trusted, and each resulting
subinterval is reconstructed anew. Thus a newly drawn internal anchor changes
the surrounding solution instead of being placed into an already-frozen
interpolation.

The same mathematical rule applies outside the Python **b/e** interface.
RGBCaMP Fiji invalidates all prior neighbor-filled midlines whenever another
manual midline is drawn, then rebuilds the N+1 subintervals defined by its
ordered manual/reference anchors. pBoc marks every supplied outline landmark
as authoritative manual geometry, so all calibration anchors remain available
to its variable-length temporal reconstruction.

When the user supplies an initial outline, its area is established before any
automatic frame candidate is selected. Candidate fragments below 55% or large
structures above 160% of the traced area are rejected before they can become a
continuity hint. The registered temporal background remains a motion/identity
signal; it does not by itself erase a nearly stationary living worm.

pBoc calibration uses a scrollable navigator for baseline, peak, and recovery
outlines. Those outlines define the acceptable adult length and area envelope;
substantially smaller larvae cannot be accepted as shortened target geometry.

Population assays remain on their multi-object tracking engines because they
do not have a user-traced single-worm identity or outline.

## pBoc calibration

pBoc requires three complete, head-to-tail-consistent outlines:

1. the last full-length frame before contraction;
2. the minimum-length peak;
3. the first fully recovered frame.

These anchors calibrate shortening, area conservation, contraction/recovery
duration and rate, and the posterior-versus-anterior fraction of textured worm
pixels participating in axial residual motion. Candidate scores combine axial
flow, calibrated shortening, area conservation, axial participation, and a
cadence priority. The 30–90 second window remains a review prior, never an
automatic biological decision.

Raw flow, raw length, regularized geometry, and reconstruction provenance are
exported separately. A length-regularized tracking spine must not be treated as
a direct contraction measurement.
