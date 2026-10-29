"""Main window: wires the toolbar, class bar, canvas and side panels to the
dataset index, image loader and label storage."""

import os
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import config
from ..core.annotation import AnnotationDoc
from ..core.dataset_index import DatasetIndex, compute_stats
from ..core.image_loader import ImageLoader, LoadedImage
from ..core.storage import (Journal, LabelStore, find_classes_file, load_classes,
                            load_settings, save_settings, work_dir_for)
from .box_panel import BoxPanel
from .canvas_view import CanvasView
from .class_bar import ClassBar
from .dialogs import ClassesDialog, StatisticsDialog, UnsavedChangesDialog
from . import hotkeys, theme
from .image_list import ImageList
from .toolbar import Toolbar

POLL_MS = 25
JOURNAL_DELAY_MS = 300


def _hms(sec: int) -> str:
    return "%02d:%02d:%02d" % (sec // 3600, sec // 60 % 60, sec % 60)


class App:
    def __init__(self, root: tk.Tk, folder: Optional[str] = None):
        self.root = root
        self.settings = load_settings()
        s = self.settings
        self.show_names = s.get("show_names", config.SHOW_NAMES)
        self.autosave_on = bool(s.get("autosave", config.AUTOSAVE_DEFAULT))
        self.labels_mode = s.get("labels_mode", config.LABELS_MODE)
        self.hotkeys = hotkeys.load(s.get("hotkeys"))
        self._key_actions = hotkeys.key_map(self.hotkeys)  # combination -> action id

        self.loader = ImageLoader(config.LOADER_WORKERS, config.CACHE_MAX_BYTES,
                                  config.PREVIEW_MAX_SIDE)
        self.image_root: Optional[Path] = None
        self.store: Optional[LabelStore] = None
        self.index: Optional[DatasetIndex] = None
        self.journal: Optional[Journal] = None

        self.classes = []
        self.classes_path = ""
        self.active_class: Optional[int] = None

        self.current: Optional[int] = None
        self.current_rel = ""
        self.current_path = ""
        self.doc: Optional[AnnotationDoc] = None
        self._pending_goto: Optional[int] = None
        # (target idx, boxes, src width, src height): boxes to paste once the
        # target image of "copy to previous/next image" has loaded.
        self._pending_paste = None
        self._saved_last_idx: Optional[int] = None
        self._journal_job = None
        self._list_suffix = ""
        self._last_progress = 0

        self.session_sec = 0
        self.image_sec = 0
        self.last_activity = time.time()
        self.saved_this_session = set()
        self._autosave_job = None

        self._build_ui()
        self._bind_keys()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(POLL_MS, self._poll)
        self.root.after(1000, self._tick)
        self._schedule_autosave()

        last = folder or s.get("last_folder")
        if last and os.path.isdir(last):
            self.root.after(100, lambda: self.open_dataset(last))
        else:
            self.canvas.show_message("Open Folder to start annotating")

    # ================================================================== UI
    def _build_ui(self) -> None:
        self.root.title("mylabel")
        self.root.geometry("1500x900")
        self.root.minsize(900, 600)
        theme.apply(self.root, self.settings.get("theme", config.THEME))

        self.toolbar = Toolbar(self.root, {
            "open_folder": self.open_folder, "open_classes": self.open_classes,
            "save": lambda: self.save(manual=True),
            "toggle_draw": self.toggle_draw, "prev": self.prev_image, "next": self.next_image,
            "statistics": self.show_statistics, "classes": self.show_classes,
            "toggle_names": self.toggle_names, "toggle_theme": self.toggle_theme,
            "toggle_autosave": self.toggle_autosave, "hotkeys": self.show_hotkeys,
        })
        self.toolbar.pack(fill="x")
        self.toolbar.set_names(self.show_names)
        self.toolbar.set_autosave(self.autosave_on)
        self._update_key_hints()

        self.class_bar = ClassBar(self.root, padding=(4, 0))
        self.class_bar.pack(fill="x")
        self.class_bar.on_pick = self.pick_class
        ttk.Separator(self.root).pack(fill="x", pady=(2, 0))

        status = ttk.Frame(self.root, padding=(6, 2))
        status.pack(side="bottom", fill="x")
        self.status_msg = ttk.Label(status, text="", anchor="w")
        self.status_msg.pack(side="left", fill="x", expand=True)
        self.status_info = ttk.Label(status, text="", anchor="e", style="Muted.TLabel")
        self.status_info.pack(side="right")
        self.status_cursor = ttk.Label(status, text="", width=18, anchor="e")
        self.status_cursor.pack(side="right", padx=10)

        paned = ttk.Panedwindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True)

        self.canvas = CanvasView(paned, min_box=config.MIN_BOX_SIZE)
        self.canvas.on_change = self._on_canvas_change
        self.canvas.on_status = self.set_status
        self.canvas.on_cursor = lambda t: self.status_cursor.configure(text=t)
        self.canvas.on_need_full = self._request_full
        self.canvas.on_zoom = lambda z: self._update_status_info()
        self.canvas.class_name = self.class_name
        self.canvas.active_class = lambda: self.active_class if self.classes else None
        self.canvas.set_show_names(self.show_names)
        paned.add(self.canvas, weight=1)

        side = ttk.Panedwindow(paned, orient="vertical", width=440)
        paned.add(side, weight=0)
        self.box_panel = BoxPanel(side, padding=6)
        self.box_panel.on_select = self.canvas.select
        self.box_panel.on_select_many = self.canvas.set_marked
        self.box_panel.on_delete = self.canvas.delete_selected
        self.box_panel.on_copy_prev = lambda: self.copy_to_neighbour(-1)
        self.box_panel.on_copy_next = lambda: self.copy_to_neighbour(1)
        side.add(self.box_panel, weight=1)
        self.image_list = ImageList(side, self._list_rows, padding=6)
        self.image_list.on_select = self.goto
        self.image_list.on_find = self.find_image
        self.image_list.on_next_unlabelled = self.next_unlabelled
        side.add(self.image_list, weight=3)

    def _bind_keys(self) -> None:
        # Action ids are defined in hotkeys.ACTIONS; the keys come from the Hotkeys dialog.
        self._actions = {
            "prev_image": self.prev_image, "next_image": self.next_image,
            "next_unlabelled": self.next_unlabelled, "toggle_draw": self.toggle_draw,
            "delete_box": self.canvas.delete_selected, "cancel": self.canvas.cancel,
            "undo": self.canvas.undo, "save": lambda: self.save(manual=True),
            "copy_box": self.canvas.copy_box,
            "paste_box": lambda: self.canvas.paste_box(at_mouse=False),
            "paste_box_at_mouse": lambda: self.canvas.paste_box(at_mouse=True),
            "copy_to_prev": lambda: self.copy_to_neighbour(-1),
            "copy_to_next": lambda: self.copy_to_neighbour(1),
            "toggle_autosave": self.toggle_autosave, "open_folder": self.open_folder,
            "zoom_in": lambda: self.canvas.zoom_by(1.25),
            "zoom_out": lambda: self.canvas.zoom_by(0.8),
            "fit": self.canvas.fit, "toggle_names": self.toggle_names,
            "toggle_theme": self.toggle_theme, "statistics": self.show_statistics,
            "classes": self.show_classes, "hotkeys": self.show_hotkeys,
        }
        for n in range(10):  # n-th visible class button
            self._actions["class_%d" % (n + 1)] = lambda n=n: self._pick_visible_class(n)
        r = self.root
        r.bind_all("<Key>", self._on_key)
        for seq in ("<Any-KeyPress>", "<Any-ButtonPress>", "<Motion>"):
            r.bind_all(seq, self._activity, add="+")
        r.bind_all("<MouseWheel>", lambda e: self._on_wheel(e, e.delta))
        r.bind_all("<Button-4>", lambda e: self._on_wheel(e, 120))   # X11 wheel up
        r.bind_all("<Button-5>", lambda e: self._on_wheel(e, -120))  # X11 wheel down

    def _on_wheel(self, e, delta: int) -> None:
        """Send wheel events to the widget under the mouse pointer. Some Tk
        versions on Windows deliver them to the focused widget instead."""
        self._activity()
        try:
            target = self.root.winfo_containing(e.x_root, e.y_root)
        except (KeyError, tk.TclError):
            return
        if target is self.canvas:
            self.canvas.wheel(e.x_root - self.canvas.winfo_rootx(),
                              e.y_root - self.canvas.winfo_rooty(), delta)
        elif target is self.image_list.canvas and delta:
            self.image_list.scroll(-3 if delta > 0 else 3)
        elif delta:
            # Scrollable areas in dialogs expose a `wheel_handler` on an ancestor.
            w = target
            while w is not None:
                handler = getattr(w, "wheel_handler", None)
                if handler is not None:
                    handler(delta)
                    break
                w = getattr(w, "master", None)

    @staticmethod
    def _is_text_input(widget) -> bool:
        return isinstance(widget, (tk.Entry, ttk.Entry, tk.Spinbox, ttk.Spinbox, tk.Text))

    def _on_key(self, e) -> None:
        try:
            if e.widget.winfo_toplevel() is not self.root:
                return  # keys typed in dialogs are not shortcuts
        except (AttributeError, tk.TclError):
            return
        combo = hotkeys.combo_from_event(e)
        action = self._key_actions.get(combo) if combo else None
        if action is None:
            return
        # While typing in a text box only Ctrl/Alt combinations act (except undo
        # and copy/paste, which belong to the text box there).
        if self._is_text_input(e.widget) and (
                action in ("undo", "copy_box", "paste_box", "paste_box_at_mouse")
                or not hotkeys.has_command_modifier(combo)):
            return
        self._actions[action]()

    def _pick_visible_class(self, pos: int) -> None:
        cls = self.class_bar.class_at(pos)
        if cls is not None:
            self.pick_class(cls)

    def show_hotkeys(self) -> None:
        hotkeys.HotkeysDialog(self.root, self.hotkeys, self._set_hotkeys)

    def _set_hotkeys(self, bindings) -> None:
        self.hotkeys = bindings
        self._key_actions = hotkeys.key_map(bindings)
        self.settings["hotkeys"] = bindings
        save_settings(self.settings)
        self._update_key_hints()
        self.set_status("Hotkeys saved")

    def _update_key_hints(self) -> None:
        keys = self.hotkeys.get("toggle_draw") or []
        self.toolbar.set_draw_key(hotkeys.display(keys[0]) if keys else "")

    def _activity(self, _e=None) -> None:
        self.last_activity = time.time()

    def set_status(self, msg: str) -> None:
        self.status_msg.configure(text=msg)

    # ============================================================= dataset
    def open_folder(self) -> None:
        path = filedialog.askdirectory(title="Select image folder", parent=self.root,
                                       initialdir=self.settings.get("last_folder") or None)
        if path:
            self.open_dataset(path)

    def open_dataset(self, path: str) -> None:
        if not self._leave_image():
            return
        self._close_dataset()
        root = Path(path)
        try:
            self.store = LabelStore(root, self.labels_mode)
            work = work_dir_for(root)
            self.index = DatasetIndex(work / "index.db", self.store, config.IMAGE_EXTENSIONS,
                                      config.INDEX_BATCH, config.MAX_IMAGES)
        except Exception as e:
            self.store = self.index = None
            messagebox.showerror("Open Folder", "Cannot open dataset:\n%s" % e, parent=self.root)
            return
        self.image_root = root
        self.journal = Journal(work)
        self._recover_journal()
        self.index.start()

        self.settings["last_folder"] = str(root)
        save_settings(self.settings)
        self.root.title("mylabel - %s" % root)
        self.session_sec = self.image_sec = 0
        self.saved_this_session.clear()

        cpath = self.settings.get("classes_by_folder", {}).get(str(root))
        if not (cpath and os.path.isfile(cpath)):
            found = find_classes_file(self.store)
            cpath = str(found) if found else None
        if cpath is None:
            # A classes file from another dataset could silently write the
            # wrong class ids, so only reuse it when the user confirms.
            last = self.settings.get("last_classes")
            if last and os.path.isfile(last) and messagebox.askyesno(
                    "Classes",
                    "No classes.txt was found for this folder.\n\n"
                    "Use the last classes file?\n%s" % last, parent=self.root):
                cpath = last
                self.settings.setdefault("classes_by_folder", {})[str(root)] = last
                save_settings(self.settings)
        if cpath:
            self._load_classes(cpath)
        else:
            self.classes, self.classes_path, self.active_class = [], "", None
            self.class_bar.set_classes([])
            self.set_status("No classes.txt for this folder - load one with Classes.txt")

        try:
            target = int(self.index.get_meta("last_idx", "0"))
        except ValueError:
            target = 0
        self._saved_last_idx = target
        self.image_list.set_count(self.index.count())
        self.canvas.show_message("Indexing images...")
        self._pending_goto = target
        self._try_pending_goto()

    def _close_dataset(self) -> None:
        if self.index is not None:
            self._persist_position()
            self.index.close()
        self.index = None
        self.loader.clear()
        self.current = None
        self.doc = None
        self.current_rel = self.current_path = ""
        self.canvas.set_doc(None)
        self.box_panel.clear()
        self.image_list.set_count(0)
        self.image_list.set_current(None)

    def _recover_journal(self) -> None:
        data = self.journal.read()
        if not data:
            return
        rel, lines = data["rel"], data["lines"]
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(data.get("time", 0)))
        if messagebox.askyesno(
                "Recover annotations",
                "Unsaved annotations from a previous session were found:\n\n%s\n(%d boxes, %s)\n\n"
                "Restore them to the label file?" % (rel, len(lines), when), parent=self.root):
            try:
                self.store.save_lines(rel, lines)
                idx = self.index.idx_of(rel)
                if idx is not None:
                    self.index.set_labels(idx, lines)
            except OSError as e:
                messagebox.showerror("Recover annotations", "Restore failed:\n%s" % e,
                                     parent=self.root)
                return
        self.journal.clear()

    def _try_pending_goto(self) -> None:
        if self._pending_goto is None or self.index is None:
            return
        count = self.index.count()
        target = self._pending_goto
        if count > target or (count > 0 and not self.index.files_scanning):
            self._pending_goto = None
            self.goto(min(target, count - 1))
        elif count == 0 and not self.index.busy and self.index.get_meta("files_complete") == "1":
            self._pending_goto = None
            self.canvas.show_message("No images found in this folder")

    def _rebuild_index(self) -> None:
        if self.index is None or not self._leave_image():
            return
        self.current = None
        self.doc = None
        self.current_rel = self.current_path = ""  # drop late image loads for the old position
        self.canvas.show_message("Rebuilding index...")
        self.box_panel.clear()
        self.loader.clear()
        self.index.start(rebuild=True)
        self.image_list.set_count(0)
        self._pending_goto = 0

    def _persist_position(self) -> None:
        if self.index is not None and self.current is not None \
                and self.current != self._saved_last_idx:
            try:
                self.index.set_meta("last_idx", self.current)
                self._saved_last_idx = self.current
            except Exception:
                pass

    def _list_rows(self, start: int, end: int):
        return self.index.rows(start, end) if self.index is not None else []

    # ============================================================= classes
    def open_classes(self) -> None:
        path = filedialog.askopenfilename(
            title="Select classes.txt", filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=str(self.image_root) if self.image_root else None, parent=self.root)
        if not path:
            return
        if self._load_classes(path):
            self.settings["last_classes"] = path
            if self.image_root is not None:
                self.settings.setdefault("classes_by_folder", {})[str(self.image_root)] = path
            save_settings(self.settings)

    def _load_classes(self, path: str) -> bool:
        try:
            names = load_classes(Path(path))
        except (OSError, UnicodeDecodeError) as e:
            messagebox.showerror("Classes", "Cannot read %s:\n%s" % (path, e), parent=self.root)
            return False
        if not names:
            messagebox.showwarning("Classes", "%s contains no class names." % path,
                                   parent=self.root)
            return False
        self.classes = names
        self.classes_path = path
        saved = self.settings.get("visible_classes", {}).get(str(Path(path).resolve()))
        visible = [c for c in saved if 0 <= c < len(names)] if saved else None
        self.class_bar.set_classes(names, visible or None)
        self.active_class = self.class_bar.active
        self.canvas.redraw_overlays()
        self._refresh_box_panel()
        return True

    def _set_visible_classes(self, selected) -> None:
        """Apply the Classes dialog selection and remember it per classes.txt."""
        key = str(Path(self.classes_path).resolve())
        store = self.settings.setdefault("visible_classes", {})
        if len(selected) == len(self.classes):
            store.pop(key, None)  # all classes: the default
        else:
            store[key] = list(selected)
        save_settings(self.settings)
        self.class_bar.set_classes(self.classes, list(selected))
        self.active_class = self.class_bar.active
        self.set_status("Showing %d of %d classes" % (len(selected), len(self.classes)))

    def class_name(self, cls: int) -> str:
        return self.classes[cls] if 0 <= cls < len(self.classes) else "class %d" % cls

    def pick_class(self, cls: int) -> None:
        if not 0 <= cls < len(self.classes):
            return
        self.active_class = cls
        self.class_bar.set_active(cls)
        self.canvas.set_selected_class(cls)

    def show_classes(self) -> None:
        if not self.classes:
            messagebox.showinfo("Classes", "Load a classes.txt first (Classes.txt button).",
                                parent=self.root)
            return
        ClassesDialog(self.root, self.classes, self.class_bar.visible,
                      self._set_visible_classes, self.classes_path)

    # ========================================================== navigation
    def prev_image(self) -> None:
        if self.current is not None:
            self.goto(self.current - 1)

    def next_image(self) -> None:
        if self.current is not None:
            self.goto(self.current + 1)

    def next_unlabelled(self) -> None:
        if self.index is None:
            return
        idx = self.index.next_unlabelled(self.current if self.current is not None else -1)
        if idx is None:
            self.set_status("No unlabelled image after the current one"
                            + (" (label scan still running)" if self.index.labels_scanning else ""))
        else:
            self.goto(idx)

    def find_image(self, text: str) -> None:
        if self.index is None:
            return
        # A number within range is an image number; otherwise (e.g. "000123"
        # beyond the image count) it is searched as part of a file name.
        if text.isdigit() and 1 <= int(text) <= self.index.count():
            self.goto(int(text) - 1)
            return
        idx = self.index.find(text, self.current if self.current is not None else -1)
        if idx is None:
            self.set_status("No image name contains '%s'" % text)
        else:
            self.goto(idx)

    def copy_to_neighbour(self, step: int) -> None:
        """Copy the boxes selected in the box list to the previous (-1) or next
        (+1) image and open it; the copies are unsaved edits there."""
        if self.doc is None or self.index is None or self.current is None:
            return
        indices = self.canvas.selected_indices()
        if not indices:
            self.set_status("Select boxes in the Bounding boxes list first "
                            "(Ctrl/Shift+click for several, or All)")
            return
        target = self.current + step
        if not 0 <= target < self.index.count():
            self.set_status("No %s image" % ("previous" if step < 0 else "next"))
            return
        boxes = [self.doc.boxes[i] for i in indices]
        self._pending_paste = (target, boxes, self.doc.img_w, self.doc.img_h)
        self.goto(target)
        if self.current != target:  # navigation cancelled (unsaved-changes prompt)
            self._pending_paste = None

    def _apply_pending_paste(self) -> None:
        p = self._pending_paste
        if p is None or p[0] != self.current or self.doc is None:
            return
        self._pending_paste = None
        _, boxes, w, h = p
        self.canvas.paste_boxes(boxes, w, h)

    def goto(self, idx: int, force: bool = False) -> None:
        if self.index is None:
            return
        if self._pending_paste is not None and self._pending_paste[0] != idx:
            self._pending_paste = None  # the user went somewhere else
        if not 0 <= idx < self.index.count():
            return
        if idx == self.current and not force:
            return
        if not self._leave_image():
            return
        rel = self.index.get_rel(idx)
        if rel is None:
            return
        self.current = idx
        self.current_rel = rel
        self.current_path = str(self.image_root / rel)
        self.doc = None
        self.canvas.set_doc(None)
        self.image_sec = 0
        self.toolbar.set_image_name(rel)
        self.image_list.set_current(idx)

        neighbours = [r[1] for r in self.index.rows(idx - config.PREFETCH_BEHIND,
                                                    idx + config.PREFETCH_AHEAD + 1)]
        paths = [str(self.image_root / r) for r in neighbours]
        self.loader.set_wanted(paths)
        hit = self.loader.cached(self.current_path)
        if hit is not None:
            self._on_image_loaded(hit)
        else:
            self.root.after(150, lambda p=self.current_path: self._show_loading(p))
            self.loader.request(self.current_path)
        self.loader.prefetch([p for p in paths if p != self.current_path])

    def _show_loading(self, path: str) -> None:
        if path == self.current_path and self.doc is None:
            self.canvas.show_message("Loading %s ..." % os.path.basename(path))

    def _request_full(self) -> None:
        if self.current_path:
            self.loader.request(self.current_path, full=True)

    def _on_image_loaded(self, item: LoadedImage) -> None:
        if item.path != self.current_path or self.current is None:
            return
        if self.doc is not None:
            # Full-resolution upgrade of the image being edited.
            if item.is_full and self.canvas.loaded is not None and not self.canvas.loaded.is_full:
                self.canvas.set_image(item, keep_view=True)
            return
        w, h = item.orig_size
        try:
            loaded = self.store.load(self.current_rel, w, h)
        except (OSError, UnicodeDecodeError) as e:
            self.canvas.show_message("Cannot read label file for %s\n%s" % (self.current_rel, e))
            return
        boxes, extra = loaded if loaded is not None else ([], [])
        lpath = self.store.label_path(self.current_rel)
        if loaded is None:
            self.set_status("No label file - new labels will be saved to %s" % lpath)
        elif extra:
            self.set_status("Labels: %s (%d boxes; %d non-box/invalid lines kept unchanged, "
                            "not shown)" % (lpath, len(boxes), len(extra)))
        else:
            self.set_status("Labels: %s (%d boxes)" % (lpath, len(boxes)))
        self.doc = AnnotationDoc(boxes, w, h, config.DUPLICATE_IOU, config.UNDO_LIMIT, extra)
        self.canvas.set_image(item)
        self.canvas.set_doc(self.doc)
        self._refresh_box_panel()
        nb = -1 if loaded is None else len(boxes) + len(extra)
        if self.index.nboxes(self.current) != nb:
            self.index.set_labels(self.current, None if loaded is None else self.doc.yolo_lines())
            self.image_list.redraw()
        self._update_title()
        self._apply_pending_paste()

    # ============================================================== editing
    def toggle_draw(self) -> None:
        on = not self.canvas.draw_mode
        self.canvas.set_draw_mode(on)
        self.toolbar.set_draw(on)

    def toggle_theme(self) -> None:
        """Switch between light and dark mode and remember the choice."""
        theme.apply(self.root, "light" if theme.name() == "dark" else "dark")
        for w in (self.toolbar, self.class_bar, self.canvas, self.image_list, self.box_panel):
            w.apply_theme()
        self.settings["theme"] = theme.name()
        save_settings(self.settings)

    def toggle_names(self) -> None:
        self.show_names = not self.show_names
        self.canvas.set_show_names(self.show_names)
        self.toolbar.set_names(self.show_names)
        self.settings["show_names"] = self.show_names
        save_settings(self.settings)

    def _on_canvas_change(self, boxes_changed: bool) -> None:
        self._refresh_box_panel()
        if boxes_changed:
            self._update_title()
            if self._journal_job is not None:
                self.root.after_cancel(self._journal_job)
            self._journal_job = self.root.after(JOURNAL_DELAY_MS, self._write_journal)

    def _write_journal(self) -> None:
        self._journal_job = None
        if self.doc is None or self.journal is None:
            return
        try:
            if self.doc.dirty:
                self.journal.write(self.current_rel, self.doc.yolo_lines())
            else:  # undone back to the saved state: nothing to recover
                self.journal.clear()
        except OSError as e:
            self.set_status("Journal write failed: %s" % e)

    def _refresh_box_panel(self) -> None:
        if self.doc is None:
            self.box_panel.clear()
        else:
            self.box_panel.update_boxes(self.doc.boxes, self.canvas.selected_indices(),
                                        self.class_name, (self.doc.img_w, self.doc.img_h))

    def _update_title(self) -> None:
        if self.current is None:
            return
        dirty = self.doc is not None and self.doc.dirty
        self.toolbar.set_image_name("%s%s   [%s / %s]" % (
            "* " if dirty else "", self.current_rel, format(self.current + 1, ","),
            format(self.image_list.count, ",")))

    # =============================================================== saving
    def save(self, manual: bool = False) -> bool:
        """Write the current image's labels. Automatic saves skip clean images;
        a manual save always writes (an empty file marks a reviewed negative)."""
        if self.doc is None or self.index is None:
            return True
        if not manual and not self.doc.dirty:
            return True
        lines = self.doc.yolo_lines()
        try:
            self.store.save_lines(self.current_rel, lines)
        except OSError as e:
            messagebox.showerror("Save", "Cannot write labels for %s:\n%s" % (self.current_rel, e),
                                 parent=self.root)
            return False
        self.index.set_labels(self.current, lines)
        self.doc.mark_saved()
        if self._journal_job is not None:
            self.root.after_cancel(self._journal_job)
            self._journal_job = None
        self.journal.clear()
        self.saved_this_session.add(self.current)
        self.image_list.redraw()
        self._update_title()
        self.set_status("Saved %s (%d boxes)" % (self.store.label_path(self.current_rel), len(lines)))
        return True

    def _leave_image(self) -> bool:
        """Called before switching image/dataset. False means stay."""
        if self.doc is None or not self.doc.dirty:
            return True
        if self.autosave_on:
            return self.save()
        choice = UnsavedChangesDialog.ask(self.root, self.current_rel)
        if choice == "save":
            return self.save()
        if choice == "discard":
            self.doc.dirty = False
            if self._journal_job is not None:
                self.root.after_cancel(self._journal_job)
                self._journal_job = None
            if self.journal is not None:
                self.journal.clear()
            return True
        return False  # cancel: stay on this image, keep the edits

    def toggle_autosave(self) -> None:
        self.autosave_on = not self.autosave_on
        self.toolbar.set_autosave(self.autosave_on)
        self.settings["autosave"] = self.autosave_on
        save_settings(self.settings)
        self.set_status("Auto-save %s" % ("ON: changes are saved automatically"
                                          if self.autosave_on else
                                          "OFF: you will be asked before leaving an edited image"))

    def _schedule_autosave(self) -> None:
        """Start the background auto-save timer: one Tk timer per
        config.AUTOSAVE_INTERVAL_SEC, independent of the 1-second UI tick."""
        if self._autosave_job is not None:
            self.root.after_cancel(self._autosave_job)
            self._autosave_job = None
        interval = max(5, int(config.AUTOSAVE_INTERVAL_SEC))
        self._autosave_job = self.root.after(interval * 1000, self._autosave_fire)

    def _autosave_fire(self) -> None:
        self._autosave_job = None
        try:
            if self.autosave_on and self.doc is not None and self.doc.dirty \
                    and not self.canvas.dragging:
                self.save()  # not in the middle of a drag; edits so far are kept
        finally:
            self._schedule_autosave()

    # ======================================================= periodic tasks
    def _poll(self) -> None:
        try:
            for path, item, err in self.loader.poll():
                if path != self.current_path:
                    continue
                if item is not None:
                    self._on_image_loaded(item)
                elif err is not None and self.doc is None:
                    self.canvas.show_message("Cannot open %s\n%s" % (os.path.basename(path), err))
        finally:
            self.root.after(POLL_MS, self._poll)

    def _tick(self) -> None:
        try:
            self._tick_inner()
        finally:
            self.root.after(1000, self._tick)

    def _tick_inner(self) -> None:
        idle = time.time() - self.last_activity >= config.IDLE_TIMEOUT_SEC
        if self.index is not None and not idle:
            self.session_sec += 1
            if self.doc is not None:
                self.image_sec += 1
        self.toolbar.set_timer("Session %s  Image %s%s" % (
            _hms(self.session_sec), _hms(self.image_sec), "  (idle)" if idle else ""))

        if self.index is not None:
            ix = self.index
            suffix = ""
            if ix.files_scanning:
                suffix = "  indexing..."
            elif ix.labels_scanning:
                n = self.image_list.count
                suffix = "  labels %d%%" % (100 * ix.labels_progress // n if n else 0)
            count = ix.count()
            if count != self.image_list.count or suffix != self._list_suffix:
                self._list_suffix = suffix
                self.image_list.set_count(count, suffix)
                self._update_title()
            elif ix.labels_scanning and self._last_progress != ix.labels_progress \
                    and self._last_progress <= self.image_list.top + 100:
                self.image_list.redraw()  # statuses of visible rows just got scanned
            self._last_progress = ix.labels_progress
            self._try_pending_goto()
            self._persist_position()
            if ix.error:
                self.set_status(ix.error)
                ix.error = None
            elif ix.notice:
                self.set_status(ix.notice)
                ix.notice = None
        self._update_status_info()

    def _update_status_info(self) -> None:
        n_cached, used = self.loader.cache_info
        text = "Zoom %d%%   Cache %d img / %d MB" % (
            round(self.canvas.zoom * 100), n_cached, used // (1024 * 1024))
        if self.status_info.cget("text") != text:
            self.status_info.configure(text=text)

    # ============================================================== dialogs
    def show_statistics(self) -> None:
        if self.index is None:
            messagebox.showinfo("Statistics", "Open a folder first.", parent=self.root)
            return
        n = len(self.saved_this_session)
        session = {
            "Active time": _hms(self.session_sec),
            "Images saved": format(n, ","),
            "Avg time / image": _hms(self.session_sec // n) if n else "-",
        }
        note = ""
        if self.index.files_scanning:
            note = "Image indexing is still running; numbers are partial."
        elif self.index.labels_scanning:
            note = "Label scan is still running; numbers are partial."
        db = self.index.db_path
        StatisticsDialog(self.root, lambda cb: compute_stats(db, cb), self.classes, session,
                         note, self._rebuild_index)

    # ================================================================ close
    def on_close(self) -> None:
        if not self._leave_image():
            return
        if self._autosave_job is not None:
            self.root.after_cancel(self._autosave_job)
            self._autosave_job = None
        self._close_dataset()
        self.loader.shutdown()
        self.root.destroy()
