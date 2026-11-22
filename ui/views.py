"""Every screen: what it draws and which keys it answers.

The App object owns the curses window and the task runner; these functions
only read/write the current view dict and call back into the App.
"""

import curses
import textwrap
import time

from ui.theme import bar, fit, health_dot, kind_icon

ENTER_KEYS = (curses.KEY_ENTER, 10, 13, ord(" "))
UP_KEYS = (curses.KEY_UP, ord("k"))
DOWN_KEYS = (curses.KEY_DOWN, ord("j"))


# --------------------------------------------------------------------------- #
# home
# --------------------------------------------------------------------------- #
def draw_home(app, body_h, width):
    app.put(2, 1, "Search one phrase, get every site at once.", app.pal.dim())
    for index, (label, _action) in enumerate(app.HOME):
        y = 4 + index
        if y >= body_h:
            break
        selected = index == app.view["sel"]
        attr = app.pal.selected() if selected else 0
        if selected:
            app.put(y, 0, " " * (width - 1), attr)
        app.put(y, 1, ("▸ " if selected else "  ") + label, attr)

    y = 4 + len(app.HOME) + 1
    status = app.site_status or {}
    if status:
        parts = []
        for site in app.sites:
            state = status.get(site.id) or {}
            ok = state.get("ok")
            parts.append(f"{health_dot(bool(ok))}{site.badge}")
        app.put(y, 2, "sites: " + "  ".join(parts), app.pal.dim())
    else:
        app.put(y, 2, "site status: press s (or just search)", app.pal.dim())
    app.put(y + 1, 2, "downloads land in " + app.download_dir, app.pal.dim())


def key_home(app, ch):
    count = len(app.HOME)
    if ch in UP_KEYS:
        app.view["sel"] = (app.view["sel"] - 1) % count
    elif ch in DOWN_KEYS:
        app.view["sel"] = (app.view["sel"] + 1) % count
    elif ch in ENTER_KEYS:
        app.activate(app.HOME[app.view["sel"]][1])
    elif ch == ord("/"):
        app.open_search()
    elif ch == ord("s"):
        app.open_status()
    elif ch == ord("d"):
        app.open_downloads()


# --------------------------------------------------------------------------- #
# search input
# --------------------------------------------------------------------------- #
def draw_search(app, body_h, width):
    app.put(2, 2, "Search every site", app.pal.dim())
    query = app.view.get("query", "")
    app.put(4, 1, "› ", app.pal.title())
    app.put(4, 3, fit(query, width - 5), curses.A_BOLD)
    app.put(4, 3 + min(len(query), width - 5), "█", app.pal.title())
    y = 6
    app.put(y, 2, "sites: " + ", ".join(site.name for site in app.sites), app.pal.dim())
    if app.last_query:
        app.put(y + 2, 2, "last: " + app.last_query, app.pal.dim())


def key_search(app, ch):
    query = app.view.get("query", "")
    if ch == 27:
        app.pop()
    elif ch in (curses.KEY_BACKSPACE, 127, 8):
        app.view["query"] = query[:-1]
    elif ch in (curses.KEY_ENTER, 10, 13):
        text = query.strip()
        if len(text) >= 2:
            app.pop()
            app.run_search(text)
        else:
            app.say("type at least two letters")
    elif 32 <= ch < 127:
        app.view["query"] = query + chr(ch)


# --------------------------------------------------------------------------- #
# results (merged across sites)
# --------------------------------------------------------------------------- #
def draw_results(app, body_h, width):
    statuses = app.view.get("statuses") or {}
    if statuses:
        parts = []
        for site in app.sites:
            state = statuses.get(site.id)
            if not state:
                continue
            ok = state.get("ok")
            label = site.badge if ok else f"{site.badge}✕"
            parts.append((label, ok, state))
        x = 1
        for label, ok, state in parts:
            attr = app.pal.good() if ok else app.pal.bad()
            app.put(1, x, health_dot(ok) + label, attr)
            x += len(label) + 2
            if x > width - 6:
                break
        broken = [s for s in app.sites if statuses.get(s.id) and not statuses[s.id].get("ok")]
        if broken:
            detail = ", ".join(
                f"{s.badge}: {statuses[s.id].get('detail')}" for s in broken
            )
            app.put(2, 1, fit(detail, width - 2), app.pal.bad())
        else:
            total = len(app.view.get("hits") or [])
            app.put(2, 1, f"{total} result(s) from {len(parts)} site(s)", app.pal.dim())
    else:
        app.put(1, 1, "searching every site…", app.pal.dim())

    hits = app.view.get("hits") or []
    if not hits:
        if statuses:
            app.put(4, 2, "Nothing found. / to try another phrase.", app.pal.dim())
        return

    sel = app.view["sel"]
    app.ensure_visible(body_h - 3, len(hits))
    top = app.view["top"]
    for row, hit in enumerate(hits[top : top + body_h - 3]):
        index = top + row
        y = 3 + row
        selected = index == sel
        attr = app.pal.selected() if selected else 0
        if selected:
            app.put(y, 0, " " * (width - 1), attr)
        badge = f"[{app.badge_of(hit.provider)}]"
        app.put(y, 1, badge, attr if selected else app.badge_attr(hit.provider))
        app.put(y, 1 + len(badge) + 1, fit(hit.year or "----", 4), attr)
        title_room = width - (1 + len(badge) + 1 + 5) - 12
        app.put(y, 1 + len(badge) + 6, fit(hit.title, max(10, title_room)), attr)
        if width >= 54:
            extra = hit.subtitle or hit.kind
            app.put(y, max(1, width - len(extra) - 2), fit(extra, 18),
                    attr if selected else app.pal.dim())


def key_results(app, ch):
    hits = app.view.get("hits") or []
    if ch in UP_KEYS:
        app.view["sel"] = max(0, app.view["sel"] - 1)
    elif ch in DOWN_KEYS:
        app.view["sel"] = min(max(0, len(hits) - 1), app.view["sel"] + 1)
    elif ch == curses.KEY_PPAGE:
        app.view["sel"] = max(0, app.view["sel"] - 8)
    elif ch == curses.KEY_NPAGE:
        app.view["sel"] = min(max(0, len(hits) - 1), app.view["sel"] + 8)
    elif ch == curses.KEY_HOME:
        app.view["sel"] = 0
    elif ch == curses.KEY_END:
        app.view["sel"] = max(0, len(hits) - 1)
    elif ch in ENTER_KEYS:
        if hits:
            app.open_detail(hits[app.view["sel"]])
    elif ch == ord("n"):
        app.next_page()
    elif ch == ord("r"):
        app.reload_results()
    elif ch == ord("/"):
        app.open_search()
    elif ch == ord("o"):
        hit = hits[app.view["sel"]] if hits else None
        if hit:
            app.open_hit_page(hit)


# --------------------------------------------------------------------------- #
# detail
# --------------------------------------------------------------------------- #
def draw_detail(app, body_h, width):
    view = app.view
    about = view.get("about") or {}
    y = 1
    app.put(y, 1, fit(about.get("title") or view["hit"].title, width - 2), app.pal.title())
    y += 1
    site = app.provider_name(view["hit"].provider)
    meta = about.get("meta") or view["hit"].year
    app.put(y, 1, fit(f"{site} · {meta}", width - 2), app.pal.dim())
    y += 2
    plot = about.get("plot") or ""
    if plot:
        for line in textwrap.wrap(plot, max(20, width - 4))[: max(3, body_h - 8)]:
            app.put(y, 2, line)
            y += 1
    cast = about.get("cast") or []
    if cast and y < body_h - 2:
        y += 1
        app.put(y, 2, fit("Cast: " + ", ".join(cast), width - 4), app.pal.dim())
    hint_y = body_h - 1
    app.put(hint_y, 2, "enter → sources for this title", app.pal.dim())


def key_detail(app, ch):
    if ch in ENTER_KEYS:
        app.open_sources(app.view["hit"])
    elif ch == ord("o"):
        app.open_hit_page(app.view["hit"])
    elif ch == ord("r"):
        app.open_detail(app.view["hit"])


# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #
def draw_sources(app, body_h, width):
    view = app.view
    sources = view.get("sources") or []
    app.put(1, 1, fit(f"{app.badge_of(view['hit'].provider)} {view['hit'].title}", width - 2),
            app.pal.dim())
    if not sources:
        app.put(3, 2, "Looking for links…" if view.get("loading") else "No links found.", app.pal.dim())
        return
    sel = view["sel"]
    app.ensure_visible(body_h - 2, len(sources))
    top = view["top"]
    for row, source in enumerate(sources[top : top + body_h - 2]):
        index = top + row
        y = 2 + row
        selected = index == sel
        attr = app.pal.selected() if selected else 0
        if selected:
            app.put(y, 0, " " * (width - 1), attr)
        icon = kind_icon(source.kind)
        app.put(y, 1, icon + " ", attr if selected else app.pal.title())
        room = width - 4
        tail = " ".join(part for part in (source.size, source.note) if part)
        label_room = room - (len(tail) + 2 if tail and width > 56 else 0)
        app.put(y, 3, fit(source.label, max(12, label_room)), attr)
        if tail and width > 56:
            app.put(y, max(3, width - len(tail) - 2), fit(tail, 30),
                    attr if selected else app.pal.dim())


def key_sources(app, ch):
    sources = app.view.get("sources") or []
    if ch in UP_KEYS:
        app.view["sel"] = max(0, app.view["sel"] - 1)
    elif ch in DOWN_KEYS:
        app.view["sel"] = min(max(0, len(sources) - 1), app.view["sel"] + 1)
    elif ch in ENTER_KEYS:
        if sources:
            app.activate_source(sources[app.view["sel"]], app.view["hit"])
    elif ch == ord("d"):
        if sources:
            app.download_source(sources[app.view["sel"]], app.view["hit"])
    elif ch == ord("o"):
        if sources:
            app.open_source_page(sources[app.view["sel"]])
    elif ch == ord("r"):
        app.open_sources(app.view["hit"], reload=True)


# --------------------------------------------------------------------------- #
# episodes (netmirror series)
# --------------------------------------------------------------------------- #
def draw_episodes(app, body_h, width):
    view = app.view
    app.put(1, 1, fit(f"{view['hit'].title} · season {view['season']}", width - 2),
            app.pal.dim())
    episodes = view.get("sources") or []
    sel = view["sel"]
    app.ensure_visible(body_h - 2, len(episodes))
    top = view["top"]
    for row, source in enumerate(episodes[top : top + body_h - 2]):
        index = top + row
        y = 2 + row
        selected = index == sel
        attr = app.pal.selected() if selected else 0
        if selected:
            app.put(y, 0, " " * (width - 1), attr)
        app.put(y, 1, ("▸ " if selected else "  ") + source.label, attr)


def key_episodes(app, ch):
    episodes = app.view.get("sources") or []
    if ch in UP_KEYS:
        app.view["sel"] = max(0, app.view["sel"] - 1)
    elif ch in DOWN_KEYS:
        app.view["sel"] = min(max(0, len(episodes) - 1), app.view["sel"] + 1)
    elif ch in ENTER_KEYS:
        if episodes:
            app.activate_source(episodes[app.view["sel"]], app.view["hit"])
    elif ch == ord("d"):
        if episodes:
            app.download_source(episodes[app.view["sel"]], app.view["hit"])


# --------------------------------------------------------------------------- #
# downloads
# --------------------------------------------------------------------------- #
def draw_downloads(app, body_h, width):
    jobs = app.jobs
    app.put(1, 1, f"downloading to {app.download_dir}", app.pal.dim())
    if not jobs:
        app.put(3, 2, "Nothing yet. Pick a source and press d.", app.pal.dim())
        return
    sel = app.view["sel"]
    app.ensure_visible(body_h - 2, len(jobs))
    top = app.view["top"]
    bar_room = 10 if width >= 56 else 6
    for row, job in enumerate(jobs[top : top + body_h - 2]):
        index = top + row
        y = 2 + row
        selected = index == sel
        attr = app.pal.selected() if selected else 0
        if selected:
            app.put(y, 0, " " * (width - 1), attr)
        tag = "⛁" if job.kind == "torrent" else "▶"
        app.put(y, 1, tag, attr if selected else app.pal.title())
        app.put(y, 3, bar(job.percent, bar_room), attr if selected else app.pal.good())
        pct = f"{job.percent:3.0f}%"
        app.put(y, 4 + bar_room, pct, attr)
        room = width - (5 + bar_room + 4) - (0 if width < 64 else 24)
        app.put(y, 5 + bar_room + 3, fit(job.title, max(8, room)), attr)
        if width >= 64:
            app.put(y, max(1, width - 25), fit(job.line(), 23),
                    attr if selected else app.pal.dim())


def key_downloads(app, ch):
    jobs = app.jobs
    if ch in UP_KEYS:
        app.view["sel"] = max(0, app.view["sel"] - 1)
    elif ch in DOWN_KEYS:
        app.view["sel"] = min(max(0, len(jobs) - 1), app.view["sel"] + 1)
    elif ch in ENTER_KEYS:
        if jobs:
            app.play_download(jobs[app.view["sel"]])
    elif ch == ord("x"):
        if jobs:
            app.remove_download(jobs[app.view["sel"]])
    elif ch == ord("c"):
        app.manager.clear_finished()
        app.jobs = app.manager.jobs
        app.say("cleared finished downloads")


# --------------------------------------------------------------------------- #
# site status
# --------------------------------------------------------------------------- #
def draw_status(app, body_h, width):
    rows = app.view.get("rows")
    if rows is None:
        app.put(2, 2, "Checking every site…", app.pal.dim())
        return
    app.put(1, 1, "site status (r to check again)", app.pal.dim())
    for index, (site, ok, detail, seconds) in enumerate(rows):
        y = 2 + index
        attr = app.pal.good() if ok else app.pal.bad()
        app.put(y, 1, health_dot(ok) + " " + site.badge, attr)
        app.put(y, 6, fit(site.name, 24), 0)
        app.put(y, 32 if width > 50 else 6 + len(site.name) + 1,
                fit(f"{detail}  {seconds:.1f}s", max(10, width - 34)),
                app.pal.dim())


def key_status(app, ch):
    if ch == ord("r"):
        app.open_status(reload=True)


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #
def draw_settings(app, body_h, width):
    app.put(1, 1, "streams open in:", app.pal.dim())
    for index, player in enumerate(app.players):
        y = 2 + index
        selected = index == app.view["sel"]
        attr = app.pal.selected() if selected else 0
        if selected:
            app.put(y, 0, " " * (width - 1), attr)
        app.put(y, 1, ("▸ " if selected else "  ") + player["name"], attr)
    y = 3 + len(app.players)
    app.put(y, 2, "downloads: " + app.download_dir, app.pal.dim())
    app.put(y + 1, 2, "torrents: aria2 " + ("ready" if app.aria_ready else "missing"), app.pal.dim())


def key_settings(app, ch):
    if ch in UP_KEYS:
        app.view["sel"] = (app.view["sel"] - 1) % len(app.players)
    elif ch in DOWN_KEYS:
        app.view["sel"] = (app.view["sel"] + 1) % len(app.players)
    elif ch in ENTER_KEYS:
        app.set_player(app.players[app.view["sel"]]["name"])


DRAW = {
    "home": draw_home,
    "search": draw_search,
    "results": draw_results,
    "detail": draw_detail,
    "sources": draw_sources,
    "episodes": draw_episodes,
    "downloads": draw_downloads,
    "status": draw_status,
    "settings": draw_settings,
}

KEYS = {
    "home": key_home,
    "search": key_search,
    "results": key_results,
    "detail": key_detail,
    "sources": key_sources,
    "episodes": key_episodes,
    "downloads": key_downloads,
    "status": key_status,
    "settings": key_settings,
}

HINTS = {
    "home": "↑↓ move · enter open · / search · s sites · d downloads · q quit",
    "search": "type · enter search all sites · esc back",
    "results": "↑↓ move · enter details · / search · n more · o open page · b back",
    "detail": "enter sources · o site page · b back",
    "sources": "enter play/open · d download · o browser · r reload · b back",
    "episodes": "enter play · d download · b back",
    "downloads": "enter play file · x remove · c clear finished · b back",
    "status": "r check again · b back",
    "settings": "↑↓ choose player · enter save · b back",
}
