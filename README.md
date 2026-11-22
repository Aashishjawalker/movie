# movie

One terminal command that searches **four** movie sites at once, tells you which
site each result came from, and downloads what you pick.

```
 movie  v2.0.0
 Search one phrase, get every site at once.
 ▸ Search all sites
   Trending movies · netmirror
   Trending series · netmirror
   Latest additions · netmirror
   Site status
   Downloads
   Settings
   Quit
 sites: ●NM  ●MR  ●MF  ●YTS
 downloads land in /storage/emulated/0/Download/Movies
```

```bash
movie                # open the browser
movie --selftest     # check all four sites + a real stream, no UI
movie --search Q     # search every site, plain text
movie --health       # which sites answer right now
```

## The four sites

| badge | site | search | what you get |
| --- | --- | --- | --- |
| `NM` | netmirror.plus | JSON API | direct MP4 — **play** or **download** |
| `MR` | movierulzs.co.in | DLE HTML | magnets (1080p/720p/320p) + player links |
| `MF` | moviesflixz.co.in | DLE HTML | file-host links (browser) + web player |
| `YTS` | yts-official.com | JSON API | magnets with seed counts and sizes |

A search runs all four **in parallel**. Every row carries its site badge, and
the line under the search shows which sites answered:

```
 ●NM ●MR ●MF ○YTS
 YTS: timeout
```

`●` = answered, `○` = down / no answer. The app never blocks on a dead site:
each one gets 12 seconds, the rest of the results come through anyway.

## Keys

| key | action |
| --- | --- |
| `↑` `↓` / `j` `k` | move |
| `enter` | open / play / download |
| `b` `q` `esc` | back (`q` on home quits) |
| `/` | search all sites |
| `s` | site status |
| `d` | downloads list (on a source: start a download) |
| `o` | open the site page in the browser |
| `r` | reload / re-check |
| `n` | next page (netmirror lists) |

## Downloading

* **netmirror** — the real MP4 is fetched at full speed (tested ~3 MB/s) into
  `Download/Movies/`, with the exact `Referer` that CDN host wants.
* **YTS / movierulz** — the magnet is handed to `aria2c`, which runs as a local
  daemon. Progress, speed and seeds show live in the Downloads screen; when it
  finishes, `enter` plays the file.
* **moviesflix** — the download buttons lead to nexdrive / fastdl pages that ask
  for a captcha, so `enter` opens them in your browser. Save from there.

`x` removes a download, `c` clears finished ones. A finished file can be played
straight from the Downloads screen with your chosen player.

## Player

`Settings` picks where streams open: the Android chooser (default) or a fixed
app — VLC, MX Player, mpv, Just Player, Samsung Video, Kodi. Saved in
`~/.config/movie/config.json`.

## If something does not open

* Termux → Settings → Apps → Termux → Advanced → **Display over other apps**:
  allow (needed to start the player).
* Termux battery → **Unrestricted**, so downloads and the stream proxy survive
  the screen turning off.

## Docs

* `README.md` — this page.
* `HOW_IT_WORKS.md` — every request per site, the proxy, the download daemon,
  and a symptom → fix guide for when a site moves or breaks.

## Notes

* Catalogue and files come from third-party sites. Use it only for content you
  are allowed to watch.
* `--serve`, `--mode` and `--referer` are internal flags used by the stream
  proxy.
