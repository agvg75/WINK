# NIKE 11.25

## AFD neuronal tracker: bounded-memory 4K movie loading

- The tracker asks the user to draw a rectangular working region around the
  worm and its expected movement before loading the complete movie.
- Only that region is decoded into the tracking array, preventing full-frame
  `float32` allocations of 10 GiB or more.
- Soma, nose, and body-centroid coordinates exported to CSV are translated
  back into full source-frame coordinates. Crop offsets are also recorded.
- Registered background estimation uses 31 distributed frames instead of
  constructing another registered copy of every movie frame.
- Oversized working regions are refused with an estimated-memory explanation.

Validation used `VID_0001.mp4` (333 decoded frames at 3840 × 2160). A 400 × 300
working region loaded in 152 MiB and complete tracker initialization used
approximately 305 MiB across its principal arrays.
