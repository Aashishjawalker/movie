"""netmirror.plus — JSON catalogue + signed player pages + direct MP4 CDN.

Everything in here is network code; the UI lives elsewhere.
"""

import hashlib
import hmac
import json
import re
import time
import urllib.parse

import net
from providers.base import Hit, Source, Provider, human_size, relevance

API_BASES = ("https://api2.imdb4.shop/api", "https://api2.imdb3.shop/api")
PLAY_BASE = "https://webvp.watch21.shop/play"
HMAC_SECRET = b"net###@@sss"
STREAM_REFERER = "https://netfilm.world/"
SITE_REFERER = "https://netmirror.plus/"

TRENDING = {"movies": "60", "series": "61", "top": "44"}

GENRES = [
    ("Action", "200"), ("Adventure", "8"), ("Animation", "10"),
    ("Biography", "29"), ("Comedy", "12"), ("Crime", "13"),
    ("Documentary", "25"), ("Drama", "14"), ("Family", "38"),
    ("Fantasy", "41"), ("History", "15"), ("Horror", "34"),
    ("Music", "47"), ("Mystery", "16"), ("Romance", "20"),
    ("Sci-Fi", "30"), ("Sport", "27"), ("Thriller", "23"),
    ("War", "32"), ("Western", "58"),
]


class ApiError(RuntimeError):
    pass


def _enc_query(text):
    q = urllib.parse.quote(text.strip())
    return q.replace("%20", "+").replace("%2F", "--slash--")


def api_get(path):
    last = None
    for base in API_BASES:
        try:
            data = net.json_load(base + path)
        except Exception as exc:
            last = exc
            continue
        if isinstance(data, dict) and data.get("system") is not None:
            return data
        last = ApiError("unexpected response")
    raise ApiError(str(last) if last else "api unavailable")


def _year(row):
    return (row.get("release_date") or "").split(",")[-1].strip()[:4]


def search_titles(query, page=0, per=14):
    data = api_get(f"/search2/{_enc_query(query)}?page={page}")
    rows = data.get("results") or []
    pager = data.get("pager") or {}
    more = page < int(pager.get("total_pages") or 1) - 1
    return rows, more


def trending(kind="movies", page=0, per=14):
    cat = TRENDING.get(kind, TRENDING["movies"])
    data = api_get(f"/tranding/list?id={cat}&items_per_page={per}&page={page}")
    rows = data.get("results") or []
    pager = data.get("pager") or {}
    return rows, page < int(pager.get("total_pages") or 1) - 1


def browse(genre_id=None, page=0, per=14):
    params = [f"page={page}", f"items_per_page={per}"]
    if genre_id:
        params.append("genre_id%5B%5D=" + urllib.parse.quote(str(genre_id)))
    data = api_get("/movies/list/filter?" + "&".join(params))
    rows = data.get("results") or []
    pager = data.get("pager") or {}
    return rows, page < int(pager.get("total_pages") or 1) - 1


def details(media_type, internal_id):
    data = api_get(f"/{media_type}/{internal_id}")
    rows = data.get("results") or []
    if not rows:
        raise ApiError("title not found")
    row = dict(rows[0])
    row["media_type"] = row.get("media_type") or media_type
    return row


def sign(tm_id):
    ts = int(time.time())
    sig = hmac.new(HMAC_SECRET, f"{tm_id}:{ts}".encode(), hashlib.sha256).hexdigest()
    return ts, sig


def ext_servers(tm_id, media_type, se=0, ep=0):
    ts, sig = sign(tm_id)
    url = f"{PLAY_BASE}/external.php?tm_id={tm_id}&tm_type={media_type}"
    if media_type == "tv":
        url += f"&se={se}&ep={ep}"
    url += f"&ts={ts}&sig={sig}"
    html = net.text(url, headers={"Referer": SITE_REFERER}, timeout=20)
    match = re.search(r"const servers = (\[.*?\]);", html, re.S)
    if not match:
        return []
    try:
        return json.loads(match.group(1))
    except Exception:
        return []


def watchbox_url(subjectid, dp, tm_id, se, ep):
    ts, sig = sign(tm_id)
    query = urllib.parse.urlencode(
        {
            "id": subjectid or "",
            "se": se or 0,
            "ep": ep or 0,
            "dp": dp or "",
            "na": "",
            "year": "",
            "tm_id": tm_id,
            "ts": ts,
            "sig": sig,
            "nid": "",
            "exten": "",
            "tv": "",
            "token": "",
            "warp": "",
        }
    )
    return f"{PLAY_BASE}/watchbox.php?{query}"


def parse_streams_html(html):
    out = []
    match = re.search(r"const qualities\s*=\s*(\[.*?\]);", html, re.S)
    if match:
        try:
            items = json.loads(match.group(1))
        except Exception:
            items = []
        for item in items:
            if item.get("type") == "dash":
                continue
            url = item.get("url") or ""
            if not url:
                continue
            out.append(
                {
                    "label": (item.get("html") or "").strip() or "stream",
                    "url": url,
                }
            )
    if not out:
        seen = set()
        for url in re.findall(r"https://[A-Za-z0-9.\-]*hakunaymatata\.com[^'\"\s)]+", html):
            if ".mp4" not in url or url in seen:
                continue
            seen.add(url)
            out.append({"label": f"Direct {len(seen)}", "url": url})
    dedup, seen = [], set()
    for item in out:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        dedup.append(item)
    return dedup


def get_streams(row, se=None, ep=None):
    tm_id = str(row.get("tm_id") or "").strip()
    media_type = row.get("media_type") or "movie"
    if not tm_id:
        raise ApiError("this release has no TMDB id, pick another one")
    streams = []
    if media_type == "movie":
        try:
            for srv in ext_servers(tm_id, "movie"):
                if "watchcinemo" in srv.get("url", ""):
                    html = net.text(
                        srv["url"], headers={"Referer": PLAY_BASE + "/"}, timeout=20
                    )
                    streams += parse_streams_html(html)
                    break
        except Exception:
            pass
    try:
        html = net.text(
            watchbox_url(row.get("subjectid"), row.get("dp"), tm_id, se, ep),
            headers={"Referer": PLAY_BASE + "/"},
            timeout=20,
        )
        streams += parse_streams_html(html)
    except Exception:
        pass
    dedup, seen = [], set()
    for item in streams:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        dedup.append(item)
    if not dedup:
        raise ApiError("no playable source for this title")
    return dedup


class NetMirror(Provider):
    id = "netmirror"
    name = "netmirror.plus"
    badge = "NM"
    colour = 1
    home_url = "https://netmirror.plus/"
    supports_pages = True

    def __init__(self):
        self._details = {}

    # ---- search --------------------------------------------------------- #
    def search(self, query, limit=14):
        rows, _more = search_titles(query, 0, limit)
        hits = []
        for row in rows[:limit]:
            title = (row.get("title") or "Untitled").strip()
            hits.append(
                Hit(
                    self.id,
                    title,
                    _year(row),
                    subtitle=self._subtitle(row),
                    kind="series" if row.get("media_type") == "tv" else "movie",
                    ref={
                        "id": str(row.get("id") or ""),
                        "media_type": row.get("media_type") or "movie",
                    },
                    score=relevance(query, title),
                )
            )
        return hits

    @staticmethod
    def _subtitle(row):
        rating = str(row.get("vote_average") or "").strip()
        if row.get("media_type") == "tv":
            seasons = len(row.get("season") or [])
            return f"series · {seasons} season(s)" if seasons else "series"
        return f"{rating}/10" if rating else "movie"

    def browse(self, section, page=0, per=14):
        if section == "latest":
            rows, more = browse(page=page, per=per)
        elif section in TRENDING:
            rows, more = trending(section, page, per)
        else:
            rows, more = browse(genre_id=section, page=page, per=per)
        hits = []
        for row in rows:
            title = (row.get("title") or "Untitled").strip()
            hits.append(
                Hit(
                    self.id,
                    title,
                    _year(row),
                    subtitle=self._subtitle(row),
                    kind="series" if row.get("media_type") == "tv" else "movie",
                    ref={
                        "id": str(row.get("id") or ""),
                        "media_type": row.get("media_type") or "movie",
                    },
                )
            )
        return hits, more

    # ---- details -------------------------------------------------------- #
    def row(self, hit):
        key = (hit.ref.get("media_type"), hit.ref.get("id"))
        if key not in self._details:
            self._details[key] = details(*key)
        return self._details[key]

    def about(self, hit):
        row = self.row(hit)
        return {
            "title": (row.get("title") or hit.title).strip(),
            "meta": " · ".join(
                part
                for part in (
                    _year(row),
                    "series" if row.get("media_type") == "tv" else "movie",
                    f"{(row.get('vote_average') or '-')}/10",
                    row.get("country") or "",
                )
                if part
            ),
            "plot": (row.get("dis") or "").strip().strip('"'),
            "cast": [s.get("name") for s in (row.get("stafflist") or []) if s.get("name")][:8],
        }

    # ---- sources -------------------------------------------------------- #
    def sources(self, hit):
        row = self.row(hit)
        if row.get("media_type") == "tv":
            out = []
            for season in row.get("season") or []:
                se = season.get("se")
                count = season.get("ep")
                out.append(
                    Source(
                        f"Season {se}",
                        "season",
                        str(se),
                        size=f"{count} episodes",
                        note="enter to list episodes",
                    )
                )
            if not out:
                raise ApiError("no episodes listed for this series")
            return out
        streams = get_streams(row)
        return [
            Source(
                item["label"],
                "stream",
                item["url"],
                note="direct mp4",
            )
            for item in streams
        ]

    def episodes(self, hit, season):
        row = self.row(hit)
        info = None
        for season_row in row.get("season") or []:
            if str(season_row.get("se")) == str(season):
                info = season_row
                break
        eps = []
        if info:
            all_ep = (info.get("allEp") or "").strip()
            if all_ep:
                for part in all_ep.replace(";", ",").split(","):
                    part = part.strip()
                    if not part:
                        continue
                    if "-" in part:
                        try:
                            a, b = part.split("-", 1)
                            eps.extend(range(int(a), int(b) + 1))
                        except Exception:
                            pass
                    elif part.isdigit():
                        eps.append(int(part))
            if not eps:
                eps = list(range(1, int(info.get("ep") or 0) + 1))
        out = [
            Source(f"S{int(season):02d}E{n:02d}", "episode", f"{season}:{n}")
            for n in sorted(set(eps))
        ]
        if not out:
            raise ApiError("no episodes in this season")
        return out

    def resolve(self, source, hit):
        if source.kind == "episode":
            se, ep = source.url.split(":")
            streams = get_streams(self.row(hit), int(se), int(ep))
            best = streams[0]
            return Source(best["label"], "stream", best["url"], note="direct mp4")
        return source

    def headers_for(self, url):
        """Which referer this CDN host wants is discovered by the prober."""
        return STREAM_REFERER

    # ---- health --------------------------------------------------------- #
    def health(self, timeout=8):
        started = time.time()
        try:
            net.json_load(API_BASES[0] + "/movie/27205", timeout=timeout)
        except Exception as exc:
            return False, net.status_line(exc), time.time() - started
        return True, "api ok", time.time() - started


provider = NetMirror()
