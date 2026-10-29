"""Light and dark color themes.

ttk widgets are styled through ttk.Style (the "clam" theme is used because the
native Windows themes ignore custom colors). Classic tk widgets (canvases,
tk.Button, Listbox, Toplevel) read colors from `palette()` and are refreshed by
their owner's `apply_theme()` when the theme changes.
"""

import tkinter as tk
from tkinter import ttk
from typing import Dict

LIGHT: Dict[str, str] = {
    "bg": "#f3f3f3",            # window and panels
    "fg": "#1e1e1e",            # text
    "fg_muted": "#6b6b6b",      # hints, secondary text
    "fg_warn": "#b06000",
    "button": "#e2e2e2",
    "button_hover": "#d4d4d4",
    "button_pressed": "#c4c4c4",
    "border": "#c2c2c2",
    "field": "#ffffff",         # entries, lists, tables
    "select": "#cce4ff",
    "select_fg": "#000000",
    "accent": "#2d7ff9",        # active toggle buttons
    "accent_fg": "#ffffff",
    "canvas": "#cfcfcf",        # image area around the image
    "canvas_text": "#4a4a4a",
    "ok": "#1a9b3c",            # labelled image
    "info": "#1f6fd1",          # empty label file
    "muted_mark": "#9a9a9a",    # unlabelled / unknown
}

DARK: Dict[str, str] = {
    "bg": "#202124",
    "fg": "#e6e6e6",
    "fg_muted": "#9a9a9a",
    "fg_warn": "#f0a040",
    "button": "#3a3b3e",
    "button_hover": "#4a4b4f",
    "button_pressed": "#57585c",
    "border": "#4a4b4f",
    "field": "#2a2b2e",
    "select": "#264f78",
    "select_fg": "#ffffff",
    "accent": "#3b8cff",
    "accent_fg": "#ffffff",
    "canvas": "#141414",
    "canvas_text": "#a8a8a8",
    "ok": "#4cc76a",
    "info": "#5aa2ff",
    "muted_mark": "#7a7a7a",
}

THEMES = {"light": LIGHT, "dark": DARK}
_current = "light"


def name() -> str:
    return _current


def palette() -> Dict[str, str]:
    return THEMES[_current]


def apply(root: tk.Tk, theme_name: str) -> Dict[str, str]:
    """Switch the global theme and restyle all ttk widgets. Returns the palette."""
    global _current
    _current = theme_name if theme_name in THEMES else "light"
    p = palette()

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=p["bg"], foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["bg"], darkcolor=p["bg"], troughcolor=p["bg"],
                    fieldbackground=p["field"], selectbackground=p["select"],
                    selectforeground=p["select_fg"], insertcolor=p["fg"],
                    focuscolor=p["accent"], arrowcolor=p["fg"])
    style.map(".", foreground=[("disabled", p["fg_muted"])])

    style.configure("TButton", background=p["button"], foreground=p["fg"],
                    bordercolor=p["border"], lightcolor=p["button"], darkcolor=p["button"],
                    padding=(8, 3))
    style.map("TButton",
              background=[("pressed", p["button_pressed"]), ("active", p["button_hover"])],
              lightcolor=[("pressed", p["button_pressed"]), ("active", p["button_hover"])],
              darkcolor=[("pressed", p["button_pressed"]), ("active", p["button_hover"])])

    style.configure("TEntry", fieldbackground=p["field"], foreground=p["fg"],
                    insertcolor=p["fg"], bordercolor=p["border"],
                    lightcolor=p["field"], darkcolor=p["field"])

    style.configure("Treeview", background=p["field"], fieldbackground=p["field"],
                    foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["field"], darkcolor=p["field"])
    style.map("Treeview", background=[("selected", p["select"])],
              foreground=[("selected", p["select_fg"])])
    style.configure("Treeview.Heading", background=p["button"], foreground=p["fg"],
                    bordercolor=p["border"], lightcolor=p["button"], darkcolor=p["button"])
    style.map("Treeview.Heading", background=[("active", p["button_hover"])])

    style.configure("TScrollbar", background=p["button"], troughcolor=p["bg"],
                    bordercolor=p["border"], arrowcolor=p["fg"],
                    lightcolor=p["button"], darkcolor=p["button"])
    style.map("TScrollbar", background=[("active", p["button_hover"]),
                                        ("pressed", p["button_pressed"])])

    style.configure("TPanedwindow", background=p["border"])
    style.configure("Sash", sashthickness=5, gripcount=0, background=p["border"],
                    lightcolor=p["border"], darkcolor=p["border"])
    style.configure("TSeparator", background=p["border"])
    style.configure("Muted.TLabel", foreground=p["fg_muted"])
    style.configure("Warn.TLabel", foreground=p["fg_warn"])

    # Classic tk widgets created later (dialogs) pick these up from the option DB.
    root.configure(bg=p["bg"])
    for pattern, value in (("*Toplevel.background", p["bg"]),
                           ("*Listbox.background", p["field"]),
                           ("*Listbox.foreground", p["fg"]),
                           ("*Listbox.selectBackground", p["select"]),
                           ("*Listbox.selectForeground", p["select_fg"]),
                           ("*Listbox.highlightBackground", p["border"]),
                           ("*Listbox.highlightColor", p["accent"])):
        root.option_add(pattern, value)
    return p
