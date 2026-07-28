# NIKE application v11.19

## Strictly bounded spine correction

- Treats **b** and **e** as trusted boundary spines in both the single-worm DIC and anterior-neuron/body reviewers, reconstructing only the frames strictly between them.
- Keeps a bounded-edit region active after **e** so **f** can add any number of intervening manual anchors without forward retracking beyond the interval.
- Uses **a** to visit recursively suggested midpoint anchors and **c** to leave bounded-edit mode.
- Restricts gap filling and endpoint stabilization to the selected interval, preventing changes to other flagged sequences elsewhere in the recording.

## Background and identity protection

- Applies the user-traced worm length and area before automatic masks are selected.
- Rejects candidate fragments below 55% and oversized structures above 160% of the traced area before either can become the next-frame tracking hint.
- Uses calibrated size similarity for candidate scoring in addition to registered temporal-background residual motion and spatial continuity.
- Persists the manual identity-calibration flag in resumable review sessions.

## Installation

- This is an application-only update. Existing NIKE installations can install it through **Help > Check for updates**; no runtime reinstall is required.
