"""Statistics and class-list dialogs."""

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional

from . import theme
from .colors import class_color, readable_on


def _fmt(n) -> str:
    return format(int(n or 0), ",")


def place_over(win: tk.Toplevel, master, width: Optional[int] = None,
               height: Optional[int] = None) -> None:
    """Center `win` over the main window, on whichever monitor that window is,
    then show it. Create the dialog withdrawn so it never flashes at the
    default position (often another monitor).

    Monitors left of / above the primary display have negative coordinates;
    they are kept as is ("+-1500+200" is valid Tk geometry), never clamped to 0.
    """
    win.update_idletasks()
    top = master.winfo_toplevel()
    w = width or win.winfo_reqwidth()
    h = height or win.winfo_reqheight()
    x = top.winfo_rootx() + (top.winfo_width() - w) // 2
    y = top.winfo_rooty() + (top.winfo_height() - h) // 3
    size = "%dx%d" % (w, h) if width and height else ""
    win.geometry("%s+%d+%d" % (size, x, y))
    win.deiconify()
    win.lift()


class StatisticsDialog(tk.Toplevel):
    """Shows dataset statistics. `compute(callback)` must call back from any
    thread with a stats dict; the result is marshalled to the Tk thread."""

    def __init__(self, master, compute: Callable[[Callable[[Dict], None]], None],
                 class_names: List[str], session: Dict[str, str],
                 indexing_note: str, on_rebuild: Callable[[], None]):
        super().__init__(master)
        self.withdraw()  # shown by place_over() once positioned
        self.title("Statistics")
        self.transient(master)
        self.compute = compute
        self.class_names = class_names
        self.on_rebuild = on_rebuild
        self._result: Optional[Dict] = None

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        self.summary = ttk.Label(frm, text="Computing...", justify="left",
                                 font=("Consolas", 10))
        self.summary.pack(anchor="w")
        if indexing_note:
            ttk.Label(frm, text=indexing_note, style="Warn.TLabel").pack(anchor="w", pady=(4, 0))

        ttk.Label(frm, text="Boxes per class", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(10, 2))
        cols = ("class", "boxes", "images")
        self.tree = ttk.Treeview(frm, columns=cols, show="headings", height=10)
        for c, w in zip(cols, (240, 100, 100)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w" if c == "class" else "e")
        self.tree.pack(fill="both", expand=True)

        ttk.Label(frm, text="This session", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(10, 2))
        ttk.Label(frm, text="\n".join("%-22s %s" % (k, v) for k, v in session.items()),
                  font=("Consolas", 10), justify="left").pack(anchor="w")

        bar = ttk.Frame(frm)
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="Rebuild index", command=self._rebuild).pack(side="left")
        ttk.Button(bar, text="Refresh", command=self._refresh).pack(side="left", padx=4)
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        place_over(self, master, 520, 560)
        self._refresh()

    def _refresh(self) -> None:
        self.summary.configure(text="Computing...")
        self._result = None
        self.compute(self._deliver)
        self._wait()

    def _deliver(self, stats: Dict) -> None:  # worker thread
        self._result = stats

    def _wait(self) -> None:
        if not self.winfo_exists():
            return
        if self._result is None:
            self.after(100, self._wait)
        else:
            self._show(self._result)

    def _show(self, s: Dict) -> None:
        if "error" in s:
            self.summary.configure(text="Error: " + s["error"])
            return
        total = s["total"] or 0
        pct = 100.0 * s["labelled"] / total if total else 0.0
        lines = [
            ("Images", _fmt(total)),
            ("Labelled", "%s  (%.2f%%)" % (_fmt(s["labelled"]), pct)),
            ("  with boxes", _fmt(s["nonempty"])),
            ("  empty (negative)", _fmt(s["empty"])),
            ("Unlabelled", _fmt(s["missing"])),
            ("Not scanned yet", _fmt(s["unknown"])),
            ("Total boxes", _fmt(s["boxes"])),
        ]
        self.summary.configure(text="\n".join("%-22s %s" % kv for kv in lines))
        self.tree.delete(*self.tree.get_children())
        field = theme.palette()["field"]
        for cls, n, imgs in s["per_class"]:
            name = self.class_names[cls] if 0 <= cls < len(self.class_names) else "(unknown)"
            # Same color as the class buttons, adjusted for readability.
            tag = "cls%d" % cls
            self.tree.tag_configure(tag, foreground=readable_on(class_color(cls), field))
            self.tree.insert("", "end", tags=(tag,),
                             values=("%d: %s" % (cls, name), _fmt(n), _fmt(imgs)))

    def _rebuild(self) -> None:
        if messagebox.askyesno(
                "Rebuild index",
                "Rescan the folder for images and re-read all label files?\n"
                "Use this after adding/removing images or editing labels outside this tool.",
                parent=self):
            self.on_rebuild()
            self.destroy()


class ClassesDialog(tk.Toplevel):
    """Checkbox list of all classes; the checked ones get a button in the class bar."""

    def __init__(self, master, names: List[str], visible: List[int],
                 on_apply: Callable[[List[int]], None], classes_path: str):
        super().__init__(master)
        self.withdraw()  # shown by place_over() once positioned
        self.title("Classes")
        self.transient(master)
        self.names = names
        self.on_apply = on_apply
        p = theme.palette()
        shown = set(visible)
        self.vars = [tk.BooleanVar(value=i in shown) for i in range(len(names))]

        frm = ttk.Frame(self, padding=8)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=classes_path or "(no classes.txt loaded)",
                  style="Muted.TLabel", wraplength=350).pack(anchor="w")
        self.count_lbl = ttk.Label(frm, text="", font=("Segoe UI", 10, "bold"))
        self.count_lbl.pack(anchor="w", pady=(2, 4))

        tools = ttk.Frame(frm)
        tools.pack(fill="x", pady=(0, 4))
        self.filter_var = tk.StringVar()
        ent = ttk.Entry(tools, textvariable=self.filter_var)
        ent.pack(side="left", fill="x", expand=True)
        self.filter_var.trace_add("write", lambda *a: self._apply_filter())
        for text, fn in (("All", self._all), ("None", self._none), ("Invert", self._invert)):
            ttk.Button(tools, text=text, width=6, command=fn).pack(side="left", padx=(3, 0))
        ttk.Label(frm, text="Type to filter; All/None/Invert act on the filtered list",
                  style="Muted.TLabel", font=("Segoe UI", 8)).pack(anchor="w")

        body = ttk.Frame(frm)
        body.pack(fill="both", expand=True, pady=(4, 0))
        self.canvas = tk.Canvas(body, bg=p["field"], highlightthickness=1,
                                highlightbackground=p["border"])
        sb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=p["field"])
        win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        # Used by App._on_wheel, which routes wheel events to the widget under the mouse.
        self.canvas.wheel_handler = lambda delta: self.canvas.yview_scroll(
            -3 if delta > 0 else 3, "units")

        self.rows = []
        for i, name in enumerate(names):
            color = readable_on(class_color(i), p["field"])
            row = tk.Frame(self.inner, bg=p["field"])
            tk.Label(row, text="■", fg=class_color(i), bg=p["field"],
                     font=("Segoe UI", 11)).pack(side="left", padx=(4, 2))
            tk.Checkbutton(row, text="%3d  %s" % (i, name), variable=self.vars[i],
                           command=self._update_count, anchor="w", bg=p["field"], fg=color,
                           activebackground=p["field"], activeforeground=color,
                           selectcolor=p["field"], font=("Segoe UI", 10, "bold"),
                           highlightthickness=0, bd=0).pack(side="left", fill="x", expand=True)
            self.rows.append(row)
        self._apply_filter()

        bar = ttk.Frame(frm)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="Apply", command=self._apply).pack(side="right")
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._apply())
        self._update_count()
        place_over(self, master, 380, 560)
        ent.focus_set()

    def _filtered(self) -> List[int]:
        text = self.filter_var.get().strip().lower()
        return [i for i, n in enumerate(self.names)
                if not text or text in n.lower() or text == str(i)]

    def _apply_filter(self) -> None:
        for row in self.rows:
            row.pack_forget()
        for i in self._filtered():
            self.rows[i].pack(fill="x", anchor="w")
        self.canvas.yview_moveto(0)

    def _set(self, value_of: Callable[[bool], bool]) -> None:
        for i in self._filtered():
            self.vars[i].set(value_of(self.vars[i].get()))
        self._update_count()

    def _all(self) -> None:
        self._set(lambda v: True)

    def _none(self) -> None:
        self._set(lambda v: False)

    def _invert(self) -> None:
        self._set(lambda v: not v)

    def _update_count(self) -> None:
        n = sum(v.get() for v in self.vars)
        self.count_lbl.configure(text="Showing %d of %d classes" % (n, len(self.names)))

    def _apply(self) -> None:
        selected = [i for i, v in enumerate(self.vars) if v.get()]
        if self.names and not selected:
            messagebox.showwarning("Classes", "Select at least one class.", parent=self)
            return
        self.on_apply(selected)
        self.destroy()


class UnsavedChangesDialog(tk.Toplevel):
    """Modal Save / Don't Save / Cancel prompt. `result` is "save", "discard"
    or "cancel"."""

    def __init__(self, master, image_name: str):
        super().__init__(master)
        self.withdraw()  # shown by place_over() once positioned
        self.title("Unsaved changes")
        self.transient(master)
        self.resizable(False, False)
        self.result = "cancel"
        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Save changes to the annotations of this image?",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(frm, text=image_name, style="Muted.TLabel",
                  wraplength=420).pack(anchor="w", pady=(4, 14))
        bar = ttk.Frame(frm)
        bar.pack(fill="x")
        ttk.Button(bar, text="Cancel", command=lambda: self._close("cancel")).pack(side="right")
        ttk.Button(bar, text="Don't Save",
                   command=lambda: self._close("discard")).pack(side="right", padx=6)
        save = ttk.Button(bar, text="Save", command=lambda: self._close("save"))
        save.pack(side="right")
        self.protocol("WM_DELETE_WINDOW", lambda: self._close("cancel"))
        self.bind("<Escape>", lambda e: self._close("cancel"))
        self.bind("<Return>", lambda e: self._close("save"))
        place_over(self, master)
        try:
            self.wait_visibility()  # grab_set fails on a window that is not yet mapped
            self.grab_set()
        except tk.TclError:
            pass
        save.focus_set()

    def _close(self, result: str) -> None:
        self.result = result
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    @classmethod
    def ask(cls, master, image_name: str) -> str:
        dlg = cls(master, image_name)
        master.wait_window(dlg)
        return dlg.result
