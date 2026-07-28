# NIKE 11.39

## Plan a recording

- The Lab Tools hub now includes a shared `Plan a recording` advisor.
- Assay profiles cover Population Swimming, single-worm kinematics, AFD, RGBCaMP, pharyngeal pumping, population centroid/basal slowing, egg laying, and nonstriated muscle morphology.
- Each profile states the smallest required biological feature in pixels, recommended frame-rate floor, intensity/file-format requirement, and which operations may safely use a proxy.
- Geometry-only assays may trade surplus spatial resolution for speed; quantitative fluorescence tools retain lossless high-bit-depth measurement pixels while allowing navigation/registration proxies.
- Population Swimming consumes the shared profile for its automatic resolution/frame-rate explanation.
- Floors are explicitly labeled conservative and provisional pending assay-specific technical validation.

## Decoder-side proxy

Includes NIKE 11.38 direct FFmpeg grayscale/downsampling: approximately 12x less decoder-pipe data at 50% and 48x less at 25%, with source timing and coordinates preserved.
