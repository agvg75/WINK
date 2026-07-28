# NIKE 11.24

## Resumable review and metric-neutral workflow improvements

### Population Swimming

- Track review now has **Save progress** and autosaves accept/reject, stitch,
  and undo actions.
- **Resume existing results review** restores reviewed tracks, decisions, ROIs,
  frame range, and stitch history without rerunning detection.

### Shared track-derived assays

Swimming Fatigue, Longitudinal Decline, Area-restricted Search,
Roaming/Dwelling, Quiescence, and Burrowing now share:

- optional start/end time controls when the input contains `time_s`;
- a descriptive banner above the review plot showing row and identity counts,
  selected time coverage, and assay-relevant medians/ranges;
- saved selected-range provenance in the reviewed JSON.

### Single-worm Swimming

- Optional start/end frame selection was added before analysis.
- The completion summary states the analyzed source-frame interval.
- No-range defaults produce numerically identical metrics to explicitly
  selecting the complete recording.

### Basal Slowing

- Starting-drop and lawn ROI windows can navigate the entire recording using
  the slider, arrow buttons, or keyboard arrow keys.

These changes do not replace assay-specific segmentation, frequency,
fatigue, state, posture, amplitude, or locomotion definitions.
