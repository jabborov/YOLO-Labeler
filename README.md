# YOLO-Labeller

[![Downloads](https://img.shields.io/github/downloads/jabborov/YOLO-Labeler/total?label=downloads)](https://github.com/jabborov/YOLO-Labeler/releases)
[![Latest release](https://img.shields.io/github/v/release/jabborov/YOLO-Labeler?label=release)](https://github.com/jabborov/YOLO-Labeler/releases/latest)

A YOLO bounding-box annotation tool built with Python and Tkinter. It is designed for datasets of up to 200,000 images per opened folder (`MAX_IMAGES` in `config.py`).

## Installation

Requirements: Python 3.8 or later with Tkinter (included in the python.org installers), and Pillow.

Download the latest `YOLO-Labeler-vX.Y.Z.zip` from [Releases](https://github.com/jabborov/YOLO-Labeler/releases/latest) and unzip it (or `git clone` the repository), then:

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

## Running

```bash
python main.py                  # reopens the last folder, if any
python main.py D:\datasets\cam01\images
```

## Usage

1. **Open Folder** – select the image folder. Subfolders are included.
   - The image list fills in the background, and the first image appears as soon as it is indexed.
   - The tool reopens a dataset at the image you last viewed.
   - At most `MAX_IMAGES` (200,000) images are indexed per folder. If a folder has more, the status bar says so; open a subfolder to annotate the rest. Set `MAX_IMAGES = 0` for no limit.
2. **Classes.txt** – select the class file, with one class name per line (UTF-8, UTF-8 with BOM, or the system code page such as CP949).
   - The class file is found automatically if it is in the image folder, in the labels folder, or in the parent folder.
   - If none is found, you are asked whether to reuse the last classes file; the answer is remembered for the folder.
3. **Classes** – choose which classes get a button, using checkboxes.
   - For example, select 20 of 80 classes.
   - Type in the box to filter the list. **All**, **None** and **Invert** act on the filtered rows.
   - The selection is remembered for each classes.txt.
   - Boxes of hidden classes are still drawn and saved.
4. Pick a class with the class buttons or the keys `1`–`9` and `0` (the first ten visible buttons).
   - Each button shows its class id, which is the number written to the label files (e.g. `0: person`, `1: bicycle`).
5. Press `W` (or click **Draw Box**) and drag on the image to draw a box.
6. Move between images with `D` / `A`. The **Auto-save** button next to **Save** switches between two modes:
   - **ON (red):** labels are saved when you leave an image, and in the background every `AUTOSAVE_INTERVAL_SEC` seconds (30 by default, set in `config.py`).
   - **OFF:** nothing is saved automatically. Leaving an image with unsaved changes asks:
     - **Save** – save, then go to the next image.
     - **Don't Save** – discard the changes, then go.
     - **Cancel** – stay on the image and keep the edits.

   The prompt also appears when you jump with the image list, open another folder or close the window. The mode is remembered.

### Mouse

| Action | Effect |
|---|---|
| Hover over a box | The box becomes see-through (thin dashed outline; the class name stays) so the object underneath is visible. Only the smallest box under the cursor changes. |
| Left-drag (draw mode) | Draw a new box with the active class |
| Left-click | Select the smallest box under the cursor |
| `Ctrl`+click / `Shift`+click in the **Bounding boxes** list | Select several boxes (shown with a thick outline) |
| Drag inside a selected box (draw mode off) | Move the box |
| Drag a white handle | Resize the box (corners and edges) |
| Left-drag on an empty area (draw mode off) | Pan the zoomed image |
| Ctrl + left-drag (any mode) | Pan |
| Right- or middle-drag | Pan |
| Mouse wheel | Zoom at the cursor. Zoom-out stops at fit-to-window, and a zoomed image always fills the view (no background gaps). |

### Keyboard

The keys below are the defaults. Click **Hotkeys** in the toolbar to change them:
- Select an action, then double-click it (or press **Change...**) and press the new key or combination, such as `Ctrl+Shift+S`, `Alt+D` or `F2`.
- **Add key...** adds another key to the same action. **Clear** removes its keys, **Default** restores its default keys, and **Reset all** restores every default.
- If a key is already used by another action, you are asked whether to move it.
- Actions without a default key, such as **Auto-save on/off**, **Statistics**, **Classes** and **Hotkeys**, can be given one.
- Hotkeys are saved in `~/.mylabel/settings.json`. While you type in a text box, only `Ctrl` and `Alt` combinations act as hotkeys.

| Key | Action |
|---|---|
| `D` / `→`, `A` / `←` | Next / previous image |
| `W` | Toggle draw mode |
| `1`–`9`, `0` | Select the 1st–10th visible class button; also changes the class of the selected box |
| `Del` / `Backspace` | Delete the selected box(es) |
| `Ctrl+Z` | Undo (per image) |
| `Ctrl+C` | Copy the boxes selected in the **Bounding boxes** list; otherwise the box under the mouse (or the selected box) |
| `Ctrl+V` | Paste the copied boxes at the same position – e.g. on the next video frame |
| `Ctrl+Shift+V` | Paste the copied boxes centered at the mouse pointer |
| `Ctrl+S` | Save now (with no boxes, writes an empty file to mark a reviewed negative image) |
| `Esc` | Cancel the current drag, or deselect |
| `N` | Toggle class names on boxes |
| `T` | Toggle light / dark mode (also the **Dark mode / Light mode** toolbar button; the choice is remembered) |
| `F` | Fit the image to the window |
| `+` / `-` | Zoom in / out at the mouse pointer (window center if the pointer is outside the image area) |
| `U` | Jump to the next image without a label file (same as **Next unlabelled**, see below) |
| `Ctrl+O` | Open a folder |

### Copying boxes between images

In the **Bounding boxes** list, select one or more boxes (`Ctrl`+click / `Shift`+click, or **All**); they are highlighted on the image.
- **◀ Copy** / **Copy ▶** copies them to the previous / next image at the same relative position and opens that image. The copies are unsaved edits there (auto-save or the Save prompt applies) and one `Ctrl+Z` undoes them.
- Boxes that already exist on the target image are skipped, so copying twice never doubles them. The pasted boxes stay selected, so pressing **Copy ▶** again carries them on to the following frame.
- `Ctrl+C` / `Ctrl+V` work with the same selection. Pasting onto the image the boxes came from shifts the copies slightly so they are not rejected as duplicates.
- `Del` deletes all selected boxes (one undo step).
- **Copy selected boxes to previous / next image** can be given hotkeys in the **Hotkeys** dialog.

### Image list

The **Image List** search box takes either an image number (1-based) or part of a file name. A number larger than the image count is searched as a file name; `_` and `%` match literally.

Status markers in the list:
- `✓n` – label file with *n* lines
- `0` – empty label file (reviewed negative)
- `-` – no label file
- `?` – not scanned yet

**Next unlabelled** (key `U`) jumps forward to the next image marked `-` or `?`, i.e. one without a label file. It is meant for labelling a folder from scratch or resuming after a break.
- Images marked `✓n` or `0` count as labelled and are skipped. An empty label file (written by `Ctrl+S` on an image without boxes) counts as a reviewed negative.
- The search only goes forward from the current image and does not wrap around to the first one.
- If nothing is found, the image does not change and the status bar shows *"No unlabelled image after the current one"*.
- When every image already has a label file (e.g. labels created by a model), the button has nothing to jump to.

## Annotation format (YOLO)

Each image has one `.txt` file. Each line describes one box:

```
<class_id> <x_center> <y_center> <width> <height>
```

- All values except `class_id` are normalized to 0–1 by the image width and height, with 6 decimal places.
- `class_id` is the 0-based line number in `classes.txt`.
- Boxes are clipped to the image.
- Only 5-column lines are editable boxes. Other lines (segmentation polygons, OBB, pose keypoints, malformed lines) are not shown, but are kept unchanged when the file is saved; the status bar reports how many.
- EXIF orientation is applied, so coordinates refer to the image as it is displayed. This matches Ultralytics YOLO.
- 16-bit and 32-bit grayscale images (e.g. thermal, depth) are displayed stretched over each image's own min–max range, so the same raw value can look different between images. This affects display only; label coordinates are unaffected.

### Where label files are written

With the default `LABELS_MODE = "auto"` in `config.py`, the tool looks for an existing label file in each of these places, in order:

| Layout | Image | Label |
|---|---|---|
| Ultralytics (`images` → `labels`) | `data/images/train/a.jpg` | `data/labels/train/a.txt` |
| `labels/` subfolder | `<folder>/sub/a.jpg` | `<folder>/labels/sub/a.txt` |
| Next to the image | `<folder>/a.jpg` | `<folder>/a.txt` |

- Under the Ultralytics layout you can open either `data/` or `data/images/`.
- An existing label file is always updated in place.
- A new label file is written in the layout where a label was last found for an image you opened.
- The status bar shows the label path of the current image.
- To allow only one layout, set `LABELS_MODE = "labels_dir"` or `"same"`.

## Large datasets: how it stays fast

- **Index** – the image list and label status are stored in SQLite at `<folder>/.mylabel/index.db`.
  - If the folder is read-only, the index goes to `~/.mylabel/datasets/<hash>/` instead.
  - Python holds only the rows currently visible.
  - Reopening an indexed dataset is instant.
  - At most `MAX_IMAGES` (200,000) images are indexed per folder. Changing `MAX_IMAGES` rescans the folder on the next open; the last viewed image is kept.
- **Background scanning** – a worker thread lists files in sorted order, then reads label files to fill in status and per-class counts.
  - The scan resumes if it is interrupted.
  - **Rebuild index** stops the running scan and starts a new one; a stopped scan that is still finishing slow disk I/O can no longer restart or corrupt the index.
- **Virtual image list** – only the visible rows are queried and drawn.
- **Image loading** – a thread pool decodes images.
  - JPEGs are decoded at reduced size in draft mode, up to `PREVIEW_MAX_SIDE`.
  - Full resolution is loaded automatically when you zoom in past the preview resolution.
  - The next 3 images and the previous one are prefetched into an LRU cache with a size limit (`CACHE_MAX_BYTES`).
  - Requests for images you have already skipped past are dropped.
- **Rendering** – only the visible region is cropped and scaled, so the cost of a frame depends on the window size, not on the image size or zoom level.

## Reliability

- **Atomic saves** – label files are written to a temporary file, flushed with fsync, then renamed with `os.replace`. A crash never leaves a partly written label.
- **Recovery journal** – unsaved edits of the current image are written to `.mylabel/journal.json` 300 ms after each change. On the next start, the tool offers to restore them.
- **Undo-aware change tracking** – undoing back to the last saved state counts as unchanged: no save prompt appears, and the recovery journal is cleared.
- **No lost label lines** – lines the tool cannot edit (segmentation, OBB, pose, malformed) are written back unchanged; only edited images are ever rewritten.
- **Duplicate prevention** – a new or edited box is rejected if a box of the same class overlaps it with IoU ≥ `DUPLICATE_IOU` (0.95). Pasting is the exception described in [Copying boxes between images](#copying-boxes-between-images).
- **Edits during a drag** – deleting, undoing or changing the class while a box is being moved or resized cancels that move/resize first, so the edit is kept.

## Statistics and timer

- **Statistics** shows:
  - labelled, unlabelled and negative image counts
  - box and image counts per class
  - session figures (active time, images saved, average time per image)
- **Rebuild index** (in the Statistics dialog) rescans the folder. Use it after adding or removing images, or after editing labels outside the tool.
- **Timer** shows active session time and time on the current image. It pauses after `IDLE_TIMEOUT_SEC` (60 s) without input.

## Configuration

Defaults are in `config.py`:

| Setting | Default | Meaning |
|---|---|---|
| `MAX_IMAGES` | `200_000` | Images indexed per opened folder (`0` = no limit) |
| `LABELS_MODE` | `"auto"` | Where label files are looked for and written (see above) |
| `AUTOSAVE_DEFAULT` | `True` | Auto-save state on first run |
| `AUTOSAVE_INTERVAL_SEC` | `30` | Background auto-save interval |
| `DUPLICATE_IOU` | `0.95` | IoU at which a same-class box counts as a duplicate |
| `MIN_BOX_SIZE` | `2` | Minimum box side in image pixels |
| `UNDO_LIMIT` | `100` | Undo steps per image |
| `IDLE_TIMEOUT_SEC` | `60` | Timer pauses after this long without input |
| `PREVIEW_MAX_SIDE` | `2560` | Preview decode size before full resolution is loaded |
| `CACHE_MAX_BYTES` | 512 MB | Decoded-image cache budget |
| `PREFETCH_AHEAD` / `PREFETCH_BEHIND` | `3` / `1` | Images prefetched around the current one |
| `THEME`, `SHOW_NAMES` | `"light"`, `True` | Initial look |

Settings you change in the GUI are kept in `~/.mylabel/settings.json` and override these defaults:
- theme, names on/off and auto-save on/off
- hotkeys
- last folder
- the classes file used for each folder, and the visible classes for each classes file

## Project structure

```
mylabel/
├── main.py                  # entry point
├── config.py                # defaults
├── requirements.txt
├── tests/
│   └── test_core.py         # unit tests for the core modules
└── mylabel/
    ├── core/                # no Tkinter imports
    │   ├── annotation.py    # Box model, YOLO parsing/conversion, IoU/duplicates, undo
    │   ├── dataset_index.py # SQLite index + background scanners + statistics
    │   ├── image_loader.py  # decoding thread pool, LRU cache, prefetch, 16-bit display
    │   └── storage.py       # label paths, atomic writes, journal, classes, settings
    └── gui/
        ├── app.py           # main window, wiring, navigation, saving, copy to prev/next
        ├── toolbar.py
        ├── class_bar.py
        ├── canvas_view.py   # rendering, zoom/pan, draw/select/move/resize, hover, copy/paste
        ├── box_panel.py     # box list with multi-select and copy buttons
        ├── image_list.py    # virtualized list
        ├── dialogs.py       # statistics, classes, unsaved changes
        ├── hotkeys.py       # configurable hotkeys and the Hotkeys dialog
        ├── theme.py         # light / dark palettes
        └── colors.py        # class colors
```

## Releases and download count

Pushing a version tag publishes a release automatically (`.github/workflows/release.yml`):

```bash
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions builds `YOLO-Labeler-v1.0.0.zip` from the tagged code and attaches it to a new release with generated notes. The **downloads** badge at the top counts downloads of these release files across all releases.
- `git clone` and GitHub's automatic "Source code (zip)" links are not counted. Clone counts for the last 14 days are visible to the repository owner under **Insights → Traffic**.
- Keep the tag in step with `__version__` in `mylabel/__init__.py`.

## Tests

The core modules (no GUI) have unit tests that use only the standard library and Pillow:

```bash
python -m unittest discover -s tests -v
```
