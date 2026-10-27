"""The part of the brand agents may change: a layer over BRAND_DIR, versioned, every change reversible.

DATA_DIR/brand/
  current        the active version number (0: no agent layer, only BRAND_DIR and the defaults)
  v0001/         brand.json with only what agents set, the files they gave, and meta.json
                 (who, when, note, what changed)

A change is a new version made from the current one; a restore is a new version too, copied from an
older one (or empty, for the base profile). Nothing is overwritten or deleted, as with reports.
Files are checked by content, SVGs that could run anything are refused, and files given as URLs are
fetched only over https from public addresses.
"""
import base64
import http.client
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import threading
import urllib.parse
from datetime import datetime, timezone

IMAGES = ("logo.svg", "logo.png", "logo-dark.svg", "logo-dark.png", "favicon.svg", "favicon.png",
          "favicon.ico", "apple-touch-icon.png")
FONT_FILE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,60}\.woff2?$")
HEX = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
FONT_NAME = re.compile(r"^[A-Za-z0-9 _-]{1,60}$")
COLOURS = ("accent", "accent_ink", "accent_text", "accent_dark", "background", "surface", "surface_2",
           "text", "muted", "faint", "line", "line_strong")
DARK = ("background", "surface", "surface_2", "text", "muted", "faint", "line", "line_strong")
MAX_IMAGE, MAX_FONT, MAX_TOTAL = 512 * 1024, 1024 * 1024, 4 * 1024 * 1024
SVG_DANGER = re.compile(r"<\s*script|\bon[a-z]+\s*=|javascript:|<\s*foreignObject|<!ENTITY|<\s*(iframe|embed|object)\b"
                        r"|href\s*=\s*[\"']?\s*(https?:|//|data:)|url\(\s*[\"']?\s*(https?:|//)|@import", re.I)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- checking what agents send --------------------------------------------------------------

def check_settings(settings):
    """Validate brand.json keys from an agent. None as a value means: drop that key from the layer."""
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object with brand.json keys")
    out = {}
    for key, value in settings.items():
        if value is None:
            out[key] = None
            continue
        if key in COLOURS:
            if not (isinstance(value, str) and HEX.match(value)):
                raise ValueError(f"{key}: a colour like #1b1620 or #1b1620a6")
        elif key == "dark":
            if not isinstance(value, dict) or any(k not in DARK for k in value):
                raise ValueError(f"dark: an object with {', '.join(DARK)}")
            for k, v in value.items():
                if v is not None and not (isinstance(v, str) and HEX.match(v)):
                    raise ValueError(f"dark.{k}: a colour like #121016")
        elif key in ("heading_font", "body_font"):
            if not (isinstance(value, str) and FONT_NAME.match(value)):
                raise ValueError(f"{key}: a font family name (letters, digits, spaces, - and _)")
        elif key == "heading_weight":
            if not (isinstance(value, int) and 100 <= value <= 900):
                raise ValueError("heading_weight: 100–900")
        elif key == "heading_scale":
            if not (isinstance(value, (int, float)) and 0.7 <= value <= 1.6):
                raise ValueError("heading_scale: 0.7–1.6")
        elif key == "radius":
            if not (isinstance(value, int) and 0 <= value <= 24):
                raise ValueError("radius: 0–24 (pixels)")
        elif key == "series":
            if not (isinstance(value, list) and 1 <= len(value) <= 6 and all(isinstance(c, str) and HEX.match(c) for c in value)):
                raise ValueError("series: one to six colours like #7a1fa2")
        elif key == "fonts":
            if not (isinstance(value, list) and len(value) <= 8):
                raise ValueError("fonts: at most eight {family, file, weight, style, unicode_range}")
            for f in value:
                if not (isinstance(f, dict) and FONT_NAME.match(str(f.get("family", ""))) and FONT_FILE.match(str(f.get("file", "")))):
                    raise ValueError("fonts: each needs family and file (a .woff2 given in files, or already there)")
                if f.get("weight") is not None and not re.fullmatch(r"[0-9]{3}( [0-9]{3})?", str(f["weight"])):
                    raise ValueError("fonts: weight like 400 or 400 700")
                if f.get("style") not in (None, "normal", "italic"):
                    raise ValueError("fonts: style normal or italic")
                if f.get("unicode_range") is not None and not re.fullmatch(r"[Uu0-9A-Fa-f+?, -]{1,600}", str(f["unicode_range"])):
                    raise ValueError("fonts: unicode_range like U+0000-00FF, U+0131")
        else:
            raise ValueError(f"{key}: not something agents can set. Allowed: {', '.join(COLOURS)}, dark, heading_font, "
                             "body_font, heading_weight, heading_scale, radius, series, fonts")
        out[key] = value
    return out


def check_file(name, data):
    """The bytes must be what the name says, within the size limits."""
    if name in IMAGES:
        if len(data) > MAX_IMAGE:
            raise ValueError(f"{name}: {len(data)} bytes, the limit is {MAX_IMAGE}")
        if name.endswith(".png") and not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"{name}: not a PNG")
        if name.endswith(".ico") and not (data.startswith(b"\x00\x00\x01\x00") or data.startswith(b"\x89PNG")):
            raise ValueError(f"{name}: not an ICO")
        if name.endswith(".svg"):
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError(f"{name}: not a UTF-8 SVG")
            if "<svg" not in text:
                raise ValueError(f"{name}: not an SVG")
            if SVG_DANGER.search(text):
                raise ValueError(f"{name}: scripts, event handlers, external links and embedded documents are not "
                                 "allowed in an SVG; give a plain drawing or a PNG")
        return
    if FONT_FILE.match(name):
        if len(data) > MAX_FONT:
            raise ValueError(f"{name}: {len(data)} bytes, the limit is {MAX_FONT}")
        if not data.startswith(b"wOF2" if name.endswith(".woff2") else b"wOFF"):
            raise ValueError(f"{name}: not a {'WOFF2' if name.endswith('2') else 'WOFF'} font")
        return
    raise ValueError(f"{name}: allowed files are {', '.join(IMAGES)} and fonts named like body.woff2")


# --- fetching files an agent points at ------------------------------------------------------

class _Pinned(http.client.HTTPSConnection):
    """Connects to the address that was checked, not to whatever the name resolves to a moment later."""

    def __init__(self, host, ip, port, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def fetch(url, cap, hops=3):
    """GET over https from a public address only, at most cap bytes, following a few redirects."""
    for _ in range(hops + 1):
        u = urllib.parse.urlsplit(url)
        if u.scheme != "https" or not u.hostname:
            raise ValueError(f"{url}: only https:// addresses")
        port = u.port or 443
        try:
            infos = socket.getaddrinfo(u.hostname, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            raise ValueError(f"{url}: the name does not resolve")
        ips = {info[4][0] for info in infos}
        if not ips or any(not ipaddress.ip_address(ip.split("%")[0]).is_global for ip in ips):
            raise ValueError(f"{url}: not a public address")
        conn = _Pinned(u.hostname, sorted(ips)[0], port, timeout=10)
        try:
            conn.request("GET", (u.path or "/") + (f"?{u.query}" if u.query else ""),
                         headers={"User-Agent": "AgentReports brand fetch", "Accept": "*/*"})
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308) and r.getheader("Location"):
                url = urllib.parse.urljoin(url, r.getheader("Location"))
                continue
            if r.status != 200:
                raise ValueError(f"{url}: HTTP {r.status}")
            data = r.read(cap + 1)
        except (OSError, http.client.HTTPException) as e:
            raise ValueError(f"{url}: {e}")
        finally:
            conn.close()
        if len(data) > cap:
            raise ValueError(f"{url}: larger than {cap} bytes")
        return data
    raise ValueError(f"{url}: too many redirects")


# --- the versioned layer --------------------------------------------------------------------

class BrandStore:
    def __init__(self, data_dir):
        self.root = os.path.join(data_dir, "brand")
        os.makedirs(self.root, exist_ok=True)
        self.lock = threading.Lock()

    def _vdir(self, n):
        return os.path.join(self.root, f"v{n:04d}")

    def current(self):
        try:
            with open(os.path.join(self.root, "current")) as f:
                n = int(f.read().strip() or 0)
        except (OSError, ValueError):
            return 0
        return n if n and os.path.isdir(self._vdir(n)) else 0

    def layer_dir(self):
        n = self.current()
        return self._vdir(n) if n else None

    def settings(self, n=None):
        n = self.current() if n is None else n
        if not n:
            return {}
        try:
            with open(os.path.join(self._vdir(n), "brand.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def files(self, n=None):
        n = self.current() if n is None else n
        if not n:
            return []
        return sorted(x for x in os.listdir(self._vdir(n)) if x in IMAGES or FONT_FILE.match(x))

    def history(self, limit=50):
        out = []
        for name in sorted(os.listdir(self.root), reverse=True):
            if re.fullmatch(r"v\d{4,}", name):
                try:
                    with open(os.path.join(self.root, name, "meta.json"), encoding="utf-8") as f:
                        out.append(json.load(f))
                except (OSError, ValueError):
                    continue
            if len(out) >= limit:
                break
        return out

    def _next(self):
        ns = [int(n[1:]) for n in os.listdir(self.root) if re.fullmatch(r"v\d{4,}", n)]
        return max(ns, default=0) + 1

    def _commit(self, n, meta):
        with open(os.path.join(self._vdir(n), "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        tmp = os.path.join(self.root, "current.part")
        with open(tmp, "w") as f:
            f.write(str(n))
        os.replace(tmp, os.path.join(self.root, "current"))

    def update(self, by, settings=None, files=None, note=None, base_dirs=()):
        """Apply a change on top of the current layer as a new version. files: {name: bytes or None}."""
        settings = check_settings(settings or {})
        files = files or {}
        for name, data in files.items():
            if data is not None:
                check_file(name, data)
        if sum(len(d) for d in files.values() if d) > MAX_TOTAL:
            raise ValueError(f"more than {MAX_TOTAL} bytes of files in one change")
        if not settings and not files:
            raise ValueError("nothing to change: give settings and/or files")
        with self.lock:
            cur = self.current()
            cfg = self.settings(cur)
            for key, value in settings.items():
                if value is None:
                    cfg.pop(key, None)
                elif key == "dark":
                    merged = {**cfg.get("dark", {}), **value}
                    cfg["dark"] = {k: v for k, v in merged.items() if v is not None}
                else:
                    cfg[key] = value
            have = set(self.files(cur)) | {n for n, d in files.items() if d is not None}
            have -= {n for n, d in files.items() if d is None}
            for font in cfg.get("fonts", []):
                if font["file"] not in have and not any(os.path.isfile(os.path.join(d, font["file"])) for d in base_dirs if d):
                    raise ValueError(f"fonts: {font['file']} is neither given in files nor already there")
            n = self._next()
            target = self._vdir(n)
            os.makedirs(target)
            for name in self.files(cur):
                if name not in files:
                    shutil.copy2(os.path.join(self._vdir(cur), name), os.path.join(target, name))
            for name, data in files.items():
                if data is not None:
                    with open(os.path.join(target, name), "wb") as f:
                        f.write(data)
            with open(os.path.join(target, "brand.json"), "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=1)
            meta = {"version": n, "at": now(), "by": by, "note": (note or "").strip()[:300] or None,
                    "settings": sorted(settings), "files": sorted(files)}
            self._commit(n, meta)
            return meta

    def restore(self, version, by):
        """A new version with the content of an older one; 0 is the base profile (no agent layer)."""
        version = int(version)
        with self.lock:
            if version and not os.path.isdir(self._vdir(version)):
                raise KeyError(version)
            n = self._next()
            target = self._vdir(n)
            if version:
                shutil.copytree(self._vdir(version), target)
                os.remove(os.path.join(target, "meta.json"))
            else:
                os.makedirs(target)
                with open(os.path.join(target, "brand.json"), "w") as f:
                    f.write("{}")
            meta = {"version": n, "at": now(), "by": by, "settings": [], "files": [],
                    "note": f"restored from v{version}" if version else "back to the base profile",
                    "restored_from": version}
            self._commit(n, meta)
            return meta


def decode_file(item, fetch_fn=fetch):
    """One entry of update_brand's files: {name, url} or {name, base64} or {name, remove: true}."""
    if not isinstance(item, dict) or not isinstance(item.get("name"), str):
        raise ValueError("files: each entry needs a name")
    name = item["name"]
    if item.get("remove"):
        return name, None
    cap = MAX_FONT if FONT_FILE.match(name) else MAX_IMAGE
    if item.get("url"):
        return name, fetch_fn(str(item["url"]), cap)
    if item.get("base64"):
        try:
            return name, base64.b64decode(item["base64"], validate=True)
        except ValueError:
            raise ValueError(f"{name}: base64 is not valid")
    raise ValueError(f"{name}: give url, base64 or remove")
