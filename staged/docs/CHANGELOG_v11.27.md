# NIKE 11.27

## Disk-backed virtual stacks for large recordings

- AFD neuronal tracking and DIC single-worm tracking no longer refuse a broad
  working region merely because its in-memory `float32` stack would exceed 2 GB.
- Large selections are decoded once, sequentially, into a temporary disk-backed
  stack using the source's compact integer depth. Frames remain numpy-indexable
  while RAM use stays bounded.
- The temporary cache is removed when tracking closes and an exit cleanup is
  registered for ordinary application termination.
- Crop selection remains available as a speed and disk-space optimization, not
  a requirement for successful analysis.
- Camera registration operates on bounded-resolution views. Registered
  background sample counts obey a 256 MiB working budget.

Real-movie benchmark (`VID_0001.mp4`, 333 decoded frames, source 3840 × 2160):

- a 1500 × 1200 selection would require about 2.2 GiB as `float32`;
- the disk-backed `uint8` stack used approximately 572 MiB of temporary disk;
- sequential cache construction completed in 79.3 s;
- complete AFD tracker initialization completed in a further 49.7 s;
- no full time-series array was allocated in RAM.

This release also formalizes the NIKE cross-tool propagation policy: reusable
features and unintended failure fixes require an applicability audit across all
tools, while assay-specific metrics retain a scientific firewall.
