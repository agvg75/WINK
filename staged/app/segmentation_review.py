"""Supervised, preview-first spatial and temporal segmentation maps.

This module may define object extent only. It never returns corrected pixel
intensities and must not be used for fluorescence photometry.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import simpledialog

import cv2
import numpy as np

SCHEMA_VERSION = 2
CONFIG_NAME = "nike_segmentation_review.json"
GEOMETRY_TOOLS = {
    "track_one_worm", "neuron_tracker_geometry", "kinematics_extractor", "population_swimming",
    "population_basal_slowing", "population_orientation",
    "defecation_cycle", "endpoint_egg_counting", "dynamic_egg_laying",
}
PHOTOMETRY_EXCLUSIONS = {
    "rgbcamp", "single_channel_gcamp", "pharyngeal_pumping",
    "neuron_tracker", "myocyte_morphometry",
    "nonstriated_muscle_degeneration",
}


@dataclass
class SpaceTimePatch:
    polygon_xy: list[list[float]]
    frame_start: int
    frame_end: int
    threshold: float
    temporal_blend_frames: int = 4


@dataclass
class FrameRangeRecipe:
    """One reviewed segmentation recipe for an inclusive source-frame range."""
    frame_start: int
    frame_end: int
    mode: str = "global"
    feature: str = "gray"
    polarity: str = "dark"
    threshold: float = 144.0
    threshold_low: float = 0.0
    threshold_high: float = 144.0
    close_iterations: int = 0
    fill_holes: bool = False
    min_object_area: int = 0
    temporal_overlap: bool = False
    camera_registration: bool = False

    def validate(self):
        self.frame_start = int(self.frame_start)
        self.frame_end = int(self.frame_end)
        if self.frame_start < 0 or self.frame_end < self.frame_start:
            raise ValueError("Invalid segmentation frame range.")
        if self.mode not in {"global", "local_adaptive", "space_time"}:
            raise ValueError("Unknown segmentation mode in frame range.")
        if self.feature not in {"gray", "local_contrast", "difference"}:
            raise ValueError("Unknown segmentation feature in frame range.")
        if self.polarity not in {"bright", "dark", "band"}:
            raise ValueError("Range polarity must be bright, dark, or band.")
        self.threshold_low = float(np.clip(self.threshold_low, 0, 255))
        self.threshold_high = float(np.clip(self.threshold_high, 0, 255))
        if self.threshold_high < self.threshold_low:
            self.threshold_low, self.threshold_high = (
                self.threshold_high, self.threshold_low)
        self.close_iterations = max(0, int(self.close_iterations))
        self.min_object_area = max(0, int(self.min_object_area))
        return self


@dataclass
class SegmentationConfig:
    mode: str = "local_adaptive"
    threshold: float = 128.0
    polarity: str = "bright"
    adaptive_block_size: int = 31
    adaptive_c: float = 4.0
    feature: str = "gray"
    threshold_low: float = 0.0
    threshold_high: float = 255.0
    close_iterations: int = 0
    fill_holes: bool = False
    min_object_area: int = 0
    temporal_overlap: bool = False
    camera_registration: bool = False
    patches: list[SpaceTimePatch] = field(default_factory=list)
    ranges: list[FrameRangeRecipe] = field(default_factory=list)
    target_tools: list[str] = field(default_factory=lambda: sorted(GEOMETRY_TOOLS))
    accepted: bool = False
    locked: bool = False
    blinding_acknowledged: bool = False
    source: str = ""

    def validate(self):
        if self.mode not in {"global", "local_adaptive", "space_time"}:
            raise ValueError("Unknown segmentation mode.")
        if self.polarity not in {"bright", "dark"}:
            raise ValueError("Polarity must be bright or dark.")
        if self.feature not in {"gray", "local_contrast", "difference"}:
            raise ValueError("Unknown segmentation feature.")
        self.threshold = float(np.clip(self.threshold, 0, 255))
        self.threshold_low = float(np.clip(self.threshold_low, 0, 255))
        self.threshold_high = float(np.clip(self.threshold_high, 0, 255))
        if self.threshold_high < self.threshold_low:
            self.threshold_low, self.threshold_high = (
                self.threshold_high, self.threshold_low)
        self.close_iterations = max(0, int(self.close_iterations))
        self.min_object_area = max(0, int(self.min_object_area))
        if self.adaptive_block_size < 3:
            raise ValueError("Adaptive block size is too small.")
        if self.adaptive_block_size % 2 == 0:
            self.adaptive_block_size += 1
        forbidden = PHOTOMETRY_EXCLUSIONS.intersection(self.target_tools)
        if forbidden:
            raise ValueError(
                "Photometry firewall: segmentation maps cannot target " +
                ", ".join(sorted(forbidden)))
        self.ranges = [item.validate() for item in self.ranges]
        ordered = sorted(self.ranges, key=lambda item: (item.frame_start, item.frame_end))
        for previous, current in zip(ordered, ordered[1:]):
            if current.frame_start <= previous.frame_end:
                raise ValueError(
                    f"Segmentation frame ranges overlap: "
                    f"{previous.frame_start}-{previous.frame_end} and "
                    f"{current.frame_start}-{current.frame_end}.")
        self.ranges = ordered
        return self

    def to_dict(self):
        data = asdict(self)
        data["schema_version"] = SCHEMA_VERSION
        data["workflow"] = "set-lock-apply-record"
        data["intensity_firewall"] = (
            "mask only; all reported intensity must use raw pixels")
        return data

    def save(self, path):
        self.validate()
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        data.pop("schema_version", None)
        data.pop("workflow", None)
        data.pop("intensity_firewall", None)
        data["patches"] = [SpaceTimePatch(**item)
                           for item in data.get("patches", [])]
        data["ranges"] = [FrameRangeRecipe(**item)
                          for item in data.get("ranges", [])]
        return cls(**data).validate()

    def recipe_for_frame(self, frame_index):
        for recipe in self.ranges:
            if recipe.frame_start <= frame_index <= recipe.frame_end:
                return recipe
        return None


def _gray8(frame):
    array = np.asarray(frame)
    if array.ndim == 3:
        array = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    array = array.astype(np.float32)
    lo, hi = np.percentile(array, (0.2, 99.8))
    return np.uint8(np.clip((array - lo) * 255 / max(hi - lo, 1e-6), 0, 255))


def _feature(frame, name, reference=None):
    gray = _gray8(frame)
    if name == "gray":
        return gray
    if name == "difference":
        if reference is None:
            raise ValueError("Difference segmentation requires a reference frame.")
        return cv2.absdiff(gray, _gray8(reference))
    mean = cv2.blur(gray.astype(np.float32), (9, 9))
    mean2 = cv2.blur(gray.astype(np.float32) ** 2, (9, 9))
    local = np.sqrt(np.maximum(mean2 - mean ** 2, 0))
    return np.uint8(np.clip(
        local * 255 / max(float(np.percentile(local, 99.5)), 1e-6), 0, 255))


def _temporal_weight(frame_index, patch):
    blend = max(0, int(patch.temporal_blend_frames))
    if patch.frame_start <= frame_index <= patch.frame_end:
        return 1.0
    if blend and patch.frame_start - blend <= frame_index < patch.frame_start:
        return (frame_index - (patch.frame_start - blend)) / blend
    if blend and patch.frame_end < frame_index <= patch.frame_end + blend:
        return ((patch.frame_end + blend) - frame_index) / blend
    return 0.0


def effective_threshold_map(shape, frame_index, config, base_threshold=None):
    base_value = (float(config.threshold) if base_threshold is None
                  else float(base_threshold))
    base = np.full(shape, base_value, np.float32)
    numerator = base.copy()
    denominator = np.ones(shape, np.float32)
    yy, xx = np.indices(shape)
    for patch in config.patches:
        tw = _temporal_weight(frame_index, patch)
        if tw <= 0 or len(patch.polygon_xy) < 3:
            continue
        polygon = np.rint(np.asarray(patch.polygon_xy)).astype(np.int32)
        mask = np.zeros(shape, np.uint8)
        cv2.fillPoly(mask, [polygon], 1)
        center = np.mean(polygon, axis=0)
        scale = max(np.ptp(polygon[:, 0]), np.ptp(polygon[:, 1]), 1)
        spatial = np.exp(-(
            (xx - center[0]) ** 2 + (yy - center[1]) ** 2) /
            (2 * (0.6 * scale) ** 2)).astype(np.float32)
        spatial = np.maximum(spatial, mask.astype(np.float32))
        weight = tw * spatial
        numerator += weight * float(patch.threshold)
        denominator += weight
    return numerator / denominator


def segment_frame(frame, frame_index, config, reference=None):
    """Return a mask only. Raw/corrected intensities are intentionally absent."""
    config.validate()
    if not config.accepted or not config.locked:
        raise ValueError(
            "Segmentation map has not completed preview, accept, and lock.")
    recipe = config.recipe_for_frame(frame_index)
    mode = recipe.mode if recipe else config.mode
    feature_name = recipe.feature if recipe else config.feature
    polarity = recipe.polarity if recipe else config.polarity
    feature = _feature(frame, feature_name, reference)
    invert = polarity == "dark"
    if mode == "local_adaptive":
        method = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
        mask = cv2.adaptiveThreshold(
            feature, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, method,
            config.adaptive_block_size, config.adaptive_c) > 0
    elif recipe and polarity == "band":
        mask = ((feature >= recipe.threshold_low)
                & (feature <= recipe.threshold_high))
    else:
        base_threshold = float(recipe.threshold if recipe else config.threshold)
        threshold = (
            effective_threshold_map(
                feature.shape, frame_index, config,
                base_threshold=base_threshold)
            if mode == "space_time" else base_threshold)
        mask = (feature <= threshold) if invert else (feature >= threshold)
    cleanup = recipe if recipe else config
    if cleanup:
        if cleanup.close_iterations:
            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.morphologyEx(
                np.uint8(mask), cv2.MORPH_CLOSE, kernel,
                iterations=cleanup.close_iterations) > 0
        if cleanup.fill_holes:
            flood = np.uint8(mask) * 255
            padded = cv2.copyMakeBorder(flood, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
            filled = padded.copy()
            cv2.floodFill(filled, None, (0, 0), 255)
            holes = cv2.bitwise_not(filled)[1:-1, 1:-1]
            mask = (flood | holes) > 0
        if cleanup.min_object_area:
            count, labels, stats, _ = cv2.connectedComponentsWithStats(
                np.uint8(mask), connectivity=8)
            keep = np.zeros_like(mask, dtype=bool)
            for label in range(1, count):
                if stats[label, cv2.CC_STAT_AREA] >= cleanup.min_object_area:
                    keep |= labels == label
            mask = keep
    return np.asarray(mask, dtype=bool)


def continuity_acceptance(lengths, seam_frames, tolerance_fraction=0.15):
    lengths = np.asarray(lengths, dtype=float)
    failures = []
    for seam in seam_frames:
        if not (1 <= seam < len(lengths)):
            continue
        before, after = lengths[seam - 1], lengths[seam]
        scale = np.nanmedian(lengths[max(0, seam - 5):seam + 5])
        if (np.isfinite(before) and np.isfinite(after) and np.isfinite(scale)
                and scale > 0 and abs(after - before) / scale > tolerance_fraction):
            failures.append(int(seam))
    return {"passed": not failures, "failed_seams": failures,
            "tolerance_fraction": float(tolerance_fraction)}


def find_accepted_config(source, tool_name):
    source = Path(source)
    path = (source if source.is_dir() else source.parent) / CONFIG_NAME
    if not path.is_file():
        return None
    config = SegmentationConfig.load(path)
    if not (config.accepted and config.locked and tool_name in config.target_tools):
        return None
    return config


def scaled_config(config, spatial_scale):
    """Copy a reviewed map into a downsampled analysis coordinate system."""
    if config is None:
        return None
    data = config.to_dict()
    data.pop("schema_version", None)
    data.pop("workflow", None)
    data.pop("intensity_firewall", None)
    scale = float(spatial_scale)
    data["patches"] = [
        SpaceTimePatch(
            polygon_xy=[[x * scale, y * scale] for x, y in patch.polygon_xy],
            frame_start=patch.frame_start, frame_end=patch.frame_end,
            threshold=patch.threshold,
            temporal_blend_frames=patch.temporal_blend_frames)
        for patch in config.patches]
    data["ranges"] = [FrameRangeRecipe(**asdict(recipe))
                      for recipe in config.ranges]
    return SegmentationConfig(**data).validate()


class SegmentationReviewWindow(tk.Toplevel):
    """Preview-first, frame-range segmentation recipe workbench."""
    def __init__(self, parent, frames, source="", save_dir=None,
                 tool_name="track_one_worm", frame_numbers=None,
                 frame_loader=None, source_frame_count=None):
        super().__init__(parent)
        self.title("WINK supervised segmentation review")
        self.frames = frames
        self.frame_numbers = (
            list(range(len(frames))) if frame_numbers is None
            else [int(value) for value in frame_numbers])
        if len(self.frame_numbers) != len(self.frames):
            raise ValueError("frame_numbers must match the preview frames.")
        self.source = source
        self.frame_loader = frame_loader
        self.source_frame_count = int(
            source_frame_count if source_frame_count is not None
            else (max(self.frame_numbers) + 1 if self.frame_numbers else 0))
        self.save_dir = Path(save_dir or source or ".")
        if tool_name not in GEOMETRY_TOOLS:
            raise ValueError(f"Segmentation review is not permitted for {tool_name}.")
        self.tool_name = tool_name
        # This is an opt-in workbench default only. It does not replace any
        # assay's native detector (especially the Fiji RGBCaMP workflow).
        default_feature = "gray"
        self.config = SegmentationConfig(
            source=str(source), target_tools=[tool_name],
            mode="global", threshold=144, threshold_low=0,
            threshold_high=144, polarity="dark", feature=default_feature,
            close_iterations=2, fill_holes=True,
            temporal_overlap=True, camera_registration=True)
        existing_path = self.save_dir / CONFIG_NAME
        if existing_path.exists():
            try:
                existing = SegmentationConfig.load(existing_path)
                if tool_name in existing.target_tools:
                    self.config = existing
            except Exception:
                # A malformed/legacy file must not prevent a fresh review.
                pass
        self.good = tk.IntVar(value=0)
        self.bad = tk.IntVar(value=max(0, len(frames) - 1))
        self.threshold = tk.DoubleVar(value=self.config.threshold or 144)
        self.threshold_low = tk.DoubleVar(value=self.config.threshold_low)
        self.threshold_high = tk.DoubleVar(value=self.config.threshold_high)
        self.mode = tk.StringVar(value=self.config.mode)
        self.polarity = tk.StringVar(value=self.config.polarity)
        self.feature = tk.StringVar(value=self.config.feature)
        self.close_iterations = tk.IntVar(
            value=self.config.close_iterations)
        self.fill_holes = tk.BooleanVar(value=self.config.fill_holes)
        self.min_object_area = tk.IntVar(value=self.config.min_object_area)
        self.temporal_overlap = tk.BooleanVar(
            value=self.config.temporal_overlap)
        self.camera_registration = tk.BooleanVar(
            value=self.config.camera_registration)
        self.range_start = None
        self.range_end = None
        self.playing = False
        self.reference = np.median(np.asarray(frames, dtype=np.float32), axis=0)
        self.status = tk.StringVar(value=(
            "Preview only. No analysis parameter has changed. "
            "Set, inspect, then explicitly Accept + Lock."))
        self._images = []
        self._build()
        self._refresh_range_tree()
        self._draw()
        self.bind("<Left>", lambda _event: self._step_source(-1))
        self.bind("<Right>", lambda _event: self._step_source(1))

    def _build(self):
        top = ttk.Frame(self); top.pack(fill="x", padx=8, pady=8)
        ttk.Label(top, text="Mode").pack(side="left")
        mode_box = ttk.Combobox(
            top, textvariable=self.mode, state="readonly",
            values=["local_adaptive", "global", "space_time"], width=18)
        mode_box.pack(side="left", padx=4)
        ttk.Label(top, text="Low (bright/band)").pack(side="left", padx=(8, 0))
        self.low_scale = tk.Scale(
            top, from_=0, to=255, orient="horizontal",
            variable=self.threshold_low,
            command=lambda _=None: self.after_idle(self._draw), length=110)
        self.low_scale.pack(side="left")
        ttk.Label(top, text="High (dark/band)").pack(side="left")
        self.high_scale = tk.Scale(
            top, from_=0, to=255, orient="horizontal",
            variable=self.threshold_high,
            command=lambda _=None: self.after_idle(self._draw), length=110)
        self.high_scale.pack(side="left")
        polarity_box = ttk.Combobox(
            top, textvariable=self.polarity, state="readonly",
            values=["bright", "dark", "band"], width=8)
        polarity_box.pack(side="left")
        ttk.Label(top, text="Feature").pack(side="left", padx=(8, 0))
        feature_box = ttk.Combobox(
            top, textvariable=self.feature, state="readonly",
            values=["gray", "local_contrast", "difference"], width=14)
        feature_box.pack(side="left")
        for box, value in ((mode_box, self.mode.get()),
                           (polarity_box, self.polarity.get()),
                           (feature_box, self.feature.get())):
            values = list(box.cget("values"))
            box.current(values.index(value) if value in values else 0)
        for box in (mode_box, polarity_box, feature_box):
            box.bind(
                "<<ComboboxSelected>>",
                lambda _event: self._selection_changed())
        self._sync_polarity_controls()
        tools = ttk.LabelFrame(self, text="Optional tools (least to more intervention)")
        tools.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(tools, text="Close").pack(side="left", padx=(6, 2))
        tk.Spinbox(tools, from_=0, to=20, width=4,
                   textvariable=self.close_iterations,
                   command=self._draw).pack(side="left")
        ttk.Checkbutton(tools, text="Fill body", variable=self.fill_holes,
                        command=self._draw).pack(side="left", padx=6)
        ttk.Label(tools, text="Minimum object area").pack(side="left")
        tk.Spinbox(tools, from_=0, to=100000, increment=50, width=7,
                   textvariable=self.min_object_area,
                   command=self._draw).pack(side="left", padx=3)
        ttk.Checkbutton(tools, text="Previous-mask overlap",
                        variable=self.temporal_overlap).pack(side="left", padx=6)
        ttk.Checkbutton(tools, text="Camera registration",
                        variable=self.camera_registration).pack(side="left", padx=6)
        body = ttk.Frame(self); body.pack(fill="both", expand=True)
        self.labels = []
        for _ in range(2):
            label = ttk.Label(body); label.pack(side="left", padx=5, pady=5)
            self.labels.append(label)
        scrub = ttk.Frame(self); scrub.pack(fill="x", padx=8)
        for label, variable in (("Good frame", self.good), ("Bad frame", self.bad)):
            ttk.Label(scrub, text=label).pack(side="left")
            tk.Scale(scrub, from_=0, to=max(0, len(self.frames)-1),
                     orient="horizontal", variable=variable,
                     command=lambda _=None: self.after_idle(self._draw),
                     length=220).pack(side="left")
        ttk.Button(scrub, text="Play / pause", command=self._toggle_play).pack(
            side="left", padx=6)
        ttk.Button(scrub, text="Previous exact",
                   command=lambda: self._step_source(-1)).pack(side="left")
        ttk.Button(scrub, text="Next exact",
                   command=lambda: self._step_source(1)).pack(side="left", padx=2)
        ttk.Button(scrub, text="Jump to frame...",
                   command=self._jump_to_source).pack(side="left")
        ranges = ttk.LabelFrame(self, text="Frame-range recipes")
        ranges.pack(fill="both", padx=8, pady=6)
        columns = ("start", "end", "feature", "threshold", "tools")
        self.range_tree = ttk.Treeview(ranges, columns=columns, show="headings", height=5)
        for column, heading, width in (
                ("start", "Start", 65), ("end", "End", 65),
                ("feature", "Feature", 105), ("threshold", "Threshold", 125),
                ("tools", "Additional tools", 350)):
            self.range_tree.heading(column, text=heading)
            self.range_tree.column(column, width=width, anchor="w")
        self.range_tree.pack(side="left", fill="both", expand=True)
        range_buttons = ttk.Frame(ranges); range_buttons.pack(side="left", padx=6)
        ttk.Button(range_buttons, text="Mark start", command=self._mark_start).pack(fill="x")
        ttk.Button(range_buttons, text="Mark end", command=self._mark_end).pack(fill="x", pady=2)
        ttk.Button(range_buttons, text="Apply settings to range",
                   command=self._apply_range).pack(fill="x")
        ttk.Button(range_buttons, text="Load selected",
                   command=self._load_selected_range).pack(fill="x", pady=2)
        ttk.Button(range_buttons, text="Delete selected",
                   command=self._delete_selected_range).pack(fill="x")
        ttk.Label(self, textvariable=self.status, wraplength=900).pack(
            fill="x", padx=8, pady=5)
        buttons = ttk.Frame(self); buttons.pack(fill="x", padx=8, pady=8)
        ttk.Button(buttons, text="Accept + Lock",
                   command=self._accept).pack(side="right")
        ttk.Button(buttons, text="Add space-time ROI",
                   command=self._add_patch).pack(side="left")
        ttk.Button(buttons, text="Cancel",
                   command=self.destroy).pack(side="right", padx=5)

    def _current_recipe(self, start, end):
        raw_low = float(self.threshold_low.get())
        raw_high = float(self.threshold_high.get())
        low, high = sorted((raw_low, raw_high))
        threshold = raw_high if self.polarity.get() == "dark" else raw_low
        return FrameRangeRecipe(
            frame_start=int(start), frame_end=int(end), mode=self.mode.get(),
            feature=self.feature.get(), polarity=self.polarity.get(),
            threshold=threshold, threshold_low=low, threshold_high=high,
            close_iterations=int(self.close_iterations.get()),
            fill_holes=bool(self.fill_holes.get()),
            min_object_area=int(self.min_object_area.get()),
            temporal_overlap=bool(self.temporal_overlap.get()),
            camera_registration=bool(self.camera_registration.get())).validate()

    def _selection_changed(self):
        self._sync_polarity_controls()
        self.after_idle(self._draw)

    def _sync_polarity_controls(self):
        polarity = self.polarity.get()
        self.low_scale.configure(state=("normal" if polarity in {"bright", "band"}
                                        else "disabled"))
        self.high_scale.configure(state=("normal" if polarity in {"dark", "band"}
                                         else "disabled"))

    def _load_exact_into_bad_preview(self, source_index):
        if self.frame_loader is None:
            messagebox.showinfo(
                "Exact-frame navigation",
                "Exact source-frame loading is unavailable for this launch.",
                parent=self)
            return
        source_index = max(0, min(self.source_frame_count - 1, int(source_index)))
        slot = int(self.bad.get())
        self.frames[slot] = self.frame_loader(source_index)
        self.frame_numbers[slot] = source_index
        self._draw()

    def _step_source(self, delta):
        slot = int(self.bad.get())
        self._load_exact_into_bad_preview(self.frame_numbers[slot] + int(delta))
        return "break"

    def _jump_to_source(self):
        slot = int(self.bad.get())
        value = simpledialog.askinteger(
            "Jump to source frame", "Source-frame number:",
            initialvalue=self.frame_numbers[slot], minvalue=0,
            maxvalue=max(0, self.source_frame_count - 1), parent=self)
        if value is not None:
            self._load_exact_into_bad_preview(value)

    def _preview(self, index):
        from PIL import Image, ImageTk
        frame = self.frames[index]
        source_index = self.frame_numbers[index]
        recipe = self._current_recipe(source_index, source_index)
        config = SegmentationConfig(
            mode=self.mode.get(), threshold=recipe.threshold,
            polarity=self.polarity.get(), patches=list(self.config.patches),
            ranges=[recipe],
            feature=self.feature.get(), target_tools=[self.tool_name],
            accepted=True, locked=True)
        reference = self.reference if self.feature.get() == "difference" else None
        mask = segment_frame(frame, source_index, config, reference=reference)
        gray = _gray8(frame)
        rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
        rgb[mask] = (0.45 * rgb[mask] + 0.55 * np.array([180, 0, 0])).astype(np.uint8)
        image = Image.fromarray(rgb)
        image.thumbnail((460, 460))
        # Explicit master is essential when opened from Matplotlib/TkAgg: the
        # process can contain more than one Tcl interpreter, and Pillow's
        # implicit default root otherwise creates a pyimage in the wrong one.
        return (ImageTk.PhotoImage(image, master=self), int(mask.sum()),
                float(np.mean(gray)), float(np.median(gray)))

    def _draw(self):
        self._images = []
        readouts = []
        for label, index in zip(self.labels, (self.good.get(), self.bad.get())):
            image, area, mean, median = self._preview(index)
            self._images.append(image); label.configure(image=image)
            readouts.append(
                f"source frame {self.frame_numbers[index]}: "
                f"threshold={self.threshold_low.get():.0f}-{self.threshold_high.get():.0f}, "
                f"mean={mean:.1f}, median={median:.1f}, mask area={area}")
        self.status.set(" | ".join(readouts) + " — preview only; not applied")

    def _toggle_play(self):
        self.playing = not self.playing
        if self.playing:
            self._play_step()

    def _play_step(self):
        if not self.playing or not self.winfo_exists():
            return
        self.good.set((self.good.get() + 1) % len(self.frames))
        self._draw()
        self.after(120, self._play_step)

    def _source_frame_at_cursor(self):
        return self.frame_numbers[int(self.good.get())]

    def _mark_start(self):
        self.range_start = self._source_frame_at_cursor()
        self.status.set(f"Range start marked at source frame {self.range_start}.")

    def _mark_end(self):
        self.range_end = self._source_frame_at_cursor()
        self.status.set(f"Range end marked at source frame {self.range_end}.")

    def _apply_range(self):
        if self.range_start is None or self.range_end is None:
            messagebox.showwarning(
                "Frame range", "Mark both a start and an end frame first.", parent=self)
            return
        start, end = sorted((self.range_start, self.range_end))
        recipe = self._current_recipe(start, end)
        kept = [item for item in self.config.ranges
                if item.frame_end < start or item.frame_start > end]
        kept.append(recipe)
        self.config.ranges = sorted(kept, key=lambda item: item.frame_start)
        self.config.validate()
        self.range_start = self.range_end = None
        self._refresh_range_tree(); self._draw()

    def _refresh_range_tree(self):
        for item in self.range_tree.get_children():
            self.range_tree.delete(item)
        for index, recipe in enumerate(self.config.ranges):
            tools = []
            if recipe.close_iterations: tools.append(f"close {recipe.close_iterations}")
            if recipe.fill_holes: tools.append("fill")
            if recipe.min_object_area: tools.append(f"min area {recipe.min_object_area}")
            if recipe.temporal_overlap: tools.append("overlap")
            if recipe.camera_registration: tools.append("registration")
            threshold = (f"{recipe.threshold_low:g}-{recipe.threshold_high:g}"
                         if recipe.polarity == "band" else
                         f"{recipe.threshold:g} {recipe.polarity}")
            self.range_tree.insert("", "end", iid=str(index), values=(
                recipe.frame_start, recipe.frame_end, recipe.feature,
                threshold, ", ".join(tools) or "none"))

    def _selected_range_index(self):
        selected = self.range_tree.selection()
        return int(selected[0]) if selected else None

    def _load_selected_range(self):
        index = self._selected_range_index()
        if index is None:
            return
        recipe = self.config.ranges[index]
        self.mode.set(recipe.mode); self.feature.set(recipe.feature)
        self.polarity.set(recipe.polarity); self.threshold.set(recipe.threshold)
        self.threshold_low.set(recipe.threshold_low)
        self.threshold_high.set(recipe.threshold_high)
        self.close_iterations.set(recipe.close_iterations)
        self.fill_holes.set(recipe.fill_holes)
        self.min_object_area.set(recipe.min_object_area)
        self.temporal_overlap.set(recipe.temporal_overlap)
        self.camera_registration.set(recipe.camera_registration)
        self.range_start, self.range_end = recipe.frame_start, recipe.frame_end
        self._draw()

    def _delete_selected_range(self):
        index = self._selected_range_index()
        if index is None:
            return
        del self.config.ranges[index]
        self._refresh_range_tree(); self._draw()

    def _add_patch(self):
        import matplotlib.pyplot as plt
        index = self.bad.get()
        source_index = self.frame_numbers[index]
        fig, axis = plt.subplots()
        axis.imshow(_gray8(self.frames[index]), cmap="gray")
        axis.set_title("Draw one illumination region; Enter finishes")
        points = plt.ginput(-1, timeout=0)
        plt.close(fig)
        if len(points) < 3:
            return
        start = simpledialog.askinteger(
            "Start frame", "First source-frame number for this region:",
            initialvalue=source_index, minvalue=0, parent=self)
        end = simpledialog.askinteger(
            "End frame", "Last source-frame number for this region:",
            initialvalue=source_index, minvalue=0, parent=self)
        threshold = simpledialog.askfloat(
            "Region threshold", "Threshold for this space-time region:",
            initialvalue=(self.threshold_high.get()
                          if self.polarity.get() == "dark"
                          else self.threshold_low.get()),
            minvalue=0, maxvalue=255,
            parent=self)
        if start is None or end is None or threshold is None:
            return
        if end < start:
            start, end = end, start
        self.config.patches.append(SpaceTimePatch(
            [[float(x), float(y)] for x, y in points], start, end, threshold))
        self.mode.set("space_time")
        self.status.set(
            f"Added region {len(self.config.patches)} for frames {start}–{end}. "
            "Preview remains inert until Accept + Lock.")

    def _accept(self):
        if not messagebox.askyesno(
                "Blinding reminder",
                "Thresholds can encode expectation. Confirm settings were chosen "
                "without using the expected biological outcome. Accept and lock?"):
            return
        self.config.mode = self.mode.get()
        self.config.threshold = float(
            self.threshold_high.get() if self.polarity.get() == "dark"
            else self.threshold_low.get())
        self.config.threshold_low = float(self.threshold_low.get())
        self.config.threshold_high = float(self.threshold_high.get())
        self.config.polarity = self.polarity.get()
        self.config.feature = self.feature.get()
        self.config.close_iterations = int(self.close_iterations.get())
        self.config.fill_holes = bool(self.fill_holes.get())
        self.config.min_object_area = int(self.min_object_area.get())
        self.config.temporal_overlap = bool(self.temporal_overlap.get())
        self.config.camera_registration = bool(self.camera_registration.get())
        self.config.patches = list(self.config.patches)
        self.config.accepted = True
        self.config.locked = True
        self.config.blinding_acknowledged = True
        path = self.save_dir / CONFIG_NAME
        self.config.save(path)
        self.status.set(f"Accepted, locked, and recorded: {path}")
        self.result_path = path
