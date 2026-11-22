"""Small HTTP layer used by every provider.

Only the standard library. Every call takes a timeout, because one dead site
must never freeze the whole search.
"""

import gzip
import http.client
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
import zlib

from config import UA


class NetError(RuntimeError):
    """Raised when a site cannot be reached or answers with an error page."""


def request(url, headers=None, timeout=15, method="GET", data=None):
    """Return (status, headers, body-bytes). Never raises on HTTP status."""
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    body = data
    if isinstance(body, str):
        body = body.encode()
    req = urllib.request.Request(url, headers=hdrs, method=method, data=body)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw = resp.read()
        status = resp.status
        resp_headers = resp.headers
    except urllib.error.HTTPError as err:
        raw = err.read() or b""
        status = err.code
        resp_headers = err.headers
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
        raise NetError(_short(exc)) from exc
    enc = (resp_headers.get("Content-Encoding") or "").lower()
    try:
        if enc == "gzip":
            raw = gzip.decompress(raw)
        elif enc == "deflate":
            raw = zlib.decompress(raw)
    except Exception:
        pass
    return status, resp_headers, raw


def text(url, headers=None, timeout=15, method="GET", data=None):
    status, _headers, raw = request(url, headers, timeout, method, data)
    if status >= 400:
        raise NetError(f"HTTP {status}")
    return raw.decode("utf-8", "replace")


def json_load(url, headers=None, timeout=15):
    status, _headers, raw = request(url, headers, timeout)
    if status >= 400:
        raise NetError(f"HTTP {status}")
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception as exc:
        raise NetError("not json") from exc


def head(url, headers=None, timeout=12):
    """Return (status, content-type, content-length) using HEAD, GET fallback."""
    hdrs = dict(headers or {})
    try:
        status, resp_headers, _raw = request(url, hdrs, timeout, method="HEAD")
        if status in (405, 501):
            status, resp_headers, _raw = request(url, hdrs, timeout)
    except NetError:
        return None, "", 0
    length = resp_headers.get("Content-Length") or "0"
    try:
        length = int(length)
    except Exception:
        length = 0
    return status, (resp_headers.get("Content-Type") or ""), length


def quote(text):
    return urllib.parse.quote(str(text), safe="")


def _short(exc):
    name = exc.__class__.__name__
    msg = str(exc)
    if isinstance(exc, socket.timeout) or "timed out" in msg.lower():
        return "timeout"
    if "Name or service not known" in msg or "Temporary failure" in msg:
        return "dns failed"
    if "Connection refused" in msg:
        return "refused"
    return f"{name}: {msg}"[:80]


def status_line(exc):
    """Turn an exception into a short human reason for the status bar."""
    if isinstance(exc, NetError):
        return str(exc)
    return _short(exc)


def strip_tags(html):
    import re

    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = html.replace("&nbsp;", " ").replace("&amp;", "&")
    html = html.replace("&#8211;", "-").replace("&#038;", "&")
    html = html.replace("&quot;", '"').replace("&#039;", "'")
    return re.sub(r"\s+", " ", html).strip()


def unescape(text):
    import html as html_mod

    return html_mod.unescape(text or "").strip()
