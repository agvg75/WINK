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

| You want to measure | Grinder (px) | To score it PRESENT | To COUNT it |
|---|---|---|---|
| Pharyngeal pumping rate | 8 | 15 fps | **30 fps** |

**30 fps is also the maximum every camera in this lab can do.** So pumping is
filmed at the ceiling, with no margin, and there is no "comfortable" setting
to reach for — a 150 ms pump spans 4.5 frames at 30 fps and that is as good
as the hardware gets. If you need more margin the answer is a faster camera,
not a different setting.

An earlier version of this page listed 40 fps as comfortable. **That was
impossible on our rigs** and the checker warned about it on every recording,
which is worse than not warning at all.

**Between 15 and 30 fps you can still see pumping, you just cannot count it.**
Below 30 the pumps merge or fall between frames and the rate comes out too
low — which does not look like a failure, it looks like a slow worm. So a
recording in that band is reported as *present but not countable*, and
because defecation and crawling are often filmed below 30, that category is
expected to be common. It is a limit of the camera, not a fault in the
analysis.

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
| Defecation / pBoc | crawl | **1 fps, 10 px** | Duration-bound, not frame-rate bound — needs *minutes*, several 50 s cycles. Oblique light required |
| Pharyngeal pumping | — | **30 fps** | Event-duration floor, see the section above. Frames the head, so no body-length floor. Oblique light required |

---

## Oblique illumination — required for pumping and defecation

**Light the plate from one side, not from directly beneath.** The animal
should show a bright edge where the light strikes it and a **shadow cast to
the opposite side**. This is deliberate technique, chosen because it gives the
contrast that makes the grinder and the gut readable. It is not a quirk of one
rig on one day.

The checker measures it and reports the direction:

```
PASS  Oblique illumination present, shadow below (94deg)
      consistency 0.86, contrast 66 counts.
```

**Any consistent direction is fine.** What matters is that there *is* one.
Measured across the pezo-1 CRISPR archive the shadow falls below the animal in
five recordings of six, and below-right in the other — both perfectly usable.
The check tests for a consistent shadow, not for a particular bearing.

**If the checker reports no directional shadow**, the plate is probably lit
from below or diffusely. Move the light off-axis and re-run the ten-second
clip.

> **The one exception.** An animal **immersed in an OP50 lawn** rather than
> lying on top of it casts little shadow even under correct lighting. If the
> checker fails this and the animal is down in the lawn, **record that** — it
> is a property of the preparation, not a lighting fault, and relighting will
> not change it. The analysis does not depend on the shadow; it detects the
> animal by its cuticle texture, which the lawn lacks. The check exists so
> that genuinely flat lighting is caught at the scope rather than at analysis.

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


---

## Turn on per-frame timestamps, if your camera has them

**This costs nothing at capture and settles a question that cannot be
answered afterwards.**

Most scientific cameras can stamp each frame with the time it was actually
taken — Basler calls it a hardware timestamp, and it goes into the file with
the image. When that is on, a recording **tells you its own frame rate**, and
nobody has to remember, type, or infer one.

When it is off, the frame rate has to be recovered from whatever is left:

| what survives | how good it is |
|---|---|
| a per-frame timestamp | **exact.** Also shows dropped frames |
| a number written in a notebook | fine, if the notebook is found |
| file modification times | a proposal. Some copy operations rewrite them |
| nothing | absolute-time measures are unsupported. Not approximated — unsupported |

Measured on Naga's Basler series: 3,676 frames with no embedded timestamps,
so the interval had to be estimated from file mtimes at 33.0 ms. That
estimate is good — it agrees end to end across 121 s — but it is an estimate,
and it would not have survived a copy that rewrote the mtimes.

**Why it matters beyond convenience.** With per-frame timestamps, a decay
constant or a time-to-peak is fitted against **when the frames actually
happened** rather than frame index times a nominal interval. Those two agree
until a frame is dropped, and then they disagree silently — the fit shifts and
nothing looks wrong. A recording with a dropped frame and no timestamps
reports a decay that is simply a little fast.

Irregular frame timing is then reported as an **acquisition finding**, naming
the frame and the size of the gap, rather than averaged into an interval.

**One switch, once per rig. Future data then describes itself.**
