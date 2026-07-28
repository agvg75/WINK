# NIKE application v11.13

- Population swimming now accepts MP4, AVI, MOV, MKV, WebM and M4V movies,
  multipage TIFF stacks, and folders of common sequential image formats.
- The launcher provides separate **Movie / stack** and **Image folder** choices.
- A movie, stack, or folder loaded in the Lab Hub is passed directly into the
  population-swimming tool.
- Compressed movies are decoded sequentially in two linear passes: one samples
  the background and one performs analysis. The complete movie is not loaded
  into memory and frames are not repeatedly decoded from the beginning.
- Movie-file results are saved beside the input as
  `<movie_name>_population_swimming_results`.
- Analysis metadata records the original input source, source kind, and actual
  number of decoded frames.
- Replaced a pandas-version-sensitive group operation in step-distance
  calculation with an index-stable grouped difference.
