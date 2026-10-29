"""User-configurable hotkeys: action list, key-combination names and the
Hotkeys dialog.

A combination is stored as a canonical string such as "D", "Left", "Ctrl+S",
"Ctrl+Shift+Z" or "KP_Add" (modifiers in the order Ctrl, Alt, Shift, then the
Tk keysym; letters upper-case). The same function, `combo_from_event`, is used
when recording a key in the dialog and when dispatching a key press, so a
recorded combination always matches the event that produced it.
"""

import sys
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional

from .dialogs import place_over

# (action id, label, default keys)
ACTIONS = [
    ("prev_image", "Previous image", ["A", "Left"]),
    ("next_image", "Next image", ["D", "Right"]),
    ("next_unlabelled", "Next unlabelled image", ["U"]),
    ("toggle_draw", "Draw Box mode on/off", ["W"]),
    ("delete_box", "Delete selected box", ["Delete", "BackSpace"]),
    ("cancel", "Cancel drag / deselect", ["Escape"]),
    ("undo", "Undo", ["Ctrl+Z"]),
    ("copy_box", "Copy box(es) (selected in list, else under mouse)", ["Ctrl+C"]),
    ("paste_box", "Paste box(es) at the same position", ["Ctrl+V"]),
    ("paste_box_at_mouse", "Paste box(es) at the mouse", ["Ctrl+Shift+V"]),
    ("copy_to_prev", "Copy selected boxes to previous image", []),
    ("copy_to_next", "Copy selected boxes to next image", []),
    ("save", "Save", ["Ctrl+S"]),
    ("toggle_autosave", "Auto-save on/off", []),
    ("open_folder", "Open folder", ["Ctrl+O"]),
    ("zoom_in", "Zoom in", ["plus", "equal", "KP_Add"]),
    ("zoom_out", "Zoom out", ["minus", "KP_Subtract"]),
    ("fit", "Fit image to window", ["F"]),
    ("toggle_names", "Class names on/off", ["N"]),
    ("toggle_theme", "Light / dark mode", ["T"]),
    ("statistics", "Statistics window", []),
    ("classes", "Classes window", []),
    ("hotkeys", "Hotkeys window", []),
] + [("class_%d" % n, "Class button %d" % n, [str(n % 10)]) for n in range(1, 11)]

LABELS = {a: label for a, label, _ in ACTIONS}

SHIFT, CTRL = 0x1, 0x4
ALT = 0x20000 if sys.platform == "win32" else 0x8

MODIFIER_KEYS = {
    "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R",
    "Super_L", "Super_R", "Win_L", "Win_R", "Caps_Lock", "Num_Lock", "Scroll_Lock",
    "ISO_Level3_Shift", "App", "??",
}

KEY_NAMES = {
    "plus": "+", "minus": "-", "equal": "=", "comma": ",", "period": ".", "slash": "/",
    "backslash": "\\", "semicolon": ";", "apostrophe": "'", "quoteright": "'",
    "bracketleft": "[", "bracketright": "]", "grave": "`", "quoteleft": "`",
    "Return": "Enter", "BackSpace": "Backspace", "Escape": "Esc", "space": "Space",
    "Prior": "PageUp", "Next": "PageDown",
}
KP_NAMES = {"Add": "+", "Subtract": "-", "Multiply": "*", "Divide": "/", "Decimal": "."}


def defaults() -> Dict[str, List[str]]:
    return {a: list(keys) for a, _, keys in ACTIONS}


def load(saved) -> Dict[str, List[str]]:
    """Defaults overridden by the saved settings (unknown actions are ignored)."""
    bindings = defaults()
    if isinstance(saved, dict):
        for a, keys in saved.items():
            if a in bindings and isinstance(keys, list):
                bindings[a] = [k for k in keys if isinstance(k, str) and k]
    return bindings


def key_map(bindings: Dict[str, List[str]]) -> Dict[str, str]:
    """combination -> action. If a combination is listed twice, the first action wins."""
    result: Dict[str, str] = {}
    for a, _, _ in ACTIONS:
        for k in bindings.get(a, []):
            result.setdefault(k, a)
    return result


def combo_from_event(e) -> Optional[str]:
    """Canonical combination for a <KeyPress> event, None for a lone modifier."""
    key = e.keysym
    if not key or key in MODIFIER_KEYS:
        return None
    letter = len(key) == 1 and key.isalpha()
    if letter:
        key = key.upper()
    char = e.char or ""
    # For printed symbols Shift is already part of the key ("plus", "exclam"),
    # so it is not added again; for letters and named keys it is.
    symbol = not letter and len(char) == 1 and char.isprintable() and not char.isspace()
    mods = []
    if e.state & CTRL:
        mods.append("Ctrl")
    if e.state & ALT:
        mods.append("Alt")
    if e.state & SHIFT and not symbol:
        mods.append("Shift")
    return "+".join(mods + [key])


def has_command_modifier(combo: str) -> bool:
    """True for Ctrl/Alt combinations, which also work while typing in a text box."""
    return combo.startswith(("Ctrl+", "Alt+"))


def display(combo: str) -> str:
    """Readable name of a combination, e.g. "Ctrl+S", "Num +", "PageUp"."""
    mods, _, key = combo.rpartition("+")
    if key.startswith("KP_"):  # numeric keypad
        name = "Num " + KP_NAMES.get(key[3:], key[3:])
    else:
        name = KEY_NAMES.get(key, key)
    return mods + "+" + name if mods else name


class KeyCaptureDialog(tk.Toplevel):
    """Modal window that records one key combination. `result` is the
    canonical combination, or None if cancelled."""

    def __init__(self, master, action_label: str):
        super().__init__(master)
        self.withdraw()  # shown by place_over() once positioned
        self.title("Set hotkey")
        self.transient(master)
        self.resizable(False, False)
        self.result: Optional[str] = None
        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=action_label, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(frm, text="Press a key or a combination (e.g. Ctrl+Shift+S).",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 8))
        self.preview = ttk.Label(frm, text="...", font=("Consolas", 12, "bold"))
        self.preview.pack(anchor="w")
        ttk.Button(frm, text="Cancel", command=self._close,
                   takefocus=False).pack(anchor="e", pady=(12, 0))
        self.protocol("WM_DELETE_WINDOW", self._close)
        # On the toplevel itself, so "break" also stops Tab traversal and Escape
        # (both can be recorded as hotkeys; use the Cancel button to cancel).
        self.bind("<KeyPress>", self._on_key)
        place_over(self, master)
        try:
            self.wait_visibility()  # grab_set fails on a window that is not yet mapped
            self.grab_set()
        except tk.TclError:
            pass
        self.focus_force()

    def _on_key(self, e):
        combo = combo_from_event(e)
        if combo is None:  # modifier only: show it and wait for the key
            # e.state does not yet include the modifier being pressed, so check the keysym too.
            mods = [name for bit, name, sym in ((CTRL, "Ctrl", "Control"), (ALT, "Alt", "Alt"),
                                                (SHIFT, "Shift", "Shift"))
                    if e.state & bit or e.keysym.startswith(sym)]
            self.preview.configure(text="+".join(mods) + "+..." if mods else "...")
        else:
            self.result = combo
            self._close()
        return "break"

    def _close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    @classmethod
    def ask(cls, master, action_label: str) -> Optional[str]:
        dlg = cls(master, action_label)
        master.wait_window(dlg)
        return dlg.result


class HotkeysDialog(tk.Toplevel):
    """Lists every action with its keys; the user can change, add or clear them."""

    def __init__(self, master, bindings: Dict[str, List[str]],
                 on_apply: Callable[[Dict[str, List[str]]], None]):
        super().__init__(master)
        self.withdraw()  # shown by place_over() once positioned
        self.title("Hotkeys")
        self.transient(master)
        self.on_apply = on_apply
        self.bindings = {a: list(keys) for a, keys in bindings.items()}

        frm = ttk.Frame(self, padding=8)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Double-click an action (or press Change) and then press the new "
                            "key. Ctrl, Alt and Shift combinations are allowed. An action can "
                            "have several keys.",
                  style="Muted.TLabel", wraplength=480, justify="left").pack(anchor="w", pady=(0, 6))

        body = ttk.Frame(frm)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=("action", "keys"), show="headings",
                                 selectmode="browse")
        self.tree.heading("action", text="Action")
        self.tree.heading("keys", text="Keys")
        self.tree.column("action", width=220, anchor="w")
        self.tree.column("keys", width=260, anchor="w")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        for a, label, _ in ACTIONS:
            self.tree.insert("", "end", iid=a, values=(label, ""))
        self.tree.bind("<Double-1>", lambda e: self._capture(replace=True))
        self.tree.bind("<Return>", lambda e: self._capture(replace=True))
        self._refresh()

        tools = ttk.Frame(frm)
        tools.pack(fill="x", pady=(6, 0))
        for text, fn in (("Change...", lambda: self._capture(replace=True)),
                         ("Add key...", lambda: self._capture(replace=False)),
                         ("Clear", self._clear), ("Default", self._default)):
            ttk.Button(tools, text=text, command=fn).pack(side="left", padx=(0, 3))

        bar = ttk.Frame(frm)
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="Reset all", command=self._reset_all).pack(side="left")
        ttk.Button(bar, text="Save", command=self._apply).pack(side="right")
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        self.bind("<Escape>", lambda e: self.destroy())
        place_over(self, master, 540, 620)
        first = ACTIONS[0][0]
        self.tree.selection_set(first)
        self.tree.focus(first)
        self.tree.focus_set()

    def _selected(self) -> Optional[str]:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _refresh(self) -> None:
        for a, label, _ in ACTIONS:
            keys = ", ".join(display(k) for k in self.bindings.get(a, []))
            self.tree.item(a, values=(label, keys or "-"))

    def _capture(self, replace: bool) -> None:
        a = self._selected()
        if a is None:
            return
        combo = KeyCaptureDialog.ask(self, LABELS[a])
        self.tree.focus_set()
        if not combo:
            return
        owner = next((o for o, keys in self.bindings.items() if o != a and combo in keys), None)
        if owner is not None:
            if not messagebox.askyesno(
                    "Hotkeys", '"%s" is already used by "%s".\n\nUse it for "%s" instead?'
                    % (display(combo), LABELS[owner], LABELS[a]), parent=self):
                return
            self.bindings[owner].remove(combo)
        if replace:
            self.bindings[a] = [combo]
        elif combo not in self.bindings[a]:
            self.bindings[a].append(combo)
        self._refresh()

    def _clear(self) -> None:
        a = self._selected()
        if a is not None:
            self.bindings[a] = []
            self._refresh()

    def _default(self) -> None:
        a = self._selected()
        if a is None:
            return
        keys = defaults()[a]
        for k in keys:  # take the default keys back from other actions
            for o, other in self.bindings.items():
                if o != a and k in other:
                    other.remove(k)
        self.bindings[a] = keys
        self._refresh()

    def _reset_all(self) -> None:
        if messagebox.askyesno("Hotkeys", "Reset all hotkeys to the defaults?", parent=self):
            self.bindings = defaults()
            self._refresh()

    def _apply(self) -> None:
        self.on_apply(self.bindings)
        self.destroy()
