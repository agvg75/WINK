# NIKE 11.30

## Faster neuronal tracking

- Camera registration now downsamples source pixels before float conversion, avoiding repeated full-resolution 4K float temporaries.
- After the initial manual seed establishes worm length, body segmentation uses a moving local work box centered on the previous soma. Coordinates remain in the selected-frame coordinate system and exports remain full-frame after crop restoration.
- The local box extends beyond a full worm length so the near-head neuron does not truncate the posterior body.
- Existing selected-frame virtual stacks, frame ranges, and persistent progress reporting remain active.

## Review navigation

- AFD neuronal review adds a frame slider and exact source-frame jump dialog.
- The same reusable navigation behavior is applied to DIC single-worm review.
- A recording in which the neuron leaves the field can be bounded before analysis; for the reported movie, end the included range at source frame 294.

## RGBCaMP audit trail

- Every new RGBCaMP CSV export also writes `<recording>_review_rois.zip`.
- The ROI ZIP contains a named body polygon and head-to-tail midline for every accepted frame, positioned on the original ImageJ stack.
- Filling the polygon recreates the exact accepted binary mask without the multi-gigabyte cost of a 4K binary TIFF stack.
- Legacy CSVs cannot reconstruct exact masks because they contain no absolute midline, edge, width, or translation coordinates.
- A prior ROI ZIP can now be loaded over its original stack as a correction session. Individual body outlines and midlines can be redrawn and exported under a new filename without repeating the whole review.
- CSV exports include a per-frame correction note, preserving whether geometry was imported or manually corrected.
- Camera-registered temporal-background construction now caches sampled frames and adapts the number of samples to image size, removing hundreds of millions of redundant frame lookups on large recordings.

## Cross-tool performance propagation

- DIC single-worm camera registration now downsamples before converting to floating point, matching the AFD memory optimization.
- Streaming and crop-first tools (population swimming/orientation, basal slowing, pharyngeal pumping, and morphology) were retained as-is because they already avoid loading a full-resolution movie into float memory.
