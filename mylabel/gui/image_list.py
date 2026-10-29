"""Virtualized image list: only the visible rows are fetched and drawn, so it
scrolls hundreds of thousands of entries as fast as a hundred."""

import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional, Tuple

from . import theme

ROW_H = 20
STATUS_W = 44


class ImageList(ttk.Frame):
    def __init__(self, master, fetch_rows: Callable[[int, int], List[Tuple[int, str, Optional[int]]]],
                 **kw):
        super().__init__(master, **kw)
        self.fetch_rows = fetch_rows
        self.on_select: Callable[[int], None] = lambda idx: None
        self.on_find: Callable[[str], None] = lambda text: None
        self.on_next_unlabelled: Callable[[], None] = lambda: None

        self.count = 0
        self.top = 0
        self.current: Optional[int] = None

        head = ttk.Frame(self)
        head.pack(fill="x", pady=(0, 3))
        self.title = ttk.Label(head, text="Images", font=("Segoe UI", 10, "bold"))
        self.title.pack(side="left")
        ttk.Button(head, text="Next unlabelled", width=15,
                   command=lambda: self.on_next_unlabelled()).pack(side="right")

        find = ttk.Frame(self)
        find.pack(fill="x", pady=(0, 3))
        self.find_var = tk.StringVar()
        ent = ttk.Entry(find, textvariable=self.find_var)
        ent.pack(side="left", fill="x", expand=True)
        ent.bind("<Return>", lambda e: self._find())
        ttk.Button(find, text="Go", width=4, command=self._find).pack(side="left", padx=(3, 0))
        ttk.Label(self, text="Enter an image number or part of a file name",
                  style="Muted.TLabel", font=("Segoe UI", 8)).pack(anchor="w")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, highlightthickness=1)
        self.sb = ttk.Scrollbar(body, orient="vertical", command=self._on_scrollbar)
        self.sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Button-1>", self._on_click)
        # Mouse-wheel scrolling is routed here by the application (App._on_wheel).
        self.apply_theme()

    # ---------------------------------------------------------------- public
    def set_count(self, n: int, suffix: str = "") -> None:
        self.count = n
        self.title.configure(text="Images (%s)%s" % (format(n, ","), suffix))
        self.top = max(0, min(self.top, n - self._visible_rows()))
        self.redraw()

    def set_current(self, idx: Optional[int]) -> None:
        self.current = idx
        if idx is not None:
            vis = self._visible_rows()
            if idx < self.top or idx >= self.top + vis:
                self.top = max(0, idx - vis // 3)
        self.redraw()

    def scroll(self, rows: int) -> None:
        self.top = max(0, min(self.top + rows, self.count - self._visible_rows()))
        self.redraw()

    def apply_theme(self) -> None:
        p = theme.palette()
        self.canvas.configure(bg=p["field"], highlightbackground=p["border"],
                              highlightcolor=p["border"])
        self.redraw()

    def redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        p = theme.palette()
        vis = self._visible_rows()
        width = c.winfo_width()
        if self.count:
            for idx, rel, nboxes in self.fetch_rows(self.top, self.top + vis + 1):
                y = (idx - self.top) * ROW_H
                text_fg = p["fg"]
                if idx == self.current:
                    c.create_rectangle(0, y, width, y + ROW_H, fill=p["select"], outline="")
                    text_fg = p["select_fg"]
                if nboxes is None:
                    mark, color = "?", p["muted_mark"]
                elif nboxes < 0:
                    mark, color = "-", p["muted_mark"]
                elif nboxes == 0:
                    mark, color = "0", p["info"]
                else:
                    mark, color = "✓%d" % nboxes, p["ok"]
                c.create_text(6, y + ROW_H / 2, text=mark, anchor="w", fill=color,
                              font=("Segoe UI", 9, "bold"))
                c.create_text(STATUS_W, y + ROW_H / 2, text="%d  %s" % (idx + 1, rel),
                              anchor="w", fill=text_fg, font=("Segoe UI", 9))
        if self.count > 0:
            self.sb.set(self.top / self.count, min(1.0, (self.top + vis) / self.count))
        else:
            self.sb.set(0, 1)

    # --------------------------------------------------------------- private
    def _visible_rows(self) -> int:
        return max(1, self.canvas.winfo_height() // ROW_H)

    def _on_scrollbar(self, *args) -> None:
        if args[0] == "moveto":
            self.top = int(float(args[1]) * self.count)
            self.scroll(0)
        elif args[0] == "scroll":
            step = int(args[1]) * (self._visible_rows() if args[2] == "pages" else 1)
            self.scroll(step)

    def _on_click(self, e) -> None:
        idx = self.top + e.y // ROW_H
        if 0 <= idx < self.count:
            self.on_select(idx)

    def _find(self) -> None:
        text = self.find_var.get().strip()
        if text:
            self.on_find(text)
