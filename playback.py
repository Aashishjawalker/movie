"""Playback: find the referer a CDN wants, proxy it locally, open a player.

The player app cannot send a Referer header and needs range requests, so the
stream is re-served from 127.0.0.1 by a detached process.
"""

import http.client
import http.server
import os
import queue
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse

from config import AM_APK, UA, on_android

STREAM_REFERER = "https://netfilm.world/"
PROBE_MODES = ("referer", "none")


# --------------------------------------------------------------------------- #
# probe
# --------------------------------------------------------------------------- #
def _range_status(url, mode, timeout=10, referer=STREAM_REFERER):
    headers = {"User-Agent": UA, "Accept": "*/*", "Range": "bytes=0-1"}
    if mode == "referer":
        headers["Referer"] = referer
    conn = None
    target = url
    try:
        for _ in range(4):
            parts = urllib.parse.urlsplit(target)
            conn = (
                http.client.HTTPSConnection(parts.hostname, timeout=timeout)
                if parts.scheme == "https"
                else http.client.HTTPConnection(parts.hostname, timeout=timeout)
            )
            path = parts.path + (("?" + parts.query) if parts.query else "")
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.getheader("Location")
                conn.close()
                conn = None
                if not loc:
                    return None, None
                target = urllib.parse.urljoin(target, loc)
                continue
            resp.read(64)
            ctype = resp.getheader("Content-Type") or ""
            if resp.status in (200, 206) and "text/html" in ctype:
                return 0, ctype
            return resp.status, ctype
        return None, None
    except Exception:
        return None, None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def probe(url, referer=STREAM_REFERER):
    """Pick the header mode this host accepts. Returns (mode, status)."""
    last = None
    for mode in PROBE_MODES:
        status, _ctype = _range_status(url, mode, referer=referer)
        if status in (200, 206):
            return mode, status
        if status:
            last = status
    return None, last


def stream_size(url, mode, referer=STREAM_REFERER):
    """Content-Length of a probed stream, or 0."""
    headers = {"User-Agent": UA, "Accept": "*/*", "Range": "bytes=0-0"}
    if mode == "referer":
        headers["Referer"] = referer
    try:
        parts = urllib.parse.urlsplit(url)
        conn = (
            http.client.HTTPSConnection(parts.hostname, timeout=12)
            if parts.scheme == "https"
            else http.client.HTTPConnection(parts.hostname, timeout=12)
        )
        path = parts.path + (("?" + parts.query) if parts.query else "")
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        total = 0
        content_range = resp.getheader("Content-Range") or ""
        if "/" in content_range:
            try:
                total = int(content_range.rsplit("/", 1)[1])
            except Exception:
                total = 0
        if not total:
            try:
                total = int(resp.getheader("Content-Length") or 0)
            except Exception:
                total = 0
        conn.close()
        return total
    except Exception:
        return 0


# --------------------------------------------------------------------------- #
# proxy
# --------------------------------------------------------------------------- #
def make_handler(url, mode, referer=STREAM_REFERER):
    class StreamHandler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _upstream(self, method):
            target = url
            headers = {"User-Agent": UA, "Accept": "*/*", "Connection": "close"}
            if mode == "referer":
                headers["Referer"] = referer
            rng = self.headers.get("Range")
            if rng:
                headers["Range"] = rng
            for _ in range(4):
                parts = urllib.parse.urlsplit(target)
                conn = (
                    http.client.HTTPSConnection(parts.hostname, timeout=40)
                    if parts.scheme == "https"
                    else http.client.HTTPConnection(parts.hostname, timeout=40)
                )
                path = parts.path + (("?" + parts.query) if parts.query else "")
                conn.request(method, path, headers=headers)
                resp = conn.getresponse()
                if resp.status in (301, 302, 303, 307, 308):
                    loc = resp.getheader("Location")
                    conn.close()
                    if not loc:
                        raise IOError("redirect without location")
                    target = urllib.parse.urljoin(target, loc)
                    continue
                return conn, resp
            raise IOError("too many redirects")

        def _copy_headers(self, resp):
            for key in (
                "Content-Type",
                "Content-Length",
                "Content-Range",
                "Accept-Ranges",
                "Last-Modified",
                "ETag",
            ):
                value = resp.getheader(key)
                if value:
                    self.send_header(key, value)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()

        def _serve(self, method):
            try:
                conn, resp = self._upstream(method)
            except Exception:
                self.send_error(502, "upstream unavailable")
                return
            try:
                self.send_response(resp.status)
                self._copy_headers(resp)
                if method == "HEAD":
                    return
                try:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        def do_GET(self):
            self._serve("GET")

        def do_HEAD(self):
            self._serve("HEAD")

    return StreamHandler


class ProxyServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve_stream(url, mode, idle=1800, referer=STREAM_REFERER):
    handler = make_handler(url, mode, referer)
    httpd = ProxyServer(("127.0.0.1", 0), handler)
    print(f"PORT {httpd.server_address[1]}", flush=True)
    last = [time.time()]

    def watch():
        while True:
            time.sleep(20)
            if time.time() - last[0] > idle:
                os._exit(0)

    original = handler.handle

    def handle(self):
        last[0] = time.time()
        return original(self)

    handler.handle = handle
    threading.Thread(target=watch, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def _read_pipe_line(pipe, timeout=8):
    """Read a line from pipe with timeout without select (cross-platform for Windows, Linux, Mac, Android)."""
    q = queue.Queue()

    def reader():
        try:
            line = pipe.readline()
            q.put((line, None))
        except Exception as exc:
            q.put((None, exc))

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        line, exc = q.get(timeout=timeout)
        if exc:
            raise exc
        return line
    except queue.Empty:
        return None


def start_proxy(url, mode, referer=STREAM_REFERER, entry=None):
    """Spawn a detached proxy process and return its port."""
    entry = entry or os.path.join(os.path.dirname(os.path.abspath(__file__)), "movie.py")
    cmd = [sys.executable, entry, "--serve", url, "--mode", mode]
    if referer and referer != STREAM_REFERER:
        cmd += ["--referer", referer]

    kwargs = {}
    if sys.platform == "win32":
        flags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags |= subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        if flags:
            kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        **kwargs,
    )
    line = _read_pipe_line(proc.stdout, timeout=8)
    proc.stdout.close()
    if not line:
        proc.kill()
        raise RuntimeError("proxy did not start")
    line = line.strip()
    if not line.startswith("PORT "):
        proc.kill()
        raise RuntimeError("proxy failed: " + (line or "no output"))
    return int(line.split()[1])


# --------------------------------------------------------------------------- #
# intents and player launchers
# --------------------------------------------------------------------------- #
def _am(args, timeout=30):
    env = os.environ.copy()
    env.pop("LD_PRELOAD", None)
    env.pop("LD_LIBRARY_PATH", None)
    env["CLASSPATH"] = AM_APK
    return subprocess.run(
        ["/system/bin/app_process", "-Xnoimage-dex2oat", "/", "com.termux.termuxam.Am"]
        + args,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _check(proc):
    output = (proc.stdout or "") + (proc.stderr or "")
    low = output.lower()
    if "unable to resolve" in low or "exception occurred" in low or "does not exist" in low:
        raise RuntimeError("no app can open that")
    if proc.returncode != 0:
        raise RuntimeError(
            output.strip().splitlines()[-1] if output.strip() else "launch failed"
        )
    return output


def open_chooser(url, mime="video/mp4"):
    return _am(
        [
            "broadcast", "--user", "0",
            "-a", "android.intent.action.VIEW",
            "-n", "com.termux/com.termux.app.TermuxOpenReceiver",
            "--ez", "chooser", "true",
            "-d", url,
            "--es", "content-type", mime,
        ]
    )


def launch_url(url, player=None, mime="video/mp4"):
    if on_android():
        pkg = (player or {}).get("pkg")
        if pkg:
            proc = _am(
                [
                    "start", "--user", "0",
                    "-a", "android.intent.action.VIEW",
                    "-d", url,
                    "-t", mime,
                    "-p", pkg,
                ]
            )
        else:
            proc = open_chooser(url, mime)
        return _check(proc)

    # Desktop: Windows, macOS, Linux / Ubuntu
    player_name = ((player or {}).get("name") or "").lower()
    candidates = []
    if "vlc" in player_name or not player_name:
        candidates.append("vlc")
    if "mpv" in player_name or not player_name:
        candidates.append("mpv")

    for app in candidates:
        bin_path = shutil.which(app)
        if bin_path:
            subprocess.Popen([bin_path, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ""

    if sys.platform == "win32":
        try:
            os.startfile(url)
            return ""
        except Exception:
            import webbrowser
            webbrowser.open(url)
            return ""
    elif sys.platform == "darwin":
        subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return ""
    elif shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return ""

    import webbrowser
    webbrowser.open(url)
    return ""


def open_in_browser(url):
    if on_android():
        proc = _am(
            ["start", "--user", "0", "-a", "android.intent.action.VIEW", "-d", url]
        )
        return _check(proc)
    import webbrowser
    webbrowser.open(url)
    return ""


def open_magnet(magnet):
    """Hand a magnet to whichever torrent app is installed."""
    if on_android():
        proc = _am(
            [
                "start", "--user", "0",
                "-a", "android.intent.action.VIEW",
                "-d", magnet,
                "-t", "application/x-bittorrent",
            ]
        )
        return _check(proc)

    if sys.platform == "win32":
        try:
            os.startfile(magnet)
            return ""
        except Exception:
            pass
    elif sys.platform == "darwin":
        subprocess.Popen(["open", magnet], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return ""
    elif shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", magnet], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return ""

    raise RuntimeError("no default torrent app found")


def play_file(path, player=None):
    """Open a finished download with the chosen player."""
    if on_android():
        url = "file://" + urllib.parse.quote(path)
        return launch_url(url, player)
    return launch_url(path, player)


def play_stream(url, player=None, referer=STREAM_REFERER):
    """Probe, proxy and launch. Returns the local link."""
    mode, status = probe(url, referer)
    if not mode:
        raise RuntimeError(f"source blocked (HTTP {status}); try another")
    port = start_proxy(url, mode, referer)
    link = f"http://127.0.0.1:{port}/stream.mp4"
    launch_url(link, player)
    return link
