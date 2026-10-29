"""Tests for the core (non-GUI) modules. Run: python -m unittest discover tests"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from mylabel.core.annotation import AnnotationDoc, Box, parse_label_lines  # noqa: E402
from mylabel.core.dataset_index import DatasetIndex  # noqa: E402
from mylabel.core.image_loader import decode  # noqa: E402
from mylabel.core.storage import LabelStore, load_classes  # noqa: E402


class AnnotationTest(unittest.TestCase):
    def test_non_box_lines_are_kept_not_misread(self):
        lines = ["0 0.5 0.5 0.2 0.2",
                 "1 0.1 0.1 0.3 0.1 0.3 0.4 0.1 0.4",  # segmentation polygon
                 "2 0.5 0.5 0.2 0.2 0.4 0.4 2",        # pose keypoint
                 "garbage"]
        boxes, extra = parse_label_lines(lines, 100, 100)
        self.assertEqual(len(boxes), 1)
        self.assertEqual(extra, lines[1:])
        doc = AnnotationDoc(boxes, 100, 100, 0.95, extra=extra)
        doc.add(Box(3, 10, 10, 20, 20))
        out = doc.yolo_lines()
        self.assertEqual(out[0], "0 0.500000 0.500000 0.200000 0.200000")
        self.assertEqual(out[-3:], lines[1:])  # extra lines written back unchanged
        self.assertEqual(len(out), 5)

    def test_add_and_remove_many_are_single_undo_steps(self):
        doc = AnnotationDoc([Box(0, 10, 10, 20, 20)], 100, 100, 0.95)
        added = doc.add_many([Box(0, 10, 10, 20, 20),   # duplicate: skipped
                              Box(1, 30, 30, 40, 40), Box(2, 50, 50, 60, 60)])
        self.assertEqual(added, [1, 2])
        doc.remove_many([0, 2])
        self.assertEqual([b.cls for b in doc.boxes], [1])
        doc.undo()
        self.assertEqual([b.cls for b in doc.boxes], [0, 1, 2])
        doc.undo()
        self.assertEqual([b.cls for b in doc.boxes], [0])
        self.assertFalse(doc.dirty)

    def test_undo_to_saved_state_is_clean(self):
        doc = AnnotationDoc([], 100, 100, 0.95)
        doc.add(Box(0, 10, 10, 20, 20))
        self.assertTrue(doc.dirty)
        doc.undo()
        self.assertFalse(doc.dirty)
        doc.add(Box(0, 10, 10, 20, 20))
        doc.mark_saved()
        doc.add(Box(1, 30, 30, 40, 40))
        doc.undo()
        self.assertFalse(doc.dirty)
        doc.undo()  # before the save point
        self.assertTrue(doc.dirty)


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_classes_utf8_bom(self):
        p = self.root / "classes.txt"
        p.write_bytes("person\ncar\n".encode("utf-8-sig"))
        self.assertEqual(load_classes(p), ["person", "car"])

    def test_classes_cp949(self):
        import locale
        enc = locale.getpreferredencoding(False)
        try:
            data = "사람\n차량\n".encode(enc)
        except UnicodeEncodeError:
            self.skipTest("system code page %s cannot encode Korean" % enc)
        p = self.root / "classes.txt"
        p.write_bytes(data)
        self.assertEqual(load_classes(p), ["사람", "차량"])

    def test_background_read_does_not_change_preferred_layout(self):
        (self.root / "a.txt").write_text("0 0.5 0.5 0.1 0.1\n")
        store = LabelStore(self.root, "auto")
        before = store.preferred
        self.assertIsNotNone(store.read_lines("a.jpg", remember=False))
        self.assertEqual(store.preferred, before)
        store.read_lines("a.jpg")
        self.assertEqual(store.preferred, "same")


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "data"
        self.root.mkdir()
        for name in ("a_1.jpg", "ab1.jpg", "c%d.jpg", "d.jpg", "e.jpg"):
            (self.root / name).write_bytes(b"")
        self.db = Path(self.tmp.name) / "index.db"

    def tearDown(self):
        self.tmp.cleanup()

    def _index(self, max_images=0):
        ix = DatasetIndex(self.db, LabelStore(self.root), (".jpg",), 2, max_images)
        ix.start()
        deadline = time.time() + 10
        while ix.busy and time.time() < deadline:
            time.sleep(0.02)
        return ix

    def test_image_limit(self):
        ix = self._index(max_images=3)
        try:
            self.assertEqual(ix.count(), 3)
            self.assertIsNotNone(ix.notice)
        finally:
            ix.close()
        ix = self._index(max_images=0)  # changed limit forces a rescan
        try:
            self.assertEqual(ix.count(), 5)
        finally:
            ix.close()

    def test_find_treats_wildcards_literally(self):
        ix = self._index()
        try:
            self.assertEqual(ix.get_rel(ix.find("a_", -1)), "a_1.jpg")
            self.assertIsNone(ix.find("b_", -1))
            self.assertEqual(ix.get_rel(ix.find("%", -1)), "c%d.jpg")
        finally:
            ix.close()

    def test_restart_uses_fresh_stop_event(self):
        ix = DatasetIndex(self.db, LabelStore(self.root), (".jpg",))
        try:
            old = ix._stop
            ix.start()
            self.assertIsNot(ix._stop, old)
            self.assertTrue(old.is_set())  # the previous run stays stopped
        finally:
            ix.close()


class LoaderTest(unittest.TestCase):
    def test_16bit_image_is_stretched_not_clipped(self):
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "t.png")
            im = Image.new("I;16", (2, 1))
            im.putpixel((0, 0), 1000)
            im.putpixel((1, 0), 3000)
            im.save(p)
            out = decode(p, True, 2560).image
            self.assertEqual(out.mode, "L")
            self.assertEqual((out.getpixel((0, 0)), out.getpixel((1, 0))), (0, 255))


if __name__ == "__main__":
    unittest.main()
