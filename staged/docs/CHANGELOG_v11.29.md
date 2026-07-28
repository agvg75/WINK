# NIKE 11.29

## Neuronal tracker control and visibility

- The virtual-stack notice now says the selection is valid and explains why disk backing is being used. It no longer describes a valid rectangle as simply “too large.”
- A movie navigator supports one or more disjoint included ranges before decoding and tracking.
- Skipped intervals retain their original source-frame numbers and elapsed time. They are not concatenated into false continuous time.
- Each new included range requires a fresh soma and body-outline seed, so tracking never jumps blindly across an omitted artifact interval.
- CSV output includes the original `frame`, original `time_s`, sequential `analyzed_frame_index`, and `source_gap_before` provenance.
- The optional supervised segmentation workbench is available before tracking. Threshold/range recipes affect worm-body geometry only; neuronal photometry continues to use original source pixels.
- A persistent progress window reports phase, frame count, percentage, and elapsed time during selected-frame decoding, camera registration, and tracking. It supports safe cancellation and progress saving.

## Shared infrastructure

- `frame_range_selector.py` provides reusable disjoint-range navigation for compatible movie tools.
- Disk-backed virtual stacks can store only selected source frames while preserving their source-index mapping.
