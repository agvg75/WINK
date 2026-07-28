# NIKE 11.34

Includes the Population Swimming proxy, adaptive-background, timing, and movie-folder safeguards described in NIKE 11.33.

## Measurement-aware recommendation

- `Auto: lowest safe resolution` is now the Population Swimming default.
- NIKE uses source dimensions and the configured accepted-object area range to choose the smallest proxy expected to retain enough pixels for object and spine detection.
- Before analysis it explains the selected percentage, estimated typical object area in proxy pixels, and when to rerun one level higher.
- The advisor states the temporal requirement: this detector measures frequencies up to 5 Hz and therefore retains at least 20 fps. Source timestamps remain authoritative.
- Original, 50%, and 25% modes remain explicit overrides for controlled timing and QC comparisons.
