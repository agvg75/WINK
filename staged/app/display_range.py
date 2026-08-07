"""How bright to draw an image on screen. Display only, never measurement.

WHY THIS IS ITS OWN MODULE. The 0.5/99.5 percentile stretch was written out
by hand in five places - pboc_tool twice, render_failure_queue,
myocyte_morphometry_tool and pumping_tool - and was MISSING from the two
screens that need it most: the single-worm tracker's outline-drawing step and
its interval chooser. On oblique-lit agar the worm is mid-grey against a
mid-grey background, and at default scaling it is close to invisible. A
person cannot draw an accurate outline around something they cannot see, and
that outline sets the reference length and area every later frame is
accepted or rejected against.

So this is not a cosmetic control. A bad outline drawn on an unviewable frame
produces an area reference that no real detection matches, and the tracker
then finds the worm in zero frames while every individual step behaves
exactly as written.

NOTHING HERE TOUCHES THE DATA. These values are passed to imshow as vmin and
vmax. The array is never rescaled, so no measurement downstream can inherit a
display choice - which is the reason the stretch is applied at draw time
rather than to the frame.
"""
from __future__ import annotations

import numpy as np

# The percentiles every existing WINK screen already used. Kept identical so
# a frame looks the same in the tracker as it does in the pumping tool; a
# different stretch per screen would make two views of one recording
# disagree about what is visible.
LOW_PERCENTILE = 0.5
HIGH_PERCENTILE = 99.5


def name_window(fig, title):
    """Give a figure a descriptive window title instead of 'Figure 1'.

    Matplotlib names every window 'Figure N'. The single-worm tracker alone
    opens five, and with several on the taskbar at once they are
    indistinguishable - working out which one was in front cost a real
    debugging session. Backend-dependent and never worth an exception, so a
    failure here is silent.
    """
    try:
        fig.canvas.manager.set_window_title(str(title))
    except Exception:                                        # noqa: BLE001
        pass
    return fig


def auto_range(image, low=LOW_PERCENTILE, high=HIGH_PERCENTILE):
    """(vmin, vmax) that make the structure visible, as a display hint.

    Falls back to the full range when the percentiles collapse - a frame that
    is almost entirely one value, which happens on blank or saturated
    frames. Returning a zero-width range would draw pure black.
    """
    data = np.asarray(image)
    finite = data[np.isfinite(data)] if data.dtype.kind == "f" else data
    if finite.size == 0:
        return 0.0, 1.0
    lo, hi = (float(v) for v in np.percentile(finite, [low, high]))
    if hi <= lo:
        lo, hi = float(np.min(finite)), float(np.max(finite))
    if hi <= lo:
        hi = lo + 1.0
    return lo, hi


def full_range(image):
    """The untouched min and max, for a Reset control."""
    data = np.asarray(image)
    finite = data[np.isfinite(data)] if data.dtype.kind == "f" else data
    if finite.size == 0:
        return 0.0, 1.0
    lo, hi = float(np.min(finite)), float(np.max(finite))
    return (lo, hi + 1.0) if hi <= lo else (lo, hi)


def attach_sliders(fig, image_artist, image, plt, *, bottom=0.02,
                   layout="bottom"):
    """Put Black/White brightness sliders and an Auto/Reset pair on a figure.

    Matplotlib rather than Tk, because these screens are matplotlib figures
    driven by ginput. Returns the widgets so the caller can keep a reference -
    Matplotlib drops widgets that are garbage collected, and a slider that
    stops responding after a few seconds is worse than none.

    `layout` picks where they go, because the screens that need this do not
    have the same free space:

        "bottom"  a full-width row under the image
        "left"    the narrow gutter beside it, for screens whose bottom is
                  already occupied - roi_editor has a frame slider at y=.125,
                  navigation buttons at .115 and an action row at .035, and
                  squeezing a third row in would overlap all of them
    """
    from matplotlib.widgets import Button, Slider

    low, high = full_range(image)
    start_lo, start_hi = auto_range(image)
    image_artist.set_clim(start_lo, start_hi)

    if layout == "left":
        axis_lo = fig.add_axes([0.035, 0.46, 0.10, 0.02])
        axis_hi = fig.add_axes([0.035, 0.41, 0.10, 0.02])
        auto_box = [0.015, 0.335, 0.062, 0.045]
        reset_box = [0.082, 0.335, 0.062, 0.045]
    else:
        axis_lo = fig.add_axes([0.13, bottom + 0.045, 0.52, 0.022])
        axis_hi = fig.add_axes([0.13, bottom + 0.015, 0.52, 0.022])
        auto_box = [0.70, bottom + 0.015, 0.10, 0.05]
        reset_box = [0.815, bottom + 0.015, 0.10, 0.05]
    slider_lo = Slider(axis_lo, "Black", low, high, valinit=start_lo)
    slider_hi = Slider(axis_hi, "White", low, high, valinit=start_hi)

    def changed(_value):
        lo, hi = slider_lo.val, slider_hi.val
        if hi <= lo:                       # crossed sliders draw a blank frame
            hi = lo + max((high - low) * 1e-3, 1e-6)
        image_artist.set_clim(lo, hi)
        fig.canvas.draw_idle()

    slider_lo.on_changed(changed)
    slider_hi.on_changed(changed)

    def set_both(lo, hi):
        slider_lo.set_val(lo)
        slider_hi.set_val(hi)

    button_auto = Button(fig.add_axes(auto_box), "Auto")
    button_reset = Button(fig.add_axes(reset_box), "Reset")
    button_auto.on_clicked(lambda _e: set_both(*auto_range(image)))
    button_reset.on_clicked(lambda _e: set_both(low, high))

    widgets = (slider_lo, slider_hi, button_auto, button_reset)
    fig._display_range_widgets = widgets      # keep them alive
    return widgets
