#!/usr/bin/env python3
"""movie — search netmirror, movierulz, moviesflix and YTS from one terminal.

    movie                 open the browser
    movie --selftest      check every site, one line each
    movie --search Q      search all sites without the UI
    movie --health        site status only
    movie --serve ...     (internal) local stream proxy
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from config import APP, VERSION  # noqa: E402


def selftest():
    import aggregate
    import playback
    import providers as registry

    ok = True

    def step(name, fn):
        nonlocal ok
        try:
            detail = fn()
            print(f"[PASS] {name}: {detail}")
        except Exception as exc:
            ok = False
            print(f"[FAIL] {name}: {exc}")

    print(f"{APP} {VERSION} selftest")

    def check(site):
        ok, detail, seconds = site.health()
        if not ok:
            raise RuntimeError(detail)
        return f"{detail} ({seconds:.1f}s)"

    for site in registry.ALL:
        step(f"{site.id} health", lambda s=site: check(s))

    def search():
        hits, statuses = aggregate.search_all("inception", limit=5)
        if not hits:
            raise RuntimeError("no results from any site")
        per = {key: val.get("count") for key, val in statuses.items()}
        return f"{len(hits)} hits {per}"

    step("merged search", search)

    def netmirror_streams():
        site = registry.get("netmirror")
        hits = site.search("inception", 1)
        if not hits:
            raise RuntimeError("netmirror search empty")
        sources = site.sources(hits[0])
        if not sources:
            raise RuntimeError("no sources")
        mode, status = playback.probe(sources[0].url)
        if not mode:
            raise RuntimeError(f"probe failed (HTTP {status})")
        return f"{len(sources)} source(s), first plays (mode={mode})"

    step("netmirror stream", netmirror_streams)

    def yts_torrents():
        site = registry.get("yts")
        hits = site.search("inception", 1)
        if not hits:
            raise RuntimeError("yts search empty")
        sources = site.sources(hits[0])
        return f"{len(sources)} torrent(s), {sources[0].note}"

    step("yts torrents", yts_torrents)

    def downloader():
        from download import Manager

        manager = Manager()
        return "aria2 ready" if manager.aria.start() else "builtin http only"

    step("download backend", downloader)

    print("RESULT: " + ("ok" if ok else "problems above"))
    return 0 if ok else 1


def main(argv=None):
    if argv is None:
        argv = sys.argv
    args = list(argv[1:])
    if not args:
        from ui.app import run

        run()
        return 0

    flag = args[0]
    if flag in ("-h", "--help"):
        print(__doc__)
        return 0
    if flag in ("-V", "--version"):
        print(f"{APP} {VERSION}")
        return 0
    if flag == "--selftest":
        return selftest()
    if flag == "--health":
        import aggregate

        for site_id, (ok, detail, seconds) in aggregate.health_all().items():
            print(f"{'ok  ' if ok else 'DOWN'} {site_id:10} {detail:20} {seconds:.1f}s")
        return 0
    if flag == "--search":
        import aggregate

        query = " ".join(args[1:]) or "inception"
        hits, statuses = aggregate.search_all(query)
        for site_id, state in statuses.items():
            flag_text = "ok" if state["ok"] else "DOWN"
            detail = state["detail"]
            print(f"# {site_id:10} {flag_text:4} {detail:18} {state['count']} hits")
        for hit in hits:
            print(f"[{hit.provider:10}] {hit.year:4} {hit.title}  {hit.subtitle}")
        return 0
    if flag == "--serve":
        import playback

        url = args[1]
        mode = "none"
        referer = playback.STREAM_REFERER
        if "--mode" in args:
            mode = args[args.index("--mode") + 1]
        if "--referer" in args:
            referer = args[args.index("--referer") + 1]
        playback.serve_stream(url, mode, referer=referer)
        return 0

    print(f"unknown option: {flag}\n")
    print(__doc__)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        sys.exit(130)
