# Pharyngeal Pumping

This tool follows the lab's interval-based scoring rule. It does not claim to
measure frames in which pumping cannot be seen.

## Workflow

1. Choose one frame from a numbered pumping sequence, or choose a folder that
   contains exactly one recording.
2. Confirm the frame rate.
3. Use the frame slider to find a stretch where the pharynx is visible and the
   head is relatively still.
4. Set START and END around only that usable stretch.
5. Draw a close oval around the terminal bulb/pharynx.
6. Analyze the approved interval.
7. Review the motion trace and adjust the detection-threshold slider.
8. Close the trace window and choose whether to save the reviewed result.

## Output

The CSV records the approved interval, frame rate, pump count, pumping rate,
median interpump interval, and the time and signal value of every reviewed
pump.

## Recording guidance

- Prefer 25 to 40 frames per second.
- Record at least 30 seconds when possible.
- Keep the pharynx and grinder in focus.
- Use only intervals where individual pumps are visually discernible.
- Do not extend the interval through head movement, loss of focus, or
  obstruction merely to obtain a longer measurement.

The automatic mode tracks the oval through the complete recording, rejects
frames with excessive motion, weak tracking, poor focus, or insufficient
contrast, and detects pumping only inside the remaining usable segments.

This is a new detector and must be validated against manual counts before it is
used as an unattended or publication-grade measurement.
