"""Background image decoding with an LRU cache and prefetching.

Workers decode with Pillow (JPEG draft mode for fast reduced-size decoding).
Results are delivered through a queue that the Tk main thread drains with
`poll()`; Tk objects are never touched from worker threads.
"""

import math
import queue
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple

from PIL import Image, ImageOps

try:
    _BILINEAR = Image.Resampling.BILINEAR
except AttributeError:  # Pillow < 9.1
    _BILINEAR = Image.BILINEAR

_EXIF_ORIENTATION = 0x0112


@dataclass
class LoadedImage:
    path: str
    image: Image.Image          # decoded RGB/L pixels, possibly reduced
    orig_size: Tuple[int, int]  # size in original pixels (EXIF orientation applied)
    is_full: bool

    @property
    def nbytes(self) -> int:
        w, h = self.image.size
        return w * h * len(self.image.getbands())


def _to_8bit(im: Image.Image) -> Image.Image:
    """16-bit / 32-bit / float grayscale (thermal, depth) to 8-bit "L",
    stretched over the image's own min..max. A plain convert("L") clips
    every value above 255 to white."""
    try:
        im = im.convert("F")
        lo, hi = im.getextrema()
        if hi > lo:
            scale = 255.0 / (hi - lo)
            im = im.point(lambda v: v * scale - lo * scale)
        else:
            im = im.point(lambda v: v * 0.0)
        return im.convert("L")
    except Exception:
        return im.convert("L")


def decode(path: str, full: bool, preview_max: int) -> LoadedImage:
    with Image.open(path) as im:
        raw_w, raw_h = im.size
        try:
            orient = im.getexif().get(_EXIF_ORIENTATION, 1)
        except Exception:
            orient = 1
        w, h = (raw_h, raw_w) if orient in (5, 6, 7, 8) else (raw_w, raw_h)
        if not full and max(raw_w, raw_h) > preview_max:
            s = preview_max / float(max(raw_w, raw_h))
            try:
                im.draft("RGB", (math.ceil(raw_w * s), math.ceil(raw_h * s)))
            except Exception:
                pass
        im.load()
        if orient != 1:
            im = ImageOps.exif_transpose(im)
        if im.mode.startswith("I") or im.mode == "F":
            im = _to_8bit(im)
        elif im.mode not in ("RGB", "L"):
            im = im.convert("L" if im.mode == "1" else "RGB")
        if not full and max(im.size) > preview_max:
            im.thumbnail((preview_max, preview_max), _BILINEAR, reducing_gap=2.0)
        return LoadedImage(path, im, (w, h), im.size == (w, h))


class ImageLoader:
    def __init__(self, workers: int, cache_bytes: int, preview_max: int):
        self.preview_max = preview_max
        self.cache_bytes = cache_bytes
        self._cache: "OrderedDict[str, LoadedImage]" = OrderedDict()
        self._cache_used = 0
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="img")
        self._results: "queue.Queue" = queue.Queue()
        self._inflight: Set[Tuple[str, bool]] = set()
        self._wanted: Set[str] = set()
        self._notify: Set[Tuple[str, bool]] = set()

    # ---------------------------------------------------------------- cache
    def cached(self, path: str, need_full: bool = False) -> Optional[LoadedImage]:
        with self._lock:
            item = self._cache.get(path)
            if item is None or (need_full and not item.is_full):
                return None
            self._cache.move_to_end(path)
            return item

    def _put(self, item: LoadedImage) -> None:
        with self._lock:
            old = self._cache.get(item.path)
            if old is not None:
                if old.is_full and not item.is_full:
                    return
                self._cache_used -= old.nbytes
            self._cache[item.path] = item
            self._cache.move_to_end(item.path)
            self._cache_used += item.nbytes
            while self._cache_used > self.cache_bytes and len(self._cache) > 1:
                _, ev = self._cache.popitem(last=False)
                self._cache_used -= ev.nbytes

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._cache_used = 0
            self._wanted = set()
            self._notify = set()

    @property
    def cache_info(self) -> Tuple[int, int]:
        with self._lock:
            return len(self._cache), self._cache_used

    # ------------------------------------------------------------- requests
    def set_wanted(self, paths: List[str]) -> None:
        """Paths still worth decoding; queued work for other paths is skipped."""
        with self._lock:
            self._wanted = set(paths)

    def request(self, path: str, full: bool = False) -> None:
        """Decode `path` in the background unless cached; the result appears in poll()."""
        key = (path, full)
        with self._lock:
            self._notify.add(key)
        hit = self.cached(path, need_full=full)
        if hit is not None:
            with self._lock:
                self._notify.discard(key)
            self._results.put((path, hit, None))
            return
        self._submit(key)

    def prefetch(self, paths: List[str]) -> None:
        for p in paths:
            if self.cached(p) is None:
                self._submit((p, False))

    def _submit(self, key: Tuple[str, bool]) -> None:
        with self._lock:
            if key in self._inflight:
                return  # the running job will notify if requested meanwhile
            self._inflight.add(key)
        self._pool.submit(self._work, key)

    def _work(self, key: Tuple[str, bool]) -> None:
        path, full = key
        err = None
        try:
            with self._lock:
                skip = path not in self._wanted
            if not skip and self.cached(path, need_full=full) is None:
                self._put(decode(path, full, self.preview_max))
        except Exception as e:
            err = e
        finally:
            with self._lock:
                self._inflight.discard(key)
                notify = key in self._notify
                self._notify.discard(key)
        if notify:
            item = self.cached(path)
            self._results.put((path, item, err if item is None else None))

    def poll(self) -> List[Tuple[str, Optional[LoadedImage], Optional[Exception]]]:
        out = []
        while True:
            try:
                out.append(self._results.get_nowait())
            except queue.Empty:
                return out

    def shutdown(self) -> None:
        self.set_wanted([])
        self._pool.shutdown(wait=False)
