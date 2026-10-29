"""Box model, YOLO conversion, duplicate detection and per-image edit state.

Boxes are kept in original-image pixel coordinates (x1, y1, x2, y2) so that
zooming/panning never introduces rounding drift. Conversion to normalized
YOLO values happens only when reading or writing label files.
"""

from dataclasses import dataclass, replace
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class Box:
    cls: int
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def w(self) -> float:
        return self.x2 - self.x1

    @property
    def h(self) -> float:
        return self.y2 - self.y1

    def normalized(self) -> "Box":
        """Return the box with x1 <= x2 and y1 <= y2."""
        return Box(self.cls, min(self.x1, self.x2), min(self.y1, self.y2),
                   max(self.x1, self.x2), max(self.y1, self.y2))

    def clipped(self, img_w: int, img_h: int) -> "Box":
        b = self.normalized()
        return Box(b.cls,
                   min(max(b.x1, 0.0), img_w), min(max(b.y1, 0.0), img_h),
                   min(max(b.x2, 0.0), img_w), min(max(b.y2, 0.0), img_h))

    def with_class(self, cls: int) -> "Box":
        return replace(self, cls=cls)

    def contains(self, x: float, y: float) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def to_yolo(self, img_w: int, img_h: int) -> str:
        b = self.clipped(img_w, img_h)
        cx = (b.x1 + b.x2) / 2.0 / img_w
        cy = (b.y1 + b.y2) / 2.0 / img_h
        return "%d %.6f %.6f %.6f %.6f" % (b.cls, cx, cy, b.w / img_w, b.h / img_h)

    @staticmethod
    def from_yolo(line: str, img_w: int, img_h: int) -> Optional["Box"]:
        """Parse a 5-column detection line. Other formats (segmentation
        polygons, OBB, pose keypoints) return None so they are never misread."""
        parts = line.split()
        if len(parts) != 5:
            return None
        try:
            cls = int(float(parts[0]))
            cx, cy, w, h = (float(p) for p in parts[1:5])
        except ValueError:
            return None
        if w <= 0 or h <= 0:
            return None
        x1 = (cx - w / 2.0) * img_w
        y1 = (cy - h / 2.0) * img_h
        return Box(cls, x1, y1, x1 + w * img_w, y1 + h * img_h).clipped(img_w, img_h)


def parse_label_lines(lines: List[str], img_w: int, img_h: int) -> Tuple[List[Box], List[str]]:
    """Split label lines into editable boxes and other lines (non-box formats,
    malformed lines), which are kept verbatim so saving never drops them."""
    boxes: List[Box] = []
    extra: List[str] = []
    for ln in lines:
        b = Box.from_yolo(ln, img_w, img_h)
        if b is None:
            extra.append(ln)
        else:
            boxes.append(b)
    return boxes, extra


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union > 0 else 0.0


def find_duplicate(boxes: List[Box], box: Box, threshold: float,
                   ignore: Optional[int] = None) -> Optional[int]:
    """Index of an existing same-class box overlapping `box` by >= threshold IoU."""
    for i, other in enumerate(boxes):
        if i != ignore and other.cls == box.cls and iou(other, box) >= threshold:
            return i
    return None


def dedupe(boxes: List[Box], threshold: float) -> List[Box]:
    out: List[Box] = []
    for b in boxes:
        if find_duplicate(out, b, threshold) is None:
            out.append(b)
    return out


class AnnotationDoc:
    """Boxes of the current image plus undo history and dirty tracking.

    `extra` holds label lines that are not editable boxes; they are written
    back unchanged after the boxes."""

    def __init__(self, boxes: List[Box], img_w: int, img_h: int,
                 dup_threshold: float, undo_limit: int = 100,
                 extra: Optional[List[str]] = None):
        self.boxes: List[Box] = list(boxes)
        self.extra: List[str] = list(extra or [])
        self.img_w = img_w
        self.img_h = img_h
        self.dup_threshold = dup_threshold
        self.undo_limit = undo_limit
        self.dirty = False
        self._saved: List[Box] = list(boxes)  # boxes as last loaded/saved
        self._undo: List[List[Box]] = []

    def _snapshot(self) -> None:
        self._undo.append(list(self.boxes))
        if len(self._undo) > self.undo_limit:
            del self._undo[0]
        self.dirty = True

    def add(self, box: Box) -> Optional[int]:
        """Add a box. Returns its index, or None if it duplicates an existing box."""
        box = box.clipped(self.img_w, self.img_h)
        if find_duplicate(self.boxes, box, self.dup_threshold) is not None:
            return None
        self._snapshot()
        self.boxes.append(box)
        return len(self.boxes) - 1

    def update(self, i: int, box: Box) -> bool:
        box = box.clipped(self.img_w, self.img_h)
        if box == self.boxes[i]:
            return True
        if find_duplicate(self.boxes, box, self.dup_threshold, ignore=i) is not None:
            return False
        self._snapshot()
        self.boxes[i] = box
        return True

    def add_many(self, boxes: List[Box]) -> List[int]:
        """Add several boxes as one undo step, skipping duplicates. Returns the
        indices of the boxes actually added."""
        new: List[Box] = []
        for b in boxes:
            b = b.clipped(self.img_w, self.img_h)
            if find_duplicate(self.boxes + new, b, self.dup_threshold) is None:
                new.append(b)
        if not new:
            return []
        self._snapshot()
        start = len(self.boxes)
        self.boxes.extend(new)
        return list(range(start, start + len(new)))

    def remove(self, i: int) -> None:
        self._snapshot()
        del self.boxes[i]

    def remove_many(self, indices: List[int]) -> None:
        """Remove several boxes as one undo step."""
        drop = {i for i in indices if 0 <= i < len(self.boxes)}
        if drop:
            self._snapshot()
            self.boxes = [b for i, b in enumerate(self.boxes) if i not in drop]

    def set_class(self, i: int, cls: int) -> bool:
        return self.update(i, self.boxes[i].with_class(cls))

    def undo(self) -> bool:
        if not self._undo:
            return False
        self.boxes = self._undo.pop()
        self.dirty = self.boxes != self._saved  # undoing back to the saved state is clean
        return True

    def mark_saved(self) -> None:
        self._saved = list(self.boxes)
        self.dirty = False

    def yolo_lines(self) -> List[str]:
        return [b.to_yolo(self.img_w, self.img_h) for b in self.boxes] + self.extra
