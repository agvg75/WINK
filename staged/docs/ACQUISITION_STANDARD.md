# Acquisition standard — filming worms so the analysis can work

Print this and keep it at the scope. Every number below is a **floor for the
measurement to mean anything**, not a target for a good recording.

**Before the experiment, film ten seconds at the settings you plan to use and
run the checker.** It answers per measurement, and names what to change:

```
python check_acquisition.py "D:\test_clip" --fps 30 --assay crawling
```

---

## The two rules that decide everything

**1. The animal must be big enough in PIXELS.** Not in micrometres — in
pixels. Zoom in until it is.

**2. The frame rate must be several times the body wave.** A crawling animal
undulates at about **0.5 Hz**; a swimming one at about **2 Hz**. Four samples
per undulation is the practical floor.

> **Nyquist is not good enough.** An archived magnetotaxis recording sampled
> the wave at exactly 2.0 times per cycle — textbook Nyquist — and the
> trajectories came out a random walk. Turning angle sat at 70–95° where
> uncorrelated is 90°, and *rose* toward 90° as the sampling interval
> lengthened. Neither per-frame linking nor smoothing fixed it. **There is no
> analysis that recovers an aliased body wave.** Re-film or lose the data.

---

## What each measurement needs

| You want to measure | Animal (px) | Samples per undulation | Crawl (0.5 Hz) | Swim (2 Hz) | Needs midline |
|---|---|---|---|---|---|
| Position and dispersal | 5 | — | 1 fps | 4 fps | no |
| Speed and distance travelled | 10 | 2 | 1 fps | 4 fps | no |
| **Direction of travel** | **20** | **4** | **2 fps** | **8 fps** | no |
| Turning rate and reorientation | 25 | 6 | 3 fps | 12 fps | no |
| Body orientation relative to a stimulus | 40 | 6 | 3 fps | 12 fps | **yes** |
| Body curvature and bend depth | 60 | 8 | 4 fps | 16 fps | **yes** |
| Omega turns and escape manoeuvres | 60 | 10 | 5 fps | 20 fps | **yes** |

The names in the first column are the ones the checker prints, so a `FAIL`
line points straight at a row here.

### Pharyngeal pumping is a different kind of measurement

| You want to measure | Grinder (px) | Floor | Comfortable |
|---|---|---|---|
| Pharyngeal pumping rate | 8 | **30 fps** | 40 fps |

**Do not compute this one from the undulation rule.** Everything above is a
waveform, and four samples per cycle reconstructs it. A pump is not a
waveform — it is a discrete event lasting about **150 ms**, and the job is to
count individual pumps without merging or missing them.

Applying the waveform rule to a 4–5 Hz pump rate gives 16–20 fps, and it is
wrong. At 20 fps a pump spans 3 frames; a pump falling between frames is not
dimmed, it is **absent**. At 30 fps it spans 4.5 frames and survives both a
dropped frame and a pump landing anywhere in the cycle.

The checker reports **frames per pump event**, not a bare pass, so a recording
that scrapes the floor looks different from one with room to spare. An
undercount here does not look like a failure — it looks like a low pump rate,
which is exactly how a bad recording becomes a fake result.

Pumping frames the **head**, not the whole animal, so the body-length floors
above do not apply. The spatial requirement is that the grinder itself is
resolved. The checker will not infer grinder size from body length; if it
isn't measured, it says so rather than guessing.

Read down to the *last* row you need and use that line. The floors are
cumulative — turning also needs everything speed needs.

**"Needs midline" means centroids are not enough.** An animal can point one
way and travel another; during a reversal it always does. A midline needs the
body several pixels wide, not just long, and it needs the animals *separable*
— a pile cannot be segmented at any frame rate.

### Setting the frame rate honestly

Film **well above** the floor when you can. The floors assume the animals
behave as expected; a worm that swims faster than 2 Hz, or a recording that
drifts out of focus halfway, eats the margin you did not leave. If the camera
trades frame rate against frame size, spend the pixels on the animal first —
a fast recording of animals too small to measure is worth nothing.

---

## Per assay, at a glance

| Assay | Gait | Floor | Notes |
|---|---|---|---|
| Basal slowing / population centroid | crawl | **2 fps, 20 px** | Centroids only; no midline needed |
| Crawling kinematics | crawl | **4 fps, 60 px** | Curvature needs the midline |
| Swimming / population modality | swim | **20 fps, 60 px** | 2 Hz undulation — five times the crawl floor |
| Magnetotaxis / orientation | crawl | **3 fps, 40 px** | Body orientation ≠ direction of travel |
| Foraging / nose tracking | crawl | **3 fps, 25 px** | |

---

## The rest of the recording

- **Calibrate the scale** on the day, with the stage micrometer, at the
  magnification you are actually using. Do not carry a number from last week
  or from another scope. Speed and frequency are both *linear* in the scale
  and frame rate, so a value wrong by 4× makes every reported number wrong by
  4×, silently and consistently.
- **Do not let the camera clip.** A saturated pixel has lost the value it was
  meant to carry and nothing restores it. Check the histogram, not the
  preview.
- **Use the sensor range.** A frame sitting in the bottom few percent of the
  range is not a dim recording to be brightened later — there is nothing in it
  to brighten. Raise exposure, gain, or illumination *at the scope*.
- **Even illumination.** A brightness gradient across the plate becomes a
  position-dependent bias in every intensity measurement.
- **Focus once and leave it.** A recording that drifts out of focus partway
  cannot be salvaged for anything shape-based.
- **Record uncompressed, or losslessly.** Lossy compression invents edges,
  and edges are what the segmentation measures.
- **Write down what you did.** Frame rate, magnification, scale, exposure,
  temperature, time since food, strain, and age. Several of these can *reverse
  the sign* of an orientation result, not merely add noise.

---

## If the checker fails

It tells you which measurement fails and what to change, in the units of the
microscope — "magnify until the scale is 19 µm/px or finer", "film at 16 fps
or faster". Fix it and re-run the ten-second clip. **This costs minutes now
and saves an experiment later.**

The one failure it cannot help with: if the animals cannot be told apart
because they are piled up or the plate is crowded, no setting fixes it. Fewer
animals per plate.

---

*Requirements come from `app/acquisition_check.py`; per-assay profiles from
`app/acquisition_advisor.py`. If a tool's needs change, they change there and
this table follows.*
