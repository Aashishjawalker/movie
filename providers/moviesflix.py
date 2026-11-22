"""moviesflixz.co.in — DLE blog, file-host links + an embedded player.

The download buttons lead to nexdrive pages. Those pages (the `.help` / `.one`
variants) are plain HTML that hand out a "G-Direct" link to a fast-dl / fastdl
landing page. That landing page hides the real file behind a tiny JS step:

    click  ->  GET <landing>/dl/dl.php?code=..&secret=..&prepare=1&hash=..&cfs=..
               (Accept: application/json)
           <-  {"ok":true,"url":"https://video-downloads.googleusercontent.com/.."}

Note the path: the anchor href is relative to `/dl/<code>`, so it resolves to
`/dl/dl.php`, *not* `/dl.php`. That is why a plain `/dl.php?...` answers 404.

The returned googleusercontent URL is a real file (video/mkv, correct
Content-Disposition) and is bound to the requesting IP, so it is resolved on
the phone, right before the download starts.
"""

import json
import re
import secrets
import urllib.parse

import net
from net import unescape
from providers.base import Hit, Source, Provider, guess_year, relevance

BASE = "https://moviesflixz.co.in"
SEARCH = BASE + "/index.php?do=search&subaction=search&story={q}"

ARTICLE = re.compile(
    r'<article class="post-item[^"]*">(.*?)</article>', re.S | re.I
)
TITLE_LINK = re.compile(
    r'<h3 class="entry-title[^"]*">\s*<a href="([^"]+)"[^>]*>([^<]*)</a>', re.S
)
DOWNLOAD_LINK = re.compile(
    r'<a[^>]+href="(https?://[^"]+)"[^>]*>.{0,500}?Click Here To Download\s*\[([^\]]*)\]',
    re.S | re.I,
)
PLAYER_SRC = re.compile(r'IndStreamPlayerConfigs\s*=\s*\{(.*?)\}', re.S)
FAST_LINK = re.compile(
    r'class="download direct"[^>]*href="(https?://[^"]+)"'
    r'|href="(https?://[^"]+)"[^>]*class="download direct"'
)
FAST_ANY = re.compile(r'href="(https?://(?:fast-dl|fastdl)[^"]*/dl/[^"]+)"')
DL_TOKEN = re.compile(r'dl\.php\?code=([^"&\s]+)&\s*(?:amp;)?secret=([^"\s]+)')

LANG_WORDS = (
    "hindi", "english", "tamil", "telugu", "malayalam", "kannada",
    "dual audio", "dubbed",
)


def _clean(text):
    return unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()


def _lang_tags(title):
    low = title.lower()
    return ", ".join(
        dict.fromkeys(word for word in LANG_WORDS if word in low)
    )


# --------------------------------------------------------------------------- #
# fast-dl / fastdl resolution
# --------------------------------------------------------------------------- #
def resolve_fastdl(landing, timeout=20):
    """Landing page -> direct file url. Returns (url, reason)."""
    try:
        html = net.text(landing, timeout=timeout)
    except Exception as exc:
        return None, net.status_line(exc)
    token = DL_TOKEN.search(html)
    if not token:
        return None, "no download token on page"
    code = token.group(1)
    secret = token.group(2).replace("&amp;", "&")
    base = landing.split("/dl/", 1)[0]
    params = {
        "code": code,
        "secret": secret,
        "prepare": "1",
        "hash": secrets.token_hex(12),
        "cfs": secrets.token_hex(8),
    }
    api = base + "/dl/dl.php?" + urllib.parse.urlencode(params)
    try:
        body = net.text(
            api,
            headers={"Accept": "application/json", "Referer": landing},
            timeout=timeout,
        )
    except Exception as exc:
        return None, net.status_line(exc)
    try:
        data = json.loads(body)
    except Exception:
        return None, "unexpected answer"
    if not data.get("ok") or not data.get("url"):
        return None, (data.get("error") or "no url")[:60]
    return data["url"], "ok"


def resolve_host(url, timeout=20):
    """nexdrive page -> fast-dl landing -> direct file url."""
    try:
        html = net.text(url, timeout=timeout)
    except Exception as exc:
        return None, net.status_line(exc)

    direct = ""
    match = FAST_LINK.search(html)
    if match:
        direct = match.group(1) or match.group(2) or ""
    if not direct:
        any_link = FAST_ANY.search(html)
        if any_link:
            direct = any_link.group(1)
    if not direct:
        return None, "host page has no direct link"
    return resolve_fastdl(direct, timeout)


class MoviesFlix(Provider):
    id = "moviesflix"
    name = "moviesflixz.co.in"
    badge = "MF"
    colour = 5
    home_url = BASE + "/"
    supports_pages = False

    # ---- search --------------------------------------------------------- #
    def search(self, query, limit=15):
        url = SEARCH.format(q=urllib.parse.quote_plus(query.strip()))
        html = net.text(url, timeout=18)
        hits, seen = [], set()
        for block in ARTICLE.findall(html):
            link = TITLE_LINK.search(block)
            if not link:
                continue
            href, title = link.group(1), unescape(link.group(2))
            if href in seen:
                continue
            seen.add(href)
            # strip the trailing site suffix for a cleaner row
            clean_title = re.sub(r"\s*Moviesflix\s*$", "", title, flags=re.I)
            hits.append(
                Hit(
                    self.id,
                    clean_title,
                    guess_year(clean_title),
                    subtitle=_lang_tags(clean_title),
                    kind="movie",
                    ref={"url": href},
                    score=relevance(query, clean_title),
                )
            )
            if len(hits) >= limit:
                break
        return hits

    # ---- details -------------------------------------------------------- #
    def _page(self, hit):
        url = hit.ref.get("url")
        if not url:
            raise net.NetError("no page for this result")
        return url, net.text(url, timeout=20)

    def about(self, hit):
        _url, html = self._page(hit)
        plot = re.search(
            r'<div class="entry-content[^"]*"[^>]*>(.*?)</div>\s*<h3', html, re.S
        )
        info = re.search(r"Movie Name</strong>\s*:\s*([^<]+)", html, re.I)
        return {
            "title": hit.title,
            "meta": " · ".join(
                part for part in (hit.year, hit.subtitle, "moviesflix") if part
            ),
            "plot": _clean(plot.group(1))[:400] if plot else "",
            "cast": [],
            "extra": _clean(info.group(1)) if info else "",
        }

    # ---- sources -------------------------------------------------------- #
    def sources(self, hit):
        url, html = self._page(hit)
        out, seen = [], set()
        for match in DOWNLOAD_LINK.finditer(html):
            link, size = match.group(1), match.group(2).strip()
            if link in seen:
                continue
            seen.add(link)
            out.append(
                Source(
                    f"Download · {size or 'file'}",
                    "file",
                    link,
                    size=size,
                    note="in-app, resolves to direct file",
                )
            )
        player = PLAYER_SRC.search(html)
        if player:
            src = re.search(r'src:\s*"([^"]+)"', player.group(1))
            if src:
                out.append(
                    Source(
                        "Watch online (browser)",
                        "embed",
                        "https://allmovieland.link/play/" + src.group(1),
                        note="site player",
                    )
                )
        if not out:
            raise net.NetError("no links on this page")
        out.append(Source("Open page in browser", "link", url, note="site page"))
        return out

    # ---- lazy resolution ------------------------------------------------ #
    def resolve(self, source, hit):
        """Turn a nexdrive link into the real, downloadable file url."""
        if source.kind != "file":
            return source
        url, reason = resolve_host(source.url)
        if not url:
            raise net.NetError(f"{reason} — open it in the browser instead")
        return Source(
            source.label,
            "stream",
            url,
            size=source.size,
            note="direct file",
        )

    def health(self, timeout=8):
        return super().health(timeout=timeout)


provider = MoviesFlix()
