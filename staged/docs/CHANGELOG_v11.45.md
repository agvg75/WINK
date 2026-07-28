# NIKE Lab Tools v11.45

- Population Swimming uses decoder-ready 8-bit grayscale frames directly instead of repeating per-frame percentile normalization.
- On `vid_0023.mp4`, processing fell from 116.06 to 83.07 seconds (28.4% faster).
- The controlled outputs retained 12,054 detections, 26 tracks, identical frame/track assignments, and identical centroid coordinates.
- The robust evenly sampled two-pass background remains the default.
- Local proxy caching, low-resolution background, selective background piping, and initial-segment single-pass background remain opt-in experiments because they did not improve this controlled movie or changed candidate segmentation.
- Track review adds **Lock good + rescue rest**. Approved trajectories are saved exactly, detections near them are suppressed in the optional rescue pass, and parent/method/locked-track provenance is recorded.
- Choosing not to run the alternate rescue keeps the locked files for continued manual review without altering the robust result.
