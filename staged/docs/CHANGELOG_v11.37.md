# NIKE 11.37

## Fast shared ROI movie navigation

- The shared ROI editor displays a navigation proxy no larger than 960 pixels on its longest side.
- The displayed axes remain in original source-pixel coordinates, so saved oval, rectangle, polygon, line, and full-frame ROIs map exactly back to the original movie.
- Slider input is debounced by 90 ms: dragging across a long movie decodes the frame where the user pauses rather than every intermediate slider value.
- The most recent 12 preview frames are cached for rapid back-and-forth inspection.
- Analysis and measurement resolution are unchanged; downsampling applies only to the interactive navigation display.
- This automatically propagates to Population Swimming, Basal Slowing, morphology, AFD, DIC, and future tools using the shared ROI editor. Tools without movie scrolling receive the same coordinate-preserving display proxy but no decoding overhead change.
