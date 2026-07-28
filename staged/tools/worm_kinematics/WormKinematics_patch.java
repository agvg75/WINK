// ============================================================================
// WormKinematics_patch.java
//
// Additive patch for WormRGBCaMPMap_v1.java that turns the extractor into a
// single-worm spine-kinematics tool matching the 2011 (swim/crawl) and 2015
// (burrowing) assays. It does four things:
//
//   1. ANATOMICAL SEGMENT SCOPING. Confines the 24 muscle-proportional
//      segments to the muscle-bearing body (behind the pharynx to the anus)
//      instead of spanning the whole midline, so the pharynx (which forages,
//      not undulates) and the passive tail spike stop diluting the body wave.
//      The existing raised-cosine muscle taper is kept; only its span changes.
//
//   2. FORAGING PRIMITIVE. A per-frame head-bend angle (head tip deflection
//      relative to the neck-to-body axis), emitted as a CSV column. This is
//      the geometric quantity foraging is measured FROM.
//
//   3. FORAGING + POSTERIOR-DAMPENING SUMMARIES (plain Java, end of run).
//      Foraging amplitude and frequency from the head-bend series; posterior
//      dampening from the anterior-to-posterior fall in per-segment bend
//      amplitude. Written to a sidecar <name>_kinematics_summary.csv.
//      NOTE: these plain-Java estimators (zero-crossing frequency, std
//      amplitude, linear-fit dampening) are the convenient in-plugin numbers.
//      The Python worm_kinetics layer's Hilbert/phase-gradient versions are
//      more robust near Nyquist and should be treated as authoritative when
//      they disagree.
//
//   4. SINGLE-CHANNEL TRANSMITTED-LIGHT INPUT. A kinematics-only load path so
//      the tool opens ONE transmitted-light stack instead of requiring four
//      channels. Calcium columns are written NaN in this mode.
//
// INTEGRATION: paste the FIELDS block into the class field area, the METHODS
// block anywhere inside the class body, then apply the four small edits marked
// [EDIT 1..4] below (dialog fields, CSV header + row, run() branch, export
// guards). None of this compiles standalone: it references private members of
// WormRGBCaMPMap_v1 and the ImageJ API, and is meant to live inside that class.
//
// Cannot be compiled against ImageJ in the authoring environment; review and
// build inside Fiji.
// ============================================================================


// ---------------------------------------------------------------------------
// FIELDS  (paste into the class field area, near the other tunables)
// ---------------------------------------------------------------------------

    // Anatomical body scoping. The 24 muscle-proportional segments are placed
    // BETWEEN these two arc fractions, not across the whole midline. Defaults
    // are literature-guided starting points, adjustable in the setup dialog:
    //   headFrac ~ pharynx/body-wall boundary (anterior foraging domain is
    //             [0, headFrac]); tailFrac ~ anus/pre-anal (passive tail spike
    //             is [tailFrac, 1]). Only the muscle-bearing span drives the
    //             body wave, so only it is segmented.
    double headFrac = 0.10;   // pharynx boundary (foraging domain ends here)
    double tailFrac = 0.92;   // anus / start of passive tail spike
    // Reference span used to define the "body axis" the head bends against:
    // the neck sits at headFrac; the axis reference sits headAxisSpan further
    // posterior. Kept small so the axis is the local anterior body direction,
    // not the whole worm.
    double headAxisSpan = 0.12;

    // Kinematics-only (single transmitted-light channel) mode. When true, the
    // three fluorescence stacks are absent and calcium columns are written NaN.
    boolean kinematicsOnly = false;

    // Per-frame head-bend angle (deg), signed. NaN where the frame is invalid.
    // Filled by computeHeadBend(); consumed by the foraging summary and the CSV.
    double[] headBendDeg;


// ---------------------------------------------------------------------------
// METHODS  (paste anywhere inside the class body)
// ---------------------------------------------------------------------------

    // === 1. Anatomical segment scoping ======================================
    // REPLACES the existing buildMuscleBoundaries(). Same muscle-size taper,
    // but the cumulative fractions are mapped into [headFrac, tailFrac] rather
    // than [0, 1], so the pharynx and tail spike are excluded from the muscle
    // segments. segStart()/segEnd() are unchanged: they still read
    // muscleBoundaryFrac and round onto the midline grid, so nothing downstream
    // needs editing. Bump nMid (e.g. 100 -> 192) if the grid quantization of
    // these anatomical edges matters for your shortest segments.
    void buildMuscleBoundaries(){
        double lo = clampD(headFrac, 0.0, 0.45);
        double hi = clampD(tailFrac, lo + 0.10, 1.0);
        double span = hi - lo;

        double[] prof = new double[nSeg];
        for (int k = 0; k < nSeg; k++){
            double u = (nSeg > 1) ? (double)k/(nSeg-1) : 0.5;   // 0..1 head->tail
            double hump = 0.5 - 0.5*Math.cos(2*Math.PI*u);      // 0 at ends, 1 centre
            prof[k] = 0.55 + 0.45*hump;                          // 0.55..1.0 relative size
        }
        if (muscleSizeProfile != null && muscleSizeProfile.length == nSeg){
            prof = muscleSizeProfile.clone();
        }
        double sum = 0; for (double v : prof) sum += v;

        muscleBoundaryFrac = new double[nSeg+1];
        muscleBoundaryFrac[0] = lo;
        double acc = 0;
        for (int k = 0; k < nSeg; k++){ acc += prof[k]/sum; muscleBoundaryFrac[k+1] = lo + acc*span; }
        muscleBoundaryFrac[nSeg] = hi;   // guard exact end
    }


    // === 2. Foraging primitive: per-frame head-bend angle ===================
    // Head bend = signed angle between the anterior body axis (from an axis
    // point back to the neck) and the head vector (from the neck to the head
    // tip). 0 = head aligned with the neck's body axis; sign is dorsal-positive
    // where the dorsal side is resolved, otherwise left-of-axis positive.
    //
    // The three indices are taken from the HEAD end, respecting per-frame
    // orientation (headIsPoint0). Purely head-region geometry, so it needs no
    // calcium and is valid on transmitted light.
    void computeHeadBend(){
        if (headBendDeg == null || headBendDeg.length != nFrames) headBendDeg = new double[nFrames];
        int off  = (int)Math.round(headFrac * (nMid-1));                 // neck offset from head
        int offA = (int)Math.round((headFrac + headAxisSpan) * (nMid-1)); // axis offset from head
        off  = clamp(off,  1, nMid-2);
        offA = clamp(offA, off+1, nMid-1);

        for (int f = 0; f < nFrames; f++){
            headBendDeg[f] = Double.NaN;
            if (!found[f] || skip[f]) continue;

            boolean h0 = headIsPoint0 != null && headIsPoint0[f];
            int iHead = h0 ? 0            : nMid-1;
            int iNeck = h0 ? off          : nMid-1-off;
            int iAxis = h0 ? offA         : nMid-1-offA;

            double axx = midX[f][iNeck] - midX[f][iAxis];   // anterior body axis
            double axy = midY[f][iNeck] - midY[f][iAxis];
            double hx  = midX[f][iHead] - midX[f][iNeck];    // head vector
            double hy  = midY[f][iHead] - midY[f][iNeck];
            double na = Math.hypot(axx, axy), nh = Math.hypot(hx, hy);
            if (na < 1e-6 || nh < 1e-6) continue;

            double cross = axx*hy - axy*hx;      // signed area (left-of-axis > 0)
            double dot   = axx*hx + axy*hy;
            double ang   = Math.toDegrees(Math.atan2(cross, dot));

            // make dorsal-positive if dorsal is resolved this frame
            if (dorsalSign != null && dorsalSign[f] != 0) ang *= Math.signum((double)dorsalSign[f]);
            headBendDeg[f] = ang;
        }
    }


    // === 3a. Foraging summary (plain Java) ==================================
    // Amplitude and frequency of the head-bend oscillation over the recording.
    // Amplitude: RMS (deg) and peak-to-peak (deg) of the mean-subtracted head
    // bend. Frequency: zero-crossing rate of the mean-subtracted series
    // (crossings/2 over the recording duration). Returns
    //   {rmsDeg, p2pDeg, freqHz, coverageFrac, undersampledFlag}.
    // Zero-crossing frequency is crude and biased low when the signal is noisy;
    // it is Nyquist-limited at fps/2. The undersampled flag fires when the
    // estimate approaches Nyquist, i.e. when fps is too low to trust it.
    double[] foragingSummary(){
        int n = 0; double s = 0, s2 = 0, mn = Double.POSITIVE_INFINITY, mx = Double.NEGATIVE_INFINITY;
        int first = -1, last = -1;
        for (int f = 0; f < nFrames; f++){
            double v = headBendDeg[f];
            if (Double.isNaN(v)) continue;
            n++; s += v; s2 += v*v; if (v < mn) mn = v; if (v > mx) mx = v;
            if (first < 0) first = f; last = f;
        }
        if (n < 8) return new double[]{Double.NaN, Double.NaN, Double.NaN, 0, 0};
        double mean = s/n;
        double var  = Math.max(0, s2/n - mean*mean);
        double rms  = Math.sqrt(var);
        double p2p  = mx - mn;

        // zero crossings of the mean-subtracted series, over valid frames only
        int cross = 0; double prev = Double.NaN;
        for (int f = 0; f < nFrames; f++){
            double v = headBendDeg[f]; if (Double.isNaN(v)) continue;
            double c = v - mean;
            if (!Double.isNaN(prev) && ((prev <= 0 && c > 0) || (prev >= 0 && c < 0))) cross++;
            prev = c;
        }
        double durS = (last > first) ? (last - first)/fps : Double.NaN;
        double freq = (durS > 0) ? (cross/2.0)/durS : Double.NaN;
        double coverage = (double)n / Math.max(1, nFrames);
        double undersampled = (!Double.isNaN(freq) && freq >= 0.4*fps) ? 1 : 0;
        return new double[]{rms, p2p, freq, coverage, undersampled};
    }


    // === 3b. Posterior dampening (plain Java) ================================
    // Per-segment bend amplitude = temporal standard deviation of that
    // segment's signed curvature (segCurv) over valid frames. Posterior
    // dampening is the anterior-to-posterior fall in that amplitude:
    //   slopePerBodyLen : linear-fit slope of amplitude vs body-fraction
    //                     (deg amplitude per unit body length; negative = the
    //                     wave attenuates posteriorly, the expected sign)
    //   paRatio         : mean amplitude of the posterior third divided by the
    //                     anterior third (< 1 = damped posteriorly)
    // Fills ampProfile (per segment) and segPosFrac (per segment) as a side
    // effect for the sidecar CSV. Returns {slopePerBodyLen, paRatio, r2}.
    double[] ampProfile;    // [nSeg] per-segment bend amplitude (deg)
    double[] segPosFrac;    // [nSeg] per-segment body-fraction midpoint
    double[] posteriorDampening(){
        ampProfile = new double[nSeg];
        segPosFrac = new double[nSeg];
        if (muscleBoundaryFrac == null) buildMuscleBoundaries();

        for (int k = 0; k < nSeg; k++){
            int nn = 0; double s = 0, s2 = 0;
            for (int f = 0; f < nFrames; f++){
                if (!found[f] || skip[f]) continue;
                double v = segCurv(f, k);
                if (Double.isNaN(v)) continue;
                nn++; s += v; s2 += v*v;
            }
            double amp = Double.NaN;
            if (nn >= 4){ double m = s/nn; amp = Math.sqrt(Math.max(0, s2/nn - m*m)); }
            ampProfile[k] = amp;
            segPosFrac[k] = 0.5*(muscleBoundaryFrac[k] + muscleBoundaryFrac[k+1]);
        }

        // linear fit amplitude vs body fraction
        double[] fit = kinLinreg(segPosFrac, ampProfile);   // {slope, intercept, r2}

        // posterior/anterior third ratio
        int t = Math.max(1, nSeg/3);
        double antS = 0, postS = 0; int antN = 0, postN = 0;
        for (int k = 0; k < t; k++)               if (!Double.isNaN(ampProfile[k])){ antS  += ampProfile[k]; antN++; }
        for (int k = nSeg - t; k < nSeg; k++)     if (!Double.isNaN(ampProfile[k])){ postS += ampProfile[k]; postN++; }
        double antM  = (antN  > 0) ? antS/antN   : Double.NaN;
        double postM = (postN > 0) ? postS/postN : Double.NaN;
        double pa = (!Double.isNaN(antM) && antM > 1e-6) ? postM/antM : Double.NaN;

        return new double[]{fit[0], pa, fit[2]};
    }


    // ordinary least squares on finite (x,y) pairs -> {slope, intercept, r2}
    double[] kinLinreg(double[] x, double[] y){
        int n = 0; double sx = 0, sy = 0, sxx = 0, sxy = 0, syy = 0;
        for (int i = 0; i < x.length; i++){
            if (Double.isNaN(x[i]) || Double.isNaN(y[i])) continue;
            n++; sx += x[i]; sy += y[i]; sxx += x[i]*x[i]; sxy += x[i]*y[i]; syy += y[i]*y[i];
        }
        if (n < 3) return new double[]{Double.NaN, Double.NaN, Double.NaN};
        double denom = n*sxx - sx*sx;
        if (Math.abs(denom) < 1e-12) return new double[]{Double.NaN, Double.NaN, Double.NaN};
        double slope = (n*sxy - sx*sy)/denom;
        double inter = (sy - slope*sx)/n;
        double num = n*sxy - sx*sy;
        double den = Math.sqrt((n*sxx - sx*sx)*(n*syy - sy*sy));
        double r2  = (den > 1e-12) ? (num/den)*(num/den) : Double.NaN;
        return new double[]{slope, inter, r2};
    }


    // === 3c. Sidecar summary CSV ============================================
    // Whole-recording kinematic scalars do not fit the per-(frame,segment,side)
    // row shape, so they get their own one-plus-nSeg-row file next to the main
    // export. Call this from exportCsv() AFTER the main CSV is written (see
    // [EDIT 2]). dir/base are the same directory and base name as the main CSV.
    void exportKinematicsSummary(String dir, String base){
        computeHeadBend();
        double[] for_ = foragingSummary();
        double[] pd   = posteriorDampening();

        StringBuilder sb = new StringBuilder();
        sb.append("metric,value,units,note\n");
        sb.append("foraging_rms_deg,"        + fmt(for_[0]) + ",deg,RMS head-bend amplitude\n");
        sb.append("foraging_p2p_deg,"        + fmt(for_[1]) + ",deg,peak-to-peak head-bend\n");
        sb.append("foraging_freq_hz,"        + fmt(for_[2]) + ",Hz,zero-crossing estimate (Nyquist-limited)\n");
        sb.append("foraging_coverage_frac,"  + fmt(for_[3]) + ",frac,valid head-bend frames / total\n");
        sb.append("foraging_undersampled,"   + (int)for_[4] + ",flag,1 = freq approaches fps/2; raise fps\n");
        sb.append("dampening_slope_per_L,"   + fmt(pd[0])   + ",deg/bodyfrac,amp vs body position (neg = damped posteriorly)\n");
        sb.append("dampening_pa_ratio,"      + fmt(pd[1])   + ",ratio,posterior third / anterior third amplitude (<1 = damped)\n");
        sb.append("dampening_fit_r2,"        + fmt(pd[2])   + ",r2,linear-fit quality for the slope\n");
        sb.append("fps,"                     + fmt(fps)     + ",Hz,frame rate used\n");
        sb.append("head_frac,"               + fmt(headFrac)+ ",frac,pharynx/body-wall boundary\n");
        sb.append("tail_frac,"               + fmt(tailFrac)+ ",frac,anus/tail-spike boundary\n");
        // per-segment amplitude profile (the spatial curve the slope is fit to)
        sb.append("\nsegment,body_frac,bend_amplitude_deg\n");
        for (int k = 0; k < nSeg; k++)
            sb.append(k + "," + fmt(segPosFrac[k]) + "," + fmt(ampProfile[k]) + "\n");

        try {
            java.io.FileWriter fw = new java.io.FileWriter(dir + base + "_kinematics_summary.csv");
            fw.write(sb.toString()); fw.close();
            IJ.log("Wrote kinematics summary: " + base + "_kinematics_summary.csv");
            if ((int)for_[4] == 1)
                IJ.log("  NOTE foraging_undersampled=1: the head oscillation nears fps/2. "
                     + "Trust the Python Hilbert estimate over this zero-crossing value.");
        } catch (Exception e){ IJ.error("Kinematics summary write failed: " + e.getMessage()); }
    }


    // === 4. Single transmitted-light channel input ==========================
    // Kinematics-only load: use ONE stack for tracking, leave the three fluor
    // stacks null. Prefers the frontmost open image; falls back to a picker.
    // Call this INSTEAD of loadFourChannels() when kinematicsOnly is chosen
    // (see [EDIT 3]).
    boolean loadSingleChannel(){
        ImagePlus tl = IJ.getImage();      // frontmost open stack
        if (tl == null){
            OpenDialog od = new OpenDialog("Choose a transmitted-light worm stack", null);
            if (od.getFileName() == null) return false;
            tl = IJ.openImage(od.getDirectory() + od.getFileName());
        }
        if (tl == null){ IJ.error("No transmitted-light stack."); return false; }
        if (tl.getStackSize() < 2){ IJ.error("Need a multi-frame stack, got a single image."); return false; }

        trackImp   = tl;
        trackStack = tl.getStack();
        measStacks = new ImageStack[]{null, null, null};   // no fluorescence
        nMeas = 0;
        rgbMode = false;
        kinematicsOnly = true;
        useRedPharynx = false;     // no red channel to guide the head
        return true;
    }


// ---------------------------------------------------------------------------
// EDITS TO EXISTING CODE
// ---------------------------------------------------------------------------
//
// [EDIT 1] setupDialog(): add the anatomical + mode controls, and read them.
//   Add near the other numeric fields (before gd.showDialog()):
//       gd.addCheckbox("Kinematics only (single transmitted-light stack)", kinematicsOnly);
//       gd.addNumericField("Head/pharynx boundary (body fraction)", headFrac, 2);
//       gd.addNumericField("Tail/anus boundary (body fraction)",    tailFrac, 2);
//   Add in the same ORDER among the gd.getNext... reads:
//       kinematicsOnly = gd.getNextBoolean();
//       headFrac = clampD(gd.getNextNumber(), 0.0, 0.45);
//       tailFrac = clampD(gd.getNextNumber(), headFrac + 0.10, 1.0);
//       muscleBoundaryFrac = null;   // force rebuild with the new span
//   (Field/read order must match: add both together, in the same position.)
//
// [EDIT 2] exportCsv():
//   (a) add ",head_bend_deg" to the header string, at the end of the kinematics
//       group, e.g. after "...,angular_vel_deg_s," insert head_bend_deg before
//       the lag columns (choose one spot and keep header and row in step).
//   (b) in the row append, add the head-bend value. It is per-FRAME, so compute
//       it once per frame before the segment loop:
//           if (headBendDeg == null) computeHeadBend();
//           double hb = headBendDeg[f];
//       and append fmt(hb) at the matching position in every row.
//   (c) after the main file is written (after fw.close()), add:
//           exportKinematicsSummary(sd.getDirectory(), sd.getFileName().replace(".csv",""));
//
// [EDIT 3] run(): choose the load path. Replace
//           if (!loadFourChannels()) return;
//   with a branch. Simplest: add a first tiny dialog, or key off a macro arg:
//           boolean single = arg != null && arg.toLowerCase().contains("kin");
//           if (single){ if (!loadSingleChannel()) return; }
//           else       { if (!loadFourChannels()) return; }
//   Register a second menu entry pointing at this plugin with arg "kinematics"
//   so a transmitted-light run is one click for the operator.
//
// [EDIT 4] Guard the calcium reads so kinematicsOnly does not dereference the
//   null fluor stacks. In buildSeriesMeanMulti() and in the exportCsv segment
//   loop, wrap the per-channel statsInPolygonMeas(...) calls:
//           if (!kinematicsOnly && measStacks[c] != null) { ... read channel ... }
//           else { leave the blue/green/red min/mean/max and bg_* as NaN }
//   The geometry and kinematics columns (seg_angle, seg_curv, axial_vel,
//   angular_vel, head_bend, all flags) are unaffected and remain populated.
// ============================================================================
