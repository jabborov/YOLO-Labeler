"""Top toolbar."""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict

from . import theme

AUTOSAVE_ON_BG = "#d93025"  # red while auto-save is ON (both themes)


class Toolbar(ttk.Frame):
    def __init__(self, master, commands: Dict[str, Callable[[], None]], **kw):
        super().__init__(master, padding=(4, 4), **kw)
        self._draw_on = False
        self._names_on = True
        self._autosave_on = True

        def btn(text, key, width=None):
            b = ttk.Button(self, text=text, command=commands[key], width=width)
            b.pack(side="left", padx=2)
            return b

        def sep():
            ttk.Separator(self, orient="vertical").pack(side="left", fill="y", padx=4)

        def toggle(text, key, width=None):
            b = tk.Button(self, text=text, command=commands[key], relief="flat", bd=1,
                          padx=8, pady=2, width=width, highlightthickness=1)
            b.pack(side="left", padx=2)
            return b

        btn("Open Folder", "open_folder")
        btn("Classes.txt", "open_classes")
        sep()
        btn("Save", "save", 6)
        self.autosave_btn = toggle("Auto-save: ON", "toggle_autosave", 14)
        sep()
        self.draw_btn = toggle("Draw Box (W)", "toggle_draw")
        btn("◀ Prev", "prev")
        btn("Next ▶", "next")
        sep()
        btn("Statistics", "statistics")
        btn("Classes", "classes")
        btn("Hotkeys", "hotkeys")
        self.names_btn = toggle("Names: ON", "toggle_names", 10)
        self.theme_btn = btn("Dark mode", "toggle_theme", 11)
        sep()
        # Fixed width so the per-second timer text never re-lays out the toolbar.
        self.timer_lbl = ttk.Label(self, text="", font=("Consolas", 10), width=42)
        self.timer_lbl.pack(side="left", padx=4)
        self.name_lbl = ttk.Label(self, text="", font=("Segoe UI", 10, "bold"), anchor="w")
        self.name_lbl.pack(side="left", padx=4, fill="x", expand=True)
        self.apply_theme()

    def apply_theme(self) -> None:
        self.theme_btn.configure(text="Light mode" if theme.name() == "dark" else "Dark mode")
        self._style_toggle(self.draw_btn, self._draw_on)
        self._style_toggle(self.names_btn, self._names_on)
        self._style_toggle(self.autosave_btn, self._autosave_on, AUTOSAVE_ON_BG)

    @staticmethod
    def _style_toggle(b: tk.Button, on: bool, on_bg: str = "") -> None:
        p = theme.palette()
        on_bg = on_bg or p["accent"]
        bg, fg = (on_bg, "#ffffff") if on else (p["button"], p["fg"])
        b.configure(bg=bg, fg=fg, activebackground=on_bg if on else p["button_hover"],
                    activeforeground=fg, highlightbackground=p["border"],
                    relief="sunken" if on else "flat")

    def set_autosave(self, on: bool) -> None:
        self._autosave_on = on
        self.autosave_btn.configure(text="Auto-save: ON" if on else "Auto-save: OFF")
        self._style_toggle(self.autosave_btn, on, AUTOSAVE_ON_BG)

    def set_draw_key(self, key: str) -> None:
        self.draw_btn.configure(text="Draw Box (%s)" % key if key else "Draw Box")

    def set_draw(self, on: bool) -> None:
        self._draw_on = on
        self._style_toggle(self.draw_btn, on)

    def set_names(self, on: bool) -> None:
        self._names_on = on
        self.names_btn.configure(text="Names: ON" if on else "Names: OFF")
        self._style_toggle(self.names_btn, on)

    def set_timer(self, text: str) -> None:
        if self.timer_lbl.cget("text") != text:
            self.timer_lbl.configure(text=text)

    def set_image_name(self, text: str) -> None:
        if self.name_lbl.cget("text") != text:
            self.name_lbl.configure(text=text)
