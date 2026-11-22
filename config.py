"""Settings, paths and constants shared by every module."""

import json
import os

APP = "movie"
VERSION = "2.0.0"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.expanduser("~/.config/movie")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)

# Where finished films land. The first one that exists wins.
DOWNLOAD_DIRS = (
    "/storage/emulated/0/Download/Movies",
    "/storage/emulated/0/Download",
    os.path.expanduser("~/Downloads"),
)

# Android intent helper (Termux:API am binary)
AM_APK = "/data/data/com.termux/files/usr/libexec/termux-am/am.apk"

PLAYERS = [
    {"name": "Android chooser (pick any player)", "pkg": None},
    {"name": "VLC", "pkg": "org.videolan.vlc"},
    {"name": "MX Player", "pkg": "com.mxtech.videoplayer.ad"},
    {"name": "MX Player Pro", "pkg": "com.mxtech.videoplayer.pro"},
    {"name": "mpv", "pkg": "is.xyz.mpv"},
    {"name": "Just Player", "pkg": "com.brouken.player"},
    {"name": "Samsung Video", "pkg": "com.samsung.android.video"},
    {"name": "Kodi", "pkg": "org.xbmc.kodi"},
]

DEFAULTS = {
    "player": PLAYERS[0]["name"],
    "download_dir": "",
    "aria2_port": 6899,
    "providers": ["netmirror", "movierulz", "moviesflix", "yts"],
}


def _load():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def load_config():
    cfg = dict(DEFAULTS)
    cfg.update(_load())
    return cfg


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    except Exception:
        pass


def download_dir(cfg=None):
    """Return the first existing download folder, creating it if needed."""
    cfg = cfg or load_config()
    custom = (cfg.get("download_dir") or "").strip()
    candidates = ([custom] if custom else []) + list(DOWNLOAD_DIRS)
    for path in candidates:
        if not path:
            continue
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except Exception:
            continue
    return os.path.expanduser("~")


def player_by_name(name):
    for player in PLAYERS:
        if player["name"] == name:
            return player
    return PLAYERS[0]


def on_android():
    return os.path.exists("/system/bin/app_process") and os.path.isdir(
        "/data/data/com.termux"
    )
