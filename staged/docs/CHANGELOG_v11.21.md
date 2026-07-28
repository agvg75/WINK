# NIKE application v11.21

## Supervised DIC segmentation workbench

- Adds an opt-in, preview-first segmentation workbench for single-worm DIC tracking.
- Supports global, local-adaptive, and space-time thresholding; dark, bright, and intensity-band polarity; gray, local-contrast, and temporal-background-difference features.
- Supports inclusive frame-range recipes, localized space-time threshold ROIs, morphological closing, hole filling, and minimum-object-area filtering.
- Adds exact source-frame navigation using Previous/Next, arrow keys, and a Jump-to-frame dialog without loading the complete recording into memory.
- Allows the workbench to be summoned from the tracker with **g**. It runs in an isolated GUI process, then reloads the accepted map and retracks automatically.

## Identity and camera continuity

- Distinguishes alignable whole-frame camera motion from unalignable clip/reposition changes.
- Applies opt-in camera compensation to the previous centroid and mask before choosing the next object.
- Adds opt-in previous-mask overlap so the tracker requests review instead of switching to spatially separate bacteria or a newly arriving worm.
- Clears temporal identity state at genuine clip boundaries.

## Compatibility and validation

- Keeps the original DIC detector unchanged when no accepted segmentation map is present.
- Keeps RGBCaMP on its existing Fiji/manual-midline default; supervised DIC maps remain blocked by the photometry firewall.
- Validated on a 561-frame real DIC sequence: QC flags decreased from 476 to 1 after reviewed range settings; the remaining final frame correctly required a one-sided manual decision.
- Adds regression coverage for range serialization, overlap rejection, camera translation, hard cuts, camera-compensated masks, and rejection of a spatially separate newcomer.
- Updates the definitive NIKE manual with the complete workbench workflow, exact-frame controls, escalation ladder, range semantics, QC interpretation, provenance requirements, and honest-failure guidance.

## Installation

- This is an application-only update. Existing NIKE installations can install it through **Help > Check for updates**; no runtime reinstall is required.
