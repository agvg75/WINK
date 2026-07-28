# NIKE 11.41

## Optional one-decode Population Swimming path

- `Single-pass moving-worm background` buffers a short initial proxy interval, builds a 90th-percentile background for dark moving worms, and continues analysis from the same FFmpeg stream.
- This removes the separate whole-movie background decode when the short interval represents the arena adequately.
- The existing evenly sampled two-pass median remains available by unchecking the option and is preferable when illumination changes substantially or worms remain stationary during the initial interval.
- Timing reports record `single_pass_background` so the two strategies can be compared on the same recording.

## ROI remains optional

- Selecting Include/Exclude without drawing an ROI no longer produces a dead-end requirement.
- NIKE offers to switch to `none` and analyze the full frame, or lets the user return and draw the intended ROI.
