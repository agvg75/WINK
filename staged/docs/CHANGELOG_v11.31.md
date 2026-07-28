# NIKE 11.31

Includes all NIKE 11.30 performance, navigation, and RGBCaMP audit/correction improvements.

## Stable AFD spine and length

- The neuronal tracker now arc-length-resamples and gently smooths the pixel skeleton before using it as the worm midline.
- A linear endpoint correction keeps both measured body ends fixed, so smoothing does not silently shorten the worm.
- Nose placement, body length, and the displayed review spine now use the same smooth centerline.
- Synthetic validation retained curved shape and endpoints: a 128.16 px curve measured 136.98 px as a jagged pixel spine and 128.14 px after smoothing.
