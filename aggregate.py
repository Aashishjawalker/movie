"""Run every site at once and report which ones answered.

Threads (not processes) because the work is pure waiting on sockets, and a
daemon thread that hangs can be abandoned without blocking the UI or exit.
"""

import threading
import time

import providers as registry
from net import status_line

TIMEOUT = 12


def _fan_out(jobs, timeout):
    """jobs: {key: callable}. Returns ({key: value}, {key: error}, {key: seconds})."""
    values, errors, timings = {}, {}, {}
    lock = threading.Lock()

    def worker(key, fn):
        started = time.time()
        try:
            value = fn()
        except Exception as exc:
            with lock:
                errors[key] = exc
                timings[key] = time.time() - started
            return
        with lock:
            values[key] = value
            timings[key] = time.time() - started

    threads = []
    for key, fn in jobs.items():
        thread = threading.Thread(target=worker, args=(key, fn), daemon=True)
        thread.start()
        threads.append((key, thread))

    deadline = time.time() + timeout
    for key, thread in threads:
        thread.join(max(0.0, deadline - time.time()))

    pending = [key for key, thread in threads if thread.is_alive()]
    return values, errors, timings, pending


def search_all(query, limit=10, timeout=TIMEOUT, config=None):
    """Search every enabled site. Returns (hits, statuses).

    statuses[provider_id] = {"ok": bool, "detail": str, "ms": int, "count": int}
    """
    sites = registry.enabled(config)
    jobs = {site.id: (lambda s=site: s.search(query, limit)) for site in sites}
    values, errors, timings, pending = _fan_out(jobs, timeout)

    hits = []
    statuses = {}
    for site in sites:
        if site.id in pending:
            statuses[site.id] = {
                "ok": False,
                "detail": f"no answer in {timeout}s",
                "ms": int(timeout * 1000),
                "count": 0,
            }
            continue
        if site.id in errors:
            statuses[site.id] = {
                "ok": False,
                "detail": status_line(errors[site.id]),
                "ms": int(timings.get(site.id, 0) * 1000),
                "count": 0,
            }
            continue
        site_hits = values.get(site.id) or []
        site_hits = [hit for hit in site_hits if hit.score >= 0.5]
        statuses[site.id] = {
            "ok": True,
            "detail": "ok" if site_hits else "no matches",
            "ms": int(timings.get(site.id, 0) * 1000),
            "count": len(site_hits),
        }
        hits.extend(site_hits)

    # best textual match first; the badge column already says which site it is
    priority = {site.id: index for index, site in enumerate(registry.ALL)}
    hits.sort(
        key=lambda hit: (
            -hit.score,
            priority.get(hit.provider, 99),
            hit.title.lower(),
        )
    )
    return hits, statuses


def health_all(timeout=8, config=None):
    sites = registry.enabled(config)
    jobs = {site.id: (lambda s=site: s.health(timeout)) for site in sites}
    values, errors, timings, pending = _fan_out(jobs, timeout + 2)
    out = {}
    for site in sites:
        if site.id in pending:
            out[site.id] = (False, "timeout", timeout)
            continue
        if site.id in errors:
            out[site.id] = (False, status_line(errors[site.id]), timings.get(site.id, 0))
            continue
        out[site.id] = values[site.id]
    return out
