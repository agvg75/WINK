# NIKE 11.26

## Cross-tool bounded-memory audit

Following the AFD 4K allocation failure, all student-facing movie tools were
audited for full-stack array construction.

- **DIC single-worm tracker:** recordings whose full `float32` array would
  exceed 2 GB now request a working rectangle before loading. Exported segment,
  head, tail, and centroid coordinates are restored to full-frame coordinates;
  crop offsets are recorded and included in saved-session identity.
- **Single-channel GCaMP:** complete extraction is restricted to a bounding
  region covering all manually sampled target positions plus a search margin.
  Exported target coordinates are restored to the source frame.
- **Supervised segmentation review:** the distributed reference sample is
  dynamically limited to a 512 MiB memory budget instead of always retaining
  as many as 81 full-resolution color frames.

The AFD and DIC bounded loaders were both validated against the 333-frame,
3840 × 2160 `VID_0001.mp4`; a 400 × 300 crop used 152.4 MiB.

Population Swimming and Basal Slowing already stream frames and retain only
small distributed background samples. pBoc feasibility processing is explicitly
downsampled and stride-controlled. Those metric paths were therefore unchanged.
