"""SQLite index of the dataset: ordered image list, label status, class counts.

Nothing about the dataset is held in Python memory except the rows currently
being displayed. Row `idx` is the 0-based position in the image list, so
random access by position is a primary-key lookup.

images.nboxes:  NULL = not scanned yet, -1 = no label file, >=0 = box count
"""

import os
import sqlite3
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .storage import LabelStore, class_ids_of

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS images (idx INTEGER PRIMARY KEY, rel TEXT NOT NULL, nboxes INTEGER);
CREATE TABLE IF NOT EXISTS class_counts (
    idx INTEGER NOT NULL, cls INTEGER NOT NULL, n INTEGER NOT NULL,
    PRIMARY KEY (idx, cls)) WITHOUT ROWID;
"""
INDEX_VERSION = "2"  # bump to force a rescan of existing indexes


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


class DatasetIndex:
    def __init__(self, db_path: Path, store: LabelStore, extensions, batch: int = 5000,
                 max_images: int = 0):
        self.db_path = Path(db_path)
        self.store = store
        self.extensions = tuple(e.lower() for e in extensions)
        self.batch = batch
        self.max_images = max_images  # 0 = no limit
        self.conn = _connect(self.db_path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

        # Each scan run gets its own stop event, so a run that is still
        # blocked in slow I/O after stop() can never be revived by start().
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Images saved from the GUI during this session; the background label
        # scan must not overwrite their status with stale data.
        self.touched = set()
        self.files_scanning = False
        self.labels_scanning = False
        self.labels_progress = 0
        self.error: Optional[str] = None
        self.notice: Optional[str] = None  # one-time status message (e.g. image limit)

    # ----------------------------------------------------------------- meta
    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                          (key, str(value)))
        self.conn.commit()

    # -------------------------------------------------------------- queries
    def count(self) -> int:
        row = self.conn.execute("SELECT MAX(idx) FROM images").fetchone()
        return 0 if row[0] is None else row[0] + 1

    def get_rel(self, idx: int) -> Optional[str]:
        row = self.conn.execute("SELECT rel FROM images WHERE idx=?", (idx,)).fetchone()
        return row[0] if row else None

    def idx_of(self, rel: str) -> Optional[int]:
        row = self.conn.execute("SELECT idx FROM images WHERE rel=?", (rel,)).fetchone()
        return row[0] if row else None

    def nboxes(self, idx: int) -> Optional[int]:
        row = self.conn.execute("SELECT nboxes FROM images WHERE idx=?", (idx,)).fetchone()
        return row[0] if row else None

    def rows(self, start: int, end: int) -> List[Tuple[int, str, Optional[int]]]:
        """Rows with start <= idx < end."""
        return self.conn.execute(
            "SELECT idx, rel, nboxes FROM images WHERE idx>=? AND idx<? ORDER BY idx",
            (start, end)).fetchall()

    def next_unlabelled(self, after: int) -> Optional[int]:
        row = self.conn.execute(
            "SELECT idx FROM images WHERE idx>? AND (nboxes IS NULL OR nboxes<0) "
            "ORDER BY idx LIMIT 1", (after,)).fetchone()
        return row[0] if row else None

    def find(self, text: str, after: int) -> Optional[int]:
        """Next image (wrapping around) whose relative path contains `text`."""
        text = text.replace("\\", "/")
        for ch in "!%_":  # match "_" and "%" literally, not as LIKE wildcards
            text = text.replace(ch, "!" + ch)
        pat = "%" + text + "%"
        for lo, hi in ((after, None), (-1, after + 1)):
            sql = "SELECT idx FROM images WHERE idx>? AND rel LIKE ? ESCAPE '!'"
            args = [lo, pat]
            if hi is not None:
                sql += " AND idx<?"
                args.append(hi)
            row = self.conn.execute(sql + " ORDER BY idx LIMIT 1", args).fetchone()
            if row:
                return row[0]
        return None

    # -------------------------------------------------------------- updates
    def set_labels(self, idx: int, lines: Optional[List[str]]) -> None:
        """Record the label state of one image (None = no label file)."""
        self.touched.add(idx)
        _write_label_state(self.conn, idx, lines)
        self.conn.commit()

    # ------------------------------------------------------- background scan
    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, rebuild: bool = False) -> None:
        """Index files (if needed) and then label status, in a background thread."""
        self.stop()
        self._stop = stop = threading.Event()
        self.labels_progress = 0
        need_files = (rebuild or self.get_meta("files_complete") != "1"
                      or self.get_meta("version") != INDEX_VERSION
                      or self.get_meta("max_images") != str(self.max_images))
        if need_files:
            self.conn.execute("DELETE FROM images")
            self.conn.execute("DELETE FROM class_counts")
            self.conn.execute("DELETE FROM meta WHERE key<>'last_idx'")
            self.conn.commit()
            self.touched.clear()
        elif self.get_meta("truncated") == "1":
            self.notice = self._limit_notice()
        self._thread = threading.Thread(target=self._run, args=(need_files, stop), daemon=True)
        self._thread.start()

    def _limit_notice(self) -> str:
        return ("Image limit reached: only the first %s images are indexed. "
                "Open a subfolder to annotate the rest." % format(self.max_images, ","))

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None

    def close(self) -> None:
        self.stop()
        self.conn.close()

    def _run(self, need_files: bool, stop: threading.Event) -> None:
        conn = _connect(self.db_path)
        current = lambda: stop is self._stop  # status flags belong to the latest run only
        try:
            if need_files:
                self.files_scanning = True
                if not self._scan_files(conn, stop):
                    return
                self.files_scanning = False
            self.labels_scanning = True
            self._scan_labels(conn, stop)
        except Exception as e:  # reported in the status bar
            if current() and not stop.is_set():
                self.error = "Indexing failed: %s" % e
        finally:
            if current():
                self.files_scanning = False
                self.labels_scanning = False
            conn.close()

    def _iter_images(self, stop: threading.Event):
        """Yield relative paths in a stable sorted depth-first order."""
        root = str(self.store.image_root)
        skip = {os.path.normcase(os.path.abspath(os.path.join(root, ".mylabel")))}
        if self.store.mode != "same":
            skip.add(os.path.normcase(os.path.abspath(str(self.store.label_root))))
        stack = [root]
        while stack:
            d = stack.pop()
            try:
                with os.scandir(d) as it:
                    entries = sorted(it, key=lambda e: e.name)
            except OSError:
                continue
            subdirs = []
            for e in entries:
                if stop.is_set():
                    return
                try:
                    if e.is_dir(follow_symlinks=False):
                        if os.path.normcase(os.path.abspath(e.path)) not in skip:
                            subdirs.append(e.path)
                    elif e.name.lower().endswith(self.extensions):
                        yield os.path.relpath(e.path, root).replace("\\", "/")
                except OSError:
                    continue
            stack.extend(reversed(subdirs))

    def _scan_files(self, conn: sqlite3.Connection, stop: threading.Event) -> bool:
        # INSERT OR REPLACE: a previous run still finishing a batch writes the
        # same (idx, rel) pairs (the order is deterministic), never a conflict.
        sql = "INSERT OR REPLACE INTO images(idx, rel) VALUES (?, ?)"
        buf = []
        idx = 0
        truncated = False
        for rel in self._iter_images(stop):
            if self.max_images and idx >= self.max_images:
                truncated = True
                break
            buf.append((idx, rel))
            idx += 1
            if len(buf) >= self.batch:
                conn.executemany(sql, buf)
                conn.commit()
                buf.clear()
        if stop.is_set():
            return False
        if buf:
            conn.executemany(sql, buf)
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('files_complete', '1')")
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('version', ?)", (INDEX_VERSION,))
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('max_images', ?)", (str(self.max_images),))
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('truncated', ?)", ("1" if truncated else "0",))
        conn.commit()
        if truncated:
            self.notice = self._limit_notice()
        return True

    def _scan_labels(self, conn: sqlite3.Connection, stop: threading.Event) -> None:
        last = -1
        while not stop.is_set():
            rows = conn.execute(
                "SELECT idx, rel FROM images WHERE nboxes IS NULL AND idx>? "
                "ORDER BY idx LIMIT 1000", (last,)).fetchall()
            if not rows:
                break
            # Read files first, then write in one short transaction, so the GUI
            # thread's saves never wait on disk I/O of this scan.
            results = []
            for idx, rel in rows:
                if stop.is_set():
                    break
                last = idx
                if idx not in self.touched:
                    try:
                        results.append((idx, self.store.read_lines(rel, remember=False)))
                    except (OSError, UnicodeDecodeError):
                        pass  # unreadable label: status stays "not scanned"
            for idx, lines in results:
                if idx not in self.touched:
                    _write_label_state(conn, idx, lines)
            conn.commit()
            if stop is self._stop:
                self.labels_progress = last + 1


def _write_label_state(conn: sqlite3.Connection, idx: int,
                       lines: Optional[List[str]]) -> None:
    conn.execute("DELETE FROM class_counts WHERE idx=?", (idx,))
    if lines is None:
        conn.execute("UPDATE images SET nboxes=-1 WHERE idx=?", (idx,))
        return
    counts = class_ids_of(lines)
    conn.execute("UPDATE images SET nboxes=? WHERE idx=?", (sum(counts.values()), idx))
    if counts:
        conn.executemany("INSERT INTO class_counts(idx, cls, n) VALUES (?, ?, ?)",
                         [(idx, c, n) for c, n in counts.items()])


def compute_stats(db_path: Path, done: Callable[[Dict], None]) -> None:
    """Aggregate statistics in a worker thread; `done(stats)` runs in that thread."""

    def work():
        conn = _connect(db_path)
        try:
            total, labelled, nonempty, empty, missing, unknown, boxes = conn.execute(
                "SELECT COUNT(*), SUM(nboxes>=0), SUM(nboxes>0), SUM(nboxes=0), "
                "SUM(nboxes<0), SUM(nboxes IS NULL), SUM(CASE WHEN nboxes>0 THEN nboxes END) "
                "FROM images").fetchone()
            per_class = conn.execute(
                "SELECT cls, SUM(n), COUNT(*) FROM class_counts GROUP BY cls ORDER BY cls"
            ).fetchall()
            done({"total": total or 0, "labelled": labelled or 0, "nonempty": nonempty or 0,
                  "empty": empty or 0, "missing": missing or 0, "unknown": unknown or 0,
                  "boxes": boxes or 0, "per_class": per_class})
        except Exception as e:
            done({"error": str(e)})
        finally:
            conn.close()

    threading.Thread(target=work, daemon=True).start()
