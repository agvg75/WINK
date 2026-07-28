# NIKE application v11.10

- Automated pBoc detections now begin as pending candidates and cannot silently
  enter biological rhythm calculations.
- Added full-sequence playback, frame and event navigation, synchronized
  `score_z`, unusable-frame shading, tracking overlays, event details, keyboard
  shortcuts, and independent overlay controls.
- Reviewers can accept, reject, restore pending status, add missed events, move
  peaks, add/move/clear recovery, annotate events, and delete manual additions.
- Original automatic frames and human-reviewed frames remain separate.
- Reviews save atomically as versioned JSON and reopen without losing decisions.
- Finalization uses only accepted reviewed peak frames and refuses statistics
  for pending candidates, invalid recovery order, insufficient accepted events,
  or interrupted tracking.
- New scans retain compressed mask-outline and centerline overlays. Dense
  optical-flow vectors are not retained.
