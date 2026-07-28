# NIKE 11.23

## Population swimming: crossing continuity and Ready status

- Population Swimming + Modality Review is promoted from Experimental to
  Ready while retaining visual review and QC safeguards.
- During crossings, outgoing detections are scored by projected position,
  heading continuity, and speed continuity rather than proximity alone.
- When two worms form one collision-like component, both last-clean incoming
  trajectories are retained for up to 45 frames. Emerging worms are assigned
  to the most natural continuation of those trajectories.
- Nearly equal alternatives remain explicitly marked as ambiguous.
- Manual stitch and undo remain available for genuinely unresolved cases.
- The opening window can analyze an inclusive start/end frame interval instead
  of requiring the complete movie. Saved frame numbers retain their original
  movie coordinates.

This release also contains the NIKE 11.22 population improvements: full-movie
ROI navigation, descriptive run summaries, saved stitch histories, and the
centroid-oscillation frequency correction.
