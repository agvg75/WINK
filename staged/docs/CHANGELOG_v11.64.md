# NIKE Lab Tools v11.64

## Population basal slowing

- Fixed the crash where some source types could fail with:
  `numpy.ndarray object has no attribute parent`.
- The basal slowing detector now looks for reviewed segmentation settings using
  the original loaded source path instead of assuming the first decoded frame is
  a filesystem object.
- Status remains **Ready** in the Lab Tools hub.

## Carried forward

- v11.63 defecation source intake: TIFF stacks, movie files, still images, and
  image folders are accepted and converted to a reusable frame cache.
- v11.62 pharyngeal pumping editable ellipse ROI.
- Hub version label in the Lab Tools hub.
