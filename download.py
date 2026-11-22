"""Downloads: aria2 over its JSON-RPC socket, with a stdlib fallback.

aria2 handles both plain HTTP (netmirror's direct MP4s, with the referer the
CDN wants) and magnet links (yts / movierulz torrents), and it keeps the
progress in a daemon so the TUI stays responsive.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

from config import UA, download_dir, load_config

TRACKERS = (
    "udp://tracker.opentrackr.org:1337/announce,"
    "udp://open.stealth.si:80/announce,"
    "udp://tracker.torrent.eu.org:451/announce,"
    "udp://exodus.desync.com:6969/announce,"
    "udp://tracker.openbittorrent.com:6969/announce,"
    "udp://open.demonii.com:1337/announce,"
    "udp://tracker.bittor.pw:1337/announce,"
    "udp://opentracker.io:6969/announce"
)

STATE_FILE = os.path.expanduser("~/.config/movie/downloads.json")


def sanitize(name, limit=90):
    name = re.sub(r"[\\/:*?\"<>|\n\r\t]+", " ", name or "download")
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name or "download")[:limit]


class Job:
    """One download, as the UI sees it."""

    def __init__(self, gid, title, kind, path="", url="", added=None):
        self.gid = gid
        self.title = title
        self.kind = kind          # "http" | "torrent"
        self.path = path
        self.url = url
        self.added = added or time.time()
        self.status = "active"
        self.completed = 0
        self.total = 0
        self.speed = 0
        self.error = ""
        self.files = []

    @property
    def percent(self):
        if self.total:
            return min(100.0, 100.0 * self.completed / self.total)
        return 0.0

    @property
    def done(self):
        return self.status in ("complete", "error", "removed")

    def line(self):
        if self.status == "error":
            return f"failed · {self.error[:40]}"
        if self.status == "complete":
            return "finished"
        if self.status == "paused":
            return f"paused {self.percent:.0f}%"
        if self.total:
            return f"{self.percent:5.1f}%  {_rate(self.speed)}  {_size(self.completed)}/{_size(self.total)}"
        return f"starting…  {_rate(self.speed)}"


def _size(num):
    try:
        num = float(num)
    except Exception:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.0f}{unit}" if unit in ("B", "KB") else f"{num:.1f}{unit}"
        num /= 1024.0
    return "-"


def _rate(num):
    return _size(num) + "/s" if num else "-"


class Aria2:
    def __init__(self, port=6899):
        self.port = port
        self.secret = "movie"
        self._lock = threading.Lock()

    # ---- rpc plumbing --------------------------------------------------- #
    def _call(self, method, params=None, timeout=4):
        payload = {
            "jsonrpc": "2.0",
            "id": "movie",
            "method": method,
            "params": ["token:" + self.secret] + list(params or []),
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/jsonrpc",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, socket.timeout, OSError) as exc:
            raise RuntimeError("aria2 not running") from exc
        if body.get("error"):
            raise RuntimeError(body["error"].get("message") or "aria2 error")
        return body.get("result")

    def alive(self):
        try:
            self._call("aria2.getVersion", timeout=2)
            return True
        except Exception:
            return False

    def start(self):
        """Start the daemon once; safe to call repeatedly."""
        if self.alive():
            return True
        binary = shutil.which("aria2c")
        if not binary:
            return False
        cfg = load_config()
        port = int(cfg.get("aria2_port") or self.port)
        self.port = port
        folder = download_dir(cfg)
        log_path = os.path.expanduser("~/.config/movie/aria2.log")
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
        except Exception:
            log_path = "/tmp/movie-aria2.log"
        cmd = [
            binary,
            "--enable-rpc",
            f"--rpc-listen-port={port}",
            "--rpc-listen-all=false",
            f"--rpc-secret={self.secret}",
            "--continue=true",
            "--seed-time=0",
            "--file-allocation=none",
            "--max-concurrent-downloads=4",
            "--max-connection-per-server=4",
            "--split=4",
            "--summary-interval=0",
            "--console-log-level=warn",
            "--daemon=true",
            f"--dir={folder}",
            f"--bt-tracker={TRACKERS}",
            f"--log={log_path}",
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=20)
        except Exception:
            return False
        for _ in range(20):
            if self.alive():
                return True
            time.sleep(0.25)
        return False

    # ---- jobs ----------------------------------------------------------- #
    def add(self, uri, title, kind="http", headers=None, folder=None):
        options = {
            "dir": folder or download_dir(),
            "seed-time": "0",
            "bt-tracker": TRACKERS,
            "user-agent": UA,
            "continue": "true",
            "file-allocation": "none",
        }
        if kind == "torrent":
            options["out"] = sanitize(title) + ".torrent"
        else:
            options["out"] = sanitize(title) + _extension(uri)
        if headers:
            options["header"] = list(headers)
        return self._call("aria2.addUri", [[uri], options])

    def tell(self, gid):
        return self._call("aria2.tellStatus", [gid])

    def remove(self, gid):
        try:
            self._call("aria2.forceRemove", [gid])
        except Exception:
            pass

    def unpause(self, gid):
        try:
            self._call("aria2.unpause", [gid])
        except Exception:
            pass

    def pause(self, gid):
        try:
            self._call("aria2.pause", [gid])
        except Exception:
            pass


def _extension(url):
    path = url.split("?")[0]
    match = re.search(r"\.(mp4|mkv|avi|webm|m4v|mov)$", path, re.I)
    return "." + match.group(1).lower() if match else ".mp4"


class HttpJob(threading.Thread):
    """Fallback downloader: plain ranged GET to a file, progress in memory."""

    def __init__(self, job, headers=None, folder=None):
        super().__init__(daemon=True)
        self.job = job
        self.headers = headers or {}
        self.folder = folder or download_dir()

    def run(self):
        target = os.path.join(self.folder, sanitize(self.job.title) + _extension(self.job.url))
        self.job.path = target
        have = os.path.getsize(target) if os.path.exists(target) else 0
        headers = {"User-Agent": UA, "Accept": "*/*"}
        headers.update(self.headers)
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            req = urllib.request.Request(self.job.url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                if resp.status == 200:
                    have = 0
                self.job.total = total + have
                self.job.completed = have
                mode = "ab" if have else "wb"
                with open(target, mode) as fh:
                    last = time.time()
                    chunk_start = have
                    while True:
                        chunk = resp.read(262144)
                        if not chunk:
                            break
                        fh.write(chunk)
                        self.job.completed += len(chunk)
                        now = time.time()
                        if now - last >= 1:
                            self.job.speed = (self.job.completed - chunk_start) / (now - last)
                            chunk_start = self.job.completed
                            last = now
            self.job.status = "complete"
        except Exception as exc:
            self.job.status = "error"
            self.job.error = str(exc)[:80]


class Manager:
    """Registry of downloads, backed by aria2 when it is available."""

    def __init__(self):
        self.cfg = load_config()
        self.aria = Aria2(int(self.cfg.get("aria2_port") or 6899))
        self.jobs = []
        self._fallbacks = []
        self._load()

    # ---- persistence ---------------------------------------------------- #
    def _load(self):
        try:
            with open(STATE_FILE, encoding="utf-8") as fh:
                rows = json.load(fh)
        except Exception:
            return
        for row in rows:
            job = Job(
                row.get("gid") or "",
                row.get("title") or "download",
                row.get("kind") or "http",
                row.get("path") or "",
                row.get("url") or "",
                row.get("added"),
            )
            self.jobs.append(job)

    def _save(self):
        rows = [
            {
                "gid": job.gid,
                "title": job.title,
                "kind": job.kind,
                "path": job.path,
                "url": job.url,
                "added": job.added,
            }
            for job in self.jobs[-40:]
        ]
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w", encoding="utf-8") as fh:
                json.dump(rows, fh, indent=1)
        except Exception:
            pass

    # ---- adding --------------------------------------------------------- #
    def backend(self):
        if self.aria.start():
            return "aria2"
        return "builtin"

    def add_stream(self, url, title, referer=None):
        folder = download_dir(self.cfg)
        job = Job("", title, "http", url=url)
        if self.aria.start():
            headers = [f"Referer: {referer}"] if referer else None
            gid = self.aria.add(url, title, "http", headers, folder)
            job.gid = gid
        else:
            thread = HttpJob(job, {"Referer": referer} if referer else None, folder)
            thread.start()
            self._fallbacks.append(thread)
        self.jobs.append(job)
        self._save()
        return job

    def add_magnet(self, magnet, title):
        folder = download_dir(self.cfg)
        job = Job("", title, "torrent", url=magnet)
        if self.aria.start():
            job.gid = self.aria.add(magnet, title, "torrent", None, folder)
        else:
            raise RuntimeError("torrents need aria2 (pkg install aria2)")
        self.jobs.append(job)
        self._save()
        return job

    # ---- live status ---------------------------------------------------- #
    def refresh(self):
        """Pull aria2 status into the job objects. Cheap enough for 1 Hz."""
        alive = self.aria.alive()
        for job in self.jobs:
            if job.kind == "torrent" and not job.gid:
                job.status = "removed"
                continue
            if not alive or not job.gid:
                continue
            try:
                info = self.aria.tell(job.gid)
            except Exception:
                if job.status not in ("complete", "error"):
                    job.status = "removed"
                continue
            job.status = info.get("status") or job.status
            followed = info.get("followedBy") or []
            if followed and followed[0]:
                # a magnet first downloads metadata, then continues as a new gid
                job.gid = followed[0]
                try:
                    info = self.aria.tell(job.gid)
                except Exception:
                    pass
                job.status = info.get("status") or job.status
            job.completed = int(info.get("completedLength") or 0)
            job.total = int(info.get("totalLength") or 0)
            job.speed = int(info.get("downloadSpeed") or 0)
            job.error = info.get("errorMessage") or ""
            files = info.get("files") or []
            real_files = [
                f for f in files
                if f.get("path") and "[METADATA]" not in f["path"]
            ]
            if real_files:
                job.files = [f.get("path") for f in real_files]
                biggest = max(
                    real_files,
                    key=lambda f: int(f.get("length") or 0),
                    default=None,
                )
                if biggest and biggest.get("path"):
                    job.path = biggest["path"]
        return self.jobs

    def remove(self, gid):
        self.aria.remove(gid)

    def pause(self, gid):
        self.aria.pause(gid)

    def resume(self, gid):
        self.aria.unpause(gid)

    def clear_finished(self):
        self.jobs = [job for job in self.jobs if not job.done]
        self._save()

    def playable(self, job):
        """Return a local file for a finished job, if there is one."""
        candidates = []
        if job.path and os.path.isfile(job.path):
            candidates.append(job.path)
        for path in job.files:
            if path and os.path.isfile(path):
                candidates.append(path)
        videos = [
            path
            for path in candidates
            if re.search(r"\.(mp4|mkv|avi|webm|m4v|mov)$", path, re.I)
        ]
        pool = videos or candidates
        if not pool:
            return ""
        return max(pool, key=os.path.getsize)


__all__ = ["Manager", "Job", "sanitize", "TRACKERS"]
