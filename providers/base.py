"""Shared types for the site providers.

A provider turns a search phrase into `Hit`s, and a `Hit` into `Source`s.
Nothing here knows about curses or the terminal.
"""

import time

from net import NetError, head, status_line


class Hit:
    """One search result, already tagged with the site it came from."""

    __slots__ = ("provider", "title", "year", "subtitle", "kind", "ref", "score")

    def __init__(self, provider, title, year="", subtitle="", kind="movie",
                 ref=None, score=0.0):
        self.provider = provider
        self.title = (title or "Untitled").strip()
        self.year = (year or "").strip()
        self.subtitle = (subtitle or "").strip()
        self.kind = kind
        self.ref = ref or {}
        self.score = score

    def __repr__(self):
        return f"<Hit {self.provider} {self.title!r} {self.year}>"


class Source:
    """One playable / downloadable / openable option for a hit.

    kind:
      stream  -> direct http(s) video the proxy can serve
      magnet  -> BitTorrent magnet link (aria2 or a torrent app)
      link    -> a page that leads to a file (browser / file host)
      embed   -> an embedded player page (browser)
    """

    __slots__ = ("label", "kind", "url", "size", "note")

    def __init__(self, label, kind, url, size="", note=""):
        self.label = label
        self.kind = kind
        self.url = url
        self.size = size
        self.note = note

    def __repr__(self):
        return f"<Source {self.kind} {self.label!r}>"


class Provider:
    """Base class. Subclasses fill in id/name/badge/home and the two verbs."""

    id = "base"
    name = "base"
    badge = "??"
    colour = 1
    home_url = ""
    supports_pages = False

    # ---- verbs --------------------------------------------------------- #
    def search(self, query, limit=12):
        raise NotImplementedError

    def sources(self, hit):
        raise NotImplementedError

    # ---- optional ------------------------------------------------------ #
    def browse(self, section, page=0, per=14):
        """Optional curated lists (only netmirror implements this)."""
        raise NotImplementedError

    def health(self, timeout=8):
        """Return (ok, detail, seconds). Never raises."""
        started = time.time()
        if not self.home_url:
            return True, "no check", 0.0
        try:
            status, ctype, _length = head(self.home_url, timeout=timeout)
        except Exception as exc:  # defensive: providers must not break the ui
            return False, status_line(exc), time.time() - started
        took = time.time() - started
        if status is None:
            return False, "unreachable", took
        if status >= 500:
            return False, f"HTTP {status}", took
        if status >= 400 and status not in (403, 429):
            return False, f"HTTP {status}", took
        # 403/429 usually means "cloudflare says slow down", the site is alive
        return True, f"HTTP {status}", took


def relevance(query, title):
    """0..1 textual score: exact title beats a word inside a longer title."""
    import re

    q = (query or "").lower().strip()
    t = (title or "").lower().strip()
    if not q or not t:
        return 0.0
    if q == t:
        return 1.0
    if t.startswith(q):
        return 0.9
    if re.search(r"(?<![a-z0-9])" + re.escape(q) + r"(?![a-z0-9])", t):
        return 0.8
    if q in t:
        return 0.6
    words = [w for w in q.split() if w]
    if not words:
        return 0.0
    hits = sum(1 for word in words if word in t)
    return round(0.5 * hits / len(words), 3)


def guess_year(text):
    import re

    match = re.search(r"\b(19\d{2}|20\d{2})\b", text or "")
    return match.group(1) if match else ""


def human_size(num):
    try:
        num = float(num)
    except Exception:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.0f}{unit}" if unit in ("B", "KB") else f"{num:.2f}{unit}"
        num /= 1024.0
    return ""


__all__ = [
    "Hit",
    "Source",
    "Provider",
    "NetError",
    "relevance",
    "guess_year",
    "human_size",
]
