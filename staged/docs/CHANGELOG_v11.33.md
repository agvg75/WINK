# NIKE 11.33

## Population Swimming performance

- Adds optional original-resolution, 50% detection-proxy, and 25% detection-proxy modes.
- All proxy coordinates, body areas, spines, speeds, and physical measurements are restored to source scale before export.
- Adds optional image-size-adaptive temporal-background sampling; a 4K original-resolution run uses 14 rather than 31 background frames.
- Writes `timing_report.json` with background, detection/spine, linking/summary, export, and total processing durations.
- A folder containing separate movie files is rejected with a clear instruction to select one movie; numbered-image folders remain supported.

At 50%, geometry processing receives one quarter of the pixels. At 25%, it receives one sixteenth. Video decoding remains full resolution, so actual end-to-end improvement depends on codec and network speed. Original-resolution mode remains the comparison control.
