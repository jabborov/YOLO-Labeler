"""Class colors shared by the canvas, class bar and panels."""

PALETTE = (
    "#ff3b30", "#34c759", "#007aff", "#ff9500", "#af52de", "#00c7be",
    "#ffcc00", "#ff2d55", "#5856d6", "#a2845e", "#30b0c7", "#8e8e93",
    "#64d2ff", "#bf5af2", "#ffd60a", "#32d74b", "#ff6482", "#0a84ff",
)


def class_color(cls: int) -> str:
    return PALETTE[cls % len(PALETTE)]


def _rgb(c: str):
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _luminance(c: str) -> float:
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(c)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def readable_on(color: str, bg: str, min_contrast: float = 3.0) -> str:
    """`color` darkened (on light bg) or lightened (on dark bg) just enough to be
    readable as text on `bg`, keeping its hue."""
    target = (0, 0, 0) if _luminance(bg) > 0.4 else (255, 255, 255)
    r, g, b = _rgb(color)
    out = color
    for step in range(11):
        t = step / 10.0
        out = "#%02x%02x%02x" % tuple(int(round(v + (tv - v) * t))
                                      for v, tv in zip((r, g, b), target))
        if _contrast(out, bg) >= min_contrast:
            break
    return out


def text_color_on(bg: str) -> str:
    r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
    return "#000000" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"
