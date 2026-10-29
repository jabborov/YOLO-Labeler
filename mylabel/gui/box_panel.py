"""Bounding-box information panel for the current image."""

import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional, Tuple

from ..core.annotation import Box
from . import theme
from .colors import class_color, readable_on

COLUMNS = (("#", 34), ("class", 110), ("x1", 50), ("y1", 50), ("x2", 50), ("y2", 50),
           ("w", 46), ("h", 46))


class BoxPanel(ttk.Frame):
    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.on_select: Callable[[Optional[int]], None] = lambda i: None
        self.on_select_many: Callable[[List[int]], None] = lambda indices: None
        self.on_delete: Callable[[], None] = lambda: None
        self.on_copy_prev: Callable[[], None] = lambda: None
        self.on_copy_next: Callable[[], None] = lambda: None
        self._updating = False
        self._tags = set()  # class color tags configured on the tree

        head = ttk.Frame(self)
        head.pack(fill="x", pady=(0, 3))
        self.title = ttk.Label(head, text="Bounding boxes", font=("Segoe UI", 10, "bold"))
        self.title.pack(side="left")
        ttk.Button(head, text="Delete", width=7,
                   command=lambda: self.on_delete()).pack(side="right")
        ttk.Button(head, text="Copy ▶", width=7,
                   command=lambda: self.on_copy_next()).pack(side="right", padx=(0, 3))
        ttk.Button(head, text="◀ Copy", width=7,
                   command=lambda: self.on_copy_prev()).pack(side="right", padx=(0, 3))
        ttk.Button(head, text="All", width=4,
                   command=self.select_all).pack(side="right", padx=(0, 3))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        # "extended": Ctrl+click / Shift+click select several boxes.
        self.tree = ttk.Treeview(body, columns=[c for c, _ in COLUMNS], show="headings",
                                 selectmode="extended", height=8)
        for col, w in COLUMNS:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, minwidth=30, anchor="w" if col == "class" else "e",
                             stretch=(col == "class"))
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        self.detail = tk.StringVar()
        ttk.Label(self, textvariable=self.detail, font=("Consolas", 9),
                  justify="left").pack(anchor="w", pady=(3, 0))
        ttk.Label(self, text="Ctrl/Shift+click selects several boxes; ◀ Copy / Copy ▶ "
                             "copies them to the previous / next image",
                  style="Muted.TLabel", font=("Segoe UI", 8)).pack(anchor="w")

    def update_boxes(self, boxes: List[Box], selected: List[int],
                     class_name: Callable[[int], str], img_size: Optional[Tuple[int, int]]) -> None:
        self._updating = True
        try:
            self.tree.delete(*self.tree.get_children())
            for i, b in enumerate(boxes):
                self.tree.insert("", "end", iid=str(i), tags=(self._class_tag(b.cls),), values=(
                    i + 1, "%d: %s" % (b.cls, class_name(b.cls)),
                    round(b.x1), round(b.y1), round(b.x2), round(b.y2),
                    round(b.w), round(b.h)))
            self.title.configure(text="Bounding boxes (%d)" % len(boxes))
            selected = [i for i in selected if 0 <= i < len(boxes)]
            if selected:
                self.tree.selection_set([str(i) for i in selected])
                self.tree.see(str(selected[0]))
            if len(selected) == 1 and img_size:
                self.detail.set("YOLO: " + boxes[selected[0]].to_yolo(*img_size))
            elif len(selected) > 1:
                self.detail.set("%d boxes selected" % len(selected))
            else:
                self.detail.set("Image size: %d x %d" % img_size if img_size else "")
        finally:
            self._updating = False

    def select_all(self) -> None:
        items = self.tree.get_children()
        if items:
            self.tree.selection_set(items)  # reported through <<TreeviewSelect>>

    def _class_tag(self, cls: int) -> str:
        """Row tag that draws the text in the class's color, as on the class buttons."""
        tag = "cls%d" % cls
        if tag not in self._tags:
            self._tags.add(tag)
            self._color_tag(cls)
        return tag

    def _color_tag(self, cls: int) -> None:
        self.tree.tag_configure("cls%d" % cls,
                                foreground=readable_on(class_color(cls), theme.palette()["field"]))

    def apply_theme(self) -> None:
        for tag in self._tags:
            self._color_tag(int(tag[3:]))

    def clear(self) -> None:
        self.update_boxes([], [], str, None)

    def _on_tree_select(self, _e) -> None:
        if self._updating:
            return
        sel = [int(s) for s in self.tree.selection()]
        if len(sel) > 1:
            self.detail.set("%d boxes selected" % len(sel))
            self.on_select_many(sel)
        else:
            self.on_select(sel[0] if sel else None)
