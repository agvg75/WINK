# NIKE 11.22

## Population swimming review and frequency correction

- The include/exclude ROI editor can now scroll through the complete movie
  using a frame slider, arrow buttons, or the keyboard arrow keys.
- The trajectory reviewer can stitch two non-overlapping fragments after the
  user inspects their time gap and endpoint distance. The latest stitch can be
  undone. Automatic tracks remain untouched and the reviewed tracks plus a
  JSON edit history are saved separately.
- Swimming frequency is now measured primarily from signed lateral centroid
  displacement around the slowly varying trajectory. This fixes severe
  underestimation when a track is good but spine extraction is sparse.
- Spine-curvature frequency remains available as a diagnostic and fallback.
- The review window begins with a compact descriptive summary of track counts,
  QC flags, duration, and the frequency distribution.
