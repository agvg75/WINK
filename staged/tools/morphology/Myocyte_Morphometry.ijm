// ============================================================================
//  Myocyte_Morphometry.ijm   [VERSION 2026-07-10e]
//  Per-myocyte morphometry for C. elegans body-wall muscle, replicating the
//  Biology Open (Fazyl et al. 2026) measurement set.
//
//  For: Vidal-Gadea lab.  Ella: day-5 dys-1(eg33) vs N2, same metrics as the
//  swimming/crawling paper, measured on selected Lightning-deconvolved confocal
//  sections (single sarcomere layer per myocyte; see WormAtlas MusFIG10).
//
//  CHANGELOG since 2026-07-10d:
//   - Added "Retry with different parameters" to the wave detection review
//     dialog, alongside Accept and Correct individually. Real workflow gap
//     found in use: adjusting parameters only ever affected the NEXT
//     myocyte measured, with no way to test new numbers against the one
//     just measured, and no way to discard a bad automatic pass before it
//     got written. Retry re-opens the parameter dialog and immediately
//     re-classifies the SAME myocyte with the new numbers; nothing is
//     written to the CSV until Accept is chosen, so a bad first attempt
//     never ends up stored alongside a corrected one, there is nothing to
//     store until the operator is satisfied. Choosing Correct
//     individually now also loops back to this same review dialog
//     afterward (rather than finalizing immediately), so corrections and
//     parameter retries can be freely combined in any order.
//   - detectWaves() now strips only ITS OWN overlay items between retries
//     (tracked via Overlay.size at entry, removed with
//     Overlay.removeSelection()), so re-classifying with new parameters
//     does not also erase the sarcomere tick overlay drawn earlier for
//     the same myocyte.
//
//  CHANGELOG since 2026-07-10c:
//   - Wave detection is now a 3-way call (straight/wavy/low-confidence),
//     not forced binary. traceFiberAlong() now also checks, at every
//     step, whether the search window shows a genuine SECOND local peak
//     nearly as bright as the one being followed, a real signature of a
//     split (one fiber forking in two) or an oblique branch to a
//     neighbor, distinct from ordinary noise. A fiber whose traced steps
//     are ambiguous often enough (WAVE_AMBIG_THRESH, a new adjustable
//     parameter) is flagged low-confidence (yellow overlay) instead of
//     being forced into a wavy or straight guess. Splitting/branching
//     classification itself remains out of scope, that is a separate,
//     harder tool this lab is still developing; this only recognizes
//     that the ambiguity exists rather than silently guessing through it.
//   - Added interactive correction: after automatic classification, a
//     dialog reports the count in each category and offers "Correct
//     individual fibers by clicking." If chosen, click near any fiber's
//     overlay line and pick its correct label (Straight/Wavy/Low
//     confidence); the corrected fiber is redrawn in its new color
//     (re-tracing is deterministic, so it lands exactly on the same path,
//     cleanly covering the old color), and repeats until nothing is
//     selected on OK. Final CSV values are computed from the corrected
//     classifications, not the automatic ones, if any were changed. Same
//     interaction pattern as "Edit ticks" on the sarcomere side.
//   - New CSV column wave_n_lowconf (count of low-confidence fibers per
//     myocyte); present as a zero placeholder on blind-recount rows,
//     which don't run wave detection.
//
//  CHANGELOG since 2026-07-10b:
//   - Fixed a real, visually-confirmed false-positive mechanism: the fiber
//     tracer's search radius (from WAVE_LINK_UM) had no awareness of how
//     close together the real fibers in a given myocyte actually are. On
//     a real image, MinFeret/sarc_number implied adjacent fibers roughly
//     1.5 um apart while the search radius was 1.4 um, nearly the whole
//     gap, so the tracer regularly snapped onto the neighboring fiber,
//     producing a fake zigzag from hopping between two individually
//     straight fibers rather than a real wave. detectWaves() now computes
//     the real minimum gap between THIS myocyte's actual adjacent fibers
//     directly from zpos (already the true detected positions) and caps
//     the search radius at 35% of that gap, so it can never reach a
//     neighbor regardless of the WAVE_LINK_UM dial setting.
//
//  CHANGELOG since 2026-07-10a:
//   - Fixed a second real crash from the same live test session: fiber 0
//     of a myocyte traced and classified correctly (confirming the prior
//     NaN/string fix worked), but fiber 1 crashed with "No selection" in
//     Roi.contains(). Cause: drawing each fiber's overlay
//     (makeSelection("polyline",...) then Select None) replaces and then
//     clears the active selection, which also destroys the myocyte
//     boundary Roi.contains() needs for the NEXT fiber's trace. Fixed by
//     capturing the boundary's ROI Manager index once and re-selecting it
//     at the start of every fiber iteration in detectWaves(), rather than
//     assuming the selection survives across iterations.
//
//  CHANGELOG since 2026-07-09d:
//   - Fixed a real crash caught on first live Fiji test of wave detection:
//     classifyFiberWavy()'s return statement built its comma-joined string
//     starting from a bare number (anyWavy+","+wavyLenUm) instead of
//     anchoring it with a leading empty string the way intervalStats()
//     already does elsewhere in this file (""+nint+","+mean+...). Under
//     some condition this produced a bare NaN instead of a proper two-part
//     string, so splitting it on the caller's side found only one part and
//     crashed trying to read the second. Fixed to match the established,
//     working pattern, plus explicit isNaN guards on both values before
//     they're ever formatted, regardless of what upstream condition
//     produced the NaN in the first place.
//
//  CHANGELOG since 2026-07-09d (wave detection):
//   - Added fiber waviness detection, for quantifying dystrophic muscle
//     damage (broken/detached actin fibers picking up tension through
//     sarcomere branches, producing a characteristic zigzag). Developed
//     and calibrated offline against real hand-marked images (a dystrophic
//     sample and a healthy N2 negative control) before being ported here;
//     see conversation history for the validation process. Reuses the
//     EXISTING per-myocyte ROI, band angle (mux/muy/nux/nuy), sampling
//     line, and Feret already computed for sarcomere detection, no
//     duplicate detection of any of it:
//       - Seeds one fiber trace per already-detected sarcomere band
//         position (zpos), traces each along the muscle's long axis
//         (traceFiberAlong), classifies it (classifyFiberWavy: local
//         slope sign-change rate x magnitude, in a sliding window, both
//         calibrated in real microns so behavior does not depend on
//         pixel size), and aggregates into two damage measures per
//         myocyte (detectWaves):
//           width fraction  = fraction of fibers (across MinFeret) with
//                              a wave anywhere along them
//           length fraction = for affected fibers, how much of the
//                              myocyte's own Feret their wave covers
//                              (mean and max across affected fibers)
//     Both measures are comparative, matching the lab's approach to the
//     other proxy columns, not absolute damage measurements.
//   - Four parameters (smoothing, link distance, scoring window,
//     classification threshold) are exposed via a new main-menu option,
//     "Adjust wave detection parameters," rather than fixed constants,
//     since each was shown by direct testing to meaningfully trade
//     sensitivity against specificity and a student may need to retune
//     them for different staining, magnification, or muscle region, the
//     same way pixel size already must be re-entered per session. True
//     continuous live-preview (dragging a slider and watching the overlay
//     update) was considered and deliberately not built, classic ImageJ
//     macro dialogs are not well suited to that, and adjust-numbers-then-
//     re-measure was judged to get the job done without the added
//     engineering risk.
//   - Five new CSV columns: wave_n_fibers, wave_n_affected,
//     wave_width_fraction, wave_length_frac_mean, wave_length_frac_max.
//     Present (as zero placeholders) on blind-recount rows too, which
//     don't run wave detection, so column count stays consistent across
//     all row types.
//   - Draws a simple per-fiber overlay (red = wavy somewhere along it,
//     blue = clean) alongside the existing sarcomere tick overlay, for a
//     quick visual sanity check. This is coarser than the per-segment
//     coloring used during offline calibration; a finer overlay and a
//     manual add/remove/correct step (mirroring "Edit ticks" on the
//     sarcomere side) are reasonable future additions once this has seen
//     real use, deliberately left out of this first version to keep it
//     reviewable.
//   - Known limitation carried over from calibration: even after fixing a
//     tracer coverage bug (link distance too tight to follow genuinely
//     wavy fibers, which change direction faster than straight ones) and
//     a calibration bug (smoothing was a fixed pixel count rather than a
//     real distance, so it behaved differently on images with a different
//     um/px), the healthy negative control still read 33% wavy at the
//     chosen default settings, not the near-zero a clean negative should
//     show. Real, useful separation from the dystrophic sample was still
//     observed at every setting tried, but treat absolute wave numbers
//     as comparative between conditions imaged the same way, not as a
//     validated absolute damage measurement, the same caveat already
//     applied to the contractile proxy columns.
//
//  CHANGELOG since 2026-07-09b:
//   - Added "Blind hand recount of last sarcomere line" to the main menu,
//     for hand-vs-AUTO validation studies (this lab's own, and reusable by
//     future users doing their own). Reuses the EXACT boundary and line
//     from the last myocyte measured, rather than requiring a fresh trace,
//     since the line's position and angle both derive from the traced ROI
//     and a redrawn boundary could shift the line even if it looks the
//     same, confounding a hand-vs-AUTO comparison with a hand-vs-hand-trace
//     difference. Shows only the reference line (no detected ticks) and
//     uses the existing manualClicks() to get a genuinely independent,
//     blind count, not a correction of the AUTO result. Written to a new
//     row with sarc_mode=MANUAL_RECOUNT, carrying the same (unchanged)
//     geometry as the original row, and a new linked_myocyte_id column
//     that references the original row's myocyte_id so pairing for
//     analysis is unambiguous regardless of whether myocyte_number was
//     identified.
//
//  CHANGELOG since 2026-07-09a:
//   - Fixed a real syntax error introduced in initCsvIfNeeded(): used the
//     C/Java/JavaScript ternary operator (`cond ? a : b`), which ImageJ
//     macro does not support at all. Caught immediately when the macro
//     failed to run. Replaced with a plain if/else assignment. Checked the
//     rest of the file for the same class of mistake (ternaries, ===,
//     let/const, array literals, template strings); nothing else found.
//
//  CHANGELOG since 2026-07-08k:
//   - CSV filename now built from session metadata (genotype/BLINDED, day,
//     region, worm id, date) instead of only a timestamp, e.g.
//     myocyte_morphometry_BLINDED_day5_midbody_007_20260709_093708.csv.
//     Filename is finalized after the FIRST perImageMeta() call in a
//     session (moved out of setup(), where none of this was known yet);
//     changing worm/region metadata mid-session does not rename or split
//     the file, later rows just carry their own correct values as before,
//     only the filename reflects the session's starting identity. If BLIND
//     is on, the filename uses BLINDED, same as the CSV column, so it
//     cannot leak the answer the operator was never shown.
//   - Added an "Edit ticks" option alongside Accept/Manual/Skip in the
//     sarcomere veto dialog. Starts the multi-point tool PRE-LOADED with
//     the detected tick positions (new editDetectedTicks(), reusing
//     ImageJ's own point-tool gestures: drag to move, Alt/Option-click to
//     delete, click empty space to add), instead of requiring either full
//     acceptance or redoing all points from scratch by hand. Accept,
//     Manual, and Skip are unchanged.
//
//  CHANGELOG since 2026-07-08j:
//   - Real test data (4 repeats on one location, 3 on another, still with
//     the known-wrong um_px=0.01389) confirmed the relative-detection
//     redesign is working as intended: peak counts were stable (9,8,7,7 on
//     the cleaner location; 3,5,6 on a harder, lower-contrast one) and
//     unaffected by the wrong calibration, exactly the goal.
//   - Found the calib_flag floor (0.4 um) was set too low: some rows from
//     the SAME confirmed 3.85x calibration error (0.49-0.59 um) landed just
//     above it and were marked OK, while others from the identical error
//     (0.22-0.33 um) correctly tripped it. Raised the floor to 0.8 um so
//     the same error is caught consistently rather than only partially.
//
//  CHANGELOG since 2026-07-08i:
//   - Root cause found for persistent under-detection on Ella's images:
//     confirmed via a real image's own scale bar that a session used
//     um_px=0.01389 when the true value was 0.0535, a 3.85x error. Every
//     absolute, calibration-derived threshold in detection shifted with
//     it, with no way for the code to notice.
//   - Redesigned detection to be RELATIVE rather than absolute: detectBandPeaks
//     now estimates the expected spacing from the profile's OWN data (see
//     estimatePeriodPx, pixels only, no um/px involved) and uses that to set
//     minimum spacing and spacing-consistency, instead of converting a fixed
//     micron target through um/px. Detection itself is now unaffected by
//     whether calibration is right or wrong; only the final reported LENGTH
//     changes, and that is now sanity-checked separately (see below) rather
//     than being allowed to silently distort which peaks get accepted.
//   - Replaced bestPeriodHarmonic (the autocorrelation cross-check) with
//     estimatePeriodPx for the same reason, and fixed a real bug found in
//     the process: searching for the raw maximum of autocorrelation over a
//     window that includes small lags almost always returns a trivial,
//     meaningless "period" near 0, since autocorrelation is inherently high
//     there regardless of real periodicity. Now only genuine local maxima
//     are considered, starting well past that trivial region.
//   - Added a calib_flag CSV column and a live dialog warning: if the
//     detected length falls far outside any plausible sarcomere size
//     (well outside 1.2-2.5 um, deliberately loose), it is flagged
//     CHECK_CALIBRATION rather than silently reported as a normal value.
//     This is a sanity check on the OUTPUT, not a filter on detection.
//   - Diagnostic profile export (2026-07-08i) now reports the data-driven
//     period estimate instead of the removed absolute minimum spacing.
//   - Caution found while doing this: the test profiles I'd selected earlier
//     today via a "best periodicity" search had the SAME short-lag bug,
//     meaning some of today's earlier offline comparisons may not have been
//     against genuinely clean reference data. Flagging this rather than
//     quietly leaving it.
//
//  CHANGELOG since 2026-07-08h:
//   - Added a diagnostic export: every time a sarcomere line is measured
//     (n>=8 profile), the exact raw profile array getProfile() returned,
//     the detected peak indices, um/px, band width, and line endpoints are
//     written to <worm>_m<n>_profile.txt in the rois folder. This exists
//     because offline reconstruction of a line's profile from the image
//     alone kept disagreeing with Fiji's real output, most likely because
//     getProfile() samples perpendicular to the line's true angle with
//     interpolation, which a manual approximation from outside cannot
//     exactly reproduce. This writes what the macro itself actually used,
//     so real discrepancies can be diagnosed directly instead of guessed at.
//
//  CHANGELOG since 2026-07-08g:
//   - REVERTED both detectBandPeaks() smoothing (07-08f/g) and the getProfile
//     band-averaging width bw (changed to scale with um/px, also from 07-08,
//     but never clearly called out as a change when made, that's on me)
//     back to the ORIGINAL fixed values from 2026-06-25b: 3-point smoothing,
//     bw=15 px flat. Direct side-by-side testing in Fiji on the same real
//     myocyte showed the original placing 5 ticks correctly on real fibers,
//     while today's scaled/capped version collapsed to 1 tick on the same
//     cell. Three separate changes to this same detection pathway in one
//     day, each looking justified from offline pixel analysis and each
//     needing a further patch, means this pathway needs real in-Fiji
//     testing before being touched again, not another offline-reasoned
//     adjustment. Sarcomere detection in this version is back to exactly
//     what 2026-06-25b did.
//
//  CHANGELOG since 2026-07-08f:
//   - detectBandPeaks() smoothing half-width now hard-capped at 10% of the
//     profile length, regardless of the calibration-derived value. Root
//     cause of the "only sees one peak" regression: the 2026-07-08f fix
//     scales smoothing to minSpacingPx, which itself depends on um/px being
//     correct. A stale or wrong pixel size (e.g. left over from a different
//     magnification session) inflates minSpacingPx and therefore the
//     smoothing window, which can exceed the whole profile length and
//     collapse a genuinely clean, evenly-spaced signal down to a single
//     peak. Confirmed directly: the same real profile that correctly gave
//     4 evenly-spaced peaks at the right calibration collapsed to 1 when
//     the calibration was off by roughly 6x. This cap does not fix a wrong
//     calibration, it just stops a wrong calibration from being able to
//     silently destroy detection entirely.
//   - Also fixed: detectBandPeaks() previously skipped its own spacing
//     sanity filter entirely whenever fewer than 2 peaks were found
//     (`if (pos.length<2) return pos`), meaning the least trustworthy case
//     got the least scrutiny. This still returns early (spacing filtering
//     needs at least 2 points to define a neighbor distance), but the
//     directly-following quality scoring in measureMyocyte() already grades
//     0 or 1 peaks as sarc_length_um=0, sarc_quality=LOW, so this case is
//     flagged rather than silently trusted; verify this still shows LOW/0
//     rather than a plausible-looking number if you see a lone peak again.
//
//  CHANGELOG since 2026-07-08e:
//   - detectBandPeaks() smoothing widened from a fixed 3-pixel average to a
//     window scaled to a fraction of the expected minimum sarcomere spacing.
//     Diagnosed directly from real phalloidin crops: dense-body dots inside
//     each actin fiber were creating spurious extra peaks under minimal
//     smoothing, causing overcounting and scattered tick positions instead
//     of one clean peak per fiber. Verified on two real test crops (one
//     with 5 countable fiber peaks, one with 8) that this widened window
//     recovers the correct, evenly-spaced peak count where the old fixed
//     window overcounted. The exact scaling constant is informed by that
//     test but not yet confirmed on a properly calibrated full-resolution
//     TIFF; re-check against a hand count before trusting broadly.
//
//  CHANGELOG since 2026-07-08d:
//   - The schematic WAS opening correctly all along; it was just ending up
//     behind the working image, because the auto-show step immediately
//     called selectWindow(MAINIMG) right after opening it, which brings the
//     working image back to front. Removed that immediate refocus.
//     measureMyocyte() already refocuses MAINIMG defensively right before
//     any measurement action, so this was redundant as well as the actual
//     cause of the schematic being hidden.
//
//  CHANGELOG since 2026-07-08c:
//   - REVERTED the bestPeriodHarmonic() "harmonic check" added on 2026-07-08.
//     It systematically doubled sarcomere spacing on genuinely periodic
//     signals, since a real periodic signal naturally shows a secondary
//     autocorrelation peak at 2x the true period, so the check fired on
//     essentially every clean case, not just the aliasing cases it was
//     meant to catch. Confirmed as a real regression on live data. Back to
//     the simple strongest-in-window peak, no harmonic override.
//   - bandNormalAngle()'s Roi.contains restriction (2026-07-08) is being
//     left in place for now, since the reported failure mode (systematic
//     doubling) is fully explained by the harmonic bug above; that
//     restriction is a smaller, separate change and has not itself been
//     shown to cause a problem. Re-test with just this revert first; if
//     sarcomere detection is still off, that change should be reverted too.
//   - Schematic path is now persisted via ij.Prefs after the first
//     successful pick (auto-detected or manually browsed), so it does not
//     need to be located again on the same machine even if the bundled-file
//     auto-detect (via macro.filepath) does not resolve, e.g. when running
//     from the Script Editor's Run button rather than an installed tool.
//
//  CHANGELOG since 2026-07-08b:
//   - Schematic now opens automatically ONCE per session, right after
//     setup, positioned at the top-left of the screen so it stays visible
//     alongside the working image instead of needing a manual menu click
//     every time. Still reachable manually afterward if closed.
//   - Companion schematic filename simplified to "myocyte schematic"
//     (.jpg/.jpeg/.png/.tif), matched exactly including the space.
//
//  CHANGELOG since 2026-07-08:
//   - Added per-myocyte identification (Myo01-Myo24), not just anterior/
//     midbody/posterior. Region for that row is derived from the number
//     when known (anterior 1-10, midbody 11-18, posterior 19-24), otherwise
//     falls back to the image-level region. New myocyte_number CSV column.
//   - Added an optional reference schematic viewer ("Show myocyte numbering
//     schematic" in the main menu) so a student can check which numbered
//     cell they are looking at. Path is asked once at setup, or on first
//     use if left blank.
//   - The macro now auto-detects a schematic bundled in its OWN folder
//     under the name myocyte schematic.jpg/.png/.tif, so anyone who
//     downloads the .ijm together with that file gets this working with no
//     setup step. Ship the two files together for distribution.
//   - measureMyocyte() now defensively refocuses the working image at the
//     start of every measurement, so leaving the schematic window active
//     cannot accidentally redirect a measurement onto it.
//
//  CHANGELOG since 2026-06-25b:
//   - bandNormalAngle() now restricted to Roi.contains pixels, not the full
//     bounding box, so background does not bias the band-orientation estimate
//     for thin, oblique cells.
//   - bestPeriodHarmonic() now actually performs the harmonic check the
//     original comment described (prefers 2x period when ac[2*best] is also
//     a clean local max), which previously did not run.
//   - roiManagerAdd() deselects before Save so the full worm ROI set is
//     written, not just the single most recently added ROI.
//   - Calibration: added USECAL global. When set, each image's own pixel
//     size is re-read at measurement time instead of being frozen from
//     whichever image was open during setup().
//   - BLIND mode now hides the genotype dropdown from perImageMeta entirely,
//     so the operator measuring cells never sees or enters it. Genotype must
//     be linked to WORMID afterward via a coded key kept outside this macro.
//   - WORMID is now comma-sanitized before being written to the CSV row.
//   - NOT YET VALIDATED against a control image with known values; test the
//     harmonic check and band-angle change against the tail image dataset
//     before trusting on new data.
//
//  WHAT IT MEASURES (per myocyte, matching the paper):
//    geometry  : area, perimeter, Feret (max diameter), MinFeret (min diameter),
//                major/minor ellipse axes, aspect_ratio, circularity, solidity,
//                anisotropy (Feret/MinFeret)            <- all from ImageJ Measure
//    sarcomere : sarc_number (your Z-line click count),
//                sarc_length_um (mean Z-to-Z), sd, cv
//    derived   : sarc_density (n/area), serial_density (n/Feret)
//
//  WORKFLOW per myocyte:
//    1. You draw the cell boundary (freehand/polygon). ImageJ computes all
//       geometry from that ROI (the validated, standard definitions; nothing is
//       re-implemented by hand).
//    2. You draw a straight line along the cell long axis, then click each
//       Z-line in order (multi-point). The macro records number and spacing.
//    3. One CSV row per myocyte is written and the ROI is saved to an ROI set
//       for audit / re-measurement.
//
//  Replication unit is the WORM. The CSV carries worm_id and region so the
//  downstream LMM (worm random intercept, condition*region, Kenward-Roger df,
//  IQR outlier removal) reproduces the paper's pipeline. The macro does NOT run
//  that model; per-myocyte summary values only.
//
//  Measurements are taken BLIND to genotype when blind mode is on.
// ============================================================================

var OUTDIR="";
var CSV="";
var CSVINIT=false;
var ROIDIR="";
var UMPX=0.1;
var USECAL=false;
var BLIND=true;
var GENOTYPE="unknown";
var WORMID="";
var REGION="midbody";
var DAY="5";
var myoCounter=0;
var REFIMG="";
var MAINIMG="";
var LASTMYON=0;
var SCHEMSHOWN=false;
// Cache of the last measured myocyte's sarcomere line and context, so a
// blind hand recount can reuse the exact same boundary and line without
// redrawing. See blindRecount().
var LASTLINE_VALID=false;
var LASTLINE_X1=0; var LASTLINE_Y1=0; var LASTLINE_X2=0; var LASTLINE_Y2=0;
var LASTLINE_IMGTITLE="";
var LASTLINE_WORMID=""; var LASTLINE_GTAG=""; var LASTLINE_DAY="";
var LASTLINE_REGION=""; var LASTLINE_MNSEL="";
var LASTLINE_AREA=0; var LASTLINE_PERIM=0; var LASTLINE_FERET=0; var LASTLINE_MINFER=0;
var LASTLINE_MAJOR=0; var LASTLINE_MINOR=0; var LASTLINE_AR=0; var LASTLINE_CIRC=0;
var LASTLINE_SOLID=0; var LASTLINE_ANISO=0; var LASTLINE_FANG=0;
var LASTLINE_FILLEN=0; var LASTLINE_SRCID=-1;

// ---------------------------------------------------------------------------
//  Fiber waviness detection (dystrophic muscle damage quantification)
// ---------------------------------------------------------------------------
// Adjustable, not fixed: these four were each shown, by direct testing
// against real marked-up images (both a dystrophic sample and a healthy N2
// negative control), to meaningfully trade sensitivity against specificity.
// A student working with different staining, magnification, or muscle
// region should expect to retune these against their own images, the same
// way pixel size already has to be re-entered per session.
var WAVE_SMOOTH_UM = 1.2;   // smooths out noise finer than this; real wave
                            // wavelength is ~5.6 um, so this must stay well
                            // below that or the real signal gets smoothed
                            // away too, not just noise (tested: sensitivity
                            // collapses well before 3 um)
var WAVE_LINK_UM = 1.4;     // how far a fiber's position may locally shift
                            // between trace steps before the tracer gives
                            // up on it; too small loses coverage of sharp
                            // waves (they shift faster than straight fibers
                            // by definition), too large starts jumping onto
                            // neighboring fibers
var WAVE_WINDOW_UM = 18.0;  // local length judged for periodicity; scoring
                            // a whole fiber with one number was confirmed
                            // to dilute real local waves against long
                            // straight stretches elsewhere on the same fiber
var WAVE_THRESH = 1.65;     // classification cutoff on the combined score
                            // (turns per um along the fiber x mean slope
                            // magnitude); found by sweeping against labeled
                            // wavy/straight examples, not guessed
var WAVE_AMBIG_THRESH = 0.15; // fraction of a fiber's traced steps that must
                            // show a genuine second, comparably-bright peak
                            // (a real split or branch point, not noise)
                            // before that fiber is flagged low-confidence
                            // instead of a forced wavy/straight guess
// last measurement's results, written to the CSV row
var WAVE_N_FIBERS=0; var WAVE_N_AFFECTED=0; var WAVE_N_LOWCONF=0;
var WAVE_WIDTH_FRAC=0; var WAVE_LEN_MEAN_FRAC=0; var WAVE_LEN_MAX_FRAC=0;
// scratch return values for traceFiberAlong()
var TRACE_X = newArray(0);
var TRACE_Y = newArray(0);
var TRACE_AMBIG = newArray(0);

macro "Myocyte Morphometry Action Tool - C000T0509MT5509YT9509O" { runTool(); }
runTool();

function runTool(){
    print("[Myocyte_Morphometry] version 2026-07-10e loaded");
    if (nImages==0){ showMessage("Open a myocyte image first."); return; }
    MAINIMG = getTitle();
    if (OUTDIR=="") setup();
    if (!SCHEMSHOWN){
        print("[Myocyte_Morphometry] schematic path before auto-show: '"+REFIMG+"'");
        showSchematic();
        SCHEMSHOWN=true;
        // deliberately NOT refocusing MAINIMG here: doing so immediately
        // buried the schematic behind the working image. measureMyocyte()
        // already refocuses MAINIMG defensively right before it is needed,
        // so it is safe to just leave the schematic visible in front here.
    }
    perImageMeta();
    initCsvIfNeeded();

    // make sure ImageJ measures everything we need
    run("Set Measurements...",
        "area mean shape feret's perimeter fit redirect=None decimal=4");

    keep=true;
    while (keep){
        Dialog.createNonBlocking("Myocyte Morphometry  -  "+WORMID+" ["+REGION+"]");
        items=newArray("Measure a myocyte",
                       "Blind hand recount of last sarcomere line (validation)",
                       "Adjust wave detection parameters",
                       "Show myocyte numbering schematic",
                       "Change worm / region metadata",
                       "Finish this image");
        Dialog.addRadioButtonGroup("Action",items,6,1,items[0]);
        Dialog.show();
        c=Dialog.getRadioButton();
        if (c==items[0]) measureMyocyte();
        else if (c==items[1]) blindRecount();
        else if (c==items[2]) adjustWaveParams();
        else if (c==items[3]) showSchematic();
        else if (c==items[4]) perImageMeta();
        else keep=false;
    }
    showStatus("Done. CSV: "+CSV);
}

// ---------------------------------------------------------------------------
function setup(){
    Dialog.create("Myocyte Morphometry - session setup");
    Dialog.addDirectory("Output folder", getDirectory("home"));
    Dialog.addNumber("Pixel size (um/px)",0.1,4,8,"um");
    Dialog.addCheckbox("Use image's own calibration if present",false);
    Dialog.addCheckbox("BLIND mode (hide genotype while measuring)",true);
    Dialog.addFile("Myocyte numbering schematic (optional)","");
    Dialog.show();
    OUTDIR=Dialog.getString();
    UMPX=Dialog.getNumber();
    USECAL=Dialog.getCheckbox();
    BLIND=Dialog.getCheckbox();
    REFIMG=Dialog.getString();
    if (REFIMG==""){
        REFIMG=call("ij.Prefs.get","myocyte_morph.refimg","");
        if (REFIMG=="" || !File.exists(REFIMG)) REFIMG=findBundledSchematic();
    }
    if (USECAL){ getPixelSize(u,pw,ph); if(pw>0) UMPX=pw; }
    if(!endsWith(OUTDIR,File.separator)) OUTDIR=OUTDIR+File.separator;
    ROIDIR=OUTDIR+"rois"+File.separator;
    File.makeDirectory(ROIDIR);
    // CSV filename and header are created in initCsvIfNeeded(), called after
    // the first perImageMeta(), so the filename can reflect strain/day/
    // region/worm id instead of only a timestamp. See that function.
}

// Sanitize a string for safe use inside a filename: keep letters, digits,
// hyphen, underscore, and period; replace everything else (spaces,
// parentheses, slashes, etc.) with underscore.
function sanitizeForFilename(s){
    out="";
    for (i=0; i<lengthOf(s); i++){
        ch=substring(s,i,i+1);
        if (matches(ch,"[A-Za-z0-9_.-]")) out=out+ch;
        else out=out+"_";
    }
    return out;
}
// yyyymmdd only, for the descriptive part of the CSV filename (tstamp()
// itself, with time included, is still used as a uniqueness suffix).
function dateOnly(){
    getDateAndTime(yr,mo,dw,dy,hr,mi,sc,ms);
    return ""+yr+IJ.pad(mo+1,2)+IJ.pad(dy,2);
}
// Build the CSV filename from session metadata (strain, day, region, worm
// id) instead of only a timestamp, then write its header. Runs once, after
// the FIRST perImageMeta() call, since that is the first point these
// values are known; guarded so later metadata changes mid-session (via
// "Change worm / region metadata") do not create a second file. If BLIND
// is on, genotype is written as BLINDED here too, same as in the CSV rows,
// so the filename itself cannot leak the answer the operator was never
// shown.
function initCsvIfNeeded(){
    if (CSVINIT) return;
    gtag = GENOTYPE;
    if (BLIND) gtag = "BLINDED";
    name = "myocyte_morphometry_"
        +sanitizeForFilename(gtag)+"_day"+sanitizeForFilename(DAY)+"_"
        +sanitizeForFilename(REGION)+"_"+sanitizeForFilename(WORMID)+"_"
        +dateOnly()+"_"+tstamp()+".csv";
    CSV=OUTDIR+name;
    f=File.open(CSV);
    print(f,"myocyte_id,worm_id,genotype,day,region,myocyte_number,um_px,"
        +"area_um2,perimeter_um,feret_um,minferet_um,major_um,minor_um,"
        +"aspect_ratio,circularity,solidity,anisotropy,"
        +"sarc_number,sarc_length_um,sarc_sd_um,sarc_cv,sarc_mode,sarc_quality,calib_flag,"
        +"sarc_density_per_um2,serial_density_per_um,"
        +"filament_length_um,sarc_parallel_proxy,sarc_series_proxy,contractile_content_proxy,"
        +"feret_angle_deg,roi_name,blind,timestamp,image_title,linked_myocyte_id,"
        +"wave_n_fibers,wave_n_affected,wave_n_lowconf,wave_width_fraction,wave_length_frac_mean,wave_length_frac_max");
    File.close(f);
    CSVINIT=true;
}

function perImageMeta(){
    Dialog.create("Worm / region metadata");
    Dialog.addString("Worm ID",WORMID,16);
    // In BLIND mode the genotype dropdown is not shown at all: the operator
    // measuring cells should not have to see or enter it. Genotype must then
    // be linked to WORMID afterward via a coded key kept outside this macro
    // by whoever assigned the worm IDs.
    if (!BLIND){
        g=newArray("N2","dys-1(eg33)","other","unknown");
        Dialog.addChoice("Genotype",g,GENOTYPE);
    }
    d=newArray("1","5","other");
    Dialog.addChoice("Adult day",d,DAY);
    r=newArray("anterior","midbody","posterior");
    Dialog.addChoice("Region",r,REGION);
    Dialog.show();
    WORMID=Dialog.getString();
    if (!BLIND) GENOTYPE=Dialog.getChoice();
    else GENOTYPE="unknown";
    DAY=Dialog.getChoice();
    REGION=Dialog.getChoice();
}

// ---------------------------------------------------------------------------
function measureMyocyte(){
    // guard against the schematic (or any other window) being left active
    if (MAINIMG!="" && isOpen(MAINIMG) && getTitle()!=MAINIMG) selectWindow(MAINIMG);

    // make sure calibration is applied so ImageJ returns microns directly
    setCalibration();

    // ---- 1. cell boundary ----
    setTool("polygon");
    waitForUser("Draw cell boundary",
        "Outline ONE myocyte (polygon or freehand). Close the ROI, then OK.\n"
      + "Tip: press 'f' to switch to freehand if you prefer.");
    if (selectionType()<0){ showMessage("No ROI. Skipped."); return; }

    // ImageJ computes the geometry (standard, validated definitions)
    run("Clear Results");
    run("Measure");
    area   = getResult("Area",0);
    perim  = getResult("Perim.",0);
    feret  = getResult("Feret",0);
    minfer = getResult("MinFeret",0);
    major  = getResult("Major",0);
    minor  = getResult("Minor",0);
    ar     = getResult("AR",0);
    circ   = getResult("Circ.",0);
    solid  = getResult("Solidity",0);
    fang   = getResult("FeretAngle",0);
    aniso  = 0; if (minfer>0) aniso = feret/minfer;

    // Which numbered myocyte (Myo01-Myo24) is this, per the body-wall
    // schematic? Falls back to the image-level region when not identifiable.
    mnSel = pickMyoNumber();
    curRegion = REGION;
    curLabel = REGION;
    if (mnSel!="unknown" && mnSel!="other"){
        curRegion = regionFromMyoNum(parseInt(mnSel));
        curLabel = "Myo"+IJ.pad(parseInt(mnSel),2);
    }

    // save the ROI for audit
    roiName = WORMID+"_"+curLabel+"_m"+myoCounter;
    roiManagerAdd(roiName);

    // ---- 2. sarcomeres: CORRECTED geometry for C. elegans oblique striation ----
    //   C. elegans body-wall muscle is NOT vertebrate-like. The long bright
    //   phalloidin tracks run ALONG the muscle long axis and are NOT one
    //   sarcomere long. The sarcomere repeat (dense body to dense body) is read
    //   ACROSS the bands, ~normal to the (slightly oblique, ~5.9deg) striations.
    //   Therefore:
    //     LENGTH  = spacing of the across-band intensity profile (this section)
    //     NUMBER  = count of bands crossed ALONG the cell long axis
    //   The script auto-detects band orientation from the image content in the
    //   ROI, proposes an ACROSS-band sampling line, and lets Ella veto it.
    sarcN=0; sarcMean=0; sarcSd=0; sarcCv=0; sarcQual="none"; sarcMode="none"; calibFlag="n/a";
    WAVE_N_FIBERS=0; WAVE_N_AFFECTED=0; WAVE_WIDTH_FRAC=0; WAVE_LEN_MEAN_FRAC=0; WAVE_LEN_MAX_FRAC=0;

    // bounding box + centroid of the current ROI (cell already selected)
    getSelectionBounds(rbx,rby,rbw,rbh);
    ccx = rbx + rbw/2;  ccy = rby + rbh/2;

    // detect band orientation: sample gradients inside the ROI box, build a
    // structure tensor; its principal (gradient) direction is the BAND-NORMAL
    // = the direction to sample ACROSS bands for sarcomere length.
    normAng = bandNormalAngle(rbx,rby,rbw,rbh);

    // Place the across-band sampling line at the WIDEST point of the (rhomboid)
    // cell so edge sarcomeres are not undercounted. March along the long axis
    // through the centroid; at each step measure how far the across-band line
    // stays inside the ROI; keep the position with the longest in-cell span.
    nux = cos(normAng); nuy = sin(normAng);          // across-band direction
    mux = -nuy;  muy = nux;                           // along-band (long axis)
    longSpan = maxOf(rbw,rbh);
    maxReach = 2*longSpan;
    bestT = 0; bestSpan = -1; bestPx = ccx; bestPy = ccy;
    for (t=-0.5*longSpan; t<=0.5*longSpan; t+=3){
        qx = ccx + t*mux;  qy = ccy + t*muy;
        // reach in +across and -across from this point while inside ROI
        rp=0; while (rp<maxReach && Roi.contains(round(qx+rp*nux), round(qy+rp*nuy))) rp++;
        rm=0; while (rm<maxReach && Roi.contains(round(qx-rm*nux), round(qy-rm*nuy))) rm++;
        sp = rp+rm;
        if (sp>bestSpan){ bestSpan=sp; bestT=t; bestPx=qx; bestPy=qy;
                          bestRp=rp; bestRm=rm; }
    }
    // build the across-band line spanning the full in-cell width at widest point
    ax1 = bestPx - bestRm*nux;  ay1 = bestPy - bestRm*nuy;
    ax2 = bestPx + bestRp*nux;  ay2 = bestPy + bestRp*nuy;
    // fallback if ROI marching found nothing (e.g. tiny ROI)
    if (bestSpan<6){
        sampLen = 0.8*minOf(rbw,rbh); if (sampLen<20) sampLen=minOf(rbw,rbh);
        ax1 = ccx - 0.5*sampLen*nux;  ay1 = ccy - 0.5*sampLen*nuy;
        ax2 = ccx + 0.5*sampLen*nux;  ay2 = ccy + 0.5*sampLen*nuy;
    }

    // show proposed line for veto
    Overlay.remove;
    makeLine(ax1,ay1,ax2,ay2); Overlay.addSelection("cyan",2);
    Overlay.show(); run("Select None");

    Dialog.createNonBlocking("Sarcomere sampling line");
    Dialog.addMessage("The cyan line samples ACROSS the bands (sarcomere length\n"
        + "direction), auto-oriented normal to the striations\n"
        + "(detected angle "+d2s((normAng*180/PI),0)+" deg).\n\n"
        + "Accept this line, draw your own across the bands, or skip.");
    so=newArray("Accept proposed line","Let me draw the across-band line","Skip sarcomeres");
    Dialog.addRadioButtonGroup("Sampling line",so,3,1,so[0]);
    Dialog.show();
    sc=Dialog.getRadioButton();

    haveLine=false;
    if (sc==so[0]){ haveLine=true; }
    else if (sc==so[1]){
        setTool("line");
        waitForUser("Draw across-band line",
            "Draw a WIDE line ACROSS the bands (perpendicular to the long bright\n"
          + "tracks, spanning several bands). Double-click the line tool to set\n"
          + "width ~10-20 px. Then OK.");
        if (selectionType()==5){ getLine(ax1,ay1,ax2,ay2,lw); haveLine=true; }
    }

    if (haveLine){
        bw = 15;                                   // band-average width (px)
        prof = getProfileBand(ax1,ay1,ax2,ay2,bw); // intensity across bands
        n = prof.length;
        if (n>=8){
            sLo = 1.2;  sHi = 2.5;                  // sarcomere window (um), now used
                                                     // only as a fallback/sanity check,
                                                     // not to shape detection itself

            // bright band centers = dense-body-associated actin peaks; spacing
            // between consecutive bright bands across the profile = sarcomere len.
            // Spacing consistency is judged RELATIVE to the profile's own
            // estimated period (see detectBandPeaks/estimatePeriodPx), not an
            // absolute calibrated target, so a wrong um/px cannot silently
            // corrupt which peaks get accepted.
            zpos = detectBandPeaks(prof, sLo, sHi);
            res = intervalStats(zpos);
            parts = split(res,",");
            lenN   = parseInt(parts[0]);
            lenMean= parseFloat(parts[1]);
            lenCv  = parseFloat(parts[3]);

            // Diagnostic export: the EXACT raw profile and detected peak
            // positions used for this measurement, written as plain text.
            // Added because offline reconstruction of this profile from the
            // image alone kept disagreeing with Fiji's real output, almost
            // certainly because getProfile() samples perpendicular to the
            // line's actual (possibly non-vertical) angle with proper
            // interpolation, which a manual approximation cannot replicate
            // exactly. This writes what the macro itself actually used.
            dbgName = ROIDIR+WORMID+"_m"+myoCounter+"_profile.txt";
            dbg = "line_endpoints_px: "+d2s(ax1,1)+","+d2s(ay1,1)+" to "+d2s(ax2,1)+","+d2s(ay2,1)+"\n";
            dbg = dbg+"um_px: "+d2s(UMPX,5)+"\n";
            dbg = dbg+"band_width_px: "+bw+"\n";
            dbg = dbg+"data_driven_period_px: "+d2s(LASTESTPERIOD,2)+"\n";
            peakStr = "";
            for (zi=0; zi<zpos.length; zi++){
                peakStr = peakStr+zpos[zi];
                if (zi<zpos.length-1) peakStr = peakStr+",";
            }
            dbg = dbg+"detected_peak_index: "+peakStr+"\n";
            dbg = dbg+"raw_profile:\n";
            profStr = "";
            for (pi=0; pi<prof.length; pi++){
                profStr = profStr+d2s(prof[pi],2);
                if (pi<prof.length-1) profStr = profStr+",";
            }
            dbg = dbg+profStr+"\n";
            File.saveString(dbg, dbgName);

            // cross-check via the same calibration-free period estimator
            det = detrend(prof, maxOf(6, round(n/10)));
            acPeriodPx = estimatePeriodPx(det);
            if (acPeriodPx<2) acPeriodPx = LASTESTPERIOD;  // fall back to detection's own estimate
            acLen = acPeriodPx*UMPX;

            if (lenN>=4 && lenCv<0.18) sarcQual="HIGH";
            else if (lenN>=3 && lenCv<0.30) sarcQual="MED";
            else sarcQual="LOW";

            // Calibration sanity flag: does the reported length land anywhere
            // near a plausible sarcomere length at all, GENEROUSLY defined
            // (well outside sLo/sHi, which is for quality not for this)? This
            // is deliberately loose, it exists only to catch a badly wrong
            // um/px, not to second-guess normal biological variation. Floor
            // raised from 0.4 to 0.8 after real test data: a confirmed 3.85x
            // calibration error produced lengths of 0.49-0.59 um in some
            // rows, which slipped past a 0.4 floor as "OK" while other rows
            // from the SAME wrong calibration (0.22-0.33 um) correctly
            // tripped it. 0.8 catches both without touching real biology.
            calibFlag = "OK";
            if (lenMean>0 && (lenMean<0.8 || lenMean>6.0)) calibFlag = "CHECK_CALIBRATION";

            sarcMean = lenMean;  sarcCv = lenCv;
            // sd from intervalStats
            sarcSd = parseFloat(parts[2]);

            // NUMBER and LENGTH both come from the SAME across-band line.
            // Number = bands the line crosses (= detected peaks). Length = their
            // spacing. The line is placed at the widest point of the rhomboid
            // cell (above) so edge bands are included and number is not
            // undercounted. zpos holds the across-band peak positions.
            sarcN = zpos.length;                   // bands crossed = sarcomere number

            // overlay detected across-band peaks (length) in image coords
            L=sqrt((ax2-ax1)*(ax2-ax1)+(ay2-ay1)*(ay2-ay1));
            ux=(ax2-ax1)/L; uy=(ay2-ay1)/L;
            Overlay.remove;
            makeLine(ax1,ay1,ax2,ay2); Overlay.addSelection("cyan",1);
            for (i=0;i<zpos.length;i++){
                zx=ax1+zpos[i]*ux; zy=ay1+zpos[i]*uy;
                tx1=zx-8*uy; ty1=zy+8*ux; tx2=zx+8*uy; ty2=zy-8*ux;
                makeLine(tx1,ty1,tx2,ty2); Overlay.addSelection("red",2);
            }
            Overlay.show(); run("Select None");

            Dialog.createNonBlocking("Sarcomere detection");
            calibNote = "";
            if (calibFlag!="OK") calibNote = "\n*** "+calibFlag+": this length is far outside any\n"
                + "plausible sarcomere size. Check your entered pixel size (um/px)\n"
                + "before trusting this measurement. ***\n";
            Dialog.addMessage("Sarcomere LENGTH (across bands, dense body to dense body):\n"
                + "   primary:     "+d2s(lenMean,3)+" um   ("+lenN+" intervals)\n"
                + "   cross-check: "+d2s(acLen,3)+" um\n"
                + "   quality: "+sarcQual+calibNote+"\n"
                + "Sarcomere NUMBER (bands across, at widest point): "+sarcN+"\n\n"
                + "Bio Open length range is ~1.4-1.9 um. Red ticks mark the bands.\n"
                + "If only a tick or two is wrong, use Edit ticks rather than\n"
                + "redoing the whole line. Accept, edit, override, or skip.");
            vo=newArray("Accept auto detection",
                        "Edit ticks: fix, add, or remove individual marks",
                        "Manual: I will click across the bands (start from scratch)",
                        "Skip sarcomeres for this cell");
            Dialog.addRadioButtonGroup("Choice",vo,4,1,vo[0]);
            Dialog.show();
            v=Dialog.getRadioButton();

            if (v==vo[0]){
                sarcMode="AUTO";
            } else if (v==vo[1]){
                editDetectedTicks(ax1,ay1,ax2,ay2,zpos);
                sarcMode="EDITED"; sarcQual="EDITED";
                sarcN=E_n; sarcMean=E_mean; sarcSd=E_sd; sarcCv=E_cv;
            } else if (v==vo[2]){
                manualClicks(ax1,ay1,ax2,ay2);
                sarcMode="MANUAL"; sarcQual="MANUAL";
                sarcN=M_n; sarcMean=M_mean; sarcSd=M_sd; sarcCv=M_cv;
            } else {
                sarcN=0; sarcMean=0; sarcSd=0; sarcCv=0; sarcMode="none";
            }
        }
    }

    // ---- 2b. filament length along the long axis + biomechanical proxies ----
    //   Distinct from Feret (cell outline caliper). This is the in-cell extent of
    //   the contractile tracks along the band direction. With the 5.9deg oblique
    //   striation the cos correction is <0.5% so we use the simple definitions.
    //   ALL three are COMPARATIVE PROXIES (same imaging), not absolute force.
    filLen = 0;
    if (sarcMode!="none" && roiManager("count")>0){
        // Roi.contains needs the cell ROI active; the across-band overlays cleared
        // the selection, so restore it first.
        roiManager("Select", roiManager("count")-1);
        // along-band direction (perpendicular to the across-band normal)
        fmux = -sin(normAng); fmuy = cos(normAng);
        fr=0; while (fr<3*longSpan && Roi.contains(round(ccx+fr*fmux), round(ccy+fr*fmuy))) fr++;
        fl=0; while (fl<3*longSpan && Roi.contains(round(ccx-fl*fmux), round(ccy-fl*fmuy))) fl++;
        filLen = (fr+fl)*UMPX;

        // Fiber waviness (dystrophic damage quantification). Reuses the
        // SAME ROI (still active from just above), band angle, sampling
        // line, and zpos (across-band peak positions, one per fiber) that
        // sarcomere detection already produced, no re-detection of any of
        // it. Only meaningful if sarcomeres were actually detected this
        // round (same guard as filLen above), since zpos and the line
        // endpoints are what seed each fiber trace.
        detectWaves(zpos, ax1, ay1, mux, muy, nux, nuy, feret);
    }
    sarcParallel = sarcN;                         // across-band count = force proxy
    sarcSeries = 0;                               // along-fiber count = shortening proxy
    if (sarcMean>0) sarcSeries = filLen/sarcMean;
    contentProxy = sarcParallel*sarcSeries;       // total contractile units proxy

    // ---- 3. derived densities ----
    sdens=0; if (area>0) sdens=sarcN/area;
    serial=0; if (feret>0) serial=sarcN/feret;

    // ---- 4. write row ----
    gtxt=GENOTYPE; if (BLIND) gtxt="BLINDED";
    File.append(
        myoCounter+","+cleanTitle(WORMID)+","+gtxt+","+DAY+","+curRegion+","+mnSel+","+d2s(UMPX,5)+","
        +d2s(area,4)+","+d2s(perim,4)+","+d2s(feret,4)+","+d2s(minfer,4)+","
        +d2s(major,4)+","+d2s(minor,4)+","+d2s(ar,4)+","+d2s(circ,4)+","
        +d2s(solid,4)+","+d2s(aniso,4)+","
        +sarcN+","+d2s(sarcMean,4)+","+d2s(sarcSd,4)+","+d2s(sarcCv,4)+","
        +sarcMode+","+sarcQual+","+calibFlag+","
        +d2s(sdens,6)+","+d2s(serial,6)+","
        +d2s(filLen,4)+","+sarcParallel+","+d2s(sarcSeries,3)+","+d2s(contentProxy,2)+","
        +d2s(fang,2)+","+roiName+","+BLIND+","+tstamp()+","+cleanTitle(getTitle())+","+""+","
        +WAVE_N_FIBERS+","+WAVE_N_AFFECTED+","+WAVE_N_LOWCONF+","+d2s(WAVE_WIDTH_FRAC,4)+","
        +d2s(WAVE_LEN_MEAN_FRAC,4)+","+d2s(WAVE_LEN_MAX_FRAC,4),
        CSV);

    // overlay a label so you can see which cells are done
    run("Restore Selection");
    Overlay.addSelection("cyan",2);
    getSelectionBounds(bx,by,bw,bh);
    lbl = curLabel+" (m"+myoCounter+")";
    if (sarcN>0) lbl = lbl+" n="+sarcN;
    Overlay.drawString(lbl, bx+bw/2, by+bh/2);
    Overlay.show();
    run("Select None");
    // Cache this line/context so a blind hand recount can be done later on
    // the EXACT same boundary and line, without redrawing, for validation
    // (this lab's own, and for future users doing their own sanity check).
    // Only cached when a real line was actually used for this myocyte.
    if (haveLine && sarcMode!="none"){
        LASTLINE_VALID=true;
        LASTLINE_X1=ax1; LASTLINE_Y1=ay1; LASTLINE_X2=ax2; LASTLINE_Y2=ay2;
        LASTLINE_IMGTITLE=getTitle();
        LASTLINE_WORMID=WORMID; LASTLINE_GTAG=gtxt; LASTLINE_DAY=DAY;
        LASTLINE_REGION=curRegion; LASTLINE_MNSEL=mnSel;
        LASTLINE_AREA=area; LASTLINE_PERIM=perim; LASTLINE_FERET=feret; LASTLINE_MINFER=minfer;
        LASTLINE_MAJOR=major; LASTLINE_MINOR=minor; LASTLINE_AR=ar; LASTLINE_CIRC=circ;
        LASTLINE_SOLID=solid; LASTLINE_ANISO=aniso; LASTLINE_FANG=fang;
        LASTLINE_FILLEN=filLen;
        LASTLINE_SRCID=myoCounter;   // links a recount row back to this original row
    }
    myoCounter++;
    showStatus("Myocyte "+myoCounter+" recorded.");
}

// ---------------------------------------------------------------------------
//  Sarcomere detection helpers
// ---------------------------------------------------------------------------
// Band profile: average intensity across a wide line. ImageJ's getProfile on a
// wide line already averages across the width, so we set the line and read it.
function getProfileBand(x1,y1,x2,y2,lw){
    makeLine(x1,y1,x2,y2,lw);
    p = getProfile();          // averaged across the band width
    run("Select None");
    return p;
}
// moving-mean detrend
function detrend(a,win){
    n=a.length; out=newArray(n);
    for (i=0;i<n;i++){
        s=0; c=0;
        for (j=maxOf(0,i-win); j<=minOf(n-1,i+win); j++){ s+=a[j]; c++; }
        out[i]=a[i]-s/c;
    }
    return out;
}
// normalised autocorrelation
function autocorr(a){
    n=a.length; out=newArray(n);
    z=0; for (i=0;i<n;i++) z+=a[i]*a[i];
    if (z<=0){ for(i=0;i<n;i++) out[i]=0; return out; }
    for (lag=0; lag<n; lag++){
        s=0; for (i=0;i<n-lag;i++) s+=a[i]*a[i+lag];
        out[lag]=s/z;
    }
    return out;
}
var LASTESTPERIOD = -1;   // last data-driven period estimate (px), for diagnostics
// Estimate the dominant spacing present in a profile from its OWN
// autocorrelation, in PIXELS, with NO dependency on calibration. Searches
// for the first genuine LOCAL MAXIMUM beyond a small minimum lag.
// This replaces an earlier version (bestPeriodHarmonic) that searched a
// calibration-derived [loPx,hiPx] window; that meant a wrong um/px value
// corrupted this estimate the same way it corrupted detection. Also fixes
// a real bug found 2026-07-08: taking the raw max over a window that
// INCLUDES small lags almost always returns a tiny, meaningless "period",
// since autocorrelation is trivially high near lag 0 regardless of whether
// real periodicity exists. Only genuine local maxima are considered here.
// Returns -1 if no clear local maximum is found (e.g. the signal really
// isn't periodic in this stretch).
function estimatePeriodPx(prof){
    n = prof.length;
    minLag = 5;                 // ignore trivial short-range self-similarity
    maxLag = floor(n/2);
    if (maxLag <= minLag+1) return -1;
    ac = autocorr(prof);
    best=-1; bestv=-1;
    for (lag=minLag; lag<=maxLag; lag++){
        if (ac[lag]>=ac[lag-1] && ac[lag]>ac[lag+1]){
            if (ac[lag]>bestv){ bestv=ac[lag]; best=lag; }
        }
    }
    if (best<1) return -1;
    // parabolic refine
    yl=ac[best-1]; y0=ac[best]; yrr=ac[best+1];
    den=(yl-2*y0+yrr);
    ref=best; if (den!=0) ref=best+0.5*(yl-yrr)/den;
    return ref;
}
// Detect the BAND-NORMAL angle (direction to sample ACROSS bands) from image
// content inside the ROI bounding box, via a structure tensor. The principal
// gradient direction is normal to the long bright tracks = the sarcomere-length
// sampling direction. Returns angle in radians.
function bandNormalAngle(bx,by,bw,bh){
    // sample on a coarse grid inside the box; accumulate gradient products
    step = maxOf(1, floor(minOf(bw,bh)/40));
    Jxx=0; Jyy=0; Jxy=0; cnt=0;
    x0=maxOf(1,bx); y0=maxOf(1,by);
    x1=minOf(getWidth()-2, bx+bw); y1=minOf(getHeight()-2, by+bh);
    for (yy=y0; yy<y1; yy+=step){
        for (xx=x0; xx<x1; xx+=step){
            if (!Roi.contains(xx,yy)) continue;  // skip background outside the polygon
            gx = (getPixel(xx+1,yy)-getPixel(xx-1,yy))/2;
            gy = (getPixel(xx,yy+1)-getPixel(xx,yy-1))/2;
            Jxx += gx*gx; Jyy += gy*gy; Jxy += gx*gy;
            cnt++;
        }
    }
    if (cnt==0) return PI/2;
    // principal direction of the structure tensor (gradient/band-normal)
    ang = 0.5*atan2(2*Jxy, Jxx-Jyy);
    return ang;
}
// Detect bright BAND centers along a profile (dense-body-associated actin
// peaks). Minimum spacing and spacing-consistency are now RELATIVE to a
// period estimated from the profile's OWN data (see estimatePeriodPx),
// not an absolute calibrated target. This is the direct fix for a real
// failure mode found 2026-07-08: with absolute calibrated thresholds, a
// wrong um/px value (confirmed: a session used 0.01389 when the image's
// own scale bar gave 0.0535, a 3.85x error) shifts every threshold with
// it, causing systematic under-detection with no way for the code to
// notice anything was wrong. Deriving spacing from the data itself means
// detection succeeds even when calibration is wrong; only the final
// reported LENGTH in microns is affected, and that gets sanity-checked
// separately against the biological window as a quality flag, not used
// to shape detection. loUm/hiUm are now used only as a fallback if the
// profile has no genuine periodicity of its own to measure.
function detectBandPeaks(prof, loUm, hiUm){
    n=prof.length;
    sm=newArray(n);
    for (i=0;i<n;i++){
        a=maxOf(0,i-1); b=minOf(n-1,i+1);
        sm[i]=(prof[a]+prof[i]+prof[b])/3;
    }

    estPeriod = estimatePeriodPx(sm);
    if (estPeriod<2){
        // No genuine periodicity found in the data itself. Fall back to
        // the calibrated biological midpoint so the function still
        // returns something usable, but this case is inherently less
        // trustworthy since it is not confirmed by the data.
        estPeriod = ((loUm+hiUm)/2)/UMPX;
    }
    LASTESTPERIOD = estPeriod;
    minSpacingPx = maxOf(2, round(0.6*estPeriod));

    // local maxima with enforced minimum separation, relative to the
    // profile's OWN estimated period, not an absolute calibrated target
    pos=newArray(0); last=-100000;
    for (i=1;i<n-1;i++){
        if (sm[i]>=sm[i-1] && sm[i]>sm[i+1]){
            if (i-last >= minSpacingPx){
                pos=Array.concat(pos,i); last=i;
            } else {
                if (pos.length>0 && sm[i] > sm[pos[pos.length-1]]){
                    pos[pos.length-1]=i; last=i;
                }
            }
        }
    }
    // keep peaks whose neighbour spacing is consistent with the SAME
    // data-driven period (relative), not an absolute calibrated um window
    if (pos.length<2) return pos;
    loRel=0.6*estPeriod; hiRel=1.5*estPeriod;
    keep=newArray(0);
    for (i=0;i<pos.length;i++){
        okL=false; okR=false;
        if (i>0){ d=pos[i]-pos[i-1]; if (d>=loRel && d<=hiRel) okL=true; }
        if (i<pos.length-1){ d=pos[i+1]-pos[i]; if (d>=loRel && d<=hiRel) okR=true; }
        if (okL || okR) keep=Array.concat(keep,pos[i]);
    }
    return keep;
}
// interval stats from refined positions (px) -> "n,mean_um,sd_um,cv"
function intervalStats(pos){
    if (pos.length<2) return "0,0,0,0";
    nint=pos.length-1; sum=0; ss=0;
    for (i=0;i<nint;i++){ d=(pos[i+1]-pos[i])*UMPX; sum+=d; ss+=d*d; }
    mean=sum/nint; sd=0;
    if (nint>1) sd=sqrt(maxOf(0,(ss-sum*sum/nint)/(nint-1)));
    cv=0; if (mean>0) cv=sd/mean;
    return ""+nint+","+mean+","+sd+","+cv;
}
// Let the user edit the AUTO-detected ticks directly, drag a wrong one to
// the correct spot, delete an extra one, add a missed one, instead of
// having to redo the whole line by hand or accept it as-is. Starts the
// multi-point tool PRE-LOADED with the detected positions (unlike
// manualClicks() below, which starts empty), reusing gestures ImageJ's own
// point tool already provides: click-drag to move a point, Alt-click
// (Option-click on Mac) to delete one, click empty space to add one.
var E_n; var E_mean; var E_sd; var E_cv;
function editDetectedTicks(x1,y1,x2,y2,zpos){
    E_n=0; E_mean=0; E_sd=0; E_cv=0;
    L=sqrt((x2-x1)*(x2-x1)+(y2-y1)*(y2-y1));
    ux=(x2-x1)/L; uy=(y2-y1)/L;

    n0=zpos.length;
    if (n0>0){
        xs=newArray(n0); ys=newArray(n0);
        for (i=0;i<n0;i++){
            xs[i]=x1+zpos[i]*ux;
            ys[i]=y1+zpos[i]*uy;
        }
        makeSelection("point", xs, ys);
    }

    setTool("multipoint");
    waitForUser("Edit ticks",
        "The detected tick marks are now editable points on the image.\n\n"
      + "Drag a point to move it to the correct location.\n"
      + "Alt-click (Option-click on Mac) an existing point to delete it.\n"
      + "Click empty space along the line to add a missed one.\n\n"
      + "When done, click OK.");

    if (selectionType()!=10) return;   // selection lost/cleared: treat as zero ticks
    getSelectionCoordinates(px,py);
    if (px.length<2) return;
    t=newArray(px.length);
    for (i=0;i<px.length;i++) t[i]=(px[i]-x1)*ux+(py[i]-y1)*uy;
    Array.sort(t);
    nint=t.length-1; sum=0; ss=0;
    for (i=0;i<nint;i++){ d=(t[i+1]-t[i])*UMPX; sum+=d; ss+=d*d; }
    E_n=nint; E_mean=sum/nint;
    if (nint>1) E_sd=sqrt(maxOf(0,(ss-sum*sum/nint)/(nint-1)));
    if (E_mean>0) E_cv=E_sd/E_mean;
}
// manual fallback: click Z-lines, project onto the band axis
var M_n; var M_mean; var M_sd; var M_cv;
function manualClicks(x1,y1,x2,y2){
    M_n=0; M_mean=0; M_sd=0; M_cv=0;
    L=sqrt((x2-x1)*(x2-x1)+(y2-y1)*(y2-y1));
    ux=(x2-x1)/L; uy=(y2-y1)/L;
    setTool("multipoint");
    waitForUser("Click Z-lines",
        "With the MULTI-POINT tool, click each Z-line in order (head first).\n"
      + ">=2 points => >=1 sarcomere. Then OK.");
    if (selectionType()!=10) return;
    getSelectionCoordinates(px,py);
    if (px.length<2) return;
    t=newArray(px.length);
    for (i=0;i<px.length;i++) t[i]=(px[i]-x1)*ux+(py[i]-y1)*uy;
    Array.sort(t);
    nint=t.length-1; sum=0; ss=0;
    for (i=0;i<nint;i++){ d=(t[i+1]-t[i])*UMPX; sum+=d; ss+=d*d; }
    M_n=nint; M_mean=sum/nint;
    if (nint>1) M_sd=sqrt(maxOf(0,(ss-sum*sum/nint)/(nint-1)));
    if (M_mean>0) M_cv=M_sd/M_mean;
}

// Blind hand recount of the sarcomere line from the last myocyte measured,
// WITHOUT redrawing the boundary. Reuses the exact same line coordinates
// and geometry, so the only thing that differs between this row and the
// original is the sarcomere counting method (algorithm vs a fresh, blind
// hand count), which is what a hand-vs-AUTO validation actually needs to
// isolate; redrawing the boundary risks shifting the line itself (its
// position and angle both derive from the traced ROI), confounding the
// comparison. Uses the same manualClicks() as the regular Manual option,
// which starts from an empty selection, so this is a genuinely independent
// count, not a correction of the AUTO result. Written for the lab's own
// validation dataset, but intended to be reusable by anyone validating
// their own results against a hand count.
function blindRecount(){
    if (!LASTLINE_VALID){
        showMessage("No sarcomere line yet",
            "Measure a myocyte with a sarcomere line first (Accept, Edit,\n"
          + "or Manual, not Skip), then use this option to add a blind hand\n"
          + "recount of that same line for validation.");
        return;
    }
    if (MAINIMG!="" && isOpen(MAINIMG) && getTitle()!=MAINIMG) selectWindow(MAINIMG);
    if (getTitle()!=LASTLINE_IMGTITLE){
        showMessage("Wrong image",
            "The last sarcomere line was on a different image ("+LASTLINE_IMGTITLE+").\n"
          + "Switch back to that image to do the blind recount.");
        return;
    }

    // show only the reference line itself, no ticks, so the operator knows
    // where to click without seeing the automatic detection
    makeLine(LASTLINE_X1,LASTLINE_Y1,LASTLINE_X2,LASTLINE_Y2);
    Overlay.remove;
    Overlay.addSelection("yellow",1);
    Overlay.show();
    run("Select None");

    manualClicks(LASTLINE_X1,LASTLINE_Y1,LASTLINE_X2,LASTLINE_Y2);
    if (M_n<1){
        showMessage("Recount not saved", "Fewer than 2 points were clicked; nothing was recorded.");
        return;
    }

    rN=M_n; rMean=M_mean; rSd=M_sd; rCv=M_cv;
    rQual="MANUAL";
    rCalib="OK";
    if (rMean>0 && (rMean<0.8 || rMean>6.0)) rCalib="CHECK_CALIBRATION";

    rSeries=0; if (rMean>0) rSeries=LASTLINE_FILLEN/rMean;
    rParallel=rN;
    rContent=rParallel*rSeries;
    rSdens=0; if (LASTLINE_AREA>0) rSdens=rN/LASTLINE_AREA;
    rSerial=0; if (LASTLINE_FERET>0) rSerial=rN/LASTLINE_FERET;

    roiNameR = LASTLINE_WORMID+"_recount_of_m"+LASTLINE_SRCID;

    File.append(
        myoCounter+","+cleanTitle(LASTLINE_WORMID)+","+LASTLINE_GTAG+","+LASTLINE_DAY+","
        +LASTLINE_REGION+","+LASTLINE_MNSEL+","+d2s(UMPX,5)+","
        +d2s(LASTLINE_AREA,4)+","+d2s(LASTLINE_PERIM,4)+","+d2s(LASTLINE_FERET,4)+","+d2s(LASTLINE_MINFER,4)+","
        +d2s(LASTLINE_MAJOR,4)+","+d2s(LASTLINE_MINOR,4)+","+d2s(LASTLINE_AR,4)+","+d2s(LASTLINE_CIRC,4)+","
        +d2s(LASTLINE_SOLID,4)+","+d2s(LASTLINE_ANISO,4)+","
        +rN+","+d2s(rMean,4)+","+d2s(rSd,4)+","+d2s(rCv,4)+","
        +"MANUAL_RECOUNT"+","+rQual+","+rCalib+","
        +d2s(rSdens,6)+","+d2s(rSerial,6)+","
        +d2s(LASTLINE_FILLEN,4)+","+rParallel+","+d2s(rSeries,3)+","+d2s(rContent,2)+","
        +d2s(LASTLINE_FANG,2)+","+roiNameR+","+BLIND+","+tstamp()+","+cleanTitle(LASTLINE_IMGTITLE)+","+LASTLINE_SRCID+","
        +"0"+","+"0"+","+"0"+","+d2s(0,4)+","+d2s(0,4)+","+d2s(0,4),
        CSV);
    myoCounter++;
    showStatus("Blind recount recorded, linked to myocyte_id "+LASTLINE_SRCID+".");
}

// Trace ONE fiber starting at (x0,y0), stepping along direction (mux,muy)
// [the muscle's long axis], following the fiber's true local path by
// searching perpendicular to that direction (nux,nuy) at each step for the
// local intensity peak, i.e. the standard "follow the ridge" approach,
// same idea as the sarcomere band detection but oriented along the fiber
// instead of across it. Stays within the traced myocyte's own ROI. Stores
// the result in the TRACE_X/TRACE_Y globals (parallel to how M_n/M_mean
// etc. are already used elsewhere in this file) and returns the count.
// Also detects, at every step, whether the search window shows a genuine
// SECOND local peak nearly as bright as the one being followed, a real
// signature of a split (one fiber forking into two) or an oblique branch
// connecting to a neighbor, distinct from ordinary noise (which usually
// leaves one clear peak). Recorded per-step in TRACE_AMBIG for the caller
// to use as a low-confidence flag, since a simple ridge-tracer has no
// principled way to know which branch is "correct" at such a point.
function traceFiberAlong(x0,y0,mux,muy,nux,nuy,stepPx,searchPx,maxSteps){
    xs=newArray(maxSteps); ys=newArray(maxSteps); ambig=newArray(maxSteps);
    cx=x0; cy=y0; n=0;
    for (s=0; s<maxSteps; s++){
        if (!Roi.contains(round(cx),round(cy))) break;
        bestOff=0; bestV=getPixel(round(cx),round(cy));
        vals=newArray(2*searchPx+1);
        for (off=-searchPx; off<=searchPx; off++){
            px = round(cx+off*nux); py = round(cy+off*nuy);
            v=-1;
            if (px>=0 && py>=0 && px<getWidth() && py<getHeight()) v = getPixel(px,py);
            vals[off+searchPx]=v;
            if (v>bestV){ bestV=v; bestOff=off; }
        }
        // a genuine second peak: a local maximum at least 3px from the one
        // just picked, and at least 80% as bright, not just noise on its
        // shoulder
        secondV=-1;
        for (kk=1; kk<vals.length-1; kk++){
            offk = kk-searchPx;
            if (abs(offk-bestOff)<3) continue;
            if (vals[kk]>=0 && vals[kk]>=vals[kk-1] && vals[kk]>=vals[kk+1]){
                if (vals[kk]>secondV) secondV=vals[kk];
            }
        }
        isAmbig=0;
        if (secondV>=0 && bestV>0 && (secondV/bestV)>=0.8) isAmbig=1;

        cx = cx + bestOff*nux; cy = cy + bestOff*nuy;
        xs[n]=cx; ys[n]=cy; ambig[n]=isAmbig; n++;
        cx = cx + stepPx*mux; cy = cy + stepPx*muy;
    }
    TRACE_X = Array.trim(xs,n); TRACE_Y = Array.trim(ys,n); TRACE_AMBIG = Array.trim(ambig,n);
    return n;
}

// Classify ONE already-traced fiber as wavy or not, and how much of its
// length is wavy. Ports the same logic validated offline against real
// marked-up images: project onto the fiber's own (along, across) axes,
// smooth at WAVE_SMOOTH_UM (calibrated in real distance, not a fixed pixel
// count, that mismatch was a confirmed real bug when this was first tried
// on an image with a different um/px), take the local slope, then slide a
// WAVE_WINDOW_UM window along and score each by (direction changes per um)
// x (mean slope magnitude); a window scoring at or above WAVE_THRESH marks
// that stretch wavy. Returns "anyWavy,wavyLenUm" (comma string, matching
// this file's existing convention for multi-value returns, e.g.
// intervalStats()).
function classifyFiberWavy(fx, fy, mux, muy, nux, nuy){
    n = fx.length;
    if (n<10) return "0,0";
    t = newArray(n); dd = newArray(n);
    x0=fx[0]; y0=fy[0];
    for (i=0;i<n;i++){
        rx=fx[i]-x0; ry=fy[i]-y0;
        t[i] = rx*mux + ry*muy;    // pixel distance along the fiber
        dd[i]= rx*nux + ry*nuy;    // pixel deviation perpendicular to it
    }
    spacingPx = 1; if (n>1) spacingPx = (t[n-1]-t[0])/(n-1);
    if (spacingPx<=0) spacingPx = 1;
    smoothN = maxOf(1, round((WAVE_SMOOTH_UM/UMPX)/spacingPx));

    dd_sm = newArray(n);
    for (i=0;i<n;i++){
        a=maxOf(0,i-smoothN); b=minOf(n-1,i+smoothN);
        s=0; c=0; for (j=a;j<=b;j++){ s+=dd[j]; c++; }
        dd_sm[i]=s/c;
    }
    slope = newArray(n);
    for (i=0;i<n;i++){
        a=maxOf(0,i-smoothN); b=minOf(n-1,i+smoothN);
        if (t[b]!=t[a]) slope[i] = (dd_sm[b]-dd_sm[a])/(t[b]-t[a]);
        else slope[i] = 0;
    }

    windowN = maxOf(4, round((WAVE_WINDOW_UM/UMPX)/spacingPx));
    stepN = maxOf(1, round(windowN/2));
    deadzone = 0.05;

    wavyMask = newArray(n);
    i=0;
    while (i<n){
        j = minOf(n, i+windowN);
        if (j-i < windowN*0.6){
            i2 = maxOf(0, n-windowN); j=n;
        } else i2=i;
        turns=0; state=0; sumAbs=0; cnt=0;
        for (k=i2;k<j;k++){
            sVal = slope[k];
            sumAbs += abs(sVal); cnt++;
            cur=0;
            if (sVal>deadzone) cur=1;
            else if (sVal<-deadzone) cur=-1;
            if (cur!=0){
                if (state!=0 && cur!=state) turns++;
                state=cur;
            }
        }
        lengthUmSeg = (t[j-1]-t[i2])*UMPX;
        meanAbs = 0; if (cnt>0) meanAbs = sumAbs/cnt;
        score = 0; if (lengthUmSeg>0) score = (turns/lengthUmSeg)*meanAbs*100;
        if (score >= WAVE_THRESH){
            for (k=i2;k<j;k++) wavyMask[k]=1;
        }
        if (j>=n) i=n; else i += stepN;
    }

    anyWavy=0; wavyCount=0;
    for (i=0;i<n;i++){ if (wavyMask[i]==1){ anyWavy=1; wavyCount++; } }
    wavyLenUm = wavyCount*spacingPx*UMPX;
    if (isNaN(wavyLenUm)) wavyLenUm=0;
    if (isNaN(anyWavy)) anyWavy=0;
    return ""+anyWavy+","+d2s(wavyLenUm,4);
}

// Orchestrates wave detection for the myocyte just measured: seeds one
// fiber trace per already-detected sarcomere band position (zpos), traces
// each forward and backward along the muscle's long axis, classifies each
// as straight, wavy, or low-confidence, lets the operator correct any
// misclassified fiber by clicking it, then aggregates into the two damage
// fractions from the (possibly corrected) classifications. Deliberately
// reuses the SAME ROI, band angle (mux/muy/nux/nuy), sampling line
// (ax1,ay1), and Feret already computed for this myocyte, no
// re-detection of any of it.
//   width fraction  = fraction of fibers (across MinFeret) with any wave
//   length fraction = for affected fibers, how much of the myocyte's own
//                     Feret that fiber's wave covers (mean and max)
// Low-confidence exists because a real split (one fiber forking into two)
// or oblique branch to a neighbor gives a simple ridge-tracer no
// principled way to choose which path is "correct"; forcing a wavy/
// straight guess at such a point would misrepresent it either way, so it
// is flagged instead, the same philosophy as sarc_quality and calib_flag
// elsewhere in this tool. Splitting/branching classification itself is
// intentionally out of scope here, that is a separate, harder tool this
// lab is still working on; this only recognizes that ambiguity exists.
function detectWaves(zpos, ax1, ay1, mux, muy, nux, nuy, feretUm){
    nFibers = zpos.length;
    WAVE_N_FIBERS=nFibers; WAVE_N_AFFECTED=0; WAVE_N_LOWCONF=0;
    WAVE_WIDTH_FRAC=0; WAVE_LEN_MEAN_FRAC=0; WAVE_LEN_MAX_FRAC=0;
    if (nFibers<2) return;

    myoRoiIndex = roiManager("count")-1;
    // remember how many overlay items exist before wave detection adds
    // any (the sarcomere ticks, already drawn), so a retry can strip only
    // ITS OWN overlay items and redraw, without touching those
    waveOverlayStart = Overlay.size;

    fiberClass = newArray(nFibers);    // 0=straight, 1=wavy, 2=low-confidence
    fiberLenFrac = newArray(nFibers);  // wavyLenUm/feretUm; 0 if not wavy

    reclassify = true;
    reviewing = true;
    while (reviewing){
        if (reclassify){
            // strip this function's own overlay items from a prior pass
            // (a Retry), leaving the sarcomere ticks and anything from
            // before this myocyte's wave detection untouched
            while (Overlay.size > waveOverlayStart) Overlay.removeSelection(Overlay.size-1);

            // Real minimum gap between THIS myocyte's actual adjacent
            // fibers (zpos are already the real detected positions, in
            // profile-index units = px along the sampling line).
            // Confirmed on real data: with searchPx set only from
            // WAVE_LINK_UM and no awareness of how close together the
            // real fibers are, the tracer snapped onto a neighboring
            // fiber whenever the search radius approached the real
            // inter-fiber gap, producing a fake zigzag from hopping
            // between two real, individually straight fibers, not a real
            // wave. Capping the search radius at a safe fraction of the
            // tightest real gap in this specific myocyte prevents that by
            // construction, regardless of the WAVE_LINK_UM dial.
            // Recomputed fresh every pass since Retry may have just
            // changed WAVE_LINK_UM (or any other parameter).
            minGapPx = -1;
            for (zi=1; zi<zpos.length; zi++){
                gap = zpos[zi]-zpos[zi-1];
                if (minGapPx<0 || gap<minGapPx) minGapPx = gap;
            }
            searchPx = maxOf(2, round(WAVE_LINK_UM/UMPX));
            if (minGapPx>0){
                safeCapPx = floor(0.35*minGapPx);
                if (safeCapPx<2) safeCapPx=2;
                searchPx = minOf(searchPx, safeCapPx);
            }
            stepPx = 2;
            maxStepsFiber = round((3*feretUm)/UMPX);
            if (maxStepsFiber<10) maxStepsFiber=10;

            for (fi=0; fi<nFibers; fi++){
                if (myoRoiIndex>=0) roiManager("Select", myoRoiIndex);
                seedX = ax1 + zpos[fi]*nux; seedY = ay1 + zpos[fi]*nuy;

                nF = traceFiberAlong(seedX,seedY, mux,muy, nux,nuy, stepPx, searchPx, maxStepsFiber);
                fxF=TRACE_X; fyF=TRACE_Y; ambF=TRACE_AMBIG;
                if (myoRoiIndex>=0) roiManager("Select", myoRoiIndex);
                nB = traceFiberAlong(seedX,seedY, -mux,-muy, nux,nuy, stepPx, searchPx, maxStepsFiber);
                fxB=TRACE_X; fyB=TRACE_Y; ambB=TRACE_AMBIG;

                nTot = nF+nB;
                if (nTot<20) continue;
                fx=newArray(nTot); fy=newArray(nTot); amb=newArray(nTot);
                for (k=0;k<nB;k++){ fx[k]=fxB[nB-1-k]; fy[k]=fyB[nB-1-k]; amb[k]=ambB[nB-1-k]; }
                for (k=0;k<nF;k++){ fx[nB+k]=fxF[k]; fy[nB+k]=fyF[k]; amb[nB+k]=ambF[k]; }

                nAmbig=0; for (k=0;k<nTot;k++){ if (amb[k]==1) nAmbig++; }
                ambigFrac = nAmbig/nTot;

                result = classifyFiberWavy(fx, fy, mux, muy, nux, nuy);
                parts = split(result,",");
                anyWavy = parseInt(parts[0]);
                wavyLenUm = parseFloat(parts[1]);

                cls = 0;
                if (ambigFrac >= WAVE_AMBIG_THRESH) cls = 2;
                else if (anyWavy==1) cls = 1;
                fiberClass[fi] = cls;
                fiberLenFrac[fi] = 0;
                if (cls==1 && feretUm>0) fiberLenFrac[fi] = wavyLenUm/feretUm;

                color = "blue";
                if (cls==1) color="red"; else if (cls==2) color="yellow";
                makeSelection("polyline", fx, fy);
                Overlay.addSelection(color, 1);
                run("Select None");
            }
            Overlay.show();
            reclassify = false;
        }

        nW=0; nL=0;
        for (fi=0; fi<nFibers; fi++){ if (fiberClass[fi]==1) nW++; if (fiberClass[fi]==2) nL++; }
        Dialog.create("Wave detection result");
        Dialog.addMessage("Detected "+nW+" wavy, "+nL+" low-confidence, "
            +(nFibers-nW-nL)+" straight, of "+nFibers+" fibers.\n"
            +"Red = wavy, yellow = low-confidence (likely a split or branch\n"
            +"point, not a confident call either way), blue = straight.\n\n"
            +"Nothing is written to the CSV until you Accept, so retrying\n"
            +"with different parameters never leaves a wrong result behind.");
        revOpts = newArray("Accept as shown","Correct individual fibers by clicking",
                            "Retry with different parameters");
        Dialog.addRadioButtonGroup("",revOpts,3,1,revOpts[0]);
        Dialog.show();
        revChoice = Dialog.getRadioButton();

        if (revChoice==revOpts[2]){
            adjustWaveParams();
            reclassify = true;   // loop back and redo the automatic pass with the new numbers
            continue;
        }

        if (revChoice==revOpts[1]){
            // Let the operator correct any fiber the automatic pass got
            // wrong, same interaction as "Edit ticks" on the sarcomere
            // side: click near the fiber, pick its correct label.
            // Deliberately re-traces on demand (traceFiberAlong is
            // deterministic given the same seed) rather than storing
            // every fiber's full path, simpler than the nested-array
            // bookkeeping that would otherwise need.
            correcting=true;
            while (correcting){
                if (myoRoiIndex>=0) roiManager("Select", myoRoiIndex);
                setTool("multipoint");
                waitForUser("Correct a fiber",
                    "Click ON the fiber you want to relabel, then click OK.\n"
                  + "Leave nothing selected and click OK when you are done.");
                if (selectionType()!=10){ correcting=false; continue; }
                getSelectionCoordinates(clickXs, clickYs);
                if (clickXs.length<1){ correcting=false; continue; }
                clickX=clickXs[0]; clickY=clickYs[0];
                run("Select None");

                bestFi=-1; bestDist=1e9;
                for (fi=0; fi<nFibers; fi++){
                    if (myoRoiIndex>=0) roiManager("Select", myoRoiIndex);
                    seedX = ax1+zpos[fi]*nux; seedY=ay1+zpos[fi]*nuy;
                    nF=traceFiberAlong(seedX,seedY,mux,muy,nux,nuy,stepPx,searchPx,maxStepsFiber);
                    fxF=TRACE_X; fyF=TRACE_Y;
                    for (k=0;k<nF;k++){
                        dx=fxF[k]-clickX; dy=fyF[k]-clickY; dd=sqrt(dx*dx+dy*dy);
                        if (dd<bestDist){ bestDist=dd; bestFi=fi; }
                    }
                    if (myoRoiIndex>=0) roiManager("Select", myoRoiIndex);
                    nB=traceFiberAlong(seedX,seedY,-mux,-muy,nux,nuy,stepPx,searchPx,maxStepsFiber);
                    fxB=TRACE_X; fyB=TRACE_Y;
                    for (k=0;k<nB;k++){
                        dx=fxB[k]-clickX; dy=fyB[k]-clickY; dd=sqrt(dx*dx+dy*dy);
                        if (dd<bestDist){ bestDist=dd; bestFi=fi; }
                    }
                }
                if (bestFi<0 || bestDist>40){
                    showMessage("No fiber found near that click",
                        "Try clicking closer to one of the traced overlay lines.");
                    continue;
                }

                classLabels=newArray("Straight","Wavy","Low confidence");
                Dialog.create("Correct fiber "+(bestFi+1)+" of "+nFibers);
                Dialog.addMessage("Currently classified: "+classLabels[fiberClass[bestFi]]);
                Dialog.addChoice("Change to", classLabels, classLabels[fiberClass[bestFi]]);
                Dialog.show();
                pickLabel=Dialog.getChoice();
                newCls=0;
                if (pickLabel=="Wavy") newCls=1;
                else if (pickLabel=="Low confidence") newCls=2;
                fiberClass[bestFi]=newCls;
                if (newCls!=1) fiberLenFrac[bestFi]=0;

                // redraw just the corrected fiber, on top of its old
                // overlay line in the new color; the retrace is
                // deterministic so it lands exactly on the same path,
                // cleanly covering the old one
                if (myoRoiIndex>=0) roiManager("Select", myoRoiIndex);
                seedX = ax1+zpos[bestFi]*nux; seedY=ay1+zpos[bestFi]*nuy;
                nF=traceFiberAlong(seedX,seedY,mux,muy,nux,nuy,stepPx,searchPx,maxStepsFiber);
                fxF=TRACE_X; fyF=TRACE_Y;
                if (myoRoiIndex>=0) roiManager("Select", myoRoiIndex);
                nB=traceFiberAlong(seedX,seedY,-mux,-muy,nux,nuy,stepPx,searchPx,maxStepsFiber);
                fxB=TRACE_X; fyB=TRACE_Y;
                nTot=nF+nB; fx=newArray(nTot); fy=newArray(nTot);
                for (k=0;k<nB;k++){ fx[k]=fxB[nB-1-k]; fy[k]=fyB[nB-1-k]; }
                for (k=0;k<nF;k++){ fx[nB+k]=fxF[k]; fy[nB+k]=fyF[k]; }
                newColor="blue"; if (newCls==1) newColor="red"; else if (newCls==2) newColor="yellow";
                makeSelection("polyline", fx, fy);
                Overlay.addSelection(newColor, 2);
                run("Select None");
                Overlay.show();
            }
            // loop back to the review dialog (not a reclassify) so they
            // can Accept, correct more, or still retry with new
            // parameters if they want, without losing these corrections
            continue;
        }

        reviewing = false;   // Accept as shown
    }

    // finalize stats from the (possibly corrected) classifications
    nAffected=0; nLow=0; lenFracs=newArray(0);
    for (fi=0; fi<nFibers; fi++){
        if (fiberClass[fi]==1){
            nAffected++;
            lenFracs = Array.concat(lenFracs, fiberLenFrac[fi]);
        }
        if (fiberClass[fi]==2) nLow++;
    }
    WAVE_N_AFFECTED = nAffected;
    WAVE_N_LOWCONF = nLow;
    if (nFibers>0) WAVE_WIDTH_FRAC = nAffected/nFibers;
    if (lenFracs.length>0){
        Array.getStatistics(lenFracs, lfMin, lfMax, lfMean, lfStd);
        WAVE_LEN_MEAN_FRAC = lfMean;
        WAVE_LEN_MAX_FRAC = lfMax;
    }
}

// Session-level dialog to retune the five wave detection parameters.
// Called either from the main menu (takes effect on the next myocyte
// measured) or from inside detectWaves()'s own review dialog via "Retry
// with different parameters" (takes effect immediately, on the same
// myocyte, before anything is written to the CSV).
function adjustWaveParams(){
    Dialog.create("Wave detection parameters");
    Dialog.addMessage("Fiber waviness detection (dystrophic muscle damage).\n"
        + "Defaults were tuned against real marked-up images (one dystrophic,\n"
        + "one healthy control); adjust and re-measure to fit your own data.");
    Dialog.addNumber("Smoothing, filters noise below this scale", WAVE_SMOOTH_UM, 2, 6, "um");
    Dialog.addNumber("Link distance, how far a fiber can locally shift", WAVE_LINK_UM, 2, 6, "um");
    Dialog.addNumber("Scoring window, local length judged for periodicity", WAVE_WINDOW_UM, 1, 6, "um");
    Dialog.addNumber("Wave threshold (higher = stricter)", WAVE_THRESH, 2, 6, "");
    Dialog.addNumber("Low-confidence threshold (fraction of a fiber's steps\nshowing a real second peak, e.g. a split or branch,\nbefore it's flagged low-confidence instead of guessed)", WAVE_AMBIG_THRESH, 2, 6, "");
    Dialog.show();
    WAVE_SMOOTH_UM = Dialog.getNumber();
    WAVE_LINK_UM = Dialog.getNumber();
    WAVE_WINDOW_UM = Dialog.getNumber();
    WAVE_THRESH = Dialog.getNumber();
    WAVE_AMBIG_THRESH = Dialog.getNumber();
}

function setCalibration(){
    if (USECAL){
        // Pull THIS image's own calibration fresh every time, rather than
        // trusting a UMPX value cached from whichever image was open during
        // setup(). Requires each image to already carry valid metadata.
        getPixelSize(u,pw,ph);
        if (pw>0) UMPX=pw;
        return;
    }
    // Fixed pixel size mode: force every image to the session UMPX.
    getPixelSize(u,pw,ph);
    if (abs(pw-UMPX)>1e-9 || (u!="micron" && u!="um")){
        run("Set Scale...","distance=1 known="+UMPX+" unit=micron");
    }
}
function roiManagerAdd(name){
    if (!isOpen("ROI Manager")) run("ROI Manager...");
    roiManager("Add");
    n=roiManager("count");
    roiManager("Select",n-1);
    roiManager("Rename",name);
    roiManager("Deselect");
    // save the whole set each time (cheap, safe against crashes)
    // Deselect above is required: with a single ROI selected, Save can write
    // only that ROI instead of the full accumulated set.
    roiManager("Save", ROIDIR+WORMID+"_rois.zip");
}
function cleanTitle(t){ t=replace(t,",",";"); return t; }
function tstamp(){
    getDateAndTime(ts_yr,ts_mo,ts_dw,ts_dy,ts_hr,ts_mi,ts_sc,ts_ms);
    return ""+ts_yr+IJ.pad(ts_mo+1,2)+IJ.pad(ts_dy,2)+"_"+IJ.pad(ts_hr,2)+IJ.pad(ts_mi,2)+IJ.pad(ts_sc,2);
}

// ---------------------------------------------------------------------------
//  Myocyte numbering (Myo01-Myo24) and reference schematic
// ---------------------------------------------------------------------------
// Ask which numbered myocyte (per the body-wall schematic: anterior 1-10,
// midbody 11-18, posterior 19-24) this cell is. Defaults to "unknown" unless
// the previous cell was a specific number, in which case it suggests the
// next one along, since cells are usually measured in sequence within an
// image. Returns a string: "1".."24", "unknown", or "other".
function pickMyoNumber(){
    mnChoices=newArray(26);
    mnChoices[0]="unknown";
    for (i=1;i<=24;i++) mnChoices[i]=""+i;
    mnChoices[25]="other";
    suggest="unknown";
    if (LASTMYON>=1 && LASTMYON<24) suggest=""+(LASTMYON+1);
    Dialog.createNonBlocking("Which myocyte is this?");
    Dialog.addMessage("Identify this cell against the body-wall schematic if you can\n"
        + "(use 'Show myocyte numbering schematic' from the main menu).\n"
        + "Leave as 'unknown' if the position along the body cannot be pinned down.");
    Dialog.addChoice("Myocyte number",mnChoices,suggest);
    Dialog.show();
    sel=Dialog.getChoice();
    if (sel!="unknown" && sel!="other") LASTMYON=parseInt(sel);
    return sel;
}
// Region boundaries per the lab's body-wall schematic (anterior 1-10,
// midbody 11-18, posterior 19-24). Falls back to the current image-level
// REGION for numbers outside that range (should not normally happen).
function regionFromMyoNum(n){
    if (n>=1 && n<=10) return "anterior";
    if (n>=11 && n<=18) return "midbody";
    if (n>=19 && n<=24) return "posterior";
    return REGION;
}
// Look for a schematic bundled in the SAME folder as this macro file, under
// a fixed name, so the tool works with zero configuration for anyone who
// downloads the .ijm and the schematic together. Falls back to "" (caller
// then prompts to browse) if the macro's own path is unavailable or no
// matching file is found there.
function findBundledSchematic(){
    mp=getInfo("macro.filepath");
    print("[Myocyte_Morphometry] macro.filepath = '"+mp+"'");
    if (mp=="") return "";
    dir=File.getParent(mp)+File.separator;
    print("[Myocyte_Morphometry] looking for schematic in: '"+dir+"'");
    names=newArray("myocyte schematic.jpg",
                    "myocyte schematic.jpeg",
                    "myocyte schematic.png",
                    "myocyte schematic.tif");
    for (i=0; i<names.length; i++){
        cand=dir+names[i];
        if (File.exists(cand)) return cand;
    }
    return "";
}
// Open (or bring forward) the reference schematic image so a student can
// check which numbered myocyte they are looking at. Deliberately does NOT
// auto-restore focus to the working image afterward, since the point is to
// let the student actually look at it; measureMyocyte() defensively
// refocuses the working image itself before doing anything measurement
// related, so leaving the schematic in front here is safe.
function showSchematic(){
    if (REFIMG=="" || !File.exists(REFIMG)) REFIMG=findBundledSchematic();
    if (REFIMG=="" || !File.exists(REFIMG)) REFIMG=call("ij.Prefs.get","myocyte_morph.refimg","");
    if (REFIMG=="" || !File.exists(REFIMG)){
        showMessage("Myocyte numbering schematic",
            "No 'myocyte schematic.jpg/.png/.tif' was found next to this macro file.\n"
            + "Choose the schematic image on the next screen, or Cancel to skip.");
        REFIMG=File.openDialog("Select myocyte numbering schematic");
        if (REFIMG==""){
            showStatus("No schematic selected. You can try again anytime from the main menu.");
            return;
        }
    }
    call("ij.Prefs.set","myocyte_morph.refimg",REFIMG);  // remember for next time
    schemTitle="Myocyte numbering schematic (reference)";
    if (isOpen(schemTitle)){
        selectWindow(schemTitle);
    } else {
        open(REFIMG);
        rename(schemTitle);
        setLocation(0,0);   // top-left corner, out of the way of the working image
    }
}
