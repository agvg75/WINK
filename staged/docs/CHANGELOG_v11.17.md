# NIKE application v11.17

## Adaptive transmitted-light reconstruction

- Removes hard-coded frame-count limits from single-animal spine-gap reconstruction.
- Attempts two-sided reconstruction when trusted flanks translate no more than half a body length and satisfy the aligned-posture agreement gate.
- Suggests the temporal midpoint of an unbridgeable interval as the next manual anchor; each correction recursively subdivides only the remaining unsafe interval.
- Lets reviewers add an optional anchor on any frame and preserves manual anchors as ground truth.
- Applies the shared policy to single-animal DIC kinematics, pBoc/defecation, anterior-neuron body tracking, and the RGBCaMP Fiji tracker.

## Numbered image sequences

- Selecting one numbered image now loads only its matching recording prefix and numeric suffix.
- Separate same-sized recordings stored in one folder are no longer concatenated into one artificial movie.

## Installation

- This is an application-only update. Existing NIKE v11.15 or v11.16 installations can install it through **Help > Check for updates**; no new runtime installation is required.
