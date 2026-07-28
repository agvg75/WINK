// ============================================================
// AFD_MTP_v7_gap_patch.java
//
// Gap resolution for AFD_MTP_v6, using the RGBCaMP approach: when the
// body is not found on a frame, do NOT silently hold the last angle.
// Instead, if the good frames on either side agree,
// interpolate the AFD angle across it and tag those frames INTERPOLATED
// so they are never mistaken for measurements. If the two sides disagree
// too much, mark the frames NEEDS HELP and
// surface them so a human corrects them.
//
// This replaces exactly one v6 behavior (the keyOff.floorEntry hold in
// recompute) and adds an honest provenance column plus a help prompt.
// Everything else in v6 is unchanged.
//
// INTEGRATION: paste the FIELDS and METHODS blocks into the AFD_MTP_v6
// class, then apply [EDIT 1..4]. Cannot be compiled here; build in Fiji.
// ============================================================


// ---------------------------------------------------------------------------
// FIELDS  (paste with the other per-frame arrays, near line 90)
// ---------------------------------------------------------------------------

    // provenance of each frame's afd_angle
    static final int P_MEASURED = 0;   // body found, angle measured this frame
    static final int P_INTERP   = 1;   // filled from the good frames flanking a gap
    static final int P_MANUAL   = 2;   // a frame the user corrected by hand
    static final int P_HELP     = 3;   // gap could not be safely filled: needs correction
    static final int P_SKIP     = 4;   // frame marked skip

    int[]     prov;            // per-frame provenance code (above)
    boolean[] needsHelp;       // true where a gap could not be safely interpolated

    // gap tolerance (no hard-coded frame-count limit)
    double maxFlankDisagreeDeg = 45.0; // if the two sides differ by more than this, refuse to interpolate


// ---------------------------------------------------------------------------
// METHODS  (paste anywhere in the class body)
// ---------------------------------------------------------------------------

    // Fill not-found gaps from their flanking measured frames, honestly.
    // Called at the END of recompute(), after the per-frame loop has set
    // afdAng to a real value on found frames and to NaN on not-found frames.
    void resolveGaps() {
        if (prov == null || prov.length != n) { prov = new int[n]; needsHelp = new boolean[n]; }
        for (int i = 0; i < n; i++) { needsHelp[i] = false; }

        // mark measured / skip up front
        for (int i = 0; i < n; i++) {
            if (skip[i])            prov[i] = P_SKIP;
            else if (bodyFound[i])  prov[i] = P_MEASURED;
        }

        // walk each maximal run of not-found, non-skip frames (a gap)
        int i = 0;
        while (i < n) {
            if (skip[i] || bodyFound[i]) { i++; continue; }
            int gs = i;
            while (i < n && !skip[i] && !bodyFound[i]) i++;
            int ge = i - 1;                       // gap spans [gs..ge]

            int L = prevFound(gs - 1);            // last measured frame before the gap
            int R = nextFound(ge + 1);            // first measured frame after the gap
            boolean bounded = (L >= 0 && R < n);
            double disagree = bounded ? Math.abs(circDiff(afdAng[L], afdAng[R])) : 999.0;
            boolean canFill = bounded && disagree <= maxFlankDisagreeDeg;

            if (canFill) {
                for (int k = gs; k <= ge; k++) {
                    double f = (double)(k - L) / (double)(R - L);   // 0..1 across the gap
                    afdAng[k] = circInterp(afdAng[L], afdAng[R], f);
                    setNoseFromAngle(k);
                    prov[k] = P_INTERP;
                }
            } else {
                // cannot fill safely: hold the nearest measured value only as a
                // visible placeholder, and flag every frame for correction so it
                // is never read as data.
                double hold = (L >= 0) ? afdAng[L] : (R < n ? afdAng[R] : Double.NaN);
                for (int k = gs; k <= ge; k++) {
                    afdAng[k] = hold;
                    setNoseFromAngle(k);
                    prov[k] = P_HELP;
                    needsHelp[k] = true;
                }
            }
        }

        // frames the user fixed by hand outrank everything
        for (int k = 0; k < n; k++)
            if (!skip[k] && bodyFound[k] && corrected[k]) prov[k] = P_MANUAL;
    }

    int prevFound(int from) { for (int k = from; k >= 0; k--) if (!skip[k] && bodyFound[k]) return k; return -1; }
    int nextFound(int from) { for (int k = from; k < n;  k++) if (!skip[k] && bodyFound[k]) return k; return n; }

    // shortest signed arc a -> b, in (-180, 180]
    double circDiff(double a, double b) { double d = mod360(b - a); if (d > 180) d -= 360; return d; }
    // interpolate a -> b along the shortest arc by fraction f
    double circInterp(double a, double b, double f) { return mod360(a + circDiff(a, b) * f); }

    // place the nose from a (possibly interpolated) angle and the tracked soma
    void setNoseFromAngle(int i) {
        double[] u = unit(afdAng[i]);   // v6 unit(): {sin, -cos} for compass angle
        noseX[i] = somaX[i] + u[0] * arrowLen;
        noseY[i] = somaY[i] + u[1] * arrowLen;
    }

    String provName(int p) {
        if (p == P_MEASURED) return "measured";
        if (p == P_INTERP)   return "interpolated";
        if (p == P_MANUAL)   return "manual";
        if (p == P_HELP)     return "help";
        return "skip";
    }

    // Call for help: after recompute, if any frames could not be filled,
    // list them and offer to jump to the first so the user can correct it
    // with v6's existing body/soma tools. Returns the first help frame, or -1.
    int reportHelp() {
        int first = -1, count = 0;
        StringBuilder ranges = new StringBuilder();
        int i = 0;
        while (i < n) {
            if (!needsHelp[i]) { i++; continue; }
            int s = i; while (i < n && needsHelp[i]) i++;
            int e = i - 1;
            if (first < 0) first = s;
            count += (e - s + 1);
            ranges.append((s + 1) + (e > s ? "-" + (e + 1) : "") + "  ");
        }
        if (count == 0) { IJ.log("Gap resolution: no frames need help."); return -1; }
        IJ.log("Gap resolution: " + count + " frame(s) need correction: " + ranges);
        new WaitForUserDialog("Some frames need your help",
            count + " frame(s) could not be filled safely (missing a flank or the\n"
          + "good frames on either side disagree). Frames: " + ranges + "\n\n"
          + "Use Fix body / Re-track / draw a HEAD-to-TAIL line on these,\n"
          + "then Recompute. They are tagged 'help' in the CSV until fixed.").show();
        return first;
    }


// ---------------------------------------------------------------------------
// EDITS TO v6
// ---------------------------------------------------------------------------
//
// [EDIT 1] Allocate the new arrays where the others are allocated (near line
//   157, beside bodyFound/skip/corrected):
//       prov = new int[n];  needsHelp = new boolean[n];
//
// [EDIT 2] In recompute(), REPLACE the AFD-anterior-direction block. v6 has:
//
//       double ax, ay;
//       if (bodyFound[i]) { ax=somaX[i]-cenX[i]; ay=somaY[i]-cenY[i]; }
//       else {
//           Map.Entry<Integer,double[]> e=keyOff.floorEntry(i);
//           double[] off=(e!=null)?e.getValue():new double[]{0,-1};
//           ax=off[0]; ay=off[1];
//       }
//       afdAng[i]=compass(ax,ay);
//       double mag=Math.max(1e-6, Math.hypot(ax,ay));
//       noseX[i]=somaX[i]+ax/mag*arrowLen; noseY[i]=somaY[i]+ay/mag*arrowLen;
//
//   REPLACE it with (found = measured now; not-found = NaN, filled later):
//
//       if (bodyFound[i]) {
//           double ax=somaX[i]-cenX[i], ay=somaY[i]-cenY[i];
//           afdAng[i]=compass(ax,ay);
//           double mag=Math.max(1e-6, Math.hypot(ax,ay));
//           noseX[i]=somaX[i]+ax/mag*arrowLen; noseY[i]=somaY[i]+ay/mag*arrowLen;
//       } else {
//           afdAng[i]=Double.NaN;   // resolveGaps() will interpolate or flag it
//       }
//
//   (moveAng and the brightness block below stay as they are: they use the
//   tracked soma, which exists even when the body is not found.)
//
// [EDIT 3] At the very END of recompute(), after the area-jump QC loop, add:
//       resolveGaps();
//   And wherever recompute() is called from the interactive flow (e.g. after
//   "Recompute and redraw"), follow it with:
//       reportHelp();
//   so the user is told which frames to fix. (Do NOT call reportHelp() inside
//   a tight batch loop; call it once after a full recompute.)
//
// [EDIT 4] exportCsv(): add two columns.
//   Header: append ",afd_provenance,needs_help" to the end of the header line
//   (after "area_flag").
//   Data branch (the non-skip append): add
//       +","+provName(prov[i])+","+(needsHelp[i]?1:0)
//   just before the closing "\n".
//   Skip branch (the fixed NaN row): append ",skip,0" before its "\n".
//
// RESULT: afd_angle on found frames is measured; short clean gaps are filled
// and tagged 'interpolated'; unfillable gaps are tagged 'help' with
// needs_help=1 and surfaced for correction. Nothing is ever silently held.
// The one v6 field this makes vestigial is keyOff; you can leave it or remove
// its now-unused reads.
// ============================================================
