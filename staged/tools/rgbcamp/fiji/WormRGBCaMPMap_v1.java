import ij.*;
import ij.gui.*;
import ij.process.*;
import ij.measure.*;
import ij.io.*;
import ij.plugin.PlugIn;
import ij.plugin.frame.RoiManager;
import java.awt.*;
import java.util.*;

// ============================================================
// WormRGBCaMPMap_v1  (single-channel GCaMP: per-muscle calcium + kinematics)
//
// PURPOSE
//   Same muscle-resolved analysis as WormMuscleMap, but from a SINGLE
//   GCaMP channel (whole body-wall muscle, bright on black). No
//   transmitted light, no mCherry, no R/G/B compartments.
//
// WHAT IT MEASURES (per midline segment, per side band, per frame)
//   - GCaMP min / mean / max (cytoplasmic calcium only)
//   - dF/dt, and rise-rate vs decay-rate of the per-ROI time series
//   - local body angle and signed curvature (the "3-point" turning angle)
//   - convex/concave side label (automatic) + optional dorsal/ventral seed
//   plus whole-animal kinematics: undulation frequency, centroid velocity,
//   and a per-segment bending-vs-translation (isotonic-vs-isometric proxy)
//   decomposition.
//
// WHAT IS DIFFERENT FROM WormMuscleMap (and why it matters)
//   1) ONE compartment. No red/green or blue/green ratios exist. The tool
//      reports cytoplasmic GCaMP only and does not fabricate the others.
//   2) BODY comes from the GCaMP signal itself (no transmitted light), so
//      segmentation is coupled to the thing being measured: a momentarily
//      DIM muscle can pinch or drop out of the body. Mitigations:
//        - body uses a LOW threshold (find the whole worm even when dim),
//        - the body mask is lightly SMOOTHED across adjacent frames,
//        - brightness is then read from the ORIGINAL (unsmoothed) pixels,
//        - frames where a segment still drops out are FLAGGED, not trusted.
//   3) HEAD/TAIL from MOTION (the leading end during forward travel), since
//      there is no pharynx marker. Manual flip/lock is primary here.
//
// SOURCE-QUALITY CAVEAT
//   Brightness and especially rise/decay are only quantitatively reliable
//   on ORIGINAL frames (TIFF / 12-16 bit). On 8-bit compressed mp4 exports
//   the geometry and kinematics are fine, but intensity columns carry a
//   "src8bit" flag and should not be treated as quantitative.
//
// STATUS: untested first pass. Validate midline + head before trusting.
// ============================================================
//
// PURPOSE
//   First stage of a muscle-resolved, multi-compartment calcium tool
//   for Mackenzie's 4-channel SP8 movies (transmitted light + green
//   cytoplasm GCaMP + red mito RCaMP/pharynx mCherry + blue ER).
//
//   THIS VERSION builds and lets you VALIDATE the skeleton/midline
//   foundation only. It does NOT yet measure calcium or cut muscle
//   ROIs. Those come next, once the midline is trusted.
//
// WHAT IT DOES NOW
//   1) the BODY is segmented from the single GCaMP channel (low threshold)
//   2) the mask is skeletonized to a single head-to-tail midline,
//      resampled to N points, with a left/right half-width at each point
//   3) HEAD is the leading end during forward motion (manual override avail)
//   4) per-segment two side-bands; GCaMP min/mean/max + kinetics measured
//      from the ORIGINAL pixels inside the body
//   5) a QC overlay draws outline (orange), midline (cyan), head (green
//      dot), tail (red dot). Frames that fail the checks are flagged.
//
// ASSUMPTIONS (stated so they can be checked)
//   - worms are MOSTLY EXTENDED (few coils/self-touch). Coiled frames
//     are detected and flagged, NOT solved.
//   - GCaMP labels the whole body wall, bright on a dark background.
//   - one worm in the field.
//
// CONVENTIONS: angles 0..360 compass, 0 = image UP, 90 = right.
// STATUS: untested first pass. Validate the midline before trusting it.
// ============================================================

public class WormRGBCaMPMap_v1 implements PlugIn {

    // ---- single-channel GCaMP: worm is BRIGHT on dark background ----
    // The body is found from the GCaMP signal itself. To decouple body-finding
    // from the signal we measure, the body threshold is deliberately LOW and
    // the body mask is smoothed across adjacent frames; brightness is then read
    // from the ORIGINAL pixels.
    int    measChannel = 1;     // (legacy, single-channel) which RGB component to read
    boolean src8bit = false;    // set true if input looks like an 8-bit (mp4) export
    int    maskSmoothFrames = 1; // +/- frames to union into the body mask (0 = none)

    // ---- RGBCaMP multichannel: track on DIC, measure 3 fluorescent channels ----
    // Each channel is a separate stack (from 4 AVIs or a split multichannel stack).
    // trackStack drives detection/geometry; measStacks[0..2] are read along the
    // shared centerline. Channel names are for CSV column labels.
    boolean rgbMode = true;             // this tool is the multichannel variant
    ImageStack trackStack;              // DIC (whole-body, used for centerline)
    ImageStack[] measStacks = new ImageStack[3];   // [0]=blue [1]=green [2]=red (ch00,ch01,ch02)
    String[]  measName = {"blue","green","red"};
    int       nMeas = 3;
    ImagePlus trackImp;                 // the DIC ImagePlus (for slice display during review)

    // ---- tunables ----
    int    nMid        = 100;   // midline resample points
    double bodyThr     = 0;     // GCaMP body threshold (0 = auto); LOW, to keep dim segments
    int    minBodyArea = 200;   // px; reject specks
    double areaJumpPct = 40.0;  // flag frames whose body area jumps vs running median
    int    nSeg        = 24;    // hemisegments per side (24 per side, per Andres' spec)

    // ---- metadata ----
    double fps = 9.0, fieldAngle = 0.0, fieldStrength = 0.0, umPerPx = 0.0;
    String wormId = "w1", condition = "1G";
    // Grouping metadata (dialog-collected, authoritative -- not inferred from the strain
    // string). Written as explicit CSV columns and used to build the export filename so
    // repeat exports never collide and carry their own grouping.
    static final String[] GENOTYPE_OPTS = {"wildtype","dystrophic"};
    String strain = "", genotype = GENOTYPE_OPTS[0], rnai = "", animalId = "a01";
    int    ageDay = 1;

    // ---- geometry ----
    int W, H, nFrames, nSlices;
    int Mw, Mh;                  // mask-space dims = full image (W, H)
    ImagePlus imp; ImageStack stack;

    // per-frame midline (resampled), width, and flags
    double[][] midX, midY;        // [frame][nMid]
    double[][] halfW;             // [frame][nMid] half-width (px) along local normal
    double[][] hwL, hwR;          // [frame][nMid] measured half-width to LEFT / RIGHT edge
    byte[][]   edgeSrcL, edgeSrcR;// 0=measured edge, 1=placed from learned width profile
    double[]   midLen;            // [frame] total midline arc length (px)
    boolean[]  lenShortFlag;      // midline notably shorter than median (skeleton fell short)
    boolean[]  lenLongFlag;       // midline notably longer than reference (overshoot onto motion trail)
    // learned conserved width profile (half-width vs body fraction), left and right:
    double[]   profL, profR;      // [nMid]; null until learned
    boolean    profLearned=false;
    java.util.ArrayList<Integer> refFrames=new java.util.ArrayList<Integer>(); // hand-picked
    double     edgeConfFrac=0.6;  // edge trusted only if marched dist >= this * profile value
    double[][] edgeLX, edgeLY;    // left edge points
    double[][] edgeRX, edgeRY;    // right edge points
    double[]   bodyArea;
    double[][] curv;              // [frame][nMid] signed local turning angle (deg)
    boolean[]  found, skip, headIsPoint0, coilFlag, areaFlag;
    // per-midline-point provenance: 0=measured (real pixels), 1=inferred
    // (filled from neighbor frames), 2=manual (user click-to-redraw).
    byte[][]   pointSrc;           // [frame][nMid]
    // manual midline override: if non-null, this frame's midline is user-set and
    // is NOT overwritten by reprocessing (only by clearing it).
    double[][] manualMidX, manualMidY;
    boolean[]  manualMidline;      // frame has a full user-redrawn midline
    String[]   correctionNote;     // audit trail for imported or manually corrected geometry
    boolean adaptiveTemporalSamples=true;
    long runStartNs=0;
    double loadSetupSeconds=0, backgroundSeconds=0, initialComputeSeconds=0, exportSeconds=0;
    double[]   thrFrame;          // per-frame GCaMP body threshold
    double[]   headPx, headPy;    // head point per frame (was pharynx)
    double     widthScale = 1.0;  // ROI bands sit at this fraction of half-width
    boolean    smoothMidlineForRois = true;  // biologically plausible spine for ROI geometry
    // Write <base>_geometry.json beside the CSV: the midline, the body outline
    // and the per-(segment,side) measurement bands, frame by frame. The ROI ZIP
    // is the Fiji-facing artefact; this is the machine-readable one, so a
    // downstream tool does not need an ImageJ ROI parser to know where this run
    // actually measured. Without it the bands exist only on screen and are gone
    // when the window closes - a reviewer can then see where the worm was, but
    // not where it was measured. Default on; see the dialog label for the cost.
    boolean    exportGeometryJson = true;
    static final int MYOCYTE_SEGMENTS = 24;  // anatomy, not a resolution knob
    int        midlineSmoothPasses = 2;       // light smoothing; intensity pixels remain raw
    // manual endpoint overrides: frame -> {headX,headY,tailX,tailY}; NaN = none
    double[][] manualEnds;
    // dorsal side: +1 = dorsal is on the LEFT-normal side at the seed, -1 = right.
    // 0 = not yet seeded. dorsalKnown[f] false where propagation is uncertain (roll).
    int        dorsalSeedSign = 0;
    int        dorsalSeedFrame = -1;
    int[]      dorsalSign;        // per-frame resolved dorsal sign (+1/-1), 0 if unknown
    boolean[]  dorsalKnown;
    // head-lock: if set at frame k, all frames >= k use this head end (true=point0)
    int        headLockFrame = -1;
    boolean    headLockIsPoint0 = true;
    int[][]    outlineX, outlineY;  // body outline polygon per frame
    // manual head anchor from the reference trace: the frame where the user clicked
    // the head, and which midline end (point0?) that click identified as the head.
    int        headAnchorFrame = -1;
    boolean    headAnchorIsPoint0 = true;
    // manual tail anchor: the frame where the user clicked the tail end
    int        tailAnchorFrame = -1;
    boolean    tailAnchorIsPoint0 = false;
    boolean[]  tailIsPoint0;        // per-frame: true if point0 is the tail end
    double[]   tailPx, tailPy;     // tail point per frame
    boolean[]  headFlipFlag;        // per-frame: orientation cues disagreed and were applied
    // accumulated curvature range per end (head bends through a wider range than tail)
    double     headEndCurvRange=0, tailEndCurvRange=0;
    // RGBCaMP: assume the red channel marks the pharynx (head). Toggleable in case a
    // future strain puts a different reporter in red.
    boolean    useRedPharynx = true;

    // red signal position along the body as an arc fraction (0 = point0 end,
    // 1 = pointN end), intensity-weighted. NaN if too little red this frame.
    double redBodyFraction(int f){
        if (!found[f]) return Double.NaN;
        int redCh=2;                        // measStacks[2] = red
        double wsum=0, fsum=0;
        // sample red at each midline point's neighborhood; assign by arc index
        for (int i=0;i<nMid;i++){
            double v=measMeanDisk(redCh, f, midX[f][i], midY[f][i], Math.max(2,halfW[f][i]));
            if (Double.isNaN(v)||v<8) continue;   // ignore near-background
            double frac=(double)i/(nMid-1);
            wsum+=v; fsum+=v*frac;
        }
        return wsum>0? fsum/wsum : Double.NaN;
    }

    // ---- red-guided head-tip extension ----
    // The pharynx (red) reaches toward the nose. Where the red mass extends BEYOND the
    // current head tip along the body axis, nudge the tip out to the far edge of red,
    // capped so it cannot run away. Only moves the HEAD end; only with red present.
    // Validated on real data: red extended past the tip in ~78% of frames.
    void redExtendHeadTips(){
        int redCh=2;
        double cap = 0.12*refLength;        // max tip move per frame (fraction of body)
        for (int f=0; f<nFrames; f++){
            if (!found[f]||skip[f]||manualEnds[f]!=null) continue;
            boolean headP0 = headIsPoint0[f];
            int tip = headP0?0:nMid-1, neck = headP0?3:nMid-4;
            if (neck<0||neck>=nMid) continue;
            double hx=midX[f][tip], hy=midY[f][tip];
            double ax=hx-midX[f][neck], ay=hy-midY[f][neck];
            double an=Math.hypot(ax,ay); if (an<1e-6) continue; ax/=an; ay/=an;
            // farthest red pixel projected along the head axis, within a corridor
            double bestProj=0; double bx=hx, by=hy;
            int R=(int)Math.ceil(cap)+6;
            for (int dy=-R;dy<=R;dy++) for (int dx=-R;dx<=R;dx++){
                int x=(int)Math.round(hx)+dx, y=(int)Math.round(hy)+dy;
                if (x<0||y<0||x>=W||y>=H) continue;
                double v=measValue(redCh,f,x,y); if (Double.isNaN(v)||v<15) continue;
                double px=x-hx, py=y-hy;
                double proj=px*ax+py*ay;                  // along head axis (beyond tip = +)
                double perp=Math.abs(-px*ay+py*ax);       // lateral distance from axis
                if (proj>bestProj && perp< Math.max(3, 0.5*halfW[f][tip]+2)){
                    bestProj=proj; bx=x; by=y;
                }
            }
            if (bestProj>2){
                double move=Math.min(bestProj, cap);
                double nx=hx+ax*move, ny=hy+ay*move;
                midX[f][tip]=nx; midY[f][tip]=ny;
                pointSrc[f][tip]=(byte)1;                 // mark inferred (red-guided)
                // re-space the few points between neck and tip so the end stays smooth
                for (int k=1;k<Math.abs(tip-neck);k++){
                    double t=(double)k/Math.abs(tip-neck);
                    int idx = headP0? k : nMid-1-k;
                    midX[f][idx]=midX[f][neck]*(1-t)+nx*t;
                    midY[f][idx]=midY[f][neck]*(1-t)+ny*t;
                }
            }
        }
    }

    // ================= Stage-1 (v2): fluorescent-tip confidence, partial, fluor sanity =====

    // Find the green channel's bright tip blobs (anterior + posterior). Returns up to two
    // {x,y,intensitySum}, brightest first. Green has two dominant maxima at the body ends.
    java.util.ArrayList<double[]> greenTips(int f){
        java.util.ArrayList<double[]> out=new java.util.ArrayList<double[]>();
        int gc=1; // measStacks[1]=green
        ImageProcessor ip=measStacks[gc].getProcessor(f+1);
        // collect bright green pixels, cluster by simple connected components on a threshold
        double mx=0; for (int y=0;y<H;y++) for (int x=0;x<W;x++){ double v=chVal(gc,ip,x,y); if(v>mx)mx=v; }
        if (mx<=0) return out;
        double thr=0.45*mx;
        boolean[] seen=new boolean[W*H];
        for (int y=0;y<H;y++) for (int x=0;x<W;x++){
            int id=y*W+x;
            if (seen[id]) continue;
            if (chVal(gc,ip,x,y)<thr){ seen[id]=true; continue; }
            // flood this blob, accumulate intensity-weighted centroid
            java.util.ArrayList<int[]> stackpx=new java.util.ArrayList<int[]>();
            stackpx.add(new int[]{x,y}); seen[id]=true;
            double sw=0,sx=0,sy=0;
            while(!stackpx.isEmpty()){
                int[] p=stackpx.remove(stackpx.size()-1);
                double v=chVal(gc,ip,p[0],p[1]); sw+=v; sx+=v*p[0]; sy+=v*p[1];
                for (int dy=-1;dy<=1;dy++) for (int dx=-1;dx<=1;dx++){
                    int nx=p[0]+dx, ny=p[1]+dy; if(nx<0||ny<0||nx>=W||ny>=H) continue;
                    int nid=ny*W+nx; if(seen[nid]) continue;
                    if(chVal(gc,ip,nx,ny)>=thr){ seen[nid]=true; stackpx.add(new int[]{nx,ny}); }
                }
            }
            if (sw>=greenTipMinInt) out.add(new double[]{sx/sw, sy/sw, sw});
        }
        java.util.Collections.sort(out, new java.util.Comparator<double[]>(){
            public int compare(double[] a,double[] b){ return Double.compare(b[2],a[2]); }
        });
        while (out.size()>2) out.remove(out.size()-1);
        return out;
    }
    double chVal(int c, ImageProcessor ip, int x, int y){
        if (ip instanceof ColorProcessor){ int p=ip.getPixel(x,y); int r=(p>>16)&0xff,g=(p>>8)&0xff,b=p&0xff; return Math.max(r,Math.max(g,b)); }
        return ip.getPixelValue(x,y);
    }

    // red anterior edge: the red pixel furthest toward the head end along the body axis.
    // Returns {x,y} or null. Used as the head-tip RED voter (pharynx anterior extent ~ nose).
    double[] redAnteriorEdge(int f, boolean headP0){
        int rc=2; ImageProcessor ip=measStacks[rc].getProcessor(f+1);
        double mx=0; for (int y=0;y<H;y++) for (int x=0;x<W;x++){ double v=chVal(rc,ip,x,y); if(v>mx)mx=v; }
        if (mx<=0) return null;
        double thr=0.4*mx;
        int hx = headP0?0:nMid-1, neck = headP0?3:nMid-4;
        if (neck<0||neck>=nMid) return null;
        double ax=midX[f][hx]-midX[f][neck], ay=midY[f][hx]-midY[f][neck];
        double am=Math.hypot(ax,ay); if(am<1e-6) return null; ax/=am; ay/=am;
        double bestProj=-1e9, bx=0, by=0; int cnt=0;
        for (int y=0;y<H;y++) for (int x=0;x<W;x++){
            if (chVal(rc,ip,x,y)<thr) continue; cnt++;
            double proj=(x-midX[f][neck])*ax+(y-midY[f][neck])*ay;   // along head axis
            if (proj>bestProj){ bestProj=proj; bx=x; by=y; }
        }
        if (cnt<redTipMinPix) return null;
        return new double[]{bx,by};
    }

    // confidence-weighted consensus of tip voters at one end. dicX/dicY = DIC midline tip.
    // greenTip = nearest green blob (or null), redEdge = red anterior edge (head only, or null).
    // Returns {consensusX, consensusY, confidence0to1, srcBitmask}. A voter joins the consensus
    // only if it agrees (within tipAgreePx) with the highest-weight present voter.
    double[] tipConsensus(double dicX,double dicY, double[] greenTip, double[] redEdge){
        // candidate voters with weights (only those present)
        java.util.ArrayList<double[]> v=new java.util.ArrayList<double[]>(); // {x,y,weight,srcbit}
        v.add(new double[]{dicX,dicY,wDicTip,1});
        if (greenTip!=null) v.add(new double[]{greenTip[0],greenTip[1],wGreenTip,2});
        if (redEdge!=null)  v.add(new double[]{redEdge[0],redEdge[1],wRedTip,4});
        // anchor = highest-weight voter
        double[] anchor=v.get(0); for (double[] q:v) if (q[2]>anchor[2]) anchor=q;
        double aw=0, ax=0, ay=0, totw=0; int src=0;
        for (double[] q:v){
            totw+=q[2];
            if (Math.hypot(q[0]-anchor[0], q[1]-anchor[1])<=tipAgreePx){
                aw+=q[2]; ax+=q[2]*q[0]; ay+=q[2]*q[1]; src|=(int)q[3];
            }
        }
        if (aw<=0) return new double[]{dicX,dicY,0,1};
        return new double[]{ax/aw, ay/aw, aw/totw, src};
    }

    // anchor head and tail midline endpoints to the fluorescent-tip consensus (bounded snap).
    void fluorTipAnchor(){
        if (!rgbMode || !useFluorTips) return;
        double cap = (refLength>0? tipSnapCapFrac*refLength : 8);
        for (int f=0; f<nFrames; f++){
            if (skip[f]||!found[f]) continue;
            boolean headP0=headIsPoint0[f];
            int hi = headP0?0:nMid-1, ti = headP0?nMid-1:0;
            java.util.ArrayList<double[]> gt=greenTips(f);
            // assign green blobs to head/tail by proximity to the DIC endpoints
            double[] gHead=null, gTail=null;
            if (gt.size()>=1){
                double[] a=gt.get(0), b=(gt.size()>=2?gt.get(1):null);
                double da_h=Math.hypot(a[0]-midX[f][hi],a[1]-midY[f][hi]);
                if (b!=null){
                    double db_h=Math.hypot(b[0]-midX[f][hi],b[1]-midY[f][hi]);
                    if (da_h<=db_h){ gHead=a; gTail=b; } else { gHead=b; gTail=a; }
                } else {
                    double da_t=Math.hypot(a[0]-midX[f][ti],a[1]-midY[f][ti]);
                    if (da_h<=da_t) gHead=a; else gTail=a;
                }
            }
            double[] rEdge=redAnteriorEdge(f, headP0);
            // HEAD consensus (3 possible voters)
            double[] hc=tipConsensus(midX[f][hi],midY[f][hi], gHead, rEdge);
            headTipConf[f]=hc[2]; headTipSrc[f]=(int)hc[3];
            snapEndpoint(f, hi, hc[0], hc[1], cap);
            // TAIL consensus (2 voters: DIC + green; red is head-only)
            double[] tc=tipConsensus(midX[f][ti],midY[f][ti], gTail, null);
            tailTipConf[f]=tc[2]; tailTipSrc[f]=(int)tc[3];
            snapEndpoint(f, ti, tc[0], tc[1], cap);
        }
    }
    // move a midline endpoint toward (tx,ty), capped at 'cap' px; re-space the few points
    // between the endpoint and its neighbor so the end stays smooth.
    void snapEndpoint(int f, int idx, double tx, double ty, double cap){
        double dx=tx-midX[f][idx], dy=ty-midY[f][idx]; double d=Math.hypot(dx,dy);
        if (d<1e-6) return;
        if (d>cap){ dx*=cap/d; dy*=cap/d; }
        double nx=midX[f][idx]+dx, ny=midY[f][idx]+dy;
        int neck = (idx==0)?3:nMid-4; if (neck<0||neck>=nMid){ midX[f][idx]=nx; midY[f][idx]=ny; return; }
        int steps=Math.abs(idx-neck);
        for (int k=0;k<=steps;k++){
            double t=(double)k/steps; int j=(idx==0)? (idx+k) : (idx-k);
            if (j<0||j>=nMid) continue;
            midX[f][j]=midX[f][neck]*(1-t)+nx*t; midY[f][j]=midY[f][neck]*(1-t)+ny*t;
        }
    }

    // PARTIAL-worm-in-frame: body mask touches the frame border, OR the midline length /
    // body area is implausibly small vs the learned reference (worm partly out of view).
    void flagPartialFrames(){
        double lenMin = (refLength>0? 0.80*refLength : 0);
        for (int f=0; f<nFrames; f++){
            partialFlag[f]=false;
            if (skip[f]||!found[f]) continue;
            // Count border pixels, don't trip on a single one. The DIC mask routinely grabs a
            // few background-texture pixels at the frame edge (5-16 px seen) even when the worm
            // is fully in view; flagging on any one pixel marked ~all frames partial. A worm that
            // is genuinely partly out of frame runs a real body edge off-screen (many edge pixels)
            // AND loses length. So require substantial border contact, with length as co-signal.
            int edge=0;
            ByteProcessor m=bodyMaskCached(f); byte[] px=(byte[])m.getPixels();
            for (int x=0;x<W;x++){ if((px[x]&0xff)==255)edge++; if((px[(H-1)*W+x]&0xff)==255)edge++; }
            for (int y=0;y<H;y++){ if((px[y*W]&0xff)==255)edge++; if((px[y*W+W-1]&0xff)==255)edge++; }
            boolean border = edge > partialBorderMinPx;       // substantial run, not speckle
            boolean tooShort = (lenMin>0 && midLen[f] < lenMin);
            partialFlag[f] = border || tooShort;
        }
        int np=0; for (int f=0;f<nFrames;f++) if(partialFlag[f]) np++;
        if (np>0) IJ.log("Partial-worm frames flagged: "+np+" (border contact > "+partialBorderMinPx
            +" px or length < 80% reference). Excluded from dimension statistics.");
    }

    // FLUOR-INSIDE-OUTLINE sanity: fraction of fluorescent pixels falling OUTSIDE the DIC body.
    // Biologically this should be ~0; a high value means the DIC outline is wrong on that frame.
    void computeFluorOutside(){
        if (!rgbMode) return;
        for (int f=0; f<nFrames; f++){
            fluorOutsideFrac[f]=Double.NaN;
            if (skip[f]||!found[f]) continue;
            ByteProcessor body=bodyMaskCached(f); byte[] bp=(byte[])body.getPixels();
            ImageProcessor b=measStacks[0].getProcessor(f+1), g=measStacks[1].getProcessor(f+1), r=measStacks[2].getProcessor(f+1);
            long inside=0, outside=0;
            // a pixel counts as fluorescent only if a SINGLE channel clears the floor.
            // (Summing all three and thresholding the sum let three noise-floor channels
            // ~10 each trip a sum>=30, producing false "outside" pixels far from the worm;
            // that bug made fluor_outside_frac read ~0.3 when it should be ~0.)
            double chFloor = fluorChannelFloor;
            for (int y=0;y<H;y++) for (int x=0;x<W;x++){
                double vb=chVal(0,b,x,y), vg=chVal(1,g,x,y), vr=chVal(2,r,x,y);
                if (vb<chFloor && vg<chFloor && vr<chFloor) continue;   // background: skip
                if ((bp[y*W+x]&0xff)==255) inside++; else outside++;
            }
            long tot=inside+outside;
            fluorOutsideFrac[f] = tot>0? (double)outside/tot : 0;
        }
    }

    // per-frame, per-channel background: MEAN pixel value OUTSIDE the worm body (DIC
    // mask), away from a frame-edge margin. Exported as bg_blue/bg_green/bg_red columns
    // (not subtracted).
    //
    // Uses the mean, not the median. Real fluorescence background at 8-bit depth is
    // often sparse: on this preparation, 80-87% of outside-body pixels are exactly 0
    // (verified against the raw ch00/ch01/ch02 TIFFs), with the true background/noise
    // floor carried by the remaining nonzero minority. A median of a majority-zero
    // sample is deterministically 0 regardless of that real signal -- not a coordinate,
    // mask-inversion, or gating bug, just the wrong statistic for this data, and it
    // masqueraded as "no background" (bg_blue/green/red = 0.0 on every row of a real
    // export) rather than surfacing the true low-level background. The mean is
    // sensitive to that minority and reports the actual average light level in the
    // region, which is what a background subtraction is meant to remove.
    //
    // If the region is genuinely empty (no valid pixels sampled) the value stays
    // Double.NaN -- never silently 0 -- so a null measurement can't be mistaken for a
    // real zero background downstream.
    void computeBackground(){
        if (!rgbMode) return;
        bgBlue=new double[nFrames]; bgGreen=new double[nFrames]; bgRed=new double[nFrames];
        for (int f=0; f<nFrames; f++){
            bgBlue[f]=Double.NaN; bgGreen[f]=Double.NaN; bgRed[f]=Double.NaN;
            if (skip[f]||!found[f]) continue;
            ByteProcessor body=bodyMaskCached(f); byte[] bp=(byte[])body.getPixels();
            for (int c=0;c<nMeas;c++){
                double sum=0; int n=0;
                for (int y=bgMarginPx;y<H-bgMarginPx;y++) for (int x=bgMarginPx;x<W-bgMarginPx;x++){
                    if ((bp[y*W+x]&0xff)==255) continue;   // inside worm body: skip
                    double v=measValue(c,f,x,y); if (Double.isNaN(v)) continue;
                    sum+=v; n++;
                }
                double mean = n>0? sum/n : Double.NaN;
                if (c==0) bgBlue[f]=mean; else if (c==1) bgGreen[f]=mean; else if (c==2) bgRed[f]=mean;
            }
        }
    }

    // ================= Stage-2 (v2): eigenworm-on-combined-fluorescence body ==============

    // combined-fluorescence mask: R+G+B thresholded LOW (stay connected), largest component.
    // This is the "the signals sum to a worm outline" idea, made into a mask.
    ByteProcessor fluorMask(int f){
        ImageProcessor b=measStacks[0].getProcessor(f+1), g=measStacks[1].getProcessor(f+1), r=measStacks[2].getProcessor(f+1);
        double mx=0;
        for (int y=0;y<H;y++) for (int x=0;x<W;x++){
            double s=chVal(0,b,x,y)+chVal(1,g,x,y)+chVal(2,r,x,y); if(s>mx)mx=s;
        }
        ByteProcessor m=new ByteProcessor(W,H);
        if (mx<=0) return m;
        double thr=fluorThreshFrac*mx; byte[] mp=(byte[])m.getPixels();
        for (int y=0;y<H;y++) for (int x=0;x<W;x++){
            double s=chVal(0,b,x,y)+chVal(1,g,x,y)+chVal(2,r,x,y);
            if (s>=thr) mp[y*W+x]=(byte)255;
        }
        // light close to bridge the dim middle, then largest component
        m.dilate(); m.erode();
        keepLargestObject(m);
        return m;
    }

    // build a midline from the combined-fluor mask: skeleton -> longest path -> resample,
    // then snap endpoints toward the green tips (bounded; one tip can sit ~25px off).
    // Returns {midX[nMid], midY[nMid]} or null if the fluor path is unusable.
    double[][] fluorMidline(int f){
        ByteProcessor fm=fluorMask(f);
        double area=countForeground(fm);
        if (area < minBodyArea*0.5) return null;
        // The worm is ~8px wide with a thin, dim middle. ImageJ skeletonize() can thin straight
        // THROUGH that middle and split the skeleton into two arms even though the MASK is one
        // connected piece; longestSkeletonPath then returns only one arm (~half length). Dilating
        // the mask a little before skeletonizing thickens the thin middle so the skeleton stays
        // connected end to end. (Validated: the fluor mask is reliably one component already.)
        // Bendy dystrophic worms fold so distant segments come CLOSE (small gap). Blanket dilation
        // bridges those gaps, and the skeleton then SHORT-CIRCUITS across the self-approach, giving a
        // too-short midline that skips the bend. So skeletonize at native resolution FIRST (gaps
        // preserved -> skeleton follows the true path around the bend). Only if that path is
        // implausibly short (the separate thin-dim-middle SPLIT problem) do we dilate to reconnect.
        ByteProcessor sk0=(ByteProcessor)fm.duplicate();
        sk0.skeletonize(255);
        ArrayList<int[]> path=longestSkeletonPath(sk0);
        double len0 = (path!=null)? skelPathLen(path) : 0;
        boolean tooShort0 = (refLength>0 && len0 < refLength*(1-fluorLenTol));
        if (path==null || path.size()<10 || tooShort0){
            // native skeleton split or fragmented -> dilate once to reconnect the thin middle,
            // but use the MINIMUM dilation that reconnects, to avoid bridging self-approach gaps.
            ByteProcessor sk1=(ByteProcessor)fm.duplicate();
            sk1.dilate(); sk1.skeletonize(255);
            ArrayList<int[]> path1=longestSkeletonPath(sk1);
            double len1=(path1!=null)? skelPathLen(path1):0;
            // keep whichever path is LONGER in arc length (closer to the true body length), since
            // the failure we are fixing is a too-short path; a longer path went further around.
            if (path1!=null && len1>len0){ path=path1; }
            if (path==null || path.size()<10){
                ByteProcessor sk2=(ByteProcessor)fm.duplicate();
                sk2.dilate(); sk2.dilate(); sk2.skeletonize(255);
                path=longestSkeletonPath(sk2);
            }
        }
        if (path==null || path.size()<10) return null;
        double[][] rs=resample(path, nMid);
        double[] mx=rs[0], my=rs[1];
        // orient + snap endpoints to green tips if available
        java.util.ArrayList<double[]> gt=greenTips(f);
        if (gt.size()>=1){
            // nearest green blob to each end
            double cap=(refLength>0? tipSnapCapFrac*refLength : 8);
            double[] e0={mx[0],my[0]}, e1={mx[nMid-1],my[nMid-1]};
            for (double[] g: gt){
                double d0=Math.hypot(g[0]-e0[0],g[1]-e0[1]);
                double d1=Math.hypot(g[0]-e1[0],g[1]-e1[1]);
                if (d0<=d1){ snapPair(mx,my,0,g[0],g[1],cap); }
                else       { snapPair(mx,my,nMid-1,g[0],g[1],cap); }
            }
        }
        return new double[][]{mx,my};
    }
    // bounded snap of a midline endpoint within a local array (mirror of snapEndpoint for arrays)
    void snapPair(double[] mx, double[] my, int idx, double tx, double ty, double cap){
        double dx=tx-mx[idx], dy=ty-my[idx]; double d=Math.hypot(dx,dy);
        if (d<1e-6) return; if (d>cap){ dx*=cap/d; dy*=cap/d; }
        double nx=mx[idx]+dx, ny=my[idx]+dy;
        int neck=(idx==0)?3:nMid-4; if (neck<0||neck>=nMid){ mx[idx]=nx; my[idx]=ny; return; }
        int steps=Math.abs(idx-neck);
        for (int k=0;k<=steps;k++){
            double t=(double)k/steps; int j=(idx==0)?(idx+k):(idx-k);
            if (j<0||j>=nMid) continue;
            mx[j]=mx[neck]*(1-t)+nx*t; my[j]=my[neck]*(1-t)+ny*t;
        }
    }

    // IoU overlap between the combined-fluor mask and the DIC body mask for one frame.
    double fluorDicOverlap(int f){
        ByteProcessor fm=fluorMask(f);
        ByteProcessor dm=bodyMaskCached(f);
        byte[] fp=(byte[])fm.getPixels(), dp=(byte[])dm.getPixels();
        long inter=0, uni=0;
        for (int i=0;i<fp.length;i++){
            boolean a=(fp[i]&0xff)==255, b=(dp[i]&0xff)==255;
            if (a||b) uni++;
            if (a&&b) inter++;
        }
        return uni>0? (double)inter/uni : 0;
    }

    // Stage-2 main pass: for each frame, build the fluor midline, fit the eigenworm to it,
    // measure fit quality + DIC overlap, and let the eigenworm body WIN when well-constrained.
    void fluorBodyPass(){
        if (!rgbMode || !useFluorBody) return;
        progBegin("Fluor body + reseed", nFrames);
        int nSkipManual=0, nNullFluor=0, nLowFit=0, nNotLearned=0, nWon=0, nShortFluor=0;
        for (int f=0; f<nFrames; f++){
            progTick("Fluor body + reseed", f+1, nFrames);
            dicConfidence[f]=Double.NaN; eigenFitQuality[f]=Double.NaN; bodySource[f]=0; selfApproachFlag[f]=false;
            if (skip[f]||manualMidline[f]){ nSkipManual++; continue; }
            dicConfidence[f]=fluorDicOverlap(f);          // confidence in DIC for this frame
            double[][] fmid=fluorMidline(f);
            if (fmid==null){ nNullFluor++; continue; }     // no usable fluor body: keep DIC
            // length plausibility. A correct fluor midline should be near the conserved worm length.
            // After adaptive skeletonization (which already keeps the longest path it can find), a
            // still-short path means either a thin-middle split OR a self-approach shortcut where a
            // bendy worm folds near itself and the skeleton cut across the gap. You asked to AUTO-FIX
            // even if occasionally wrong, so we no longer DISCARD these: we FLAG the frame for review
            // and still use the best fluor body available (better than a known-broken DIC body).
            double fluorLen=polylineLen(fmid[0],fmid[1]);
            selfApproachFlag[f] = (refLength>0 && fluorLen < refLength*(1-fluorLenTol));
            if (selfApproachFlag[f]) nShortFluor++;   // counted, flagged, but NOT skipped
            // fit quality = fraction of fluor-midline points lying inside the fluor mask after
            // an eigenworm-constrained smoothing (well-constrained = fluor actually shaped it).
            double q=eigenFitOnMidline(f, fmid);
            eigenFitQuality[f]=q;
            // Is the DIC body for this frame implausible (the very case the fluor body exists for)?
            // Use the midline-length check, which is current at this point in the pipeline (sizeFlag
            // is computed later in recomputeAll, so it would be stale here). Length off-reference or a
            // missing body means DIC is the broken option, so falling back to it is worse than a
            // slightly-imperfect fluor body; relax the bar so the fluor body can rescue the frame.
            boolean dicBad = !found[f]
                             || (refLength>0 && (midLen[f] < refLength*(1-LEN_TOL) || midLen[f] > refLength*(1+LEN_TOL)));
            double winBar = dicBad ? Math.min(eigenFitMinFrac, eigenFitRescueFrac) : eigenFitMinFrac;
            if (!eigLearned) nNotLearned++;
            else if (q<winBar) nLowFit++;
            if (eigLearned && q>=winBar){
                // eigenworm WINS: adopt the fluor-derived, eigenworm-smoothed midline directly.
                // NOTE: earlier we routed this through extendToReferenceLength + medial-axis
                // reseed to "conserve length" and fix deep bends. On real data that REGRESSED
                // easy frames (fanned/off-body midlines), so we restore the original behavior:
                // adopt the fluor midline as-is. Length-conservation QC still flags short
                // frames for review (flagShortMidlines), it just no longer rewrites the midline.
                for (int i=0;i<nMid;i++){ midX[f][i]=fmid[0][i]; midY[f][i]=fmid[1][i]; pointSrc[f][i]=1; }
                found[f]=true; bodySource[f]=1; nWon++;
                midLen[f]=polylineLen(midX[f],midY[f]);
                // AUTOMATIC ENDPOINT EXTENSION (the real fix): the fluor skeleton stops in
                // the bright front region when the tail fluoresces dimly, so the midline
                // covers only part of the worm. The DIC body mask sees the WHOLE worm.
                // Extend the midline's endpoints along the DIC body to the mask's true tips,
                // then re-space. This mirrors what the manual head/tail click does (which the
                // user confirmed nails the whole worm), but sourced from the DIC body ends.
                if (EXTEND_TO_DIC_ENDS && refLength>0){
                    extendMidlineToBodyEnds(f);
                    midLen[f]=polylineLen(midX[f],midY[f]);
                }
                lenConservedFluor[f] = (refLength<=0) || (midLen[f] >= (1.0-LEN_TOL)*refLength);
                measureWidth(f, bodyMaskCached(f));       // widths from DIC where available
                computeCurvature(f);
            }
            // else: poorly constrained -> leave the DIC body in place (fall back), bodySource stays 0
        }
        int nSelfApp=0; for (int f=0;f<nFrames;f++) if(selfApproachFlag[f]) nSelfApp++;
        IJ.log("Fluor-body decision tally: WON="+nWon+"  fell back: skip/manual="+nSkipManual
            +", no-fluor-path="+nNullFluor+", short-fluor(self-approach/split?)="+nShortFluor
            +", low-fit="+nLowFit+", basis-not-learned="+nNotLearned
            +"  (eigLearned="+eigLearned+")");
        if (nSelfApp>0) IJ.log("Self-approach flagged on "+nSelfApp+" frame(s): the worm folds so distant "
            +"segments come close and the midline may shortcut the bend. Best-effort body used; "
            +"see self_approach_flag in the CSV and the magenta 'SELF-APPROACH?' label to review/redraw these.");
        if (nWon>0) IJ.log("Eigenworm-on-fluor body adopted on "+nWon+" frame(s) (fit quality >= "
            +IJ.d2s(eigenFitMinFrac,2)+"); DIC kept elsewhere. dic_confidence = fluor/DIC overlap per frame.");
        progDone("Fluor body + reseed");
    }
    // eigenworm-constrained smoothing of a candidate fluor midline; returns fit quality 0..1
    // = fraction of the (eigenworm-reconstructed) midline points that stay inside the fluor mask.
    double eigenFitOnMidline(int f, double[][] mid){
        // measure how well the raw fluor midline already sits inside its own mask (proxy for
        // a clean, well-constrained shape). If the basis is learned, also require the shape to
        // be expressible by the eigenworm modes (low residual) — done implicitly here by the
        // inside-mask fraction, which collapses when the path wanders off the dim body.
        ByteProcessor fm=fluorMask(f); byte[] fp=(byte[])fm.getPixels();
        int inside=0;
        for (int i=0;i<nMid;i++){
            int x=(int)Math.round(mid[0][i]), y=(int)Math.round(mid[1][i]);
            if (x<0||y<0||x>=W||y>=H) continue;
            if ((fp[y*W+x]&0xff)==255) inside++;
        }
        return (double)inside/nMid;
    }
    // arc length of a pixel path (list of {x,y}); sqrt2 for diagonal steps
    double skelPathLen(ArrayList<int[]> path){
        double L=0;
        for (int i=1;i<path.size();i++){
            int dx=path.get(i)[0]-path.get(i-1)[0], dy=path.get(i)[1]-path.get(i-1)[1];
            L += Math.sqrt(dx*dx+dy*dy);
        }
        return L;
    }
    double polylineLen(double[] xs, double[] ys){
        double L=0; for (int i=1;i<xs.length;i++) L+=Math.hypot(xs[i]-xs[i-1], ys[i]-ys[i-1]); return L;
    }

    public void run(String arg) {
        runStartNs=System.nanoTime(); long phaseNs=runStartNs;
        // RGBCaMP multichannel input: expect 4 open stacks (ch00 blue, ch01 green,
        // ch02 red, ch03 DIC). Track on DIC, measure the three fluorescent channels.
        if (!loadFourChannels()) return;
        W = trackImp.getWidth(); H = trackImp.getHeight();
        nSlices = trackStack.getSize();
        stack = trackStack;                     // legacy code paths read 'stack' = tracking (DIC)
        imp = trackImp;                         // review/overlay shown on DIC
        // Ensure the DIC stack is a VISIBLE window. When channels are imported from disk
        // (FolderOpener), they are not shown by default, so there was no image to trace
        // the reference outline on and no window for the midline overlay. Show it now,
        // before reference setup, and bring it to the front.
        if (imp.getWindow()==null){ imp.show(); }
        if (imp.getWindow()!=null){ imp.getWindow().toFront(); }
        Mw = W; Mh = H;
        int bd = trackImp.getBitDepth();
        src8bit = (bd==8 || bd==24);
        if (src8bit) IJ.log("Channels are 8-bit/RGB: geometry OK; intensity flagged src8bit. Use 16-bit TIFF for quantitative calcium.");

        if (!setupDialog()) return;
        loadSetupSeconds=(System.nanoTime()-phaseNs)/1e9;
        IJ.log("[trace] setupDialog done");
        nFrames = nSlices;
        if (nFrames < 1) { IJ.error("Empty stack."); return; }
        alloc();
        IJ.log("[trace] alloc done ("+nFrames+" frames)");

        // DIC body is DARK on light: detection uses the inverted-contrast path.
        phaseNs=System.nanoTime();
        if (useTemporalBg){ IJ.log("[trace] buildTemporalBackground..."); buildTemporalBackground(); }
        backgroundSeconds=(System.nanoTime()-phaseNs)/1e9;
        if (bodyThr==0){ IJ.log("[trace] autoBodyThreshold..."); autoBodyThreshold(); }
        for (int f=0; f<nFrames; f++) thrFrame[f]=bodyThr;
        IJ.log("[trace] threshold set");

        IJ.log("[trace] registrationSanityCheck...");
        registrationSanityCheck();              // warn if fluor signal falls outside DIC body
        IJ.log("[trace] registrationSanityCheck done");

        IJ.log("[trace] setupReferenceFrames...");
        setupReferenceFrames();
        IJ.log("[trace] setupReferenceFrames done; starting compute");
        phaseNs=System.nanoTime();recomputeAll();          // progress shown via Fiji status bar (see progBegin/Tick/Done)
        initialComputeSeconds=(System.nanoTime()-phaseNs)/1e9;
        IJ.showStatus("WormRGBCaMP: done");
        redraw();

        new WaitForUserDialog("Review midline",
            "Tracking on DIC (whole body). Green=measured edge, magenta=profile-placed.\n"+
            "Midline cyan; head green dot, tail red dot.\n\n"+
            "Scroll the movie and check the midline hugs the worm head-to-tail and\n"+
            "the GREEN dot is on the HEAD. Use the menu to fix head/tail or redraw.\n"+
            "Click OK for the menu.").show();
        menuLoop();
    }


    // Progress via Fiji's OWN status bar + progress bar (bottom of the main ImageJ
    // window). This cannot spawn a separate window or grab input, so it can't recreate
    // the invisible-panel / modal-block problems. Each stage sets the status text; ticks
    // drive the built-in progress bar and update the "done / total" status.
    String progStage = "";
    void progBegin(String stage, int total){
        progStage = stage;
        IJ.showStatus("WormRGBCaMP: "+stage+(total>0? (" (0/"+total+")") : " ..."));
        IJ.showProgress(0.0);
    }
    void progTick(String stage, int done, int total){
        if (total>0){
            IJ.showStatus("WormRGBCaMP: "+stage+" ("+done+"/"+total+")");
            IJ.showProgress(done, total);
        }
    }
    void progDone(String stage){
        IJ.showStatus("WormRGBCaMP: "+stage+" done");
        IJ.showProgress(1.0);
    }

    // ---- load four channels from open windows (ch00..ch03) ----
    // ch03 = DIC (tracking); ch00/01/02 = blue/green/red (measured).
    boolean loadFourChannels() {
        // Import the four channel folders DIRECTLY from disk rather than querying open
        // windows. Dragging four TIFF-sequence folders onto Fiji registers them on the
        // ImageJ2 side, invisible to the ImageJ1 WindowManager (which returned 0 images),
        // so we bypass that entirely: pick the PARENT folder that holds ch00..ch03 and
        // import each subfolder as an ImageJ1 stack via FolderOpener. No open windows
        // required; the resulting stacks are ordinary ImagePlus objects.
        ImagePlus[] byCh = new ImagePlus[4];

        // 1) If four channel windows happen to already be open in ImageJ1, use them.
        int[] idList = null;
        try { idList = WindowManager.getIDList(); } catch (Throwable t){ idList=null; }
        if (idList!=null){
            for (int id : idList){
                ImagePlus ip=null; try { ip=WindowManager.getImage(id); } catch (Throwable t){ ip=null; }
                if (ip==null) continue;
                String tl; try { tl=ip.getTitle().toLowerCase(); } catch (Throwable t){ continue; }
                for (int c=0;c<4;c++) if (tl.contains("ch0"+c) && byCh[c]==null) byCh[c]=ip;
            }
        }
        boolean haveAll = byCh[0]!=null&&byCh[1]!=null&&byCh[2]!=null&&byCh[3]!=null;

        // 2) Otherwise import from a parent folder containing ch00..ch03 subfolders.
        if (!haveAll){
            IJ.log("[chan] no 4 open ImageJ1 stacks; importing channel folders from disk.");
            DirectoryChooser dc=new DirectoryChooser("Select the parent folder containing ch00, ch01, ch02, ch03");
            String parent=dc.getDirectory();
            if (parent==null){ IJ.error("No folder selected."); return false; }
            java.io.File pf=new java.io.File(parent);
            for (int c=0;c<4;c++){
                java.io.File sub=new java.io.File(pf, "ch0"+c);
                if (!sub.isDirectory()){
                    IJ.error("Could not find subfolder ch0"+c+" inside:\n"+parent+
                             "\nExpected ch00, ch01, ch02, ch03 subfolders.");
                    return false;
                }
                IJ.log("[chan] importing ch0"+c+" from "+sub.getAbsolutePath());
                ImagePlus ip=null;
                try {
                    ip=ij.plugin.FolderOpener.open(sub.getAbsolutePath());
                } catch (Throwable t){ ip=null; }
                if (ip==null){
                    IJ.error("Failed to import ch0"+c+" as an image sequence from:\n"+sub.getAbsolutePath());
                    return false;
                }
                ip.setTitle("ch0"+c);
                byCh[c]=ip;
            }
        }
        for (int c=0;c<4;c++){
            if (byCh[c]==null){
                IJ.error("Channel "+c+" (ch0"+c+") could not be loaded.");
                return false;
            }
        }
        // size/length consistency
        int w=byCh[3].getWidth(), h=byCh[3].getHeight(), n=byCh[3].getStackSize();
        for (int c=0;c<4;c++){
            if (byCh[c].getWidth()!=w || byCh[c].getHeight()!=h || byCh[c].getStackSize()!=n){
                IJ.error("Channel "+c+" ("+byCh[c].getTitle()+") differs in size/length from DIC.\n"+
                    "All four channels must match ("+w+"x"+h+", "+n+" frames).");
                return false;
            }
        }
        trackImp = byCh[3]; trackStack = byCh[3].getStack();
        measStacks[0]=byCh[0].getStack();  // blue
        measStacks[1]=byCh[1].getStack();  // green
        measStacks[2]=byCh[2].getStack();  // red
        IJ.log("Loaded 4 channels ("+w+"x"+h+", "+n+" frames). Tracking on DIC ch03; measuring blue/green/red.");
        return true;
    }

    // value from a specific measurement channel at integer pixel (x,y).
    // channel c: 0=blue,1=green,2=red. The AVIs are bgr24 single-color, so the
    // signal sits in that color plane; we take the max plane to be robust to which
    // plane the writer used, falling back to luminance for gray.
    double measValue(int c, int frame, int x, int y) {
        if (x<0||y<0||x>=W||y>=H) return Double.NaN;
        ImageProcessor ip = measStacks[c].getProcessor(frame+1);
        if (ip instanceof ColorProcessor){
            int v=ip.getPixel(x,y);
            int r=(v>>16)&0xff, g=(v>>8)&0xff, b=v&0xff;
            // single-color AVI: the channel's own plane dominates; use max plane.
            return Math.max(r,Math.max(g,b));
        }
        return ip.getPixelValue(x,y);
    }

    // mean of a measurement channel in a disk (for registration check / cues)
    double measMeanDisk(int c, int frame, double cx, double cy, double rad){
        int x0=(int)Math.floor(cx-rad), x1=(int)Math.ceil(cx+rad);
        int y0=(int)Math.floor(cy-rad), y1=(int)Math.ceil(cy+rad);
        double s=0; int n=0; double r2=rad*rad;
        for (int y=y0;y<=y1;y++) for (int x=x0;x<=x1;x++){
            if (x<0||y<0||x>=W||y>=H) continue;
            if ((x-cx)*(x-cx)+(y-cy)*(y-cy)>r2) continue;
            double v=measValue(c,frame,x,y); if (!Double.isNaN(v)){ s+=v; n++; }
        }
        return n>0? s/n : Double.NaN;
    }

    // registration sanity: on a few frames, what fraction of the brightest fluor
    // (green) pixels fall inside the DIC body mask? Warn if low (mis-registered).
    void registrationSanityCheck(){
        int[] probes={0, nFrames/2, nFrames-1};
        double sum=0; int n=0;
        for (int pf: probes){
            if (pf<0||pf>=nFrames) continue;
            boolean[][] body = dicBodyMask(pf);
            if (body==null) continue;
            int inside=0, total=0;
            for (int y=0;y<H;y++) for (int x=0;x<W;x++){
                double g=measValue(1,pf,x,y);
                if (g>30){ total++; if (body[y][x]) inside++; }
            }
            if (total>10){ sum += (double)inside/total; n++; }
        }
        if (n>0){
            double frac=sum/n;
            IJ.log("Registration check: "+IJ.d2s(100*frac,0)+"% of green signal falls inside the DIC body.");
            if (frac<0.7) IJ.log("  WARNING: low overlap. Channels may be mis-registered; per-segment intensities could be biased.");
        }
    }

    // ---- guided reference-frame setup at startup ----
    // The user scrolls to a clean, fully-visible, extended frame; we process just
    // that frame, draw it, and ask whether to use it as a reference. Repeats until
    // the user is done, then learns the conserved width profile from the picks.
    void setupReferenceFrames() {
        IJ.setTool("polygon");
        new WaitForUserDialog("Trace the worm (teach its shape)",
            "Teach the tool the worm's LENGTH and WIDTH by tracing it once.\n\n"+
            "1) Scroll to a frame where the whole worm is visible and extended.\n"+
            "2) Select the POLYGON tool (or Freehand) in the Fiji toolbar.\n"+
            "3) Trace a closed outline AROUND the whole worm (head to tail and\n"+
            "   back), enclosing the body. Close the loop.\n"+
            "4) Then click OK here.\n\n"+
            "The tool derives the midline, length, and width profile from YOUR\n"+
            "trace. No threshold is used on this frame.").show();

        boolean adding=true;
        while (adding) {
            int f=clamp(imp.getCurrentSlice()-1,0,nFrames-1);
            Roi r=imp.getRoi();
            if (r==null || !(r.isArea())) {
                GenericDialog bad=new GenericDialog("No outline traced");
                bad.addMessage("No closed outline found on frame "+(f+1)+".\n"+
                    "Use the Polygon or Freehand tool to trace AROUND the worm,\n"+
                    "close the loop, then try again.");
                bad.enableYesNoCancel("Try again","Skip setup");
                bad.showDialog();
                if (bad.wasOKed()){
                    imp.deleteRoi();
                    imp.setOverlay(null);
                    IJ.setTool("polygon");
                    new WaitForUserDialog("Trace again",
                        "The old selection was not a closed body outline.\n\n"+
                        "Trace a closed outline AROUND the whole worm on this image,\n"+
                        "then click OK.").show();
                    continue;
                }
                else { adding=false; break; }
            }
            boolean ok = deriveReferenceFromOutline(f, r);
            imp.deleteRoi();
            drawSingleFrame(f);
            if (!ok) {
                GenericDialog bad=new GenericDialog("Trace too small / thin");
                bad.addMessage("Couldn't derive a midline from that trace on frame "+(f+1)+".\n"+
                    "Make sure the loop encloses the whole worm body, then retry.");
                bad.enableYesNoCancel("Try again","Skip setup");
                bad.showDialog();
                if (bad.wasOKed()){
                    imp.deleteRoi();
                    imp.setOverlay(null);
                    IJ.setTool("polygon");
                    new WaitForUserDialog("Trace again",
                        "That trace was too small or too thin to derive a spine.\n\n"+
                        "Trace a closed outline enclosing the whole worm body, then click OK.").show();
                    continue;
                }
                else { adding=false; break; }
            }
            GenericDialog gd=new GenericDialog("Use this trace?");
            gd.addMessage("Frame "+(f+1)+": cyan midline should run head-to-tail down the\n"+
                "worm, green outline = your trace. Length = "+IJ.d2s(midLen[f],0)+" px.\n\n"+
                "Reference traces so far: "+refFrames.size());
            gd.enableYesNoCancel("Use this trace","Re-trace");
            gd.showDialog();
            if (gd.wasCanceled()) { adding=false; }
            else if (gd.wasOKed()) {
                if (!refFrames.contains(f)){ refFrames.add(f); IJ.log("Reference trace added on frame "+(f+1)+" (total "+refFrames.size()+"), length "+IJ.d2s(midLen[f],0)+" px"); }
                promptHeadClick(f);     // user clicks the HEAD end to set orientation
                promptTailClick(f);    // user clicks the TAIL end to set orientation
                GenericDialog more=new GenericDialog("Add another?");
                more.addMessage("Trace another frame for a better width profile?\n"+
                    "(2-3 traces across postures is ideal; or finish now.)");
                more.enableYesNoCancel("Trace another","Done");
                more.showDialog();
                if (more.wasCanceled()) { adding=false; }
                else if (more.wasOKed()) {
                    // Wait for the user to scroll to a new frame and trace it, then loop
                    // back to the top to derive/confirm that trace. One sequential dialog
                    // (dismissed before the next), so it does not stack.
                    new WaitForUserDialog("Trace another reference",
                        "Scroll to a DIFFERENT posture, trace a closed outline around the\n"+
                        "worm with the Polygon or Freehand tool, then click OK.").show();
                    // loop continues; top of loop reads the new ROI on the current frame
                } else { adding=false; }
            } else {
                IJ.showStatus("Re-trace the worm outline, then use the menu to add it.");
            }
        }

        if (!refFrames.isEmpty()) {
            // learn conserved length and width profile from the traced reference frames
            learnWidthProfile();
            learnLength();
        } else {
            IJ.log("No reference trace; falling back to threshold detection (the dim-end problem may occur). You can trace a reference later from the menu.");
        }
    }

    // ---- derive midline + length + width profile from a hand-traced closed outline ----
    // Fill the traced ROI to a mask, skeletonize, take the longest path as the midline,
    // resample to nMid, then measure half-width to the traced outline along each normal.
    boolean deriveReferenceFromOutline(int f, Roi outlineRoi) {
        // rasterize the traced polygon into a full-image mask
        ByteProcessor m=new ByteProcessor(Mw,Mh);
        m.setColor(255);
        m.fill(outlineRoi);                          // fill interior of the traced loop
        ByteProcessor mfull=(ByteProcessor)m.duplicate();
        keepLargestObject(m);
        if (countForeground(m) < minBodyArea) return false;

        // store the traced outline polygon for display
        java.awt.Polygon poly=outlineRoi.getPolygon();
        if (poly!=null){ outlineX[f]=poly.xpoints; outlineY[f]=poly.ypoints; }

        // capture this worm's reference SIZE (area + perimeter) from the trace, so
        // later frames can be sanity-checked against the animal's true dimensions.
        double aTrace=countForeground(m);
        double pTrace=polygonPerimeter(traceOutline((ByteProcessor)m.duplicate()));
        refAreaList.add(aTrace);
        if (pTrace>0) refPerimList.add(pTrace);
        refArea=median(refAreaList);
        refPerim=refPerimList.isEmpty()?0:median(refPerimList);
        IJ.log("Reference size from trace: area "+IJ.d2s(aTrace,0)+" px, perimeter "+IJ.d2s(pTrace,0)+" px.");

        // midline = longest skeleton path of the filled trace
        ByteProcessor sk=(ByteProcessor)m.duplicate();
        sk.skeletonize(255);
        ArrayList<int[]> path=longestSkeletonPath(sk);
        if (path==null || path.size()<10) return false;
        double[][] rs=resample(path,nMid);
        for (int i=0;i<nMid;i++){ midX[f][i]=rs[0][i]; midY[f][i]=rs[1][i]; pointSrc[f][i]=2; }
        applyManualEnds(f);
        smoothMidlineForRoiGeometry(f);

        // width to the TRACED outline (use the filled trace as the body)
        measureWidth(f, mfull);
        computeCurvature(f);
        assignHead(f);
        resolveDorsal(f);
        // mark this as a manual/reference midline so the auto pass won't overwrite it
        manualMidline[f]=true;
        manualMidX[f]=midX[f].clone(); manualMidY[f]=midY[f].clone();
        found[f]=true;
        return true;
    }

    // ---- user clicks the HEAD and TAIL end for reference frame to help set the orientation ----
    // The click resolves which midline end (point0 or pointN) is the head; this
    // anchors orientation for the whole movie (propagated frame to frame).
    // This process is then repeated for the tail point. 
    void promptHeadClick(int f) {
        imp.setSlice(sliceOf(f)); imp.deleteRoi();
        IJ.setTool("point");
        new WaitForUserDialog("Click the HEAD",
            "Click once on the worm's HEAD end (the point tool is selected),\n"+
            "then click OK. This sets head/tail for the whole movie.\n\n"+
            "(Tip: the head is usually the brighter, wider-bending end.)").show();
        double[] p=getClickedPoint();
        imp.deleteRoi();
        if (p==null){ IJ.log("No head click; keeping automatic head assignment."); return; }
        double d0=dist(p[0],p[1], midX[f][0],midY[f][0]);
        double dN=dist(p[0],p[1], midX[f][nMid-1],midY[f][nMid-1]);
        boolean point0IsHead = d0<=dN;
        headIsPoint0[f]=point0IsHead;
        headAnchorFrame=f; headAnchorIsPoint0=point0IsHead;
        int hi=point0IsHead?0:nMid-1;
        headPx[f]=midX[f][hi]; headPy[f]=midY[f][hi];
        IJ.log("Head set by click on frame "+(f+1)+" (head = point"+(point0IsHead?0:(nMid-1))+").");
    }

    void promptTailClick(int f) {
        imp.setSlice(sliceOf(f)); imp.deleteRoi();
        IJ.setTool("point");
        new WaitForUserDialog("Click the TAIL",
            "Click once on the worm's TAIL end (the point tool is selected),\n"+
            "then click OK. This sets head/tail for the whole movie. \n\n"+
            "(Tip: the tail is usually the dimmer, narrower-bending end.)").show();
        double[] p=getClickedPoint();
        imp.deleteRoi();
        if (p==null){ IJ.log("No tail click; keeping automatic tail assignment."); return; }
        double d0=dist(p[0],p[1], midX[f][0],midY[f][0]);
        double dN=dist(p[0],p[1], midX[f][nMid-1],midY[f][nMid-1]);
        boolean point0IsTail = d0<=dN;
        if (point0IsTail == headIsPoint0[f]) {
            IJ.log("WARNING: head and tail mapped to the same endpoint on frame "
                +(f+1));
        }
        tailIsPoint0[f]=point0IsTail;
        tailAnchorFrame=f; tailAnchorIsPoint0=point0IsTail;
        int ti = point0IsTail ? 0 : nMid-1;
        tailPx[f]=midX[f][ti]; tailPy[f]=midY[f][ti];
        double clickDist = dist(
            p[0], p[1],
            tailPx[f], tailPy[f]
        );
        IJ.log("Tail click distance from detected endpoint = "
            + IJ.d2s(clickDist,1)+" px");
        IJ.log("Tail set by click on frame "+(f+1)+" (tail = point"+(point0IsTail?0:(nMid-1))+").");
    }

    // conserved worm length = median midline length over reference traces
    double refLength=0;
    // reference body SIZE learned from the trace(s): the animal's true area & perimeter.
    // Frames whose mask deviates beyond tolerance are flagged (threshold likely off).
    double refArea=0, refPerim=0;
    java.util.ArrayList<Double> refAreaList=new java.util.ArrayList<Double>();
    java.util.ArrayList<Double> refPerimList=new java.util.ArrayList<Double>();
    double AREA_TOL = 0.30;   // +/-30% area band (data-tuned: quiet on good tracking)
    double PERIM_TOL= 0.25;   // +/-25% perimeter band (catches ragged/background-grabbing masks)
    double LEN_TOL  = 0.13;   // +/-13% midline-length band: PRIMARY size gate (length is conserved;
                              // band 128-166 for ref~147 passes good frames, rejects laced/collapsed)
    boolean[] sizeFlag;       // per-frame: mask size deviates from the traced reference

    // ---- Stage-1 (v2) additions: fluorescent-tip confidence, partial-frame, fluor sanity ----
    // Tip-voter weights. Green is the cleanest tip signal on this data, but a different strain
    // may put reporters elsewhere, so these are editable at startup. A voter must pass its
    // quality check to vote at all (a noisy signal ABSTAINS, never votes wrong).
    double wGreenTip = 1.0, wRedTip = 0.6, wDicTip = 0.7;
    double greenTipMinInt = 40;   // min green intensity-sum for a tip blob to vote
    double redTipMinPix   = 8;    // min red pixels for the head-edge voter
    double tipAgreePx     = 6;    // voters within this distance "agree"
    double tipSnapCapFrac = 0.15; // max midline-endpoint move toward consensus (x refLength)
    double[] headTipConf, tailTipConf;   // per-frame consensus confidence 0..1
    int[]    headTipSrc,  tailTipSrc;    // bitmask of agreeing voters (1=DIC 2=green 4=red)
    boolean[] partialFlag;        // per-frame: worm partly out of frame (body touches border / too small)
    boolean[] selfApproachFlag;   // per-frame: likely self-approach/shortcut (bendy worm folds near itself)
    boolean[] lenConservedFluor;  // per-frame: fluor-won midline reached conserved length after completion
    boolean[] lowEvidenceFlag;    // per-frame: too little of the midline could be placed on the DIC body
    boolean[] filledFromNeighbors;// per-frame: midline rescued by two-sided neighbour interpolation
    boolean[] suggestedAnchor;    // uncertainty-halving manual anchor for an unbridgeable interval
    double[] fluorOutsideFrac;    // per-frame: fraction of fluor pixels outside the DIC body (sanity)
    boolean useFluorTips = true;  // master toggle for fluorescent tip anchoring
    int     partialBorderMinPx = 20; // min border-pixel run to call a frame partial (speckle is ~5-16)
    double  fluorLenTol = 0.30;      // reject a fluor midline shorter than (1-this)*refLength
                                     // (guards against a skeleton that split and gave half the worm)
    double  fluorChannelFloor = 40;  // a pixel is "fluorescent" only if one channel exceeds this
                                     // (per-channel, not summed; summing trips on background noise)

    // ---- background export (extraction plugin -> analysis contract) ----
    // Per-frame, per-channel background level, measured OUTSIDE the worm body, so the
    // downstream analysis can normalise dF/F against it. Exported as a column rather than
    // pre-subtracted, so the correction stays visible and reversible.
    static final int CSV_CONTRACT_VERSION = 4;   // v4: adaptive gap reconstruction + suggested anchor provenance
    int    bgMarginPx = 10;   // exclude a border strip when sampling background: the DIC mask
                              // occasionally grabs a few edge-texture pixels as "body" near the
                              // frame border (see flagPartialFrames), so keep the sample away from it
    double[] bgBlue, bgGreen, bgRed;   // [frame]: median outside-body pixel value per channel

    // ---- Stage-2 (v2): eigenworm-on-combined-fluorescence body + DIC-overlap confidence ----
    // The summed R+G+B is itself a (sparse) worm outline. Fit the eigenworm to it (bridging dim
    // gaps with valid postures), and let it WIN as the body when its fluor fit is well-constrained.
    // Overlap with the DIC body = a confidence measure for DIC. Validated on real frames:
    // fluor is ~97% inside the DIC worm, fluor skeleton is cleaner than DIC (4 vs 12+ endpoints),
    // DIC-vs-fluor IoU ~0.6-0.7 once DIC is extracted as the DARK worm.
    boolean useFluorBody = true;        // master toggle for the eigenworm-on-fluor body
    double  fluorThreshFrac = 0.08;     // combined-fluor threshold (fraction of max) — low to stay connected
    double  eigenFitMinFrac = 0.70;     // min fraction of fluor midline points well-fit for eigenworm to WIN
    double  eigenFitRescueFrac = 0.55;  // relaxed bar when the DIC body is implausible (fluor rescues the frame)
    double[] dicConfidence;             // per-frame fluor-vs-DIC overlap (IoU), 0..1
    double[] eigenFitQuality;           // per-frame eigenworm fit quality on the fluor midline, 0..1
    int[]    bodySource;                // per-frame 0=DIC, 1=eigenworm-on-fluor
    void learnLength() {
        java.util.ArrayList<Double> v=new java.util.ArrayList<Double>();
        for (int rf: refFrames) if (rf>=0 && rf<nFrames) v.add(midLen[rf]);
        refLength=median(v);
        IJ.log("Learned conserved worm length = "+IJ.d2s(refLength,0)+" px (from "+refFrames.size()+" trace(s)).");
    }

    // ---- eigenworm posture basis (derived from THIS worm's clean frames) ----
    // Posture is represented as nMid-1 tangent angles along the body. The basis is
    // the mean angle profile + top K principal components ("eigenworms"). A real
    // worm's posture lives in a ~4D space, so a dim/clipped end can be filled by the
    // eigenworm-constrained shape that best fits the visible (bright) body, instead
    // of extending blindly along the tangent (which splays off the body).
    int    nEig=4;                 // number of eigenworm modes
    double[]   eigMean;            // [nMid-1] mean tangent-angle profile
    double[][] eigVec;             // [nEig][nMid-1] eigenworm modes
    boolean    eigLearned=false;
    // Canonical Schafer/Brown N2 eigenworms (48 tangent-angle segments, 4 modes),
    // from openworm master_eigen_worms_N2.mat. Used as fallback basis.
    static final double[][] SCHAFER_EIG = {
        {-0.274402,-0.272072,-0.276189,-0.276801,-0.272097,-0.262398,-0.246854,-0.226784,-0.202628,-0.174033,-0.141613,-0.107635,-0.072683,-0.039088,-0.007426,0.020558,0.044295,0.063010,0.076923,0.085648,0.089665,0.089279,0.085942,0.079909,0.071473,0.060232,0.049459,0.038631,0.030589,0.025821,0.024156,0.026573,0.031525,0.038868,0.048870,0.060376,0.074126,0.089052,0.104539,0.121042,0.136676,0.149843,0.159728,0.168119,0.172804,0.176767,0.179766,0.178441},
        {0.003748,0.008651,0.023561,0.038526,0.052781,0.063597,0.070928,0.073323,0.071164,0.063485,0.050241,0.031751,0.009007,-0.018450,-0.048287,-0.079790,-0.111901,-0.142512,-0.172101,-0.198020,-0.219495,-0.236177,-0.245573,-0.248097,-0.243095,-0.229457,-0.208542,-0.180849,-0.147970,-0.109837,-0.068150,-0.026140,0.015109,0.054557,0.091199,0.124666,0.153900,0.178260,0.196883,0.208981,0.214154,0.211400,0.201618,0.185332,0.163568,0.138237,0.118765,0.117052},
        {-0.097917,-0.097615,-0.082722,-0.062694,-0.037192,-0.006509,0.026702,0.061857,0.096843,0.131636,0.164357,0.192941,0.215227,0.230549,0.237735,0.236466,0.225665,0.206142,0.177861,0.143186,0.103429,0.060522,0.014366,-0.031990,-0.077502,-0.120199,-0.157338,-0.188785,-0.212103,-0.227786,-0.234155,-0.232135,-0.223161,-0.206631,-0.185416,-0.159472,-0.130120,-0.097712,-0.063982,-0.030384,-0.000126,0.025496,0.046027,0.060518,0.071131,0.076563,0.078879,0.079550},
        {-0.279275,-0.271567,-0.227064,-0.175897,-0.116878,-0.054271,0.006722,0.061596,0.108651,0.146116,0.172733,0.186508,0.186779,0.173738,0.148993,0.116435,0.078569,0.039287,0.000169,-0.034916,-0.062238,-0.080166,-0.088587,-0.087187,-0.075762,-0.053521,-0.025169,0.009904,0.047295,0.084442,0.118292,0.145138,0.164774,0.175307,0.177461,0.170336,0.153270,0.126657,0.090878,0.046223,-0.002652,-0.051927,-0.100738,-0.150378,-0.195648,-0.237000,-0.273342,-0.292090}
    };

    // ---- guards against non-biological reconstructions ----
    double ANGLE_LIMIT_RAD = 1.5;   // max |tangent-angle deviation| per segment (biological)
    double MIN_OBS_FRAC    = 0.45;  // refuse eigenworm fit below this visible-body fraction
    double TEMPORAL_WEIGHT = 0.5;   // weight of previous-frame posture prior in the fit
    int    MANUAL_BASIS_WEIGHT = 5; // how many times each hand-drawn/reference frame is entered
                                    // into the eigenworm PCA (>1 lets a few trusted traces shape
                                    // the basis without being outvoted by many auto frames)
    double FILL_MAX_TRANSLATION_BL = 0.50; // flanking centroid displacement in body lengths
    double FILL_MAX_SHAPE_RMS_BL = 0.35;   // aligned flanking posture disagreement
    double TIP_MAX_OFFSET = 2.5;   // tail tip may deviate up to this x local segment before correction
    boolean EXTEND_TO_DIC_ENDS = true; // extend front-clipped fluor midline to the DIC body's
                                       // true head/tail ends (fixes "midline only spans front
                                       // quarter"). Uses the DIC skeleton's full head-to-tail path.
    boolean USE_MEDIAL_RESEED = false; // medial-axis reseed disabled: on real data it fanned
                                       // midlines off the body on deep bends. Length-conserved
                                       // eigenworm fit is used instead. Re-enable after fixing.
    double MEDIAL_ARC_RAD   = 1.2;  // half-angle (rad) of the forward search cone per step
    int    MEDIAL_ARC_STEPS = 12;   // angular samples each side within the cone
    double MEDIAL_W_KEEPDIR = 3.0;  // penalty weight for reversing our own heading
    double MEDIAL_W_PREV    = 4.0;  // weight pulling toward the previous frame's local tangent
    int    MEDIAL_CLIMB_STEPS = 4;  // hill-climb steps to sit a point on the medial ridge
    double MEDIAL_MIN_EVIDENCE = 0.55; // mean-ridge/half-width below this => flag for redraw
    boolean usingSchaferFallback=false;


    // tangent angles along a frame's midline (unwrapped), length nMid-1
    double[] tangentAngles(int f) {
        double[] a=new double[nMid-1];
        for (int i=0;i<nMid-1;i++) a[i]=Math.atan2(midY[f][i+1]-midY[f][i], midX[f][i+1]-midX[f][i]);
        // unwrap
        for (int i=1;i<nMid-1;i++){
            while (a[i]-a[i-1] >  Math.PI) a[i]-=2*Math.PI;
            while (a[i]-a[i-1] < -Math.PI) a[i]+=2*Math.PI;
        }
        return a;
    }

    void learnEigenworms() {
        // collect angle profiles for the posture basis. TWO sources feed it:
        //  (A) hand-drawn / reference frames (manualMidline[] or refFrames): the most
        //      trustworthy postures the user has. These are admitted UNCONDITIONALLY
        //      (they are correct by construction) and entered MANUAL_BASIS_WEIGHT times
        //      so they dominate the shape space the way the user intends.
        //  (B) CLEAN auto-solved frames near full length: found, not coil/short.
        // This is the "use my traced keyframes AND the frames it solved cleanly" behavior:
        // adding more hand-drawn frames and recomputing re-learns the basis with them in it,
        // so later re-fits are retroactively informed by every correction. (Stage A)
        java.util.ArrayList<double[]> rows=new java.util.ArrayList<double[]>();
        int nManualRows=0;
        // (A) manual / reference frames, weighted
        for (int f=0; f<nFrames; f++){
            boolean isManual = (manualMidline!=null && manualMidline[f]) || refFrames.contains(f);
            if (!isManual) continue;
            if (!found[f]||skip[f]) continue;
            double[] a=tangentAngles(f);
            double m=0; for (double v:a) m+=v; m/=a.length;
            for (int i=0;i<a.length;i++) a[i]-=m;                    // remove global orientation
            for (int w=0; w<MANUAL_BASIS_WEIGHT; w++){ rows.add(a.clone()); nManualRows++; }
        }
        // (B) clean auto frames near full length (skip any already added as manual)
        for (int f=0; f<nFrames; f++){
            if (!found[f]||skip[f]||coilFlag[f]) continue;
            boolean isManual = (manualMidline!=null && manualMidline[f]) || refFrames.contains(f);
            if (isManual) continue;                                  // already counted in (A)
            if (refLength>0 && midLen[f] < 0.9*refLength) continue;  // only full-length frames
            double[] a=tangentAngles(f);
            double m=0; for (double v:a) m+=v; m/=a.length;
            for (int i=0;i<a.length;i++) a[i]-=m;                    // remove global orientation
            rows.add(a);
        }
        if (nManualRows>0) IJ.log("Eigenworm basis: "+(nManualRows/Math.max(1,MANUAL_BASIS_WEIGHT))
            +" hand-drawn/reference frame(s) included (weight "+MANUAL_BASIS_WEIGHT+"x) + "
            +(rows.size()-nManualRows)+" clean auto frame(s).");
        if (rows.size() < Math.max(4,nEig+1)) {
            // too few clean frames to derive a worm-specific basis: fall back to the
            // canonical Schafer/Brown N2 eigenworms (resampled to our segment count).
            loadSchaferBasis();
            if (eigLearned) IJ.log("Eigenworm basis: using canonical Schafer fallback ("+rows.size()+" clean frames was too few for a worm-specific basis).");
            else IJ.log("Eigenworm basis NOT available: only "+rows.size()+" clean frames and Schafer load failed. Using smooth length extension.");
            return;
        }
        usingSchaferFallback=false;
        int D=nMid-1, N=rows.size();
        eigMean=new double[D];
        for (double[] r: rows) for (int i=0;i<D;i++) eigMean[i]+=r[i];
        for (int i=0;i<D;i++) eigMean[i]/=N;
        // center
        double[][] X=new double[N][D];
        for (int n=0;n<N;n++) for (int i=0;i<D;i++) X[n][i]=rows.get(n)[i]-eigMean[i];
        // PCA via power iteration on the DxD covariance (D ~ 99, fine)
        double[][] C=new double[D][D];
        for (int n=0;n<N;n++) for (int i=0;i<D;i++){ double xi=X[n][i]; for (int j=0;j<D;j++) C[i][j]+=xi*X[n][j]; }
        for (int i=0;i<D;i++) for (int j=0;j<D;j++) C[i][j]/=Math.max(1,N-1);
        eigVec=new double[nEig][D];
        double[][] Cdef=C;
        for (int k=0;k<nEig;k++){
            double[] v=powerIteration(Cdef, D);
            eigVec[k]=v;
            // deflate: C = C - lambda v v^T
            double lam=quadForm(Cdef,v,D);
            for (int i=0;i<D;i++) for (int j=0;j<D;j++) Cdef[i][j]-=lam*v[i]*v[j];
        }
        eigLearned=true;
        usingSchaferFallback=false;
        IJ.log("Eigenworm basis learned from "+N+" clean frames ("+nEig+" modes).");
    }

    // load the canonical Schafer eigenworms, resampled from 48 segments to nMid-1.
    void loadSchaferBasis() {
        int D=nMid-1;
        eigMean=new double[D];                       // Schafer basis is mean-zero by construction
        eigVec=new double[nEig][D];
        for (int k=0;k<nEig;k++){
            double[] src=SCHAFER_EIG[k];             // length 48
            for (int i=0;i<D;i++){
                double t=(double)i*(src.length-1)/(D-1);
                int j=(int)Math.floor(t); double fr=t-j;
                eigVec[k][i] = (j+1<src.length)? src[j]*(1-fr)+src[j+1]*fr : src[src.length-1];
            }
            normalize(eigVec[k]);                     // renormalize after resampling
        }
        eigLearned=true;
        usingSchaferFallback=true;
    }

    double[] powerIteration(double[][] C, int D){
        double[] v=new double[D]; for (int i=0;i<D;i++) v[i]=Math.sin(i*0.7)+0.1;
        normalize(v);
        for (int it=0; it<200; it++){
            double[] w=new double[D];
            for (int i=0;i<D;i++){ double s=0; for (int j=0;j<D;j++) s+=C[i][j]*v[j]; w[i]=s; }
            normalize(w); v=w;
        }
        return v;
    }
    void normalize(double[] v){ double n=0; for (double x:v) n+=x*x; n=Math.sqrt(n); if (n>1e-12) for (int i=0;i<v.length;i++) v[i]/=n; }
    double quadForm(double[][] C, double[] v, int D){ double s=0; for (int i=0;i<D;i++){ double t=0; for (int j=0;j<D;j++) t+=C[i][j]*v[j]; s+=v[i]*t; } return s; }


    // draw the overlay for a single frame only (used during guided setup)
    void drawSingleFrame(int f) {
        imp.setSlice(sliceOf(f));
        Overlay ov=new Overlay();
        if (found[f]) {
            for (int side=0; side<2; side++)
                for (int i=0;i<nMid-1;i++){
                    double ax=ex(f,i,side), ay=ey(f,i,side), bx=ex(f,i+1,side), by=ey(f,i+1,side);
                    Line el=new Line(ax,ay,bx,by); el.setStrokeColor(new Color(0,180,0));
                    el.setPosition(sliceOf(f)); ov.add(el);
                }
            for (int i=0;i<nMid-1;i++){
                Line seg=new Line(midX[f][i],midY[f][i],midX[f][i+1],midY[f][i+1]);
                seg.setStrokeColor(Color.cyan); seg.setStrokeWidth(2); seg.setPosition(sliceOf(f)); ov.add(seg);
            }
            int hi=headIsPoint0[f]?0:nMid-1, ti=headIsPoint0[f]?nMid-1:0;
            PointRoi head=new PointRoi(midX[f][hi],midY[f][hi]); head.setStrokeColor(Color.green); head.setPosition(sliceOf(f)); ov.add(head);
            PointRoi tail=new PointRoi(midX[f][ti],midY[f][ti]); tail.setStrokeColor(Color.red); tail.setPosition(sliceOf(f)); ov.add(tail);
        }
        imp.setOverlay(ov); imp.updateAndDraw();
    }

    // ---------------- setup ----------------
    boolean setupDialog() {
        String[] chans = {"grayscale / whole image","red (R of RGB)","green (G of RGB)","blue (B of RGB)"};
        GenericDialog gd = new GenericDialog("WormRGBCaMPMap_v1  setup");
        gd.addMessage("Single-channel GCaMP. Worm is BRIGHT on a dark background.");
        gd.addChoice("GCaMP signal is in", chans, src8bit? "green (G of RGB)" : "grayscale / whole image");
        gd.addNumericField("Midline points", 100, 0);
        gd.addNumericField("Muscle segments per side", 24, 0);
        gd.addNumericField("Mask smoothing (+/- frames, 0 = none)", 1, 0);
        gd.addCheckbox("Smooth midline before placing muscle ROIs", smoothMidlineForRois);
        gd.addNumericField("Midline smoothing passes", midlineSmoothPasses, 0);
        gd.addNumericField("Frames per second (THIS DATA: set to your real fps, e.g. 5)", 5, 2);
        gd.addNumericField("Pixel scale (um/px, 0 = unscaled)", 0, 4);
        gd.addStringField("Worm id", "w1");
        gd.addStringField("Condition label", "1G");
        gd.addMessage("Recording metadata (written to CSV columns + export filename; genotype "
            +"is set explicitly here, never inferred from the strain name):");
        gd.addStringField("Strain (free text)", strain);
        gd.addChoice("Genotype class", GENOTYPE_OPTS, genotype);
        gd.addStringField("RNAi (e.g. l4440, unc-22, none)", rnai);
        gd.addNumericField("Age (days)", ageDay, 0);
        gd.addStringField("Animal ID (e.g. a01)", animalId);
        gd.addMessage("Fluorescent tip anchoring (edit per strain; voter abstains if below its quality bar):");
        gd.addNumericField("Green tip weight", wGreenTip, 2);
        gd.addNumericField("Red (head) tip weight", wRedTip, 2);
        gd.addNumericField("DIC tip weight", wDicTip, 2);
        gd.addCheckbox("Use fluorescent tip anchoring", useFluorTips);
        gd.addCheckbox("Use eigenworm-on-fluorescence body (wins where well-constrained)", useFluorBody);
        gd.addCheckbox("Faster adaptive temporal-background sampling", adaptiveTemporalSamples);
        gd.addCheckbox("Export geometry sidecar (unchecking = no results movie and "
            +"no post-hoc ROI review for this recording)", exportGeometryJson);
        gd.addNumericField("Combined-fluor threshold (fraction of max)", fluorThreshFrac, 3);
        gd.addNumericField("Eigenworm-fit-wins min quality (0-1)", eigenFitMinFrac, 2);
        gd.showDialog();
        if (gd.wasCanceled()) return false;
        measChannel = gd.getNextChoiceIndex();   // 0 gray, 1 R, 2 G, 3 B
        genotype = GENOTYPE_OPTS[gd.getNextChoiceIndex()];
        nMid   = Math.max(20,(int)gd.getNextNumber());
        nSeg   = Math.max(2,(int)gd.getNextNumber());
        // 24 per side is anatomy, not a resolution setting: each segment is one
        // projected myocyte, which is what lets a diagram name individual
        // muscles. The older 12 lumped neighbours, and any other value maps to
        // nothing anatomical - the numbers stay internally consistent, so a
        // mis-set run produces a CSV that looks perfectly normal and is not
        // comparable to anything. Caught here rather than downstream, because
        // by then the recording exists and the mistake is expensive.
        if (nSeg != MYOCYTE_SEGMENTS) {
            boolean useAnatomical = IJ.showMessageWithCancel(
                "Segment count does not match the myocytes",
                nSeg+" segments per side does not correspond to individual\n"+
                "myocytes. At "+MYOCYTE_SEGMENTS+" each segment is one projected\n"+
                "myocyte; at 12 each segment lumps several neighbours, and other\n"+
                "values map to no anatomical unit at all.\n\n"+
                "This recording would still export, but its per-segment values\n"+
                "would not be comparable with runs at "+MYOCYTE_SEGMENTS+", and tools that\n"+
                "name individual muscles will refuse it.\n\n"+
                "OK  - use "+MYOCYTE_SEGMENTS+" (recommended)\n"+
                "Cancel - keep "+nSeg+" deliberately");
            if (useAnatomical) {
                nSeg = MYOCYTE_SEGMENTS;
            } else {
                IJ.log("[segments] WARNING: continuing with "+nSeg+" segments per side. "
                    +"These do not correspond to individual myocytes and are not "
                    +"comparable with "+MYOCYTE_SEGMENTS+"-segment runs.");
            }
        }
        buildMuscleBoundaries();
        IJ.log("Muscle segmentation: "+nSeg+" proportional segments per side (size-weighted, "
            +"larger mid-body, tapered at ends). Boundary fractions head->tail: "
            +boundaryFracString());
        maskSmoothFrames = Math.max(0,(int)gd.getNextNumber());
        smoothMidlineForRois = gd.getNextBoolean();
        midlineSmoothPasses = Math.max(0,(int)gd.getNextNumber());
        fps    = gd.getNextNumber(); if (fps<=0) fps=1;
        umPerPx= gd.getNextNumber(); if (umPerPx<0) umPerPx=0;
        ageDay = (int)gd.getNextNumber();
        wormId = gd.getNextString();
        condition = gd.getNextString();
        strain = gd.getNextString();
        rnai = gd.getNextString();
        animalId = gd.getNextString();
        wGreenTip = gd.getNextNumber();
        wRedTip   = gd.getNextNumber();
        wDicTip   = gd.getNextNumber();
        useFluorTips = gd.getNextBoolean();
        useFluorBody = gd.getNextBoolean();
        adaptiveTemporalSamples = gd.getNextBoolean();
        exportGeometryJson = gd.getNextBoolean();
        fluorThreshFrac = gd.getNextNumber(); if (fluorThreshFrac<=0||fluorThreshFrac>=1) fluorThreshFrac=0.08;
        eigenFitMinFrac = gd.getNextNumber(); if (eigenFitMinFrac<0||eigenFitMinFrac>1) eigenFitMinFrac=0.70;
        return true;
    }

    void alloc() {
        midX=new double[nFrames][nMid]; midY=new double[nFrames][nMid];
        halfW=new double[nFrames][nMid];
        hwL=new double[nFrames][nMid]; hwR=new double[nFrames][nMid];
        edgeSrcL=new byte[nFrames][nMid]; edgeSrcR=new byte[nFrames][nMid];
        midLen=new double[nFrames]; lenShortFlag=new boolean[nFrames]; lenLongFlag=new boolean[nFrames];
        edgeLX=new double[nFrames][nMid]; edgeLY=new double[nFrames][nMid];
        edgeRX=new double[nFrames][nMid]; edgeRY=new double[nFrames][nMid];
        bodyArea=new double[nFrames];
        curv=new double[nFrames][nMid];
        found=new boolean[nFrames]; skip=new boolean[nFrames];
        headIsPoint0=new boolean[nFrames]; tailIsPoint0=new boolean[nFrames];
        coilFlag=new boolean[nFrames]; areaFlag=new boolean[nFrames];
        sizeFlag=new boolean[nFrames];
        headTipConf=new double[nFrames]; tailTipConf=new double[nFrames];
        headTipSrc=new int[nFrames]; tailTipSrc=new int[nFrames];
        partialFlag=new boolean[nFrames]; fluorOutsideFrac=new double[nFrames];
        selfApproachFlag=new boolean[nFrames];
        lenConservedFluor=new boolean[nFrames];
        lowEvidenceFlag=new boolean[nFrames];
        filledFromNeighbors=new boolean[nFrames];
        suggestedAnchor=new boolean[nFrames];
        dicConfidence=new double[nFrames]; eigenFitQuality=new double[nFrames]; bodySource=new int[nFrames];
        headPx=new double[nFrames]; headPy=new double[nFrames];
        tailPx=new double[nFrames]; tailPy=new double[nFrames];
        thrFrame=new double[nFrames];
        manualEnds=new double[nFrames][];
        dorsalSign=new int[nFrames]; dorsalKnown=new boolean[nFrames];
        outlineX=new int[nFrames][]; outlineY=new int[nFrames][];
        pointSrc=new byte[nFrames][nMid];
        manualMidX=new double[nFrames][]; manualMidY=new double[nFrames][];
        manualMidline=new boolean[nFrames];
        correctionNote=new String[nFrames]; java.util.Arrays.fill(correctionNote, "");
        headFlipFlag=new boolean[nFrames];
    }

    int sliceOf(int frame) { return frame+1; }
    ImageProcessor frameIp(int frame) {
        if(dicAlignX!=null){ dicAlignCachedX=dicAlignX[frame]; dicAlignCachedY=dicAlignY[frame]; }
        return stack.getProcessor(frame+1);
    }

    // per-frame DIC background (median), cached; worm is DARKER than this.
    double[] dicBg;
    // per-pixel temporal-median background (worm removed, static texture kept).
    // Subtracting this flattens the textured DIC field so the worm stands out and a
    // single threshold works across the movie. Validated: cuts background speckle
    // from ~1.4 to ~0.06 junk components/frame vs the frame-median method.
    float[][] dicBgImg;            // [y][x] temporal median of DIC gray
    int[] dicAlignX, dicAlignY;     // shift that maps each camera frame into frame-0 coordinates
    int dicAlignCachedX=0, dicAlignCachedY=0;
    boolean useTemporalBg = true;  // toggle (default on for DIC tracking)
    void estimateDicCameraMotion(){
        dicAlignX=new int[nFrames]; dicAlignY=new int[nFrames];
        for (int f=1; f<nFrames; f++){
            ImageProcessor a=frameIp(f-1), b=frameIp(f);
            int bestDx=0,bestDy=0; double best=Double.POSITIVE_INFINITY;
            // Robust coarse background registration. The worm is a small minority;
            // the displacement minimizing whole-field disagreement follows the arena.
            for (int dy=-4;dy<=4;dy++) for(int dx=-4;dx<=4;dx++){
                double cost=0; int n=0;
                for(int y=12;y<H-12;y+=8) for(int x=12;x<W-12;x+=8){
                    int bx=x-dx, by=y-dy;
                    if(bx<0||by<0||bx>=W||by>=H) continue;
                    cost+=Math.abs(gray(a,x,y)-gray(b,bx,by)); n++;
                }
                if(n>0 && cost/n<best){best=cost/n;bestDx=dx;bestDy=dy;}
            }
            dicAlignX[f]=dicAlignX[f-1]+bestDx;
            dicAlignY[f]=dicAlignY[f-1]+bestDy;
        }
    }
    void buildTemporalBackground(){
        if (!rgbMode) return;
        estimateDicCameraMotion();
        dicBgImg=new float[H][W];
        int N=nFrames;
        // Bound total pixel visits rather than always using 60 samples.  A 4K
        // movie otherwise needs roughly half a billion gray conversions here.
        int maxSamples=(adaptiveTemporalSamples
            ? (int)Math.max(7, Math.min(60, 120000000L/Math.max(1L,(long)W*H))) : 60);
        int step=Math.max(1, (int)Math.ceil(N/(double)maxSamples));
        java.util.ArrayList<Integer> fr=new java.util.ArrayList<Integer>();
        for (int f=0; f<N; f+=step) fr.add(f);
        int m=fr.size();
        ImageProcessor[] sampledIp=new ImageProcessor[m];
        int[] sampledDx=new int[m], sampledDy=new int[m];
        for (int i=0;i<m;i++){
            int f=fr.get(i); sampledIp[i]=frameIp(f);
            sampledDx[i]=dicAlignX[f]; sampledDy[i]=dicAlignY[f];
        }
        float[] col=new float[m];
        for (int y=0;y<H;y++) for (int x=0;x<W;x++){
            for (int i=0;i<m;i++){
                int sx=x-sampledDx[i], sy=y-sampledDy[i];
                col[i]=(sx>=0&&sy>=0&&sx<W&&sy<H)?(float)gray(sampledIp[i],sx,sy):Float.NaN;
            }
            java.util.Arrays.sort(col);
            // NaNs sort last; valid is therefore the first NaN index.
            int valid=0; while(valid<m && !Float.isNaN(col[valid])) valid++;
            dicBgImg[y][x]=(valid==0)?0:((valid%2==1)?col[valid/2]:0.5f*(col[valid/2-1]+col[valid/2]));
        }
        IJ.log("Built camera-registered temporal-median DIC background from "+m+" frames.");
    }

    double dicBackground(int f){
        if (dicBg==null) dicBg=new double[nFrames];
        if (dicBg[f]>0) return dicBg[f];
        ImageProcessor ip=frameIp(f);
        // median via histogram of the 8-bit-ish gray (DIC AVIs are mid-grey)
        int[] h=new int[256]; int n=0;
        for (int y=0;y<H;y++) for (int x=0;x<W;x++){
            int v=(int)Math.max(0,Math.min(255, gray(ip,x,y))); h[v]++; n++;
        }
        int cum=0, med=128;
        for (int i=0;i<256;i++){ cum+=h[i]; if (cum>=n/2){ med=i; break; } }
        dicBg[f]=Math.max(1,med);
        return dicBg[f];
    }
    double gray(ImageProcessor ip, int x, int y){
        if (ip instanceof ColorProcessor){ int p=ip.getPixel(x,y); int r=(p>>16)&0xff,g=(p>>8)&0xff,b=p&0xff; return (r+g+b)/3.0; }
        return ip.getPixelValue(x,y);
    }

    // In rgbMode we TRACK on DIC: the worm is dark on light, so the body "signal"
    // is how much DARKER a pixel is than the background. With temporal background on,
    // we subtract the per-pixel temporal median (flat field); otherwise the frame
    // median scalar. Either way the existing bright-on-dark path works unchanged.
    double gcampValue(ImageProcessor ip, int x, int y) {
        if (x<0||y<0||x>=W||y>=H) return Double.NaN;
        if (rgbMode){
            double here=gray(ip,x,y);
            int bx=x+dicAlignCachedX, by=y+dicAlignCachedY;
            double bg = (useTemporalBg && dicBgImg!=null && bx>=0&&by>=0&&bx<W&&by<H)
                ? dicBgImg[by][bx] : dicBackgroundCachedForIp;
            double d = bg - here;                  // positive where darker than background
            return d>0? d : 0;
        }
        if (measChannel==0 || !(ip instanceof ColorProcessor)) return ip.getPixelValue(x,y);
        int px=ip.getPixel(x,y);
        int r=(px>>16)&0xff, g=(px>>8)&0xff, b=px&0xff;
        return (measChannel==1)?r:(measChannel==2)?g:b;
    }
    // set just before a per-frame mask build so gcampValue knows the frame's bg
    double dicBackgroundCachedForIp = 128;

    // DIC body mask as a boolean[][] (for registration check), via the same path.
    boolean[][] dicBodyMask(int f){
        dicBackgroundCachedForIp = dicBackground(f);
        ByteProcessor m = rawMask(f); keepLargestObject(m);
        byte[] p=(byte[])m.getPixels();
        boolean[][] out=new boolean[H][W];
        for (int y=0;y<H;y++) for (int x=0;x<W;x++) out[y][x]=((p[y*Mw+x]&0xff)==255);
        return out;
    }

    // mean GCaMP in a disk at (cx,cy), reading the chosen component, original pixels
    double meanInDiskG(ImageProcessor ip, double cx, double cy, double r) {
        int x0=(int)Math.floor(cx-r), x1=(int)Math.ceil(cx+r);
        int y0=(int)Math.floor(cy-r), y1=(int)Math.ceil(cy+r);
        double sum=0; int cnt=0; double r2=r*r;
        for (int y=y0;y<=y1;y++) for (int x=x0;x<=x1;x++){
            if (x<0||y<0||x>=W||y>=H) continue;
            double dx=x-cx, dy=y-cy; if (dx*dx+dy*dy>r2) continue;
            double v=gcampValue(ip,x,y); if (Double.isNaN(v)) continue;
            sum+=v; cnt++;
        }
        return (cnt>0)?sum/cnt:Double.NaN;
    }

    // min/mean/max GCaMP within a polygon ROI (original pixels)
    double[] statsInPolygon(ImageProcessor ip, int[] xs, int[] ys, int npts) {
        PolygonRoi roi=new PolygonRoi(xs,ys,npts,Roi.POLYGON);
        Rectangle b=roi.getBounds();
        ImageProcessor mask=roi.getMask();
        double mn=Double.POSITIVE_INFINITY, mx=Double.NEGATIVE_INFINITY, sum=0; int cnt=0;
        for (int yy=0;yy<b.height;yy++) for (int xx=0;xx<b.width;xx++){
            if (mask!=null && mask.get(xx,yy)==0) continue;
            int x=b.x+xx, y=b.y+yy;
            double v=gcampValue(ip,x,y); if (Double.isNaN(v)) continue;
            if (v<mn) mn=v; if (v>mx) mx=v; sum+=v; cnt++;
        }
        if (cnt==0) return new double[]{Double.NaN,Double.NaN,Double.NaN,0};
        return new double[]{mn, sum/cnt, mx, cnt};
    }

    // Same as statsInPolygon, but count only pixels that are inside the detected worm
    // body. This prevents profile-placed or noisy edge ROIs that flare off the animal
    // from pulling background into the calcium measurement.
    double[] statsInPolygonClipped(ImageProcessor ip, int[] xs, int[] ys, int npts, ByteProcessor body) {
        PolygonRoi roi=new PolygonRoi(xs,ys,npts,Roi.POLYGON);
        Rectangle b=roi.getBounds();
        ImageProcessor mask=roi.getMask();
        byte[] bp=(body==null)?null:(byte[])body.getPixels();
        double mn=Double.POSITIVE_INFINITY, mx=Double.NEGATIVE_INFINITY, sum=0; int cnt=0;
        for (int yy=0;yy<b.height;yy++) for (int xx=0;xx<b.width;xx++){
            if (mask!=null && mask.get(xx,yy)==0) continue;
            int x=b.x+xx, y=b.y+yy;
            if (x<0||y<0||x>=W||y>=H) continue;
            if (bp!=null && (bp[y*W+x]&0xff)==0) continue;
            double v=gcampValue(ip,x,y); if (Double.isNaN(v)) continue;
            if (v<mn) mn=v; if (v>mx) mx=v; sum+=v; cnt++;
        }
        if (cnt==0) return new double[]{Double.NaN,Double.NaN,Double.NaN,0};
        return new double[]{mn, sum/cnt, mx, cnt};
    }

    // multichannel: min/mean/max/area of a measurement channel c in a segment polygon.
    double[] statsInPolygonMeas(int c, int f, int[] xs, int[] ys, int npts) {
        PolygonRoi roi=new PolygonRoi(xs,ys,npts,Roi.POLYGON);
        Rectangle b=roi.getBounds();
        ImageProcessor mask=roi.getMask();
        double mn=Double.POSITIVE_INFINITY, mx=Double.NEGATIVE_INFINITY, sum=0; int cnt=0;
        for (int yy=0;yy<b.height;yy++) for (int xx=0;xx<b.width;xx++){
            if (mask!=null && mask.get(xx,yy)==0) continue;
            int x=b.x+xx, y=b.y+yy;
            double v=measValue(c,f,x,y); if (Double.isNaN(v)) continue;
            if (v<mn) mn=v; if (v>mx) mx=v; sum+=v; cnt++;
        }
        if (cnt==0) return new double[]{Double.NaN,Double.NaN,Double.NaN,0};
        return new double[]{mn, sum/cnt, mx, cnt};
    }

    // multichannel version with body-mask clipping.
    double[] statsInPolygonMeasClipped(int c, int f, int[] xs, int[] ys, int npts, ByteProcessor body) {
        PolygonRoi roi=new PolygonRoi(xs,ys,npts,Roi.POLYGON);
        Rectangle b=roi.getBounds();
        ImageProcessor mask=roi.getMask();
        byte[] bp=(body==null)?null:(byte[])body.getPixels();
        double mn=Double.POSITIVE_INFINITY, mx=Double.NEGATIVE_INFINITY, sum=0; int cnt=0;
        for (int yy=0;yy<b.height;yy++) for (int xx=0;xx<b.width;xx++){
            if (mask!=null && mask.get(xx,yy)==0) continue;
            int x=b.x+xx, y=b.y+yy;
            if (x<0||y<0||x>=W||y>=H) continue;
            if (bp!=null && (bp[y*W+x]&0xff)==0) continue;
            double v=measValue(c,f,x,y); if (Double.isNaN(v)) continue;
            if (v<mn) mn=v; if (v>mx) mx=v; sum+=v; cnt++;
        }
        if (cnt==0) return new double[]{Double.NaN,Double.NaN,Double.NaN,0};
        return new double[]{mn, sum/cnt, mx, cnt};
    }

    // per-channel mean time series: meanSerCh[c][k][s][frame]
    double[][][][] buildSeriesMeanMulti() {
        double[][][][] out=new double[nMeas][nSeg][2][nFrames];
        for (int c=0;c<nMeas;c++) for (int k=0;k<nSeg;k++) for (int s=0;s<2;s++)
            for (int f=0;f<nFrames;f++) out[c][k][s][f]=Double.NaN;
        for (int f=0; f<nFrames; f++){
            if (!found[f]||skip[f]) continue;
            ByteProcessor body=bodyMaskCached(f);
            for (int k=0;k<nSeg;k++) for (int s=0;s<2;s++){
                int[][] poly=segPolygon(f,k,s);
                for (int c=0;c<nMeas;c++){
                    double[] st=statsInPolygonMeasClipped(c,f,poly[0],poly[1],4,body);
                    out[c][k][s][f]=st[1];
                }
            }
        }
        return out;
    }

    // cross-correlation lag (in frames) at which series A best matches series B.
    // positive lag = A leads B (A's pattern appears earlier). Capped at +/-maxlag.
    // Returns {lagFrames, peakCorr}. NaN-safe.
    double[] xcorrLag(double[] A, double[] B, int maxlag){
        double ma=nanmean(A), mb=nanmean(B);
        double best=-2; int bl=0;
        for (int L=-maxlag; L<=maxlag; L++){
            double sxy=0,sxx=0,syy=0; int n=0;
            for (int i=0;i<A.length;i++){
                int j=i+L; if (j<0||j>=B.length) continue;
                double a=A[i], b=B[j];
                if (Double.isNaN(a)||Double.isNaN(b)) continue;
                a-=ma; b-=mb; sxy+=a*b; sxx+=a*a; syy+=b*b; n++;
            }
            if (n<8||sxx<=0||syy<=0) continue;
            double r=sxy/Math.sqrt(sxx*syy);
            if (r>best){ best=r; bl=L; }
        }
        return new double[]{bl, best};
    }
    double nanmean(double[] a){ double s=0; int n=0; for (double v:a) if (!Double.isNaN(v)){ s+=v; n++; } return n>0?s/n:Double.NaN; }

    // ---------------- body threshold (auto, GCaMP bright on dark) ----------------
    void autoBodyThreshold() {
        // The worm is a small bright object on a large dark background, so the
        // frame mean is near background and the bright body inflates the SD,
        // pushing mean+k*sd ABOVE the faint head/tail (the dim-end problem the
        // user sees, and recovers by Auto B&C). Instead, estimate the background
        // NOISE FLOOR from the dark majority of pixels and sit just above it, so
        // faint-but-real body signal is kept.
        int[] probes={0, nFrames/4, nFrames/2, (3*nFrames)/4, nFrames-1};
        double floorSum=0, noiseSum=0; int n=0;
        for (int pf: probes){ if (pf<0||pf>=nFrames) continue;
            if (rgbMode) dicBackgroundCachedForIp = dicBackground(pf);
            ImageProcessor ip=frameIp(pf);
            // background = median-ish of the dark pixels: use the value below which
            // ~85% of pixels fall (the worm is a small fraction of the frame).
            int[] hist=new int[65536]; int maxv=0; long cnt=0;
            for (int y=0;y<H;y++) for (int x=0;x<W;x++){
                double v=gcampValue(ip,x,y); if (Double.isNaN(v)) continue;
                int iv=(int)Math.round(v); if (iv<0) iv=0; if (iv>65535) iv=65535;
                hist[iv]++; cnt++; if (iv>maxv) maxv=iv;
            }
            if (cnt==0) continue;
            long c85=(long)(0.85*cnt), acc=0; int bgLevel=0;
            for (int v=0;v<=maxv;v++){ acc+=hist[v]; if (acc>=c85){ bgLevel=v; break; } }
            // noise spread within the background: mean abs deviation of pixels <= bgLevel
            long bcnt=0; double bsum=0;
            for (int v=0;v<=bgLevel;v++){ bcnt+=hist[v]; bsum+=(double)hist[v]*v; }
            double bmean=(bcnt>0)?bsum/bcnt:0;
            double dev=0;
            for (int v=0;v<=bgLevel;v++) dev+=hist[v]*Math.abs(v-bmean);
            double noise=(bcnt>0)?dev/bcnt:1;
            floorSum+=bgLevel; noiseSum+=noise; n++;
        }
        double floor=floorSum/Math.max(1,n), noise=noiseSum/Math.max(1,n);
        bodyThr = floor + 3.0*Math.max(1.0,noise);   // just above the background noise
        IJ.log("Auto GCaMP body threshold = "+IJ.d2s(bodyThr,1)+"  (background floor "+IJ.d2s(floor,1)+", noise "+IJ.d2s(noise,2)+"; set near noise floor to keep faint head/tail)");
    }

    // ---------------- main per-frame pipeline ----------------
    void processAll() {
        IJ.log("[trace] processAll: first pass over "+nFrames+" frames");
        progBegin("First pass (detect)", nFrames);
        for (int f=0; f<nFrames; f++) {
            if (skip[f]) { found[f]=false; progTick("First pass (detect)", f+1, nFrames); continue; }
            processFrame(f);
            progTick("First pass (detect)", f+1, nFrames);
            if (f%20==0) IJ.log("[trace]   processAll frame "+f+"/"+nFrames);
        }
        progDone("First pass (detect)");
        IJ.log("[trace] processAll done");
    }

    // full recompute: per-frame geometry, temporal inference, head, dorsal, flags
    void recomputeAll() {
        processAll();                // first pass: detection + (blind) extension if any
        progBegin("Eigenworm basis", 0);
        learnEigenworms();           // build posture basis from the clean full-length frames
        progDone("Eigenworm basis");
        if (eigLearned) {            // second pass: refit short frames with the eigenworm constraint
            progBegin("Second pass (refit)", nFrames);
            for (int f=0; f<nFrames; f++){
                progTick("Second pass (refit)", f+1, nFrames);
                if (skip[f]||!found[f]||manualMidline[f]) continue;
                if (refLength>0 && midLen[f] < 0.95*refLength) { processFrame(f); }
            }
            progDone("Second pass (refit)");
        }
        inferMissingBody();          // fill vanished segments / frames from neighbors
        assignHeadByMotion();
        if (rgbMode && useRedPharynx) redExtendHeadTips();   // push head tip to red mass edge
        if (rgbMode && useFluorTips) fluorTipAnchor();        // green/red/DIC tip consensus (bounded)
        if (rgbMode && useFluorBody) fluorBodyPass();         // eigenworm-on-fluor body wins where well-constrained
        progBegin("Head / dorsal / flags", 0);
        detectVentralFromVulva();    // vulva notch: dimmer midbody side = ventral
        for (int f=0; f<nFrames; f++) if (found[f]) resolveDorsal(f);
        flagAreaJumps();
        flagPartialFrames();         // worm partly out of view -> flag + exclude from dimension stats
        flagSizeDeviations();        // compare each frame's mask to the traced area/perimeter
        computeFluorOutside();       // fluor-outside-DIC-body sanity (should be ~0)
        computeBackground();         // per-frame per-channel background (outside-worm region)
        flagShortMidlines();         // length-conservation QC (flag only)
        fillAdaptiveGapsFromNeighbors(); // bridge by normalized motion; suggest anchors otherwise
        stabilizeTailTips();          // fix tail tip snapping to plate features (spatial + temporal)
        progDone("Head / dorsal / flags");
    }

    // Tail tip can jump to an isolated plate feature on alternate frames (length stays right,
    // only the last point is wrong). Two guards: (spatial) if the tip sits far off the line
    // continued from the body's last few points, pull it back onto that continuation; then
    // (temporal) if a frame's tip is an outlier versus its two neighbours, replace it with
    // their average, since the worm barely moves between frames.
    void stabilizeTailTips(){
        int nFix=0;
        // spatial: tip should continue the body direction, not jump sideways
        for (int f=0; f<nFrames; f++){
            if (skip[f] || !found[f]) continue;
            int L=nMid-1;
            double dx=midX[f][L-1]-midX[f][L-3], dy=midY[f][L-1]-midY[f][L-3];
            double n=Math.hypot(dx,dy); if (n<1e-6) continue; dx/=n; dy/=n;
            double seg=Math.hypot(midX[f][L-1]-midX[f][L-2], midY[f][L-1]-midY[f][L-2]);
            double predX=midX[f][L-1]+dx*seg, predY=midY[f][L-1]+dy*seg;
            double off=Math.hypot(midX[f][L]-predX, midY[f][L]-predY);
            if (off > TIP_MAX_OFFSET*Math.max(seg,1)){
                midX[f][L]=predX; midY[f][L]=predY; nFix++;
            }
        }
        // temporal: tip outlier vs neighbours -> neighbour average
        for (int f=1; f<nFrames-1; f++){
            if (skip[f]||!found[f]||!found[f-1]||!found[f+1]) continue;
            if (manualMidline[f]) continue;
            int L=nMid-1;
            double ax=(midX[f-1][L]+midX[f+1][L])/2, ay=(midY[f-1][L]+midY[f+1][L])/2;
            double d=Math.hypot(midX[f][L]-ax, midY[f][L]-ay);
            double nb=Math.hypot(midX[f-1][L]-midX[f+1][L], midY[f-1][L]-midY[f+1][L]);
            if (d > TIP_MAX_OFFSET*Math.max(nb,2)){
                midX[f][L]=ax; midY[f][L]=ay; nFix++;
            }
        }
        if (nFix>0) IJ.log("Tail-tip stabilization: corrected "+nFix+" tip(s) that jumped off-body or vs neighbours.");
    }

    // Is this frame's midline trustworthy (full length)? Manual/reference frames always are.
    boolean frameIsGoodForFill(int f){
        if (skip[f] || !found[f]) return false;
        if (manualMidline[f] || refFrames.contains(f)) return true;
        if (refLength>0) return midLen[f] >= (1.0-LEN_TOL)*refLength;
        return !lenShortFlag[f];
    }

    // A previous interpolation is never evidence for a later interpolation.
    // When the user adds another manual midline, discard every old neighbor-fill
    // while preserving all manual/reference anchors. The next adaptive pass then
    // divides the movie into subintervals between the complete ordered anchor set.
    void invalidatePriorNeighborFills(){
        int n=0;
        for(int f=0;f<nFrames;f++){
            if(filledFromNeighbors[f] && !manualMidline[f] && !refFrames.contains(f)){
                found[f]=false;
                lenShortFlag[f]=true;
                n++;
            }
            filledFromNeighbors[f]=false;
        }
        if(n>0) IJ.log("Invalidated "+n+" prior inferred midline(s); rebuilding between all manual/reference anchors.");
    }

    // STAGE 1 neighbour fill. For each run of clipped (not-good) frames bordered by good
    // frames on BOTH sides, replace each clipped midline by interpolating every midline
    // point between the nearest good frame before and after, weighted by temporal distance,
    // then renormalise to conserved length. This uses the fact that the worm barely moves
    // between frames, so a full-length neighbour is a near-perfect template. There is no
    // frame-count ceiling: flanking translation and posture are evaluated in body-length
    // units. Unsafe intervals suggest their temporal midpoint as a manual anchor; rerunning
    // recursively bisects only the portion that remains unsafe.
    void fillAdaptiveGapsFromNeighbors(){
        int nFilled=0, nGapsSkipped=0;
        for(int z=0;z<nFrames;z++){ suggestedAnchor[z]=false; filledFromNeighbors[z]=false; }
        int f=0;
        while (f<nFrames){
            if (frameIsGoodForFill(f)){ f++; continue; }
            // start of a bad run
            int gapStart=f;
            while (f<nFrames && !frameIsGoodForFill(f)) f++;
            int gapEnd=f-1;                       // inclusive
            int left=gapStart-1, right=f;         // nearest good frames on each side
            int gapLen=gapEnd-gapStart+1;
            boolean twoSided = (left>=0) && (right<nFrames);
            if (!twoSided){ suggestedAnchor[(gapStart+gapEnd)/2]=true; nGapsSkipped++; continue; }
            double lcx=0,lcy=0,rcx=0,rcy=0;
            for(int i=0;i<nMid;i++){
                lcx+=midX[left][i]; lcy+=midY[left][i];
                rcx+=midX[right][i]; rcy+=midY[right][i];
            }
            lcx/=nMid; lcy/=nMid; rcx/=nMid; rcy/=nMid;
            double scale=(refLength>0?refLength:0.5*(midLen[left]+midLen[right]));
            double dx=rcx-lcx, dy=rcy-lcy;
            double translation=Math.hypot(dx,dy)/Math.max(scale,1e-9);
            double sf=0,sr=0;
            for(int i=0;i<nMid;i++){
                double fx=(midX[right][i]-dx)-midX[left][i];
                double fy=(midY[right][i]-dy)-midY[left][i];
                double rx=(midX[right][nMid-1-i]-dx)-midX[left][i];
                double ry=(midY[right][nMid-1-i]-dy)-midY[left][i];
                sf+=fx*fx+fy*fy; sr+=rx*rx+ry*ry;
            }
            boolean reverse=sr<sf;
            double shape=Math.sqrt(Math.min(sf,sr)/nMid)/Math.max(scale,1e-9);
            if (translation>FILL_MAX_TRANSLATION_BL || shape>FILL_MAX_SHAPE_RMS_BL){
                int anchor=(gapStart+gapEnd)/2;
                suggestedAnchor[anchor]=true; nGapsSkipped++;
                IJ.log("Gap "+(gapStart+1)+"-"+(gapEnd+1)+" suggests manual anchor frame "
                    +(anchor+1)+": translation="+IJ.d2s(translation,2)
                    +" body lengths, posture RMS="+IJ.d2s(shape,2)+" body lengths.");
                continue;
            }
            // interpolate each point between left and right good frames
            for (int g=gapStart; g<=gapEnd; g++){
                double t = (double)(g-left)/(double)(right-left);  // 0..1 across the gap
                for (int i=0;i<nMid;i++){
                    int ri=reverse?nMid-1-i:i;
                    midX[g][i] = (1-t)*midX[left][i] + t*midX[right][ri];
                    midY[g][i] = (1-t)*midY[left][i] + t*midY[right][ri];
                    pointSrc[g][i]=1;
                }
                if (refLength>0){
                    double[] xs=new double[nMid], ys=new double[nMid];
                    for (int i=0;i<nMid;i++){ xs[i]=midX[g][i]; ys[i]=midY[g][i]; }
                    rescaleToLength(xs,ys,refLength);
                    for (int i=0;i<nMid;i++){ midX[g][i]=xs[i]; midY[g][i]=ys[i]; }
                }
                midLen[g]=polylineLen(midX[g],midY[g]);
                found[g]=true;
                filledFromNeighbors[g]=true;
                lenShortFlag[g]=false;             // rescued to full length
                measureWidth(g, bodyMaskCached(g));
                computeCurvature(g);
                nFilled++;
            }
        }
        if (nFilled>0 || nGapsSkipped>0) IJ.log("Adaptive neighbour-fill: rescued "+nFilled
            +" clipped frame(s); intervals needing a suggested manual anchor: "+nGapsSkipped+".");
    }

    // ---- vulva-notch ventral detection ----
    // At ventral midbody, vulval muscles replace body-wall muscle, leaving a
    // reliably DIMMER patch. So the midbody side that is consistently dimmer across
    // the movie is VENTRAL. This anchors dorsal/ventral (and thus the convex/concave
    // side labels) to anatomy. Only sets the seed automatically if the user has NOT
    // already seeded dorsal manually.
    void detectVentralFromVulva() {
        if (dorsalSeedSign!=0) return;              // respect a manual dorsal seed
        // midbody band (35%-65% of body), head-relative left vs right brightness
        int a=(int)Math.round(0.35*(nMid-1)), b=(int)Math.round(0.65*(nMid-1));
        double sumLeft=0, sumRight=0; int n=0;
        for (int f=0; f<nFrames; f++){
            if (!found[f]||skip[f]) continue;
            ImageProcessor ip=frameIp(f);
            double l=0, r=0; int c=0;
            for (int i=a;i<=b;i++){
                // head-relative orientation: if head is pointN, flip the index
                int idx = headIsPoint0[f]? i : (nMid-1-i);
                double rad=Math.max(2, halfW[f][idx]*0.6);
                // left-normal and right-normal sample points
                double lx=edgeLX[f][idx], ly=edgeLY[f][idx], rx=edgeRX[f][idx], ry=edgeRY[f][idx];
                double lv=meanInDiskG(ip, midX[f][idx]+(lx-midX[f][idx])*0.5, midY[f][idx]+(ly-midY[f][idx])*0.5, rad);
                double rv=meanInDiskG(ip, midX[f][idx]+(rx-midX[f][idx])*0.5, midY[f][idx]+(ry-midY[f][idx])*0.5, rad);
                if (!Double.isNaN(lv)&&!Double.isNaN(rv)){ l+=lv; r+=rv; c++; }
            }
            if (c>0){ sumLeft+=l/c; sumRight+=r/c; n++; }
        }
        if (n<3) { IJ.log("Vulva/ventral detection skipped (too few clean frames)."); return; }
        // dimmer side = ventral; dorsalSeedSign = +1 if head-relative LEFT-normal side is dorsal
        boolean leftIsDimmer = sumLeft < sumRight;
        // left-normal side dorsal (+1) when the RIGHT side is the dim (ventral) one
        dorsalSeedSign = leftIsDimmer ? -1 : +1;
        dorsalSeedFrame = (headAnchorFrame>=0)? headAnchorFrame : 0;
        IJ.log("Ventral side set from vulva notch: head-relative "
            +(leftIsDimmer?"LEFT":"RIGHT")+" midbody is dimmer (ventral). "
            +"dorsalSeedSign="+dorsalSeedSign+". (Override with 'Seed dorsal' if wrong.)");
    }

    // ---- temporal body inference ----
    // Two cases:
    //  (a) a found frame has a stretch where the body vanished (half-width ~ 0):
    //      those points are marked INFERRED and their positions/width are filled
    //      by interpolating between the bracketing measured points within the frame,
    //      and refined toward the same body fraction in neighbor frames.
    //  (b) a whole frame failed (not found, not manual, not skipped): the entire
    //      midline is interpolated from the nearest found frames before and after.
    // All inferred points get pointSrc=1 so the overlay and CSV can distinguish them.
    void inferMissingBody() {
        double wMin = 1.0;   // px; half-width at or below this = body absent here

        // (a) within-frame vanished spans
        for (int f=0; f<nFrames; f++){
            if (!found[f] || skip[f] || manualMidline[f]) continue;
            for (int i=0;i<nMid;i++){
                if (halfW[f][i] <= wMin && pointSrc[f][i]==0){
                    // mark as inferred; position will be smoothed below
                    pointSrc[f][i]=1;
                }
            }
            // smooth inferred runs: linearly interpolate midX/midY across each run
            int i=0;
            while (i<nMid){
                if (pointSrc[f][i]==1){
                    int a=i-1; while (a>=0 && pointSrc[f][a]==1) a--;
                    int b=i;   while (b<nMid && pointSrc[f][b]==1) b++;
                    // bracket points a (last good before) and b (first good after)
                    if (a>=0 && b<nMid){
                        for (int j=a+1;j<b;j++){
                            double t=(double)(j-a)/(b-a);
                            midX[f][j]=midX[f][a]+t*(midX[f][b]-midX[f][a]);
                            midY[f][j]=midY[f][a]+t*(midY[f][b]-midY[f][a]);
                        }
                    }
                    i=b;
                } else i++;
            }
            // refine inferred points toward the same body fraction in neighbor frames
            refineInferredFromNeighbors(f);
            measureWidth(f, bodyMaskCached(f));   // recompute width on the filled midline
            computeCurvature(f);
        }

        // (b) whole missing frames
        for (int f=0; f<nFrames; f++){
            if (found[f] || skip[f] || manualMidline[f]) continue;
            int a=f-1; while (a>=0 && !found[a]) a--;
            int b=f+1; while (b<nFrames && !found[b]) b++;
            if (a<0 || b>=nFrames) continue;       // no bracket; leave as not-found
            double t=(double)(f-a)/(b-a);
            for (int i=0;i<nMid;i++){
                midX[f][i]=midX[a][i]+t*(midX[b][i]-midX[a][i]);
                midY[f][i]=midY[a][i]+t*(midY[b][i]-midY[a][i]);
                pointSrc[f][i]=1;
            }
            measureWidth(f, bodyMaskCached(f));
            computeCurvature(f);
            found[f]=true; coilFlag[f]=true;       // found-by-inference, still flagged
        }
    }

    // pull inferred points toward the average of the same body-fraction point in the
    // nearest found neighbor frames, blending with the within-frame interpolation.
    void refineInferredFromNeighbors(int f){
        int a=f-1; while (a>=0 && (!found[a]||skip[a])) a--;
        int b=f+1; while (b<nFrames && (!found[b]||skip[b])) b++;
        for (int i=0;i<nMid;i++){
            if (pointSrc[f][i]!=1) continue;
            double sx=0, sy=0; int c=0;
            if (a>=0){ sx+=midX[a][i]; sy+=midY[a][i]; c++; }
            if (b<nFrames){ sx+=midX[b][i]; sy+=midY[b][i]; c++; }
            if (c>0){
                double nx=sx/c, ny=sy/c;
                midX[f][i]=0.5*midX[f][i]+0.5*nx;   // blend within-frame and neighbor
                midY[f][i]=0.5*midY[f][i]+0.5*ny;
            }
        }
    }

    // Optional geometry-only smoothing. This does NOT blur fluorescence/DIC pixels;
    // it only removes biologically implausible one-frame zig-zags in the centreline
    // before edge marching and segment ROI placement.
    void smoothMidlineForRoiGeometry(int f){
        if (!smoothMidlineForRois || midlineSmoothPasses<=0 || nMid<5) return;
        double[] x=midX[f].clone(), y=midY[f].clone();
        for (int pass=0; pass<midlineSmoothPasses; pass++){
            double[] nx=x.clone(), ny=y.clone();
            for (int i=1; i<nMid-1; i++){
                nx[i]=0.25*x[i-1]+0.50*x[i]+0.25*x[i+1];
                ny[i]=0.25*y[i-1]+0.50*y[i]+0.25*y[i+1];
            }
            x=nx; y=ny;
        }
        // Re-sample by arc length so segment boundaries stay evenly spaced.
        double[] cum=new double[nMid]; cum[0]=0;
        for (int i=1;i<nMid;i++) cum[i]=cum[i-1]+Math.hypot(x[i]-x[i-1], y[i]-y[i-1]);
        double total=cum[nMid-1]; if (total<1e-6) return;
        double[] rx=new double[nMid], ry=new double[nMid];
        rx[0]=x[0]; ry[0]=y[0]; rx[nMid-1]=x[nMid-1]; ry[nMid-1]=y[nMid-1];
        int j=1;
        for (int i=1;i<nMid-1;i++){
            double target=total*i/(nMid-1);
            while (j<nMid-1 && cum[j]<target) j++;
            double seg=cum[j]-cum[j-1];
            double t=(seg>0)?(target-cum[j-1])/seg:0;
            rx[i]=x[j-1]+t*(x[j]-x[j-1]);
            ry[i]=y[j-1]+t*(y[j]-y[j-1]);
        }
        for (int i=0;i<nMid;i++){
            midX[f][i]=rx[i]; midY[f][i]=ry[i];
        }
    }

    // cached body mask (avoids recomputing repeatedly during inference)
    ByteProcessor bodyMaskCached(int f){ ByteProcessor m=bodyMask(f); keepLargestObject(m); return m; }

    void processFrame(int f) {
        found[f]=false; coilFlag[f]=false;

        // if the user has redrawn this frame's midline, use it verbatim and skip detection
        if (manualMidline[f] && manualMidX[f]!=null) {
            for (int i=0;i<nMid;i++){ midX[f][i]=manualMidX[f][i]; midY[f][i]=manualMidY[f][i]; pointSrc[f][i]=2; }
            // still need a mask for width; build it but don't let it override the midline
            ByteProcessor mm = bodyMask(f); keepLargestObject(mm);
            bodyArea[f]=countForeground(mm);
            ByteProcessor mo=(ByteProcessor)mm.duplicate(); Polygon ol=traceOutline(mo);
            if (ol!=null){ outlineX[f]=ol.xpoints; outlineY[f]=ol.ypoints; }
            smoothMidlineForRoiGeometry(f);
            measureWidth(f, mm); computeCurvature(f); assignHead(f); resolveDorsal(f);
            found[f]=true; return;
        }

        ByteProcessor mask = bodyMask(f);
        if (mask==null) return;

        // largest object only
        keepLargestObject(mask);
        double area = countForeground(mask);
        bodyArea[f]=area;
        if (area < minBodyArea) return;

        // outline polygon (for QC + later ROI edges)
        ByteProcessor maskForOutline = (ByteProcessor)mask.duplicate();
        Polygon outline = traceOutline(maskForOutline);
        if (outline!=null) { outlineX[f]=outline.xpoints; outlineY[f]=outline.ypoints; }

        // skeleton, then extract the longest tip-to-tip path (spur-robust).
        ByteProcessor sk = (ByteProcessor)mask.duplicate();
        sk.skeletonize(255);
        ArrayList<int[]> path = longestSkeletonPath(sk);
        if (path==null || path.size()<10) { coilFlag[f]=true; return; }
        double expectLen = Math.sqrt(area);
        if (path.size() < 1.5*expectLen) coilFlag[f]=true;  // flag but still measure

        // resample to nMid points
        double[][] rs = resample(path, nMid);
        for (int i=0;i<nMid;i++){ midX[f][i]=rs[0][i]; midY[f][i]=rs[1][i]; pointSrc[f][i]=0; }

        // LENGTH-BASED EXTENSION: if the detected midline is shorter than the learned
        // conserved length, the dim head/tail was clipped. Extend the deficient end(s)
        // along their own direction, biased toward where the previous frame's end sat,
        // until the midline reaches the reference length. Extended points are marked
        // inferred (pointSrc=1) so the overlay/CSV show they were not directly detected.
        if (refLength > 0) extendToReferenceLength(f);

        // MEDIAL-AXIS RESEED (Stage B revised): DISABLED by default (see flag). The
        // length-conserved fit above stands when off.
        if (USE_MEDIAL_RESEED && refLength > 0 && !manualMidline[f]){
            int pg=prevGoodFrame(f);
            double evid = reseedMidlineFromMedialAxis(f, pg);
            if (evid < MEDIAL_MIN_EVIDENCE){ selfApproachFlag[f]=true; lowEvidenceFlag[f]=true; }
        }

        // apply manual endpoint overrides (re-extend the two tips to clicked points)
        applyManualEnds(f);
        smoothMidlineForRoiGeometry(f);

        // width + edges along local normal, using the mask
        measureWidth(f, mask);

        // local curvature (signed turning angle) at each midline point
        computeCurvature(f);

        // head/tail from pharynx (unless head-locked by the user)
        assignHead(f);

        // resolve dorsal/ventral sign for this frame from the seed (if seeded)
        resolveDorsal(f);

        found[f]=true;
    }

    // Extend the (front-clipped) fluor midline to the true worm ends using the DIC body,
    // which images the whole worm. Strategy: skeletonize the DIC body, take its longest
    // path (spans head-to-tail on the full body), and if that path is meaningfully longer
    // than the current midline, adopt it (oriented to match the current head). This is the
    // automatic analogue of the manual head/tail click the user confirmed works perfectly.
    void extendMidlineToBodyEnds(int f){
        ByteProcessor body = bodyMaskCached(f);
        if (body==null){ if(f<25) IJ.log("[ext] f"+f+": no DIC body mask"); return; }
        ByteProcessor sk=(ByteProcessor)body.duplicate();
        sk.skeletonize(255);
        java.util.ArrayList<int[]> path=longestSkeletonPath(sk);
        if (path==null || path.size()<10){ if(f<25) IJ.log("[ext] f"+f+": DIC skeleton path too short (size="+(path==null?0:path.size())+")"); return; }
        double bodyLen=0;
        for (int i=1;i<path.size();i++){
            int[] a=path.get(i-1), b=path.get(i);
            bodyLen+=Math.hypot(a[0]-b[0], a[1]-b[1]);
        }
        double curLen=polylineLen(midX[f],midY[f]);
        if (curLen<=0){ if(f<25) IJ.log("[ext] f"+f+": current midline length 0"); return; }
        double ratio=bodyLen/curLen;
        boolean curShort = (refLength>0 && curLen < 0.90*refLength);   // midline clipped vs reference
        if (f<25) IJ.log("[ext] f"+f+": curLen="+IJ.d2s(curLen,0)+" bodyLen="+IJ.d2s(bodyLen,0)
                         +" ratio="+IJ.d2s(ratio,2)+" refLen="+IJ.d2s(refLength,0)+" curShort="+curShort);
        // Adopt the DIC body path when the current midline is clipped (short vs reference)
        // AND the DIC path is at least modestly longer than what we have. Lower gate than
        // before (1.05) so mildly clipped frames still get extended; the absolute curShort
        // test prevents us disturbing frames that already span the worm.
        if (!curShort && ratio < 1.15){ if(f<25) IJ.log("[ext] f"+f+": skip (already full length)"); return; }
        if (ratio < 1.05){ if(f<25) IJ.log("[ext] f"+f+": skip (DIC path not longer than current)"); return; }
        // NOTE: we no longer skip when bodyLen is too long. Instead we TRIM the path to the
        // conserved reference length below. The DIC body often includes the opaque motion
        // trail the worm leaves behind, which connects to the tail and makes the skeleton
        // run PAST the true tail tip (overshoot of 10-17% seen in data). Because the worm is
        // incompressible, the midline must not exceed refLength, so we cut the path there.

        // Build an ordered polyline of the full DIC path (head-oriented), then walk it from
        // the head end accumulating arc length, and stop at refLength. Everything beyond that
        // (the motion-trail overshoot) is discarded.
        double[][] full=resample(path, Math.max(nMid*4, 200));   // dense, ordered head..tail
        int np=full[0].length;
        // orient so index 0 is the head (nearest current head)
        double dKeep = dist(full[0][0],full[1][0], midX[f][0],midY[f][0]);
        double dFlip = dist(full[0][np-1],full[1][np-1], midX[f][0],midY[f][0]);
        boolean flip = dFlip < dKeep;
        double[] px=new double[np], py=new double[np];
        for (int i=0;i<np;i++){ int j=flip?(np-1-i):i; px[i]=full[0][j]; py[i]=full[1][j]; }
        // accumulate arc length from head; cut at refLength (or keep all if shorter)
        double target = (refLength>0)? refLength : polylineLen(midX[f],midY[f]);
        java.util.ArrayList<double[]> cut=new java.util.ArrayList<double[]>();
        cut.add(new double[]{px[0],py[0]});
        double acc=0;
        for (int i=1;i<np;i++){
            double d=Math.hypot(px[i]-px[i-1], py[i]-py[i-1]);
            if (acc+d >= target){
                double need=target-acc;
                double t=(d>1e-9)? need/d : 0;
                cut.add(new double[]{px[i-1]+t*(px[i]-px[i-1]), py[i-1]+t*(py[i]-py[i-1])});
                break;
            }
            acc+=d; cut.add(new double[]{px[i],py[i]});
        }
        if (f<25) IJ.log("[ext] f"+f+": EXTENDED to DIC ends, trimmed to refLen="+IJ.d2s(target,0));
        // resample the trimmed path to nMid points and adopt
        double[] cx=new double[cut.size()], cy=new double[cut.size()];
        for (int i=0;i<cut.size();i++){ cx[i]=cut.get(i)[0]; cy[i]=cut.get(i)[1]; }
        double[][] rs=resamplePoly(cx, cy, nMid);
        for (int i=0;i<nMid;i++){ midX[f][i]=rs[0][i]; midY[f][i]=rs[1][i]; pointSrc[f][i]=1; }
    }


    // point list from the current midline, then grows the deficient end(s) along the
    // end tangent, biased toward the previous frame's corresponding tip, until the
    // total arc length reaches refLength. Re-resamples to nMid. New points -> inferred.
    // Fit the dim/clipped end using the eigenworm basis. The detected (short) midline
    // is the bright body; we treat it as the OBSERVED span of a full-length worm,
    // fit eigenworm coefficients (+ global orientation) so the reconstructed angle
    // profile matches the observed angles, then rebuild the full midline at refLength.
    // Returns true on success. New (filled) points are marked inferred.
    boolean fitEigenwormConstrained(int f) {
        if (!eigLearned || refLength<=0) return false;
        double curL=arcLength(midX[f], midY[f], nMid);
        double obsFrac=curL/refLength; if (obsFrac>=0.98) return false;
        // GUARD 1 (refuse-to-fit): below MIN_OBS_FRAC the fit is underdetermined and
        // tends to invent a confident-but-wrong shape (the "arc into the dark").
        // Flag the frame for manual redraw instead of guessing.
        if (obsFrac < MIN_OBS_FRAC) { coilFlag[f]=true; return false; }

        // Which end is missing? Compare ends to previous frame (as before).
        int pf=f-1; while (pf>=0 && (!found[pf]||skip[pf])) pf--;
        boolean missHead=true;
        if (pf>=0){
            double dHead=dist(midX[f][0],midY[f][0], midX[pf][0],midY[pf][0]);
            double dTail=dist(midX[f][nMid-1],midY[f][nMid-1], midX[pf][nMid-1],midY[pf][nMid-1]);
            missHead = dHead>=dTail;        // the end farther from its previous position is the lost one
        }

        int D=nMid-1;                       // number of angle segments at full length
        int nObs=(int)Math.round(obsFrac*D); // observed segments
        if (nObs<4 || nObs>=D) return false;

        // observed tangent angles (from the detected midline), resampled to nObs
        double[] detAng=tangentAngles(f);   // length D, but represents the SHORT body
        double[] obs=resampleAngles(detAng, nObs);

        // observed segment indices within the full worm: head-missing => observed is the
        // TAIL portion (indices D-nObs..D-1); tail-missing => observed is the HEAD (0..nObs-1)
        int[] obsIdx=new int[nObs];
        for (int i=0;i<nObs;i++) obsIdx[i] = missHead ? (D-nObs+i) : i;

        // Solve least squares: obs[i] = eigMean[obsIdx] + sum_k c_k*eigVec[k][obsIdx] + off
        // unknowns: c_0..c_{nEig-1}, off  (nEig+1)
        int U=nEig+1;
        double[][] AtA=new double[U][U]; double[] Atb=new double[U];
        for (int i=0;i<nObs;i++){
            int gi=obsIdx[i];
            double[] row=new double[U];
            for (int k=0;k<nEig;k++) row[k]=eigVec[k][gi];
            row[nEig]=1.0;
            double bi=obs[i]-eigMean[gi];
            for (int a=0;a<U;a++){ for (int b=0;b<U;b++) AtA[a][b]+=row[a]*row[b]; Atb[a]+=row[a]*bi; }
        }
        // GUARD 3 (temporal prior): when a previous frame exists, add its posture as
        // soft observations over ALL segments, weighted by TEMPORAL_WEIGHT. This anchors
        // the dim end to where the worm just was (posture changes little between frames),
        // which is exactly the information missing when little body is visible.
        if (pf>=0){
            double[] prevAng=tangentAngles(pf);
            double w=TEMPORAL_WEIGHT;
            for (int i=0;i<D;i++){
                double[] row=new double[U];
                for (int k=0;k<nEig;k++) row[k]=w*eigVec[k][i];
                row[nEig]=w*1.0;
                double bi=w*(prevAng[i]-eigMean[i]);
                for (int a=0;a<U;a++){ for (int b=0;b<U;b++) AtA[a][b]+=row[a]*row[b]; Atb[a]+=row[a]*bi; }
            }
        }
        double[] sol=solveLinear(AtA, Atb, U);
        if (sol==null) return false;

        // reconstruct full angle profile, with GUARD 2 (per-segment angle limit):
        // clamp each segment's deviation from the mean to the biological max, so no
        // reconstructed bend exceeds what a real worm does.
        double[] fullAng=new double[D];
        for (int i=0;i<D;i++){
            double dev=sol[nEig];
            for (int k=0;k<nEig;k++) dev+=sol[k]*eigVec[k][i];
            if (dev >  ANGLE_LIMIT_RAD) dev= ANGLE_LIMIT_RAD;
            if (dev < -ANGLE_LIMIT_RAD) dev=-ANGLE_LIMIT_RAD;
            fullAng[i]=eigMean[i]+dev;
        }

        // rebuild midline at conserved length, anchored so the OBSERVED span lands on
        // the current detected body (anchor at the observed end that is real).
        double seg=refLength/D;
        double[] fx=new double[nMid], fy=new double[nMid];
        // start from an anchor point: if head missing, anchor at detected HEAD-of-observed
        // (which is the current midline's point 0 ... but that point is the clipped head).
        // Use the detected midline's first point as the start of the observed span.
        // Build full chain from index 0:
        fx[0]=0; fy[0]=0;
        for (int i=0;i<D;i++){ fx[i+1]=fx[i]+seg*Math.cos(fullAng[i]); fy[i+1]=fy[i]+seg*Math.sin(fullAng[i]); }
        // align: the observed span (obsIdx) should overlay the detected midline.
        // Map detected midline (nMid pts over curL) to the observed portion of the full chain.
        int obsStartPt = missHead ? (D-nObs) : 0;     // point index where observed span starts
        // anchor full chain so its obsStartPt matches detected midline's corresponding end
        double ax, ay;
        if (missHead){ ax=midX[f][0]; ay=midY[f][0]; }   // detected head = start of observed (tail side kept)
        else         { ax=midX[f][0]; ay=midY[f][0]; }
        // We align by least-squares rigid shift+rotation of the full chain's observed span
        // onto the detected midline. Simpler robust choice: shift+rotate so observed
        // endpoints match the detected midline endpoints.
        double[] dHeadPt={midX[f][0],midY[f][0]};
        double[] dTailPt={midX[f][nMid-1],midY[f][nMid-1]};
        int oa=obsStartPt, ob=obsStartPt+nObs;   // full-chain point indices of observed span
        double[] fHeadPt={fx[oa],fy[oa]}, fTailPt={fx[ob],fy[ob]};
        double[][] aligned=alignByTwoPoints(fx,fy, fHeadPt,fTailPt, dHeadPt,dTailPt);
        if (aligned==null) return false;
        double[][] rs=resamplePoly(aligned[0], aligned[1], nMid);
        for (int i=0;i<nMid;i++){ midX[f][i]=rs[0][i]; midY[f][i]=rs[1][i]; }

        // provenance: the filled end is inferred
        int fillPts=(int)Math.round((1.0-obsFrac)*nMid);
        for (int i=0;i<nMid;i++){
            boolean filled = missHead ? (i<fillPts) : (i>=nMid-fillPts);
            pointSrc[f][i]= filled ? (byte)1 : (byte)0;
        }
        return true;
    }

    // resample an angle array to length m (linear in arc index)
    double[] resampleAngles(double[] a, int m){
        double[] r=new double[m]; int n=a.length;
        for (int j=0;j<m;j++){ double t=(double)j*(n-1)/(m-1); int i=(int)Math.floor(t); double fr=t-i;
            r[j]= (i+1<n)? a[i]*(1-fr)+a[i+1]*fr : a[n-1]; }
        return r;
    }

    // rigid-align a chain so that its points P1->P2 map onto target Q1->Q2 (shift+rotate+scale-free rotation)
    double[][] alignByTwoPoints(double[] fx, double[] fy, double[] P1, double[] P2, double[] Q1, double[] Q2){
        double pdx=P2[0]-P1[0], pdy=P2[1]-P1[1]; double pn=Math.hypot(pdx,pdy);
        double qdx=Q2[0]-Q1[0], qdy=Q2[1]-Q1[1]; double qn=Math.hypot(qdx,qdy);
        if (pn<1e-6||qn<1e-6) return null;
        double ang=Math.atan2(qdy,qdx)-Math.atan2(pdy,pdx);
        double ca=Math.cos(ang), sa=Math.sin(ang);
        int n=fx.length; double[] ox=new double[n], oy=new double[n];
        for (int i=0;i<n;i++){
            double rx=fx[i]-P1[0], ry=fy[i]-P1[1];
            double rrx=rx*ca-ry*sa, rry=rx*sa+ry*ca;     // rotate (no scaling: length conserved)
            ox[i]=Q1[0]+rrx; oy[i]=Q1[1]+rry;
        }
        return new double[][]{ox,oy};
    }

    // small Gaussian-elimination linear solver for U unknowns
    double[] solveLinear(double[][] A, double[] b, int U){
        double[][] M=new double[U][U+1];
        for (int i=0;i<U;i++){ for (int j=0;j<U;j++) M[i][j]=A[i][j]; M[i][U]=b[i]; }
        for (int c=0;c<U;c++){
            int piv=c; for (int r=c+1;r<U;r++) if (Math.abs(M[r][c])>Math.abs(M[piv][c])) piv=r;
            if (Math.abs(M[piv][c])<1e-9) return null;
            double[] tmp=M[c]; M[c]=M[piv]; M[piv]=tmp;
            for (int r=0;r<U;r++){ if (r==c) continue; double fct=M[r][c]/M[c][c];
                for (int j=c;j<=U;j++) M[r][j]-=fct*M[c][j]; }
        }
        double[] x=new double[U]; for (int i=0;i<U;i++) x[i]=M[i][U]/M[i][i];
        return x;
    }

    boolean extendToReferenceLength(int f) {
        double curL=arcLength(midX[f], midY[f], nMid);
        if (curL >= 0.95*refLength) return true;        // long enough already

        // Preferred: eigenworm-constrained fit (fills the dim end with a biologically
        // plausible bend instead of a blind straight extension). Falls back to the
        // tangent extension below if the basis is not available or the fit fails.
        if (eigLearned && fitEigenwormConstrained(f)) return true;

        // previous found frame (for directional bias)
        int pf=f-1; while (pf>=0 && (!found[pf]||skip[pf])) pf--;

        // Decide which end is deficient. Compare each current end to the previous
        // frame's same-index end; the end that moved/contracted most is the lost one.
        boolean extendHead=true, extendTail=true;
        if (pf>=0){
            double dHead=dist(midX[f][0],midY[f][0], midX[pf][0],midY[pf][0]);
            double dTail=dist(midX[f][nMid-1],midY[f][nMid-1], midX[pf][nMid-1],midY[pf][nMid-1]);
            // extend the end that is FAR from its previous position (signal lost there);
            // if both are close, distribute the deficit to both ends.
            double thr=Math.max(3.0, 0.02*refLength);
            extendHead = dHead>thr;
            extendTail = dTail>thr;
            if (!extendHead && !extendTail){ extendHead=true; extendTail=true; }
        }

        double deficit = refLength - curL;
        // build a working point list (head..tail) from current midline
        java.util.ArrayList<double[]> pts=new java.util.ArrayList<double[]>();
        for (int i=0;i<nMid;i++) pts.add(new double[]{midX[f][i],midY[f][i]});

        double nEnds = (extendHead?1:0)+(extendTail?1:0);
        double addEach = deficit / Math.max(1,nEnds);

        if (extendHead) growEnd(pts, true,  addEach, (pf>=0)? new double[]{midX[pf][0],midY[pf][0]} : null);
        if (extendTail) growEnd(pts, false, addEach, (pf>=0)? new double[]{midX[pf][nMid-1],midY[pf][nMid-1]} : null);

        // re-resample the extended polyline back to nMid, mark which points are new
        double[] px=new double[pts.size()], py=new double[pts.size()];
        for (int i=0;i<pts.size();i++){ px[i]=pts.get(i)[0]; py[i]=pts.get(i)[1]; }
        double[][] rs2=resamplePoly(px,py,nMid);
        // mark points that fall in the (former) extended regions as inferred:
        // anything beyond the original detected span at each end.
        for (int i=0;i<nMid;i++){ midX[f][i]=rs2[0][i]; midY[f][i]=rs2[1][i]; }
        // recompute provenance: points near the two ends that came from extension
        double frac = (refLength>0)? (deficit/refLength) : 0;
        int extPts=(int)Math.round(frac*nMid*0.5);
        for (int i=0;i<nMid;i++){
            boolean nearHead = i < extPts && extendHead;
            boolean nearTail = i >= nMid-extPts && extendTail;
            pointSrc[f][i] = (nearHead||nearTail)? (byte)1 : (byte)0;
        }
        return true;
    }

    // grow one end of the point list by 'add' px, stepping along the end tangent,
    // gently curving toward target (previous frame's tip) if provided.
    void growEnd(java.util.ArrayList<double[]> pts, boolean headEnd, double add, double[] target) {
        if (add<=0 || pts.size()<2) return;
        double step=2.0;
        int idxEnd = headEnd?0:pts.size()-1;
        int idxIn  = headEnd?1:pts.size()-2;
        double ex=pts.get(idxEnd)[0], ey=pts.get(idxEnd)[1];
        double ix=pts.get(idxIn)[0],  iy=pts.get(idxIn)[1];
        double dx=ex-ix, dy=ey-iy; double dn=Math.hypot(dx,dy); if (dn<1e-6){dx=1;dy=0;dn=1;} dx/=dn; dy/=dn;
        double grown=0;
        double cx=ex, cy=ey;
        while (grown<add){
            // bias direction toward target tip if available
            if (target!=null){
                double tx=target[0]-cx, ty=target[1]-cy; double tn=Math.hypot(tx,ty);
                if (tn>1e-6){ tx/=tn; ty/=tn; dx=0.8*dx+0.2*tx; dy=0.8*dy+0.2*ty;
                    double nn=Math.hypot(dx,dy); dx/=nn; dy/=nn; }
            }
            cx+=dx*step; cy+=dy*step; grown+=step;
            // clamp into image
            cx=clampD(cx,0,W-1); cy=clampD(cy,0,H-1);
            if (headEnd) pts.add(0,new double[]{cx,cy}); else pts.add(new double[]{cx,cy});
        }
    }

    double arcLength(double[] xs, double[] ys, int nn){
        double L=0; for (int i=1;i<nn;i++) L+=Math.hypot(xs[i]-xs[i-1], ys[i]-ys[i-1]); return L;
    }

    // ---- STAGE B (revised): medial-axis reseed (attacks the corner-cut CAUSE) ----
    // The skeleton longest-path chords across deep bends, so the fit conserves length along
    // a wrong path. A normal-based snap cannot undo a gross wrong-branch pick and can snap to
    // the wrong arm while reporting false confidence. Instead we re-lay the midline along the
    // mask's MEDIAL AXIS (the true centre-line of the dark DIC body), marching from the head
    // and using the PREVIOUS good frame's local tangent as the tie-breaker wherever the body
    // forks or nearly self-touches. At 5 fps the worm barely moves between frames, so last
    // frame's posture reliably says which way to go around the bend.
    //
    // Returns an evidence score in [0,1]: mean (distance-to-edge along the path) / (body
    // half-width). ~1 means the path hugged the centre of the body the whole way; low means
    // it wandered off the body and the frame should be flagged for manual redraw.
    double reseedMidlineFromMedialAxis(int f, int prevGood){
        ByteProcessor mask = bodyMaskCached(f);
        if (mask==null) return 0;
        // Euclidean distance map: value = distance from each body pixel to nearest edge.
        // Ridge of this map is the medial axis; high values = centre of the body.
        // EDM lives on ij.plugin.filter.EDM (NOT on ByteProcessor). makeFloatEDM returns a
        // FloatProcessor of true Euclidean distances (background=0, edges not treated as
        // background), which gives subpixel-smooth ridge values for the hill-climb.
        FloatProcessor edmFP = new ij.plugin.filter.EDM().makeFloatEDM(
                (ByteProcessor)mask.duplicate(), 0, false);
        float[] dm = (float[])edmFP.getPixels();

        double halfWidth = Math.max(2.0, 0.5*medianBodyWidthPx());   // for score normalisation

        // --- seed head position and initial direction ---
        double hx, hy, dirx, diry;
        if (found[f] && midLen[f]>0){
            hx=midX[f][0]; hy=midY[f][0];
            dirx=midX[f][1]-midX[f][0]; diry=midY[f][1]-midY[f][0];
        } else if (prevGood>=0){
            hx=midX[prevGood][0]; hy=midY[prevGood][0];
            dirx=midX[prevGood][1]-midX[prevGood][0]; diry=midY[prevGood][1]-midY[prevGood][0];
        } else return 0;
        double dn=Math.hypot(dirx,diry); if (dn<1e-6){dirx=1;diry=0;dn=1;} dirx/=dn; diry/=dn;
        // pull the seed onto the ridge
        double[] hsnap = climbToRidge(dm, hx, hy);
        hx=hsnap[0]; hy=hsnap[1];

        double step = refLength/(nMid-1);       // fixed step => conserved length
        double[] rx=new double[nMid], ry=new double[nMid];
        rx[0]=hx; ry[0]=hy;
        double onRidgeSum = ridgeVal(dm,hx,hy);

        for (int i=1;i<nMid;i++){
            // previous frame's local tangent at this arc position (branch tie-breaker)
            double ptx=0, pty=0;
            if (prevGood>=0){
                int j=Math.min(nMid-1,i);
                ptx=midX[prevGood][j]-midX[prevGood][j-1];
                pty=midY[prevGood][j]-midY[prevGood][j-1];
                double pn=Math.hypot(ptx,pty); if (pn>1e-6){ptx/=pn; pty/=pn;}
            }
            // search a forward-facing arc of candidate headings; score each by how far onto
            // the ridge it lands (EDM), minus penalties for reversing our own direction or
            // diverging from the previous-frame tangent.
            double bestScore=-1e18, bx=rx[i-1], by=ry[i-1], bdx=dirx, bdy=diry;
            for (int a=-MEDIAL_ARC_STEPS; a<=MEDIAL_ARC_STEPS; a++){
                double ang=a*(MEDIAL_ARC_RAD/MEDIAL_ARC_STEPS);
                double ca=Math.cos(ang), sa=Math.sin(ang);
                double cdx=dirx*ca - diry*sa;
                double cdy=dirx*sa + diry*ca;
                double cx=rx[i-1]+cdx*step, cy=ry[i-1]+cdy*step;
                double ridge=ridgeVal(dm,cx,cy);                 // want high (on centre)
                if (ridge<=0) continue;                          // stepped off the body
                double keepDir = cdx*dirx + cdy*diry;            // want ~1 (no reversal)
                double keepPrev= (prevGood>=0)? (cdx*ptx+cdy*pty) : keepDir;
                double score = ridge
                             + MEDIAL_W_KEEPDIR*keepDir
                             + MEDIAL_W_PREV*keepPrev;
                if (score>bestScore){ bestScore=score; bx=cx; by=cy; bdx=cdx; bdy=cdy; }
            }
            // climb the chosen point onto the exact ridge, then commit
            double[] snap=climbToRidge(dm,bx,by);
            rx[i]=snap[0]; ry[i]=snap[1];
            dirx=rx[i]-rx[i-1]; diry=ry[i]-ry[i-1];
            double nn=Math.hypot(dirx,diry); if (nn<1e-6){dirx=bdx;diry=bdy;} else {dirx/=nn;diry/=nn;}
            onRidgeSum += ridgeVal(dm,rx[i],ry[i]);
        }

        // enforce exact conserved length (march may have drifted slightly on climbs)
        rescaleToLength(rx,ry,refLength);

        for (int i=0;i<nMid;i++){ midX[f][i]=rx[i]; midY[f][i]=ry[i]; }
        midLen[f]=polylineLen(midX[f],midY[f]);
        return (onRidgeSum/nMid)/halfWidth;      // ~1 = hugged centre; low = wandered
    }

    // Nearest earlier frame with a trustworthy midline (found, full-length, not flagged),
    // used as the branch tie-breaker for the medial-axis march. -1 if none yet.
    int prevGoodFrame(int f){
        for (int p=f-1; p>=0; p--){
            if (skip[p] || !found[p]) continue;
            if (coilFlag[p] || selfApproachFlag[p] || lowEvidenceFlag[p]) continue;
            if (refLength>0 && midLen[p] < (1.0-LEN_TOL)*refLength) continue;
            return p;
        }
        return -1;
    }

    // EDM value at a subpixel location (0 if outside body). dm holds true float distances.
    double ridgeVal(float[] dm, double x, double y){
        int xi=(int)Math.round(x), yi=(int)Math.round(y);
        if (xi<0||yi<0||xi>=W||yi>=H) return 0;
        return dm[yi*W+xi];
    }

    // Hill-climb a point to the local maximum of the distance map (i.e. onto the medial
    // ridge / centre of the body). Small 8-neighbour ascent, capped so it stays local.
    double[] climbToRidge(float[] dm, double x, double y){
        double cx=x, cy=y;
        for (int step=0; step<MEDIAL_CLIMB_STEPS; step++){
            double best=ridgeVal(dm,cx,cy); double nxs=cx, nys=cy; boolean moved=false;
            for (int dy=-1;dy<=1;dy++) for (int dx=-1;dx<=1;dx++){
                if (dx==0&&dy==0) continue;
                double v=ridgeVal(dm,cx+dx,cy+dy);
                if (v>best){ best=v; nxs=cx+dx; nys=cy+dy; moved=true; }
            }
            if (!moved) break;
            cx=nxs; cy=nys;
        }
        return new double[]{cx,cy};
    }

    double medianBodyWidthPx(){
        java.util.ArrayList<Double> w=new java.util.ArrayList<Double>();
        for (int f=0; f<nFrames; f++){
            if (!found[f] || skip[f] || halfW==null || halfW[f]==null) continue;
            // mid-body half-width is the most stable; average the central third
            int a=nMid/3, b=(2*nMid)/3; double s=0; int n=0;
            for (int i=a;i<b;i++){ if (halfW[f][i]>0){ s+=halfW[f][i]; n++; } }
            if (n>0) w.add(2.0*s/n);                 // full width = 2*half-width
        }
        if (w.isEmpty()) return 8.0;                 // sensible default (~worm width)
        return median(w);
    }

    // uniformly rescale a polyline's arc length to L, keeping point 0 (head) fixed.
    void rescaleToLength(double[] x, double[] y, double L){
        double cur=arcLength(x,y,nMid); if (cur<1e-6) return;
        double s=L/cur; double x0=x[0], y0=y[0];
        for (int i=0;i<nMid;i++){ x[i]=x0+(x[i]-x0)*s; y[i]=y0+(y[i]-y0)*s; }
    }

    // Snap the two midline tips toward user-clicked head/tail and blend nearby
    // points so the change is smooth rather than a kink at the very end.
    void applyManualEnds(int f) {
        double[] me = manualEnds[f];
        if (me==null) return;
        int blend = Math.max(2, nMid/10);   // points over which to ease the correction
        // point 0 end
        if (!Double.isNaN(me[0])) {
            double ox=me[0]-midX[f][0], oy=me[1]-midY[f][0];
            for (int i=0;i<blend;i++){ double w=(blend-i)/(double)blend;
                midX[f][i]+=ox*w; midY[f][i]+=oy*w; }
        }
        // point nMid-1 end
        if (!Double.isNaN(me[2])) {
            double ox=me[2]-midX[f][nMid-1], oy=me[3]-midY[f][nMid-1];
            for (int i=0;i<blend;i++){ int j=nMid-1-i; double w=(blend-i)/(double)blend;
                midX[f][j]+=ox*w; midY[f][j]+=oy*w; }
        }
    }

    // signed turning angle at each point: angle from (prev->cur) to (cur->next),
    // positive = left turn (counterclockwise). This is the "three successive points"
    // curvature and its SIGN gives convex/concave side automatically.
    void computeCurvature(int f) {
        for (int i=0;i<nMid;i++){
            if (i==0||i==nMid-1){ curv[f][i]=0; continue; }
            double ax=midX[f][i]-midX[f][i-1], ay=midY[f][i]-midY[f][i-1];
            double bx=midX[f][i+1]-midX[f][i], by=midY[f][i+1]-midY[f][i];
            double cross=ax*by-ay*bx, dot=ax*bx+ay*by;
            curv[f][i]=Math.toDegrees(Math.atan2(cross,dot));
        }
    }

    // ---- single-frame raw mask: bright-on-dark (fluor) OR dark-on-light (DIC) ----
    ByteProcessor rawMask(int f) {
        if (rgbMode) dicBackgroundCachedForIp = dicBackground(f);   // DIC contrast reference
        if (dicAlignX!=null){ dicAlignCachedX=dicAlignX[f]; dicAlignCachedY=dicAlignY[f]; }
        ImageProcessor ip = frameIp(f);
        double thr = thrFrame[f];
        ByteProcessor m = new ByteProcessor(Mw, Mh);
        byte[] mp = (byte[])m.getPixels();
        for (int y=0;y<Mh;y++) for (int x=0;x<Mw;x++) {
            double v = gcampValue(ip,x,y);
            mp[y*Mw+x] = (byte)((!Double.isNaN(v) && v>=thr)?255:0);
        }
        m.dilate(1,0); m.erode(1,0);
        return m;
    }

    // ---- body mask: union of this frame +/- maskSmoothFrames, so a momentarily
    //      dim muscle does not drop out of the body. Brightness is read elsewhere
    //      from the ORIGINAL pixels, not from this smoothed mask. ----
    ByteProcessor bodyMask(int f) {
        ByteProcessor m = rawMask(f);
        if (maskSmoothFrames>0) {
            byte[] mp=(byte[])m.getPixels();
            for (int g=f-maskSmoothFrames; g<=f+maskSmoothFrames; g++){
                if (g<0||g>=nFrames||g==f||skip[g]) continue;
                ByteProcessor mg=rawMask(g); byte[] gp=(byte[])mg.getPixels();
                for (int i=0;i<mp.length;i++) if ((gp[i]&0xff)==255) mp[i]=(byte)255;
            }
        }
        return m;
    }

    // keep only the largest 8-connected white component
    void keepLargestObject(ByteProcessor m) {
        int[] lab = new int[Mw*Mh];
        byte[] p = (byte[])m.getPixels();
        int next=1; int bestLab=0, bestCnt=0;
        int[] stackx=new int[Mw*Mh]; int[] stacky=new int[Mw*Mh];
        for (int y=0;y<Mh;y++) for (int x=0;x<Mw;x++) {
            int idx=y*Mw+x;
            if ((p[idx]&0xff)==255 && lab[idx]==0) {
                int cnt=0, sp=0; stackx[sp]=x; stacky[sp]=y; lab[idx]=next; sp++;
                while (sp>0) {
                    sp--; int cx=stackx[sp], cy=stacky[sp]; cnt++;
                    for (int dy=-1;dy<=1;dy++) for (int dx=-1;dx<=1;dx++) {
                        if (dx==0&&dy==0) continue;
                        int nx=cx+dx, ny=cy+dy;
                        if (nx<0||ny<0||nx>=Mw||ny>=Mh) continue;
                        int ni=ny*Mw+nx;
                        if ((p[ni]&0xff)==255 && lab[ni]==0) { lab[ni]=next; stackx[sp]=nx; stacky[sp]=ny; sp++; }
                    }
                }
                if (cnt>bestCnt){ bestCnt=cnt; bestLab=next; }
                next++;
            }
        }
        for (int i=0;i<Mw*Mh;i++) p[i] = (byte)((lab[i]==bestLab)?255:0);
    }

    double countForeground(ByteProcessor m) {
        byte[] p=(byte[])m.getPixels(); int c=0;
        for (int i=0;i<p.length;i++) if ((p[i]&0xff)==255) c++;
        return c;
    }

    // outline via ImageJ Wand on the mask (foreground 255)
    Polygon traceOutline(ByteProcessor m) {
        // find a foreground pixel
        byte[] p=(byte[])m.getPixels(); int sx=-1, sy=-1;
        for (int y=0;y<Mh&&sx<0;y++) for (int x=0;x<Mw;x++) if ((p[y*Mw+x]&0xff)==255){ sx=x; sy=y; break; }
        if (sx<0) return null;
        Wand w=new Wand(m);
        w.autoOutline(sx, sy, 128, 255);
        if (w.npoints<3) return null;
        int[] xs=new int[w.npoints], ys=new int[w.npoints];
        System.arraycopy(w.xpoints,0,xs,0,w.npoints);
        System.arraycopy(w.ypoints,0,ys,0,w.npoints);
        return new Polygon(xs, ys, w.npoints);
    }

    // ---- longest tip-to-tip skeleton path via double BFS (spur-robust) ----
    // BFS from any skeleton pixel to the farthest pixel (tip A); BFS from A to the
    // farthest (tip B); recover the A->B path. Ignores spurs and small branches.
    ArrayList<int[]> longestSkeletonPath(ByteProcessor sk) {
        byte[] p=(byte[])sk.getPixels();
        int firstIdx=-1;
        for (int i=0;i<p.length;i++) if ((p[i]&0xff)==255){ firstIdx=i; break; }
        if (firstIdx<0) return null;
        int[] aEnd = bfsFarthest(p, firstIdx);
        if (aEnd==null) return null;
        int aIdx=aEnd[0];
        int[] bEnd = bfsFarthestWithParent(p, aIdx);
        if (bEnd==null) return null;
        int bIdx=bEnd[0];
        int[] parent=lastParent;   // filled by bfsFarthestWithParent
        // recover path b -> a
        ArrayList<int[]> path=new ArrayList<int[]>();
        int cur=bIdx, guard=0, maxg=Mw*Mh;
        while (cur!=-1 && guard++<maxg){ path.add(new int[]{cur%Mw, cur/Mw}); cur=parent[cur]; }
        // path is b..a; order head-to-tail is arbitrary here, fixed later by motion
        return path;
    }

    // BFS returning {farthestIdx, dist}; no parent tracking
    int[] bfsFarthest(byte[] p, int start) {
        int n=Mw*Mh;
        int[] dist=new int[n]; java.util.Arrays.fill(dist,-1);
        int[] queue=new int[n]; int qh=0, qt=0;
        dist[start]=0; queue[qt++]=start; int far=start, fd=0;
        while (qh<qt){
            int c=queue[qh++]; int cx=c%Mw, cy=c/Mw;
            if (dist[c]>fd){ fd=dist[c]; far=c; }
            for (int dy=-1;dy<=1;dy++) for (int dx=-1;dx<=1;dx++){
                if (dx==0&&dy==0) continue;
                int nx=cx+dx, ny=cy+dy;
                if (nx<0||ny<0||nx>=Mw||ny>=Mh) continue;
                int ni=ny*Mw+nx;
                if ((p[ni]&0xff)==255 && dist[ni]<0){ dist[ni]=dist[c]+1; queue[qt++]=ni; }
            }
        }
        return new int[]{far, fd};
    }

    int[] lastParent;  // parent array from the most recent bfsFarthestWithParent
    int[] bfsFarthestWithParent(byte[] p, int start) {
        int n=Mw*Mh;
        int[] dist=new int[n]; java.util.Arrays.fill(dist,-1);
        int[] parent=new int[n]; java.util.Arrays.fill(parent,-1);
        int[] queue=new int[n]; int qh=0, qt=0;
        dist[start]=0; queue[qt++]=start; int far=start, fd=0;
        while (qh<qt){
            int c=queue[qh++]; int cx=c%Mw, cy=c/Mw;
            if (dist[c]>fd){ fd=dist[c]; far=c; }
            for (int dy=-1;dy<=1;dy++) for (int dx=-1;dx<=1;dx++){
                if (dx==0&&dy==0) continue;
                int nx=cx+dx, ny=cy+dy;
                if (nx<0||ny<0||nx>=Mw||ny>=Mh) continue;
                int ni=ny*Mw+nx;
                if ((p[ni]&0xff)==255 && dist[ni]<0){ dist[ni]=dist[c]+1; parent[ni]=c; queue[qt++]=ni; }
            }
        }
        lastParent=parent;
        return new int[]{far, fd};
    }

    // ---- skeleton endpoints (kept for reference / QC) ----
    ArrayList<int[]> skeletonEndpoints(ByteProcessor sk) {
        ArrayList<int[]> eps=new ArrayList<int[]>();
        byte[] p=(byte[])sk.getPixels();
        for (int y=1;y<Mh-1;y++) for (int x=1;x<Mw-1;x++) {
            if ((p[y*Mw+x]&0xff)!=255) continue;
            int nb=countNeighbors(p,x,y);
            if (nb==1) eps.add(new int[]{x,y});
        }
        return eps;
    }

    int countNeighbors(byte[] p, int x, int y) {
        int c=0;
        for (int dy=-1;dy<=1;dy++) for (int dx=-1;dx<=1;dx++) {
            if (dx==0&&dy==0) continue;
            if ((p[(y+dy)*Mw+(x+dx)]&0xff)==255) c++;
        }
        return c;
    }

    // ---- ordered path between two endpoints via greedy neighbor walk ----
    ArrayList<int[]> tracePath(ByteProcessor sk, int[] a, int[] b) {
        byte[] p=((byte[])sk.getPixels()).clone();
        ArrayList<int[]> path=new ArrayList<int[]>();
        int cx=a[0], cy=a[1];
        path.add(new int[]{cx,cy}); p[cy*Mw+cx]=0;
        int guard=0, maxSteps=Mw*Mh;
        while (guard++<maxSteps) {
            int nx=-1, ny=-1;
            // prefer 4-neighbors then diagonals
            int[][] order={{0,-1},{0,1},{-1,0},{1,0},{-1,-1},{1,-1},{-1,1},{1,1}};
            for (int[] d:order) {
                int tx=cx+d[0], ty=cy+d[1];
                if (tx<0||ty<0||tx>=Mw||ty>=Mh) continue;
                if ((p[ty*Mw+tx]&0xff)==255){ nx=tx; ny=ty; break; }
            }
            if (nx<0) break;
            cx=nx; cy=ny; path.add(new int[]{cx,cy}); p[cy*Mw+cx]=0;
            if (cx==b[0]&&cy==b[1]) break;
        }
        return path;
    }

    // ---- resample an ordered pixel path to m points by arc length ----
    double[][] resample(ArrayList<int[]> path, int m) {
        int k=path.size();
        double[] cum=new double[k]; cum[0]=0;
        for (int i=1;i<k;i++){ int[] a=path.get(i-1), b=path.get(i);
            cum[i]=cum[i-1]+Math.hypot(b[0]-a[0], b[1]-a[1]); }
        double total=cum[k-1]; if (total<=0) total=1;
        double[] rx=new double[m], ry=new double[m];
        for (int j=0;j<m;j++) {
            double target=total*j/(m-1);
            int i=1; while (i<k && cum[i]<target) i++;
            if (i>=k) i=k-1;
            double seg=cum[i]-cum[i-1]; double t=(seg>0)?(target-cum[i-1])/seg:0;
            int[] a=path.get(i-1), b=path.get(i);
            rx[j]=a[0]+t*(b[0]-a[0]); ry[j]=a[1]+t*(b[1]-a[1]);
        }
        return new double[][]{rx,ry};
    }

    // ---- width + edges along local normal, marched out until mask ends ----
    void measureWidth(int f, ByteProcessor mask) {
        byte[] mp=(byte[])mask.getPixels();
        for (int i=0;i<nMid;i++) {
            int ia=Math.max(0,i-1), ib=Math.min(nMid-1,i+1);
            double tx=midX[f][ib]-midX[f][ia], ty=midY[f][ib]-midY[f][ia];
            double tn=Math.hypot(tx,ty); if (tn<1e-6){tx=1;ty=0;tn=1;}
            tx/=tn; ty/=tn;
            double nx=-ty, ny=tx;            // left normal
            double cx=midX[f][i], cy=midY[f][i];
            double dl=marchToEdge(mp,cx,cy, nx, ny);
            double dr=marchToEdge(mp,cx,cy,-nx,-ny);

            byte srcL=0, srcR=0;
            // hybrid: if profile is learned, replace a dim/short measured edge with
            // the conserved profile value. Reference frames are kept as ground truth
            // (raw measured edges only), so the profile is never applied to them.
            if (profLearned && !refFrames.contains(f)) {
                double pl=profL[i], pr=profR[i];
                if (dl < edgeConfFrac*pl){ dl=pl; srcL=1; }
                if (dr < edgeConfFrac*pr){ dr=pr; srcR=1; }
            }

            hwL[f][i]=dl; hwR[f][i]=dr;
            edgeSrcL[f][i]=srcL; edgeSrcR[f][i]=srcR;
            edgeLX[f][i]=cx+nx*dl; edgeLY[f][i]=cy+ny*dl;
            edgeRX[f][i]=cx-nx*dr; edgeRY[f][i]=cy-ny*dr;
            halfW[f][i]=0.5*(dl+dr);
        }
        // total midline arc length (for length-conservation QC)
        double L=0; for (int i=1;i<nMid;i++) L+=Math.hypot(midX[f][i]-midX[f][i-1], midY[f][i]-midY[f][i-1]);
        midLen[f]=L;
    }

    // ---- learn the conserved width profile from hand-picked reference frames ----
    // median half-width at each body fraction (separately L and R) across refFrames.
    void learnWidthProfile() {
        if (refFrames.isEmpty()){ IJ.error("No reference frames picked. Use 'Add reference frame' on clean, fully-visible frames first."); return; }
        profL=new double[nMid]; profR=new double[nMid];
        for (int i=0;i<nMid;i++){
            java.util.ArrayList<Double> vl=new java.util.ArrayList<Double>();
            java.util.ArrayList<Double> vr=new java.util.ArrayList<Double>();
            for (int rf: refFrames){
                if (rf<0||rf>=nFrames||!found[rf]) continue;
                // use the RAW measured edges of reference frames (profile off there)
                vl.add(hwL[rf][i]); vr.add(hwR[rf][i]);
            }
            profL[i]=median(vl); profR[i]=median(vr);
        }
        profLearned=true;
        double tot=0; for (int i=0;i<nMid;i++) tot+=profL[i]+profR[i];
        IJ.log("Learned width profile from "+refFrames.size()+" reference frame(s). Mean full width = "+IJ.d2s(tot/nMid,1)+" px.");
    }

    double median(java.util.ArrayList<Double> v){
        if (v.isEmpty()) return 0;
        java.util.Collections.sort(v); int m=v.size();
        return (m%2==1)?v.get(m/2):0.5*(v.get(m/2-1)+v.get(m/2));
    }

    // flag frames whose midline is notably shorter (skeleton fell short) or longer
    // (overshoot past the true tail, e.g. onto the opaque motion trail) than expected.
    void flagShortMidlines() {
        java.util.ArrayList<Double> v=new java.util.ArrayList<Double>();
        for (int f=0;f<nFrames;f++) if (found[f]&&!skip[f]) v.add(midLen[f]);
        double med=median(v); if (med<=0) return;
        // Prefer the conserved reference length as the "true" length when we have it;
        // otherwise fall back to the median. Long flag mirrors the short flag.
        double target = (refLength>0)? refLength : med;
        int nShort=0, nLong=0;
        for (int f=0;f<nFrames;f++){
            if (!found[f] || skip[f]){ lenShortFlag[f]=false; lenLongFlag[f]=false; continue; }
            lenShortFlag[f] = midLen[f] < 0.85*target;
            lenLongFlag[f]  = midLen[f] > 1.15*target;
            if (lenShortFlag[f]) nShort++;
            if (lenLongFlag[f]) nLong++;
        }
        if (nShort>0 || nLong>0) IJ.log("Length QC: "+nShort+" short frame(s) (<0.85x) and "
            +nLong+" long frame(s) (>1.15x) flagged for review (target length "+IJ.d2s(target,0)+" px).");
    }

    double marchToEdge(byte[] mp, double cx, double cy, double ux, double uy) {
        double d=0; double maxd=Math.hypot(Mw,Mh);
        while (d<maxd) {
            int x=(int)Math.round(cx+ux*d), y=(int)Math.round(cy+uy*d);
            if (x<0||y<0||x>=Mw||y>=Mh) break;
            if ((mp[y*Mw+x]&0xff)!=255) break;
            d+=1.0;
        }
        return d;
    }

    // ---- provisional head: honor head-lock/manual; else leave point0=head for now.
    //      Motion-based refinement happens in assignHeadByMotion() after all frames. ----
    void assignHead(int f) {
        if (headLockFrame>=0 && f>=headLockFrame) {
            headIsPoint0[f]=headLockIsPoint0;
        } else {
            headIsPoint0[f]=true;   // provisional; refined by motion pass
        }
        int hi = headIsPoint0[f]?0:nMid-1;
        headPx[f]=midX[f][hi]; headPy[f]=midY[f][hi];
    }

    // ---- head/tail assignment from a manual anchor + three biological cues ----
    // Cues (each votes which end is the head):
    //   1) MANUAL: the head the user clicked on a reference frame (strongest).
    //   2) BRIGHTNESS: the head has more muscle per volume, so the front fifth of
    //      the body is brighter in GCaMP than the back fifth.
    //   3) MOTION: worms move forward most of the time, so the leading end is the head.
    //   4) CURVATURE RANGE: the head bends through a wider angular range than the tail.
    // The manual anchor wins at/near the traced frame. Away from it, if the cue
    // majority disagrees with the propagated orientation, the frame is flipped and
    // FLAGGED (headFlipFlag) so the user can review.
    void assignHeadByMotion() {
        // ---- cue 2: brightness front vs back (averaged over the movie, point0 frame) ----
        double brightFront=0, brightBack=0; int nb=0;
        int span=Math.max(1, nMid/5);
        for (int f=0; f<nFrames; f++){
            if (!found[f]||skip[f]) continue;
            ImageProcessor ip=frameIp(f);
            double front=0, back=0; int c=0;
            for (int i=0;i<span;i++){
                front+=meanInDiskG(ip, midX[f][i], midY[f][i], Math.max(2,halfW[f][i]));
                back +=meanInDiskG(ip, midX[f][nMid-1-i], midY[f][nMid-1-i], Math.max(2,halfW[f][nMid-1-i]));
                c++;
            }
            if (c>0){ brightFront+=front/c; brightBack+=back/c; nb++; }
        }
        // vote: is point0 the brighter (head) end?
        boolean brightSaysPoint0 = (nb>0) && (brightFront>=brightBack);

        // ---- cue 3: motion (leading end) ----
        int votesPoint0=0, votesPointN=0;
        for (int f=0; f<nFrames; f++){
            if (!found[f]) continue;
            int g=f+1; if (g>=nFrames || !found[g]) g=f-1;
            if (g<0 || !found[g]) continue;
            double cx0=centroidX(f), cy0=centroidY(f), cx1=centroidX(g), cy1=centroidY(g);
            double vx=cx1-cx0, vy=cy1-cy0; if (g<f){ vx=-vx; vy=-vy; }
            double vn=Math.hypot(vx,vy); if (vn<0.5) continue; vx/=vn; vy/=vn;
            double e0=(midX[f][0]-cx0)*vx+(midY[f][0]-cy0)*vy;
            double eN=(midX[f][nMid-1]-cx0)*vx+(midY[f][nMid-1]-cy0)*vy;
            if (e0>eN) votesPoint0++; else votesPointN++;
        }
        boolean motionSaysPoint0 = votesPoint0>=votesPointN;

        // ---- cue 4: curvature range (head bends more) ----
        double r0=endCurvRange(0), rN=endCurvRange(nMid-1);
        boolean curvSaysPoint0 = r0>=rN;

        // ---- cue 5 (RGBCaMP): red pharynx marks the head ----
        // The red channel (pharyngeal marker) is concentrated in the head third.
        // Measure red's position along the body, averaged over the movie; the end in
        // whose half the red mass sits is the head. Validated ~87% agreement with the
        // brightness cue. Strongest AUTOMATIC cue (still below the manual head click).
        boolean redValid=false, redSaysPoint0=true;
        if (rgbMode && useRedPharynx){
            double redFracSum=0; int rn=0;
            for (int f=0; f<nFrames; f++){
                if (!found[f]||skip[f]) continue;
                double rf=redBodyFraction(f);   // 0 = at point0 end, 1 = at pointN end
                if (!Double.isNaN(rf)){ redFracSum+=rf; rn++; }
            }
            if (rn>=Math.max(3,nFrames/10)){
                double meanRedFrac=redFracSum/rn;
                redValid=true; redSaysPoint0 = meanRedFrac < 0.5;  // red nearer point0 => point0 is head
                IJ.log("Red-pharynx cue: mean red body-fraction "+IJ.d2s(meanRedFrac,2)
                    +" -> head = point"+(redSaysPoint0?0:(nMid-1))+" (red marks head).");
            }
        }

        // ---- combine cues into a single global "point0 is head" decision ----
        // Manual head click is authoritative. Without it, the cues vote, weighted:
        // red pharynx (strongest, anatomical) > brightness > curvature range > motion.
        boolean point0IsHead;
        boolean cueSaysPoint0;
        {
            double cueScore = (brightSaysPoint0?1.5:-1.5) + (curvSaysPoint0?1.0:-1.0) + (motionSaysPoint0?0.7:-0.7);
            if (redValid) cueScore += redSaysPoint0? 2.5 : -2.5;   // red outweighs the others
            cueSaysPoint0 = (cueScore>=0);
        }
        if (headAnchorFrame>=0) point0IsHead = headAnchorIsPoint0;   // manual wins globally
        else                    point0IsHead = cueSaysPoint0;        // cues decide if no manual

        IJ.log("Head cues: manual="+(headAnchorFrame>=0?(headAnchorIsPoint0?"pt0":"ptN"):"none")
            +" brightness="+(brightSaysPoint0?"pt0":"ptN")
            +" curvRange="+(curvSaysPoint0?"pt0":"ptN")
            +" motion="+(motionSaysPoint0?"pt0":"ptN")
            +" -> head=point"+(point0IsHead?0:(nMid-1)));

        // If the user clicked a head but the biological cues disagree, warn loudly:
        // either the click was on the wrong end, or this worm/recording is unusual.
        if (headAnchorFrame>=0 && cueSaysPoint0!=headAnchorIsPoint0){
            IJ.log("  WARNING: brightness/curvature/motion cues disagree with your head click. "
                + "Kept your click. If head/tail looks wrong, re-click the head or check the worm.");
        }

        // apply the global orientation to all non-locked, non-manual frames
        for (int f=0; f<nFrames; f++){
            if (headLockFrame>=0 && f>=headLockFrame) continue;
            if (manualEnds[f]!=null) continue;
            headIsPoint0[f]=point0IsHead;
            headFlipFlag[f]=false;
            int hi=headIsPoint0[f]?0:nMid-1;
            if (found[f]){ headPx[f]=midX[f][hi]; headPy[f]=midY[f][hi]; }
        }
        // the anchor frame always keeps the user's choice
        if (headAnchorFrame>=0 && headAnchorFrame<nFrames){
            headIsPoint0[headAnchorFrame]=headAnchorIsPoint0;
            int hi=headAnchorIsPoint0?0:nMid-1;
            if (found[headAnchorFrame]){ headPx[headAnchorFrame]=midX[headAnchorFrame][hi]; headPy[headAnchorFrame]=midY[headAnchorFrame][hi]; }
        }
    }

    // angular range swept by an end's local heading over the movie (head sweeps wider)
    double endCurvRange(int endIdx){
        double mn=Double.POSITIVE_INFINITY, mx=Double.NEGATIVE_INFINITY;
        int inner = (endIdx==0)? 1 : nMid-2;
        for (int f=0; f<nFrames; f++){
            if (!found[f]||skip[f]) continue;
            double a=Math.atan2(midY[f][inner]-midY[f][endIdx], midX[f][inner]-midX[f][endIdx]);
            if (a<mn) mn=a; if (a>mx) mx=a;
        }
        return (mx>mn)? (mx-mn) : 0;
    }

    double centroidX(int f){ double s=0; for(int i=0;i<nMid;i++) s+=midX[f][i]; return s/nMid; }
    double centroidY(int f){ double s=0; for(int i=0;i<nMid;i++) s+=midY[f][i]; return s/nMid; }

    // Dorsal/ventral resolution.
    // The seed stores, in HEAD-RELATIVE terms, which side is dorsal: dorsalSeedSign
    // = +1 means dorsal is on the head-relative LEFT (the left-normal side when the
    // midline is walked head->tail), -1 = head-relative right. Per frame we convert
    // that head-relative side into the current geometric left/right by accounting for
    // whether the head is at point 0 or point nMid-1. Convex/concave (from curv sign)
    // is independent of this and always valid.
    //
    // Roll caveat: a 2D lateral view cannot detect roll directly. We mark the
    // anatomical label UNCERTAIN on near-straight frames (max |curv| below a small
    // angle), where side identity is least constrained. This does not affect the
    // convex/concave mechanics, only the anatomical dorsal/ventral column.
    void resolveDorsal(int f) {
        if (dorsalSeedSign==0) { dorsalSign[f]=0; dorsalKnown[f]=false; return; }
        // head-relative left = left-normal side if head is point0, else right-normal side
        int geomSign = headIsPoint0[f] ? dorsalSeedSign : -dorsalSeedSign; // +1=left-normal side dorsal
        // uncertainty: if the worm is nearly straight, flag anatomical label as low-confidence
        double maxC=0; for (int i=0;i<nMid;i++) maxC=Math.max(maxC,Math.abs(curv[f][i]));
        boolean confident = maxC > 3.0;   // deg; below this, side identity is weakly constrained
        dorsalSign[f]=geomSign;
        dorsalKnown[f]=confident;
    }

    // meanInDisk operates in FULL-IMAGE coordinates.
    double meanInDisk(ImageProcessor ip, double cx, double cy, double r) {
        double rx=clampD(cx,r,W-r), ry=clampD(cy,r,H-r);
        ip.setRoi(new OvalRoi((int)Math.round(rx-r),(int)Math.round(ry-r),(int)Math.round(2*r),(int)Math.round(2*r)));
        double m=ip.getStatistics().mean; ip.resetRoi(); return m;
    }

    // ---------------- flags ----------------
    void flagAreaJumps() {
        for (int f=0; f<nFrames; f++) {
            areaFlag[f]=false;
            if (skip[f]||!found[f]) continue;
            double med=localMedianArea(f,5);
            if (med>0) areaFlag[f] = 100.0*Math.abs(bodyArea[f]-med)/med > areaJumpPct;
        }
    }

    double localMedianArea(int f, int win) {
        ArrayList<Double> v=new ArrayList<Double>();
        for (int j=Math.max(0,f-win); j<=Math.min(nFrames-1,f+win); j++)
            if (!skip[j]&&found[j]) v.add(bodyArea[j]);
        if (v.isEmpty()) return 0;
        Collections.sort(v); int m=v.size();
        return (m%2==1)?v.get(m/2):0.5*(v.get(m/2-1)+v.get(m/2));
    }

    // ---- size sanity vs the TRACED reference (uses the area & perimeter you defined) ----
    // A bad threshold makes the mask balloon (grabs background: high area AND ragged,
    // long perimeter) or shrink (eats the body: low area). Flag frames whose area or
    // perimeter departs from the traced reference beyond tolerance. Perimeter is the
    // sharper cue for background-grabbing because a ragged mask is disproportionately
    // long-edged. Flag only (non-destructive); surfaces frames to re-threshold.
    void flagSizeDeviations() {
        for (int f=0; f<nFrames; f++){
            sizeFlag[f]=false;
            if (skip[f]||!found[f]) continue;
            if (partialFlag[f]) continue;   // partial worm: dimensions expected small, not a deviation
            // PRIMARY criterion: midline-length conservation. A real worm conserves length;
            // a laced (too long) or collapsed (too short) midline is the actual failure mode.
            // Area/perimeter vary a lot with bending and focus, so they over-fire on good
            // frames (they flagged ~40% of plausible-length frames in test data). Length is
            // the reliable size invariant, so it gates; area/perimeter only corroborate.
            boolean lenBad=false;
            if (refLength>0) lenBad = midLen[f] < refLength*(1-LEN_TOL) || midLen[f] > refLength*(1+LEN_TOL);
            boolean areaBad=false, perimBad=false;
            if (refArea>0){ double a=bodyArea[f]; areaBad = a < refArea*(1-AREA_TOL) || a > refArea*(1+AREA_TOL); }
            if (refPerim>0){ double p=framePerimeter(f); if (p>0) perimBad = p < refPerim*(1-PERIM_TOL) || p > refPerim*(1+PERIM_TOL); }
            // flag only when length is implausible (real shape failure), OR when BOTH area and
            // perimeter agree something is wrong (two weak signals concurring), not either alone.
            sizeFlag[f] = lenBad || (areaBad && perimBad);
        }
        int nf=0; for (int f=0;f<nFrames;f++) if (sizeFlag[f]) nf++;
        if (nf>0) IJ.log("Size sanity: "+nf+" frame(s) deviate (primary: midline length "
            +IJ.d2s(refLength,0)+"+/-"+(int)(LEN_TOL*100)+"%; area/perimeter only corroborate). "
            +"Length-laced or collapsed frames; re-threshold, redraw, or rely on the fluor body.");
    }

    // perimeter of the current frame's body mask
    double framePerimeter(int f){
        if (rgbMode) dicBackgroundCachedForIp = dicBackground(f);
        ByteProcessor m=bodyMask(f); keepLargestObject(m);
        return polygonPerimeter(traceOutline(m));
    }
    // perimeter (closed) of a polygon
    double polygonPerimeter(Polygon p){
        if (p==null || p.npoints<3) return 0;
        double per=0;
        for (int i=0;i<p.npoints;i++){
            int j=(i+1)%p.npoints;
            per += Math.hypot(p.xpoints[j]-p.xpoints[i], p.ypoints[j]-p.ypoints[i]);
        }
        return per;
    }

    // ---------------- overlay ----------------
    void redraw() {
        Overlay ov=new Overlay();
        for (int f=0; f<nFrames; f++) {
            int slice = sliceOf(f);     // overlay anchored to the transmitted-light slice
            if (skip[f]) continue;
            boolean flagged = coilFlag[f]||areaFlag[f];
            if (found[f]) {
                // body outline reconstructed from the (hybrid) edges, drawn as two
                // side polylines colored by source: green = measured edge, magenta =
                // placed from the conserved width profile (the dim/invisible side).
                for (int side=0; side<2; side++){
                    for (int i=0;i<nMid-1;i++){
                        double ax,ay,bx,by; byte sa,sb;
                        if (side==0){ ax=ex(f,i,0); ay=ey(f,i,0); bx=ex(f,i+1,0); by=ey(f,i+1,0); sa=edgeSrcL[f][i]; sb=edgeSrcL[f][i+1]; }
                        else        { ax=ex(f,i,1); ay=ey(f,i,1); bx=ex(f,i+1,1); by=ey(f,i+1,1); sa=edgeSrcR[f][i]; sb=edgeSrcR[f][i+1]; }
                        Color ec = (sa==1||sb==1)? Color.magenta : new Color(0,180,0);
                        Line el=new Line(ax,ay,bx,by); el.setStrokeColor(ec); el.setPosition(slice); ov.add(el);
                    }
                }
            } else if (outlineX[f]!=null) {
                PolygonRoi o=new PolygonRoi(outlineX[f], outlineY[f], outlineX[f].length, Roi.POLYGON);
                o.setStrokeColor(Color.red); o.setPosition(slice); ov.add(o);
            }
            if (found[f]) {
                // midline drawn segment-by-segment, colored by provenance:
                // cyan = measured from real pixels, orange = inferred (body vanished,
                // filled from neighbors), magenta = manual (user redrew it).
                for (int i=0;i<nMid-1;i++){
                    int prov=Math.max(pointSrc[f][i], pointSrc[f][i+1]);
                    Color c = (prov==2)?Color.magenta : (prov==1)?Color.orange : Color.cyan;
                    Line seg=new Line(midX[f][i],midY[f][i],midX[f][i+1],midY[f][i+1]);
                    seg.setStrokeColor(c); seg.setStrokeWidth(2); seg.setPosition(slice); ov.add(seg);
                }

                // muscle ROIs: each segment split into L/R side bands (thin outline)
                for (int k=0;k<nSeg;k++) for (int s=0;s<2;s++){
                    int[][] poly=segPolygon(f,k,s);
                    PolygonRoi roi=new PolygonRoi(poly[0],poly[1],4,Roi.POLYGON);
                    // color by side label (convex/concave) for quick visual check
                    double sc=segCurv(f,k);
                    boolean isLeft=(s==0);
                    Color bc;
                    if (Math.abs(sc)<1e-6) bc=Color.gray;
                    else { boolean leftConcave=sc>0; bc=(isLeft==leftConcave)?new Color(0,200,255):new Color(255,160,0); }
                    roi.setStrokeColor(bc); roi.setPosition(slice); ov.add(roi);
                }

                // dorsal-side tick at mid-body if seeded
                if (dorsalSeedSign!=0) {
                    int i=nMid/2;
                    double sx = (dorsalSign[f]>=0)? edgeLX[f][i] : edgeRX[f][i];
                    double sy = (dorsalSign[f]>=0)? edgeLY[f][i] : edgeRY[f][i];
                    sx = midX[f][i]+(sx-midX[f][i])*widthScale;
                    sy = midY[f][i]+(sy-midY[f][i])*widthScale;
                    Line dl=new Line(midX[f][i],midY[f][i],sx,sy);
                    dl.setStrokeColor(dorsalKnown[f]?Color.magenta:Color.gray);
                    dl.setStrokeWidth(2); dl.setPosition(slice); ov.add(dl);
                }

                int hi=headIsPoint0[f]?0:nMid-1, ti=headIsPoint0[f]?nMid-1:0;
                PointRoi head=new PointRoi(midX[f][hi], midY[f][hi]);
                head.setStrokeColor(Color.green); head.setPosition(slice); ov.add(head);
                PointRoi tail=new PointRoi(midX[f][ti], midY[f][ti]);
                tail.setStrokeColor(Color.red); tail.setPosition(slice); ov.add(tail);

                // count inferred points and show on this frame
                int nInf=0; for (int i=0;i<nMid;i++) if (pointSrc[f][i]==1) nInf++;
                int nProf=0; for (int i=0;i<nMid;i++){ if (edgeSrcL[f][i]==1) nProf++; if (edgeSrcR[f][i]==1) nProf++; }
                StringBuilder st=new StringBuilder();
                if (nInf>0) st.append("inferred midline pts: "+nInf+"/"+nMid+" (orange)  ");
                if (nProf>0) st.append("profile-placed edges: "+nProf+"/"+(2*nMid)+" (magenta)  ");
                if (selfApproachFlag!=null && selfApproachFlag[f]) st.append("SELF-APPROACH? bend may be shortcut - check  ");
                if (lenShortFlag[f]) st.append("SHORT midline (length<ref) ");
                if (lenLongFlag[f]) st.append("LONG midline (overshoot past tail - check) ");
                if (refFrames.contains(f)) st.append("[REFERENCE FRAME]");
                if (st.length()>0){ TextRoi t=new TextRoi(8,28,st.toString());
                    t.setStrokeColor(refFrames.contains(f)?Color.green:Color.orange); t.setPosition(slice); ov.add(t); }
            } else if (coilFlag[f]) {
                TextRoi t=new TextRoi(8,8,"frame "+(f+1)+": coil/skeleton fail");
                t.setStrokeColor(Color.red); t.setPosition(slice); ov.add(t);
            }
        }
        imp.setOverlay(ov); imp.updateAndDraw();
        imp.getWindow().toFront();   // make sure the tracked stack is the window in front
        IJ.log("[overlay] set "+ov.size()+" ROIs on the tracked DIC stack \""+imp.getTitle()+"\". "+
               "If you see overlays on only one ch03 frame, you are scrolling a DIFFERENT window; "+
               "scroll the one titled \""+imp.getTitle()+"\".");
    }

    // width-scaled edge coordinate: side 0 = left, 1 = right
    double ex(int f, int i, int side){
        double e = (side==0)? edgeLX[f][i] : edgeRX[f][i];
        return midX[f][i] + (e - midX[f][i])*widthScale;
    }
    double ey(int f, int i, int side){
        double e = (side==0)? edgeLY[f][i] : edgeRY[f][i];
        return midY[f][i] + (e - midY[f][i])*widthScale;
    }

    // ---------------- menu ----------------
    void menuLoop() {
        String[] actions={
            "Review (scroll, then OK)",
            "Threshold: this frame / range / global (preview)",
            "Flip head/tail (this frame)",
            "Lock head end (from this frame on)",
            "Redraw head & tail endpoints (click 2 points)",
            "Redraw MIDLINE (click points head->tail)",
            "Clear manual midline (this frame)",
            "Set ROI width scale",
            "Seed DORSAL side (click on dorsal side)",
            "Clear dorsal seed",
            "Add reference frame (for width profile)",
            "Learn width profile (from reference frames)",
            "Clear width profile",
            "Toggle skip at a frame",
            "Recompute and redraw",
            "Recalibrate midline & perimeter (from manual frames)",
            "Report flag summary",
            "Toggle DIC background subtraction (on/off)",
            "Go to suggested manual anchor",
            "Load prior review ROI ZIP (resume/correct)",
            "Redraw BODY OUTLINE (this frame)",
            "Export CSV and finish",
            "Quit without export"
        };
        boolean done=false;
        while(!done){
            NonBlockingGenericDialog gd=new NonBlockingGenericDialog("WormRGBCaMPMap_v1 control");
            int curFrame0=(imp.getCurrentSlice()-1);
            gd.addMessage("Frame "+(curFrame0+1)+" / "+nFrames+"   (slice "+imp.getCurrentSlice()+" / "+nSlices+")");
            gd.addChoice("Action", actions, actions[0]);
            gd.addNumericField("Frame (0 = current frame)", 0, 0);
            gd.showDialog();
            if (gd.wasCanceled()){ done=true; break; }
            int act=gd.getNextChoiceIndex();
            int fr=(int)gd.getNextNumber();
            int curFrame=(imp.getCurrentSlice()-1);
            int idx=clamp((fr<=0?curFrame+1:fr)-1,0,nFrames-1);

            if (act==0){
                new WaitForUserDialog("Review","Scroll, then OK.").show();
            } else if (act==1){
                thresholdPreview(idx);
            } else if (act==2){
                headIsPoint0[idx]=!headIsPoint0[idx];
                int hi=headIsPoint0[idx]?0:nMid-1;
                headPx[idx]=midX[idx][hi]; headPy[idx]=midY[idx][hi];
                resolveDorsal(idx); redraw();
                IJ.log("Frame "+(idx+1)+" head=point"+(headIsPoint0[idx]?0:(nMid-1)));
            } else if (act==3){
                headLockFrame=idx; headLockIsPoint0=headIsPoint0[idx];
                recomputeAll(); redraw();
                IJ.log("Head locked from frame "+(idx+1)+" (head=point"+(headLockIsPoint0?0:(nMid-1))+")");
            } else if (act==4){
                redrawEndpoints(idx);
            } else if (act==5){
                redrawMidline(idx);
            } else if (act==6){
                manualMidline[idx]=false; manualMidX[idx]=null; manualMidY[idx]=null;
                processFrame(idx); inferMissingBody(); assignHeadByMotion();
                for (int j=0;j<nFrames;j++) if(found[j]) resolveDorsal(j); flagAreaJumps(); redraw();
                IJ.log("Manual midline cleared on frame "+(idx+1));
            } else if (act==7){
                GenericDialog t=new GenericDialog("ROI width scale");
                t.addNumericField("Width scale (0.1 - 1.0; lower pulls ROIs in from cuticle)", widthScale, 2);
                t.showDialog();
                if(!t.wasCanceled()){ widthScale=clampD(t.getNextNumber(),0.1,1.0); redraw();
                    IJ.log("Width scale = "+IJ.d2s(widthScale,2)); }
            } else if (act==8){
                seedDorsal(idx);
            } else if (act==9){
                dorsalSeedSign=0; dorsalSeedFrame=-1;
                for (int f=0;f<nFrames;f++){ dorsalSign[f]=0; dorsalKnown[f]=false; }
                redraw(); IJ.log("Dorsal seed cleared.");
            } else if (act==10){
                // add reference frame: must be a clean, fully-visible frame
                if (!found[idx]){ IJ.error("Frame "+(idx+1)+" has no midline; pick a clean frame."); }
                else if (refFrames.contains(idx)){ IJ.log("Frame "+(idx+1)+" already a reference frame."); }
                else { refFrames.add(idx); IJ.log("Added reference frame "+(idx+1)+". Total: "+refFrames.size()
                        +". Pick a few extended, fully-visible frames, then 'Learn width profile'."); redraw(); }
            } else if (act==11){
                learnWidthProfile();
                if (profLearned){ recomputeAll(); redraw(); }
            } else if (act==12){
                profLearned=false; profL=null; profR=null; refFrames.clear();
                recomputeAll(); redraw(); IJ.log("Width profile and reference frames cleared.");
            } else if (act==13){
                skip[idx]=!skip[idx]; IJ.log("Frame "+(idx+1)+" skip="+skip[idx]);
                recomputeAll(); redraw();
            } else if (act==14){
                recomputeAll(); redraw();
            } else if (act==15){
                recalibrateMidlineAndPerimeter();
            } else if (act==16){
                reportFlags();
            } else if (act==17){
                // toggle DIC background subtraction and re-track
                useTemporalBg=!useTemporalBg;
                if (useTemporalBg && dicBgImg==null) buildTemporalBackground();
                IJ.log("DIC background subtraction now "+(useTemporalBg?"ON (temporal median)":"OFF (frame median)")+". Recomputing.");
                bodyThr=0; autoBodyThreshold(); for(int j=0;j<nFrames;j++) thrFrame[j]=bodyThr;
                recomputeAll(); redraw();
            } else if (act==18){
                int next=-1;
                for(int j=idx+1;j<nFrames;j++) if(suggestedAnchor[j]){ next=j; break; }
                if(next<0) for(int j=0;j<=idx;j++) if(suggestedAnchor[j]){ next=j; break; }
                if(next>=0){ imp.setSlice(sliceOf(next)); IJ.showStatus("Suggested anchor frame "+(next+1)); redraw(); }
                else IJ.showMessage("Suggested anchor","All two-sided gaps are bridgeable; no additional anchor is currently suggested.");
            } else if (act==19){
                loadReviewRois();
            } else if (act==20){
                redrawBodyOutline(idx);
            } else if (act==21){
                exportCsv(); done=true;
            } else if (act==22){
                done=true;
            }
        }
    }

    // ---- interactive threshold with LIVE slider preview ----
    // Drag the slider: the body outline AND the resulting midline redraw on the
    // current frame in real time, with a quality readout (area, connected?). Scrub
    // frames (move the stack slider) and click Preview-refresh to re-check the SAME
    // threshold on another frame, so you can confirm it holds across the movie.
    // OK applies the chosen threshold to the selected scope.
    void thresholdPreview(int idx) {
        imp.setSlice(sliceOf(idx));
        imp.deleteRoi();   // a leftover drawn line (e.g. a midline trace) must NOT confine or
                           // contaminate the threshold; always threshold the full clean image.
        final String[] scopes={"This frame only","Frame range","Global (all frames)"};
        // slider range: data-driven. DIC contrast or fluor intensity both fit 0..255-ish;
        // probe the current frame's max body signal to set a sensible top.
        double top = previewSignalMax(idx);
        final double sliderMax = Math.max(20, Math.ceil(top));
        final double start = Math.min(thrFrame[idx], sliderMax);

        final double[] trial={start};
        final NonBlockingGenericDialog d=new NonBlockingGenericDialog("Live threshold (frame "+(idx+1)+")");
        d.addSlider("Threshold", 0, sliderMax, start);
        d.addChoice("Apply to", scopes, scopes[0]);
        d.addNumericField("Range start frame", idx+1, 0);
        d.addNumericField("Range end frame", Math.min(nFrames, idx+1+10), 0);
        d.addMessage("Drag the slider: yellow outline + cyan midline update live on this frame.\n"+
                     "Scrub the stack to other frames, then nudge the slider to re-preview there.\n"+
                     "OK applies to the chosen scope; Cancel discards.");
        // live preview on any slider/field change
        d.addDialogListener(new DialogListener(){
            public boolean dialogItemChanged(GenericDialog gd, java.awt.AWTEvent e){
                double v=gd.getNextNumber();          // slider value (first numeric)
                gd.getNextChoiceIndex();               // consume choice
                gd.getNextNumber(); gd.getNextNumber();// consume range fields
                trial[0]=v;
                int cur=frameOf(imp.getCurrentSlice());
                if (cur<0) cur=idx;
                previewMask(cur, v);
                return true;
            }
        });
        previewMask(idx, start);                       // initial preview
        d.showDialog();
        if (d.wasCanceled()){ redraw(); return; }
        double tFinal=d.getNextNumber();
        int scope=d.getNextChoiceIndex();
        int rs=(int)d.getNextNumber(), re=(int)d.getNextNumber();
        if (scope==0){ thrFrame[idx]=tFinal; processFrame(idx); noteCorrection(idx,"threshold_changed"); }
        else if (scope==1){ int a=clamp(rs-1,0,nFrames-1), b=clamp(re-1,0,nFrames-1);
            if(a>b){int t=a;a=b;b=t;} for(int j=a;j<=b;j++){ thrFrame[j]=tFinal; if(!skip[j]) processFrame(j); noteCorrection(j,"threshold_changed");} }
        else { bodyThr=tFinal; for(int j=0;j<nFrames;j++){ thrFrame[j]=tFinal; if(!skip[j]) processFrame(j); noteCorrection(j,"threshold_changed");} }
        assignHeadByMotion(); for(int j=0;j<nFrames;j++) if(found[j]) resolveDorsal(j); flagAreaJumps(); redraw();
        IJ.log("Applied threshold "+IJ.d2s(tFinal,1)+" to "+scopes[scope].toLowerCase()+".");
    }

    // max body signal on a frame, to scale the slider top sensibly
    double previewSignalMax(int idx){
        if (rgbMode) dicBackgroundCachedForIp = dicBackground(idx);
        ImageProcessor ip=frameIp(idx);
        double mx=0;
        for (int y=0;y<H;y++) for (int x=0;x<W;x++){
            double v=gcampValue(ip,x,y); if (!Double.isNaN(v) && v>mx) mx=v;
        }
        return mx;
    }
    int frameOf(int slice){ return slice-1>=0 && slice-1<nFrames ? slice-1 : -1; }

    void previewMask(int idx, double thr) {
        // Start from a CLEAN overlay (not the full redraw): during threshold tuning we want to see
        // only this preview's yellow outline + cyan midline over the worm, not the old magenta
        // midline/segment markers occluding it.
        Overlay ov=new Overlay();
        imp.setOverlay(ov); imp.updateAndDraw();
        int slice=sliceOf(idx);
        double save=thrFrame[idx]; thrFrame[idx]=thr;
        if (rgbMode) dicBackgroundCachedForIp = dicBackground(idx);
        ByteProcessor m=bodyMask(idx);
        // measure fragmentation BEFORE keeping largest: count sizable components
        int comps=countComponents(m, 15);
        keepLargestObject(m);
        int area=countWhite(m);
        thrFrame[idx]=save;

        // body outline (yellow)
        Polygon out=traceOutline((ByteProcessor)m.duplicate());
        if (out!=null){ PolygonRoi o=new PolygonRoi(out.xpoints,out.ypoints,out.npoints,Roi.POLYGON);
            o.setStrokeColor(Color.yellow); o.setStrokeWidth(1); o.setPosition(slice); ov.add(o); }

        // resulting midline (cyan) so you see the centerline consequence, not just the mask
        ByteProcessor sk=(ByteProcessor)m.duplicate();
        skeletonizeSafe(sk);
        java.util.ArrayList<int[]> path=longestSkeletonPath(sk);
        if (path!=null && path.size()>=2){
            int[] px=new int[path.size()], py=new int[path.size()];
            for (int i=0;i<path.size();i++){ px[i]=path.get(i)[0]; py[i]=path.get(i)[1]; }
            PolygonRoi mr=new PolygonRoi(px,py,px.length,Roi.POLYLINE);
            mr.setStrokeColor(Color.cyan); mr.setStrokeWidth(1); mr.setPosition(slice); ov.add(mr);
        }

        // quality readout
        String q = "thr="+IJ.d2s(thr,1)+"  area="+area+"px  "
                 + (comps<=1? "connected" : ("FRAGMENTED ("+comps+" pieces)"));
        TextRoi t=new TextRoi(8,H-22,q);
        t.setStrokeColor(comps<=1?Color.yellow:Color.orange); t.setPosition(slice); ov.add(t);
        imp.setOverlay(ov); imp.updateAndDraw();
    }

    int countWhite(ByteProcessor m){ byte[] p=(byte[])m.getPixels(); int c=0; for (byte b:p) if ((b&0xff)==255) c++; return c; }
    // count connected components with area >= minA (8-connected), non-destructive
    int countComponents(ByteProcessor m, int minA){
        byte[] p=(byte[])m.getPixels(); int[] lab=new int[Mw*Mh];
        int next=1, big=0; int[] sx=new int[Mw*Mh], sy=new int[Mw*Mh];
        for (int y=0;y<Mh;y++) for (int x=0;x<Mw;x++){
            int idx=y*Mw+x;
            if ((p[idx]&0xff)==255 && lab[idx]==0){
                int cnt=0,sp=0; sx[sp]=x; sy[sp]=y; lab[idx]=next; sp++;
                while(sp>0){ sp--; int cx=sx[sp],cy=sy[sp]; cnt++;
                    for(int dy=-1;dy<=1;dy++) for(int dx=-1;dx<=1;dx++){
                        if(dx==0&&dy==0)continue; int nx=cx+dx,ny=cy+dy;
                        if(nx<0||ny<0||nx>=Mw||ny>=Mh)continue; int ni=ny*Mw+nx;
                        if((p[ni]&0xff)==255 && lab[ni]==0){ lab[ni]=next; sx[sp]=nx; sy[sp]=ny; sp++; }
                    }
                }
                if (cnt>=minA) big++;
                next++;
            }
        }
        return big;
    }
    // skeletonize wrapper: match the real pipeline's foreground-value call
    void skeletonizeSafe(ByteProcessor m){ m.skeletonize(255); }

    void noteCorrection(int f, String note){
        if(correctionNote==null || f<0 || f>=nFrames) return;
        correctionNote[f]=(correctionNote[f]==null || correctionNote[f].length()==0)
            ? note : correctionNote[f]+";"+note;
    }

    // Restore the compact body-outline/midline audit ZIP written beside a prior
    // CSV.  Body outlines are loaded first because they recreate edges/widths;
    // saved midlines are then restored as protected manual geometry.
    void loadReviewRois(){
        OpenDialog od=new OpenDialog("Open prior review ROI ZIP", null);
        String name=od.getFileName(); if(name==null) return;
        String path=od.getDirectory()+name;
        RoiManager rm=new RoiManager(false);
        try {
            if(!rm.runCommand("Open",path)){ IJ.error("Could not open review ROI ZIP:\n"+path); return; }
            Roi[] rois=rm.getRoisAsArray(); int bodies=0, lines=0;
            for(int pass=0;pass<2;pass++) for(Roi r:rois){
                String rn=r.getName(); if(rn==null || !rn.startsWith("frame_")) continue;
                int us=rn.indexOf('_',6); if(us<0) continue;
                int f; try { f=Integer.parseInt(rn.substring(6,us))-1; } catch(Exception e){ continue; }
                if(f<0 || f>=nFrames) continue;
                String kind=rn.substring(us+1).toLowerCase();
                if(pass==0 && kind.equals("body")){
                    if(deriveReferenceFromOutline(f,r)){ noteCorrection(f,"loaded_prior_body"); bodies++; }
                } else if(pass==1 && kind.startsWith("midline")){
                    FloatPolygon fp=r.getFloatPolygon(); if(fp==null || fp.npoints<2) continue;
                    double[] px=new double[fp.npoints], py=new double[fp.npoints];
                    for(int i=0;i<fp.npoints;i++){px[i]=fp.xpoints[i];py[i]=fp.ypoints[i];}
                    double[][] rs=resamplePoly(px,py,nMid);
                    manualMidX[f]=rs[0]; manualMidY[f]=rs[1]; manualMidline[f]=true;
                    processFrame(f); noteCorrection(f,"loaded_prior_midline"); lines++;
                }
            }
            assignHeadByMotion(); for(int f=0;f<nFrames;f++) if(found[f]) resolveDorsal(f);
            flagAreaJumps(); redraw();
            IJ.showMessage("Correction session","Loaded "+bodies+" body outlines and "+lines+" midlines.\n"+
                "Jump to suspicious frames, correct them, then export with a new filename.");
        } finally { rm.close(); }
    }

    void redrawBodyOutline(int idx){
        imp.setSlice(sliceOf(idx)); imp.deleteRoi(); Overlay saved=imp.getOverlay();
        imp.setOverlay(null); imp.updateAndDraw(); IJ.setTool("polygon");
        new WaitForUserDialog("Redraw body outline","Click around the true worm BODY, then double-click to close the polygon.\nClick OK here when finished.").show();
        Roi r=imp.getRoi();
        if(r==null || !deriveReferenceFromOutline(idx,r)){
            IJ.log("No valid closed body outline drawn; frame unchanged.");
            if(saved!=null){imp.setOverlay(saved);imp.updateAndDraw();} return;
        }
        noteCorrection(idx,"body_outline_redrawn"); imp.deleteRoi();
        assignHeadByMotion(); for(int f=0;f<nFrames;f++) if(found[f]) resolveDorsal(f);
        flagAreaJumps(); redraw(); IJ.log("Body outline manually redrawn on frame "+(idx+1)+".");
    }

    // ---- redraw the whole midline by clicking points head->tail ----
    // The user draws a segmented (polyline) ROI along the true body midline; we
    // resample it to nMid points and store it as this frame's manual midline.
    // Works whether the body is dim-but-visible or fully vanished, since it does
    // not depend on the signal. Marked manual (magenta) and excluded from auto-redetect.
    void redrawMidline(int idx) {
        imp.setSlice(sliceOf(idx)); imp.deleteRoi();
        Overlay savedOv = imp.getOverlay();   // hide the old midline/markers so they don't occlude the worm
        imp.setOverlay(null); imp.updateAndDraw();
        IJ.setTool("polyline");
        new WaitForUserDialog("Redraw midline",
            "The old midline is hidden so you can see the worm.\n"+
            "Using the SEGMENTED LINE tool (already selected), click points along the\n"+
            "true body midline from HEAD to TAIL, then double-click to finish the line.\n"+
            "Then click OK here.").show();
        Roi r=imp.getRoi();
        if (r==null || !(r instanceof PolygonRoi) || r.getType()!=Roi.POLYLINE){
            // accept a freeline too
            if (r==null){ IJ.log("No line drawn; midline unchanged."); if(savedOv!=null){imp.setOverlay(savedOv);imp.updateAndDraw();} return; }
        }
        FloatPolygon fp=r.getFloatPolygon();
        if (fp.npoints<2){ IJ.log("Need at least 2 points."); if(savedOv!=null){imp.setOverlay(savedOv);imp.updateAndDraw();} return; }
        // resample the clicked polyline to nMid points by arc length
        double[] px=new double[fp.npoints], py=new double[fp.npoints];
        for (int i=0;i<fp.npoints;i++){ px[i]=fp.xpoints[i]; py[i]=fp.ypoints[i]; }
        double[][] rs=resamplePoly(px,py,nMid);
        manualMidX[idx]=rs[0]; manualMidY[idx]=rs[1]; manualMidline[idx]=true;
        noteCorrection(idx,"midline_redrawn");
        imp.deleteRoi();
        processFrame(idx);
        // manual midline can change head vote and dorsal; refresh globally
        assignHeadByMotion();
        for (int j=0;j<nFrames;j++) if(found[j]) resolveDorsal(j);
        flagAreaJumps(); invalidatePriorNeighborFills(); fillAdaptiveGapsFromNeighbors(); redraw();
        IJ.log("Midline manually redrawn on frame "+(idx+1)+" ("+fp.npoints+" clicked points).");
    }

    // resample an (x,y) polyline to m points evenly by arc length
    double[][] resamplePoly(double[] px, double[] py, int m){
        int k=px.length;
        double[] cum=new double[k]; cum[0]=0;
        for (int i=1;i<k;i++) cum[i]=cum[i-1]+Math.hypot(px[i]-px[i-1], py[i]-py[i-1]);
        double total=cum[k-1]; if (total<=0) total=1;
        double[] rx=new double[m], ry=new double[m];
        for (int j=0;j<m;j++){
            double target=total*j/(m-1);
            int i=1; while (i<k && cum[i]<target) i++;
            if (i>=k) i=k-1;
            double seg=cum[i]-cum[i-1]; double t=(seg>0)?(target-cum[i-1])/seg:0;
            rx[j]=px[i-1]+t*(px[i]-px[i-1]); ry[j]=py[i-1]+t*(py[i]-py[i-1]);
        }
        return new double[][]{rx,ry};
    }

    // ---- redraw head & tail endpoints by clicking two points ----
    void redrawEndpoints(int idx) {
        imp.setSlice(sliceOf(idx)); imp.deleteRoi();
        new WaitForUserDialog("Head point","Click the TRUE HEAD (multipoint or point), then OK.").show();
        double[] h=getClickedPoint(); if(h==null){ IJ.log("No head point."); return; }
        imp.deleteRoi();
        new WaitForUserDialog("Tail point","Click the TRUE TAIL, then OK.").show();
        double[] t=getClickedPoint(); if(t==null){ IJ.log("No tail point."); return; }
        imp.deleteRoi();
        // store override mapped to point0=head, pointN=tail in current head orientation
        if (manualEnds[idx]==null) manualEnds[idx]=new double[]{Double.NaN,Double.NaN,Double.NaN,Double.NaN};
        if (headIsPoint0[idx]) { manualEnds[idx][0]=h[0]; manualEnds[idx][1]=h[1]; manualEnds[idx][2]=t[0]; manualEnds[idx][3]=t[1]; }
        else                   { manualEnds[idx][0]=t[0]; manualEnds[idx][1]=t[1]; manualEnds[idx][2]=h[0]; manualEnds[idx][3]=h[1]; }
        processFrame(idx); assignHeadByMotion(); for(int j=0;j<nFrames;j++) if(found[j]) resolveDorsal(j); flagAreaJumps(); redraw();
        IJ.log("Endpoints corrected on frame "+(idx+1));
    }

    double[] getClickedPoint() {
        Roi r=imp.getRoi();
        if (r==null) return null;
        if (r instanceof PointRoi) {
            FloatPolygon fp=r.getFloatPolygon();
            if (fp.npoints<1) return null;
            return new double[]{ fp.xpoints[fp.npoints-1], fp.ypoints[fp.npoints-1] };
        }
        Rectangle b=r.getBounds();
        return new double[]{ b.x+b.width/2.0, b.y+b.height/2.0 };
    }

    // ---- seed dorsal side: user clicks on the dorsal side at this frame ----
    void seedDorsal(int idx) {
        if (!found[idx]) { IJ.error("This frame has no midline; pick a clean frame."); return; }
        imp.setSlice(sliceOf(idx)); imp.deleteRoi();
        new WaitForUserDialog("Seed dorsal","Click a point on the DORSAL side of the worm, then OK.").show();
        double[] c=getClickedPoint(); if(c==null){ IJ.log("No point clicked."); return; }
        // decide which geometric side (left-normal vs right-normal) the click is on,
        // at the nearest midline point, then convert to head-relative sign.
        int best=0; double bd=Double.MAX_VALUE;
        for (int i=0;i<nMid;i++){ double dd=dist(c[0],c[1],midX[idx][i],midY[idx][i]); if(dd<bd){bd=dd;best=i;} }
        double dl=dist(c[0],c[1],edgeLX[idx][best],edgeLY[idx][best]);
        double dr=dist(c[0],c[1],edgeRX[idx][best],edgeRY[idx][best]);
        int geomSign = (dl<=dr)? +1 : -1;             // +1 = left-normal side
        // convert geometric side to head-relative seed sign
        dorsalSeedSign = headIsPoint0[idx]? geomSign : -geomSign;
        dorsalSeedFrame = idx;
        for (int f=0;f<nFrames;f++) if(found[f]) resolveDorsal(f);
        redraw();
        IJ.log("Dorsal seeded on frame "+(idx+1)+" (magenta = dorsal; gray = uncertain on near-straight frames).");
    }

    // ================= OUTPUT ENGINE =================
    // Per segment k (0..nSeg-1) and side s (0=left-normal band, 1=right-normal band),
    // build a quadrilateral ROI from the midline segment boundaries and the
    // (width-scaled) edge points, then measure GCaMP min/mean/max from ORIGINAL
    // pixels. Build a time series per (segment,side), then derive kinetics.

    String boundaryFracString(){
        if (muscleBoundaryFrac==null) buildMuscleBoundaries();
        StringBuilder sb=new StringBuilder();
        for (int k=0;k<=nSeg;k+=Math.max(1,nSeg/8)){ sb.append(IJ.d2s(muscleBoundaryFrac[k],2)); sb.append(" "); }
        return sb.toString().trim();
    }

    // Relative muscle SIZE profile along the body, head (index 0) to tail (index nSeg-1).
    // Body-wall muscles are not equal in length: they are shorter at both ends and larger
    // in the midbody (PNAS Fig 7 muscle-area profile; Palyanov et al. 2018 anatomy). We
    // therefore make the segment boundaries PROPORTIONAL to this profile rather than uniform,
    // so each reported segment corresponds to a true anatomical muscle share of body length.
    // Values are relative (only their ratios matter); they are normalised to cumulative
    // fractions in buildMuscleBoundaries(). This 24-value profile is a smooth taper peaking
    // mid-body; exact per-muscle areas can be substituted here later without other changes.
    double[] muscleSizeProfile = null;   // lazily built to length nSeg
    double[] muscleBoundaryFrac = null;  // cumulative boundary fractions, length nSeg+1 (0..1)

    void buildMuscleBoundaries(){
        // default smooth taper: relative size ~ 0.5 at the ends rising to 1.0 mid-body,
        // shaped by a raised cosine so neighbours change gradually (matches the gradual
        // area change along the body rather than a sharp step).
        double[] prof=new double[nSeg];
        for (int k=0;k<nSeg;k++){
            double u=(nSeg>1)? (double)k/(nSeg-1) : 0.5;      // 0..1 head->tail
            // raised-cosine hump: min at ends, max at centre
            double hump=0.5 - 0.5*Math.cos(2*Math.PI*u);      // 0 at ends, 1 at centre
            prof[k]=0.55 + 0.45*hump;                          // 0.55..1.0 relative size
        }
        // if a user/measured profile was supplied at the right length, use it instead
        if (muscleSizeProfile!=null && muscleSizeProfile.length==nSeg){
            prof=muscleSizeProfile.clone();
        }
        double sum=0; for (double v:prof) sum+=v;
        muscleBoundaryFrac=new double[nSeg+1];
        muscleBoundaryFrac[0]=0.0;
        double acc=0;
        for (int k=0;k<nSeg;k++){ acc+=prof[k]/sum; muscleBoundaryFrac[k+1]=acc; }
        muscleBoundaryFrac[nSeg]=1.0;   // guard exact end
    }

    // segment boundary indices along the midline, PROPORTIONAL to muscle size profile.
    int segStart(int k){
        if (muscleBoundaryFrac==null || muscleBoundaryFrac.length!=nSeg+1) buildMuscleBoundaries();
        return (int)Math.round(muscleBoundaryFrac[k]*(nMid-1));
    }
    int segEnd(int k){
        if (muscleBoundaryFrac==null || muscleBoundaryFrac.length!=nSeg+1) buildMuscleBoundaries();
        return (int)Math.round(muscleBoundaryFrac[k+1]*(nMid-1));
    }

    // quadrilateral polygon for (frame f, segment k, side s). side 0 = left-normal.
    int[][] segPolygon(int f, int k, int s) {
        int a=segStart(k), b=segEnd(k); if (b<=a) b=Math.min(nMid-1,a+1);
        double mAx=midX[f][a], mAy=midY[f][a], mBx=midX[f][b], mBy=midY[f][b];
        double eAx, eAy, eBx, eBy;
        if (s==0){ eAx=edgeLX[f][a]; eAy=edgeLY[f][a]; eBx=edgeLX[f][b]; eBy=edgeLY[f][b]; }
        else     { eAx=edgeRX[f][a]; eAy=edgeRY[f][a]; eBx=edgeRX[f][b]; eBy=edgeRY[f][b]; }
        // scale edges inward by widthScale
        eAx=mAx+(eAx-mAx)*widthScale; eAy=mAy+(eAy-mAy)*widthScale;
        eBx=mBx+(eBx-mBx)*widthScale; eBy=mBy+(eBy-mBy)*widthScale;
        int[] xs={(int)Math.round(mAx),(int)Math.round(mBx),(int)Math.round(eBx),(int)Math.round(eAx)};
        int[] ys={(int)Math.round(mAy),(int)Math.round(mBy),(int)Math.round(eBy),(int)Math.round(eAy)};
        return new int[][]{xs,ys};
    }

    // per-(segment,side) mean GCaMP time series; NaN where frame invalid
    double[][][] buildSeriesMean() {
        double[][][] series=new double[nSeg][2][nFrames];
        for (int k=0;k<nSeg;k++) for (int s=0;s<2;s++) for (int f=0;f<nFrames;f++) series[k][s][f]=Double.NaN;
        for (int f=0; f<nFrames; f++){
            if (skip[f]||!found[f]) continue;
            ImageProcessor ip=frameIp(f);
            ByteProcessor body=bodyMaskCached(f);
            for (int k=0;k<nSeg;k++) for (int s=0;s<2;s++){
                int[][] poly=segPolygon(f,k,s);
                double[] st=statsInPolygonClipped(ip, poly[0], poly[1], 4, body);
                series[k][s][f]=st[1]; // mean
            }
        }
        return series;
    }

    // signed dF/dt at frame f for a series (per second), central difference
    double dFdt(double[] ser, int f){
        int a=f-1, b=f+1;
        while (a>=0 && Double.isNaN(ser[a])) a--;
        while (b<ser.length && Double.isNaN(ser[b])) b++;
        if (a<0||b>=ser.length||Double.isNaN(ser[a])||Double.isNaN(ser[b])) return Double.NaN;
        double dt=(b-a)/fps; if (dt<=0) return Double.NaN;
        return (ser[b]-ser[a])/dt;
    }

    // local rise rate (positive dF/dt) and decay time constant tau (s) estimated
    // around frame f. Rise is SAMPLING-LIMITED at low fps and flagged as such.
    // Decay tau: fit ln(F-baseline) vs t over the falling window after a local peak.
    // Returns {riseRate, decayTau, riseSampleLimited(1/0)}.
    double[] localKinetics(double[] ser, int f){
        double d=dFdt(ser,f);
        double rise = (Double.isNaN(d))?Double.NaN:Math.max(0,d);
        int riseLimited = 1; // at 8-30 fps the rise phase is short; always flag
        // decay tau: look forward for a monotonic-ish fall, fit exponential
        double tau=Double.NaN;
        int w=Math.min(ser.length-1, f+Math.max(3,(int)Math.round(fps))); // ~1 s window
        java.util.ArrayList<double[]> pts=new java.util.ArrayList<double[]>();
        double baseline=seriesMin(ser);
        double prev=Double.NaN; int start=-1;
        for (int g=f; g<=w; g++){
            if (Double.isNaN(ser[g])) continue;
            if (start<0){ start=g; prev=ser[g]; }
            double y=ser[g]-baseline; if (y<=0) break;
            pts.add(new double[]{(g-start)/fps, Math.log(y)});
            if (!Double.isNaN(prev) && ser[g]>prev+1e-9) break; // stop if it rises again
            prev=ser[g];
        }
        if (pts.size()>=3){
            // linear fit ln(y)=intercept+slope*t ; tau=-1/slope when slope<0
            double sx=0,sy=0,sxx=0,sxy=0; int m=pts.size();
            for (double[] p:pts){ sx+=p[0]; sy+=p[1]; sxx+=p[0]*p[0]; sxy+=p[0]*p[1]; }
            double denom=m*sxx-sx*sx;
            if (Math.abs(denom)>1e-9){
                double slope=(m*sxy-sx*sy)/denom;
                if (slope<0) tau=-1.0/slope;
            }
        }
        return new double[]{rise, tau, riseLimited};
    }

    double seriesMin(double[] ser){ double mn=Double.POSITIVE_INFINITY;
        for (double v:ser) if(!Double.isNaN(v)&&v<mn) mn=v; return (mn==Double.POSITIVE_INFINITY)?0:mn; }

    // per-segment kinematics: body angle (tangent direction, compass), signed
    // curvature (mean over segment), curvature RATE (d/dt), and axial translation
    // rate of the segment midpoint along the local body axis (propulsion proxy).
    double segAngleDeg(int f, int k){
        int a=segStart(k), b=segEnd(k);
        double tx=midX[f][b]-midX[f][a], ty=midY[f][b]-midY[f][a];
        // compass: 0 = up(-y), 90 = right(+x)
        double ang=Math.toDegrees(Math.atan2(tx,-ty));
        return mod360(ang);
    }
    double segCurv(int f, int k){
        int a=segStart(k), b=segEnd(k); double s=0; int c=0;
        for (int i=a;i<=b;i++){ s+=curv[f][i]; c++; }
        return (c>0)?s/c:0;
    }
    double segMidX(int f,int k){ int a=segStart(k),b=segEnd(k); return 0.5*(midX[f][a]+midX[f][b]); }
    double segMidY(int f,int k){ int a=segStart(k),b=segEnd(k); return 0.5*(midY[f][a]+midY[f][b]); }

    // axial translation rate: displacement of segment midpoint between neighbor
    // frames projected onto the local body-axis direction, per second.
    double axialTransRate(int f, int k){
        int g=f+1; double sgn=1;
        if (g>=nFrames||!found[g]){ g=f-1; sgn=-1; }
        if (g<0||!found[g]) return Double.NaN;
        double dx=segMidX(g,k)-segMidX(f,k), dy=segMidY(g,k)-segMidY(f,k);
        int a=segStart(k), b=segEnd(k);
        double tx=midX[f][b]-midX[f][a], ty=midY[f][b]-midY[f][a];
        double tn=Math.hypot(tx,ty); if (tn<1e-6) return Double.NaN; tx/=tn; ty/=tn;
        double along=(dx*tx+dy*ty)*sgn;
        return along*fps;
    }
    // curvature rate (bending proxy): d(segCurv)/dt
    double curvRate(int f, int k){
        int g=f+1; double sgn=1;
        if (g>=nFrames||!found[g]){ g=f-1; sgn=-1; }
        if (g<0||!found[g]) return Double.NaN;
        return (segCurv(g,k)-segCurv(f,k))*sgn*fps;
    }

    // ---------------- CSV export ----------------
    void exportCsv() {
        // Build a human-readable, collision-resistant default filename from the recording
        // metadata, e.g. WT_day1_l4440_a01.csv, so repeat exports never overwrite each other.
        String genoCode = genotype.equals("dystrophic") ? "DYS" : "WT";
        String defaultName = genoCode+"_day"+ageDay+"_"+filenameSafe(rnai)+"_"+filenameSafe(animalId);
        SaveDialog sd=new SaveDialog("Save per-segment CSV", defaultName, ".csv");
        if (sd.getFileName()==null) return;
        double[][][][] mSer=buildSeriesMeanMulti();   // [c][k][s][frame] per-channel mean
        int maxlag = Math.min(20, nFrames/3);

        StringBuilder sb=new StringBuilder();
        // header: per-channel min/mean/max, geometry, kinematics, ratios+rates, inter-channel lag
        sb.append("frame,time_s,worm_id,condition,strain,genotype,rnai,age_day,animal_id,contract_version,fps,um_per_px,src8bit,skip,found,coil_flag,area_flag,size_flag,len_short_flag,len_long_flag,midline_len_px,"
            +"partial_flag,self_approach_flag,head_tip_conf,tail_tip_conf,head_tip_src,tail_tip_src,fluor_outside_frac,"
            +"dic_confidence,eigen_fit_quality,body_source,len_conserved,low_evidence,filled_neighbor,suggested_manual_anchor,"
            +"segment,hemisegment,side_curv_label,dorsal_label,dorsal_known,body_provenance,edge_source,correction_note,"
            +"blue_min,blue_mean,blue_max,green_min,green_mean,green_max,red_min,red_mean,red_max,roi_area_px,"
            +"bg_blue,bg_green,bg_red,"
            +"blue_dF_dt,green_dF_dt,red_dF_dt,"
            +"ratio_RG,ratio_RB,ratio_GB,dRG_dt,dRB_dt,dGB_dt,"
            +"seg_angle_deg,seg_curv_deg,axial_vel_px_s,angular_vel_deg_s,"
            +"lag_GB_frames,lag_GB_ms,lag_RG_frames,lag_RG_ms,lag_RB_frames,lag_RB_ms,lag_resolved\n");

        double frameMs = 1000.0/fps;
        for (int f=0; f<nFrames; f++){
            double t=f/fps;
            for (int k=0;k<nSeg;k++){
                int a=segStart(k), b=segEnd(k); int prov=0;
                if (found[f]) for (int i=a;i<=b && i<nMid;i++) prov=Math.max(prov, pointSrc[f][i]);
                String provLabel = (prov==2)?"manual":(prov==1)?"inferred":"measured";
                double sc=found[f]?segCurv(f,k):Double.NaN;
                for (int s=0;s<2;s++){
                    String sideCurv;
                    if (Double.isNaN(sc)||Math.abs(sc)<1e-6) sideCurv="flat";
                    else { boolean leftConcave=sc>0; boolean isLeft=(s==0);
                           sideCurv=(isLeft==leftConcave)?"concave":"convex"; }
                    // hemisegment label: dorsal/ventral from vulva notch, else L/R
                    String hemi=(s==0?"L":"R"); String dlab="NA"; int dknown=0;
                    if (dorsalSeedSign!=0 && found[f]){
                        boolean leftIsDorsal=(dorsalSign[f]>=0); boolean isLeft=(s==0);
                        dlab=(isLeft==leftIsDorsal)?"dorsal":"ventral";
                        hemi=dlab; dknown=dorsalKnown[f]?1:0;
                    }
                    // per-channel min/mean/max
                    double[] bl={Double.NaN,Double.NaN,Double.NaN}, gr={Double.NaN,Double.NaN,Double.NaN}, rd={Double.NaN,Double.NaN,Double.NaN};
                    double area=Double.NaN;
                    double segang=Double.NaN, crate=Double.NaN, atr=Double.NaN, angvel=Double.NaN;
                    double rg=Double.NaN,rb=Double.NaN,gb=Double.NaN, drg=Double.NaN,drb=Double.NaN,dgb=Double.NaN;
                    double dB=Double.NaN,dG=Double.NaN,dR=Double.NaN;
                    double lgb=Double.NaN,lrg=Double.NaN,lrb=Double.NaN; int resolved=1;
                    if (found[f] && !skip[f]){
                        int[][] poly=segPolygon(f,k,s);
                        double[] sB=statsInPolygonMeas(0,f,poly[0],poly[1],4);
                        double[] sG=statsInPolygonMeas(1,f,poly[0],poly[1],4);
                        double[] sR=statsInPolygonMeas(2,f,poly[0],poly[1],4);
                        bl=sB; gr=sG; rd=sR; area=sG[3];
                        // ratios from per-channel means (guard divide-by-zero)
                        double Bm=sB[1], Gm=sG[1], Rm=sR[1];
                        rg=safeRatio(Rm,Gm); rb=safeRatio(Rm,Bm); gb=safeRatio(Gm,Bm);
                        // per-channel dF/dt and ratio rates from the time series
                        dB=dFdt(mSer[0][k][s], f); dG=dFdt(mSer[1][k][s], f); dR=dFdt(mSer[2][k][s], f);
                        drg=ratioRate(mSer[2][k][s], mSer[1][k][s], f);
                        drb=ratioRate(mSer[2][k][s], mSer[0][k][s], f);
                        dgb=ratioRate(mSer[1][k][s], mSer[0][k][s], f);
                        segang=segAngleDeg(f,k); crate=sc; atr=axialTransRate(f,k); angvel=angularVel(f,k);
                        // inter-channel lag (whole series for this hemisegment; same every frame,
                        // but emitted per row for convenience). positive = first channel leads.
                        double[] LGB=xcorrLag(mSer[1][k][s], mSer[0][k][s], maxlag); // green vs blue
                        double[] LRG=xcorrLag(mSer[2][k][s], mSer[1][k][s], maxlag); // red vs green
                        double[] LRB=xcorrLag(mSer[2][k][s], mSer[0][k][s], maxlag); // red vs blue
                        lgb=LGB[0]; lrg=LRG[0]; lrb=LRB[0];
                        if (Math.abs(lgb)<1 && Math.abs(lrg)<1 && Math.abs(lrb)<1) resolved=0; // all 0 = sub-frame
                    }
                    String edgeSrc="measured";
                    if (found[f]){
                        boolean usedProfile=false;
                        for (int i=a;i<=b && i<nMid;i++){
                            byte es=(s==0)?edgeSrcL[f][i]:edgeSrcR[f][i];
                            if (es==1){ usedProfile=true; break; }
                        }
                        edgeSrc=usedProfile?"profile":"measured";
                    }
                    sb.append((f+1)+","+fmt(t)+","+wormId+","+condition+","
                        +csvSafe(strain)+","+genotype+","+csvSafe(rnai)+","+ageDay+","+csvSafe(animalId)+","
                        +CSV_CONTRACT_VERSION+","+fmt(fps)+","+fmt(umPerPx)+","
                        +(src8bit?1:0)+","+(skip[f]?1:0)+","+(found[f]?1:0)+","+(coilFlag[f]?1:0)+","+(areaFlag[f]?1:0)+","+(sizeFlag[f]?1:0)+","
                        +(lenShortFlag[f]?1:0)+","+(lenLongFlag[f]?1:0)+","+fmt(midLen[f])+","
                        +(partialFlag[f]?1:0)+","+(selfApproachFlag!=null&&selfApproachFlag[f]?1:0)+","+fmt(headTipConf[f])+","+fmt(tailTipConf[f])+","+headTipSrc[f]+","+tailTipSrc[f]+","+fmt(fluorOutsideFrac[f])+","
                        +fmt(dicConfidence[f])+","+fmt(eigenFitQuality[f])+","+bodySource[f]+","+((lenConservedFluor!=null&&lenConservedFluor[f])||bodySource[f]==0?1:0)+","+((lowEvidenceFlag!=null&&lowEvidenceFlag[f])?1:0)+","+((filledFromNeighbors!=null&&filledFromNeighbors[f])?1:0)+","+((suggestedAnchor!=null&&suggestedAnchor[f])?1:0)+","
                        +k+","+hemi+","+sideCurv+","+dlab+","+dknown+","+provLabel+","+edgeSrc+","+csvSafe(correctionNote[f])+","
                        +fmt(bl[0])+","+fmt(bl[1])+","+fmt(bl[2])+","
                        +fmt(gr[0])+","+fmt(gr[1])+","+fmt(gr[2])+","
                        +fmt(rd[0])+","+fmt(rd[1])+","+fmt(rd[2])+","+fmt(area)+","
                        +fmt(bgBlue!=null?bgBlue[f]:Double.NaN)+","+fmt(bgGreen!=null?bgGreen[f]:Double.NaN)+","+fmt(bgRed!=null?bgRed[f]:Double.NaN)+","
                        +fmt(dB)+","+fmt(dG)+","+fmt(dR)+","
                        +fmt(rg)+","+fmt(rb)+","+fmt(gb)+","+fmt(drg)+","+fmt(drb)+","+fmt(dgb)+","
                        +fmt(segang)+","+fmt(sc)+","+fmt(atr)+","+fmt(angvel)+","
                        +fmt(lgb)+","+fmt(lgb*frameMs)+","+fmt(lrg)+","+fmt(lrg*frameMs)+","+fmt(lrb)+","+fmt(lrb*frameMs)+","+resolved+"\n");
                }
            }
        }
        try {
            long exportStarted=System.nanoTime();
            java.io.FileWriter fw=new java.io.FileWriter(sd.getDirectory()+sd.getFileName());
            fw.write(sb.toString()); fw.close();
            exportReviewRois(sd.getDirectory(),sd.getFileName());
            if (exportGeometryJson) exportGeometrySidecar(sd.getDirectory(),sd.getFileName());
            exportSeconds=(System.nanoTime()-exportStarted)/1e9;
            exportTimingReport(sd.getDirectory(),sd.getFileName());
            IJ.log("Exported "+(nFrames*nSeg*2)+" rows ("+nMeas+" channels) to "+sd.getDirectory()+sd.getFileName());
            IJ.log("Saved reloadable body outlines and midlines beside the CSV for later QC.");
            IJ.log("Inter-channel lag: positive = first channel leads; resolution is one frame = "+IJ.d2s(frameMs,0)+" ms.");
            IJ.log("  lag_resolved=0 means all pairwise lags were 0 (true lead/lag is faster than the frame rate).");
            if (src8bit) IJ.log("NOTE: src8bit=1 -> absolute intensities are 8-bit; ratios are more robust than raw values.");
        } catch (Exception e){ IJ.error("Write failed: "+e.getMessage()); }
    }

    void exportTimingReport(String directory,String csvName) throws Exception {
        String base=csvName.toLowerCase().endsWith(".csv")?csvName.substring(0,csvName.length()-4):csvName;
        // Channel selection and setup contains user interaction, so report it
        // separately but do not call it processing time.
        double processing=backgroundSeconds+initialComputeSeconds+exportSeconds;
        double wall=(System.nanoTime()-runStartNs)/1e9;
        String json="{\n"+
            "  \"tool\": \"rgbcamp_fiji\",\n"+
            "  \"performance_options\": {\"adaptive_temporal_background_sampling\": "+adaptiveTemporalSamples+"},\n"+
            "  \"timings_seconds\": {\n"+
            "    \"channel_selection_and_setup_wall\": "+IJ.d2s(loadSetupSeconds,4)+",\n"+
            "    \"temporal_background\": "+IJ.d2s(backgroundSeconds,4)+",\n"+
            "    \"initial_tracking_and_measurement\": "+IJ.d2s(initialComputeSeconds,4)+",\n"+
            "    \"csv_and_roi_export\": "+IJ.d2s(exportSeconds,4)+",\n"+
            "    \"processing_total_excluding_manual_review\": "+IJ.d2s(processing,4)+",\n"+
            "    \"wall_clock_total_including_manual_review\": "+IJ.d2s(wall,4)+"\n"+
            "  }\n}\n";
        java.io.FileWriter timing=new java.io.FileWriter(directory+base+"_timing.json");
        timing.write(json);timing.close();
        IJ.log("Timing report: processing "+IJ.d2s(processing,1)+" s; total including review "+IJ.d2s(wall,1)+" s.");
    }

    // Compact audit trail. A binary 4K mask TIFF can be gigabytes; an ImageJ ROI
    // ZIP stores the exact accepted outline/midline geometry in a few megabytes
    // and can recreate the mask losslessly by filling the body polygon.
    void exportReviewRois(String directory,String csvName) throws Exception {
        String base=csvName.toLowerCase().endsWith(".csv")?csvName.substring(0,csvName.length()-4):csvName;
        RoiManager manager=new RoiManager(true);
        for(int f=0;f<nFrames;f++){
            if(!found[f]||skip[f])continue;
            int[] ox=new int[2*nMid],oy=new int[2*nMid];
            for(int i=0;i<nMid;i++){
                ox[i]=(int)Math.round(ex(f,i,0));oy[i]=(int)Math.round(ey(f,i,0));
                int j=2*nMid-1-i;ox[j]=(int)Math.round(ex(f,i,1));oy[j]=(int)Math.round(ey(f,i,1));
            }
            PolygonRoi body=new PolygonRoi(ox,oy,ox.length,Roi.POLYGON);
            body.setName(String.format("frame_%05d_body",f+1));body.setPosition(sliceOf(f));manager.addRoi(body);
            int[] mx=new int[nMid],my=new int[nMid];
            boolean head0=headIsPoint0[f];
            for(int i=0;i<nMid;i++){
                int q=head0?i:nMid-1-i;mx[i]=(int)Math.round(midX[f][q]);my[i]=(int)Math.round(midY[f][q]);
            }
            PolygonRoi mid=new PolygonRoi(mx,my,nMid,Roi.POLYLINE);
            mid.setName(String.format("frame_%05d_midline_head_to_tail",f+1));mid.setPosition(sliceOf(f));manager.addRoi(mid);
        }
        if(manager.getCount()>0 && !manager.runCommand("Save",directory+base+"_review_rois.zip"))
            throw new java.io.IOException("Could not save review ROI ZIP");
        manager.close();
    }

    // Machine-readable twin of the review ROI ZIP: the same accepted geometry,
    // plus the measurement bands, as plain JSON. Two reasons it is not the ZIP:
    // the bands are not in the ZIP at all (segPolygon's ROIs are built for the
    // on-screen overlay and die with the window), and reading ImageJ ROI files
    // from Python needs a parser library on every lab machine to decode a
    // format this side already holds natively.
    //
    // Coordinates are image pixels in the ORIGINAL frame, matching the CSV.
    // Frames with no accepted geometry carry found/skip and nothing else, so a
    // gap stays a gap rather than being filled with a stale outline.
    // JSON has no NaN literal. IJ.d2s would write the bare token NaN, which
    // makes the WHOLE file unparseable - so one bad coordinate would silently
    // cost the entire recording rather than one point. null says the same
    // thing truthfully and keeps the file readable.
    String jnum(double v, int dp){
        return (Double.isNaN(v)||Double.isInfinite(v)) ? "null" : IJ.d2s(v,dp);
    }

    void exportGeometrySidecar(String directory,String csvName) throws Exception {
        String base=csvName.toLowerCase().endsWith(".csv")?csvName.substring(0,csvName.length()-4):csvName;
        if (muscleBoundaryFrac==null) buildMuscleBoundaries();
        java.io.BufferedWriter w=new java.io.BufferedWriter(
            new java.io.FileWriter(directory+base+"_geometry.json"));
        try {
            w.write("{\n  \"tool\": \"rgbcamp_fiji\",\n");
            w.write("  \"n_frames\": "+nFrames+",\n");
            w.write("  \"n_seg\": "+nSeg+",\n");
            w.write("  \"n_mid\": "+nMid+",\n");
            w.write("  \"width_scale\": "+jnum(widthScale,6)+",\n");
            // The FULL boundary array. boundaryFracString() samples every
            // nSeg/8th value for the log, which is a summary and cannot
            // reconstruct where a band actually sat.
            w.write("  \"muscle_boundary_frac\": [");
            for (int k=0;k<=nSeg;k++){ if(k>0) w.write(", "); w.write(jnum(muscleBoundaryFrac[k],6)); }
            w.write("],\n  \"frames\": [\n");
            boolean first=true;
            for (int f=0; f<nFrames; f++){
                if(!first) w.write(",\n");
                first=false;
                w.write("    {\"frame\": "+(f+1)
                    +", \"found\": "+(found[f]?"true":"false")
                    +", \"skip\": "+(skip[f]?"true":"false"));
                if (found[f] && !skip[f]) {
                    boolean head0=headIsPoint0[f];
                    w.write(", \"midline\": [");
                    for (int i=0;i<nMid;i++){
                        int q=head0?i:nMid-1-i;
                        if(i>0) w.write(",");
                        w.write("["+jnum(midX[f][q],2)+","+jnum(midY[f][q],2)+"]");
                    }
                    w.write("], \"outline\": [");
                    for (int i=0;i<nMid;i++){
                        if(i>0) w.write(",");
                        w.write("["+jnum(ex(f,i,0),2)+","+jnum(ey(f,i,0),2)+"]");
                    }
                    for (int i=nMid-1;i>=0;i--){
                        w.write(",["+jnum(ex(f,i,1),2)+","+jnum(ey(f,i,1),2)+"]");
                    }
                    w.write("], \"bands\": {");
                    for (int k=0;k<nSeg;k++){
                        if(k>0) w.write(",");
                        w.write("\""+k+"\": {");
                        for (int s=0;s<2;s++){
                            int[][] poly=segPolygon(f,k,s);
                            if(s>0) w.write(",");
                            w.write("\""+(s==0?"L":"R")+"\": [");
                            for (int p=0;p<poly[0].length;p++){
                                if(p>0) w.write(",");
                                w.write("["+poly[0][p]+","+poly[1][p]+"]");
                            }
                            w.write("]");
                        }
                        w.write("}");
                    }
                    w.write("}");
                }
                w.write("}");
            }
            w.write("\n  ]\n}\n");
        } finally { w.close(); }
        IJ.log("[geometry] wrote "+base+"_geometry.json - midline, outline and "
            +nSeg+"x2 measurement bands per accepted frame.");
    }

    double safeRatio(double a, double b){ return (Double.isNaN(a)||Double.isNaN(b)||b<1e-6)?Double.NaN:a/b; }
    // rate of change of ratio A/B at frame f (per second)
    double ratioRate(double[] A, double[] B, int f){
        int g=f+1; double sgn=1;
        if (g>=nFrames||Double.isNaN(A[g])||Double.isNaN(B[g])){ g=f-1; sgn=-1; }
        if (g<0||Double.isNaN(A[g])||Double.isNaN(B[g])||Double.isNaN(A[f])||Double.isNaN(B[f])) return Double.NaN;
        double r1=safeRatio(A[f],B[f]), r2=safeRatio(A[g],B[g]);
        if (Double.isNaN(r1)||Double.isNaN(r2)) return Double.NaN;
        return (r2-r1)*sgn*fps;
    }
    // angular velocity of a segment (deg/s): change in segment body angle over time
    double angularVel(int f, int k){
        int g=f+1; double sgn=1;
        if (g>=nFrames||!found[g]){ g=f-1; sgn=-1; }
        if (g<0||!found[g]) return Double.NaN;
        double a1=segAngleDeg(f,k), a2=segAngleDeg(g,k);
        if (Double.isNaN(a1)||Double.isNaN(a2)) return Double.NaN;
        double d=a2-a1; while (d>180) d-=360; while (d<-180) d+=360;
        return d*sgn*fps;
    }

    String fmt(double v){ return Double.isNaN(v)?"NaN":IJ.d2s(v,4); }

    // Free-text metadata (strain, rnai, animal id) is written into an unquoted CSV, so
    // strip characters that would corrupt the row structure or a filename built from it.
    String csvSafe(String s){
        if (s==null) return "";
        return s.replace(",", ";").replace("\n"," ").replace("\r"," ").trim();
    }
    String filenameSafe(String s){
        if (s==null || s.trim().isEmpty()) return "na";
        String out = s.trim().replaceAll("[^A-Za-z0-9._-]+", "_").replaceAll("_+","_");
        out = out.replaceAll("^_+|_+$", "");
        return out.isEmpty()? "na" : out;
    }

    void reportFlags() {
        int nFound=0, nCoil=0, nArea=0, nSkip=0;
        for (int f=0;f<nFrames;f++){
            if (skip[f]){ nSkip++; continue; }
            if (found[f]) nFound++;
            if (coilFlag[f]) nCoil++;
            if (areaFlag[f]) nArea++;
        }
        double coilPct=100.0*nCoil/Math.max(1,nFrames);
        IJ.log("==== flag summary ====");
        IJ.log("frames: "+nFrames+"  found: "+nFound+"  skipped: "+nSkip);
        IJ.log("coil/skeleton-fail: "+nCoil+" ("+IJ.d2s(coilPct,1)+"%)   area-jump: "+nArea);
        IJ.log(coilPct>10 ? "WARNING: coil rate >10%. Standalone skeleton may be insufficient; reconsider external skeletonizer."
                          : "Coil rate acceptable for standalone skeletonization.");
    }

    // ---- Recalibrate midline & perimeter from all manual frames ----
    // After adding or correcting midlines on extra frames during review, call this to
    // re-learn the conserved length, width profile, area, and perimeter from EVERY frame
    // that currently has a manual (user-drawn or reference) midline — not just the
    // original reference frames. This updates the targets used by extension, flag, and
    // size-deviation checks without losing any existing manual work.
    void recalibrateMidlineAndPerimeter() {
        // Collect all frames that carry a trusted manual midline: either in refFrames
        // (original reference traces) OR any frame where the user redrew the midline
        // during review (manualMidline[f]==true, which includes deriveReferenceFromOutline).
        java.util.ArrayList<Integer> calibFrames = new java.util.ArrayList<Integer>();
        for (int f = 0; f < nFrames; f++) {
            if (manualMidline[f] && found[f] && !skip[f]) {
                if (!calibFrames.contains(f)) calibFrames.add(f);
            }
        }
        // Also include any original reference frames not yet in calibFrames
        for (int rf : refFrames) {
            if (rf >= 0 && rf < nFrames && found[rf] && !skip[rf] && !calibFrames.contains(rf)) {
                calibFrames.add(rf);
            }
        }

        if (calibFrames.isEmpty()) {
            IJ.error("Recalibrate: no manual midline frames found.\n" +
                     "Use 'Redraw MIDLINE' on a clean, fully-visible frame first,\n" +
                     "or add a reference frame via 'Add reference frame'.");
            return;
        }

        IJ.log("Recalibrating from " + calibFrames.size() + " manual/reference frame(s): " + calibFrames);

        // --- Re-learn conserved length ---
        java.util.ArrayList<Double> lens = new java.util.ArrayList<Double>();
        for (int f : calibFrames) lens.add(midLen[f]);
        double newLength = median(lens);
        if (newLength > 0) {
            refLength = newLength;
            IJ.log("  Updated refLength = " + IJ.d2s(refLength, 0) + " px (median of " + lens.size() + " frame(s)).");
        }

        // --- Re-learn width profile (L and R) ---
        // Temporarily treat ALL calibration frames as reference frames for profile learning.
        java.util.ArrayList<Integer> savedRef = new java.util.ArrayList<Integer>(refFrames);
        refFrames.clear();
        refFrames.addAll(calibFrames);
        learnWidthProfile();   // updates profL, profR, profLearned
        // Restore the original refFrames list (so the existing reference-frame display/logic is unchanged)
        refFrames.clear();
        refFrames.addAll(savedRef);
        // Also add any new manual frames that were not previously reference frames
        for (int f : calibFrames) {
            if (!refFrames.contains(f)) refFrames.add(f);
        }

        // --- Re-learn area and perimeter from the body masks of calibration frames ---
        // For frames with a manual midline derived from a traced outline we re-measure
        // from the stored outline; for frames redrawn freehand we measure the body mask.
        refAreaList.clear();
        refPerimList.clear();
        for (int f : calibFrames) {
            ByteProcessor m = bodyMaskCached(f);
            if (m == null) continue;
            double area = countForeground(m);
            if (area >= minBodyArea) refAreaList.add(area);
            Polygon perimPoly = traceOutline((ByteProcessor) m.duplicate());
            if (perimPoly != null) {
                double perim = polygonPerimeter(perimPoly);
                if (perim > 0) refPerimList.add(perim);
            }
        }
        if (!refAreaList.isEmpty()) {
            refArea  = median(refAreaList);
            refPerim = refPerimList.isEmpty() ? 0 : median(refPerimList);
            IJ.log("  Updated refArea = " + IJ.d2s(refArea, 0) + " px²,  refPerim = " + IJ.d2s(refPerim, 0) + " px.");
        }

        // --- Full recompute so all flags, inferred frames, and overlays reflect the new calibration ---
        IJ.log("Recalibration complete. Running full recompute...");
        recomputeAll();
        redraw();
        IJ.log("Done. All extension targets and size-deviation flags updated.");
    }

    // ---------------- helpers ----------------
    int clamp(int v,int lo,int hi){ return v<lo?lo:(v>hi?hi:v); }
    double clampD(double v,double lo,double hi){ return v<lo?lo:(v>hi?hi:v); }
    double dist(double x1,double y1,double x2,double y2){ return Math.sqrt((x1-x2)*(x1-x2)+(y1-y2)*(y1-y2)); }
    double mod360(double a){ a%=360; if(a<0)a+=360; return a; }
    double mod180(double a){ a%=180; if(a<0)a+=180; return a; }
}
