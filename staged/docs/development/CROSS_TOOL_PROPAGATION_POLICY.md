# NIKE Cross-Tool Propagation Policy

Every useful feature, safeguard, bug fix, or review control developed for one
NIKE tool must trigger a cross-tool applicability audit before release.

## Required audit

Classify every tool sharing the workflow or failure mode as:

1. **Apply directly** — assumptions and behavior match.
2. **Apply conditionally** — enable only when prerequisites such as movie
   input, multiple identities, spatial ROIs, or review tables are present.
3. **Already protected** — an equivalent safeguard already exists.
4. **Not applicable** — document why reuse would be meaningless or would alter
   the assay's scientific definition.

## Reusable capabilities to check

- movie and frame-range selection;
- bounded-memory streaming, sampling, and crop-first loading;
- navigable ROI selection across time;
- exact-frame and keyboard review navigation;
- resumable/autosaved review sessions;
- track inspection, conservative stitching, and undo;
- camera-motion and crossing continuity handling;
- manual thresholds and frame-range recipes;
- descriptive summaries above result tables;
- provenance, edit histories, and source-coordinate restoration;
- shared QC flags and explicit refusal conditions;
- strand/network vectorization, attachment-aware force tensors, damage
  simulation, and uncertainty reporting.

## Scientific firewall

Cross-tool propagation must not silently replace or reinterpret an assay's
metric. Interface, navigation, review, memory, provenance, and mathematical
infrastructure may be shared broadly. Segmentation, frequency, force, posture,
fluorescence, behavioral-state, identity, anatomical boundaries, attachment
points, and loading interpretations require assay-specific validation.

Defaults remain unchanged unless evidence from the target assay supports a new
default. Prefer an opt-in or conditional implementation when evidence is
incomplete.

## Contractile-network estimator

The force-vector estimator must be implemented as a shared network engine plus
anatomical adapters.

- The shared engine may provide strand skeletonization, junction-to-junction
  vectors, thickness weighting, force-capacity tensors, simulated strand loss,
  sensitivity analysis, and confidence/QC measures.
- The uterine adapter must define vulval center, anterior/posterior lobes,
  proximal um1 and distal um2 ensembles, resolvable left/right cells,
  cuticle-directed attachment geometry, and dystrophin association.
- A pharyngeal adapter may be evaluated after uterine validation. It must define
  pharyngeal compartments, lumen and cuticular boundaries, radial/circumferential
  orientation, attachment assumptions, and contraction interpretation from
  pharyngeal anatomy rather than inheriting uterine labels.

## Release evidence

Each changelog must state which tools were audited, which received the change,
which were already protected or excluded, whether calculations/defaults
changed, and what regression or real-recording checks were performed.

The propagation audit is part of completion, not optional follow-up work.
