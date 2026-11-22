"""The curses shell: input loop, task runner, navigation and actions."""

import curses
import time
import traceback

import aggregate
import download as download_mod
import playback
import providers as registry
from config import (
    PLAYERS,
    VERSION,
    download_dir,
    load_config,
    player_by_name,
    save_config,
)
from ui import views
from ui.theme import Palette, fit

HOME = [
    ("Search all sites", "search"),
    ("Trending movies · netmirror", "trend_movies"),
    ("Trending series · netmirror", "trend_series"),
    ("Latest additions · netmirror", "latest"),
    ("Site status", "status"),
    ("Downloads", "downloads"),
    ("Settings", "settings"),
    ("Quit", "quit"),
]

KEY_SEQ = {
    "[A": curses.KEY_UP, "[B": curses.KEY_DOWN, "[C": curses.KEY_RIGHT,
    "[D": curses.KEY_LEFT, "[H": curses.KEY_HOME, "[F": curses.KEY_END,
    "OH": curses.KEY_HOME, "OF": curses.KEY_END, "[5~": curses.KEY_PPAGE,
    "[6~": curses.KEY_NPAGE, "[1~": curses.KEY_HOME, "[4~": curses.KEY_END,
    "OA": curses.KEY_UP, "OB": curses.KEY_DOWN, "OC": curses.KEY_RIGHT,
    "OD": curses.KEY_LEFT,
}


class Task:
    def __init__(self, fn, label="Working"):
        self.fn = fn
        self.label = label
        self.result = None
        self.error = None
        self.done = False
        self.callback = None

    def start(self):
        import threading

        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self):
        try:
            self.result = self.fn()
        except Exception as exc:
            self.error = exc
        finally:
            self.done = True


class App:
    def __init__(self, scr):
        self.scr = scr
        self.cfg = load_config()
        self.sites = registry.enabled(self.cfg)
        self.players = list(PLAYERS)
        self.player = player_by_name(self.cfg.get("player"))
        self.download_dir = download_dir(self.cfg)
        self.manager = download_mod.Manager()
        self.manager.cfg = self.cfg
        self.jobs = self.manager.jobs
        self.aria_ready = bool(self.manager.aria.alive())
        self.views = [{"kind": "home", "sel": 0, "top": 0}]
        self.HOME = HOME
        self.task = None
        self.spin = 0
        self.toast = ""
        self.toast_at = 0.0
        self.site_status = {}
        self.last_query = ""
        self._last_refresh = 0.0
        self.pal = Palette(scr)
        scr.keypad(True)
        scr.timeout(120)
        try:
            curses.set_escdelay(50)
        except Exception:
            pass
        curses.curs_set(0)

    # ---- helpers --------------------------------------------------------- #
    @property
    def view(self):
        return self.views[-1]

    def push(self, view):
        view.setdefault("sel", 0)
        view.setdefault("top", 0)
        self.views.append(view)

    def pop(self):
        if len(self.views) > 1:
            self.views.pop()

    def say(self, text):
        self.toast = str(text)
        self.toast_at = time.time()

    def badge_of(self, provider_id):
        site = registry.get(provider_id)
        return site.badge if site else "??"

    def provider_name(self, provider_id):
        site = registry.get(provider_id)
        return site.name if site else provider_id

    def badge_attr(self, provider_id):
        site = registry.get(provider_id)
        return self.pal.attr(site.colour if site else 1, curses.A_BOLD)

    def load(self, fn, callback, label="Working"):
        self.task = Task(fn, label)
        self.task.callback = callback
        self.task.start()

    def ensure_visible(self, body_h, total):
        body_h = max(1, body_h)
        sel, top = self.view["sel"], self.view["top"]
        if sel < top:
            top = sel
        elif sel >= top + body_h:
            top = sel - body_h + 1
        self.view["top"] = max(0, min(top, max(0, total - 1)))

    def put(self, y, x, text, attr=0):
        height, width = self.scr.getmaxyx()
        if y < 0 or y >= height or x >= width or x < 0:
            return
        text = str(text)
        room = width - x - 1
        if room <= 0:
            return
        try:
            self.scr.addstr(y, x, text[:room], attr)
        except curses.error:
            pass

    # ---- actions --------------------------------------------------------- #
    def activate(self, action):
        if action == "quit":
            raise SystemExit
        if action == "search":
            self.open_search()
        elif action == "status":
            self.open_status()
        elif action == "downloads":
            self.open_downloads()
        elif action == "settings":
            self.push({"kind": "settings", "sel": self._player_index()})
        elif action == "latest":
            self.open_browse("latest", "Latest additions · netmirror")
        elif action == "trend_movies":
            self.open_browse("movies", "Trending movies · netmirror")
        elif action == "trend_series":
            self.open_browse("series", "Trending series · netmirror")

    def _player_index(self):
        for index, player in enumerate(self.players):
            if player["name"] == self.cfg.get("player"):
                return index
        return 0

    def set_player(self, name):
        self.cfg["player"] = name
        save_config(self.cfg)
        self.player = player_by_name(name)
        self.say("player: " + name)
        self.pop()

    # ---- search ---------------------------------------------------------- #
    def open_search(self):
        self.push({"kind": "search", "query": "", "sel": 0, "top": 0})

    def run_search(self, query):
        self.last_query = query
        view = {
            "kind": "results",
            "title": f"search · {query}",
            "hits": [],
            "statuses": {},
            "query": query,
            "page": 0,
            "has_more": False,
            "loader": None,
        }
        self.push(view)
        self.load(
            lambda: aggregate.search_all(query, limit=10, config=self.cfg),
            lambda result: self.results_loaded(view, result, 0),
            "Searching 4 sites",
        )

    def open_browse(self, section, title):
        site = registry.get("netmirror")
        view = {
            "kind": "results",
            "title": title,
            "hits": [],
            "statuses": {},
            "query": "",
            "page": 0,
            "has_more": False,
            "loader": lambda page: site.browse(section, page=page),
        }
        self.push(view)
        self.load(
            lambda: self._browse_page(view, 0),
            lambda result: self.results_loaded(view, result, 0),
            title,
        )

    def _browse_page(self, view, page):
        hits, more = view["loader"](page)
        return hits, {"netmirror": {"ok": True, "detail": "ok", "ms": 0,
                                    "count": len(hits)}}, more

    def results_loaded(self, view, result, page):
        hits, statuses, has_more = (list(result) + [False])[:3]
        if page == 0:
            view["hits"] = hits
        else:
            view["hits"].extend(hits)
        view["statuses"] = statuses or {}
        view["page"] = page
        view["has_more"] = bool(has_more)
        self.site_status = statuses or {}
        if view["query"] and statuses:
            down = [s.badge for s in self.sites
                    if statuses.get(s.id) and not statuses[s.id].get("ok")]
            if down:
                self.say("site down: " + ", ".join(down))
        if not view["hits"]:
            self.say("no results")

    def reload_results(self):
        view = self.view
        view["sel"] = 0
        view["top"] = 0
        if view.get("query"):
            view["hits"] = []
            view["statuses"] = {}
            self.load(
                lambda: aggregate.search_all(view["query"], limit=10, config=self.cfg),
                lambda result: self.results_loaded(view, result, 0),
                "Searching again",
            )
        elif view.get("loader"):
            view["hits"] = []
            self.load(
                lambda: self._browse_page(view, 0),
                lambda result: self.results_loaded(view, result, 0),
                "Reloading",
            )

    def next_page(self):
        view = self.view
        if not view.get("has_more") or not view.get("loader"):
            self.say("last page")
            return
        page = view["page"] + 1
        self.load(
            lambda: self._browse_page(view, page),
            lambda result: self.results_loaded(view, result, page),
            f"page {page + 1}",
        )

    # ---- detail / sources ------------------------------------------------ #
    def open_detail(self, hit):
        view = {"kind": "detail", "hit": hit, "about": {}, "sel": 0, "top": 0}
        self.push(view)
        site = registry.get(hit.provider)

        def work():
            if hasattr(site, "about"):
                return site.about(hit)
            return {"title": hit.title,
                    "meta": " ".join(p for p in (hit.year, hit.subtitle) if p),
                    "plot": "", "cast": []}

        self.load(work, lambda about: view.update({"about": about}), "Loading details")

    def open_sources(self, hit, reload=False):
        site = registry.get(hit.provider)
        if reload and self.view.get("kind") == "sources":
            view = self.view
            view["sources"] = []
            view["loading"] = True
        else:
            view = {"kind": "sources", "hit": hit, "sources": [],
                    "loading": True, "sel": 0, "top": 0}
            self.push(view)
        self.load(
            lambda: site.sources(hit),
            lambda sources: self._sources_loaded(view, sources),
            "Finding links",
        )

    def _sources_loaded(self, view, sources):
        view["sources"] = sources
        view["loading"] = False
        if not sources:
            self.say("no links")

    def open_episodes(self, hit, season):
        site = registry.get(hit.provider)
        view = {"kind": "episodes", "hit": hit, "season": season,
                "sources": [], "sel": 0, "top": 0}
        self.push(view)
        self.load(
            lambda: site.episodes(hit, season),
            lambda eps: view.update({"sources": eps}),
            f"Season {season}",
        )

    def _resolved(self, source, hit):
        site = registry.get(hit.provider)
        if source.kind in ("episode", "file") and hasattr(site, "resolve"):
            return site.resolve(source, hit)
        return source

    def activate_source(self, source, hit):
        if source.kind == "season":
            self.open_episodes(hit, source.url)
            return
        if source.kind == "magnet":
            self.download_source(source, hit)
            return
        if source.kind == "file":
            self.download_source(source, hit)
            return
        if source.kind in ("link", "embed"):
            self.open_source_page(source)
            return
        if source.kind == "episode":
            self.load(
                lambda: self._resolved(source, hit),
                lambda resolved: self.play(resolved, hit),
                "Resolving episode",
            )
            return
        self.play(source, hit)

    def play(self, source, hit):
        player = self.player

        def work():
            mode, status = playback.probe(source.url)
            if not mode:
                raise RuntimeError(f"source blocked (HTTP {status}) — try another")
            port = playback.start_proxy(source.url, mode)
            link = f"http://127.0.0.1:{port}/stream.mp4"
            playback.launch_url(link, player)
            return link

        self.load(work, lambda _link: self.say("playing in " + player["name"].split(" (")[0]),
                  "Opening player")

    def download_source(self, source, hit):
        if source.kind == "season":
            self.say("pick an episode first")
            return
        if source.kind in ("link", "embed"):
            self.open_source_page(source)
            self.say("opened in browser — save the file from there")
            return
        if source.kind == "magnet":
            try:
                job = self.manager.add_magnet(source.url, f"{hit.title} {source.size}".strip())
            except Exception as exc:
                self.say(str(exc)[:120])
                return
            self.jobs = self.manager.jobs
            self.say(f"torrent started · {job.title[:30]}")
            return

        def work():
            resolved = self._resolved(source, hit)
            referer = None
            if resolved.kind == "stream" and source.kind != "file":
                mode, _status = playback.probe(resolved.url)
                referer = playback.STREAM_REFERER if mode == "referer" else None
            return self.manager.add_stream(
                resolved.url, f"{hit.title} {resolved.label}".strip(), referer
            )

        label = "Resolving link" if source.kind == "file" else "Starting download"
        self.load(work, lambda job: self._download_started(job), label)

    def _download_started(self, job):
        self.jobs = self.manager.jobs
        self.aria_ready = bool(self.manager.aria.alive())
        self.say(f"downloading · {job.title[:34]}")

    def open_source_page(self, source):
        try:
            if source.kind == "magnet":
                playback.open_magnet(source.url)
            else:
                playback.open_in_browser(source.url)
            self.say("opened in browser")
        except Exception as exc:
            self.say(str(exc)[:120])

    def open_hit_page(self, hit):
        url = (hit.ref or {}).get("url")
        if not url:
            self.say("this site has no page for that title")
            return
        try:
            playback.open_in_browser(url)
            self.say("opened in browser")
        except Exception as exc:
            self.say(str(exc)[:120])

    # ---- downloads ------------------------------------------------------- #
    def open_downloads(self):
        self.jobs = self.manager.refresh()
        self.push({"kind": "downloads", "sel": 0, "top": 0})

    def play_download(self, job):
        if job.status != "complete":
            self.say("still downloading — " + job.line())
            return
        path = self.manager.playable(job)
        if not path:
            self.say("no file yet")
            return
        try:
            playback.play_file(path, self.player)
            self.say("opening " + path.rsplit("/", 1)[-1])
        except Exception as exc:
            self.say(str(exc)[:120])

    def remove_download(self, job):
        self.manager.remove(job.gid)
        self.jobs = [row for row in self.jobs if row is not job]
        self.manager.jobs = self.jobs
        self.manager._save()
        self.say("removed")

    # ---- status ---------------------------------------------------------- #
    def open_status(self, reload=False):
        if reload and self.view.get("kind") == "status":
            view = self.view
        else:
            view = {"kind": "status", "rows": None, "sel": 0, "top": 0}
            self.push(view)

        def work():
            result = aggregate.health_all(timeout=8, config=self.cfg)
            rows = []
            for site in self.sites:
                ok, detail, seconds = result.get(site.id, (False, "no answer", 0))
                rows.append((site, bool(ok), detail, seconds))
                self.site_status[site.id] = {"ok": bool(ok), "detail": detail}
            return rows

        self.load(work, lambda rows: view.update({"rows": rows}), "Checking sites")

    # ---- input / drawing ------------------------------------------------- #
    def read_key(self):
        ch = self.scr.getch()
        if ch != 27:
            return ch
        seq = ""
        self.scr.timeout(30)
        try:
            while len(seq) < 4:
                nxt = self.scr.getch()
                if nxt == -1:
                    break
                seq += chr(nxt)
                if seq in KEY_SEQ:
                    break
                if seq.startswith("[") and seq.endswith("~"):
                    break
                if not (seq.startswith("[") or seq[0] in "O"):
                    break
        finally:
            self.scr.timeout(120)
        return KEY_SEQ.get(seq, 27)

    def crumb(self):
        view = self.view
        kind = view["kind"]
        if kind == "home":
            return ""
        if kind == "results":
            return "› " + fit(view.get("title") or "results", 40)
        if kind == "detail":
            return "› " + fit(view["hit"].title, 40)
        if kind == "sources":
            return "› " + fit(view["hit"].title, 30) + " › links"
        if kind == "episodes":
            return "› " + fit(view["hit"].title, 26) + f" › season {view['season']}"
        if kind == "search":
            return "› search"
        if kind == "downloads":
            return "› downloads"
        if kind == "status":
            return "› site status"
        if kind == "settings":
            return "› settings"
        return ""

    def draw(self):
        scr = self.scr
        height, width = scr.getmaxyx()
        scr.erase()
        header = " movie "
        self.put(0, 0, header, self.pal.title())
        self.put(0, len(header), self.crumb(), self.pal.dim())
        if width > 24:
            self.put(0, max(len(header) + 1, width - 8), f"v{VERSION}", self.pal.dim())

        if self.view["kind"] == "downloads" and time.time() - self._last_refresh > 1.0:
            self.jobs = self.manager.refresh()
            self._last_refresh = time.time()

        body_h = max(1, height - 3)
        drawer = views.DRAW.get(self.view["kind"])
        if drawer:
            try:
                drawer(self, body_h, width)
            except Exception:
                self.put(2, 2, "draw error: " + traceback.format_exc().splitlines()[-1][:80],
                         self.pal.bad())

        hint = self.view.get("hint") or views.HINTS.get(self.view["kind"], "")
        if self.view["kind"] == "results" and self.view.get("has_more"):
            hint = "↑↓ move · enter details · n more · / search · o open page · b back"
        self.put(height - 1, 0, " " * max(0, width - 1))
        self.put(height - 1, 0, hint[: width - 1], self.pal.dim())

        if self.task is not None:
            self.spin += 1
            frames = "|/-\\"
            label = f"{self.task.label} {frames[self.spin % 4]}"
            self.put(height - 2, 0, " " * max(0, width - 1))
            self.put(height - 2, 2, label[: width - 4], self.pal.dim())
        elif self.toast and time.time() - self.toast_at < 4:
            self.put(height - 2, 0, " " * max(0, width - 1))
            self.put(height - 2, 2, fit(self.toast, width - 4), self.pal.title())
        scr.refresh()

    def handle(self, ch):
        kind = self.view["kind"]
        if ch == ord("q") and kind != "search":
            if kind == "home":
                raise SystemExit
            self.pop()
            return
        if ch == 27 and kind != "search":
            if kind == "home":
                raise SystemExit
            self.pop()
            return
        if ch == curses.KEY_RESIZE:
            return
        if ch == ord("b") and kind != "search":
            self.pop()
            return
        handler = views.KEYS.get(kind)
        if handler:
            handler(self, ch)

    def run(self):
        while True:
            self.draw()
            ch = self.read_key()
            if self.task is not None:
                if self.task.done:
                    task, self.task = self.task, None
                    if task.error is not None:
                        self.say(str(task.error)[:160])
                    elif task.callback:
                        task.callback(task.result)
                continue
            if ch == -1:
                continue
            try:
                self.handle(ch)
            except SystemExit:
                raise
            except Exception:
                self.say("error: " + traceback.format_exc().splitlines()[-1][:120])


def run():
    def inner(scr):
        App(scr).run()

    curses.wrapper(inner)
