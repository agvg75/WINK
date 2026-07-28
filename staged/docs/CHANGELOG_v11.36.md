# NIKE 11.36

## wrMTrck-style staged Population Swimming analysis

- The default fast first pass measures every frame using binary components, centroids, areas, ellipse axes/orientations, and trajectory linking.
- Component masks are compactly bit-packed while linking; the tool does not retain full-frame masks.
- Detailed ordered spines and curvature are then calculated only for plausible tracks at a sampling rate of at least 15 samples/s.
- Centroid and ellipse measurements retain the full source temporal sampling and source timestamps.
- `Fast wrMTrck-style first pass` can be unchecked to restore full spine extraction on every accepted object in every frame.
- Timing reports record whether staged processing was enabled, the detailed-spine stride, and time spent in the selective spine phase.

The design follows wrMTrck's efficient use of thresholded particles and fitted ellipse measurements while retaining NIKE's trajectory-continuity, collision review, ordered-spine, curvature, and modality analysis where those add information.
