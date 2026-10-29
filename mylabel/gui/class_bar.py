"""Row of class buttons that wraps onto extra lines when there are many classes.

Only the classes selected in the Classes dialog get a button. Each button shows
the class id ("0: person"). Keys 1-9 and 0 refer to the first ten *visible*
buttons, not to class ids.
"""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional

from . import theme
from .colors import class_color, readable_on, text_color_on


class ClassBar(ttk.Frame):
    def __init__(self, master, **kw):
        super().__init__(master, height=30, **kw)
        self.grid_propagate(False)  # height is set explicitly by _layout
        self.on_pick: Callable[[int], None] = lambda cls: None
        self.buttons: Dict[int, tk.Button] = {}  # class id -> button, in display order
        self.visible: List[int] = []             # class ids shown, in display order
        self.active: Optional[int] = None
        self._placeholder = ttk.Label(self, text="No classes loaded - use Classes.txt",
                                      style="Muted.TLabel")
        self._placeholder.grid(row=0, column=0, sticky="w", padx=4, pady=3)
        self._last_width = 0
        self.bind("<Configure>", self._on_configure)

    def set_classes(self, names: List[str], visible: Optional[List[int]] = None) -> None:
        """Show buttons for `visible` class ids (all classes if None)."""
        for b in self.buttons.values():
            b.destroy()
        self.buttons = {}
        if visible is None:
            visible = list(range(len(names)))
        self.visible = [c for c in visible if 0 <= c < len(names)]
        for cls in self.visible:
            color = class_color(cls)
            # Class id as written in the YOLO label files (0-based line in classes.txt).
            self.buttons[cls] = tk.Button(
                self, text="%d: %s" % (cls, names[cls]), activebackground=color,
                activeforeground=text_color_on(color), relief="raised", bd=1, padx=8, pady=1,
                font=("Segoe UI", 9, "bold"), highlightthickness=3,
                highlightbackground=color, highlightcolor=color,
                command=lambda c=cls: self.on_pick(c))
        if self.buttons:
            self._placeholder.grid_remove()
        else:
            self._placeholder.configure(
                text="No classes selected - use Classes" if names
                else "No classes loaded - use Classes.txt")
            self._placeholder.grid()
            self.configure(height=30)
        self.set_active(self.active if self.active in self.buttons
                        else (self.visible[0] if self.visible else None))

    def class_at(self, pos: int) -> Optional[int]:
        """Class id of the visible button at position `pos` (0-based)."""
        return self.visible[pos] if 0 <= pos < len(self.visible) else None

    def set_active(self, cls: Optional[int]) -> None:
        self.active = cls
        p = theme.palette()
        for c, b in self.buttons.items():
            color = class_color(c)
            if c == cls:
                b.configure(bg=color, fg=text_color_on(color), relief="sunken")
            else:
                # Class name in the class's own color (adjusted for readability).
                b.configure(bg=p["button"], fg=readable_on(color, p["button"]),
                            relief="raised")
        self._layout()

    def apply_theme(self) -> None:
        self.set_active(self.active)

    def _on_configure(self, e) -> None:
        if e.width != self._last_width:
            self._last_width = e.width
            self._layout()

    def _layout(self) -> None:
        """Place buttons left to right, wrapping at the frame width."""
        if not self.buttons:
            return
        width = max(self.winfo_width(), 200)
        x, y, row_h = 2, 2, 0
        for b in self.buttons.values():
            w, h = b.winfo_reqwidth(), b.winfo_reqheight()
            if x + w > width and x > 2:
                x, y = 2, y + row_h + 2
            b.place(x=x, y=y)
            x += w + 3
            row_h = max(row_h, h)
        height = y + row_h + 2
        if int(self.cget("height") or 0) != height:
            self.configure(height=height)
