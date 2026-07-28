# NIKE Lab Tools v11.46

- Population Swimming detects sparse, scene-spanning component crops before detailed skeletonization.
- Pathological crops are skipped and recorded as `pathological_sparse_bounding_box` in `spine_skip_reason`.
- Ordinary worm components retain the same spine algorithm and measurements.
- Missing masks and components without a valid skeleton path also receive explicit diagnostic reasons.
