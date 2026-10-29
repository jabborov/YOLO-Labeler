"""File I/O: label paths, atomic label writes, recovery journal, classes, settings."""

import hashlib
import json
import locale
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .annotation import Box, parse_label_lines


def atomic_write_text(path: Path, text: str) -> None:
    """Write via temp file + fsync + os.replace so a crash never leaves a
    truncated file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".part", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


class LabelStore:
    """Maps images to YOLO label files and reads/writes them.

    Modes:
      auto       - look in every supported layout (below); write where the
                   label already exists, otherwise to the layout in which
                   labels were last found in this dataset
      labels_dir - only the "images" -> "labels" layouts
      same       - only next to the image

    Layouts, for image <root>/<rel>:
      images     - last path component named "images" replaced by "labels"
                   (Ultralytics rule: data/images/train/a.jpg -> data/labels/train/a.txt)
      labels_dir - <root>/labels/<rel>.txt
      same       - <root>/<rel>.txt
    """

    def __init__(self, image_root: Path, mode: str = "auto"):
        self.image_root = Path(image_root)
        self.mode = mode
        if self.image_root.name.lower() == "images":
            self.label_root = self.image_root.parent / "labels"
        else:
            self.label_root = self.image_root / "labels"
        if mode == "same":
            self._kinds = ("same",)
        elif mode == "labels_dir":
            self._kinds = ("images", "labels_dir")
        else:
            self._kinds = ("images", "labels_dir", "same")
        # Layout used for new label files; updated when labels are found.
        self.preferred = self._kinds[0]

    def _candidate(self, kind: str, rel: str) -> Optional[Path]:
        img = self.image_root / rel
        if kind == "same":
            return img.with_suffix(".txt")
        if kind == "labels_dir":
            return (self.image_root / "labels" / rel).with_suffix(".txt")
        parts = list(img.parts)
        lowest = max(0, len(self.image_root.parts) - 1)  # never above the opened folder
        for i in range(len(parts) - 2, lowest - 1, -1):  # last directory named "images"
            if parts[i].lower() == "images":
                parts[i] = "labels"
                return Path(*parts).with_suffix(".txt")
        return None

    def candidates(self, rel: str) -> List[Tuple[str, Path]]:
        out, seen = [], set()
        for kind in self._kinds:
            p = self._candidate(kind, rel)
            if p is not None and p not in seen:
                seen.add(p)
                out.append((kind, p))
        return out

    def find_existing(self, rel: str, remember: bool = True) -> Optional[Path]:
        """Existing label file of the image. With `remember`, its layout becomes
        the one used for new files; the background scan passes False so the
        layout only follows images the user actually opens."""
        for kind, p in self.candidates(rel):
            if p.is_file():
                if remember:
                    self.preferred = kind
                return p
        return None

    def label_path(self, rel: str) -> Path:
        """Existing label file of the image, or where a new one will be written."""
        existing = self.find_existing(rel)
        if existing is not None:
            return existing
        cands = dict(self.candidates(rel))
        return cands.get(self.preferred) or cands.get("labels_dir") or cands["same"]

    def read_lines(self, rel: str, remember: bool = True) -> Optional[List[str]]:
        """Non-empty lines of the label file, or None if it does not exist."""
        path = self.find_existing(rel, remember)
        if path is None:
            return None
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return [ln.strip() for ln in f if ln.strip()]
        except FileNotFoundError:
            return None

    def load(self, rel: str, img_w: int, img_h: int) -> Optional[Tuple[List[Box], List[str]]]:
        """(editable boxes, other lines kept verbatim), or None if there is no label file."""
        lines = self.read_lines(rel)
        if lines is None:
            return None
        return parse_label_lines(lines, img_w, img_h)

    def save_lines(self, rel: str, lines: List[str]) -> None:
        atomic_write_text(self.label_path(rel), "".join(ln + "\n" for ln in lines))


def class_ids_of(lines: List[str]) -> Dict[int, int]:
    """Per-class box counts of YOLO label lines (no image size needed)."""
    counts: Dict[int, int] = {}
    for ln in lines:
        parts = ln.split(maxsplit=1)
        if not parts:
            continue
        try:
            c = int(float(parts[0]))
        except ValueError:
            continue
        counts[c] = counts.get(c, 0) + 1
    return counts


def load_classes(path: Path) -> List[str]:
    """Class names, one per line. UTF-8 (with or without BOM) is tried first,
    then the system code page (e.g. CP949 on Korean Windows)."""
    data = Path(path).read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode(locale.getpreferredencoding(False))  # may raise UnicodeDecodeError
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def find_classes_file(store: LabelStore) -> Optional[Path]:
    for cand in (store.image_root / "classes.txt", store.label_root / "classes.txt",
                 store.image_root.parent / "classes.txt"):
        if cand.is_file():
            return cand
    return None


def work_dir_for(image_root: Path) -> Path:
    """Directory for the index DB and journal: <root>/.mylabel, or a per-dataset
    folder under ~/.mylabel if the dataset is read-only."""
    d = Path(image_root) / ".mylabel"
    try:
        d.mkdir(exist_ok=True)
        probe = d / ".probe"
        probe.write_text("ok")
        probe.unlink()
        return d
    except OSError:
        h = hashlib.sha1(str(Path(image_root).resolve()).encode("utf-8")).hexdigest()[:16]
        d = Path.home() / ".mylabel" / "datasets" / h
        d.mkdir(parents=True, exist_ok=True)
        return d


class Journal:
    """Holds the unsaved edits of the current image so they survive a crash."""

    def __init__(self, work_dir: Path):
        self.path = Path(work_dir) / "journal.json"

    def write(self, rel: str, lines: List[str]) -> None:
        atomic_write_text(self.path, json.dumps(
            {"rel": rel, "lines": lines, "time": time.time()}))

    def read(self) -> Optional[dict]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "rel" in data and "lines" in data:
                return data
        except (OSError, ValueError):
            pass
        return None

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


SETTINGS_PATH = Path.home() / ".mylabel" / "settings.json"


def load_settings() -> dict:
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    try:
        atomic_write_text(SETTINGS_PATH, json.dumps(settings, indent=2))
    except OSError:
        pass
