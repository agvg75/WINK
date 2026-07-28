"""
neuron_tracker.py
=================
Anterior sensory-neuron tracker (AFD or any labelled head neuron) for freely
moving worms, built on background subtraction so it works on dark, dim,
vignetted footage where threshold-and-flood fails.

Seed once (click the soma, trace the worm outline). The outline gives the
invariants a worm cannot change: area, midline length, and the fixed
soma-to-nose arc used to PLACE the nose each frame. Detection is temporal-
median background subtraction; the soma is tracked by continuity within a
radius (other GFP cells ignored); the midline is a geodesic longest path; and
the length invariant is the quality check. Nothing is interpolated silently.

State is per-frame and editable, so a review window can recompute or correct
any single frame. export_rows() builds the CSV rows (dF/F with a baseline
floor, field-relative angles, provenance, needs_help).
"""
import numpy as np
from scipy import ndimage as ndi
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import shortest_path
from skimage.morphology import skeletonize
from skimage.draw import polygon2mask
from skimage.registration import phase_cross_correlation
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
from acquisition import AcquisitionMetadata
from temporal_worm_geometry import (fill_adaptive_spine_gaps, resample_polyline,
                                    suggest_manual_anchor_frames)
from segmentation_review import segment_frame


def _compass(dx, dy):
    a = np.degrees(np.arctan2(dx, -dy)); return a + 360 if a < 0 else a

def _mod360(a):
    a = a % 360.0; return a + 360 if a < 0 else a

def geodesic_midline(mask):
    sk = skeletonize(mask); ys, xs = np.where(sk)
    if len(xs) < 10: return None, 0.0
    idx = {(y, x): k for k, (y, x) in enumerate(zip(ys, xs))}; N = len(xs)
    r, c, w = [], [], []
    for k, (y, x) in enumerate(zip(ys, xs)):
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0: continue
                if (y+dy, x+dx) in idx:
                    r.append(k); c.append(idx[(y+dy, x+dx)]); w.append(1.0 if dy == 0 or dx == 0 else 1.4142136)
    Gr = csr_matrix((w, (r, c)), shape=(N, N))
    d0, _ = shortest_path(Gr, indices=0, return_predecessors=True)
    A = int(np.nanargmax(np.where(np.isinf(d0), -1, d0)))
    dA, pred = shortest_path(Gr, indices=A, return_predecessors=True)
    B = int(np.nanargmax(np.where(np.isinf(dA), -1, dA)))
    path = []; cur = B
    while cur >= 0:
        path.append((xs[cur], ys[cur])); nxt = pred[cur]
        if nxt == cur or nxt < 0: break
        cur = nxt
    raw = np.array(path[::-1], float)
    smooth = smooth_centerline(raw)
    return smooth, float(_arclen(smooth)[-1])

def smooth_centerline(path, sigma=1.5):
    """Remove one-pixel skeleton stair-steps without moving either body end.

    Arc-length resampling makes the filter independent of horizontal/diagonal
    pixel ordering.  A linear endpoint correction restores both measured tips,
    avoiding the shortening produced by ordinary Gaussian smoothing.
    """
    path = np.asarray(path, float)
    if len(path) < 5:
        return path.copy()
    raw_arc = _arclen(path)
    sampled = resample_polyline(path, max(5, int(np.ceil(raw_arc[-1]))+1))
    if sampled is None:
        return path.copy()
    filtered = np.column_stack([
        ndi.gaussian_filter1d(sampled[:, 0], sigma=sigma, mode="nearest"),
        ndi.gaussian_filter1d(sampled[:, 1], sigma=sigma, mode="nearest"),
    ])
    weight = np.linspace(0.0, 1.0, len(filtered))[:, None]
    start_delta = sampled[0]-filtered[0]
    end_delta = sampled[-1]-filtered[-1]
    return filtered + (1.0-weight)*start_delta + weight*end_delta

def _arclen(path):
    return np.concatenate([[0], np.cumsum(np.hypot(np.diff(path[:, 0]), np.diff(path[:, 1])))])

def _point_at_arc(path, cum, s):
    s = np.clip(s, 0, cum[-1]); k = int(np.searchsorted(cum, s)); k = min(max(k, 1), len(path)-1)
    f = (s - cum[k-1]) / max(1e-6, cum[k]-cum[k-1]); return path[k-1] + f*(path[k]-path[k-1])


class NeuronTracker:
    def __init__(self, frames_gray, fps=30.0, field_angle=0.0,
                 um_per_px=None, exposure_ms=None,
                 soma_radius=None, search_radius=None, qc_len_tol=25.0,
                 nose_arc_tol_frac=0.25,segmentation_config=None,
                 source_indices=None,progress_callback=None,
                 registration_proxy=True,local_segmentation=True,
                 adaptive_background_sampling=True):
        init_started=time.perf_counter();self.timings={};self.performance_options={
            "registration_proxy":bool(registration_proxy),
            "local_segmentation":bool(local_segmentation),
            "adaptive_background_sampling":bool(adaptive_background_sampling)}
        self.acquisition = AcquisitionMetadata(
            fps, "declared", um_per_px, "declared",
            exposure_ms, "declared").validate()
        self.G=(frames_gray if getattr(frames_gray,"is_virtual_stack",False)
                else np.asarray(frames_gray,dtype=np.float32))
        self.T, self.H, self.W = self.G.shape
        self.source_indices=np.asarray(source_indices if source_indices is not None else np.arange(self.T),dtype=int)
        self.segmentation_config=segmentation_config;self.progress_callback=progress_callback
        self.fps = fps; self.field_angle = field_angle; self.um_per_px = um_per_px
        self.soma_r = soma_radius or max(6, self.W//360)
        self.search_r = search_radius or max(40, self.W//16)
        self.qc_len_tol = qc_len_tol
        self.nose_arc_tol_frac = nose_arc_tol_frac
        self.registration_proxy=bool(registration_proxy)
        self.local_segmentation=bool(local_segmentation)
        self.adaptive_background_sampling=bool(adaptive_background_sampling)
        phase=time.perf_counter()
        self.camera_shift = self._estimate_camera_shifts()
        self.timings["camera_registration_s"]=time.perf_counter()-phase
        # A sampled registered median is robust for background estimation and
        # avoids a second full-movie float array at 4K resolution.
        phase=time.perf_counter();per_frame=max(self.H*self.W*4,1)
        budget_count=(max(3,(256*1024**2)//per_frame)
                      if self.adaptive_background_sampling else 31)
        background_indices=np.unique(np.linspace(0,self.T-1,min(31,self.T,budget_count)).astype(int))
        registered = [ndi.shift(self._normalized(i), self.camera_shift[i], order=1,
                                mode="constant", cval=np.nan)
                      for i in background_indices]
        self.bg = np.nanmedian(np.asarray(registered), axis=0)
        self.timings["background_model_s"]=time.perf_counter()-phase
        self.state = [None]*self.T           # per-frame dict, editable
        self.soma_nose_arc = None; self.area_ref = None; self.len_ref = None
        self.soma_profile = None             # seed oval stats: peak/mean/min/area
        self._kernel = None
        self.timings["tracker_initialization_s"]=time.perf_counter()-init_started

    def _normalized(self,i):
        frame=np.asarray(self.G[i],dtype=np.float32)
        return frame-np.median(frame)

    def _registration_frame(self,i,step):
        """Downsample before float conversion; avoids a full 4K float temporary."""
        frame=np.asarray(self.G[i])[::step,::step].astype(np.float32,copy=False)
        return frame-np.median(frame)

    def _estimate_camera_shifts(self):
        shifts = np.zeros((self.T, 2), float)
        step=(max(1,int(np.ceil(max(self.H,self.W)/1024)))
              if self.registration_proxy else 1)
        for i in range(1, self.T):
            if self.source_indices[i]!=self.source_indices[i-1]+1:
                shifts[i]=0
                continue
            try:
                delta, error, _ = phase_cross_correlation(
                    ndi.gaussian_filter(self._registration_frame(i-1,step),2),
                    ndi.gaussian_filter(self._registration_frame(i,step),2),
                    upsample_factor=4, normalization=None)
                delta = np.asarray(delta,float)*step
                shifts[i] = (shifts[i-1]+delta if np.all(np.isfinite(delta))
                             and np.linalg.norm(delta) <= 0.2*min(self.H, self.W)
                             and np.isfinite(error) else shifts[i-1])
            except Exception:
                shifts[i] = shifts[i-1]
            if self.progress_callback and (i%3==0 or i==self.T-1):self.progress_callback(i+1,self.T,"Registering camera motion")
        return shifts

    def _background_for_frame(self, i):
        return ndi.shift(self.bg, -self.camera_shift[i], order=1,
                         mode="constant", cval=np.nan)

    @property
    def soma_kernel(self):
        """Disk of the soma's own size, for region scoring. A real soma is a blob
        of a characteristic size; a hot pixel or dust speck is a single point that
        this averaging suppresses."""
        R = int(max(2, round(self.soma_r)))
        if self._kernel is None or self._kernel.shape[0] != 2*R+1:
            yy, xx = np.ogrid[:2*R+1, :2*R+1]
            k = np.zeros((2*R+1, 2*R+1), float)
            k[(xx-R)**2+(yy-R)**2 <= R*R] = 1.0
            self._kernel = k/k.sum()
        return self._kernel

    def set_soma_profile(self, frame_idx, soma_mask):
        """Learn the soma's size and brightness profile from an oval drawn INSIDE
        the cell at seed time. Gives a measured radius (rather than a guess) and a
        reference profile for diagnostics."""
        if soma_mask is None or not soma_mask.any():
            return None
        vals = self.G[frame_idx][soma_mask]
        area = float(soma_mask.sum())
        self.soma_r = float(max(2.0, np.sqrt(area/np.pi)))
        self._kernel = None
        cy, cx = ndi.center_of_mass(soma_mask)
        self.soma_profile = dict(peak=float(vals.max()), mean=float(vals.mean()),
                                 minimum=float(vals.min()), std=float(vals.std()),
                                 area_px=area, radius_px=self.soma_r,
                                 center=(float(cx), float(cy)))
        return self.soma_profile

    # ---- detection primitives ----
    def _mask(self, i, soma_hint=None):
        """Worm mask from background subtraction. The soma is only a HINT used to
        grow into the fainter head; the mask does not depend on it being right,
        so a soma that has drifted off the worm cannot drag the mask with it."""
        if self.segmentation_config is not None:
            raw=np.asarray(self.G[i]);reference=self._background_for_frame(i)+np.median(raw)
            reviewed=segment_frame(raw,int(self.source_indices[i]),self.segmentation_config,reference=reference)
            lab,n=ndi.label(reviewed)
            if n:
                keep=None
                if soma_hint is not None:
                    sx,sy=int(round(soma_hint[0])),int(round(soma_hint[1]))
                    if 0<=sx<self.W and 0<=sy<self.H and lab[sy,sx]>0:keep=lab[sy,sx]
                if keep is None:
                    sizes=ndi.sum(np.ones_like(lab),lab,range(1,n+1));keep=int(np.argmax(sizes))+1
                return ndi.binary_fill_holes(lab==keep)
        # Once the seed established worm length, process a moving local box rather
        # than repeatedly filtering a broad 4K crop. The radius exceeds a full
        # body length because the labelled soma lies near an end of the animal.
        box=None
        if self.local_segmentation and soma_hint is not None and self.len_ref is not None and self.len_ref>0:
            radius=int(np.ceil(max(self.search_r*2,self.len_ref*1.35)))
            sx,sy=int(round(soma_hint[0])),int(round(soma_hint[1]))
            x0=max(0,sx-radius);x1=min(self.W,sx+radius+1);y0=max(0,sy-radius);y1=min(self.H,sy+radius+1)
            if x1>x0 and y1>y0:box=(x0,y0,x1,y1)
        if box is None:
            x0=y0=0;x1=self.W;y1=self.H
        else:x0,y0,x1,y1=box
        frame=np.asarray(self.G[i])[y0:y1,x0:x1].astype(np.float32,copy=False);frame=frame-np.median(frame)
        bg=ndi.shift(self.bg[y0:y1,x0:x1],-self.camera_shift[i],order=1,mode="constant",cval=np.nan)
        d = ndi.gaussian_filter(np.abs(frame-bg), 4)
        finite = d[np.isfinite(d)]
        if not finite.size:
            return None
        hi = d > np.percentile(finite, 99.0)      # confident worm core
        lo = d > np.percentile(finite, 96.0)      # generous: includes the faint head
        seed = hi.copy()
        if soma_hint is not None:
            sx, sy = int(round(soma_hint[0]))-x0, int(round(soma_hint[1]))-y0
            if 0 <= sx < lo.shape[1] and 0 <= sy < lo.shape[0] and lo[sy, sx]:
                # only trust the hint if it lands on moving tissue, never on a
                # stationary background speck
                yy, xx = np.ogrid[:lo.shape[0], :lo.shape[1]]
                seed = seed | (((xx-sx)**2+(yy-sy)**2) < (self.soma_r*5)**2)
        lab, _ = ndi.label(lo); keep = np.unique(lab[seed & (lab > 0)])
        m = np.isin(lab, keep[keep > 0])
        m = ndi.binary_closing(m, iterations=8); m = ndi.binary_opening(m, iterations=1)
        m = ndi.binary_fill_holes(m)
        l2, n2 = ndi.label(m)
        if n2 == 0: return None
        sizes = ndi.sum(np.ones_like(l2), l2, range(1, n2+1))
        local=l2 == (int(np.argmax(sizes))+1)
        if box is None:return local
        result=np.zeros((self.H,self.W),dtype=bool);result[y0:y1,x0:x1]=local;return result

    def _track_soma_step(self, i, prev, mask=None):
        """Find the soma within search_r of its last position and ON THE WORM,
        scoring by the MEAN over a soma-sized disk rather than the single brightest
        pixel. Two reasons: a real soma is a blob of a characteristic size, so a
        hot pixel cannot outscore it; and restricting to the worm stops the track
        from locking onto a stationary bright speck in the background."""
        R = self.search_r; px, py = prev[0], prev[1]
        x0, x1 = max(0, int(px-R)), min(self.W, int(px+R))
        y0, y1 = max(0, int(py-R)), min(self.H, int(py+R))
        win = self.G[i, y0:y1, x0:x1]
        if win.size == 0:
            return (prev[0], prev[1], np.nan)
        score = ndi.convolve(win, self.soma_kernel, mode="nearest")
        allowed = None
        if mask is not None:
            body = ndi.binary_dilation(mask, iterations=max(1, int(round(self.soma_r))))
            allowed = body[y0:y1, x0:x1]
            if not allowed.any():
                allowed = None                      # no worm nearby: fall back
        if allowed is not None:
            score = np.where(allowed, score, -np.inf)
        j = np.unravel_index(np.argmax(score), score.shape)
        if not np.isfinite(score[j]):
            j = np.unravel_index(np.argmax(win), win.shape)
        return (x0+j[1], y0+j[0], float(win[j]))

    def _fluor(self, i, soma):
        sx, sy = int(soma[0]), int(soma[1]); yy, xx = np.ogrid[:self.H, :self.W]
        r2 = (xx-sx)**2+(yy-sy)**2
        roi = r2 < self.soma_r**2; ann = (r2 >= (self.soma_r+2)**2) & (r2 < (self.soma_r+6)**2)
        raw = float(self.G[i][roi].mean()) if roi.any() else np.nan
        bg = float(self.G[i][ann].mean()) if ann.any() else np.nan
        return raw, bg, raw-bg

    # ---- per-frame geometry (shared by full pass and single-frame recompute) ----
    def _geometry(self, i, soma, mask):
        length = area = np.nan; nose = (np.nan, np.nan); anat = np.nan
        cenx = ceny = np.nan; path_used = None; soma_dist = np.inf; on_worm = False
        nose_arc_err = np.nan; nose_prov = "none"; soma_nose_euclid = np.nan
        if mask is not None:
            # is the soma ON the animal? (the neuron sits to one side of the
            # midline, so mask membership is the meaningful test, not midline distance)
            sxi, syi = int(round(soma[0])), int(round(soma[1]))
            if 0 <= sxi < self.W and 0 <= syi < self.H:
                near = ndi.binary_dilation(mask, iterations=max(1, int(self.soma_r)))
                on_worm = bool(near[syi, sxi])
            full, flen = geodesic_midline(mask); area = float(mask.sum())
            if full is not None and flen > 0 and self.soma_nose_arc is not None:
                cum = _arclen(full)
                dss = np.hypot(full[:, 0]-soma[0], full[:, 1]-soma[1])
                sj = int(np.argmin(dss)); soma_dist = float(dss[sj])
                head_start = cum[sj] < (cum[-1]-cum[sj])
                ant = self.soma_nose_arc
                post = max(0.0, (self.len_ref or flen) - ant)
                # INDEPENDENT nose estimate: how far the real skeleton tip actually
                # lies anterior of the soma. The fixed arc says it should be `ant`.
                # These are derived differently, so comparing them is a real check
                # (it catches a truncated head, a spurious anterior spur, or a soma
                # that has slid along the body).
                arc_to_tip = cum[sj] if head_start else (cum[-1]-cum[sj])
                nose_arc_err = float(arc_to_tip - ant)
                # the faint anterior tip wobbles by tens of pixels between frames,
                # so the tolerance needs an absolute floor: a pure fraction of the
                # arc becomes hypersensitive whenever the soma sits near the nose
                tol = max(self.nose_arc_tol_frac * ant, 25.0)
                # keep only the worm's own length of midline around the soma,
                # so a spurious mask tail cannot extend the spine (incompressibility)
                if head_start:
                    a0, a1, nose_arc = cum[sj]-ant, cum[sj]+post, cum[sj]-ant
                else:
                    a0, a1, nose_arc = cum[sj]-post, cum[sj]+ant, cum[sj]+ant
                a0 = max(0.0, a0); a1 = min(cum[-1], a1)
                sel = (cum >= a0) & (cum <= a1)
                path_used = full[sel] if sel.sum() >= 2 else full
                length = float(cum[sel][-1]-cum[sel][0]) if sel.sum() >= 2 else flen
                if nose_arc_err < -tol:
                    # the mask's head is SHORT of the anatomical nose: extend along
                    # the terminal midline direction rather than silently clamping
                    # the nose onto a truncated tip.
                    tip = full[0] if head_start else full[-1]
                    ref = _point_at_arc(full, cum, max(0.0, arc_to_tip-20) if head_start
                                        else min(cum[-1], cum[sj]+max(0.0, arc_to_tip-20)))
                    d = tip - ref; nrm = np.hypot(d[0], d[1])
                    if nrm > 1e-6:
                        nose = tuple(tip + (d/nrm)*(-nose_arc_err))
                        nose_prov = "extrapolated"
                    else:
                        nose = tuple(tip); nose_prov = "tip_short"
                else:
                    nose = tuple(_point_at_arc(full, cum, nose_arc))
                    nose_prov = "measured" if abs(nose_arc_err) <= tol else "tip_long"
                anat = _compass(nose[0]-soma[0], nose[1]-soma[1])
                soma_nose_euclid = float(np.hypot(nose[0]-soma[0], nose[1]-soma[1]))
                ceny, cenx = ndi.center_of_mass(mask)
        raw, fbg, corr = self._fluor(i, soma)
        return dict(soma=(soma[0], soma[1]), soma_peak=soma[2] if len(soma) > 2 else np.nan,
                    mask_area=area, length=length, nose=nose, anat=anat,
                    soma_dist=soma_dist, soma_on_worm=on_worm,
                    nose_arc_err=nose_arc_err, nose_prov=nose_prov,
                    soma_nose_euclid=soma_nose_euclid,
                    cenx=cenx, ceny=ceny, raw=raw, fbg=fbg, corr=corr,
                    path=path_used, provenance="measured", needs_help=0)

    # ---- full pass ----
    def track_all(self, soma_seed, outline_mask, soma_mask=None,range_seeds=None):
        phase=time.perf_counter()
        if soma_mask is not None:
            self.set_soma_profile(0, soma_mask)      # measured radius + profile
        p0, l0 = geodesic_midline(outline_mask); cum0 = _arclen(p0)
        self.area_ref = float(outline_mask.sum())
        self.len_ref = float(l0)
        ds = np.hypot(p0[:, 0]-soma_seed[0], p0[:, 1]-soma_seed[1]); si = int(np.argmin(ds))
        self.soma_nose_arc = cum0[si] if cum0[si] < (cum0[-1]-cum0[si]) else (cum0[-1]-cum0[si])
        soma = (soma_seed[0], soma_seed[1], self.G[0][int(soma_seed[1]), int(soma_seed[0])])
        range_seeds=dict(range_seeds or {})
        for i in range(self.T):
            if i in range_seeds:
                soma,manual_outline,manual_soma_mask=range_seeds[i]
                if manual_soma_mask is not None:self.set_soma_profile(i,manual_soma_mask)
                m=manual_outline;self.state[i]=self._geometry(i,(soma[0],soma[1],self.G[i][int(soma[1]),int(soma[0])]),m)
                if self.progress_callback:self.progress_callback(i+1,self.T,"Tracking selected frames")
                continue
            hint = soma if i == 0 else self.state[i-1]["soma"]
            m = self._mask(i, hint)                        # mask first, independent of a drifted soma
            if i > 0:
                soma = self._track_soma_step(i, self.state[i-1]["soma"], mask=m)
            self.state[i] = self._geometry(i, soma, m)
            if self.progress_callback and (i%2==0 or i==self.T-1):self.progress_callback(i+1,self.T,"Tracking selected frames")
        self._recalibrate_and_qc()
        self._temporal_reconstruct()
        self.timings["tracking_and_reconstruction_s"]=time.perf_counter()-phase
        return self.state

    def _temporal_reconstruct(self, bounds=None):
        """Fill bridgeable two-sided failures; retain raw frame provenance."""
        offset = 0
        work = self.state
        if bounds is not None:
            left, right = sorted((int(bounds[0]), int(bounds[1])))
            left = max(0, left); right = min(self.T-1, right)
            offset = left
            work = self.state[left:right+1]
        for state in work:
            state["pts"] = (resample_polyline(state.get("path"), 25)
                            if state and state.get("path") is not None else None)
        filled_local = fill_adaptive_spine_gaps(work, target_length=self.len_ref)
        filled = [i + offset for i in filled_local]
        for i in filled:
            state = self.state[i]
            left = state["temporal_left_frame"] + offset
            right = state["temporal_right_frame"] + offset
            state["temporal_left_frame"] = left
            state["temporal_right_frame"] = right
            fraction = (i-left)/(right-left)
            for key in ("soma", "nose"):
                a, b = self.state[left].get(key), self.state[right].get(key)
                if a is not None and b is not None:
                    state[key] = tuple((1-fraction)*np.asarray(a[:2], float)
                                       + fraction*np.asarray(b[:2], float))
            state["path"] = state["pts"].copy()
            state["nose_prov"] = "inferred_between_neighbors"
        self.suggested_manual_anchors = suggest_manual_anchor_frames(self.state)
        return filled

    def next_suggested_anchor(self, current=-1):
        anchors = suggest_manual_anchor_frames(self.state)
        self.suggested_manual_anchors = anchors
        after = [frame for frame in anchors if frame > current]
        return after[0] if after else (anchors[0] if anchors else None)

    def reanalyze_interval(self, start, end):
        start, end = sorted((int(start), int(end)))
        start = max(0, start); end = min(self.T-1, end)
        if end <= start:
            return []
        self._prepare_bounded_reconstruction(start, end)
        return self._temporal_reconstruct(bounds=(start, end))

    def _prepare_bounded_reconstruction(self, start, end):
        """Retain manual/boundary anchors and invalidate prior interpolation."""
        start, end = sorted((max(0, int(start)), min(self.T-1, int(end))))
        for frame in (start, end):
            state = self.state[frame]
            if state and state.get("path") is not None:
                state["needs_help"] = 0
                state["interval_boundary_anchor"] = 1
        for frame in range(start+1, end):
            state = self.state[frame]
            if not state:
                continue
            if state.get("provenance") == "manual":
                state["needs_help"] = 0
                continue
            state.setdefault("raw_path", state.get("path"))
            state["needs_help"] = 1
            state["provenance"] = "user_flagged_interval"
            state["user_flagged_interval"] = 1

    def _recalibrate_and_qc(self):
        # needs_help means "a human must look at this frame", not "this frame is
        # imperfect". A frame is unusable when there is no worm, the soma is off
        # the animal, the mask has collapsed, or the head is so poorly segmented
        # that the nose would be mostly invented. Milder nose disagreement is
        # reported through nose_provenance instead of forcing a manual fix: the
        # anterior tip is faint and its detected position wobbles by tens of
        # pixels, so a tight tolerance here flags good frames.
        arc = self.soma_nose_arc or 0.0
        nose_severe = max(0.6*arc, 50.0)
        for s in self.state:
            if s is None:
                continue
            if s.get("provenance") in {"manual", "inferred_between_neighbors"}:
                s["needs_help"] = 0; continue
            area = s["mask_area"]
            area_dev = 100*abs(area-self.area_ref)/self.area_ref if (area == area and self.area_ref) else np.nan
            s["area_dev"] = area_dev
            len_dev = 100*abs(s["length"]-self.len_ref)/self.len_ref if (s["length"] == s["length"] and self.len_ref) else np.nan
            s["len_dev"] = len_dev
            nae = s.get("nose_arc_err", np.nan)
            bad = (s["path"] is None) \
                or (not s.get("soma_on_worm", False)) \
                or (area == area and area < 0.4*self.area_ref) \
                or (s["length"] == s["length"] and self.len_ref and s["length"] < 0.6*self.len_ref) \
                or (nae == nae and abs(nae) > nose_severe)
            s["provenance"] = "help" if bad else "measured"
            s["needs_help"] = 1 if bad else 0

    # ---- corrections ----
    def recompute_frame(self, i, soma=None, outline_verts=None,
                        reconstruct_bounds=None):
        """Recompute one frame. soma=(x,y) overrides the soma; outline_verts is a
        list of (x,y) giving a hand outline for this frame's mask. Marks manual."""
        hint = soma if soma is not None else (
            self.state[i-1]["soma"] if i > 0 and self.state[i-1] else self.state[i]["soma"])
        if outline_verts is not None and len(outline_verts) >= 3:
            poly = np.array([(y, x) for (x, y) in outline_verts])
            mask = polygon2mask((self.H, self.W), poly)
        else:
            mask = self._mask(i, hint)
        if soma is not None:
            peak = float(self.G[i][int(soma[1]), int(soma[0])]); soma = (soma[0], soma[1], peak)
        else:
            soma = self._track_soma_step(i, hint, mask=mask)
        st = self._geometry(i, soma, mask)
        st["provenance"] = "manual"; st["needs_help"] = 0
        self.state[i] = st
        self._recalibrate_and_qc()
        if reconstruct_bounds is not None:
            self._prepare_bounded_reconstruction(*reconstruct_bounds)
        self._temporal_reconstruct(bounds=reconstruct_bounds)
        return st

    def retrack_from(self, i0):
        """Re-propagate soma continuity forward from frame i0 (after a fix)."""
        for i in range(max(1, i0+1), self.T):
            prev = self.state[i-1]["soma"]
            m = self._mask(i, prev)
            soma = self._track_soma_step(i, prev, mask=m)
            self.state[i] = self._geometry(i, soma, m)
        self._recalibrate_and_qc()
        self._temporal_reconstruct()

    # ---- export ----
    def export_rows(self):
        corr = np.array([s["corr"] for s in self.state], float)
        finite = corr[np.isfinite(corr)]
        # baseline floor: never let a near-zero baseline blow up dF/F
        if finite.size:
            base = max(np.percentile(finite, 10), 0.25*np.median(finite), 1e-3)
        else:
            base = np.nan
        rows = []
        for i, s in enumerate(self.state):
            a = s["anat"]; mv = s.get("move", np.nan)
            rows.append(dict(
                **self.acquisition.as_columns(),
                frame=int(self.source_indices[i])+1, time_s=float(self.source_indices[i])/self.fps, analyzed_frame_index=i+1, soma_x=s["soma"][0], soma_y=s["soma"][1],
                soma_peak=s["soma_peak"], soma_on_worm=int(bool(s.get("soma_on_worm", False))),
                neuron_raw=s["raw"], neuron_bg=s["fbg"],
                neuron_corrected=s["corr"],
                neuron_dFF=(s["corr"]-base)/base if base == base else np.nan,
                body_centroid_x=s["cenx"], body_centroid_y=s["ceny"],
                body_area=s["mask_area"], body_length=s["length"],
                nose_arc_err_px=s.get("nose_arc_err", np.nan),
                nose_provenance=s.get("nose_prov", ""),
                soma_nose_dist_px=s.get("soma_nose_euclid", np.nan),
                nose_x=s["nose"][0], nose_y=s["nose"][1], anat_angle=a,
                length_dev_pct=s.get("len_dev", np.nan),
                anat_vs_field=_mod360(a-self.field_angle) if a == a else np.nan,
                flank_translation_body_lengths=s.get(
                    "flank_translation_body_lengths", np.nan),
                flank_shape_disagreement_body_lengths=s.get(
                    "flank_shape_disagreement_body_lengths", np.nan),
                suggested_manual_anchor=int(s.get("suggested_manual_anchor", 0)),
                reconstruction_reason=s.get("reconstruction_reason", ""),
                provenance=s["provenance"], needs_help=s["needs_help"]))
            rows[-1]["camera_shift_x_px"] = float(-self.camera_shift[i, 1])
            rows[-1]["camera_shift_y_px"] = float(-self.camera_shift[i, 0])
        # movement angle from soma displacement, and anat-vs-move
        for i in range(len(rows)):
            gap=(i==0 or self.source_indices[i]!=self.source_indices[i-1]+1)
            rows[i]["source_gap_before"]=int(gap and i>0)
            if gap: rows[i]["move_angle"] = np.nan
            else:
                dx = rows[i]["soma_x"]-rows[i-1]["soma_x"]; dy = rows[i]["soma_y"]-rows[i-1]["soma_y"]
                rows[i]["move_angle"] = _compass(dx, dy) if np.hypot(dx, dy) >= 2 else np.nan
            a = rows[i]["anat_angle"]; mv = rows[i]["move_angle"]
            rows[i]["anat_vs_move"] = _mod360(a-mv) if (a == a and mv == mv) else np.nan
            rows[i]["move_vs_field"] = _mod360(mv-self.field_angle) if mv == mv else np.nan
        return rows

    @property
    def reference(self):
        return dict(length_px=self.len_ref, area_px=self.area_ref,
                    soma_nose_arc_px=self.soma_nose_arc)
