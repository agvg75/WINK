# Defecation Cycle Analysis

Status: **Ready**. The tool detects candidate posterior body contractions
(pBoc) and keeps a required human review step before events are counted.

## Workflow

1. Choose one folder containing a single numbered TIFF sequence.
2. Enter the declared frame rate.
3. Set the plausible minimum and maximum cycle period. Defaults are 30 and
   90 seconds.
4. Click the head and then the tail of the intended worm.
5. Run the analysis.
6. Review every proposed event and every cadence warning.

## Detection principle

The tool separates motion parallel to the worm centerline from dorsoventral
motion. A candidate pBoc contains posterior axial motion toward the head,
followed by reverse motion during recovery, without equivalent anterior axial
motion. Untrimmed body length is retained as a secondary diagnostic.

## Cadence review

Closely spaced candidates are brought forward for inspection. Long gaps prompt
inspection for a missed candidate. These settings only order human attention.
They never accept, reject, count, or establish a biological period.

The alpha never reports period, IDI, IDI CV, or another rhythm statistic.
Those outputs remain unavailable until unbroken tracking spans at least ten
manually accepted cycles.

## Validation status

The method reproduced two manually labeled pBoc events from one worm and found
a cadence-consistent candidate series in the complete recording. Ready status
means the workflow is available for supervised student use with review/QC; it
does not remove the requirement to validate new genotypes, imaging conditions,
and scorers.
