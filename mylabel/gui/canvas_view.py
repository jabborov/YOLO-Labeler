"""Image canvas: rendering, zoom/pan, box drawing/selection/move/resize,
see-through hover, multi-selection and box copy/paste.

Only the visible part of the image is cropped, scaled and converted to a
PhotoImage on each render, so cost depends on the window size rather than the
image size or zoom level.
"""

import math
import sys
import tkinter as tk
from typing import Callable, List, Optional, Tuple

from PIL import Image, ImageTk

from ..core.annotation import AnnotationDoc, Box, find_duplicate
from ..core.image_loader import LoadedImage
from . import theme
from .colors import class_color, text_color_on

try:
    _NEAREST, _BILINEAR = Image.Resampling.NEAREST, Image.Resampling.BILINEAR
except AttributeError:  # Pillow < 9.1
    _NEAREST, _BILINEAR = Image.NEAREST, Image.BILINEAR

HANDLE_R = 5          # half size of drawn handles (canvas px)
HIT_R = 7             # handle hit radius (canvas px)
CLICK_PX = 4          # drags shorter than this count as clicks
MAX_ZOOM = 32.0       # canvas px per original image px
WHEEL_STEP = 1.2      # zoom factor per mouse-wheel notch (delta 120)
# The smallest zoom is "fit to window". Along any axis where the zoomed image
# is larger than the canvas, the view is clamped so the image always covers the
# canvas (no background visible); along a smaller axis the image is centered.

if sys.platform == "win32":
    _CORNER_CURSORS = {"nw": "size_nw_se", "se": "size_nw_se",
                       "ne": "size_ne_sw", "sw": "size_ne_sw"}
else:
    _CORNER_CURSORS = {"nw": "top_left_corner", "se": "bottom_right_corner",
                       "ne": "top_right_corner", "sw": "bottom_left_corner"}
_CURSORS = dict(_CORNER_CURSORS, n="sb_v_double_arrow", s="sb_v_double_arrow",
                e="sb_h_double_arrow", w="sb_h_double_arrow")


def _bounds(boxes: List[Box]) -> Tuple[float, float, float, float]:
    """Bounding rectangle (x1, y1, x2, y2) of several boxes."""
    return (min(b.x1 for b in boxes), min(b.y1 for b in boxes),
            max(b.x2 for b in boxes), max(b.y2 for b in boxes))


class CanvasView(tk.Canvas):
    def __init__(self, master, min_box: float = 2.0, **kw):
        super().__init__(master, bg=theme.palette()["canvas"], highlightthickness=0,
                         cursor="arrow", **kw)
        self.min_box = min_box

        # Callbacks wired by the application.
        self.on_change: Callable[[bool], None] = lambda boxes_changed: None
        self.on_status: Callable[[str], None] = lambda msg: None
        self.on_cursor: Callable[[str], None] = lambda text: None
        self.on_need_full: Callable[[], None] = lambda: None
        self.on_zoom: Callable[[float], None] = lambda zoom: None
        self.class_name: Callable[[int], str] = str
        self.active_class: Callable[[], Optional[int]] = lambda: None

        self.loaded: Optional[LoadedImage] = None
        self.doc: Optional[AnnotationDoc] = None
        self.selected: Optional[int] = None
        self.marked: List[int] = []           # multi-selection from the box list
        self._hover: Optional[int] = None     # box under the mouse, drawn see-through
        # Copied boxes, the size and path of the image they came from (kept across images).
        self._clipboard: Optional[Tuple[List[Box], int, int, str]] = None
        self.draw_mode = False
        self.show_names = True
        self.zoom = 1.0
        self.ox = 0.0
        self.oy = 0.0
        self._fit_zoom = 1.0

        self._photo = None
        self._render_pending = False
        self._full_requested = False
        self._message = ""
        self._mode: Optional[str] = None      # draw | move | resize | pan
        self._pan_button = 0                  # mouse button that started the pan
        self._pan_origin: Tuple[float, float] = (0.0, 0.0)
        self._press_c: Tuple[float, float] = (0, 0)
        self._press_i: Tuple[float, float] = (0, 0)
        self._handle = ""
        self._orig_box: Optional[Box] = None
        self._drag_box: Optional[Box] = None
        self._mouse: Optional[Tuple[int, int]] = None

        self.bind("<Configure>", lambda e: self._on_resize())
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)
        for b in ("2", "3"):
            self.bind("<ButtonPress-%s>" % b, self._on_pan_start)
            self.bind("<B%s-Motion>" % b, self._on_pan_drag)
            self.bind("<ButtonRelease-%s>" % b, self._on_pan_end)
        # Mouse-wheel events are routed here by the application (see App._on_wheel)
        # so zoom works no matter which widget has keyboard focus.

    # ================================================================ public
    def show_message(self, text: str) -> None:
        """Clear the image and show a centered message."""
        self.loaded = None
        self.doc = None
        self.selected = None
        self._message = text
        self._photo = None
        self.delete("all")
        self._draw_message()

    def set_image(self, loaded: LoadedImage, keep_view: bool = False) -> None:
        same = self.loaded is not None and self.loaded.path == loaded.path
        self.loaded = loaded
        self._message = ""
        self.delete("msg")
        self._full_requested = loaded.is_full
        if not (keep_view and same):
            self.fit()
        self.request_render()

    def set_doc(self, doc: Optional[AnnotationDoc]) -> None:
        self.doc = doc
        self.selected = None
        self.marked = []
        self._cancel_drag()
        self.redraw_overlays()

    def _calc_fit_zoom(self) -> float:
        cw, ch = max(self.winfo_width(), 1), max(self.winfo_height(), 1)
        ow, oh = self.loaded.orig_size
        return min(cw / ow, ch / oh)

    def _clamp_view(self) -> None:
        """Keep the image covering the canvas on every axis where it is larger
        than the canvas, and centered on any axis where it is smaller."""
        cw, ch = max(self.winfo_width(), 1), max(self.winfo_height(), 1)
        ow, oh = self.loaded.orig_size
        iw, ih = ow * self.zoom, oh * self.zoom
        self.ox = (cw - iw) / 2.0 if iw <= cw else min(0.0, max(cw - iw, self.ox))
        self.oy = (ch - ih) / 2.0 if ih <= ch else min(0.0, max(ch - ih, self.oy))

    def fit(self) -> None:
        if self.loaded is None:
            return
        self._fit_zoom = self._calc_fit_zoom()
        self.zoom = self._fit_zoom
        self._clamp_view()  # centers the image
        self.request_render()
        self.on_zoom(self.zoom)

    def zoom_by(self, factor: float, cx: Optional[float] = None,
                cy: Optional[float] = None) -> None:
        """Zoom keeping the image point under (cx, cy) fixed (as far as the
        no-background clamp allows). Without a point, the mouse position is used
        if it is over the canvas, else the center."""
        if self.loaded is None:
            return
        if cx is None:
            if self._mouse is not None:
                cx, cy = self._mouse
            else:
                cx, cy = self.winfo_width() / 2.0, self.winfo_height() / 2.0
        lo = self._fit_zoom
        hi = max(MAX_ZOOM, self._fit_zoom)
        new = min(hi, max(lo, self.zoom * factor))
        if abs(new - self.zoom) < 1e-12:
            return
        ix, iy = self.c2i(cx, cy)
        self.zoom = new
        self.ox = cx - ix * new
        self.oy = cy - iy * new
        self._clamp_view()
        if self._mode == "pan":  # continue the pan from the new view
            self._press_c = (cx, cy)
            self._pan_origin = (self.ox, self.oy)
        self.request_render()
        self.on_zoom(self.zoom)

    def wheel(self, cx: float, cy: float, delta: float) -> None:
        """Zoom at canvas point (cx, cy) for a mouse-wheel delta (120 per notch).
        Fractional deltas from touchpads/high-resolution wheels zoom proportionally."""
        if self.loaded is None or delta == 0:
            return
        notches = delta if sys.platform == "darwin" else delta / 120.0
        notches = max(-3.0, min(3.0, notches))
        self._mouse = (cx, cy)
        self.zoom_by(WHEEL_STEP ** notches, cx, cy)

    def apply_theme(self) -> None:
        self.configure(bg=theme.palette()["canvas"])
        if self.loaded is None:
            self.delete("msg")
            self._draw_message()

    @property
    def dragging(self) -> bool:
        """True while a draw/move/resize/pan drag is in progress."""
        return self._mode is not None

    def set_draw_mode(self, on: bool) -> None:
        self.draw_mode = on
        if not on:
            self.delete("cross")
        self._update_cursor()

    def set_show_names(self, on: bool) -> None:
        self.show_names = on
        self.redraw_overlays()

    def select(self, i: Optional[int]) -> None:
        if self.doc is None or (i is not None and not 0 <= i < len(self.doc.boxes)):
            i = None
        if i != self.selected or self.marked:
            self.selected = i
            self.marked = []
            self.redraw_overlays()
            self.on_change(False)

    def set_marked(self, indices: List[int]) -> None:
        """Multi-selection from the box list: the boxes are highlighted and act
        together for copy, delete and copy to the previous/next image. Does not
        call on_change, so the list keeps its own selection."""
        if self.doc is None:
            return
        self._abort_box_drag()
        self.marked = sorted(i for i in set(indices) if 0 <= i < len(self.doc.boxes))
        self.selected = None
        self.redraw_overlays()

    def selected_indices(self) -> List[int]:
        """Indices of the selected boxes (several when multi-selected)."""
        if self.marked:
            return list(self.marked)
        return [] if self.selected is None else [self.selected]

    def _abort_box_drag(self) -> None:
        """Drop an in-progress move/resize of the selected box before the boxes
        change under it (drawing a new box or panning is unaffected)."""
        if self._mode in ("move", "resize"):
            self._cancel_drag()

    def delete_selected(self) -> None:
        indices = self.selected_indices() if self.doc is not None else []
        if indices:
            self._abort_box_drag()
            self.doc.remove_many(indices)
            self.selected = None
            self.marked = []
            self._changed()

    def set_selected_class(self, cls: int) -> bool:
        """Change the class of the selected box. Returns False if nothing selected."""
        if self.doc is None or self.selected is None:
            return False
        self._abort_box_drag()  # otherwise the release would restore the old class
        if not self.doc.set_class(self.selected, cls):
            self.on_status("Not changed: an identical box of that class already exists")
        else:
            self._changed()
        return True

    def copy_box(self) -> None:
        """Copy the boxes multi-selected in the box list; otherwise the box
        under the mouse, or the selected box."""
        if self.doc is None:
            return
        indices = self.marked
        if not indices:
            i = self._hit_box(*self._mouse) if self._mouse is not None else None
            if i is None:
                i = self.selected
            indices = [] if i is None else [i]
        if not indices:
            self.on_status("Move the mouse over a box (or select boxes) to copy")
            return
        boxes = [self.doc.boxes[i] for i in indices]
        self._clipboard = (boxes, self.doc.img_w, self.doc.img_h, self.loaded.path)
        self.on_status("Copied %s" % self.describe(boxes))

    def describe(self, boxes: List[Box]) -> str:
        if len(boxes) == 1:
            return "box: %d: %s" % (boxes[0].cls, self.class_name(boxes[0].cls))
        return "%d boxes" % len(boxes)

    def paste_box(self, at_mouse: bool = False) -> None:
        """Paste the copied boxes at the same relative position (e.g. on the
        next video frame), or centered at the mouse pointer."""
        if self.doc is None:
            return
        if self._clipboard is None:
            self.on_status("Nothing to paste - copy a box first (Ctrl+C)")
            return
        boxes, src_w, src_h, src_path = self._clipboard
        self.paste_boxes(boxes, src_w, src_h, src_path, at_mouse)

    def paste_boxes(self, boxes: List[Box], src_w: int, src_h: int,
                    src_path: Optional[str] = None, at_mouse: bool = False) -> None:
        """Add `boxes` (from an image of size src_w x src_h) to this image as
        one undo step, scaled to the same relative position.

        On another image, boxes already present there are skipped, so copying
        twice never doubles them. On the source image itself, or when placed
        at the mouse, the whole group is shifted to the nearest free spot
        instead, so a paste always adds visible boxes."""
        doc = self.doc
        if doc is None or not boxes:
            return
        sx, sy = doc.img_w / float(src_w), doc.img_h / float(src_h)
        group = [Box(b.cls, b.x1 * sx, b.y1 * sy, b.x2 * sx, b.y2 * sy) for b in boxes]
        shifted = False
        if at_mouse:
            if self._mouse is None:
                self.on_status("Move the mouse over the image to paste there")
                return
            gx1, gy1, gx2, gy2 = _bounds(group)
            cx, cy = self.c2i(*self._mouse)
            group = self._moved(group, cx - (gx1 + gx2) / 2.0, cy - (gy1 + gy2) / 2.0)
        if at_mouse or (self.loaded is not None and self.loaded.path == src_path):
            offset = self._free_offset(group)
            if offset is None:
                self.on_status("Not pasted: no free position (identical boxes already exist)")
                return
            shifted = offset != (0.0, 0.0)
            group = self._moved(group, *offset)
        self._abort_box_drag()
        new = doc.add_many(group)
        skipped = len(group) - len(new)
        if not new:
            self.on_status("Not pasted: %s already on this image"
                           % ("the box is" if len(group) == 1 else "all boxes are"))
            return
        self.selected, self.marked = (new[0], []) if len(new) == 1 else (None, new)
        self._changed()
        self.on_status("Pasted %s%s%s" % (
            self.describe(doc.boxes[new[0]:new[-1] + 1]),
            "  (shifted: identical boxes are already at that position)" if shifted else "",
            "  (%d already on this image, skipped)" % skipped if skipped else ""))

    def _moved(self, group: List[Box], dx: float, dy: float) -> List[Box]:
        """`group` moved by (dx, dy), limited so it stays inside the image."""
        gx1, gy1, gx2, gy2 = _bounds(group)
        dx = max(-gx1, min(dx, self.doc.img_w - gx2)) if gx2 - gx1 <= self.doc.img_w else -gx1
        dy = max(-gy1, min(dy, self.doc.img_h - gy2)) if gy2 - gy1 <= self.doc.img_h else -gy1
        return [Box(b.cls, b.x1 + dx, b.y1 + dy, b.x2 + dx, b.y2 + dy) for b in group]

    def _free_offset(self, group: List[Box]) -> Optional[Tuple[float, float]]:
        """(0, 0) if no box of `group` duplicates an existing box; otherwise the
        nearest diagonal offset (~15 screen-px steps, kept inside the image)
        where none does. None if there is no such offset."""
        doc = self.doc
        step = 15.0 / self.zoom
        gx1, gy1, _, _ = _bounds(group)
        for k in range(30):
            for dx, dy in ((1, 1), (-1, -1), (1, -1), (-1, 1)) if k else ((0, 0),):
                moved = self._moved(group, dx * k * step, dy * k * step)
                if all(find_duplicate(doc.boxes, b.clipped(doc.img_w, doc.img_h),
                                      doc.dup_threshold) is None for b in moved):
                    return moved[0].x1 - group[0].x1, moved[0].y1 - group[0].y1
        return None

    def undo(self) -> None:
        if self.doc is not None:
            self._abort_box_drag()
            if self.doc.undo():
                self.selected = None
                self.marked = []
                self._changed()

    def cancel(self) -> None:
        if self._mode is not None:
            self._cancel_drag()
            self.redraw_overlays()
        else:
            self.select(None)

    # ============================================================ coordinates
    def c2i(self, cx: float, cy: float) -> Tuple[float, float]:
        return (cx - self.ox) / self.zoom, (cy - self.oy) / self.zoom

    def i2c(self, ix: float, iy: float) -> Tuple[float, float]:
        return self.ox + ix * self.zoom, self.oy + iy * self.zoom

    def _clamp_i(self, ix: float, iy: float) -> Tuple[float, float]:
        ow, oh = self.loaded.orig_size
        return min(max(ix, 0.0), ow), min(max(iy, 0.0), oh)

    # ============================================================== rendering
    def request_render(self) -> None:
        if not self._render_pending:
            self._render_pending = True
            self.after_idle(self._render)

    def _on_resize(self) -> None:
        if self.loaded is None:
            self.delete("all")
            self._draw_message()
            return
        at_fit = self.zoom <= self._fit_zoom * 1.0001
        self._fit_zoom = self._calc_fit_zoom()
        if at_fit or self.zoom < self._fit_zoom:
            self.fit()  # stay fitted to the new window size
        else:
            self._clamp_view()
            self.request_render()

    def _render(self) -> None:
        self._render_pending = False
        self.delete("img")
        self._photo = None
        if self.loaded is None:
            return
        img = self.loaded.image
        ow, oh = self.loaded.orig_size
        # Decoded px per original px, per axis: reduced (draft) decoding does not
        # always scale width and height by exactly the same ratio.
        dsx, dsy = img.width / float(ow), img.height / float(oh)
        cw, ch = self.winfo_width(), self.winfo_height()

        # Whole canvas pixels covered by the image, clipped to the window.
        # (The epsilon keeps float error from dropping a 1-px column/row at an edge.)
        eps = 1e-6
        x0 = max(0, int(math.ceil(self.ox - eps)))
        y0 = max(0, int(math.ceil(self.oy - eps)))
        x1 = min(cw, int(math.floor(self.ox + ow * self.zoom + eps)))
        y1 = min(ch, int(math.floor(self.oy + oh * self.zoom + eps)))
        scale = self.zoom / dsx  # canvas px per decoded px
        if x1 > x0 and y1 > y0:
            # Exact (sub-pixel) source rectangle for those canvas pixels, using the
            # same mapping as c2i(), so boxes and pixels stay aligned at any zoom.
            src = (min(max((x0 - self.ox) / self.zoom * dsx, 0.0), img.width),
                   min(max((y0 - self.oy) / self.zoom * dsy, 0.0), img.height),
                   min(max((x1 - self.ox) / self.zoom * dsx, 0.0), img.width),
                   min(max((y1 - self.oy) / self.zoom * dsy, 0.0), img.height))
            if src[2] > src[0] and src[3] > src[1]:
                size = (x1 - x0, y1 - y0)
                if scale >= 3.0:  # crisp pixels when zoomed in
                    region = img.resize(size, _NEAREST, box=src)
                elif scale < 0.5:
                    region = img.resize(size, _BILINEAR, box=src, reducing_gap=2.0)
                else:
                    region = img.resize(size, _BILINEAR, box=src)
                self._photo = ImageTk.PhotoImage(region)
                self.create_image(x0, y0, image=self._photo, anchor="nw", tags="img")
                self.tag_lower("img")

        if not self._full_requested and scale > 1.05:
            self._full_requested = True
            self.on_need_full()
        self.redraw_overlays()

    def _draw_message(self) -> None:
        if self._message:
            self.create_text(self.winfo_width() // 2, self.winfo_height() // 2,
                             text=self._message, fill=theme.palette()["canvas_text"],
                             font=("Segoe UI", 12),
                             tags="msg")

    def _hover_box(self) -> Optional[int]:
        """Box to draw see-through: the smallest box under the mouse, while
        no drag is in progress."""
        if self._mouse is None or self._mode is not None:
            return None
        return self._hit_box(*self._mouse)

    def redraw_overlays(self) -> None:
        self.delete("ov")
        self._hover = None
        if self.loaded is None or self.doc is None:
            return
        self._hover = self._hover_box()
        for i, b in enumerate(self.doc.boxes):
            if i == self.selected and self._drag_box is not None:
                continue
            self._draw_box(b, i == self.selected, i == self._hover, i in self.marked)
        if self._drag_box is not None:
            self._draw_box(self._drag_box.normalized(), True)
        self._draw_crosshair()

    def _draw_box(self, b: Box, selected: bool, hovered: bool = False,
                  marked: bool = False) -> None:
        """A hovered box is drawn as a thin dashed outline, so the object
        underneath stays visible (Tk canvas items have no alpha). Its class
        name and, if selected, its handles are kept; the size label is hidden."""
        color = class_color(b.cls)
        x1, y1 = self.i2c(b.x1, b.y1)
        x2, y2 = self.i2c(b.x2, b.y2)
        if hovered:
            self.create_rectangle(x1, y1, x2, y2, outline=color, width=1, dash=(3, 3),
                                  tags="ov")
        else:
            self.create_rectangle(x1, y1, x2, y2, outline=color,
                                  width=3 if selected or marked else 2, tags="ov")
        if self.show_names:
            name = self.class_name(b.cls)
            tid = self.create_text(x1 + 3, y1 - 2, text=name, anchor="sw",
                                   fill=text_color_on(color), font=("Segoe UI", 9, "bold"),
                                   tags="ov")
            bx = self.bbox(tid)
            if bx[1] < 0:  # no room above: put the label inside the box
                self.move(tid, 0, bx[3] - bx[1] + 2)
                bx = self.bbox(tid)
            rid = self.create_rectangle(bx[0] - 3, bx[1], bx[2] + 3, bx[3], fill=color,
                                        outline=color, tags="ov")
            self.tag_raise(tid, rid)
        if selected:
            for hx, hy in self._handle_points(b).values():
                self.create_rectangle(hx - HANDLE_R, hy - HANDLE_R, hx + HANDLE_R,
                                      hy + HANDLE_R, fill="#ffffff", outline=color,
                                      tags="ov")
            if hovered:
                return
            info ="(%d, %d) - (%d, %d)   %d x %d" % (
                round(b.x1), round(b.y1), round(b.x2), round(b.y2), round(b.w), round(b.h))
            ty = y2 + HANDLE_R + 3
            anchor = "nw"
            if ty + 16 > self.winfo_height():
                ty, anchor = y1 - HANDLE_R - 3, "sw"
                if self.show_names:
                    ty -= 16
            tid = self.create_text(x1, ty, text=info, anchor=anchor, fill="#ffffff",
                                   font=("Consolas", 9), tags="ov")
            bx = self.bbox(tid)
            rid = self.create_rectangle(bx[0] - 2, bx[1] - 1, bx[2] + 2, bx[3] + 1,
                                        fill="#000000", outline="", tags="ov")
            self.tag_raise(tid, rid)

    def _draw_crosshair(self) -> None:
        self.delete("cross")
        if not self.draw_mode or self._mouse is None or self.loaded is None:
            return
        if self._mode not in (None, "draw"):
            return
        x, y = self._mouse
        w, h = self.winfo_width(), self.winfo_height()
        for coords in ((0, y, w, y), (x, 0, x, h)):
            self.create_line(*coords, fill="#ffffff", dash=(4, 4), tags="cross")
        if self._mode == "draw" and self._drag_box is not None:
            b = self._drag_box.normalized()
            self.create_text(x + 12, y + 14, text="%d x %d" % (round(b.w), round(b.h)),
                             anchor="nw", fill="#ffff00", font=("Consolas", 10, "bold"),
                             tags="cross")

    # ============================================================ hit testing
    def _handle_points(self, b: Box):
        x1, y1 = self.i2c(b.x1, b.y1)
        x2, y2 = self.i2c(b.x2, b.y2)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        return {"nw": (x1, y1), "n": (mx, y1), "ne": (x2, y1), "e": (x2, my),
                "se": (x2, y2), "s": (mx, y2), "sw": (x1, y2), "w": (x1, my)}

    def _hit_handle(self, cx: float, cy: float) -> str:
        if self.doc is None or self.selected is None:
            return ""
        for name, (hx, hy) in self._handle_points(self.doc.boxes[self.selected]).items():
            if abs(cx - hx) <= HIT_R and abs(cy - hy) <= HIT_R:
                return name
        return ""

    def _hit_box(self, cx: float, cy: float) -> Optional[int]:
        """Smallest box under the cursor, so nested boxes stay selectable."""
        if self.doc is None:
            return None
        ix, iy = self.c2i(cx, cy)
        best, best_area = None, None
        for i, b in enumerate(self.doc.boxes):
            if b.contains(ix, iy):
                area = b.w * b.h
                if best is None or area < best_area:
                    best, best_area = i, area
        return best

    def _update_cursor(self, cx: Optional[float] = None, cy: Optional[float] = None) -> None:
        if cx is None and self._mouse is not None:
            cx, cy = self._mouse
        cursor = "crosshair" if self.draw_mode else "arrow"
        if cx is not None and self.loaded is not None and self._mode is None:
            h = self._hit_handle(cx, cy)
            if h:
                cursor = _CURSORS[h]
            elif not self.draw_mode:
                if self._hit_box(cx, cy) is not None:
                    cursor = "fleur"  # move box
                elif self.zoom > self._fit_zoom * 1.0001:
                    cursor = "hand2"  # drag to pan the zoomed image
        elif self._mode == "pan":
            cursor = "fleur"
        if str(self["cursor"]) != cursor:
            self.configure(cursor=cursor)

    # ================================================================= events
    def _on_motion(self, e) -> None:
        self._mouse = (e.x, e.y)
        if self.loaded is None:
            return
        ix, iy = self.c2i(e.x, e.y)
        ow, oh = self.loaded.orig_size
        if 0 <= ix < ow and 0 <= iy < oh:
            self.on_cursor("x=%d  y=%d" % (ix, iy))
        else:
            self.on_cursor("")
        self._update_cursor(e.x, e.y)
        if self.doc is not None and self._hover_box() != self._hover:
            self.redraw_overlays()  # also redraws the crosshair
        else:
            self._draw_crosshair()

    def _on_leave(self, _e) -> None:
        self._mouse = None
        self.delete("cross")
        self.on_cursor("")
        if self._hover is not None:
            self.redraw_overlays()

    def _on_press(self, e) -> None:
        """Left button: resize (handle) > move (box) > pan (empty area) when draw
        mode is off; draw when it is on. Ctrl+left-drag always pans."""
        self.focus_set()
        if self.loaded is None or self._mode is not None:
            return
        if (e.state & 0x4) or self.doc is None:
            self._start_pan(e, 1)
            return
        self._press_c = (e.x, e.y)
        self._press_i = self._clamp_i(*self.c2i(e.x, e.y))
        handle = self._hit_handle(e.x, e.y)
        if handle:
            self._mode, self._handle = "resize", handle
            self._orig_box = self.doc.boxes[self.selected]
            return
        if not self.draw_mode:
            hit = self._hit_box(e.x, e.y)
            self.select(hit)
            if hit is not None:
                self._mode = "move"
                self._orig_box = self.doc.boxes[hit]
            else:
                self._start_pan(e, 1)  # drag on empty area moves the image
            return
        if self.active_class() is None:
            self.on_status("Load classes.txt before drawing boxes")
            return
        self._mode = "draw"

    def _on_drag(self, e) -> None:
        self._mouse = (e.x, e.y)
        if self._mode is None or self.loaded is None:
            return
        if self._mode == "pan":
            self._on_pan_drag(e)
            return
        ix, iy = self._clamp_i(*self.c2i(e.x, e.y))
        px, py = self._press_i
        if self._mode == "draw":
            self._drag_box = Box(self.active_class(), px, py, ix, iy)
        elif self._mode == "move":
            b = self._orig_box
            ow, oh = self.loaded.orig_size
            dx = min(max(ix - px, -b.x1), ow - b.x2)
            dy = min(max(iy - py, -b.y1), oh - b.y2)
            self._drag_box = Box(b.cls, b.x1 + dx, b.y1 + dy, b.x2 + dx, b.y2 + dy)
        elif self._mode == "resize":
            b = self._orig_box
            x1, y1, x2, y2 = b.x1, b.y1, b.x2, b.y2
            if "w" in self._handle:
                x1 = ix
            if "e" in self._handle:
                x2 = ix
            if "n" in self._handle:
                y1 = iy
            if "s" in self._handle:
                y2 = iy
            self._drag_box = Box(b.cls, x1, y1, x2, y2)
        self.redraw_overlays()

    def _on_release(self, e) -> None:
        if self._mode == "pan":
            self._on_pan_end(e)
            return
        mode, box = self._mode, self._drag_box
        self._cancel_drag()
        if mode is None or self.doc is None:
            return
        moved = math.hypot(e.x - self._press_c[0], e.y - self._press_c[1]) >= CLICK_PX
        if mode == "draw":
            if not moved or box is None:
                self.select(self._hit_box(e.x, e.y))  # plain click selects
            else:
                box = box.normalized()
                if box.w < self.min_box or box.h < self.min_box:
                    self.on_status("Box too small - ignored")
                else:
                    i = self.doc.add(box)
                    if i is None:
                        self.on_status("Duplicate box ignored (same class, overlapping box exists)")
                    else:
                        self.selected = i
                        self._changed()
                        return
        elif mode in ("move", "resize") and moved and box is not None \
                and self.selected is not None:
            box = box.normalized()
            if box.w < self.min_box or box.h < self.min_box:
                self.on_status("Box too small - change discarded")
            elif not self.doc.update(self.selected, box):
                self.on_status("Change discarded: it would duplicate another box")
            else:
                self._changed()
                return
        self.redraw_overlays()
        self._update_cursor(e.x, e.y)

    def _cancel_drag(self) -> None:
        self._mode = None
        self._drag_box = None
        self._orig_box = None
        self._handle = ""

    def _on_pan_start(self, e) -> None:
        """Middle/right button press."""
        if self.loaded is None or self._mode is not None:
            return
        self._start_pan(e, e.num)

    def _start_pan(self, e, button: int) -> None:
        self._mode = "pan"
        self._pan_button = button
        self._press_c = (e.x, e.y)
        self._pan_origin = (self.ox, self.oy)
        self._update_cursor()

    def _on_pan_drag(self, e) -> None:
        if self._mode != "pan":
            return
        dx, dy = e.x - self._press_c[0], e.y - self._press_c[1]
        self.ox = self._pan_origin[0] + dx
        self.oy = self._pan_origin[1] + dy
        self._clamp_view()
        # Re-base on the clamped view so reversing direction at an edge
        # responds immediately instead of first "unwinding" the overshoot.
        self._pan_origin = (self.ox - dx, self.oy - dy)
        self.request_render()

    def _on_pan_end(self, e) -> None:
        if self._mode == "pan" and e.num == self._pan_button:
            self._mode = None
            self._pan_button = 0
            self._update_cursor(e.x, e.y)

    def _changed(self) -> None:
        self.redraw_overlays()
        self._update_cursor()
        self.on_change(True)
