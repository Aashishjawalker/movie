"""Colours and small drawing helpers for the terminal UI."""

import curses


class Palette:
    def __init__(self, scr):
        self.scr = scr
        self.enabled = False
        try:
            if curses.has_colors():
                curses.start_color()
                curses.use_default_colors()
                curses.init_pair(1, curses.COLOR_CYAN, -1)
                curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
                curses.init_pair(3, curses.COLOR_YELLOW, -1)
                curses.init_pair(4, curses.COLOR_RED, -1)
                curses.init_pair(5, curses.COLOR_GREEN, -1)
                curses.init_pair(6, curses.COLOR_MAGENTA, -1)
                curses.init_pair(7, curses.COLOR_BLUE, -1)
                self.enabled = True
        except Exception:
            self.enabled = False

    def attr(self, pair, extra=0):
        if not self.enabled:
            return extra
        try:
            return curses.color_pair(pair) | extra
        except Exception:
            return extra

    # semantic shorthands
    def title(self):
        return self.attr(1, curses.A_BOLD)

    def selected(self):
        return self.attr(2, curses.A_BOLD)

    def dim(self):
        return self.attr(3)

    def bad(self):
        return self.attr(4)

    def good(self):
        return self.attr(5)


def fit(text, width):
    """Trim to width, adding an ellipsis when it had to cut."""
    text = str(text)
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


def bar(percent, width):
    width = max(4, width)
    filled = int(round(width * max(0.0, min(100.0, percent)) / 100.0))
    return "█" * filled + "░" * (width - filled)


def health_dot(ok):
    return "●" if ok else "○"


KIND_ICON = {
    "stream": "▶",
    "magnet": "⛁",
    "link": "↗",
    "embed": "▣",
    "season": "▤",
    "episode": "▸",
}


def kind_icon(kind):
    return KIND_ICON.get(kind, "•")
