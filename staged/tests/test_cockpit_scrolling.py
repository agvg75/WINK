"""The controls column must never put a button out of reach.

Both bugs here are invisible to a construction test: the widgets exist, are
mapped, and report sensible sizes - they are just below the bottom edge of a
window that cannot scroll. So these tests measure POSITION against the
visible viewport, which is the only thing that distinguishes "crowded" from
"unreachable".
"""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk

import matplotlib
matplotlib.use("TkAgg")

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "app", ROOT / "tools"):
    sys.path.insert(0, str(p))

from process_ui import CockpitApp          # noqa: E402
import lab_hub                             # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("cockpit controls scrolling + hub scroll clamp\n")

app = None
hub = None
try:
    # ------------------------------------------------------------------
    # 1. A short controls column behaves exactly as it always did
    # ------------------------------------------------------------------
    app = CockpitApp("scroll test", geometry="900x600")
    for i in range(3):
        ttk.Button(app.controls, text=f"short {i}").pack(fill="x")
    app.update()
    app.update_idletasks()
    check("a column that fits shows NO scrollbar - a permanent one on a "
          "short column is just clutter",
          app._controls_scrollbar_shown is False)
    check("the controls frame is still an ordinary Frame that tools pack "
          "into, so no existing tool has to change",
          isinstance(app.controls, ttk.Frame)
          and app.controls is app.controls_frame)

    # ------------------------------------------------------------------
    # 2. Overflow: the reported bug
    # ------------------------------------------------------------------
    tall = [ttk.Button(app.controls, text=f"step {i}") for i in range(40)]
    for b in tall:
        b.pack(fill="x")
    app.update()
    app.update_idletasks()
    check("an overflowing column raises a scrollbar",
          app._controls_scrollbar_shown is True)

    canvas = app._controls_canvas
    view_h = canvas.winfo_height()
    last = tall[-1]
    top_of_last = last.winfo_rooty() - canvas.winfo_rooty()
    check("BEFORE scrolling, the last button really is off the bottom - "
          "which is the bug, reproduced",
          top_of_last > view_h, (top_of_last, view_h))

    canvas.yview_moveto(1.0)
    app.update()
    app.update_idletasks()
    top_of_last = last.winfo_rooty() - canvas.winfo_rooty()
    check("AFTER scrolling to the end, the last button is inside the visible "
          "viewport and can be clicked",
          0 <= top_of_last < view_h, (top_of_last, view_h))

    check("scrolling to the end does not overshoot into blank space",
          canvas.yview()[1] <= 1.0 + 1e-9, canvas.yview())

    for b in tall:
        b.destroy()
    app.refresh_controls()
    app.update()
    app.update_idletasks()
    check("a tool that rebuilds its controls can say so, and the stale "
          "scrollbar goes away", app._controls_scrollbar_shown is False)
    check("an emptied column reports no content height, rather than the "
          "height it last had", app._controls_content_height() <= 90,
          app._controls_content_height())

    # ------------------------------------------------------------------
    # 3. Collapsible sections buy the space back
    # ------------------------------------------------------------------
    body = app.add_control_section("Brightness", collapsed=False)
    for i in range(12):
        ttk.Label(body, text=f"row {i}").pack(fill="x")
    app.update()
    app.update_idletasks()
    open_h = app.controls.winfo_reqheight()
    check("an open section shows its contents", body.winfo_ismapped() == 1)
    check("its header says it will close", "[-]" in
          app._control_sections[-1]["button"].cget("text"),
          app._control_sections[-1]["button"].cget("text"))

    app.set_control_section("Brightness", True)
    app.update()
    app.update_idletasks()
    closed_h = app.controls.winfo_reqheight()
    check("collapsing actually reclaims vertical space", closed_h < open_h,
          (open_h, closed_h))
    check("and the header now says it will open", "[+]" in
          app._control_sections[-1]["button"].cget("text"))
    check("the collapsed body is unmapped, not merely shrunk",
          body.winfo_ismapped() == 0)

    app.set_control_section("Brightness", False)
    app.update()
    app.update_idletasks()
    check("reopening restores it", app.controls.winfo_reqheight() == open_h
          and body.winfo_ismapped() == 1)
    check("set_control_section reports when there is no such section",
          app.set_control_section("no such thing", True) is False)

    # The realistic shrink path: a section long enough to overflow the
    # column, folded away. This is what "buy vertical space back" means.
    big = app.add_control_section("Long step", collapsed=False)
    for i in range(40):
        ttk.Button(big, text=f"step {i}").pack(fill="x")
    app.update(); app.update_idletasks()
    check("an open section can itself overflow the column",
          app._controls_scrollbar_shown is True)
    canvas.yview_moveto(1.0)
    app.update(); app.update_idletasks()
    scrolled_away = canvas.yview()[0] > 0

    app.set_control_section("Long step", True)
    app.update(); app.update_idletasks()
    check("collapsing it retires the scrollbar",
          app._controls_scrollbar_shown is False)
    check("and rewinds the view instead of leaving blank space below the "
          "last control", scrolled_away and canvas.yview()[0] == 0.0,
          canvas.yview())
    check("every remaining control is inside the viewport once it fits",
          all(0 <= c.winfo_rooty() - canvas.winfo_rooty() < canvas.winfo_height()
              for c in app.controls.winfo_children() if c.winfo_ismapped()))

    app.destroy()
    app = None

    # ------------------------------------------------------------------
    # 4. The hub: rebuilding must not strand the view past the end
    # ------------------------------------------------------------------
    hub = lab_hub.LabHub() if hasattr(lab_hub, "LabHub") else None
    if hub is None:
        for name in dir(lab_hub):
            obj = getattr(lab_hub, name)
            if isinstance(obj, type) and issubclass(obj, tk.Tk) \
                    and obj is not tk.Tk:
                hub = obj()
                break
    check("the hub window was found and built", hub is not None)
    hub.geometry("1200x800")
    hub.update()
    hub.update_idletasks()

    check("the hub opens at the TOP of its tool list, not scrolled into "
          "empty space", hub.card_canvas.yview()[0] == 0.0,
          hub.card_canvas.yview())
    check("and it actually has cards to show", len(hub.card_widgets) > 0,
          len(hub.card_widgets))

    # Scroll down, then filter to a much shorter list - the exact sequence
    # that used to leave the hub looking empty.
    hub.card_canvas.yview_moveto(1.0)
    hub.update(); hub.update_idletasks()
    was_scrolled = hub.card_canvas.yview()[0] > 0
    hub.filter_text.set("neurite")
    hub.update(); hub.update_idletasks()
    check("after filtering to a shorter list the view is back at the top",
          was_scrolled and hub.card_canvas.yview()[0] == 0.0,
          hub.card_canvas.yview())
    check("the shorter list is genuinely shorter, so this was a real "
          "collapse of the scrollregion", 0 < len(hub.card_widgets) < 20,
          len(hub.card_widgets))

    visible_bottom = hub.card_canvas.winfo_height()
    first_card = hub.card_widgets[0]
    offset = first_card.winfo_rooty() - hub.card_canvas.winfo_rooty()
    check("the first matching card is actually on screen",
          0 <= offset < visible_bottom, (offset, visible_bottom))

    # A resize is the SAME list and must not yank the reader back to the top.
    hub.filter_text.set("")
    hub.update(); hub.update_idletasks()
    hub.card_canvas.yview_moveto(0.5)
    hub.update(); hub.update_idletasks()
    mid = hub.card_canvas.yview()[0]
    hub._rebuild_cards()
    hub.update(); hub.update_idletasks()
    check("rebuilding the SAME list keeps the reader where they were - "
          "scrolling them to the top would be its own small bug",
          mid > 0 and abs(hub.card_canvas.yview()[0] - mid) < 0.05,
          (mid, hub.card_canvas.yview()[0]))
finally:
    for window in (app, hub):
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("COCKPIT_SCROLLING_REGRESSION_PASS")
