# Imaging intake and load audit v11.4

Audit scope: every registered Python imaging workbench, checked for acquisition
constants accepted as zero/blank and rejected only after expensive work, and
for avoidable whole-recording loads or duplicate full-size arrays.

## Corrected

- Track one worm: positive scale before load; one preallocated float32 movie;
  bounded parallel decoding for independent image files.
- Neuron tracker: positive scale and exposure before load; no zero-scale
  internal default; preallocated source movie; bounded parallel sequence
  decoding; acquisition columns in the export.
- Single-channel GCaMP: constants validate before I/O; feasibility reads only
  the declared sample; the complete recording loads only after a pass and an
  explicit extraction request; full load is preallocated.
- Dynamic egg laying direct API: scale validation precedes division and movie
  opening.

## Reviewed; no equivalent defect found

- Population orientation validates first, keeps a bounded background sample,
  and streams analysis frames.
- Population swimming and basal slowing validate before detection, keep
  bounded background samples, and process frames sequentially.
- Pharyngeal pumping indexes folders asynchronously, reads display frames on
  demand, and stacks only the approved ROI crop interval.
- Egg counting, pharynx morphometry, and nonstriated morphometry load one
  selected frame for setup and review.
- Movie probe reads metadata/one probe frame. Convert for Fiji streams frames
  directly to the derivative.
- Table-driven analysis workbenches do not load movies.

## Deliberate boundaries

Python reduces application and conversion overhead but cannot eliminate disk,
SMB, decompression, or per-file-open latency. Thousands of separate images on a
network share can remain much slower than a contiguous local movie or TIFF.
Use a local SSD working copy for analysis when practical; preserve the original
and reviewed outputs together in provenance.

The shared `Movie.to_array()` method is guarded and refuses unbounded arrays
above its hard size threshold. No audited workbench uses it for an unbounded
production load.
