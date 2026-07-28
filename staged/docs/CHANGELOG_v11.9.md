# NIKE application v11.9

- Routine application-only updates no longer require reinstalling Python, Fiji,
  Java, or scientific libraries. A stale runtime-zero marker is repaired from
  the installed release information.
- The v11.9 manifest deliberately requires runtime 0.0.0 because it adds no new
  third-party dependency. This lets the existing v11.7/v11.8 updater bootstrap
  the correction.
- Kinematics analysis now loads transmitted-light Track one worm exports using
  a dedicated schema. It no longer asks crawling data for RGBCaMP fluorescence
  columns.
- The mechanosensation window now launches Track one worm for movies or image
  sequences, accepts the reviewed tracking CSV, derives signed body-length
  velocity, and aligns trials to independently declared stimulus times.
- Population-tap crowded-plate tracking remains Experimental and is explicitly
  distinguished from the reviewed single-worm route.
