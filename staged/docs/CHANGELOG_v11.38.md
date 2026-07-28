# NIKE 11.38

## Decoder-side Population Swimming proxy

- FFmpeg now performs grayscale conversion and spatial downsampling before frames enter Python.
- A 3840x2160 RGB frame previously transferred about 24.9 MB through the decoder pipe before Python discarded color and resized it.
- At the recommended 50% proxy, NIKE now receives a 1920x1080 one-channel frame, about 2.1 MB: approximately 12x less decoder-pipe data.
- At 25%, the reduction is approximately 48x.
- Source frame indices, timestamps, coordinate restoration, area restoration, and physical-unit calculations are unchanged.
- Background construction and tracking show separate progress phases and use sequential streaming rather than repeated random MP4 seeks.
- Non-video TIFF/image inputs retain their existing reader behavior.

Validated with a local MP4 through the complete background, fast-pass detection, linking, selective-spine, summary, and timing-report pipeline.
