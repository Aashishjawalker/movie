"""movierulzs.co.in — DLE blog, magnets for download, embedded players."""

import re
import urllib.parse

import net
from net import unescape
from providers.base import Hit, Source, Provider, guess_year, relevance

BASE = "https://movierulzs.co.in"
SEARCH = BASE + "/?do=search&subaction=search&story={q}"

FILM_BLOCK = re.compile(
    r'<div class="boxed film">(.*?)</div>\s*</li>', re.S | re.I
)
MAGNET_BLOCK = re.compile(
    r'<a href="(magnet:\?[^"]+)"[^>]*>(.*?)</a>', re.S | re.I
)
LOCATIONS = re.compile(r"locations\s*=\s*\[(.*?)\]", re.S)
LANG_WORDS = (
    "telugu", "tamil", "hindi", "malayalam", "kannada", "english",
    "dubbed", "dual audio", "esub",
)


def _clean(text):
    return unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()


def _lang_tags(title):
    low = title.lower()
    tags = [word for word in LANG_WORDS if word in low]
    return ", ".join(dict.fromkeys(tags))


class MovieRulz(Provider):
    id = "movierulz"
    name = "movierulzs.co.in"
    badge = "MR"
    colour = 6
    home_url = BASE + "/"
    supports_pages = False

    # ---- search --------------------------------------------------------- #
    def search(self, query, limit=15):
        url = SEARCH.format(q=urllib.parse.quote_plus(query.strip()))
        html = net.text(url, timeout=18)
        hits, seen = [], set()
        for block in FILM_BLOCK.findall(html):
            link = re.search(r'<a href="([^"]+)"[^>]*title="([^"]*)"', block, re.I)
            if not link:
                continue
            href, title = link.group(1), unescape(link.group(2))
            if href in seen:
                continue
            seen.add(href)
            hits.append(
                Hit(
                    self.id,
                    title,
                    guess_year(title),
                    subtitle=_lang_tags(title),
                    kind="movie",
                    ref={"url": href},
                    score=relevance(query, title),
                )
            )
            if len(hits) >= limit:
                break
        if not hits:
            # some posts only carry the title in the <p><b> line
            for match in re.finditer(
                r'<p><b>([^<]+)</b></p>\s*</div>', html, re.I
            ):
                title = unescape(match.group(1))
                hits.append(
                    Hit(self.id, title, guess_year(title), _lang_tags(title),
                        "movie", ref={"url": ""}, score=relevance(query, title))
                )
        return hits

    # ---- details -------------------------------------------------------- #
    def _page(self, hit):
        url = hit.ref.get("url")
        if not url:
            raise net.NetError("no page for this result")
        return url, net.text(url, timeout=20)

    def about(self, hit):
        _url, html = self._page(hit)
        title = re.search(r"<title>([^<]*)", html)
        plot = re.search(
            r'<div class="movie-description">(.*?)</div>', html, re.S
        )
        return {
            "title": hit.title,
            "meta": " · ".join(
                part
                for part in (hit.year, hit.subtitle, "movierulz")
                if part
            ),
            "plot": _clean(plot.group(1)) if plot else "",
            "cast": [],
        }

    # ---- sources -------------------------------------------------------- #
    def sources(self, hit):
        url, html = self._page(hit)
        out = []
        for match in MAGNET_BLOCK.finditer(html):
            magnet = match.group(1).replace("&amp;", "&")
            inner = match.group(2)
            size = re.search(r"<small>([^<]*)</small>", inner, re.I)
            label = _clean(size.group(1)) if size else "torrent"
            name = re.search(r"dn=([^&]+)", magnet)
            pretty = ""
            if name:
                pretty = urllib.parse.unquote_plus(name.group(1))[:70]
            out.append(
                Source(
                    f"Torrent · {label}",
                    "magnet",
                    magnet,
                    size=label,
                    note=pretty or "magnet link",
                )
            )

        block = LOCATIONS.search(html)
        if block:
            players = re.findall(r'"([^"]+)"', block.group(1))
            index = 0
            for player in players:
                player = player.strip()
                if not player:
                    continue
                index += 1
                if player.startswith("/"):
                    player = BASE + player
                out.append(
                    Source(
                        f"Watch online · player {index}",
                        "embed",
                        player,
                        note="opens in browser",
                    )
                )
        if not out:
            raise net.NetError("no download links on this page")
        out.append(Source("Open page in browser", "link", url, note="site page"))
        return out

    # ---- health --------------------------------------------------------- #
    def health(self, timeout=8):
        return super().health(timeout=timeout)


provider = MovieRulz()
