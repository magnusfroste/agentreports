"""Bring an existing folder of report files into the store, keeping their addresses.

  python server.py import <folder> --by <name> [--details details.json] [--skip index.html ...] [--note text]

Every <name>.html becomes the report <name> (so /<name>.html keeps working), and <name>.md becomes a
markdown report unless an .html of the same name exists. The title comes from <title>, the description
from <meta name="description">, the time from the file. details.json can set title, description,
category and tags per slug: {"slug": {"title": "...", "category": "..."}}. Running it again adds
nothing for files whose content is already the current version.
"""
import argparse
import html
import json
import os
import re
from datetime import datetime, timezone


def _title(text, fallback):
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I) or re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S | re.I)
    t = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""
    return " ".join(t.split()) or fallback


def _description(text):
    m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']*)', text, re.I)
    return " ".join(html.unescape(m.group(1)).split()) if m else None


def main(argv, store):
    p = argparse.ArgumentParser(prog="server.py import")
    p.add_argument("folder")
    p.add_argument("--by", required=True, help="who the versions are attributed to")
    p.add_argument("--details", help="JSON file with title/description/category/tags per slug")
    p.add_argument("--skip", nargs="*", default=["index.html"], help="file names to leave out")
    p.add_argument("--note", default="imported", help="the note on each imported version")
    a = p.parse_args(argv)
    extra = json.load(open(a.details, encoding="utf-8")) if a.details else {}
    names = sorted(os.listdir(a.folder))
    for name in names:
        base, ext = os.path.splitext(name)
        if name in a.skip or ext not in (".html", ".md") or name.startswith("."):
            continue
        if ext == ".md" and base + ".html" in names:
            print(f"skip {name}: {base}.html is the same report")
            continue
        path = os.path.join(a.folder, name)
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        fmt = "markdown" if ext == ".md" else "html"
        title = _title(text, base) if fmt == "html" else (re.search(r"^#\s+(.+)$", text, re.M) or [None, base])[1]
        d = {"title": title, "description": _description(text) if fmt == "html" else None, **extra.get(base, {})}
        at = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat(timespec="seconds")
        try:
            meta, changed = store.publish(base, text, a.by, fmt=fmt, note=a.note, at=at,
                                          **{k: v for k, v in d.items() if v is not None})
        except ValueError as e:
            print(f"skip {name}: {e}")
            continue
        print(f"{'new v' + str(meta['version']) if changed else 'unchanged'}  {base}  [{meta.get('category') or '-'}]  {meta['title']}")
