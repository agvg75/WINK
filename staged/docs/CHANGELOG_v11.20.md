# NIKE application v11.20

## Recursive internal anchors

- Fixes a defect in v11.19 where an internal **f** correction was saved as manual but the prior inferred neighboring frames remained frozen.
- Whenever an **f** anchor is added inside an active **b/e** interval, invalidates the old non-manual interpolation and reconstructs each subinterval using all boundary and manual anchors.
- Preserves all existing manual anchors and leaves every frame outside **b...e** unchanged.
- Applies the fix to both the single-worm DIC and anterior-neuron/body reviewers.
- Applies the same all-anchor rule to RGBCaMP Fiji manual midlines: old neighbor-filled spines are invalidated whenever another manual midline is added, then all subintervals are rebuilt between the complete ordered manual/reference anchor set.
- Marks every pBoc outline anchor as authoritative manual geometry so all supplied calibration anchors participate in temporal reconstruction.

## Installation

- This is an application-only update. Existing NIKE installations can install it through **Help > Check for updates**; no runtime reinstall is required.
