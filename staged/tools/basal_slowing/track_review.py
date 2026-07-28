"""Scrollable image/track overlay review for population basal slowing."""
from __future__ import annotations

from pathlib import Path
import json

import matplotlib.pyplot as plt
from matplotlib.widgets import Button, Slider
import numpy as np
import pandas as pd

from basal_slowing import read_gray


class TrackReview:
    def __init__(self, files, tracks, events, start_roi, lawn_rois, fps):
        self.files = list(files)
        self.tracks = tracks.copy()
        self.events = events.copy()
        self.start_roi = start_roi
        self.lawn_rois = lawn_rois
        self.fps = float(fps)
        self.frame = 0
        self.selected_track = None
        self.decisions = {
            int(track_id): "unreviewed"
            for track_id in sorted(tracks.track_id.unique())}
        # This reviewer binds r, c, and the arrow keys, which Matplotlib also
        # binds by default (r=reset view [keymap.home], c=back, arrows=back/
        # forward).  Left in place they would jump/zoom the view underneath the
        # reviewer, so clear the clashing default key maps for this tool.
        for _km in ("keymap.fullscreen", "keymap.save", "keymap.grid",
                    "keymap.grid_minor", "keymap.home", "keymap.back",
                    "keymap.forward", "keymap.xscale", "keymap.yscale"):
            try:
                plt.rcParams[_km] = []
            except Exception:
                pass
        self.fig, self.ax = plt.subplots(figsize=(12, 8))
        self.buttons = []
        self.fig.subplots_adjust(bottom=.19, right=.84)
        self.image_artist = self.ax.imshow(
            read_gray(self.files[0]), cmap="gray")
        self.scatter = self.ax.scatter([], [], s=70, picker=8)
        self.labels = []
        self.trail_artists = []
        self._draw_rois()
        slider_ax = self.fig.add_axes([.12, .10, .65, .035])
        self.slider = Slider(
            slider_ax, "Frame", 0, len(self.files) - 1,
            valinit=0, valstep=1)
        self.slider.on_changed(self._slide)
        self._button(.84, .72, "Accept track", self.accept_track)
        self._button(.84, .64, "Reject track", self.reject_track)
        self._button(.84, .56, "Needs correction", self.flag_track)
        self._button(.84, .48, "Clear decision", self.clear_decision)
        self._button(.84, .34, "Previous event", self.previous_event)
        self._button(.84, .26, "Next event", self.next_event)
        self._button(.84, .10, "Finish review", self.finish)
        self.pick_id = self.fig.canvas.mpl_connect(
            "pick_event", self._pick)
        self.key_id = self.fig.canvas.mpl_connect(
            "key_press_event", self._key)
        self._render()

    def _button(self, left, bottom, label, callback):
        axes = self.fig.add_axes([left, bottom, .145, .055])
        button = Button(axes, label)
        button.on_clicked(callback)
        self.buttons.append(button)
        return button

    def _draw_rois(self):
        start = np.asarray(self.start_roi + [self.start_roi[0]])
        self.ax.plot(start[:, 0], start[:, 1], color="#00ffff", lw=1.5)
        for number, lawn in enumerate(self.lawn_rois, 1):
            p = np.asarray(lawn + [lawn[0]])
            self.ax.plot(p[:, 0], p[:, 1], color="#990000", lw=1.2)
            center = p[:-1].mean(axis=0)
            self.ax.text(
                center[0], center[1], str(number), color="white",
                ha="center", va="center", fontsize=8,
                bbox=dict(facecolor="#990000", alpha=.65, edgecolor="none"))

    def _slide(self, value):
        self.frame = int(value)
        self._render()

    def _colors(self, group):
        colors = []
        for _, row in group.iterrows():
            decision = self.decisions[int(row.track_id)]
            if decision == "rejected":
                colors.append("#dc2626")
            elif decision == "needs_correction":
                colors.append("#f59e0b")
            elif decision == "accepted":
                colors.append("#16a34a")
            elif bool(row.inside_start):
                colors.append("#00ffff")
            elif bool(row.inside_any_lawn):
                colors.append("#990000")
            else:
                colors.append("#7CFC00")
        return colors

    def _render(self):
        self.image_artist.set_data(read_gray(self.files[self.frame]))
        current = self.tracks[self.tracks.frame == self.frame].copy()
        self.current_track_ids = current.track_id.astype(int).tolist()
        offsets = (current[["x", "y"]].to_numpy()
                   if len(current) else np.empty((0, 2)))
        self.scatter.set_offsets(offsets)
        self.scatter.set_color(self._colors(current))
        for artist in self.labels + self.trail_artists:
            artist.remove()
        self.labels, self.trail_artists = [], []
        trail_start = max(0, self.frame - int(round(2 * self.fps)))
        for _, row in current.iterrows():
            track_id = int(row.track_id)
            trail = self.tracks[
                (self.tracks.track_id == track_id) &
                (self.tracks.frame >= trail_start) &
                (self.tracks.frame <= self.frame)]
            line, = self.ax.plot(
                trail.x, trail.y, color=self._colors(
                    pd.DataFrame([row]))[0], lw=1.2, alpha=.8)
            self.trail_artists.append(line)
            if bool(row.get("spine_valid", False)):
                try:
                    sx = json.loads(row.spine_x_json)
                    sy = json.loads(row.spine_y_json)
                    spine_line, = self.ax.plot(
                        sx, sy, color="#facc15", lw=1.6, alpha=.95)
                    head, = self.ax.plot(
                        sx[0], sy[0], marker="o", color="#22d3ee",
                        markersize=3)
                    self.trail_artists.extend([spine_line, head])
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
            self.labels.append(self.ax.text(
                row.x + 4, row.y - 4, str(track_id), color="white",
                fontsize=8, weight="bold",
                bbox=dict(facecolor="#222222", alpha=.55, edgecolor="none")))
        entry = self.events[self.events.entry_frame == self.frame]
        exit_rows = self.events[self.events.exit_frame == self.frame]
        for _, row in entry.iterrows():
            star, = self.ax.plot(
                row.entry_x, row.entry_y, marker="*", color="#fde047",
                markersize=15, markeredgecolor="black")
            self.trail_artists.append(star)
        # Exit position is not stored separately; mark the matching track point.
        for _, event in exit_rows.iterrows():
            point = current[current.track_id == event.track_id]
            if len(point):
                cross, = self.ax.plot(
                    point.x.iloc[0], point.y.iloc[0], marker="x",
                    color="#38bdf8", markersize=12, mew=2)
                self.trail_artists.append(cross)
        selected = (
            f" | selected track {self.selected_track}: "
            f"{self.decisions[self.selected_track]}"
            if self.selected_track is not None else "")
        self.ax.set_title(
            f"Frame {self.frame}/{len(self.files)-1} "
            f"({self.frame/self.fps:.2f} s){selected}\n"
            "cyan=start ROI, lime=outside, maroon=inside lawn, "
            "yellow=spine, green=accepted, red=rejected, "
            "orange=needs correction")
        self.fig.canvas.draw_idle()

    def _pick(self, event):
        if event.artist is not self.scatter or not len(event.ind):
            return
        index = int(event.ind[0])
        if index < len(self.current_track_ids):
            self.selected_track = self.current_track_ids[index]
            self._render()

    def _set_decision(self, value):
        if self.selected_track is not None:
            self.decisions[self.selected_track] = value
            self._render()

    def accept_track(self, _event=None):
        self._set_decision("accepted")

    def reject_track(self, _event=None):
        self._set_decision("rejected")

    def flag_track(self, _event=None):
        self._set_decision("needs_correction")

    def clear_decision(self, _event=None):
        self._set_decision("unreviewed")

    def _event_frames(self):
        return sorted(set(
            self.events.entry_frame.dropna().astype(int).tolist() +
            self.events.exit_frame.dropna().astype(int).tolist()))

    def previous_event(self, _event=None):
        frames = [x for x in self._event_frames() if x < self.frame]
        if frames:
            self.slider.set_val(frames[-1])

    def next_event(self, _event=None):
        frames = [x for x in self._event_frames() if x > self.frame]
        if frames:
            self.slider.set_val(frames[0])

    def _key(self, event):
        if event.key == "right":
            self.slider.set_val(min(len(self.files)-1, self.frame + 1))
        elif event.key == "left":
            self.slider.set_val(max(0, self.frame - 1))
        elif event.key == "a":
            self.accept_track()
        elif event.key == "r":
            self.reject_track()
        elif event.key == "c":
            self.flag_track()

    def finish(self, _event=None):
        plt.close(self.fig)

    def show(self):
        plt.show()
        return self.decisions


def review_tracks(files, tracks, events, start_roi, lawn_rois, fps):
    return TrackReview(
        files, tracks, events, start_roi, lawn_rois, fps).show()


def save_track_review(decisions, output):
    table = pd.DataFrame([
        {"track_id": track_id, "manual_track_status": status}
        for track_id, status in sorted(decisions.items())])
    table.to_csv(Path(output) / "manual_track_review.csv", index=False)
    return table
