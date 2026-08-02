"""Reusable WINK UI helpers for visible, but hideable, process feedback."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
import textwrap
import tkinter as tk
from tkinter import ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure


# WINK logo palette (slate-blue wordmark, sage-green arrows, off-white ground).
WINK_SLATE = "#3E4F58"
WINK_SLATE_DARK = "#2C3B44"
WINK_SAGE = "#688877"
WINK_SLATE_SOFT = "#E4E9E7"
WINK_WHITE = "#FAFAF7"
WINK_TEXT = "#22303A"
WINK_MUTED = "#5E6E76"


def apply_wink_theme(root):
    """Apply the WINK logo palette to a tool's ttk widgets. Best-effort and
    idempotent; ttk styles are per-interpreter, so calling this from any window
    themes the whole tool process."""
    try:
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(".", font=("Segoe UI", 9), background=WINK_WHITE, foreground=WINK_TEXT)
        style.configure("TFrame", background=WINK_WHITE)
        style.configure("TLabel", background=WINK_WHITE, foreground=WINK_TEXT)
        style.configure("TLabelframe", background=WINK_WHITE, bordercolor="#BDCAC8",
                        lightcolor="#BDCAC8", darkcolor="#BDCAC8")
        style.configure("TLabelframe.Label", background=WINK_WHITE, foreground=WINK_SLATE,
                        font=("Segoe UI", 9, "bold"))
        style.configure("TButton", background=WINK_SLATE, foreground="white",
                        bordercolor=WINK_SLATE_DARK, focuscolor=WINK_SAGE, padding=(8, 4))
        style.map("TButton", background=[("active", WINK_SLATE_DARK), ("disabled", "#CBD3D2")],
                  foreground=[("disabled", "#7A8A8E")])
        style.configure("TCheckbutton", background=WINK_WHITE, foreground=WINK_TEXT)
        style.map("TCheckbutton", background=[("active", WINK_WHITE)])
        style.configure("TRadiobutton", background=WINK_WHITE, foreground=WINK_TEXT)
        style.configure("TEntry", fieldbackground="white")
        style.configure("TCombobox", fieldbackground="white")
        style.configure("TScale", background=WINK_WHITE)
        style.configure("Vertical.TScrollbar", background=WINK_SLATE_SOFT,
                        troughcolor=WINK_WHITE, arrowcolor=WINK_SLATE)
        style.configure("Horizontal.TScrollbar", background=WINK_SLATE_SOFT,
                        troughcolor=WINK_WHITE, arrowcolor=WINK_SLATE)
        try:
            root.configure(bg=WINK_WHITE)
        except Exception:
            pass
    except Exception:
        pass


class TkCanvasEllipseEditor:
    """Editable semi-transparent ellipse ROI for Tk canvases.

    This helper keeps the common WINK behavior in one place: draw an oval,
    then adjust it before accepting.  It intentionally returns the bounding
    box rather than a mask so existing modules can preserve their current
    measurement code.
    """
    def __init__(self, canvas, *, on_accept=None, on_cancel=None,
                 on_change=None, on_message=None, min_size=8):
        self.canvas = canvas
        self.on_accept = on_accept
        self.on_cancel = on_cancel
        self.on_change = on_change
        self.on_message = on_message
        self.min_size = int(min_size)
        self.tag = f"editable_ellipse_{id(self)}"
        self.bbox = None
        self._mode = None
        self._anchor = None
        self._start_bbox = None
        self._active_handle = None
        self._active = False

    def _msg(self, text):
        if self.on_message is not None:
            try:
                self.on_message(str(text))
            except Exception:
                pass

    def start(self, bbox=None):
        """Start editing.  ``bbox`` is in current canvas/display coordinates."""
        self._active = True
        self.bbox = list(bbox) if bbox is not None else None
        self._draw()
        self.canvas.bind("<ButtonPress-1>", self._down)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._up)
        self.canvas.bind("<ButtonPress-3>", self.cancel)
        root = self.canvas.winfo_toplevel()
        root.bind("<Return>", self.accept)
        root.bind("<Escape>", self.cancel)
        self._msg(
            "Draw or adjust the oval. Drag handles to resize, drag inside to move. "
            "Press Enter/Accept when satisfied; right-click/Esc cancels.")

    def stop(self):
        self._active = False
        self.canvas.unbind("<ButtonPress-1>")
        self.canvas.unbind("<B1-Motion>")
        self.canvas.unbind("<ButtonRelease-1>")
        self.canvas.unbind("<ButtonPress-3>")
        root = self.canvas.winfo_toplevel()
        root.unbind("<Return>")
        root.unbind("<Escape>")
        self.canvas.delete(self.tag)

    def clear(self):
        self.bbox = None
        self._draw()
        self._msg("ROI cleared. Drag a new oval around the feature.")
        self._changed()

    def accept(self, _event=None):
        if not self._valid():
            self._msg("ROI is too small. Drag a larger oval before accepting.")
            return
        bbox = tuple(float(v) for v in self._normalized_bbox())
        self.stop()
        if self.on_accept is not None:
            self.on_accept(bbox)

    def cancel(self, _event=None):
        self.stop()
        if self.on_cancel is not None:
            self.on_cancel()

    def _normalized_bbox(self):
        x0, y0, x1, y1 = self.bbox
        return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]

    def _valid(self):
        if self.bbox is None:
            return False
        x0, y0, x1, y1 = self._normalized_bbox()
        return (x1 - x0) >= self.min_size and (y1 - y0) >= self.min_size

    def _changed(self):
        if self.on_change is not None:
            try:
                self.on_change(tuple(self._normalized_bbox()) if self.bbox else None)
            except Exception:
                pass

    def _draw(self):
        self.canvas.delete(self.tag)
        if self.bbox is None:
            return
        x0, y0, x1, y1 = self._normalized_bbox()
        self.canvas.create_oval(
            x0, y0, x1, y1,
            outline="#00FF66", fill="#00AA44", stipple="gray25", width=2,
            tags=(self.tag, f"{self.tag}_ellipse"))
        # corner handles
        r = 5
        for name, x, y in (
                ("nw", x0, y0), ("ne", x1, y0),
                ("sw", x0, y1), ("se", x1, y1)):
            self.canvas.create_rectangle(
                x - r, y - r, x + r, y + r,
                outline="#111111", fill="#FFFF66",
                tags=(self.tag, f"{self.tag}_handle", f"{self.tag}_{name}"))
        # center move handle
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        self.canvas.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            outline="#111111", fill="#00FFFF",
            tags=(self.tag, f"{self.tag}_center"))

    def _hit_handle(self, x, y):
        if self.bbox is None:
            return None
        x0, y0, x1, y1 = self._normalized_bbox()
        candidates = {
            "nw": (x0, y0), "ne": (x1, y0),
            "sw": (x0, y1), "se": (x1, y1),
            "center": ((x0 + x1) / 2.0, (y0 + y1) / 2.0),
        }
        for name, (hx, hy) in candidates.items():
            if abs(x - hx) <= 9 and abs(y - hy) <= 9:
                return name
        return None

    def _inside(self, x, y):
        if self.bbox is None:
            return False
        x0, y0, x1, y1 = self._normalized_bbox()
        if x1 <= x0 or y1 <= y0:
            return False
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        rx = max((x1 - x0) / 2.0, 1.0)
        ry = max((y1 - y0) / 2.0, 1.0)
        return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0

    def _down(self, event):
        self._anchor = (event.x, event.y)
        self._start_bbox = list(self.bbox) if self.bbox is not None else None
        self._active_handle = self._hit_handle(event.x, event.y)
        if self._active_handle == "center" or self._inside(event.x, event.y):
            self._mode = "move"
        elif self._active_handle:
            self._mode = "resize"
        else:
            self._mode = "draw"
            self.bbox = [event.x, event.y, event.x, event.y]
            self._start_bbox = list(self.bbox)
        self._draw()

    def _drag(self, event):
        if self._mode is None or self._anchor is None:
            return
        ax, ay = self._anchor
        if self._mode == "draw":
            self.bbox = [ax, ay, event.x, event.y]
        elif self._mode == "move" and self._start_bbox is not None:
            dx = event.x - ax
            dy = event.y - ay
            self.bbox = [
                self._start_bbox[0] + dx, self._start_bbox[1] + dy,
                self._start_bbox[2] + dx, self._start_bbox[3] + dy]
        elif self._mode == "resize" and self._start_bbox is not None:
            x0, y0, x1, y1 = self._start_bbox
            handle = self._active_handle
            if handle in ("nw", "sw"):
                x0 = event.x
            if handle in ("ne", "se"):
                x1 = event.x
            if handle in ("nw", "ne"):
                y0 = event.y
            if handle in ("sw", "se"):
                y1 = event.y
            self.bbox = [x0, y0, x1, y1]
        self._draw()
        self._changed()

    def _up(self, _event):
        self._mode = None
        self._anchor = None
        self._start_bbox = None
        self._active_handle = None
        if self._valid():
            self._msg("ROI ready. Adjust handles/move if needed, then press Enter/Accept.")
        else:
            self._msg("ROI too small. Drag a larger oval.")
        self._draw()
        self._changed()


def standardize_matplotlib_window(fig, title=None, width=1120, height=820, x=80, y=60):
    """Give matplotlib review windows a predictable size and title.

    This is deliberately best-effort because matplotlib backends differ.  If a
    backend does not expose a resizable window, nothing breaks.
    """
    try:
        if title:
            fig.canvas.manager.set_window_title(str(title))
    except Exception:
        pass
    manager = getattr(fig.canvas, "manager", None)
    window = getattr(manager, "window", None)
    if window is None:
        return
    for call in (
        lambda: window.wm_geometry(f"{int(width)}x{int(height)}+{int(x)}+{int(y)}"),
        lambda: window.geometry(f"{int(width)}x{int(height)}+{int(x)}+{int(y)}"),
    ):
        try:
            call()
            break
        except Exception:
            pass
    for attr, value in (("-topmost", False),):
        try:
            window.attributes(attr, value)
        except Exception:
            pass
    try:
        window.resizable(True, True)
    except Exception:
        pass


@dataclass
class ProcessLog:
    """Tiny process/timer model that can back a sidebar or export."""
    title: str = "Process"
    steps: list[dict] = field(default_factory=list)
    hidden: bool = False

    @contextmanager
    def timed(self, name, detail=""):
        start = perf_counter()
        row = {"step": str(name), "detail": str(detail or ""), "status": "running",
               "elapsed_s": None}
        self.steps.append(row)
        try:
            yield row
            row["status"] = "done"
        except Exception as exc:
            row["status"] = "failed"
            row["error"] = str(exc)
            raise
        finally:
            row["elapsed_s"] = round(perf_counter() - start, 4)

    def add(self, name, detail="", status="info", elapsed_s=None):
        self.steps.append({"step": str(name), "detail": str(detail or ""),
                           "status": str(status), "elapsed_s": elapsed_s})

    def as_text(self, max_rows=12):
        visible = self.steps[-max_rows:]
        lines = [self.title]
        for row in visible:
            timer = "" if row.get("elapsed_s") is None else f" ({row['elapsed_s']:.2f}s)"
            detail = row.get("detail", "")
            if detail:
                detail = " - " + " ".join(textwrap.wrap(str(detail), width=58))
            lines.append(f"* {row.get('status','info')}: {row.get('step','')}{timer}{detail}")
        return "\n".join(lines)


class MatplotlibProcessPanel:
    """Hideable text panel inside a matplotlib figure.

    It uses plot real estate only when visible.  Press 'h' to hide/show.
    """
    def __init__(self, fig, ax, process_log: ProcessLog, *, visible=True):
        self.fig = fig
        self.ax = ax
        self.log = process_log
        self.visible = bool(visible)
        self.artist = None
        self.cid = fig.canvas.mpl_connect("key_press_event", self._on_key)
        self.refresh()

    def _on_key(self, event):
        if event.key and str(event.key).lower() == "h":
            self.visible = not self.visible
            self.refresh()

    def refresh(self):
        if self.artist is not None:
            try:
                self.artist.remove()
            except Exception:
                pass
            self.artist = None
        if self.visible:
            self.artist = self.fig.text(
                0.985, 0.985,
                self.log.as_text(),
                ha="right", va="top", fontsize=8,
                bbox=dict(boxstyle="round,pad=0.45", facecolor="#111111",
                          edgecolor="#666666", alpha=0.78),
                color="white",
            )
        try:
            self.fig.canvas.draw_idle()
        except Exception:
            pass


def track_colour(track_id):
    """A stable, distinguishable colour per track id.

    Several animals reviewed at once are impossible to tell apart when every
    trajectory is drawn in the same colour. tab20 is categorical, so adjacent
    ids get clearly different hues, and the mapping is stable across redraws
    and across sessions for the same id.
    """
    import matplotlib
    palette = getattr(track_colour, "_palette", None)
    if palette is None:
        palette = [matplotlib.colormaps["tab20"](i / 20.0) for i in range(20)]
        track_colour._palette = palette
    return palette[int(track_id) % len(palette)]


def install_error_reporting(root, title="Action failed", log=None, status=None):
    """Make Tk callback failures visible in a window that has no process hood.

    Tk writes callback exceptions to stderr, which ``pythonw`` discards, so a
    handler that raises leaves a button that silently does nothing - the failure
    mode that hides broken controls until someone reports them. ``CockpitApp``
    routes these into its hood; plain ``tk.Tk`` tools use this instead.

    ``log`` and ``status`` are optional one-argument callables.
    """
    import traceback
    from tkinter import messagebox

    def handler(exc_type, value, tb):
        detail = f"{exc_type.__name__}: {value}"
        try:
            frames = traceback.extract_tb(tb)
            if frames:
                last = frames[-1]
                name = str(last.filename).replace("\\", "/").rsplit("/", 1)[-1]
                detail += f"  [{name}:{last.lineno} in {last.name}]"
        except Exception:
            pass
        for sink in (log, status):
            if sink is not None:
                try:
                    sink(detail)
                except Exception:
                    pass
        if log is None and status is None:
            try:
                messagebox.showerror(title, detail, parent=root)
            except Exception:
                pass
        traceback.print_exception(exc_type, value, tb)

    try:
        root.report_callback_exception = handler
    except Exception:
        pass
    return handler


class ReviewWorkbench:
    """Three-pane review shell: controls | editing canvas | process hood.

    The side panels are visible by default for teaching/review.  Press `c` to
    hide/show controls, `h` to hide/show the hood, or use the panel buttons.
    """
    def __init__(self, parent, title, process_log: ProcessLog | None = None,
                 *, width=1380, height=880):
        self.parent = parent
        self.log = process_log or ProcessLog(title)
        self.window = tk.Toplevel(parent)
        apply_wink_theme(self.window)
        self.window.title(title)
        # Clamp to the actual screen and centre the window.  A hard-coded size
        # can push the title bar's minimize/maximize/close buttons off the right
        # or bottom edge on smaller laptop screens, leaving no way to resize or
        # close the window except killing the app.
        try:
            screen_w = self.window.winfo_screenwidth()
            screen_h = self.window.winfo_screenheight()
        except Exception:
            screen_w, screen_h = 1366, 768
        win_w = max(760, min(int(width), screen_w - 80))
        win_h = max(520, min(int(height), screen_h - 120))
        pos_x = max(0, (screen_w - win_w) // 2)
        pos_y = max(0, (screen_h - win_h) // 3)
        self.window.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
        self.window.minsize(min(760, win_w), min(520, win_h))
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        try:
            self.window.resizable(True, True)
        except Exception:
            pass
        self.controls_visible = tk.BooleanVar(value=True)
        self.hood_visible = tk.BooleanVar(value=True)
        self._close_handler = None
        self._closed = False

        self.window.grid_columnconfigure(0, weight=0)
        self.window.grid_columnconfigure(1, weight=1)
        self.window.grid_columnconfigure(2, weight=0)
        self.window.grid_rowconfigure(1, weight=1)

        top = ttk.Frame(self.window)
        top.grid(row=0, column=0, columnspan=3, sticky="ew")
        ttk.Button(top, text="< controls", command=self.toggle_controls).pack(side="left", padx=4, pady=3)
        self.status_var = tk.StringVar(
            value="Canvas: toolbar zoom/pan works here. Shortcuts: c=controls, h=hood.")
        ttk.Label(top, textvariable=self.status_var).pack(side="left", padx=8)
        ttk.Button(top, text="hood >", command=self.toggle_hood).pack(side="right", padx=4, pady=3)

        self.controls_frame = ttk.LabelFrame(self.window, text="Controls")
        self.controls_frame.grid(row=1, column=0, sticky="nsw", padx=(6, 3), pady=6)
        self.center_frame = ttk.Frame(self.window)
        self.center_frame.grid(row=1, column=1, sticky="nsew", padx=3, pady=6)
        self.hood_frame = ttk.LabelFrame(self.window, text="Hood: process and reasons")
        self.hood_frame.grid(row=1, column=2, sticky="nse", padx=(3, 6), pady=6)

        self.center_frame.grid_columnconfigure(0, weight=1)
        self.center_frame.grid_rowconfigure(0, weight=1)
        self.fig = Figure(figsize=(8.8, 6.8), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.center_frame)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self.toolbar = NavigationToolbar2Tk(self.canvas, self.center_frame, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.grid(row=1, column=0, sticky="ew")

        self.hood_text = tk.Text(self.hood_frame, width=42, height=28, wrap="word")
        self.hood_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.refresh_hood()

        self.window.bind("<h>", lambda _e: self.toggle_hood())
        self.window.bind("<H>", lambda _e: self.toggle_hood())
        self.window.bind("<c>", lambda _e: self.toggle_controls())
        self.window.bind("<C>", lambda _e: self.toggle_controls())

    def set_status(self, text):
        """Update the one-line status/instruction area above the canvas."""
        try:
            self.status_var.set(str(text))
        except Exception:
            pass

    def set_close_handler(self, handler):
        self._close_handler = handler

    def clear_controls(self):
        for child in self.controls_frame.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass

    def add_control_label(self, text, *, wraplength=260):
        label = ttk.Label(
            self.controls_frame, text=str(text), wraplength=wraplength,
            justify="left")
        label.pack(anchor="w", fill="x", padx=6, pady=3)
        return label

    def add_control_button(self, text, command):
        button = ttk.Button(self.controls_frame, text=str(text), command=command)
        button.pack(fill="x", padx=6, pady=3)
        return button

    def add_control_separator(self):
        sep = ttk.Separator(self.controls_frame, orient="horizontal")
        sep.pack(fill="x", padx=6, pady=7)
        return sep

    def add_labeled_entry(self, label, variable, *, width=10):
        row = ttk.Frame(self.controls_frame)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text=str(label), width=16).pack(side="left")
        ent = ttk.Entry(row, textvariable=variable, width=width)
        ent.pack(side="right")
        return ent

    def refresh_hood(self):
        try:
            self.hood_text.configure(state="normal")
            self.hood_text.delete("1.0", "end")
            self.hood_text.insert("1.0", self.log.as_text(max_rows=18))
            self.hood_text.configure(state="disabled")
        except Exception:
            pass

    def refresh(self):
        self.refresh_hood()
        try:
            self.canvas.draw_idle()
        except Exception:
            pass

    def draw_idle(self):
        try:
            self.canvas.draw_idle()
        except Exception:
            pass

    def toggle_controls(self):
        if self.controls_visible.get():
            self.controls_frame.grid_remove()
            self.controls_visible.set(False)
        else:
            self.controls_frame.grid()
            self.controls_visible.set(True)

    def toggle_hood(self):
        if self.hood_visible.get():
            self.hood_frame.grid_remove()
            self.hood_visible.set(False)
        else:
            self.hood_frame.grid()
            self.hood_visible.set(True)

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._close_handler is not None:
            self._close_handler()
        try:
            self.window.destroy()
        except Exception:
            pass

    def wait(self):
        # NOTE: a `transient` window on Windows is drawn as a tool window and
        # loses its minimize/maximize/restore buttons.  Users need those on
        # these full workbench windows, so we keep the window a normal top-level
        # (min/max/restore available, own taskbar entry) and enforce modality
        # with grab_set alone instead of transient().
        try:
            self.window.grab_set()
        except Exception:
            pass
        try:
            self.window.lift()
            self.window.focus_force()
        except Exception:
            pass
        self.window.wait_window()


# Alias used by newly migrated modules.  ReviewWorkbench remains for backward
# compatibility; ModuleWorkbench names the broader cockpit pattern:
# controls | interactive canvas | transparent process hood.
ModuleWorkbench = ReviewWorkbench


class CockpitApp(tk.Tk):
    """Standard WINK single-window shell: header + controls | center | hood.

    ``ReviewWorkbench`` is a *Toplevel* opened for one interactive editing pass;
    ``CockpitApp`` is the *main application window* pattern, so form/measurement
    tools that are their own ``tk.Tk`` get the same three-pane look without each
    hand-rolling it.  A tool subclasses this, builds its inputs into
    ``self.controls``, its main content/instructions into ``self.center``, and
    reports progress with :meth:`set_status` / :meth:`log`.  Controls and hood
    toggle with the ``c`` and ``h`` keys, matching the review workbench.

    The centre pane is a plain frame, not a canvas: most legacy tools do their
    image work in separate review windows, so the centre holds instructions,
    a summary, or a preview - the shared value here is consistency, the process
    hood, and a common place for the Calibrate-scale button.
    """

    def __init__(self, title, *, geometry="1100x740", process_title=None,
                 controls_label="Controls",
                 hood_label="Hood: process and notes"):
        super().__init__()
        self.title(title)
        try:
            self.geometry(geometry)
        except Exception:
            pass
        self.process_log = ProcessLog(process_title or title)
        self._controls_visible = True
        self._hood_visible = True
        apply_wink_theme(self)
        self._build_cockpit(controls_label, hood_label)
        # Tk sends callback exceptions to stderr, which pythonw discards - so a
        # button whose handler raises simply appears to do nothing, and the user
        # has no way to tell a broken control from an inapplicable one. Surface
        # them in the hood and the status line instead. Every CockpitApp tool
        # gets this; a subclass may still override the method.
        self.report_callback_exception = self._report_callback_exception

    def _report_callback_exception(self, exc_type, value, tb):
        import traceback
        detail = f"{exc_type.__name__}: {value}"
        try:
            frames = traceback.extract_tb(tb)
            if frames:
                last = frames[-1]
                name = str(last.filename).replace("\\", "/").rsplit("/", 1)[-1]
                detail += f"  [{name}:{last.lineno} in {last.name}]"
        except Exception:
            pass
        try:
            self.log("Action failed", detail, status="failed")
        except Exception:
            pass
        try:
            self.set_status("Action failed: " + detail)
        except Exception:
            pass
        traceback.print_exception(exc_type, value, tb)

    def _build_cockpit(self, controls_label, hood_label):
        tk.Frame(self, bg=WINK_SAGE, height=5).pack(fill="x")
        header = ttk.Frame(self)
        header.pack(fill="x", padx=8, pady=(8, 3))
        ttk.Button(header, text="< controls",
                   command=self.toggle_controls).pack(side="left", padx=4)
        self._status_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self._status_var, anchor="w",
                  wraplength=640).pack(side="left", padx=8, fill="x", expand=True)
        ttk.Button(header, text="hood >",
                   command=self.toggle_hood).pack(side="right", padx=4)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=5)
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(2, weight=0)
        body.grid_rowconfigure(0, weight=1)

        self._controls_holder = ttk.LabelFrame(body, text=controls_label)
        self._controls_holder.grid(row=0, column=0, sticky="nsw", padx=(0, 5))
        self.controls = self.controls_frame = ttk.Frame(self._controls_holder)
        self.controls.pack(fill="both", expand=True, padx=4, pady=4)

        self.center = self.center_frame = ttk.Frame(body)
        self.center.grid(row=0, column=1, sticky="nsew", padx=3)

        self._hood_holder = ttk.LabelFrame(body, text=hood_label)
        self._hood_holder.grid(row=0, column=2, sticky="nse", padx=(5, 0))
        self.hood_text = tk.Text(self._hood_holder, width=36, height=30,
                                 wrap="word")
        self.hood_text.pack(fill="both", expand=True, padx=5, pady=5)

        self._body = body
        self.bind("<c>", lambda _e: self.toggle_controls())
        self.bind("<C>", lambda _e: self.toggle_controls())
        self.bind("<h>", lambda _e: self.toggle_hood())
        self.bind("<H>", lambda _e: self.toggle_hood())
        self.refresh_hood()

    # -- status + hood ------------------------------------------------------
    def set_status(self, text):
        try:
            self._status_var.set(str(text))
        except Exception:
            pass

    def log(self, step, detail="", status="info"):
        self.process_log.add(step, detail, status=status)
        self.refresh_hood()

    def refresh_hood(self):
        try:
            self.hood_text.configure(state="normal")
            self.hood_text.delete("1.0", "end")
            self.hood_text.insert("1.0", self.process_log.as_text(max_rows=20))
            self.hood_text.configure(state="disabled")
        except Exception:
            pass

    # -- toggles ------------------------------------------------------------
    def toggle_controls(self):
        if self._controls_visible:
            self._controls_holder.grid_remove()
        else:
            self._controls_holder.grid()
        self._controls_visible = not self._controls_visible

    def toggle_hood(self):
        if self._hood_visible:
            self._hood_holder.grid_remove()
        else:
            self._hood_holder.grid()
        self._hood_visible = not self._hood_visible

    # -- shared Calibrate-scale button --------------------------------------
    def add_scale_button(self, get_frame, apply_result, *, initial=None,
                         text="Calibrate scale (um/px)", master=None):
        """Standard button that opens the shared scale dialog.

        ``get_frame()`` returns a numpy image (or None) for the scale bar;
        ``apply_result(result_dict)`` stores the chosen um/px.  ``initial`` may
        be a float or a zero-arg callable returning the current um/px.
        """
        def _open():
            from tkinter import messagebox
            try:
                from scale_calibration_ui import ScaleCalibrationPanel
            except Exception as exc:
                messagebox.showerror("Scale calibration", str(exc))
                return
            try:
                frame = get_frame()
            except Exception:
                frame = None
            start = initial() if callable(initial) else initial
            # In-window: cover the centre pane with the panel instead of opening
            # a separate dialog window.  Destroyed when OK/Cancel is pressed.
            overlay = ttk.Frame(self.center, relief="raised", borderwidth=1)
            overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

            def _done(result):
                try:
                    overlay.destroy()
                except Exception:
                    pass
                if result:
                    apply_result(result)
            ScaleCalibrationPanel(overlay, frame=frame, initial=start, on_done=_done)
        return ttk.Button(master or self.controls, text=text, command=_open)


def collect_image_points(
        parent, image, *, title="Select points", instructions="Click points.",
        mode="points", min_points=1, max_points=None, process_log=None,
        cmap="gray", width=1380, height=880):
    """Collect image points inside the WINK workbench.

    Parameters
    ----------
    mode:
        "points" draws individual points, "polyline" connects points in order,
        and "polygon" also closes the path.
    max_points:
        When set, collection auto-finishes after that many left-clicks.

    Returns a list of ``(x, y)`` floats, or ``None`` if the user cancels.
    """
    log = process_log or ProcessLog(title)
    log.add("Interactive selection", instructions, status="ready")
    wb = ModuleWorkbench(parent, title, log, width=width, height=height)
    wb.set_status(instructions + "  Keys: Enter/finish, Backspace/undo, Esc/cancel.")
    ax = wb.ax
    ax.imshow(image, cmap=cmap)
    ax.set_title(instructions)
    points = []
    artists = []
    result = {"cancelled": False}

    def redraw():
        nonlocal artists
        for artist in artists:
            try:
                artist.remove()
            except Exception:
                pass
        artists = []
        if points:
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            artists.append(ax.scatter(xs, ys, c="#00FFFF", s=36, zorder=5))
            if mode in ("polyline", "polygon") and len(points) >= 2:
                lx = list(xs)
                ly = list(ys)
                if mode == "polygon" and len(points) >= 3:
                    lx.append(xs[0])
                    ly.append(ys[0])
                line, = ax.plot(lx, ly, color="#00FF66", lw=2, zorder=4)
                artists.append(line)
            for i, (x, y) in enumerate(points, start=1):
                artists.append(ax.text(
                    x, y, str(i), color="yellow", fontsize=8,
                    ha="left", va="bottom", zorder=6))
        wb.refresh()

    def finish():
        if len(points) < int(min_points or 0):
            log.add(
                "Selection not complete",
                f"{len(points)} point(s) selected; at least {min_points} needed.",
                status="warning")
            wb.refresh_hood()
            return
        wb.close()

    def cancel():
        result["cancelled"] = True
        wb.close()

    def undo():
        if points:
            points.pop()
            log.add("Undo point", f"{len(points)} point(s) remain.", status="edit")
            redraw()

    def clear():
        points.clear()
        log.add("Clear points", "Selection cleared.", status="edit")
        redraw()

    def click(event):
        if event.inaxes != ax or event.xdata is None or event.ydata is None:
            return
        if event.button != 1:
            return
        if max_points is not None and len(points) >= int(max_points):
            return
        points.append((float(event.xdata), float(event.ydata)))
        log.add("Point added", f"x={event.xdata:.1f}, y={event.ydata:.1f}", status="edit")
        redraw()
        if max_points is not None and len(points) >= int(max_points):
            finish()

    def key(event):
        key_name = str(getattr(event, "key", "") or "").lower()
        if key_name in ("enter", "return"):
            finish()
        elif key_name in ("backspace", "delete"):
            undo()
        elif key_name == "escape":
            cancel()

    wb.clear_controls()
    wb.add_control_label(instructions)
    wb.add_control_button("Finish / accept", finish)
    wb.add_control_button("Undo last point", undo)
    wb.add_control_button("Clear and redraw", clear)
    wb.add_control_button("Cancel", cancel)
    wb.add_control_separator()
    wb.add_control_button("Hide controls (c)", wb.toggle_controls)
    wb.add_control_button("Hide hood (h)", wb.toggle_hood)
    wb.fig.canvas.mpl_connect("button_press_event", click)
    wb.fig.canvas.mpl_connect("key_press_event", key)
    redraw()
    wb.wait()
    if result["cancelled"]:
        return None
    return list(points)
