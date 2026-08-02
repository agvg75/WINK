"""Scrollable image/track overlay review for population basal slowing."""
from __future__ import annotations

from pathlib import Path
import json
import sys

import matplotlib.pyplot as plt
from matplotlib.widgets import Button, Slider
import numpy as np
import pandas as pd

from basal_slowing import read_gray

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
from process_ui import track_colour


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
        # Editing state. `edits` is an audit trail: every structural change a
        # person makes is recorded so the resulting events can be traced back
        # to a decision rather than appearing unexplained.
        self.selection = []          # tracks picked for a join, in click order
        self.edits = []
        self.undo_stack = []
        self.tracks_edited = False
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
        self._button(.855, .90, "Accept track", self.accept_track)
        self._button(.855, .845, "Reject track", self.reject_track)
        self._button(.855, .79, "Needs correction", self.flag_track)
        self._button(.855, .735, "Clear decision", self.clear_decision)
        # Editing: a flagged track can now be corrected here rather than only
        # marked for someone else to deal with later.
        self._button(.855, .655, "Shift-click: pick 2", None, enabled=False)
        self._button(.855, .60, "Join selected", self.join_selected)
        self._button(.855, .545, "Split at frame", self.split_here)
        self._button(.855, .49, "Trim before frame", self.trim_before)
        self._button(.855, .435, "Trim after frame", self.trim_after)
        self._button(.855, .38, "Delete track", self.delete_track)
        self._button(.855, .325, "Undo edit", self.undo_edit)
        self._button(.855, .245, "Previous event", self.previous_event)
        self._button(.855, .19, "Next event", self.next_event)
        self._button(.855, .10, "Finish review", self.finish)
        self.pick_id = self.fig.canvas.mpl_connect(
            "pick_event", self._pick)
        self.key_id = self.fig.canvas.mpl_connect(
            "key_press_event", self._key)
        self._render()

    def _button(self, left, bottom, label, callback, enabled=True):
        axes = self.fig.add_axes([left, bottom, .135, .048])
        button = Button(axes, label)
        if not enabled:                      # a caption, not a control
            button.label.set_fontsize(7)
            button.color = button.hovercolor = "#e8e8e8"
            self.buttons.append(button)
            return button
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
        """Marker colours: the review decision, else where the animal is.

        Position markers carry REGION meaning (in the start ROI, on a lawn),
        which is why they are not coloured per track - see _trail_colour.
        """
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

    def _trail_colour(self, row):
        """Trail colours carry IDENTITY, so each animal gets its own.

        Previously every undecided track in the open field was drawn the same
        green, which made several animals impossible to tell apart. A decided
        track keeps its decision colour, because that state matters more than
        identity once a call has been made.
        """
        decision = self.decisions[int(row.track_id)]
        if decision == "rejected":
            return "#dc2626"
        if decision == "needs_correction":
            return "#f59e0b"
        if decision == "accepted":
            return "#16a34a"
        return track_colour(int(row.track_id))

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
                trail.x, trail.y, color=self._trail_colour(row),
                lw=2.2, alpha=.95)
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
        if index >= len(self.current_track_ids):
            return
        track_id = self.current_track_ids[index]
        shift = getattr(event.mouseevent, "key", None) == "shift"
        if shift:
            # Shift builds the pair for a join; a plain click just selects.
            if track_id in self.selection:
                self.selection.remove(track_id)
            elif len(self.selection) < 2:
                self.selection.append(track_id)
            else:
                self.selection = [self.selection[-1], track_id]
        self.selected_track = track_id
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

    # -- editing -----------------------------------------------------------
    # A "needs correction" flag used to be the end of the line: it marked a
    # track for someone else and nothing could act on it. These operations let
    # the correction happen here, and every one is recorded in `edits` so the
    # recomputed events can be traced to a decision.

    def _push_undo(self, description):
        self.undo_stack.append((self.tracks.copy(), dict(self.decisions),
                                list(self.edits), description))
        if len(self.undo_stack) > 40:
            self.undo_stack.pop(0)

    def _after_edit(self, record):
        self.edits.append(record)
        self.tracks_edited = True
        self.selection = []
        self._render()

    def _next_track_id(self):
        return int(self.tracks.track_id.max()) + 1

    def join_selected(self, _event=None):
        """Join two fragments of the same animal, in time order."""
        if len(self.selection) != 2:
            self._notice("Shift-click exactly two tracks to join them.")
            return
        groups = [self.tracks[self.tracks.track_id == t].sort_values("frame")
                  for t in self.selection]
        groups = [g for g in groups if len(g)]
        if len(groups) != 2:
            return
        groups.sort(key=lambda g: g.frame.min())
        first, second = groups
        if int(first.frame.max()) >= int(second.frame.min()):
            self._notice("Those tracks overlap in time - they cannot be one animal.")
            return
        keep = int(first.track_id.iloc[0]); drop = int(second.track_id.iloc[0])
        gap = int(second.frame.min() - first.frame.max())
        distance = float(np.hypot(second.x.iloc[0] - first.x.iloc[-1],
                                  second.y.iloc[0] - first.y.iloc[-1]))
        self._push_undo(f"join {drop} into {keep}")
        self.tracks.loc[self.tracks.track_id == drop, "track_id"] = keep
        self.decisions.pop(drop, None)
        self.selected_track = keep
        self._after_edit({"action": "join", "kept_track_id": keep,
                          "merged_track_id": drop, "gap_frames": gap,
                          "endpoint_distance_px": round(distance, 2)})

    def split_here(self, _event=None):
        """Split a track at the current frame - for one that jumped animals."""
        track_id = self.selected_track
        if track_id is None:
            self._notice("Click a track first.")
            return
        group = self.tracks[self.tracks.track_id == track_id]
        if group.empty or not (group.frame.min() < self.frame <= group.frame.max()):
            self._notice("Scrub to a frame inside the selected track first.")
            return
        new_id = self._next_track_id()
        self._push_undo(f"split {track_id} at {self.frame}")
        mask = (self.tracks.track_id == track_id) & (self.tracks.frame >= self.frame)
        self.tracks.loc[mask, "track_id"] = new_id
        self.decisions[new_id] = self.decisions.get(track_id, "unreviewed")
        self._after_edit({"action": "split", "track_id": track_id,
                          "new_track_id": new_id, "at_frame": int(self.frame)})

    def _trim(self, keep_from_start):
        track_id = self.selected_track
        if track_id is None:
            self._notice("Click a track first.")
            return
        group = self.tracks[self.tracks.track_id == track_id]
        if group.empty:
            return
        if keep_from_start:
            mask = (self.tracks.track_id == track_id) & (self.tracks.frame < self.frame)
            word, kept = "trim_before", f"frames from {self.frame} onward"
        else:
            mask = (self.tracks.track_id == track_id) & (self.tracks.frame > self.frame)
            word, kept = "trim_after", f"frames up to {self.frame}"
        removed = int(mask.sum())
        if not removed:
            self._notice("Nothing to trim at this frame.")
            return
        self._push_undo(f"{word} {track_id} at {self.frame}")
        self.tracks = self.tracks[~mask]
        self._after_edit({"action": word, "track_id": track_id,
                          "at_frame": int(self.frame), "frames_removed": removed,
                          "kept": kept})

    def trim_before(self, _event=None):
        """Drop everything before the current frame - a bad lead-in."""
        self._trim(keep_from_start=True)

    def trim_after(self, _event=None):
        """Drop everything after the current frame - a bad tail."""
        self._trim(keep_from_start=False)

    def delete_track(self, _event=None):
        track_id = self.selected_track
        if track_id is None:
            self._notice("Click a track first.")
            return
        removed = int((self.tracks.track_id == track_id).sum())
        self._push_undo(f"delete {track_id}")
        self.tracks = self.tracks[self.tracks.track_id != track_id]
        self.decisions.pop(track_id, None)
        self.selected_track = None
        self._after_edit({"action": "delete", "track_id": track_id,
                          "frames_removed": removed})

    def undo_edit(self, _event=None):
        if not self.undo_stack:
            self._notice("Nothing to undo.")
            return
        self.tracks, self.decisions, self.edits, description = self.undo_stack.pop()
        self.tracks_edited = bool(self.edits)
        self.selection = []
        self._notice(f"Undid: {description}")
        self._render()

    def _notice(self, text):
        self._message = text
        try:
            self.fig.canvas.draw_idle()
        except Exception:
            pass

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

    def result(self):
        """Decisions plus whatever structural editing was done.

        The caller needs `tracks_edited` to know whether the entry events must
        be re-derived: an edited trajectory whose events were not rebuilt would
        describe a track that no longer exists.
        """
        return {"decisions": self.decisions, "tracks": self.tracks,
                "edits": self.edits, "tracks_edited": self.tracks_edited}


def review_tracks(files, tracks, events, start_roi, lawn_rois, fps,
                  return_edits=False):
    """Review tracks, optionally returning any structural edits.

    ``return_edits=False`` preserves the original contract - a plain decisions
    mapping - so existing callers are unaffected.
    """
    reviewer = TrackReview(files, tracks, events, start_roi, lawn_rois, fps)
    reviewer.show()
    return reviewer.result() if return_edits else reviewer.decisions


def save_track_review(decisions, output):
    table = pd.DataFrame([
        {"track_id": track_id, "manual_track_status": status}
        for track_id, status in sorted(decisions.items())])
    table.to_csv(Path(output) / "manual_track_review.csv", index=False)
    return table
