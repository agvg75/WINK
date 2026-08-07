"""Reusable Matplotlib ROI editor for Lab Tools.

Supports oval, rectangle, polygon, and line geometry. Area-based assays should
disable line mode; crossing assays can retain the raw two-point line while also
using the thin polygon returned in ``polygon`` for display or hit testing.
"""
from __future__ import annotations

from collections import OrderedDict
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, Polygon, Rectangle
from matplotlib.widgets import (
    Button, EllipseSelector, PolygonSelector, RadioButtons, RectangleSelector,
    Slider)
from roi_geometry import ellipse_polygon, line_polygon, rectangle_polygon


class ROIEditor:
    def __init__(self, image, title="Draw ROI", allow_line=True,
                 default_shape="Oval", line_width=5.0, multi=False,
                 label_prefix="ROI", frame_count=None, frame_loader=None,
                 allow_full_frame=False,navigation_max_dimension=960,
                 allow_empty=False):
        self.allow_empty = bool(allow_empty)
        self.image = image
        self.source_h,self.source_w=np.asarray(image).shape[:2]
        self.navigation_max_dimension=max(256,int(navigation_max_dimension))
        self.title = title
        self.allow_line = allow_line
        self.line_width = float(line_width)
        self.result = None
        self.multi = bool(multi)
        self.label_prefix = label_prefix
        self.results = []
        self.committed_artists = []
        self.current = None
        self.selector = None
        self.preview = None
        self.line_points = []
        self.frame_count = int(frame_count or 1)
        self.frame_loader = frame_loader
        self.frame_index = 0
        self._pending_frame_index=0
        self._frame_cache=OrderedDict()
        self._frame_timer=None
        self.allow_full_frame = bool(allow_full_frame)
        self.fig, self.ax = plt.subplots(figsize=(11, 8))
        import display_range as _dr; _dr.name_window(self.fig, title)
        self.fig.subplots_adjust(left=.16, bottom=.21 if self.frame_count > 1 else .15)
        first_preview=self._navigation_proxy(image);self._frame_cache[0]=first_preview
        self.image_artist = self.ax.imshow(first_preview, cmap="gray",
            extent=(0,self.source_w-1,self.source_h-1,0),interpolation="nearest")
        self.ax.set_title(
            title + "\nChoose a shape. Drag oval/rectangle; click polygon "
                    "vertices; click two points for a line.")
        choices = ["Oval", "Rectangle", "Polygon"]
        if allow_line:
            choices.append("Line")
        radio_ax = self.fig.add_axes([.01, .55, .13, .25])
        self.radio = RadioButtons(radio_ax, choices, active=(
            choices.index(default_shape) if default_shape in choices else 0))
        self.radio.on_clicked(self._activate)
        self.undo_button = self._button(.18, "Undo", self.undo)
        self.clear_button = self._button(.33, "Clear", self.clear)
        self.accept_button = self._button(
            .50, "Add ROI" if self.multi else "Accept ROI", self.accept)
        if self.multi:
            self.done_button = self._button(
                .66, "Finish / none" if self.allow_empty else "Finish",
                self.finish)
            self.cancel_button = self._button(.82, "Cancel", self.cancel)
        else:
            if self.allow_full_frame:
                self.full_button = self._button(.66, "Use full frame", self.use_full_frame)
                self.cancel_button = self._button(.82, "Cancel", self.cancel)
            else:
                self.cancel_button = self._button(.72, "Cancel", self.cancel)
        self.click_id = self.fig.canvas.mpl_connect(
            "button_press_event", self._line_click)
        self.key_id = self.fig.canvas.mpl_connect("key_press_event", self._key_press)
        if self.frame_count > 1 and self.frame_loader is not None:
            slider_ax = self.fig.add_axes([.19, .125, .58, .035])
            self.frame_slider = Slider(slider_ax, "Frame", 1,
                                       self.frame_count, valinit=1, valstep=1)
            self.frame_slider.on_changed(self._show_frame)
            self._frame_timer=self.fig.canvas.new_timer(interval=90)
            self._frame_timer.single_shot=True
            self._frame_timer.add_callback(self._load_pending_frame)
            self.prev_button = self._nav_button(.79, "<", -1)
            self.next_button = self._nav_button(.86, ">", 1)
        # BRIGHTNESS, HERE RATHER THAN PER TOOL. Eight tools draw their
        # regions through this editor, and every one of them was asking a
        # person to draw an accurate shape on a frame at default scaling. On
        # oblique-lit agar a mid-grey worm is close to invisible that way, and
        # the region drawn sets what the analysis will and will not look at.
        # In the left gutter because the bottom already holds the frame
        # slider, the navigation buttons and the action row.
        try:
            import display_range
            self._display_widgets = display_range.attach_sliders(
                self.fig, self.image_artist, first_preview, plt,
                layout="left")
        except Exception:                                    # noqa: BLE001
            # A missing brightness control must never stop someone drawing a
            # region; the editor worked without it for years.
            self._display_widgets = None
        self._activate(self.radio.value_selected)

    def _nav_button(self, left, label, step):
        axes = self.fig.add_axes([left, .115, .055, .05])
        button = Button(axes, label)
        button.on_clicked(lambda _event: self._step_frame(step))
        return button

    def _show_frame(self, value):
        index = int(round(value)) - 1
        self._pending_frame_index=index
        if index == self.frame_index:return
        # Slider dragging can emit dozens of intermediate values. Decode only
        # the last requested frame after a short quiet period.
        if self._frame_timer is not None:
            self._frame_timer.stop();self._frame_timer.start()
        else:self._load_pending_frame()

    def _navigation_proxy(self,frame):
        a=np.asarray(frame);step=max(1,int(np.ceil(max(a.shape[:2])/self.navigation_max_dimension)))
        return np.ascontiguousarray(a[::step,::step,...] if a.ndim>2 else a[::step,::step])

    def _load_pending_frame(self):
        index=int(self._pending_frame_index)
        if index==self.frame_index:return
        preview=self._frame_cache.get(index)
        if preview is None:
            preview=self._navigation_proxy(self.frame_loader(index));self._frame_cache[index]=preview
            self._frame_cache.move_to_end(index)
            while len(self._frame_cache)>12:self._frame_cache.popitem(last=False)
        self.image_artist.set_data(preview)
        self.image_artist.set_extent((0,self.source_w-1,self.source_h-1,0))
        self.frame_index = index
        self.fig.canvas.draw_idle()

    def _step_frame(self, step):
        if hasattr(self, "frame_slider"):
            value = int(np.clip(self.frame_index + step, 0,
                                self.frame_count - 1)) + 1
            self.frame_slider.set_val(value)

    def _key_press(self, event):
        if event.key in ("left", "down"):
            self._step_frame(-1)
        elif event.key in ("right", "up"):
            self._step_frame(1)

    def _button(self, left, label, callback):
        axes = self.fig.add_axes([left, .035, .13, .055])
        button = Button(axes, label)
        button.on_clicked(callback)
        return button

    def _remove_preview(self):
        if self.preview is not None:
            try:
                self.preview.remove()
            except ValueError:
                pass
            self.preview = None

    def _deactivate_selector(self):
        if self.selector is not None:
            try:
                self.selector.set_visible(False)
                for artist in self.selector.artists:
                    artist.remove()
            except (AttributeError, ValueError):
                pass
            self.selector.set_active(False)
            self.selector.disconnect_events()
            self.selector = None

    def _activate(self, label):
        self._deactivate_selector()
        self._remove_preview()
        self.current = None
        self.line_points = []
        props = dict(facecolor="#990000", edgecolor="white", alpha=.28,
                     fill=True)
        if label == "Oval":
            self.selector = EllipseSelector(
                self.ax, self._ellipse_done, useblit=True,
                props=props, button=[1], minspanx=3, minspany=3,
                spancoords="pixels", interactive=True)
        elif label == "Rectangle":
            self.selector = RectangleSelector(
                self.ax, self._rectangle_done, useblit=True,
                props=props, button=[1], minspanx=3, minspany=3,
                spancoords="pixels", interactive=True)
        elif label == "Polygon":
            self.selector = PolygonSelector(
                self.ax, self._polygon_done, useblit=True,
                props=dict(color="#990000", linewidth=2, alpha=.8))
        self.fig.canvas.draw_idle()

    def _ellipse_done(self, click, release):
        points = ellipse_polygon(
            click.xdata, click.ydata, release.xdata, release.ydata)
        self.current = {
            "shape": "oval",
            "geometry": {
                "x0": float(click.xdata), "y0": float(click.ydata),
                "x1": float(release.xdata), "y1": float(release.ydata)},
            "polygon": points,
        }

    def _rectangle_done(self, click, release):
        points = rectangle_polygon(
            click.xdata, click.ydata, release.xdata, release.ydata)
        self.current = {
            "shape": "rectangle",
            "geometry": {
                "x0": float(click.xdata), "y0": float(click.ydata),
                "x1": float(release.xdata), "y1": float(release.ydata)},
            "polygon": points,
        }

    def _polygon_done(self, vertices):
        if len(vertices) >= 3:
            points = [[float(x), float(y)] for x, y in vertices]
            self.current = {
                "shape": "polygon", "geometry": {"vertices": points},
                "polygon": points}

    def _line_click(self, event):
        if self.radio.value_selected != "Line" or event.inaxes != self.ax:
            return
        if event.button != 1 or event.xdata is None:
            return
        if len(self.line_points) == 2:
            self.line_points = []
        self.line_points.append([float(event.xdata), float(event.ydata)])
        self._remove_preview()
        if len(self.line_points) == 1:
            self.preview, = self.ax.plot(
                self.line_points[0][0], self.line_points[0][1],
                "o", color="#990000")
        else:
            points = line_polygon(
                self.line_points[0], self.line_points[1], self.line_width)
            self.preview, = self.ax.plot(
                [self.line_points[0][0], self.line_points[1][0]],
                [self.line_points[0][1], self.line_points[1][1]],
                color="#990000", linewidth=3)
            self.current = {
                "shape": "line",
                "geometry": {"points": self.line_points.copy(),
                             "width_px": self.line_width},
                "polygon": points,
            }
        self.fig.canvas.draw_idle()

    def undo(self, _event=None):
        """Undo the last vertex/point, or clear the current completed shape."""
        if self.radio.value_selected == "Line" and self.line_points:
            self.line_points.pop()
            self.current = None
            self._remove_preview()
            if self.line_points:
                self.preview, = self.ax.plot(
                    self.line_points[0][0], self.line_points[0][1],
                    "o", color="#990000")
        elif (self.radio.value_selected == "Polygon" and
              self.selector is not None and len(self.selector.verts) > 1):
            vertices = list(self.selector.verts)[:-1]
            self.selector.verts = vertices
            self.current = None
        else:
            if self.multi and self.current is None and self.results:
                self.results.pop()
                for artist in self.committed_artists.pop():
                    artist.remove()
            else:
                self.current = None
                self._remove_preview()
                shape = self.radio.value_selected
                self._activate(shape)
        self.fig.canvas.draw_idle()

    def clear(self, _event=None):
        for group in self.committed_artists:
            for artist in group:
                try:artist.remove()
                except ValueError:pass
        self.committed_artists=[];self.results=[];self.current=None
        shape = self.radio.value_selected
        self._activate(shape)
        self.ax.set_title(self.title + "\nAll ROI marks cleared. Draw a new ROI.")
        self.fig.canvas.draw_idle()

    def _capture_visible_selector(self):
        """Commit selector geometry even if the backend missed its release callback."""
        if self.current is not None or self.selector is None:return
        label=self.radio.value_selected
        try:
            if label in ("Rectangle","Oval"):
                x0,x1,y0,y1=map(float,self.selector.extents)
                if abs(x1-x0)>=3 and abs(y1-y0)>=3:
                    points=rectangle_polygon(x0,y0,x1,y1) if label=="Rectangle" else ellipse_polygon(x0,y0,x1,y1)
                    self.current={"shape":label.lower(),"geometry":{"x0":x0,"y0":y0,"x1":x1,"y1":y1},"polygon":points}
            elif label=="Polygon" and len(self.selector.verts)>=3:
                self._polygon_done(self.selector.verts)
        except Exception:
            pass

    def accept(self, _event=None):
        self._capture_visible_selector()
        if self.current is None or len(self.current.get("polygon", [])) < 3:
            self.ax.set_title(
                self.title + "\nDraw a complete ROI before accepting.",
                color="#990000")
            self.fig.canvas.draw_idle()
            return
        if self.multi:
            self.results.append(self.current)
            points = np.asarray(self.current["polygon"] +
                                [self.current["polygon"][0]])
            line, = self.ax.plot(
                points[:, 0], points[:, 1], color="#990000", linewidth=2)
            center = np.mean(points[:-1], axis=0)
            label = self.ax.text(
                center[0], center[1],
                f"{self.label_prefix} {len(self.results)}",
                color="white", fontsize=9, weight="bold",
                ha="center", va="center",
                bbox=dict(facecolor="#990000", alpha=.75, edgecolor="none"))
            self.committed_artists.append([line, label])
            shape = self.radio.value_selected
            self._activate(shape)
            self.ax.set_title(
                self.title + f"\n{len(self.results)} ROI(s) added. "
                "Draw the next one or click Finish.")
            self.fig.canvas.draw_idle()
        else:
            self.result = self.current
            plt.close(self.fig)

    def use_full_frame(self, _event=None):
        h,w=self.source_h,self.source_w
        points=rectangle_polygon(0,0,w-1,h-1)
        self.result={"shape":"full_frame","geometry":{"x0":0.0,"y0":0.0,"x1":float(w-1),"y1":float(h-1)},"polygon":points}
        plt.close(self.fig)

    def finish(self, _event=None):
        if not self.results and not self.allow_empty:
            self.ax.set_title(
                self.title + "\nAdd at least one ROI before finishing.",
                color="#990000")
            self.fig.canvas.draw_idle()
            return
        # allow_empty callers accept an empty list ("no ROIs / none").
        self.result = self.results
        plt.close(self.fig)

    def cancel(self, _event=None):
        self.result = None
        plt.close(self.fig)

    def show(self):
        plt.show()
        return self.result


def draw_roi(image, title="Draw ROI", allow_line=True,
             default_shape="Oval", line_width=5.0, frame_count=None,
             frame_loader=None, allow_full_frame=False,
             navigation_max_dimension=960):
    """Open the modal editor and return shape metadata or ``None``."""
    return ROIEditor(
        image, title=title, allow_line=allow_line,
        default_shape=default_shape, line_width=line_width,
        frame_count=frame_count, frame_loader=frame_loader,
        allow_full_frame=allow_full_frame,
        navigation_max_dimension=navigation_max_dimension).show()


def draw_rois(image, title="Draw ROIs", allow_line=True,
              default_shape="Oval", line_width=5.0, label_prefix="ROI",
              frame_count=None, frame_loader=None,
              navigation_max_dimension=960, allow_empty=False):
    """Draw, label, undo, and finish multiple ROIs in one persistent window.

    With ``allow_empty=True`` the Finish button also closes with no ROIs drawn,
    returning an empty list, so genuinely optional ROI steps never trap the user.
    """
    return ROIEditor(
        image, title=title, allow_line=allow_line,
        default_shape=default_shape, line_width=line_width,
        multi=True, label_prefix=label_prefix, frame_count=frame_count,
        frame_loader=frame_loader,
        navigation_max_dimension=navigation_max_dimension,
        allow_empty=allow_empty).show()
