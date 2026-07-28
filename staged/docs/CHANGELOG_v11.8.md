# NIKE application v11.8

- pBoc and shared numbered-image tools now accept TIFF, PNG, JPEG, BMP, PGM,
  PPM, PNM, and WebP through one natural-order loader.
- JPEG and WebP are marked lossy. Geometry and motion are allowed; quantitative
  intensity use is refused.
- Added an on-demand supervised segmentation review with synchronized good/bad
  previews, global and local-adaptive modes, blended space-time ROIs, numeric
  readouts, explicit Accept + Lock, blinding reminder, and saved provenance.
- Accepted maps can define extent/detection for Track one worm, pBoc,
  population swimming, basal slowing, population orientation, endpoint egg
  counting, and dynamic egg laying. Without a compatible accepted map, original
  behavior is unchanged.
- RGBCaMP and other fluorescence-intensity tools are hard-excluded. Pharyngeal
  pumping remains unchanged because its threshold detects events rather than
  spatial extent.
- The Fiji kinematics extractor retains its existing manual outline and
  midline review; its native Fiji segmentation has not been replaced by the
  Python map.
