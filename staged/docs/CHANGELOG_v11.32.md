# NIKE 11.32

## Optional performance controls

- AFD: optional low-resolution registration proxy, moving worm-local segmentation, and image-size-adaptive background sampling.
- DIC single-worm: optional registration proxy and adaptive background sampling.
- Fiji RGBCaMP: optional adaptive temporal-background sampling.
- These options accelerate geometry processing only. Fluorescence, coordinates, segmentation output, and exported measurements remain based on original-resolution pixels.

## Comparable timing reports

- Each completed analysis writes a sibling `*_timing.json` file.
- Reports preserve the source, selected crop/frame count where available, enabled options, and phase durations.
- Processing time is separated from wall-clock time including manual review, allowing meaningful on/off comparisons.
- Timed phases include movie loading, camera registration, background construction, tracking/reconstruction, and measurement/export where applicable.

## How to compare

Run the same recording and ranges twice, changing only one performance checkbox. Compare the matching phase and `processing_total_excluding_manual_review_s`; also compare QC flags and geometry before adopting the faster setting as a default.
