# NIKE application v11.12

- Added a mandatory moving-distractor preflight to pBoc analysis.
- Students can scrub the recording, draw a segmented centerline through each
  non-target worm at its first clear frame, and declare its last visible frame.
- Each distractor is tracked as a moving episode; it is not treated as a static
  region of the image. A worm that disappears and re-enters uses a new episode.
- Moving distractor masks are excluded from target segmentation.
- If a distractor is lost, or its mask approaches/contacts the target, affected
  target frames are marked unusable and cannot generate measurements.
- The visual reviewer draws distractors in magenta/pink, labels their episode
  identities, reports their tracked fractions, and states target identity
  warnings at affected frames.
- Saved annotation JSON and tracking summaries preserve the distractor episodes
  and their correction/identity evidence for reproducibility and failure reports.
