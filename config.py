"""Default settings. Values the user changes in the GUI are persisted to
~/.mylabel/settings.json and override these defaults."""

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")

# Where YOLO label files live (see LabelStore in mylabel/core/storage.py):
# "auto":       find existing labels in any supported layout (recommended)
# "labels_dir": only .../images/... -> .../labels/... or <folder>/labels/
# "same":       only next to the image file
LABELS_MODE = "auto"

# Auto-save (toolbar toggle, remembered in settings.json; this is the first-run
# default). ON: labels are saved when leaving an image and, in the background,
# every AUTOSAVE_INTERVAL_SEC seconds if the current image has changes.
# OFF: nothing is saved automatically; leaving an edited image asks
# Save / Don't Save / Cancel.
AUTOSAVE_DEFAULT = True
AUTOSAVE_INTERVAL_SEC = 30

SHOW_NAMES = True

# Initial color theme: "light" or "dark" (toggled in the toolbar or with T;
# the last choice is remembered in ~/.mylabel/settings.json).
THEME = "light"

# Image cache budget (decoded RGB bytes) and prefetch distance.
CACHE_MAX_BYTES = 512 * 1024 * 1024
PREFETCH_AHEAD = 3
PREFETCH_BEHIND = 1
LOADER_WORKERS = 3

# Images are first decoded at roughly screen resolution (fast JPEG draft mode);
# full resolution is loaded in the background when zooming in past it.
PREVIEW_MAX_SIDE = 2560

# A new box is rejected if it has the same class as an existing box and
# IoU >= this threshold.
DUPLICATE_IOU = 0.95

# Minimum box side in original image pixels.
MIN_BOX_SIZE = 2

# Timer stops counting after this many seconds without user input.
IDLE_TIMEOUT_SEC = 60

UNDO_LIMIT = 100

# Number of rows inserted per SQLite transaction while indexing.
INDEX_BATCH = 5000

# Maximum number of images indexed per opened folder (0 = no limit). Indexing
# stops at this count and the status bar says so; open a subfolder to
# annotate the rest. Changing it rescans the folder on the next open.
MAX_IMAGES = 200_000
