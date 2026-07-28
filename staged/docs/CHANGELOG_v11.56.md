# NIKE Lab Tools v11.56 notes

Date: 2026-07-25

This patch implements reusable lessons from the recent pharyngeal/egg/defecation
discussion and literature scan: keep the human in the loop, make automatic
decisions explicit, and expose enough method detail for students and reviewers
to understand why a module proposed or rejected a feature.

## Endpoint egg counting

- Added an explicit multi-cue vote summary to the decision-transparency export.
- Added learned reject-memory scoring:
  - accepted eggs still grow the shared prototype library;
  - rejected candidates are saved as false-positive traps;
  - future proposals now carry `false_positive_match_score` and
    `false_positive_memory_hit` fields;
  - a new `Reject-memory match` dial controls how strongly those rejected
    examples veto look-alikes.
- Preserved the color contract:
  - cyan = module proposal not yet evaluated;
  - green = accepted by reviewer;
  - red = rejected by reviewer;
  - orange = manually added/reference/training egg.
- Added the missing `reviewed_eggs_all_states.png` overlay promised by the
  decision manifest.
- Updated the review side controls so the reject-memory threshold can be tuned
  live alongside vote and contrast thresholds.

## Shared transparent-decision infrastructure

- Added `vote_policy_summary()` to `app/decision_transparency.py` so modules can
  export a consistent, plain-language description of multi-cue vote detectors.
- The intended standard remains: automatic candidates are hypotheses; reviewed
  accepted records are the final measurement source when review is offered.

## Acquisition advisor

Added “before you film” guidance profiles for:

- Endpoint egg counting
- Defecation / pBoc
- Foraging / nose tracking

These profiles describe the feature that must be visible, approximate pixel and
frame-rate floors, known difficult recordings, and when downsampled proxies are
safe.

## Shared worm-geometry helper

- Added optional centerline smoothing and QC helpers to
  `app/temporal_worm_geometry.py`:
  - `smooth_centerline()`
  - `centerline_jaggedness()`
  - `centerline_qc()`
- These helpers are deliberately opt-in and preserve endpoints/arc length by
  default, so modules can expose smoothing as a checkbox without silently
  changing raw measurements.

## Validation

- Syntax compilation passed for the touched staged files.
- Full egg/defecation tests could not be run in the bundled Codex runtime because
  that runtime does not include OpenCV (`cv2`). The deployed NIKE runtime should
  still be used for functional testing on real images.
