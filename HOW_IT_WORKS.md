# How `movie` works — and how to fix it

`README.md` is how to use it. This file is how it is built and what to do when
a site moves, changes its HTML, or dies.

---

## 1. Layout

```
movie/
├── movie.py              entry point: UI, --selftest, --search, --health, --serve
├── config.py             paths, user agent, players, settings file
├── net.py                HTTP helpers (timeouts, gzip, HEAD, status lines)
├── aggregate.py          runs every site at once, collects hits + site health
├── playback.py           referer probe, localhost proxy, Android intents
├── download.py           aria2 JSON-RPC client + builtin HTTP fallback
├── providers/
│   ├── base.py           Hit / Source / Provider types, relevance scoring
│   ├── __init__.py       registry (order = badge order in the UI)
│   ├── netmirror.py      JSON catalogue + signed player + direct MP4
│   ├── movierulz.py      DLE search, magnets, player embeds
│   ├── moviesflix.py     DLE search, file-host links, web player
│   └── yts.py            TMDB-style search API + torrent index API
└── ui/
    ├── theme.py          colours, truncation, progress bar, icons
    ├── views.py          one draw + one key handler per screen
    └── app.py            the shell: input loop, tasks, navigation, actions
```

Adding a fifth site = one file in `providers/` + one line in
`providers/__init__.py`. Nothing in `ui/` changes: it only knows `Hit`,
`Source` and the provider interface.

### The provider interface

```python
class Provider:
    id, name, badge, colour, home_url
    def search(self, query, limit=10) -> list[Hit]
    def sources(self, hit) -> list[Source]
    def about(self, hit) -> {"title","meta","plot","cast"}   # optional
    def episodes(self, hit, season) -> list[Source]          # optional (series)
    def resolve(self, source, hit) -> Source                 # optional (lazy)
    def health(self, timeout=8) -> (ok, detail, seconds)
```

`Source.kind` decides what `enter` does:

| kind | meaning | enter does |
| --- | --- | --- |
| `stream` | direct http(s) video | probe + proxy + player |
| `magnet` | BitTorrent magnet | start aria2 download |
| `link` | a page that leads to a file | open in browser |
| `embed` | a player page | open in browser |
| `season` | a season of a series | list its episodes |
| `episode` | one episode (URL resolved later) | resolve, then play |

---

## 2. Searching all four at once

`aggregate.search_all(query)`:

1. one daemon thread per provider (`search` is pure socket waiting),
2. join with a 12 s deadline; a thread still alive is reported as
   `no answer in 12s` and abandoned (daemon threads cannot block exit),
3. exceptions become a status (`timeout`, `HTTP 403`, `dns failed`, …),
4. hits below a relevance of `0.5` are dropped (DLE full-text search loves to
   return unrelated posts),
5. the rest are sorted by score, then by site priority, then by title.

`relevance()` in `providers/base.py`:

| title vs query | score |
| --- | --- |
| exact | 1.0 |
| starts with | 0.9 |
| whole-word match | 0.8 |
| substring | 0.6 |
| all words present | 0.5 |
| partial | less, filtered out |

`aggregate.health_all()` does the same fan-out over `Provider.health()`, which
is a `HEAD` request to the site's home page (netmirror checks its API instead,
because the front-end being up does not mean the API is).

---

## 3. The four sites

### 3.1 netmirror.plus — `providers/netmirror.py`

Catalogue JSON, then signed player pages, then a CDN MP4.

```bash
# search
curl -s 'https://api2.imdb4.shop/api/search2/inception?page=0'
# details (their id, not TMDB's)
curl -s 'https://api2.imdb4.shop/api/movie/62426'
# trending 60 movies / 61 series / 44 top, browse latest
curl -s 'https://api2.imdb4.shop/api/tranding/list?id=60&items_per_page=14&page=0'
curl -s 'https://api2.imdb4.shop/api/movies/list/filter?page=0&items_per_page=14'
```

`items_per_page` must be **7, 14 or 30** — anything else returns an empty list.

Signing (HMAC-SHA256 over `"{tm_id}:{ts}"`, key `net###@@sss`):

```bash
TS=$(date +%s)
SIG=$(python3 -c "import hmac,hashlib;print(hmac.new(b'net###@@sss',('27205:$TS').encode(),hashlib.sha256).hexdigest())")
curl -s -H 'Referer: https://netmirror.plus/' \
  "https://webvp.watch21.shop/play/external.php?tm_id=27205&tm_type=movie&ts=$TS&sig=$SIG"
```

The answer contains `const servers = [...]`; Server 1 is `watchcinemo.php`,
whose page holds `const qualities = [{"html":"Mp4-English-1080p","url":"https://…mp4?sign=…"}]`.
Series go through `watchbox.php?id=<subjectid>&se=<season>&ep=<episode>&dp=<dp>`.

`external.php` **only** accepts `Referer: https://netmirror.plus/` (not `www.`,
not another domain, not empty). The front-end site is never contacted otherwise.

### 3.2 movierulzs.co.in — `providers/movierulz.py`

DLE blog. Search is a **GET** (POST is stopped by Cloudflare):

```bash
curl -s 'https://movierulzs.co.in/?do=search&subaction=search&story=inception'
```

Results: `<div class="boxed film">` → `<a href="…html" title="Title">`.

Detail page gives:

* magnets — `<a href="magnet:…" class="mv_button_css">…GET THIS TORRENT <small>3.4 gb 1080p</small></a>`
* players — a JS `locations = [ "/plays/tt1375666", "https://ww7.vcdnlare.com/…", … ]`

The `/plays/<imdb-id>` page builds an HDVB player whose playlist URL
(`salov447hev.com/playlist/….txt`) answers `11` (empty) to a plain client, so
the app does not try to play it. Magnets are the reliable path.

### 3.3 moviesflixz.co.in — `providers/moviesflix.py`

DLE blog with a different theme:

```bash
curl -s 'https://moviesflixz.co.in/index.php?do=search&subaction=search&story=inception'
```

Results: `<article class="post-item site__col">` → `<h3 class="entry-title…"><a href="…">Title</a>`.

Detail page:

* download buttons — `<a href="https://nexdrive.one/…"> <button>…Click Here To Download [1.91 GB]</button></a>`
  (also `fastdl.bar/dl/…`; nexdrive domains rotate: `.one`, `.help`, …)
* web player — `IndStreamPlayerConfigs = {src: "tt1375666"}` →
  `https://allmovieland.link/play/<imdb-id>` → iframe on `slast430did.com`

The file hosts use Cloudflare Turnstile captchas, and `fastdl.bar`'s one-time
`dl.php?code=…&secret=…` link answers 404 even when fetched immediately. So the
app opens them in the browser instead of pretending it can download them.

### 3.4 yts-official.com — `providers/yts.py`

The site is a small JS app with its own JSON API (no `/api/v2`, that redirects
to the homepage):

```bash
curl -s 'https://en.yts-official.com/?api=search&mode=movie&q=inception'
curl -s 'https://en.yts-official.com/?api=search&mode=tv&q=breaking%20bad'
curl -s 'https://en.yts-official.com/?api=torrents&mode=movie&name=Inception&year=2010&quality=all'
```

Search returns TMDB-shaped rows (`title`/`name`, `release_date`/`first_air_date`,
`vote_average`). The torrents call returns:

```json
{"hits":[{"title":"Inception (2010) 1080p BrRip x264 - 1.85GB - YIFY",
          "seeds":870,"peers":90,"bytes":1986422374,
          "magnetUrl":"magnet:?xt=urn:btih:…","hash":"…","source":"The Pirate Bay (proxy)"}],
 "sources":["Knaben"],"total":168}
```

There are **no `.torrent` files** — only magnets. The app sorts by seeds and
keeps the first 14.

---

## 4. Playback (netmirror streams)

Your player cannot send a `Referer`, and it needs HTTP ranges to seek, so:

```
player  → GET http://127.0.0.1:PORT/stream.mp4   Range: bytes=5000000-
proxy   → GET https://bcdn….hakunaymatata.com/x.mp4  Range: … + Referer (if needed)
proxy   ← 206 Content-Range: bytes 5000000-…/2414667149
player  ← same status/headers/bytes
```

* `playback.probe()` asks for **2 bytes**, first with `Referer: https://netfilm.world/`,
  then without, and keeps whichever returns 200/206.
* `playback.start_proxy()` spawns `movie.py --serve <url> --mode <mode>` in a new
  session, reads `PORT <n>` from its stdout, and returns the port.
* The proxy exits by itself 30 minutes after the last request, so quitting the
  TUI does not stop the film.
* Redirects (301/302/307/308) are followed inside the proxy, so signed links can
  hop CDN hosts.

Referer rules seen so far:

| CDN host | wants |
| --- | --- |
| `bcdnxw.hakunaymatata.com` | `https://netfilm.world/` |
| `bcdnt.hakunaymatata.com` | no referer (with it: 429) |

---

## 5. Downloads

`download.py` talks to **aria2** over JSON-RPC on `127.0.0.1:6899`
(`~/.config/movie/config.json → aria2_port`). The daemon is started on demand:

```bash
aria2c --enable-rpc --rpc-listen-port=6899 --rpc-secret=movie --daemon=true \
       --continue=true --seed-time=0 --file-allocation=none \
       --max-concurrent-downloads=4 --dir=/storage/emulated/0/Download/Movies
```

* **HTTP (netmirror)** — `aria2.addUri` with `header: ["Referer: …"]` when the
  probe said that host wants one. Tested at ~3 MB/s.
* **magnet (yts / movierulz)** — `aria2.addUri` with the magnet plus a public
  tracker list (`download.TRACKERS`). aria2 first downloads ~20 KB of metadata
  under one GID and then continues under a **new** GID listed in `followedBy`;
  `Manager.refresh()` follows that so progress keeps counting. Tested at
  ~5 MB/s on a 1.9 GB YTS torrent.
* If `aria2c` is missing, plain MP4s fall back to `HttpJob` (stdlib, ranged,
  resumable); magnets then raise a clear error.
* Job history lives in `~/.config/movie/downloads.json`; finished files are
  played with a `file://` intent.

Install aria2 once if the self-test says `builtin http only`:

```bash
apt-get install -y aria2        # Debian/Ubuntu proot
pkg install aria2               # plain Termux
```

---

## 6. Configuration map

| search for | file | what it is |
| --- | --- | --- |
| `API_BASES` | providers/netmirror.py | catalogue backends, fallback order |
| `PLAY_BASE` | providers/netmirror.py | player host (`watch21`) |
| `HMAC_SECRET` | providers/netmirror.py | `net###@@sss` |
| `SITE_REFERER` | providers/netmirror.py | referer `external.php` demands |
| `STREAM_REFERER` | playback.py | referer for the probe's first attempt |
| `BASE` | providers/movierulz.py, moviesflix.py, yts.py | site roots |
| `TRACKERS` | download.py | trackers appended to magnets |
| `DOWNLOAD_DIRS` | config.py | where files land |
| `PLAYERS` | config.py | intent targets |
| `TIMEOUT` | aggregate.py | per-site search deadline (12 s) |

Back up before editing:

```bash
cd ~/Download/AI_Brain/projects/movie
cp -r . /tmp/movie.bak
```

---

## 7. When something goes wrong

### Step 0 — always

```bash
movie --selftest
```

```
[PASS] netmirror health: api ok (0.4s)
[PASS] movierulz health: HTTP 200 (0.4s)
[PASS] moviesflix health: HTTP 200 (0.3s)
[PASS] yts health: HTTP 200 (0.8s)
[PASS] merged search: 12 hits {...}
[PASS] netmirror stream: 11 source(s), first plays (mode=none)
[PASS] yts torrents: 14 torrent(s), 870 seeds · …
[PASS] download backend: aria2 ready
```

The first `FAIL` names the layer. `movie --health` is the quick version.

### Symptom table

| symptom | cause | fix |
| --- | --- | --- |
| a site shows `○` after search | that site is down/blocked | `s` to re-check; if it stays down, §7.1 |
| `movie: command not found` | shell cache | `hash -r` or new terminal |
| search returns nothing at all | network | `movie --health` |
| netmirror: "no playable source" | release has no `tm_id` (some S1-S5 packs) | pick another release |
| netmirror: "source blocked (HTTP 429/403)" | CDN referer changed | pick another source; §7.3 |
| stream opens then black | signed link expired | `r` in the sources list |
| downloads stuck at `starting…` | aria2 not running / port taken | `movie --selftest`; §7.4 |
| torrent at 0 B/s | no peers / trackers blocked | wait, or pick a source with more seeds |
| "opened in browser" but nothing happens | no browser app | install one, or copy the link |
| player does not open | Termux background start blocked | allow **Display over other apps** |
| downloads die when screen locks | Android killed Termux | battery → **Unrestricted** |
| TUI garbled | terminal size / TERM | resize, `reset`, run again |

### 7.1 A site moved to a new domain

Each provider has one `BASE` (or `API_BASES`/`PLAY_BASE`) constant. Update it,
then:

```bash
movie --selftest
```

To find the new domain, open the site's old address and follow the redirect, or
search for the new name. For netmirror specifically, the live backend and player
hosts are inside its JS bundle:

```bash
curl -s https://netmirror.plus | grep -oE '/assets/index-[^"]*\.js'
curl -s https://netmirror.plus/assets/index-XXXX.js -o /tmp/nm.js
grep -oE 'https://[a-z0-9.]*imdb[0-9]*\.shop[^"`]{0,20}' /tmp/nm.js | sort -u
grep -oE 'https://[a-z0-9.]*(watch|play)[0-9]*\.shop[^"`]{0,30}' /tmp/nm.js | sort -u
```

### 7.2 A DLE site changed its HTML

Symptom: search works (status `ok`) but the list is empty.

```bash
curl -s 'https://movierulzs.co.in/?do=search&subaction=search&story=inception' | grep -o 'class="[^"]*"' | sort | uniq -c | sort -rn | head
```

Update the regex at the top of the provider:

* `movierulz.py`: `FILM_BLOCK` (`<div class="boxed film">`), `MAGNET_BLOCK`, `LOCATIONS`
* `moviesflix.py`: `ARTICLE` (`<article class="post-item…">`), `TITLE_LINK`, `DOWNLOAD_LINK`, `PLAYER_SRC`

A quick sanity check without the UI:

```bash
python3 -c "import providers as r; [print(h) for h in r.get('movierulz').search('inception')]"
```

### 7.3 Every netmirror source is "blocked"

The CDN's referer rule changed. Take a source URL (from the app or from
`watchcinemo.php`) and try the candidates:

```bash
URL='https://bcdn….hakunaymatata.com/….mp4?sign=…&t=…'
for R in "https://netfilm.world/" "" "https://netmirror.plus/"; do
  echo "== ${R:-none}"
  curl -s -o /dev/null -w '%{http_code}\n' --max-time 20 -r 0-1 -A "Mozilla/5.0" \
    ${R:+-H "Referer: $R"} "$URL"
done
```

`206` wins. If it is not `netfilm.world`, edit `STREAM_REFERER` in
`playback.py` (and `STREAM_REFERER` in `providers/netmirror.py`). If a new
behaviour appears (cookie, different UA), add it to `PROBE_MODES` in
`playback.py`.

If `external.php` itself fails, check which referer it now wants:

```bash
TS=$(date +%s)
SIG=$(python3 -c "import hmac,hashlib;print(hmac.new(b'net###@@sss',('27205:$TS').encode(),hashlib.sha256).hexdigest())")
for R in https://netmirror.plus/ https://netmirror.net/ ""; do
  printf '%-24s ' "${R:-none}"
  curl -s --max-time 20 ${R:+-H "Referer: $R"} \
    "https://webvp.watch21.shop/play/external.php?tm_id=27205&tm_type=movie&ts=$TS&sig=$SIG" \
    | grep -c "const servers"
done
```

The line printing `1` is the referer to put in `SITE_REFERER`.

### 7.4 Downloads

```bash
# is the daemon up?
curl -s http://127.0.0.1:6899/jsonrpc -d '{"jsonrpc":"2.0","id":"1","method":"aria2.getVersion","params":["token:movie"]}'

# what is it doing?
tail -20 ~/.config/movie/aria2.log

# restart it
pkill -f '[a]ria2c'
python3 -c "import download; print(download.Manager().aria.start())"
```

If port 6899 is busy, change `aria2_port` in `~/.config/movie/config.json`.

### 7.5 Is the stream proxy healthy?

While a film plays:

```bash
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' -r 0-1 \
  "http://127.0.0.1:PORT/stream.mp4"
```

`206 video/mp4` = proxy and CDN are fine. Or check the real duration:

```bash
ffprobe -v error -show_entries format=duration,size -of default=nw=1 \
  "http://127.0.0.1:PORT/stream.mp4"
```

### 7.6 Player does not open

1. Termux → Display over other apps → allow.
2. Termux battery → Unrestricted.
3. `Settings` → Android chooser.
4. By hand:

```bash
am start -a android.intent.action.VIEW -d "http://127.0.0.1:PORT/stream.mp4" -t video/mp4
```

---

## 8. What to send if you want help

1. `movie --selftest` output
2. `movie --search "<the title>"` output (shows which site failed and why)
3. the toast text, if any
4. what you pressed last (title → source → play/download)

---

## 9. Limits

* netmirror series packs without a `tm_id` cannot be signed, so they cannot be
  played; the app says so instead of hanging.
* movierulz/moviesflix web players are browser-only: their embed pages need
  JavaScript and, in moviesflix's case, a captcha.
* Links expire; `r` re-resolves them.
* Torrents need `aria2c` and peers; if your network blocks trackers, use a VPN.
* Third-party catalogues. Use only for content you may watch.
