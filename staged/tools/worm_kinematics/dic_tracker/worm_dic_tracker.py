"""
worm_dic_tracker.py
===================
Single-worm body tracker for TRANSMITTED-LIGHT (DIC / Nomarski / brightfield)
recordings: the footage where the worm crawls on a bacterial lawn and you want
kinematics (undulation, foraging, posterior dampening, angular velocity).

Why a separate front end. The neuron tracker finds the worm by temporal
background subtraction, which works when the animal translates across a static
arena. On these recordings the worm crawls in place while the lawn is a mesh of
thin trails, so the temporal median absorbs the worm and background subtraction
fails (measured: mean |frame - median| about 1 grey level, i.e. nothing). What
does separate the worm here is THICKNESS: the worm is the only thick coherent
body, while the lawn trails are thin. So this module segments by local contrast
plus a morphological opening that removes thin structures and keeps the worm.

Everything downstream is the SAME engine as the neuron tracker: the geodesic
longest-path midline, trimming to the worm's own (invariant) length, and the
provenance/QC philosophy of never silently inventing a measurement.

Output is LONG format, one row per frame per body segment, carrying
seg_curv_deg and head_bend_deg, which is what the kinematics analysis
(run_one_kinematics.py -> worm_kinetics.undulation_descriptors,
locomotion_summary, foraging_descriptors, posterior_dampening) consumes.

Validated on real DIC frames: worm found in 20/20, midline length CV about 10%,
area CV about 7%.
"""
import sys
import time
from pathlib import Path
import numpy as np
from scipy import ndimage as ndi
from skimage.registration import phase_cross_correlation

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "app"))
from acquisition import AcquisitionMetadata
from segmentation_review import segment_frame
from temporal_worm_geometry import (fill_adaptive_spine_gaps,
                                    stabilize_endpoints,
                                    suggest_manual_anchor_frames)

from neuron_tracker import geodesic_midline, _arclen, _point_at_arc, _compass, _mod360


def _local_std(im, k=9):
    """Local contrast. The worm has strong internal/edge contrast in DIC; flat
    agar has almost none."""
    m = ndi.uniform_filter(im, k)
    m2 = ndi.uniform_filter(im*im, k)
    return np.sqrt(np.maximum(m2-m*m, 0))


def _signed_angle(v1, v2):
    """Signed turn from v1 to v2 in degrees, positive counter-clockwise."""
    a = np.arctan2(v1[0]*v2[1]-v1[1]*v2[0], v1[0]*v2[0]+v1[1]*v2[1])
    return np.degrees(a)


class DICWormTracker:
    def __init__(self, frames_gray, fps, um_per_px, fps_source, um_per_px_source, worm_id="worm",
                 n_segments=24, contrast_pct=95.0, thickness_iter=2,
                 qc_len_tol=25.0, assay_mode="crawling",
                 exposure_ms=None, exposure_source="not_applicable",
                 dv_orientation="unknown", dv_source="unknown",
                 segmentation_config=None, strict_target_identity=False,
                 exclusion_masks=None, identity_area_bounds=None,
                 identity_length_bounds=None,registration_proxy=True,
                 adaptive_background_sampling=True,
                 ignore_border_objects=False, border_area_ratio=1.5,
                 border_penalty=12.0):
        init_started=time.perf_counter();self.timings={};self.performance_options={
            "registration_proxy":bool(registration_proxy),
            "adaptive_background_sampling":bool(adaptive_background_sampling)}
        self.acquisition = AcquisitionMetadata(
            fps=fps, fps_source=fps_source, um_per_px=um_per_px,
            um_per_px_source=um_per_px_source, exposure_ms=exposure_ms,
            exposure_source=exposure_source, dv_orientation=dv_orientation,
            dv_source=dv_source).validate()
        self.G=(frames_gray if getattr(frames_gray,"is_virtual_stack",False)
                else np.asarray(frames_gray,dtype=np.float32))
        self.T, self.H, self.W = self.G.shape
        self.fps = fps; self.um_per_px = um_per_px; self.worm_id = worm_id
        self.assay_mode = assay_mode
        self.fps_source = fps_source
        self.um_per_px_source = um_per_px_source
        self.exposure_ms = exposure_ms
        self.exposure_source = exposure_source
        self.dv_orientation = dv_orientation
        self.dv_source = dv_source
        self.segmentation_config = segmentation_config
        self.strict_target_identity = bool(strict_target_identity)
        self.exclusion_masks = exclusion_masks
        self.identity_area_bounds = identity_area_bounds
        self.identity_length_bounds = identity_length_bounds
        self.n_segments = int(n_segments)
        self.contrast_pct = float(contrast_pct)   # higher = tighter; too low leaks into the lawn
        self.thickness_iter = int(thickness_iter)
        self.qc_len_tol = float(qc_len_tol)
        self.registration_proxy=bool(registration_proxy)
        self.adaptive_background_sampling=bool(adaptive_background_sampling)
        # Probe/pick rejection: an object introduced to touch the worm (a wire
        # held by the experimenter) is bigger than the worm AND always contiguous
        # with a frame edge.  When enabled, a component that touches the frame
        # border and is larger than the worm reference is demoted so the worm is
        # preferred; the demotion is a penalty, not a hard reject, so the blob is
        # still chosen if it is the only candidate (e.g. mid-contact merges).
        self.ignore_border_objects=bool(ignore_border_objects)
        self.border_area_ratio=float(border_area_ratio)
        self.border_penalty=float(border_penalty)
        self.state = [None]*self.T
        self.len_ref = None; self.area_ref = None
        self.manual_identity_reference = False
        self.clip_starts = self._find_clip_starts()
        self.clip_start_set = set(self.clip_starts)
        self.clip_id = np.zeros(self.T, dtype=int)
        for number, start in enumerate(self.clip_starts):
            end = self.clip_starts[number+1] if number+1 < len(self.clip_starts) else self.T
            self.clip_id[start:end] = number
        phase=time.perf_counter();self.camera_shift = self._estimate_camera_shifts()
        self.timings["camera_registration_s"]=time.perf_counter()-phase
        phase=time.perf_counter();self.backgrounds = self._clip_backgrounds()
        self.timings["background_model_s"]=time.perf_counter()-phase
        self.timings["tracker_initialization_s"]=time.perf_counter()-init_started

    def _estimate_camera_shifts(self):
        """Cumulative background/camera translation within each clip.

        Shifts map each frame into its clip's first-frame coordinates.  Large or
        unreliable jumps are ignored; hard cuts have already split the clips.
        """
        shifts = np.zeros((self.T, 2), dtype=float)  # scipy order: y, x
        sampling_step=(max(1,int(np.ceil(max(self.H,self.W)/1024)))
                       if self.registration_proxy else 1)
        for start_index, start in enumerate(self.clip_starts):
            end = (self.clip_starts[start_index+1]
                   if start_index+1 < len(self.clip_starts) else self.T)
            for i in range(start+1, end):
                # Subsample the source first.  Converting a full 4K frame to
                # float merely to discard most pixels caused large temporary
                # allocations and dominated registration startup.
                previous=ndi.gaussian_filter(
                    np.asarray(self.G[i-1])[::sampling_step,::sampling_step].astype(np.float32,copy=False),2)
                current=ndi.gaussian_filter(
                    np.asarray(self.G[i])[::sampling_step,::sampling_step].astype(np.float32,copy=False),2)
                try:
                    delta, error, _ = phase_cross_correlation(
                        previous, current, upsample_factor=4,
                        normalization=None)
                    delta=np.asarray(delta,float)*sampling_step
                    if (np.all(np.isfinite(delta)) and np.linalg.norm(delta) <= 0.2*min(self.H, self.W)
                            and np.isfinite(error)):
                        shifts[i] = shifts[i-1]+delta
                    else:
                        shifts[i] = shifts[i-1]
                except Exception:
                    shifts[i] = shifts[i-1]
        return shifts

    def _find_clip_starts(self):
        """Find hard cuts without mistaking coherent camera motion for a cut.

        A biological change is local, while a camera translation changes most
        pixels but is substantially reversible by registration.  Only large
        changes that remain largely unexplained after translation alignment
        start a new clip.  This also prevents a camera move spread over several
        frames from resetting registration on every frame.
        """
        if self.T < 2:
            return [0]
        scores = []
        for i in range(1, self.T):
            a = self.G[i-1][::8, ::8]
            b = self.G[i][::8, ::8]
            scores.append(float(np.mean(np.abs(a-b))))
        scores = np.asarray(scores)
        med = float(np.median(scores))
        mad = float(np.median(np.abs(scores-med))*1.4826)
        threshold = max(med + 8*max(mad, 0.1), med*3.0, 3.0)
        starts = [0]
        for previous_index in np.where(scores > threshold)[0]:
            i = int(previous_index + 1)
            previous = ndi.gaussian_filter(self.G[i-1][::2, ::2], 2)
            current = ndi.gaussian_filter(self.G[i][::2, ::2], 2)
            raw_residual = float(np.mean(np.abs(previous-current)))
            residual_ratio = 1.0
            try:
                delta, _, _ = phase_cross_correlation(
                    previous, current, upsample_factor=2,
                    normalization=None)
                aligned = ndi.shift(
                    current, delta, order=1, mode="constant", cval=np.nan)
                aligned_residual = float(np.nanmean(np.abs(previous-aligned)))
                residual_ratio = aligned_residual/max(raw_residual, 1e-6)
            except Exception:
                pass
            # Translation must explain at least 35% of the large change.  A
            # scene reposition/cut (or an untrackably blurred transition frame)
            # is safer as a fresh clip with no inherited identity hint.
            if residual_ratio >= 0.65:
                starts.append(i)
        return sorted(set(int(x) for x in starts))

    def _clip_backgrounds(self):
        """Sampled temporal medians, used to score motion rather than define shape."""
        backgrounds = []
        for number, start in enumerate(self.clip_starts):
            end = self.clip_starts[number+1] if number+1 < len(self.clip_starts) else self.T
            per_frame=max(self.H*self.W*4,1)
            budget_count=(max(3,(256*1024**2)//per_frame)
                          if self.adaptive_background_sampling else 81)
            count = min(81,end-start,budget_count)
            idx = np.linspace(start, end-1, count, dtype=int)
            registered = [ndi.shift(self.G[i], self.camera_shift[i], order=1,
                                    mode="constant", cval=np.nan)
                          for i in idx]
            backgrounds.append(np.nanmedian(np.asarray(registered), axis=0).astype(np.float32))
        return backgrounds

    def _background_for_frame(self, i):
        return ndi.shift(
            self.backgrounds[self.clip_id[i]], -self.camera_shift[i], order=1,
            mode="constant", cval=np.nan)

    def _camera_compensated_hint(self, i, hint):
        """Map a previous-frame (x, y) hint into the current camera coordinates.

        ``camera_shift`` maps each image into the clip's first-frame coordinate
        system.  Therefore the inverse change between consecutive cumulative
        shifts predicts where the same specimen point appears in the current
        raw frame.  This is enabled only by an explicit per-range recipe.
        """
        if hint is None or i <= 0 or i in self.clip_start_set:
            return hint
        recipe = (self.segmentation_config.recipe_for_frame(i)
                  if self.segmentation_config is not None else None)
        settings = recipe if recipe is not None else self.segmentation_config
        if settings is None or not settings.camera_registration:
            return hint
        delta_y, delta_x = self.camera_shift[i] - self.camera_shift[i - 1]
        return (float(hint[0] - delta_x), float(hint[1] - delta_y))

    def _temporal_identity_prior(self, i, previous_mask):
        """Return the previous worm mask predicted in the current frame.

        The modest dilation permits real locomotion and small segmentation
        changes while making a jump to a spatially separate bacterium or worm
        impossible. Camera translation is applied first when that range opts
        into registration.
        """
        if previous_mask is None or i <= 0 or i in self.clip_start_set:
            return None
        recipe = (self.segmentation_config.recipe_for_frame(i)
                  if self.segmentation_config is not None else None)
        settings = recipe if recipe is not None else self.segmentation_config
        if settings is None or not settings.temporal_overlap:
            return None
        predicted = np.asarray(previous_mask, bool)
        if settings.camera_registration:
            delta_y, delta_x = self.camera_shift[i] - self.camera_shift[i - 1]
            predicted = ndi.shift(
                predicted.astype(np.uint8), (-delta_y, -delta_x), order=0,
                mode="constant", cval=0) > 0
        allowance = max(4, min(18, int(round(0.10*(self.len_ref or 100.0)))))
        return ndi.binary_dilation(predicted, iterations=allowance)

    # ---- detection: thickness for shape, motion/continuity for identity ----
    def _mask(self, i, hint=None, previous_mask=None):
        hint = self._camera_compensated_hint(i, hint)
        temporal_prior = self._temporal_identity_prior(i, previous_mask)
        if self.segmentation_config is None:
            lv = _local_std(self.G[i], 9)
            lo = lv > np.percentile(lv, self.contrast_pct)
        else:
            # The reviewed map defines object extent only. The raw frame remains
            # untouched and all downstream geometry is computed from this mask.
            lo = segment_frame(
                self.G[i], i, self.segmentation_config,
                reference=self._background_for_frame(i))
        if self.exclusion_masks is not None and i < len(self.exclusion_masks):
            excluded = self.exclusion_masks[i]
            if excluded is not None and np.any(excluded):
                lo &= ~ndi.binary_dilation(
                    np.asarray(excluded, bool), iterations=3)
        lo = ndi.binary_closing(lo, iterations=3)
        lo = ndi.binary_fill_holes(lo)
        # the opening keeps only structures thicker than the kernel: the worm
        # survives, the thin lawn trails do not
        if self.segmentation_config is not None:
            # A user-REVIEWED segmentation has already removed the lawn/noise, so
            # the thickness opening is no longer needed to reject trails -- and on
            # burrowing / dark-field footage the worm itself is often thin, so a
            # 7x7 opening would erase it and leave the frame with no spine (the
            # reviewed mask looks great but every frame still "needs spining").
            # Trust the reviewed mask: open only gently, and fall back to the mask
            # itself when the worm is too thin to survive even that.
            core = ndi.binary_opening(lo, structure=np.ones((3, 3)), iterations=1)
            if not core.any():
                core = lo
        else:
            core = ndi.binary_opening(lo, structure=np.ones((7, 7)), iterations=self.thickness_iter)
            if not core.any():
                return None
        # Restore only the nearby body shell around the thick core. Reconstructing
        # the entire connected local-contrast component can follow an old OP50
        # track for hundreds of pixels.
        restored = ndi.binary_dilation(core, structure=np.ones((3, 3)), iterations=5) & lo
        restored = ndi.binary_closing(restored, iterations=2)
        restored = ndi.binary_fill_holes(restored)
        lab, n = ndi.label(restored)
        if n == 0:
            return None
        motion = np.abs(self.G[i] - self._background_for_frame(i))
        finite_motion = motion[np.isfinite(motion)]
        motion_cut = np.percentile(finite_motion, 88) if finite_motion.size else np.inf
        moving = np.isfinite(motion) & (motion >= motion_cut)
        # Worm-size reference for the border-intruder cue.  Prefer the calibrated
        # area; before that is known, fall back to the tracked worm's area in the
        # previous frame so the probe can be judged from frame one of contact.
        if self.ignore_border_objects:
            if self.area_ref and self.area_ref == self.area_ref:
                worm_area_ref = float(self.area_ref)
            elif previous_mask is not None:
                worm_area_ref = float(np.asarray(previous_mask, bool).sum())
            else:
                worm_area_ref = None
        else:
            worm_area_ref = None
        best = None; best_score = -np.inf
        for k in range(1, n+1):
            if k <= 0:
                continue
            comp = (lab == k)
            cc = int((core & comp).sum())
            if cc <= 0:
                continue
            area = int(comp.sum())
            if self.identity_area_bounds is not None:
                lo_area, hi_area = self.identity_area_bounds
                if area < lo_area or area > hi_area:
                    continue
            elif self.manual_identity_reference and self.area_ref:
                # A user-traced outline is an identity calibration, not merely
                # a post-hoc QC hint. Reject fragments and large background
                # structures before either can become the next-frame hint.
                if area < 0.55*self.area_ref or area > 1.60*self.area_ref:
                    continue
            if self.strict_target_identity and self.area_ref:
                ratio = area / max(float(self.area_ref), 1.0)
                if (self.identity_area_bounds is None
                        and (ratio < 0.30 or ratio > 2.75)):
                    continue
            moving_fraction = float((moving & comp).sum()/max(area, 1))
            overlap_fraction = 0.0
            if temporal_prior is not None:
                overlap_pixels = int((temporal_prior & comp).sum())
                if overlap_pixels == 0:
                    continue
                overlap_fraction = overlap_pixels/max(
                    min(area, int(previous_mask.sum())), 1)
            cy, cx = ndi.center_of_mass(comp)
            proximity = 0.0
            if hint is not None and cx == cx:
                distance = np.hypot(cx-hint[0], cy-hint[1])
                proximity = -distance/max(self.len_ref or 100.0, 1.0)
            size_penalty = (
                3.0 * abs(np.log(area / self.area_ref))
                if self.area_ref else 0.0)
            border_penalty = 0.0
            if (worm_area_ref
                    and area > self.border_area_ratio * worm_area_ref
                    and (comp[0, :].any() or comp[-1, :].any()
                         or comp[:, 0].any() or comp[:, -1].any())):
                # Big + touches a frame edge = the probe/pick, not the worm.
                border_penalty = self.border_penalty
            score = (np.log1p(cc) + 2.5*moving_fraction + 2.0*proximity
                     + 8.0*overlap_fraction
                     - size_penalty - border_penalty)
            if score > best_score:
                best_score = score; best = comp
        return best

    # ---- geometry ----
    def _resample(self, path):
        cum = _arclen(path)
        s = np.linspace(0, cum[-1], self.n_segments+1)
        return np.array([_point_at_arc(path, cum, si) for si in s])

    def _segments(self, path):
        """Resample the midline into n_segments+1 equally spaced points, then
        return per-segment direction vectors and the signed curvature at each
        interior segment."""
        cum = _arclen(path)
        s = np.linspace(0, cum[-1], self.n_segments+1)
        pts = np.array([_point_at_arc(path, cum, si) for si in s])
        vecs = np.diff(pts, axis=0)
        curv = np.full(self.n_segments, np.nan)
        for k in range(1, self.n_segments):
            curv[k] = _signed_angle(vecs[k-1], vecs[k])
        return pts, vecs, curv

    def _geometry(self, i, mask, prev_head, prev_pts=None, forced_head=None):
        st = dict(frame=i, path=None, pts=None, curv=None, length=np.nan,
                  area=np.nan, head=(np.nan, np.nan), tail=(np.nan, np.nan),
                  head_bend=np.nan, head_angle=np.nan, centroid=(np.nan, np.nan),
                  provenance="measured", needs_help=0)
        if mask is None:
            st["provenance"] = "help"; st["needs_help"] = 1
            return st
        full, flen = geodesic_midline(mask)
        st["area"] = float(mask.sum())
        if full is None or flen <= 0:
            st["provenance"] = "help"; st["needs_help"] = 1
            return st
        # Polarity. Deciding the head from one endpoint's proximity is fragile: a
        # single mangled frame flips it and the error then propagates forever. So
        # match the WHOLE resampled midline against the previous frame's, forward
        # versus reversed, and keep the orientation that fits the body better.
        # Frame 1 is anchored by the user's head click.
        if forced_head is not None:
            d0 = np.hypot(full[0, 0]-forced_head[0], full[0, 1]-forced_head[1])
            d1 = np.hypot(full[-1, 0]-forced_head[0], full[-1, 1]-forced_head[1])
            if d1 < d0:
                full = full[::-1]
        elif prev_pts is not None:
            fwd = self._resample(full)
            rev = self._resample(full[::-1])
            d_f = np.nanmean(np.hypot(fwd[:, 0]-prev_pts[:, 0], fwd[:, 1]-prev_pts[:, 1]))
            d_r = np.nanmean(np.hypot(rev[:, 0]-prev_pts[:, 0], rev[:, 1]-prev_pts[:, 1]))
            if d_r < d_f:
                full = full[::-1]
        elif prev_head is not None:
            d0 = np.hypot(full[0, 0]-prev_head[0], full[0, 1]-prev_head[1])
            d1 = np.hypot(full[-1, 0]-prev_head[0], full[-1, 1]-prev_head[1])
            if d1 < d0:
                full = full[::-1]
        # trim to the worm's own length from the head (incompressibility), so a
        # lawn trail fused to the body cannot lengthen the spine
        cum = _arclen(full)
        if self.len_ref:
            sel = cum <= self.len_ref
            if sel.sum() >= 2:
                full = full[sel]
        pts, vecs, curv = self._segments(full)
        st["path"] = full; st["pts"] = pts; st["curv"] = curv
        distance = ndi.distance_transform_edt(mask)
        sample_x = np.clip(np.rint(pts[:, 0]).astype(int), 0, self.W - 1)
        sample_y = np.clip(np.rint(pts[:, 1]).astype(int), 0, self.H - 1)
        st["seg_widths"] = 2.0 * distance[sample_y, sample_x]
        st["length"] = float(_arclen(full)[-1])
        st["head"] = (float(full[0, 0]), float(full[0, 1]))
        st["tail"] = (float(full[-1, 0]), float(full[-1, 1]))
        cy, cx = ndi.center_of_mass(mask)
        st["centroid"] = (float(cx), float(cy))
        # head bend: the turn of the most anterior segment away from the axis of
        # the anterior body behind it. This is the foraging head swing.
        n_head, n_body = 2, 6
        if len(vecs) > n_head+n_body:
            hv = vecs[:n_head].sum(axis=0)
            bv = vecs[n_head:n_head+n_body].sum(axis=0)
            st["head_bend"] = float(_signed_angle(bv, hv))
            st["head_angle"] = float(_compass(hv[0], hv[1]))
        return st

    # ---- full pass ----
    def track_all(self, head_seed, outline_mask=None):
        phase=time.perf_counter()
        """head_seed = (x, y) clicked on the HEAD in frame 1 (sets polarity).
        outline_mask = optional hand outline of the worm in frame 1; if given it
        sets the reference length and area used for trimming and QC.

        Two passes when there is no hand outline: the first establishes the
        worm's own length (its invariant), the second re-runs the geometry with
        the midline trimmed to that length, so a lawn trail fused to the body
        cannot lengthen the spine or move the apparent head."""
        # Establish manual identity bounds before segmenting any automatic
        # frame. Previously all masks were selected first, so the user's traced
        # area could not prevent a background component from becoming the
        # tracking hint.
        if outline_mask is not None and outline_mask.any():
            p0, l0 = geodesic_midline(outline_mask)
            if p0 is not None and l0 > 0:
                self.len_ref = float(l0); self.area_ref = float(outline_mask.sum())
                self.manual_identity_reference = True
        masks = []
        hint = tuple(head_seed)
        previous_mask = None
        for i in range(self.T):
            if i in self.clip_start_set and i != 0:
                hint = None
                previous_mask = None
            mask = self._mask(i, hint=hint, previous_mask=previous_mask)
            masks.append(mask)
            if mask is not None:
                cy, cx = ndi.center_of_mass(mask)
                hint = (float(cx), float(cy))
                previous_mask = mask
        if self.len_ref is None:
            # pass 1: untrimmed, only to learn the length. The median is robust to
            # the minority of frames where the mask leaks into the lawn.
            self._run_pass(masks, head_seed)
            Ls = [s["length"] for s in self.state if s["length"] == s["length"]]
            As = [s["area"] for s in self.state if s["area"] == s["area"]]
            self.len_ref = float(np.median(Ls)) if Ls else np.nan
            self.area_ref = float(np.median(As)) if As else np.nan
        # pass 2 (or the only pass, if the outline gave us the reference)
        self._run_pass(masks, head_seed)
        self._qc()
        self._temporal_reconstruct()
        self.timings["tracking_and_reconstruction_s"]=time.perf_counter()-phase
        return self.state

    def _temporal_reconstruct(self, variable_length=None, bounds=None):
        """RGBCaMP-style two-sided repair, with raw geometry retained.

        The ordinary kinematics tracker uses conserved length.  pBoc supplies a
        variable-length callback so contraction is preserved rather than erased.
        """
        offset = 0
        work = self.state
        local_variable_length = variable_length
        if bounds is not None:
            left, right = sorted((int(bounds[0]), int(bounds[1])))
            left = max(0, left); right = min(self.T-1, right)
            offset = left
            # The slice is deliberate: gap filling and endpoint stabilization
            # cannot see or mutate any frame outside the user's edit interval.
            work = self.state[left:right+1]
            if variable_length is not None:
                local_variable_length = lambda frame, fraction, ls, rs: variable_length(
                    frame + offset, fraction, ls, rs)
        filled_local = fill_adaptive_spine_gaps(
            work, target_length=self.len_ref,
            variable_length=local_variable_length)
        filled = [i + offset for i in filled_local]
        for local_i, i in zip(filled_local, filled):
            state = self.state[i]
            pts, vecs, curv = self._segments(state["pts"])
            state["pts"], state["path"], state["curv"] = pts, pts.copy(), curv
            state["length"] = float(_arclen(pts)[-1])
            state["head"], state["tail"] = tuple(pts[0]), tuple(pts[-1])
            state["head_bend"] = np.nan
            state["head_angle"] = float(_compass(vecs[0, 0], vecs[0, 1])) if len(vecs) else np.nan
            left = state["temporal_left_frame"] + offset
            right = state["temporal_right_frame"] + offset
            state["temporal_left_frame"] = left
            state["temporal_right_frame"] = right
            lw = self.state[left].get("seg_widths")
            rw = self.state[right].get("seg_widths")
            if lw is not None and rw is not None:
                fraction = (i-left)/(right-left)
                state["seg_widths"] = (1-fraction)*np.asarray(lw)+fraction*np.asarray(rw)
        stabilize_endpoints(work)
        self.suggested_manual_anchors = suggest_manual_anchor_frames(self.state)
        return filled

    def next_suggested_anchor(self, current=-1):
        """Return the next uncertainty-halving manual anchor, cyclically."""
        anchors = suggest_manual_anchor_frames(self.state)
        self.suggested_manual_anchors = anchors
        after = [frame for frame in anchors if frame > current]
        return after[0] if after else (anchors[0] if anchors else None)

    def reanalyze_interval(self, start, end):
        """Invalidate a user-selected interval and reconstruct it from its flanks.

        Geometry outside the inclusive interval is never changed. If the two
        trusted boundaries cannot support reconstruction, the shared engine
        proposes the minimum-work midpoint anchor instead.
        """
        start, end = sorted((int(start), int(end)))
        start = max(0, start); end = min(self.T-1, end)
        if end <= start:
            return []
        self._prepare_bounded_reconstruction(start, end)
        return self._temporal_reconstruct(bounds=(start, end))

    def _prepare_bounded_reconstruction(self, start, end):
        """Invalidate non-manual interior geometry while retaining every anchor.

        This is repeated whenever the user adds an internal ``f`` anchor. The
        previous interpolation must not masquerade as a trusted observation or
        it will prevent the new anchor from influencing neighboring frames.
        """
        start, end = sorted((max(0, int(start)), min(self.T-1, int(end))))
        # b and e are trusted boundary anchors. Only frames strictly between
        # them are eligible for reconstruction.
        for frame in (start, end):
            state = self.state[frame]
            if state and state.get("pts") is not None:
                state["needs_help"] = 0
                state["interval_boundary_anchor"] = 1
        for frame in range(start+1, end):
            state = self.state[frame]
            if not state:
                continue
            if state.get("provenance") == "manual":
                state["needs_help"] = 0
                continue
            state.setdefault("raw_pts", None if state.get("pts") is None
                             else np.asarray(state["pts"], float).copy())
            state.setdefault("raw_path", state.get("path"))
            state.setdefault("raw_length", state.get("length", np.nan))
            state["needs_help"] = 1
            state["provenance"] = "user_flagged_interval"
            state["user_flagged_interval"] = 1

    def _run_pass(self, masks, head_seed):
        prev_head = tuple(head_seed); prev_pts = None; gap = 1
        for i in range(self.T):
            clip_restart = i in self.clip_start_set and i != 0
            if clip_restart:
                prev_head = None
                prev_pts = None
                gap = 1
            st = self._geometry(i, masks[i], prev_head, prev_pts)
            st["clip_start"] = 1 if clip_restart else 0
            # Body-shape continuity. At these frame rates a worm cannot re-shape
            # between frames, so a midline that jumps is a segmentation failure,
            # not behaviour. This is what catches a mangled skeleton that has a
            # plausible length and area but loops back on itself.
            shift = np.nan
            if prev_pts is not None and st["pts"] is not None:
                shift = float(np.nanmean(np.hypot(st["pts"][:, 0]-prev_pts[:, 0],
                                                  st["pts"][:, 1]-prev_pts[:, 1])))
            st["shape_shift"] = shift
            tol = 0.15*(self.len_ref or 1e9)*np.sqrt(max(1, gap))
            good = (st["path"] is not None and st["length"] == st["length"]
                    and (not self.len_ref
                         or abs(st["length"]-self.len_ref) <= 0.25*self.len_ref)
                    and (shift != shift or shift <= tol))
            if good:
                prev_head = st["head"]; prev_pts = st["pts"]; gap = 1
            else:
                gap += 1
            self.state[i] = st

    def run_pass_from_anchor(self, masks, head_seed, anchor_frame=0):
        """Track away from a trusted frame in both temporal directions."""
        anchor_frame = int(np.clip(anchor_frame, 0, self.T-1))
        anchor = self._geometry(
            anchor_frame, masks[anchor_frame], None, None,
            forced_head=tuple(head_seed))
        anchor["clip_start"] = 0
        self.state[anchor_frame] = anchor
        for direction in (1, -1):
            prev_head, prev_pts = anchor["head"], anchor["pts"]
            gap = 1
            frames = (range(anchor_frame+1, self.T) if direction > 0
                      else range(anchor_frame-1, -1, -1))
            for i in frames:
                st = self._geometry(i, masks[i], prev_head, prev_pts)
                st["clip_start"] = 0
                shift = np.nan
                if prev_pts is not None and st["pts"] is not None:
                    shift = float(np.nanmean(np.linalg.norm(st["pts"]-prev_pts, axis=1)))
                st["shape_shift"] = shift
                tolerance = 0.15*(self.len_ref or 1e9)*np.sqrt(max(1, gap))
                good = (st["path"] is not None and np.isfinite(st["length"])
                        and (not self.len_ref or
                             abs(st["length"]-self.len_ref) <= 0.25*self.len_ref)
                        and (not np.isfinite(shift) or shift <= tolerance))
                if good:
                    prev_head, prev_pts, gap = st["head"], st["pts"], 1
                else:
                    gap += 1
                self.state[i] = st

    def _qc(self):
        for s in self.state:
            if s is None or s.get("provenance") in {
                    "manual", "inferred_between_neighbors",
                    "measured_endpoint_stabilized"}:
                continue
            L = s["length"]; A = s["area"]
            len_dev = 100*abs(L-self.len_ref)/self.len_ref if (L == L and self.len_ref) else np.nan
            s["len_dev"] = len_dev
            shift = s.get("shape_shift", np.nan)
            bad = (s["path"] is None) \
                or bool(s.get("clip_start", 0)) \
                or (len_dev == len_dev and len_dev > self.qc_len_tol) \
                or (A == A and self.area_ref and A < 0.4*self.area_ref) \
                or (shift == shift and self.len_ref and shift > 0.15*self.len_ref)
            if self.manual_identity_reference and self.area_ref:
                bad = bad or not (np.isfinite(A)
                                  and 0.55*self.area_ref <= A <= 1.60*self.area_ref)
            if self.strict_target_identity and self.identity_length_bounds is not None:
                low, high = self.identity_length_bounds
                bad = bad or not (np.isfinite(L) and low <= L <= high)
            if self.strict_target_identity and self.identity_area_bounds is not None:
                low, high = self.identity_area_bounds
                bad = bad or not (np.isfinite(A) and low <= A <= high)
            s["provenance"] = "help" if bad else "measured"
            s["needs_help"] = 1 if bad else 0

    def recompute_frame(self, i, head=None, outline_verts=None,
                        reconstruct_bounds=None):
        """Fix one frame by hand: head=(x,y) re-seeds polarity, outline_verts
        replaces the mask."""
        from skimage.draw import polygon2mask
        mask = None
        if outline_verts is not None and len(outline_verts) >= 3:
            mask = polygon2mask((self.H, self.W), np.array([(y, x) for (x, y) in outline_verts]))
        else:
            mask = self._mask(i)
        prev_head = head if head is not None else (
            self.state[i-1]["head"] if i > 0 and self.state[i-1] else None)
        prev_pts = None if head is not None else (
            self.state[i-1]["pts"] if (i > 0 and self.state[i-1]) else None)
        st = self._geometry(i, mask, prev_head, prev_pts, forced_head=head)
        st["clip_start"] = self.state[i].get("clip_start", 0) if self.state[i] else 0
        st["provenance"] = "manual"; st["needs_help"] = 0
        self.state[i] = st
        self._qc()
        if reconstruct_bounds is not None:
            self._prepare_bounded_reconstruction(*reconstruct_bounds)
        self._temporal_reconstruct(bounds=reconstruct_bounds)
        return st

    def retrack_from(self, i0, stop_at_next_clip=True):
        prev_head = self.state[i0]["head"] if self.state[i0] else None
        prev_pts = self.state[i0]["pts"] if self.state[i0] else None
        previous_mask = self._mask(
            i0, hint=self.state[i0].get("centroid") if self.state[i0] else None)
        for i in range(max(1, i0+1), self.T):
            if i in self.clip_start_set:
                if stop_at_next_clip:
                    break
                previous_mask = None
                prev_head = None
                prev_pts = None
            hint = self.state[i-1]["centroid"] if self.state[i-1] else prev_head
            if i in self.clip_start_set:
                hint = None
            mask = self._mask(
                i, hint=hint, previous_mask=previous_mask)
            st = self._geometry(i, mask, prev_head, prev_pts)
            st["clip_start"] = 0
            good = (st["path"] is not None and st["length"] == st["length"]
                    and (not self.len_ref
                         or abs(st["length"]-self.len_ref) <= 0.25*self.len_ref))
            if good:
                prev_head = st["head"]; prev_pts = st["pts"]
            if mask is not None:
                previous_mask = mask
            self.state[i] = st
        self._qc()
        self._temporal_reconstruct()

    # ---- export: LONG format for the kinematics analysis ----
    def export_rows(self):
        rows = []
        prev_c = None; prev_ha = None
        for i, s in enumerate(self.state):
            t = i/self.fps
            # whole-frame quantities (repeat across segments, as the analysis expects)
            cx, cy = s["centroid"]
            speed = np.nan; move_ang = np.nan
            if prev_c is not None and cx == cx and prev_c[0] == prev_c[0]:
                dx, dy = cx-prev_c[0], cy-prev_c[1]
                speed = float(np.hypot(dx, dy)*self.fps)
                if np.hypot(dx, dy) >= 1:
                    move_ang = _compass(dx, dy)
            ang_vel = np.nan
            if prev_ha is not None and s["head_angle"] == s["head_angle"]:
                d = _mod360(s["head_angle"]-prev_ha)
                if d > 180:
                    d -= 360
                ang_vel = float(d*self.fps)
            for k in range(self.n_segments):
                curv = s["curv"][k] if s["curv"] is not None else np.nan
                widths = s.get("seg_widths")
                width = widths[k] if widths is not None else np.nan
                px, py = (s["pts"][k] if s["pts"] is not None else (np.nan, np.nan))
                rows.append(dict(
                    worm_id=self.worm_id, frame=i+1, time_s=t, segment=k,
                    seg_curv_deg=curv, seg_width_px=width, seg_x=px, seg_y=py,
                    head_bend_deg=s["head_bend"], head_angle_deg=s["head_angle"],
                    head_x=s["head"][0], head_y=s["head"][1],
                    tail_x=s["tail"][0], tail_y=s["tail"][1],
                    centroid_x=cx, centroid_y=cy,
                    body_length_px=s["length"], body_area_px=s["area"],
                    centroid_speed_px_s=speed, move_angle_deg=move_ang,
                    head_angular_velocity_deg_s=ang_vel,
                    **self.acquisition.as_columns(),
                    assay_mode=self.assay_mode,
                    body_length_role={
                        "crawling": "diagnostic",
                        "swimming": "qc",
                        "burrowing": "diagnostic",
                    }.get(self.assay_mode, "diagnostic"),
                    length_dev_pct=s.get("len_dev", np.nan), shape_shift_px=s.get("shape_shift", np.nan),
                    geometry_inferred=int(s.get("geometry_inferred", 0)),
                    endpoint_stabilized=int(s.get("endpoint_stabilized", 0)),
                    temporal_left_frame=s.get("temporal_left_frame", np.nan),
                    temporal_right_frame=s.get("temporal_right_frame", np.nan),
                    flank_translation_body_lengths=s.get(
                        "flank_translation_body_lengths", np.nan),
                    flank_shape_disagreement_body_lengths=s.get(
                        "flank_shape_disagreement_body_lengths", np.nan),
                    suggested_manual_anchor=int(s.get("suggested_manual_anchor", 0)),
                    reconstruction_reason=s.get("reconstruction_reason", ""),
                    clip_id=int(self.clip_id[i]), clip_start=int(s.get("clip_start", 0)),
                    camera_shift_x_px=float(-self.camera_shift[i, 1]),
                    camera_shift_y_px=float(-self.camera_shift[i, 0]),
                    provenance=s["provenance"], needs_help=s["needs_help"]))
            if cx == cx:
                prev_c = (cx, cy)
            if s["head_angle"] == s["head_angle"]:
                prev_ha = s["head_angle"]
        return rows

    @property
    def reference(self):
        return dict(length_px=self.len_ref, area_px=self.area_ref,
                    n_segments=self.n_segments, clip_starts=self.clip_starts)
