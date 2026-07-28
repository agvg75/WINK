# NIKE Lab Tools v11.70

## Track one worm — faster review scrubbing and a resizable window

- **Faster scrolling.** The review window now updates the displayed frame with
  `set_data` instead of clearing and rebuilding the whole plot every step, so
  moving frame-to-frame (and dragging the slider) is much more responsive.
- **Faster jumps.** `Page Down` / `Page Up` (or `Shift`+`Right` / `Left`) move
  **±10 frames**; `Home` / `End` jump to the first / last frame. Single arrows
  still step one frame.
- **Window fits the screen.** The review window opens at a screen-clamped,
  non-maximized size and is centered, so its minimize/maximize/close buttons are
  always reachable (previously it could open oversized/zoomed and be hard to
  resize, including after pressing `f`).

No tracking or measurement logic changed — this is display/navigation only.
