# NIKE application v11.11

- pBoc initialization now requires a head click, tail click, and complete-worm
  outline. The outline establishes authoritative length and area references.
- PBOC-specific component scoring penalizes wrong-sized objects and rejects
  grossly incomplete or oversized bodies without changing the general Track one
  worm defaults.
- Tail proximity is checked against the outlined centerline endpoints.
- Incomplete bodies are marked unusable and cannot silently support events.
- Added **Tracking wrong: reseed full worm and rerun** to the pBoc reviewer.
- Reanalysis archives an existing review when candidate frames change; previous
  decisions cannot silently transfer onto new detections.
- Fixed event navigation sometimes returning the image display to frame zero.
