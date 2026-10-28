"""Reports on disk. No database: a report is a folder, and every publish adds a version.

DATA_DIR/reports/<slug>/
  meta.json        title, description, category, tags, current version, who and when, archived, locked (details a person set in the browser)
  v0001.html       the content of version 1 (.md for markdown)
  v0001.json       who published it, when, the note, size and checksum

Nothing is ever overwritten or deleted here. An agent that publishes the same slug again adds a
version; restoring an old version adds a new one with the old content. Archiving only hides a
report from the start page, and only a person can do it (see server.py).
"""
import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
# Paths the server uses itself, so they can never be a report.
# server.py adds the first part of FILES_ROUTE.
RESERVED = {"index", "api", "mcp", "login", "logout", "health", "r", "static", "files",
            "favicon", "apple-touch-icon", "robots", "assets"}
FORMATS = {"html": ".html", "markdown": ".md"}
DETAILS = ("title", "description", "category", "tags")
# What a person can set in the browser; once set there, an agent's new version keeps it (see locked in meta.json).
LOCKABLE = ("title", "description", "category")
ATTACHMENT = re.compile(r"^[a-z0-9][a-z0-9._-]{0,60}\.(csv|json)$")
MAX_ATTACHMENT, MAX_ATTACHMENTS = 5 * 1024 * 1024, 10
MAX_BYTES = int(os.environ.get("MAX_REPORT_BYTES", str(10 * 1024 * 1024)))


class Conflict(ValueError):
    """The report changed after the caller last read it."""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text):
    s = (text or "").lower().translate(str.maketrans("åäöéèëüæøá", "aaoeeeuaoa"))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:80].strip("-") or "report"


def clean_details(title=None, description=None, category=None, tags=None):
    out = {}
    if title is not None:
        title = " ".join(str(title).split())[:200]
        if not title:
            raise ValueError("title must not be empty")
        out["title"] = title
    if description is not None:
        out["description"] = " ".join(str(description).split())[:600]
    if category is not None:
        out["category"] = " ".join(str(category).split())[:60]
    if tags is not None:
        if isinstance(tags, str):
            tags = tags.split(",")
        out["tags"] = sorted({" ".join(str(t).split())[:40] for t in tags if str(t).strip()})[:12]
    return out


class Store:
    def __init__(self, data_dir):
        self.root = os.path.join(data_dir, "reports")
        os.makedirs(self.root, exist_ok=True)
        self.lock = threading.RLock()

    # --- files ------------------------------------------------------------------------------

    def _dir(self, slug):
        return os.path.join(self.root, slug)

    @staticmethod
    def _write(path, data):
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _write_json(self, path, obj):
        self._write(path, json.dumps(obj, ensure_ascii=False, indent=1).encode())

    @staticmethod
    def _read_json(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    # --- reading ----------------------------------------------------------------------------

    def get(self, slug):
        if not SLUG.match(slug or ""):
            return None
        return self._read_json(os.path.join(self._dir(slug), "meta.json"))

    def all(self):
        out = []
        for slug in os.listdir(self.root):
            meta = self.get(slug)
            if meta:
                out.append(meta)
        return sorted(out, key=lambda m: m.get("updated", ""), reverse=True)

    def versions(self, slug):
        d = self._dir(slug)
        if not self.get(slug):
            return []
        vs = [self._read_json(os.path.join(d, n)) for n in sorted(os.listdir(d)) if re.match(r"^v\d{4,}\.json$", n)]
        return sorted((v for v in vs if v), key=lambda v: v["version"], reverse=True)

    def content(self, slug, version=None):
        """(meta, bytes, version info) or None."""
        meta = self.get(slug)
        if not meta:
            return None
        n = int(version or meta["version"])
        info = self._read_json(os.path.join(self._dir(slug), f"v{n:04d}.json"))
        if not info:
            return None
        with open(os.path.join(self._dir(slug), f"v{n:04d}{FORMATS[info['format']]}"), "rb") as f:
            return meta, f.read(), info

    def attachments(self, slug, version=None):
        """{name: bytes} of the data files that belong to a version (data for tables and charts)."""
        meta = self.get(slug)
        if not meta:
            return {}
        n = int(version or meta["version"])
        d = os.path.join(self._dir(slug), f"v{n:04d}.data")
        if not os.path.isdir(d):
            return {}
        out = {}
        for name in sorted(os.listdir(d)):
            if ATTACHMENT.match(name):
                with open(os.path.join(d, name), "rb") as f:
                    out[name] = f.read()
        return out

    # --- writing ----------------------------------------------------------------------------

    def publish(self, slug, content, by, fmt="html", note=None, expected_version=None, at=None, requested_by=None,
                draft=None, attachments=None, **details):
        """Add a version. Returns (meta, changed): publishing identical content changes only the details.

        by is the agent key's name (proven by the key); requested_by is who the agent says asked for it."""
        if fmt not in FORMATS:
            raise ValueError(f"format must be one of: {', '.join(FORMATS)}")
        if not SLUG.match(slug or "") or slug in RESERVED:
            raise ValueError("slug: lowercase letters, digits and hyphens, at most 80, and not a reserved word "
                             f"({', '.join(sorted(RESERVED))})")
        data = content.encode() if isinstance(content, str) else bytes(content or b"")
        if not data.strip():
            raise ValueError("content must not be empty")
        if len(data) > MAX_BYTES:
            raise ValueError(f"content is {len(data)} bytes; the limit is {MAX_BYTES}")
        if fmt == "html" and not data.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<"):
            raise ValueError("content is not an HTML page: it must start with <!doctype html> or a tag. It looks like "
                             "the script that builds the page was sent instead of the page it writes; run the script "
                             "and publish its output (or use format=markdown for markdown)")
        details = clean_details(**{k: v for k, v in details.items() if k in DETAILS})
        attachments = attachments or {}
        for name, blob in attachments.items():
            if not ATTACHMENT.match(name):
                raise ValueError(f"attachment {name!r}: a name like invoices.csv or data.json (lowercase, digits, . _ -)")
            if blob is not None and len(blob) > MAX_ATTACHMENT:
                raise ValueError(f"attachment {name}: {len(blob)} bytes, the limit is {MAX_ATTACHMENT}")
        sha = hashlib.sha256(data).hexdigest()
        stamp = at or now()
        requested_by = " ".join(str(requested_by or "").split())[:80] or None
        with self.lock:
            meta = self.get(slug)
            if meta and expected_version is not None and int(expected_version) != meta["version"]:
                raise Conflict(f"'{slug}' is at version {meta['version']}, not {expected_version}: someone published "
                               "in between. Read it again (read_report) and publish on top of that.")
            if draft and meta and not meta.get("draft"):
                raise ValueError(f"'{slug}' is already published; a draft is only for a new report. Check content "
                                 "with check_report before publishing over it.")
            if not meta:
                if "title" not in details:
                    raise ValueError("title is required for a new report")
                meta = {"slug": slug, "title": details["title"], "description": "", "category": "", "tags": [],
                        "format": fmt, "version": 0, "created": stamp, "created_by": by,
                        "created_for": requested_by, "archived": False, "draft": bool(draft)}
                os.makedirs(self._dir(slug), exist_ok=True)
            current = self.content(slug) if meta["version"] else None
            # The data files carry over from the version before unless they are given again (None removes one).
            files = self.attachments(slug) if meta["version"] else {}
            for name, blob in attachments.items():
                if blob is None:
                    files.pop(name, None)
                else:
                    files[name] = blob if isinstance(blob, bytes) else str(blob).encode()
            if len(files) > MAX_ATTACHMENTS:
                raise ValueError(f"at most {MAX_ATTACHMENTS} data files per report")
            data_sha = hashlib.sha256(b"".join(n.encode() + b"\0" + hashlib.sha256(b).digest()
                                               for n, b in sorted(files.items()))).hexdigest() if files else None
            changed = (not current or current[2].get("sha256") != sha or current[2].get("format") != fmt
                       or current[2].get("data_sha256") != data_sha)
            # Details a person set in the browser stay as they are; the caller tells the agent (meta["kept"]).
            locked = meta.get("locked") or {}
            kept = {k: meta[k] for k in list(details) if k in locked and details[k] != meta.get(k)}
            for k in kept:
                details.pop(k)
            meta.update(details)
            if draft is False and meta.get("draft"):
                meta.update(draft=False, published=stamp, published_by=by)
            if changed:
                n = meta["version"] + 1
                self._write(os.path.join(self._dir(slug), f"v{n:04d}{FORMATS[fmt]}"), data)
                if files:
                    ddir = os.path.join(self._dir(slug), f"v{n:04d}.data")
                    os.makedirs(ddir, exist_ok=True)
                    for name, blob in files.items():
                        self._write(os.path.join(ddir, name), blob)
                self._write_json(os.path.join(self._dir(slug), f"v{n:04d}.json"), {
                    "version": n, "at": stamp, "by": by, "requested_by": requested_by,
                    "note": (note or "").strip()[:300] or None,
                    "format": fmt, "bytes": len(data), "sha256": sha, "data_sha256": data_sha,
                    "attachments": {n: len(b) for n, b in sorted(files.items())}})
                meta.update(version=n, format=fmt, bytes=len(data), updated=stamp, updated_by=by, updated_for=requested_by)
            elif details:
                meta.update(details_updated=stamp, details_updated_by=by)
            meta.setdefault("updated", stamp)
            meta.setdefault("updated_by", by)
            self._write_json(os.path.join(self._dir(slug), "meta.json"), meta)
            return ({**meta, "kept": kept} if kept else meta), changed

    def update_details(self, slug, by, person=False, **details):
        """Change title, description, category or tags. person=True (the browser) also locks what it sets,
        so an agent cannot change it back; an agent changing a locked field gets a ValueError."""
        details = clean_details(**{k: v for k, v in details.items() if k in DETAILS})
        if not details:
            raise ValueError("nothing to change: give title, description, category or tags")
        with self.lock:
            meta = self.get(slug)
            if not meta:
                raise KeyError(slug)
            locked = dict(meta.get("locked") or {})
            if person:
                stamp = now()
                for k in details:
                    if k in LOCKABLE:
                        locked[k] = {"by": by, "at": stamp}
            else:
                refused = [k for k in details if k in locked and details[k] != meta.get(k)]
                if refused:
                    raise ValueError(f"{', '.join(refused)} of '{slug}' was set by a person in the browser and is "
                                     f"kept: {'; '.join(repr(meta[k]) for k in refused)}. Ask them to change or "
                                     "unlock it there.")
            meta.update(details, locked=locked, details_updated=now(), details_updated_by=by)
            if not locked:
                meta.pop("locked")
            self._write_json(os.path.join(self._dir(slug), "meta.json"), meta)
            return meta

    def unlock(self, slug, by, fields=None):
        """Let agents set these details again (default: all of them)."""
        with self.lock:
            meta = self.get(slug)
            if not meta:
                raise KeyError(slug)
            locked = {k: v for k, v in (meta.get("locked") or {}).items() if fields and k not in fields}
            if locked:
                meta["locked"] = locked
            else:
                meta.pop("locked", None)
            meta.update(details_updated=now(), details_updated_by=by)
            self._write_json(os.path.join(self._dir(slug), "meta.json"), meta)
            return meta

    def set_archived(self, slug, archived, by):
        with self.lock:
            meta = self.get(slug)
            if not meta:
                raise KeyError(slug)
            meta.update(archived=bool(archived), archived_at=now() if archived else None,
                        archived_by=by if archived else None)
            self._write_json(os.path.join(self._dir(slug), "meta.json"), meta)
            return meta

    def restore(self, slug, version, by):
        with self.lock:
            found = self.content(slug, version)
            if not found:
                raise KeyError(f"{slug} v{version}")
            meta, data, info = found
            old = self.attachments(slug, version)
            gone = {n: None for n in self.attachments(slug) if n not in old}
            return self.publish(slug, data, by, fmt=info["format"], note=f"restored from v{info['version']}",
                                attachments={**old, **gone})[0]
