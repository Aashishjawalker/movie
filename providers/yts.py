"""yts-official.com — TMDB-style search API plus a torrent index API."""

import urllib.parse

import net
from providers.base import Hit, Source, Provider, human_size, relevance

BASE = "https://en.yts-official.com"
SEARCH = BASE + "/?api=search&mode={mode}&q={q}"
TORRENTS = BASE + "/?api=torrents&mode={mode}&name={name}&year={year}&quality=all"


def _year(row):
    date = row.get("release_date") or row.get("first_air_date") or ""
    return (date or "")[:4]


class Yts(Provider):
    id = "yts"
    name = "yts-official.com"
    badge = "YTS"
    colour = 3
    home_url = BASE + "/"
    supports_pages = False

    # ---- search --------------------------------------------------------- #
    def search(self, query, limit=10):
        hits = []
        for mode in ("movie", "tv"):
            try:
                data = net.json_load(
                    SEARCH.format(mode=mode, q=urllib.parse.quote(query.strip())),
                    timeout=18,
                )
            except Exception:
                continue
            for row in (data.get("results") or [])[:limit]:
                title = (row.get("title") or row.get("name") or "").strip()
                if not title:
                    continue
                year = _year(row)
                rating = row.get("vote_average") or 0
                try:
                    rating = f"{float(rating):.1f}"
                except Exception:
                    rating = str(rating)
                hits.append(
                    Hit(
                        self.id,
                        title,
                        year,
                        subtitle=f"{rating}/10 · {mode}",
                        kind="series" if mode == "tv" else "movie",
                        ref={
                            "name": title,
                            "year": year,
                            "id": row.get("id"),
                            "mode": mode,
                        },
                        score=relevance(query, title),
                    )
                )
        hits.sort(key=lambda h: -h.score)
        return hits[: min(limit, 6)]
    # ---- sources -------------------------------------------------------- #
    def sources(self, hit):
        mode = hit.ref.get("mode") or "movie"
        url = TORRENTS.format(
            mode=mode,
            name=urllib.parse.quote(hit.ref.get("name") or hit.title),
            year=urllib.parse.quote(hit.ref.get("year") or ""),
        )
        data = net.json_load(url, timeout=25)
        rows = data.get("hits") or []
        rows.sort(key=lambda r: -(r.get("seeds") or 0))
        out = []
        for row in rows[:14]:
            magnet = (row.get("magnetUrl") or "").replace("&amp;", "&")
            if not magnet:
                continue
            seeds = row.get("seeds") or 0
            size = human_size(row.get("bytes"))
            title = (row.get("title") or "torrent")[:64]
            out.append(
                Source(
                    title,
                    "magnet",
                    magnet,
                    size=size,
                    note=f"{seeds} seeds · {row.get('source') or 'tracker'}",
                )
            )
        if not out:
            raise net.NetError("no torrents for this title")
        return out

    def health(self, timeout=8):
        return super().health(timeout=timeout)


provider = Yts()
