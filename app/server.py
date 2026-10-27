#!/usr/bin/env python3
"""AgentReports: agents publish reports over MCP, people read them behind a password.

Agents can add and change reports, never remove or hide them, and never touch the start page: it
is generated from each report's title, description and category. Every publish is a new version;
a person can restore an old one or archive a report from the browser.

Environment:
  REPORTS_PASSWORD      the password people sign in with (20+ characters)
  MCP_KEYS              name:key pairs, comma separated, one per agent installation (keys 32+ characters)
  AGENT_NAMES           optional display names: name=Shown name,name2=Other (default: the key's name)
  SITE_TITLE            heading of the start page (default "Reports"); SITE_SUBTITLE below it
  REPORTS_LANG          en or sv (default en)
  PUBLIC_URL            e.g. https://reports.example.com, for the links agents get back
  FILES_DIR, FILES_ROUTE   optional read-only folder served under FILES_ROUTE (default /files) to
                        people who are signed in, e.g. the source documents a report links to
  TRUSTED_PROXY_HEADER  e.g. CF-Connecting-IP or X-Forwarded-For, when behind a proxy that sets it
                        (for the lockout; from a list, the last address is used)
  REPORT_STYLE          on (default) or off: offer agents the report kit (/static/report.css, the tool
                        report_style and a line in the MCP instructions) so reports look like the site
  AGENT_BRANDING        on (default) or off: agents may change logo, fonts and colours over MCP
                        (get_brand, update_brand, restore_brand), as a versioned layer over BRAND_DIR
                        that people can roll back at /brand
  BRAND_DIR             optional folder: logo.svg/.png, logo-dark.svg/.png, favicon.svg/.png/.ico,
                        apple-touch-icon.png, font files and brand.json (colours, fonts; see README);
                        whatever is there replaces the default, the rest stays
  DATA_DIR / PORT       default /data, 8000

Routes: / | /<slug>.html | /r/<slug> | /r/<slug>/v/<n> | /api/reports... | POST /mcp | /login | /health
"""
import hashlib
import hmac
import html
import http.cookies
import json
import mimetypes
import os
import re
import shutil
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import brandstore
from store import FORMATS, RESERVED, SLUG, Conflict, Store, slugify

VERSION = "0.2.1"
UI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
DATA = os.environ.get("DATA_DIR", "/data")
PASSWORD = os.environ.get("REPORTS_PASSWORD", "")
TITLE = os.environ.get("SITE_TITLE", "Reports")
SUBTITLE = os.environ.get("SITE_SUBTITLE", "")
LANG = os.environ.get("REPORTS_LANG", "en") if os.environ.get("REPORTS_LANG", "en") in ("en", "sv") else "en"
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
FILES_DIR = os.environ.get("FILES_DIR", "")
FILES_ROUTE = "/" + os.environ.get("FILES_ROUTE", "/files").strip("/")
PROXY_HEADER = os.environ.get("TRUSTED_PROXY_HEADER", "")
BRAND_DIR = os.environ.get("BRAND_DIR", "")
REPORT_STYLE = os.environ.get("REPORT_STYLE", "on").strip().lower() not in ("off", "0", "false", "no")
AGENT_BRANDING = os.environ.get("AGENT_BRANDING", "on").strip().lower() not in ("off", "0", "false", "no")
SESSION_DAYS = 30
LOCKOUT_FAILS, LOCKOUT_SECONDS = 10, 900
COOKIE = "ar_session"
REPORT_CSP = ("sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox allow-forms allow-modals "
              "allow-downloads allow-top-navigation-by-user-activation; frame-ancestors 'self'")
PAGE_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
MARKED = "https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"

RESERVED.update({"brand"})
RESERVED.add(FILES_ROUTE.strip("/").split("/")[0])
store = Store(DATA)
brands = brandstore.BrandStore(DATA)


def log(msg):
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z {msg}", flush=True)


# --- words ----------------------------------------------------------------------------------

WORDS = {
    "en": {"search": "Search reports", "sort_updated": "Recently updated", "sort_created": "Newest",
           "sort_title": "Title A–Z", "sort_category": "By category", "show_archived": "Archive",
           "all": "All", "logout": "Sign out", "empty": "No reports yet. Agents publish them with publish_report.",
           "empty_filtered": "Nothing matches.", "new": "New", "updated": "Updated", "archived": "Archived",
           "archive": "Archive", "unarchive": "Restore to start page",
           "archive_confirm": "Hide this report from the start page? It stays available, with all versions.",
           "archived_toast": "Archived", "undo": "Undo", "copy_link": "Copy link", "copied": "Link copied",
           "details": "Versions & details", "open": "Open", "reports": "reports", "report": "report",
           "categories": "categories", "category": "category", "last_updated": "last updated", "by": "by",
           "version": "Version", "versions": "Versions", "created": "Created", "restore": "Restore",
           "restore_confirm": "Publish this version again as the newest one? Nothing is lost.",
           "restored": "Restored", "current": "current", "view": "View", "note": "Note", "size": "Size",
           "back": "All reports", "uncategorized": "Other", "sign_in_title": "Sign in", "password": "Password",
           "sign_in": "Sign in", "wrong_password": "Wrong password.",
           "locked_out": "Too many attempts. Try again in a quarter of an hour.", "format": "Format",
           "link": "Link", "when": "When", "who": "Who", "error": "Something went wrong", "menu": "More",
           "not_found": "Not found", "not_found_text": "There is no report at this address.",
           "details_changed": "Details changed", "view_mode": "View", "view_cards": "Cards", "view_list": "List",
           "theme": "Theme", "theme_system": "System", "theme_light": "Light", "theme_dark": "Dark",
           "brand": "Look", "brand_title": "The site's look", "brand_lead": "Logo, fonts and colours. Agents can change them over MCP; every change is a version you can go back to.",
           "brand_base": "Back to the base look", "brand_base_confirm": "Remove what agents changed and go back to the base look? It stays in the history.",
           "brand_restore_confirm": "Make this version the current look? Nothing is lost.", "brand_none": "Agents have not changed the look.",
           "brand_changed": "Changed", "brand_current_base": "the base look", "brand_off": "Agents may not change the look on this site (AGENT_BRANDING=off).",
           "overview": "Overview", "pinned": "Pinned", "pin": "Pin", "unpin": "Unpin", "open_tab": "Open in a new tab",
           "panel": "Panel", "menu_open": "Open the menu", "not_found_report": "That report does not exist (any more).",
           "empty_archive": "Nothing archived. Archive a report from its menu (⋯) to hide it from the start page."},
    "sv": {"search": "Sök rapporter", "sort_updated": "Senast uppdaterad", "sort_created": "Nyast",
           "sort_title": "Titel A–Ö", "sort_category": "Per kategori", "show_archived": "Arkiv",
           "all": "Alla", "logout": "Logga ut", "empty": "Inga rapporter än. Agenterna publicerar dem med publish_report.",
           "empty_filtered": "Inget matchar.", "new": "Ny", "updated": "Uppdaterad", "archived": "Arkiverad",
           "archive": "Arkivera", "unarchive": "Tillbaka till startsidan",
           "archive_confirm": "Dölja rapporten från startsidan? Den finns kvar, med alla versioner.",
           "archived_toast": "Arkiverad", "undo": "Ångra", "copy_link": "Kopiera länk", "copied": "Länken kopierad",
           "details": "Versioner och detaljer", "open": "Öppna", "reports": "rapporter", "report": "rapport",
           "categories": "kategorier", "category": "kategori", "last_updated": "senast uppdaterad", "by": "av",
           "version": "Version", "versions": "Versioner", "created": "Skapad", "restore": "Återställ",
           "restore_confirm": "Publicera den här versionen igen som den senaste? Inget går förlorat.",
           "restored": "Återställd", "current": "aktuell", "view": "Visa", "note": "Notering", "size": "Storlek",
           "back": "Alla rapporter", "uncategorized": "Övrigt", "sign_in_title": "Logga in", "password": "Lösenord",
           "sign_in": "Logga in", "wrong_password": "Fel lösenord.",
           "locked_out": "För många försök. Försök igen om en kvart.", "format": "Format",
           "link": "Länk", "when": "När", "who": "Vem", "error": "Något gick fel", "menu": "Mer",
           "not_found": "Hittades inte", "not_found_text": "Det finns ingen rapport på den här adressen.",
           "details_changed": "Detaljer ändrade", "view_mode": "Visning", "view_cards": "Kort", "view_list": "Lista",
           "theme": "Tema", "theme_system": "System", "theme_light": "Ljust", "theme_dark": "Mörkt",
           "brand": "Profil", "brand_title": "Sidans profil", "brand_lead": "Logga, typsnitt och färger. Agenter kan ändra dem via MCP; varje ändring är en version du kan gå tillbaka till.",
           "brand_base": "Tillbaka till grundprofilen", "brand_base_confirm": "Ta bort det agenterna ändrat och gå tillbaka till grundprofilen? Det finns kvar i historiken.",
           "brand_restore_confirm": "Gör den här versionen till den aktuella profilen? Inget går förlorat.", "brand_none": "Agenterna har inte ändrat profilen.",
           "brand_changed": "Ändrat", "brand_current_base": "grundprofilen", "brand_off": "Agenter får inte ändra profilen på den här sidan (AGENT_BRANDING=off).",
           "overview": "Översikt", "pinned": "Fästa", "pin": "Fäst", "unpin": "Lossa", "open_tab": "Öppna i ny flik",
           "panel": "Panel", "menu_open": "Öppna menyn", "not_found_report": "Den rapporten finns inte (längre).",
           "empty_archive": "Inget arkiverat. Arkivera en rapport från dess meny (⋯) för att dölja den från startsidan."},
}
T = WORDS[LANG]


# --- people: password, session cookie, lockout ----------------------------------------------

SESSION_KEY = hmac.new(PASSWORD.encode(), b"agentreports-session-v1", hashlib.sha256).digest()
_fails, _fails_lock = {}, threading.Lock()


def make_session():
    exp = str(int(time.time()) + SESSION_DAYS * 86400)
    return f"{exp}.{hmac.new(SESSION_KEY, exp.encode(), hashlib.sha256).hexdigest()}"


def session_ok(value):
    exp, _, mac = (value or "").partition(".")
    good = hmac.new(SESSION_KEY, exp.encode(), hashlib.sha256).hexdigest()
    return bool(mac) and hmac.compare_digest(mac, good) and exp.isdigit() and int(exp) > time.time()


def password_ok(given):
    return hmac.compare_digest(hashlib.sha256(given.encode()).digest(), hashlib.sha256(PASSWORD.encode()).digest())


def locked(ip):
    with _fails_lock:
        recent = [t for t in _fails.get(ip, []) if time.time() - t < LOCKOUT_SECONDS]
        _fails[ip] = recent
        return len(recent) >= LOCKOUT_FAILS


def failed(ip):
    with _fails_lock:
        _fails.setdefault(ip, []).append(time.time())


# --- agents: keys -----------------------------------------------------------------------------

def load_keys():
    keys = {}
    for pair in os.environ.get("MCP_KEYS", "").split(","):
        name, _, key = pair.strip().partition(":")
        if name and len(key) >= 32:
            keys[key] = name
        elif name:
            log(f"key for {name!r} ignored: shorter than 32 characters")
    return keys


KEYS = load_keys()


def load_names():
    names = {}
    for pair in os.environ.get("AGENT_NAMES", "").split(","):
        key, _, shown = pair.partition("=")
        if key.strip() and shown.strip():
            names[key.strip()] = " ".join(shown.split())[:60]
    return names


NAMES = load_names()


def shown(name):
    return NAMES.get(name, name) if name else ""


def who_text(by, requested_by=None):
    """'Ana Lind via Hermes' when an agent says who asked; the agent's own name is always there."""
    agent_name = shown(by)
    return f"{requested_by} via {agent_name}" if requested_by and requested_by != agent_name else agent_name


def agent(header):
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    found = None
    for key, name in KEYS.items():
        if token and hmac.compare_digest(token, key):
            found = name
    return found


# --- reports as the outside sees them -------------------------------------------------------

def url_of(slug, version=None):
    """The address to share: the report inside the site (panel on the left); /<slug>.html is the bare page."""
    path = f"/r/{slug}/v/{version}" if version else f"/r/{slug}"
    return PUBLIC_URL + path


def public(meta):
    return {"slug": meta["slug"], "title": meta["title"], "description": meta.get("description", ""),
            "category": meta.get("category", ""), "tags": meta.get("tags", []), "format": meta.get("format"),
            "version": meta["version"], "created": meta.get("created"), "created_by": meta.get("created_by"),
            "created_for": meta.get("created_for"), "updated": meta.get("updated"), "updated_by": meta.get("updated_by"),
            "updated_for": meta.get("updated_for"),
            "created_by_text": who_text(meta.get("created_by"), meta.get("created_for")),
            "updated_by_text": who_text(meta.get("updated_by"), meta.get("updated_for")),
            "archived": bool(meta.get("archived")), "url": url_of(meta["slug"])}


# --- MCP tools ------------------------------------------------------------------------------

def t_publish(a, who):
    title = a.get("title")
    slug = a.get("slug") or slugify(title or "")
    existed = store.get(slug)
    meta, changed = store.publish(slug, a.get("content") or "", who, fmt=a.get("format") or "html",
                                  note=a.get("note"), expected_version=a.get("expected_version"),
                                  requested_by=a.get("requested_by"),
                                  title=title, description=a.get("description"), category=a.get("category"),
                                  tags=a.get("tags"))
    log(f"{who}: published {slug} v{meta['version']}{'' if changed else ' (same content)'}")
    return {**public(meta), "new_report": not existed, "new_version": changed,
            "note": "The start page lists it automatically. Earlier versions are kept." if changed else
                    "Content identical to the current version: no new version, details updated."}


def t_details(a, who):
    try:
        meta = store.update_details(a.get("slug"), who, title=a.get("title"), description=a.get("description"),
                                    category=a.get("category"), tags=a.get("tags"))
    except KeyError:
        raise ValueError(f"No report '{a.get('slug')}'. See list_reports.")
    return public(meta)


def t_list(a):
    q = (a.get("query") or "").lower()
    rows = [m for m in store.all()
            if (a.get("include_archived") or not m.get("archived"))
            and (not a.get("category") or (m.get("category") or "").lower() == a["category"].lower())
            and (not q or q in " ".join([m["slug"], m["title"], m.get("description", ""), m.get("category", "")]
                                        + m.get("tags", [])).lower())]
    cats = {}
    for m in store.all():
        if not m.get("archived"):
            cats[m.get("category") or ""] = cats.get(m.get("category") or "", 0) + 1
    return {"count": len(rows), "reports": [public(m) for m in rows],
            "categories": dict(sorted(cats.items())),
            "note": "Reuse an existing category when one fits, so the start page stays tidy."}


def t_read(a):
    found = store.content(a.get("slug") or "", a.get("version"))
    if not found:
        raise ValueError(f"No report '{a.get('slug')}'" + (f" version {a['version']}" if a.get("version") else ""))
    meta, data, info = found
    return {**public(meta), "content_version": info["version"], "content_format": info["format"],
            "published_by": info["by"], "requested_by": info.get("requested_by"), "published": info["at"], "content": data.decode("utf-8", "replace"),
            "note": "Pass expected_version=version to publish_report to make sure nobody published in between."}


def t_versions(a):
    meta = store.get(a.get("slug") or "")
    if not meta:
        raise ValueError(f"No report '{a.get('slug')}'.")
    return {"slug": meta["slug"], "current": meta["version"],
            "versions": [{**v, "url": url_of(meta["slug"], v["version"])} for v in store.versions(meta["slug"])]}


REPORT_SKELETON = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Title of the report</title>
<link rel="stylesheet" href="/static/report.css">
<link rel="icon" href="/favicon.ico">
</head>
<body>
<main class="r-page">
  <a class="r-back" href="/">← {back}</a>
  <p class="r-eyebrow">Category</p>
  <h1>Title of the report</h1>
  <p class="r-lead">What the reader learns here, in one or two sentences.</p>
  <p class="r-meta"><span>Data up to 2026-10-26</span><span>Source: …</span></p>
  <nav class="r-nav"><a href="x-overview.html" aria-current="page">Overview</a><a href="x-details.html">Details</a></nav>

  <div class="r-kpis">
    <div class="r-kpi"><div class="r-kpi-value">3 752 294 kr</div><div class="r-kpi-label">Total cost</div><div class="r-kpi-note r-up">+12 % vs last month</div></div>
  </div>

  <h2>Per month</h2>
  <div class="r-note warn">Something the reader should check.</div>
  <div class="r-table-wrap"><table class="r-table">
    <thead><tr><th>Month</th><th class="num">Amount</th><th>Share</th></tr></thead>
    <tbody><tr><td>2026-10</td><td class="num">412 000</td><td><span class="r-bar c1"><span style="width:42%"></span></span></td></tr></tbody>
    <tfoot><tr><td>Total</td><td class="num">412 000</td><td></td></tr></tfoot>
  </table></div>

  <footer class="r-sources"><p>Built from …, on 2026-10-26. Not readable: …</p></footer>
</main>
</body>
</html>"""

STYLE_CLASSES = {
    "r-page": "the page container (wrap everything in <main class=\"r-page\">)",
    "r-back": "link back to the start page: <a class=\"r-back\" href=\"/\">",
    "r-eyebrow, h1, r-lead, r-meta": "header: category line, title, one-sentence summary, date and sources",
    "r-nav": "links between the pages of one report set; mark the current one with aria-current=\"page\"",
    "r-kpis > r-kpi (r-kpi-value, r-kpi-label, r-kpi-note)": "key figures; add r-up / r-down to a note for change",
    "r-card, r-grid": "a panel, and a responsive grid of panels",
    "r-note (warn, bad, good)": "a highlighted remark",
    "r-tag (c1–c6)": "a small label, optionally in one of six series colours",
    "r-toolbar, r-search, r-chips > r-chip[aria-pressed]": "filters; keep the filter state in the URL, not storage",
    "r-table-wrap > table.r-table": "tables with a sticky header; th.num/td.num right-align figures; tr.r-group, "
                                     "tr.r-total or tfoot for subtotals; r-muted for secondary text",
    "r-bar (c1–c6) > span[style=width:N%]": "a simple horizontal bar in a table cell",
    "r-legend": "a legend: <span><i style=\"background:var(--c1)\"></i>Series A</span>",
    "details.r-details": "a collapsible section",
    "r-sources": "the footer with sources and what could not be read",
}


def t_style(_):
    return {"stylesheet": '<link rel="stylesheet" href="/static/report.css">',
            "how": "Link the stylesheet in <head> and build the page from the classes below. Do not set your own "
                   "colours, fonts or background: the site's look (and dark mode) comes from the stylesheet, so a "
                   "report looks like the start page and changes with it. Inline CSS only for layout the kit lacks. "
                   "For charts use the series colours var(--c1)…var(--c6) and var(--accent).",
            "colours": {"accent": "var(--accent)", "text": "var(--text)", "muted": "var(--muted)",
                        "surface": "var(--surface)", "series": ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)",
                                                                "var(--c5)", "var(--c6)"],
                        "brand_values": BRAND_INFO.get("colours", {})},
            "fonts": {"heading": BRAND_INFO.get("heading_font") or "system sans-serif",
                      "body": BRAND_INFO.get("body_font") or "system sans-serif",
                      "note": "Loaded by the stylesheet; do not add font links."},
            "classes": STYLE_CLASSES,
            "skeleton": REPORT_SKELETON.replace("{lang}", LANG).replace("{back}", T["back"]),
            "rules": ["A complete HTML document with data inline; no external scripts unless needed for a chart.",
                      "Reports run in a sandbox: localStorage and cookies do not work; keep filter state in the URL.",
                      "Must work at 390 px wide: tables inside r-table-wrap, no fixed widths.",
                      "Write numbers with the unit and the definition used (e.g. which invoices are counted).",
                      "End with r-sources: what the report is built on and what could not be read."]}


BRAND_HELP = ("Colours as #rrggbb or #rrggbbaa: " + ", ".join(brandstore.COLOURS) + "; dark: an object with "
              + ", ".join(brandstore.DARK) + " for dark mode; heading_font, body_font (family names, the font files "
              "given in files and declared in fonts); heading_weight 100–900; heading_scale 0.7–1.6; radius 0–24; "
              "series: up to six chart colours; fonts: [{family, file, weight, style, unicode_range}].")


def t_get_brand(_):
    cur = brands.current()
    return {"version": cur, "current": f"v{cur}" if cur else "the base look (no agent changes)",
            "settings": BRAND_INFO.get("settings", {}), "agent_layer": brands.settings(),
            "files": {n: ("agent" if n in brands.files() else "site") for n in BRANDING["files"]
                      if BRANDING["files"][n] != DEFAULT_ICONS.get(n)} | {f"fonts/{n}": "font" for n in BRANDING["fonts"]},
            "history": brands.history(20), "allowed": BRAND_HELP,
            "files_allowed": f"{', '.join(brandstore.IMAGES)} (images up to {brandstore.MAX_IMAGE // 1024} kB) and fonts "
                             f"named like body.woff2 (up to {brandstore.MAX_FONT // 1024} kB)",
            "note": "update_brand changes it, restore_brand(version) goes back, version 0 is the base look. People see "
                    "the history at /brand and can restore it too."}


def t_update_brand(a, who):
    files = dict(brandstore.decode_file(item) for item in (a.get("files") or []))
    meta = brands.update(who, settings=a.get("settings"), files=files, note=a.get("note"),
                         base_dirs=[BRAND_DIR] if BRAND_DIR else [])
    reload_brand()
    log(f"{who}: brand v{meta['version']} ({', '.join(meta['settings'] + meta['files'])})")
    return {**meta, "url": PUBLIC_URL + "/brand",
            "result": "Live now on the start page and in reports that link /static/report.css (within minutes). "
                      "Check it in the browser; restore_brand goes back."}


def t_restore_brand(a, who):
    try:
        meta = brands.restore(a.get("version", 0), who)
    except (KeyError, ValueError, TypeError):
        raise ValueError("No such version; see get_brand for the history (0 is the base look).")
    reload_brand()
    log(f"{who}: brand v{meta['version']} ({meta['note']})")
    return meta


S = {"type": "string"}
TOOLS = [
    ("publish_report", lambda a, w: t_publish(a, w),
     "Publish a report, or a new version of one, for people to read in the browser. Give a title, the "
     "content (a complete HTML page, or markdown with format=markdown), a one-or-two sentence description "
     "and a category: the start page shows them as a card, so you never write an index page yourself. "
     "Publishing the same slug again adds a version; earlier ones are kept and a person can restore them. "
     "Reports cannot be deleted or hidden by agents. Link between reports with relative links "
     "('other-slug.html').",
     {"title": {**S, "description": "Shown on the card and in lists"},
      "content": {**S, "description": "The report: a full HTML document (inline CSS/JS) or markdown"},
      "slug": {**S, "description": "Address: lowercase, digits, hyphens. Default: made from the title. "
                                   "Use the same slug to update a report"},
      "format": {**S, "enum": list(FORMATS), "description": "html (default) or markdown"},
      "description": {**S, "description": "What the reader finds in it, one or two sentences"},
      "category": {**S, "description": "Groups cards on the start page; reuse existing ones (list_reports)"},
      "tags": {"type": "array", "items": S, "description": "Optional keywords"},
      "note": {**S, "description": "What changed in this version"},
      "requested_by": {**S, "description": "The person who asked for this report, when several people share "
                                          "this agent; shown as '<person> via <agent>'"},
      "expected_version": {"type": "integer", "description": "Refuse if the report is no longer at this version"}},
     ["title", "content"]),
    ("update_report_details", lambda a, w: t_details(a, w),
     "Change the title, description, category or tags of a report without publishing new content.",
     {"slug": S, "title": S, "description": S, "category": S, "tags": {"type": "array", "items": S}}, ["slug"]),
    ("list_reports", lambda a, w: t_list(a),
     "The published reports with title, description, category, version and link, and the categories in use.",
     {"category": S, "query": {**S, "description": "Words in slug, title, description, category or tags"},
      "include_archived": {"type": "boolean"}}, []),
    ("read_report", lambda a, w: t_read(a),
     "Read a report's content (the current version, or an older one), e.g. to build on it.",
     {"slug": S, "version": {"type": "integer"}}, ["slug"]),
    ("report_versions", lambda a, w: t_versions(a),
     "Every version of a report: when, by whom, the note and a link to each.", {"slug": S}, ["slug"]),
]
if AGENT_BRANDING:
    TOOLS += [
        ("get_brand", lambda a, w: t_get_brand(a),
         "The site's look: current logo, fonts and colours, what agents changed, the history, and what may be set.",
         {}, []),
        ("update_brand", lambda a, w: t_update_brand(a, w),
         "Change the site's look: colours, fonts, logo and icons, in one change that becomes one version (people "
         "can roll it back). E.g. to match a company's website: take its logo, fonts and colours. Files can be "
         "URLs (https, public sites), fetched by the server, so they do not pass through you. " + BRAND_HELP,
         {"settings": {"type": "object", "description": "brand.json keys to set; null removes one"},
          "files": {"type": "array", "description": "[{name, url} | {name, base64} | {name, remove: true}]; names: "
                                                    + ", ".join(brandstore.IMAGES) + ", or fonts like body.woff2",
                    "items": {"type": "object"}},
          "note": {**S, "description": "What changed and why, e.g. 'colours and fonts from example.com'"}}, ["note"]),
        ("restore_brand", lambda a, w: t_restore_brand(a, w),
         "Go back to an earlier look (a version from get_brand), or to the base look with version 0.",
         {"version": {"type": "integer"}}, ["version"]),
    ]
if REPORT_STYLE:
    TOOLS.insert(1, ("report_style", lambda a, w: t_style(a),
                     "How reports on this site should look: the stylesheet to link, the classes to use, a page "
                     "skeleton and the rules. Call it before building a report.", {}, []))
BY_NAME = {n: fn for n, fn, *_ in TOOLS}


def tool_list():
    return [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": p, "required": r},
             "annotations": {"readOnlyHint": n not in ("publish_report", "update_report_details", "update_brand",
                                                       "restore_brand"),
                             "destructiveHint": False}} for n, _, d, p, r in TOOLS]


def rpc(msg, who):
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None
    ok = lambda result: {"jsonrpc": "2.0", "id": mid, "result": result}
    if method == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion") or "2025-06-18",
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "agentreports", "version": VERSION},
                   "instructions": f"{TITLE}: publish reports for people with publish_report. The start page is "
                                   "generated from title, description and category. Nothing you publish replaces "
                                   "history: each publish is a version."
                                   + (" Reports should look like the site: link /static/report.css and use its r-* "
                                      "classes, no colours or fonts of your own; report_style has the details."
                                      if REPORT_STYLE else "")})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": tool_list()})
    if method == "tools/call":
        fn = BY_NAME.get(params.get("name"))
        if not fn:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool: {params.get('name')}"}}
        args = params.get("arguments") or {}
        try:
            result = fn(args, who)
            return ok({"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=1)}],
                       "structuredContent": result, "isError": False})
        except (ValueError, KeyError, TypeError) as e:
            return ok({"content": [{"type": "text", "text": str(e)}], "isError": True})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unknown method: {method}"}}


# --- pages ----------------------------------------------------------------------------------

def asset(name):
    with open(os.path.join(UI, name), "rb") as f:
        return f.read()


def hex_color(value):
    return value if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", value) else None


def ink_for(color, dark="#08201d"):
    """Dark or white text on a button of this colour, whichever reads better."""
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return dark if 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2] > 0.3 else "#ffffff"


def font_name(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9 _-]{1,60}", value) else None


BRAND_INFO = {}
BRAND_FILES = ("logo.svg", "logo.png", "logo-dark.svg", "logo-dark.png", "favicon.svg", "favicon.png",
               "favicon.ico", "apple-touch-icon.png")


def brand_layers():
    """BRAND_DIR (the operator's) first, then the layer agents maintain, when that is allowed."""
    layers = [BRAND_DIR] if BRAND_DIR else []
    agent_dir = brands.layer_dir() if AGENT_BRANDING else None
    return layers + ([agent_dir] if agent_dir else [])


def merged_settings(layers):
    cfg = {}
    for layer in layers:
        try:
            with open(os.path.join(layer, "brand.json"), encoding="utf-8") as f:
                more = json.load(f)
        except (OSError, ValueError):
            continue
        for key, value in more.items():
            cfg[key] = {**cfg.get("dark", {}), **value} if key == "dark" and isinstance(value, dict) else value
    return cfg


def layer_file(layers, name):
    """The path of name in the last layer that has it."""
    for layer in reversed(layers):
        path = os.path.join(layer, name)
        if os.path.isfile(path):
            return path
    return None


def brand():
    """Files, fonts and colours from the brand layers over the defaults. Returns (assets, css)."""
    layers = brand_layers()
    found = {}
    for name in BRAND_FILES:
        path = layer_file(layers, name)
        if path and os.path.getsize(path) <= 2 * 1024 * 1024:
            with open(path, "rb") as f:
                found[name] = f.read()
    cfg = merged_settings(layers)
    if "favicon.svg" not in found and "favicon.png" not in found and "logo.svg" in found:
        found["favicon.svg"] = found["logo.svg"]

    rules, light, root = [], {}, []
    text = hex_color(cfg.get("text"))
    for key, var in (("background", "--bg"), ("surface", "--surface"), ("surface_2", "--surface-2"),
                     ("text", "--text"), ("muted", "--muted"), ("faint", "--faint"), ("line", "--line"),
                     ("line_strong", "--line-strong"), ("accent", "--accent"), ("accent_text", "--accent-text")):
        if hex_color(cfg.get(key)):
            light[var] = cfg[key]
    if "--bg" in light:
        light["--bg-grad"] = "none"
    if "--accent" in light:
        light["--accent-ink"] = hex_color(cfg.get("accent_ink")) or ink_for(light["--accent"], text or "#08201d")
        light["--accent-soft"] = f"color-mix(in srgb, {light['--accent']} 16%, {light.get('--surface', '#ffffff')})"
    # Fonts: files in BRAND_DIR, declared in brand.json, served from this site (nothing from a font CDN).
    for font in cfg.get("fonts") or []:
        family, file = font_name(font.get("family")), str(font.get("file") or "")
        path = layer_file(layers, file) if re.fullmatch(r"[A-Za-z0-9._-]+\.woff2?", file) else None
        if not family or not path:
            log(f"brand.json: font {font!r} skipped (family, and a .woff2 file in the brand folder)")
            continue
        with open(path, "rb") as f:
            found["fonts/" + file] = f.read()
        weight = str(font.get("weight") or "400")
        style = "italic" if font.get("style") == "italic" else "normal"
        rng = font.get("unicode_range")
        rng = f" unicode-range: {rng};" if isinstance(rng, str) and re.fullmatch(r"[Uu0-9A-Fa-f+?, -]+", rng) else ""
        rules.append(f"@font-face {{ font-family: '{family}'; src: url('/brand/fonts/{file}') "
                     f"format('{'woff2' if file.endswith('2') else 'woff'}'); font-weight: {weight if re.fullmatch(r'[0-9 ]+', weight) else '400'}; "
                     f"font-style: {style}; font-display: swap;{rng} }}")
    if font_name(cfg.get("body_font")):
        root.append(f"--font-body: '{cfg['body_font']}', ui-sans-serif, system-ui, sans-serif;")
    if font_name(cfg.get("heading_font")):
        root.append(f"--font-heading: '{cfg['heading_font']}', Georgia, serif;")
        root.append("--heading-tracking: 0;")
    if str(cfg.get("heading_weight", "")).isdigit():
        root.append(f"--heading-weight: {int(cfg['heading_weight'])};")
    if isinstance(cfg.get("heading_scale"), (int, float)) and 0.7 <= cfg["heading_scale"] <= 1.6:
        root.append(f"--heading-scale: {cfg['heading_scale']};")
    series = [c for c in (cfg.get("series") or []) if hex_color(c)][:6]
    root += [f"--c{i}: {c};" for i, c in enumerate(series, 1)]
    if isinstance(cfg.get("radius"), int) and 0 <= cfg["radius"] <= 24:
        root.append(f"--radius: {cfg['radius']}px; --radius-control: {min(cfg['radius'], 11)}px;")
    root += [f"{k}: {v};" for k, v in light.items()]
    if root:
        rules.append(":root { " + " ".join(root) + " }")
    night = cfg.get("dark") if isinstance(cfg.get("dark"), dict) else {}
    dark_vars = {var: night[key] for key, var in (("background", "--bg"), ("surface", "--surface"),
                                                  ("surface_2", "--surface-2"), ("text", "--text"), ("muted", "--muted"),
                                                  ("faint", "--faint"), ("line", "--line"), ("line_strong", "--line-strong"))
                 if hex_color(night.get(key))}
    if "--bg" in dark_vars:
        dark_vars["--bg-grad"] = "none"
    dark = hex_color(cfg.get("accent_dark")) or light.get("--accent")
    if dark:
        dark_vars.update({"--accent": dark, "--accent-text": dark, "--accent-ink": ink_for(dark, dark_vars.get("--bg", "#08201d")),
                          "--accent-soft": f"color-mix(in srgb, {dark} 18%, {dark_vars.get('--surface', '#131c1e')})"})
    if dark_vars:
        block = " ".join(f"{k}: {v};" for k, v in dark_vars.items())
        rules.append("@media (prefers-color-scheme: dark) { :root:not([data-theme=\"light\"]) { " + block + " } }")
        rules.append(":root[data-theme=\"dark\"] { " + block + " }")
    if cfg and not rules:
        log("brand.json: nothing usable in it (colours are #rrggbb, fonts need a file); ignored")
    BRAND_INFO.clear()
    BRAND_INFO.update(settings=cfg, colours={k: cfg[k] for k in ("accent", "accent_text", "background", "surface", "text", "muted")
                               if hex_color(cfg.get(k))},
                      heading_font=font_name(cfg.get("heading_font")), body_font=font_name(cfg.get("body_font")))
    return found, "\n".join(rules).encode()


def brand_html(found):
    """The <link rel=icon> lines and the logo element, from whatever the brand provides."""
    icons = []
    if "favicon.png" in found:
        icons.append('<link rel="icon" href="/favicon.png?v={v}" type="image/png">')
    else:
        icons.append('<link rel="icon" href="/favicon.svg?v={v}" type="image/svg+xml">')
    icons.append('<link rel="icon" href="/favicon.ico?v={v}" sizes="any">')
    icons.append('<link rel="apple-touch-icon" href="/apple-touch-icon.png?v={v}">')
    logo = next((f"/{n}" for n in ("logo.svg", "logo.png") if n in found), "/favicon.svg")
    dark = next((f"/{n}" for n in ("logo-dark.svg", "logo-dark.png") if n in found), None)

    def logo_el(height):
        img = f'<img src="{logo}?v={{v}}" alt="" height="{height}">'
        if not dark:
            return img
        # Both, and CSS shows one: a <picture> media query would follow the system, not the theme switch.
        return (f'<img class="logo-light" src="{logo}?v={{v}}" alt="" height="{height}">'
                f'<img class="logo-dark" src="{dark}?v={{v}}" alt="" height="{height}">')
    return "\n".join(icons), logo_el(32), logo_el(56)


ASSETS = {n: asset(n) for n in os.listdir(UI)}
REPORT_KIT = ASSETS.pop("report.css")
DEFAULT_ICONS = {n: ASSETS[n] for n in ("favicon.svg", "favicon.ico", "apple-touch-icon.png")}
BRANDING = {}          # the current brand, swapped as a whole when it changes
_brand_lock = threading.Lock()


def reload_brand():
    files, css = brand()
    served = {**DEFAULT_ICONS, **{n: d for n, d in files.items() if not n.startswith("fonts/")}}
    v = hashlib.sha256(b"".join(ASSETS[n] for n in sorted(ASSETS)) + css
                       + b"".join(files[n] for n in sorted(files))).hexdigest()[:10]
    icons, logo_32, logo_56 = (x.replace("{v}", v) for x in brand_html(files))
    global BRANDING
    with _brand_lock:  # one new dict, swapped in whole: a request never sees half a brand
        BRANDING = dict(files=served, fonts={n[6:]: d for n, d in files.items() if n.startswith("fonts/")},
                        css=css, report_css=REPORT_KIT + b"\n/* brand */\n" + css, v=v,
                        icons=icons, logo_32=logo_32, logo_56=logo_56)


reload_brand()
TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
         ".ico": "image/x-icon", ".png": "image/png", ".html": "text/html; charset=utf-8"}


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def json_script(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")


THEME_SWITCH = """<div class="theme" role="group" aria-label="{theme}">
        <button type="button" data-theme-set="system" title="{system}" aria-label="{system}"><svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg></button>
        <button type="button" data-theme-set="light" title="{light}" aria-label="{light}"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg></button>
        <button type="button" data-theme-set="dark" title="{dark}" aria-label="{dark}"><svg viewBox="0 0 24 24"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg></button>
      </div>"""


def top_actions():
    switch = THEME_SWITCH.format(theme=esc(T["theme"]), system=esc(T["theme_system"]), light=esc(T["theme_light"]),
                                 dark=esc(T["theme_dark"]))
    link = f'<a class="btn ghost small" href="/brand">{esc(T["brand"])}</a>' if AGENT_BRANDING or BRAND_DIR else ""
    return (f'<div class="top-actions">{switch}{link}<form method="post" action="/logout">'
            f'<button class="btn ghost small" type="submit">{esc(T["logout"])}</button></form></div>')


def page(name, **values):
    """Fill a template in one pass, so text from a report can never fill in another placeholder."""
    values.setdefault("lang", LANG)
    values.setdefault("v", BRANDING["v"])
    values.setdefault("site_title", esc(TITLE))
    values.setdefault("icons", BRANDING["icons"])
    values.setdefault("top_actions", top_actions())
    values.setdefault("logo_32", BRANDING["logo_32"])
    values.setdefault("logo_56", BRANDING["logo_56"])

    def fill(m):
        if m.group(1):
            return esc(T.get(m.group(2), m.group(2)))
        return str(values.get(m.group(2), ""))
    return re.sub(r"\{\{(t\.)?(\w+)\}\}", fill, ASSETS[name].decode()).encode()


# Appended to a report shown inside the app: it tells the app which report is showing, and sends links to
# the start page or to another report's app address (/r/<slug>) to the app instead of opening the whole
# site inside the frame. It carries nothing but a slug or such a path.
FRAME_SCRIPT = """<script>(function(){var s=%s;try{parent.postMessage({agentreports:s},"*")}catch(e){}
document.addEventListener("click",function(e){var a=e.target.closest&&e.target.closest("a[href]");
if(!a||(a.target&&a.target!=="_self")||e.metaKey||e.ctrlKey||e.shiftKey)return;var u;try{u=new URL(a.href)}catch(x){return}
if(u.host!==location.host)return;if(u.pathname==="/"||/^\\/r\\/[a-z0-9-]+\\/?$/.test(u.pathname)){e.preventDefault();
parent.postMessage({agentreportsGo:u.pathname},"*")}},true)})();</script>"""


def shell(slug=None):
    """The app: reports in a panel on the left; the overview, or one report, on the right."""
    reports = [public(m) for m in store.all()]
    return page("dashboard.html", subtitle=esc(SUBTITLE),
                data=json_script({"lang": LANG, "words": T, "reports": reports, "open": slug,
                                  "site": TITLE, "brand_page": bool(AGENT_BRANDING or BRAND_DIR)}))


def fmt_time(iso):
    """A <time> the page shows in the reader's own time zone; UTC until the script has run."""
    try:
        text = datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return ""
    return f'<time datetime="{esc(iso)}">{text}</time>'



def fmt_size(n):
    n = int(n or 0)
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, round(n / 1024))} kB"


def details(slug):
    meta = store.get(slug)
    if not meta:
        return None
    rows = []
    for v in store.versions(slug):
        current = v["version"] == meta["version"]
        restore = "" if current else (f'<button class="btn small" data-action="restore" data-slug="{esc(slug)}" '
                                      f'data-version="{v["version"]}">{esc(T["restore"])}</button>')
        rows.append(f'<tr><td><b>v{v["version"]}</b>{" <span class=badge>" + esc(T["current"]) + "</span>" if current else ""}'
                    f'</td><td>{fmt_time(v["at"])}</td><td title="{esc(v["by"])}">{esc(who_text(v["by"], v.get("requested_by")))}</td><td>{esc(v.get("note") or "")}</td>'
                    f'<td class="num">{esc(fmt_size(v["bytes"]))}</td><td class="actions">'
                    f'<a class="btn small ghost" href="/r/{esc(slug)}/v/{v["version"]}">{esc(T["view"])}</a>{restore}</td></tr>')
    archived = bool(meta.get("archived"))
    tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in meta.get("tags", []))
    return page("details.html", title=esc(meta["title"]), slug=esc(slug), description=esc(meta.get("description") or ""),
                category=esc(meta.get("category") or T["uncategorized"]), tags=tags,
                created=fmt_time(meta.get("created")), created_by=esc(who_text(meta.get("created_by"), meta.get("created_for"))),
                updated=fmt_time(meta.get("updated")), updated_by=esc(who_text(meta.get("updated_by"), meta.get("updated_for"))),
                version=meta["version"], format=esc(meta.get("format")), rows="".join(rows),
                archived_class="is-archived" if archived else "",
                archive_action="unarchive" if archived else "archive",
                archive_label=esc(T["unarchive"] if archived else T["archive"]),
                data=json_script({"lang": LANG, "words": T}))


def brand_page():
    cur = brands.current()
    cfg = BRAND_INFO.get("settings", {})
    sw = []
    for key in ("background", "surface", "text", "accent", "accent_text"):
        if brandstore.HEX.match(str(cfg.get(key, ""))):
            sw.append(f'<span class="swatch" data-colour="{esc(cfg[key])}" title="{esc(key)} {esc(cfg[key])}"></span>')
    for i, c in enumerate(cfg.get("series") or []):
        if brandstore.HEX.match(str(c)):
            sw.append(f'<span class="swatch small" data-colour="{esc(c)}" title="series {i + 1} {esc(c)}"></span>')
    fonts = " · ".join(esc(cfg[k]) for k in ("heading_font", "body_font") if cfg.get(k))
    rows = []
    for h in brands.history():
        changed = ", ".join(h.get("settings", []) + h.get("files", []))
        restore = "" if h["version"] == cur else (
            f'<button class="btn small" data-action="brand-restore" data-version="{h["version"]}">{esc(T["restore"])}</button>')
        rows.append(f'<tr><td><b>v{h["version"]}</b>{" <span class=badge>" + esc(T["current"]) + "</span>" if h["version"] == cur else ""}</td>'
                    f'<td>{fmt_time(h.get("at"))}</td><td title="{esc(h.get("by"))}">{esc(shown(h.get("by")))}</td>'
                    f'<td>{esc(h.get("note") or "")}</td><td>{esc(changed)}</td><td class="actions">{restore}</td></tr>')
    if not rows:
        rows.append(f'<tr><td colspan="6">{esc(T["brand_none"] if AGENT_BRANDING else T["brand_off"])}</td></tr>')
    current = f'{esc(T["current"]).capitalize()}: ' + (f"v{cur}" if cur else esc(T["brand_current_base"])) + (f" · {fonts}" if fonts else "")
    base = (f'<button class="btn" data-action="brand-restore" data-version="0">{esc(T["brand_base"])}</button>'
            if cur and AGENT_BRANDING else "")
    return page("brand.html", swatches="".join(sw), current=current, base_button=base, rows="".join(rows),
                data=json_script({"lang": LANG, "words": T}))


def markdown_page(meta, data):
    return (f'<!doctype html><html lang="{LANG}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(meta["title"])}</title>'
            f'<style>{ASSETS["markdown.css"].decode()}</style></head><body><main id="doc"></main>'
            f'<script type="application/json" id="md">{json_script(data.decode("utf-8", "replace"))}</script>'
            f'<script src="{MARKED}"></script>'
            '<script>document.getElementById("doc").innerHTML=marked.parse(JSON.parse('
            'document.getElementById("md").textContent))</script></body></html>').encode()


# --- http -----------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version, sys_version = "agentreports", ""
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def ip(self):
        # X-Forwarded-For can be a list; the last entry is the one our own proxy added.
        value = (self.headers.get(PROXY_HEADER) if PROXY_HEADER else None) or ""
        return value.split(",")[-1].strip() or self.client_address[0]

    def send(self, code, body=b"", ctype="text/html; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def json(self, code, obj, headers=None):
        self.send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json", headers)

    def ours(self, body, code=200):
        self.send(code, body, headers={"Content-Security-Policy": PAGE_CSP, "Cache-Control": "no-store",
                                       "X-Frame-Options": "DENY"})

    def redirect(self, where, headers=None):
        self.send(303, b"", headers={"Location": where, **(headers or {})})

    def signed_in(self):
        c = http.cookies.SimpleCookie()
        try:
            c.load(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            return False
        return COOKIE in c and session_ok(c[COOKIE].value)

    def cookie(self, value, max_age):
        secure = "; Secure" if PUBLIC_URL.startswith("https://") else ""
        return f"{COOKIE}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}{secure}"

    def body(self, limit):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("too large")
        return self.rfile.read(n)

    def not_found(self):
        self.ours(page("message.html", title=esc(T["not_found"]), text=esc(T["not_found_text"])), 404)

    # --- GET ---

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/health":
            return self.json(200, {"ok": True, "version": VERSION})
        name = path.lstrip("/")
        b = BRANDING
        if name in b["files"]:
            # A brand image may come from an agent: an SVG is shown, never run.
            extra = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"} if name.endswith(".svg") else {}
            return self.send(200, b["files"][name], TYPES.get(os.path.splitext(name)[1], "application/octet-stream"),
                             {"Cache-Control": "public, max-age=604800", **extra})
        if path == "/static/brand.css":
            return self.send(200, b["css"], "text/css; charset=utf-8", {"Cache-Control": "public, max-age=604800"})
        if path.startswith("/static/") and path[8:] in ASSETS and not path.endswith(".html"):
            name = path[8:]
            return self.send(200, ASSETS[name], TYPES.get(os.path.splitext(name)[1], "application/octet-stream"),
                             {"Cache-Control": "public, max-age=604800"})
        if path.startswith("/brand/fonts/") and path[13:] in b["fonts"]:
            # Reports run sandboxed (an opaque origin), and fonts are always fetched with CORS.
            return self.send(200, b["fonts"][path[13:]], "font/woff2" if path.endswith("2") else "font/woff",
                             {"Cache-Control": "public, max-age=31536000, immutable", "Access-Control-Allow-Origin": "*"})
        if path == "/static/report.css":
            if not REPORT_STYLE:
                return self.send(404, b"", "text/plain")
            return self.send(200, b["report_css"], "text/css; charset=utf-8",
                             {"Cache-Control": "public, max-age=300", "Access-Control-Allow-Origin": "*"})
        if path == "/mcp":
            return self.send(405, b"", headers={"Allow": "POST"})
        if path == "/robots.txt":
            return self.send(200, b"User-agent: *\nDisallow: /\n", "text/plain")
        if path == "/login":
            if self.signed_in():
                return self.redirect("/")
            return self.ours(page("login.html", error="", next=esc(urllib.parse.parse_qs(query).get("next", ["/"])[0])))
        if not self.signed_in():
            return self.redirect("/login?next=" + urllib.parse.quote(self.path, safe=""))

        if path in ("/", "/index.html"):
            return self.redirect("/") if path != "/" else self.ours(shell())
        if path == "/brand":
            return self.ours(brand_page())
        if path == "/api/reports":
            return self.json(200, {"reports": [public(m) for m in store.all()]}, {"Cache-Control": "no-store"})
        m = re.match(r"^/r/([a-z0-9-]+)/?$", path)
        if m:
            return self.ours(shell(m.group(1))) if store.get(m.group(1)) else self.not_found()
        m = re.match(r"^/r/([a-z0-9-]+)/info$", path)
        if m:
            body = details(m.group(1))
            return self.ours(body) if body else self.not_found()
        m = re.match(r"^/r/([a-z0-9-]+)/v/(\d+)$", path)
        if m:
            return self.report(m.group(1), int(m.group(2)))
        m = re.match(r"^/([a-z0-9][a-z0-9-]*)(\.html|\.md)?$", path)
        if m:
            if m.group(2) != ".html":  # /slug and /slug.md lead to the page
                return self.redirect(f"/{m.group(1)}.html") if store.get(m.group(1)) else self.not_found()
            return self.report(m.group(1))
        if FILES_DIR and (path + "/").startswith(FILES_ROUTE + "/"):
            return self.file(urllib.parse.unquote(path[len(FILES_ROUTE):]))
        return self.not_found()

    def report(self, slug, version=None):
        found = store.content(slug, version) if SLUG.match(slug) else None
        if not found:
            return self.not_found()
        meta, data, info = found
        if info["format"] == "markdown":
            data = markdown_page(meta, data)
        if self.headers.get("Sec-Fetch-Dest") == "iframe":
            # Inside the site's panel: tell the page around it which report is showing, so a link from one
            # report to another updates the address bar and the panel. Only the slug, only to the parent.
            data += (FRAME_SCRIPT % json.dumps(meta["slug"])).encode()
        # The report runs in a sandbox: its scripts work, but it has no access to the session or to the
        # start page, so a report can not archive, restore or read anything on behalf of the reader.
        self.send(200, data, "text/html; charset=utf-8", {"Content-Security-Policy": REPORT_CSP,
                                                          "Cache-Control": "private, no-cache"})

    def file(self, rel):
        parts = [p for p in rel.split("/") if p]
        root = os.path.realpath(FILES_DIR)
        full = os.path.realpath(os.path.join(root, *parts)) if parts else root
        if (not parts or any(p.startswith(".") for p in parts) or not full.startswith(root + os.sep)
                or not os.path.isfile(full)):
            return self.not_found()
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype == "image/svg+xml" or ctype.startswith("text/") or ctype.endswith(("xml", "json", "javascript")):
            ctype = "text/plain; charset=utf-8"  # shown, never run
        size = os.path.getsize(full)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(full))
        self.send_response(200)
        for k, v in {"Content-Type": ctype, "Content-Length": str(size), "X-Content-Type-Options": "nosniff",
                     "Content-Security-Policy": "sandbox", "Cache-Control": "private, max-age=300",
                     "Content-Disposition": f'inline; filename="{safe}"'}.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            with open(full, "rb") as f:
                try:
                    shutil.copyfileobj(f, self.wfile)
                except (BrokenPipeError, ConnectionResetError):
                    pass

    # --- POST ---

    def do_POST(self):
        path = self.path.partition("?")[0]
        if path == "/mcp":
            return self.mcp()
        if path == "/login":
            return self.login()
        # Everything else is a person acting in the browser: signed in, from our own page.
        same_origin = self.headers.get("X-Requested-With") == "agentreports" and (
            not self.headers.get("Origin") or urllib.parse.urlparse(self.headers["Origin"]).netloc == self.headers.get("Host"))
        if path == "/logout":
            return self.redirect("/login", {"Set-Cookie": self.cookie("", 0)})
        if not self.signed_in():
            return self.json(401, {"error": "sign in"})
        if not same_origin:
            return self.json(403, {"error": "forbidden"})
        if path == "/api/brand/restore" and AGENT_BRANDING:
            try:
                meta = brands.restore(int(json.loads(self.body(10_000) or b"{}").get("version", 0)), "browser")
            except (KeyError, ValueError, TypeError):
                return self.json(404, {"error": "not found"})
            reload_brand()
            log(f"browser ({self.ip()}): brand v{meta['version']} ({meta['note']})")
            return self.json(200, meta)
        m = re.match(r"^/api/reports/([a-z0-9-]+)/(archive|unarchive|restore)$", path)
        if not m:
            return self.json(404, {"error": "not found"})
        slug, action = m.groups()
        who = "browser"
        try:
            if action == "restore":
                v = int(json.loads(self.body(10_000) or b"{}").get("version"))
                meta = store.restore(slug, v, who)
            else:
                meta = store.set_archived(slug, action == "archive", who)
        except (KeyError, ValueError, TypeError):
            return self.json(404, {"error": "not found"})
        log(f"{who} ({self.ip()}): {action} {slug}")
        return self.json(200, public(meta))

    def login(self):
        ip = self.ip()
        try:
            form = urllib.parse.parse_qs(self.body(10_000).decode())
        except ValueError:
            return self.send(400)
        nxt = form.get("next", ["/"])[0]
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/"
        if locked(ip):
            return self.ours(page("login.html", error=f'<p class="error">{esc(T["locked_out"])}</p>', next=esc(nxt)), 429)
        if password_ok(form.get("password", [""])[0]):
            log(f"signed in from {ip}")
            return self.redirect(nxt, {"Set-Cookie": self.cookie(make_session(), SESSION_DAYS * 86400)})
        failed(ip)
        log(f"wrong password from {ip}")
        time.sleep(0.5)
        return self.ours(page("login.html", error=f'<p class="error">{esc(T["wrong_password"])}</p>', next=esc(nxt)), 401)

    def mcp(self):
        who = agent(self.headers.get("Authorization", ""))
        if not who:
            return self.json(401, {"error": "Missing or wrong key. Send Authorization: Bearer <key>."},
                             {"WWW-Authenticate": "Bearer"})
        try:
            msg = json.loads(self.body(20 * 1024 * 1024) or b"null")
        except ValueError:
            return self.json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON"}})
        batch = msg if isinstance(msg, list) else [msg]
        answers = [a for a in (rpc(m, who) for m in batch if isinstance(m, dict)) if a is not None]
        if not answers:
            return self.send(202, b"", "application/json")
        return self.json(200, answers if isinstance(msg, list) else answers[0])


def main():
    if len(PASSWORD) < 20:
        log("REPORTS_PASSWORD must be at least 20 characters. Refusing to start.")
        sys.exit(1)
    if not KEYS:
        log("MCP_KEYS has no name:key pair with a key of 32+ characters: agents cannot publish.")
    port = int(os.environ.get("PORT", "8000"))
    log(f"agentreports {VERSION} on :{port}, {len(store.all())} reports, agents: {', '.join(sorted(KEYS.values())) or '-'}"
        + (f", files {FILES_DIR} at {FILES_ROUTE}" if FILES_DIR else "")
        + f", brand: {', '.join(sorted(n for n in BRANDING['files'] if n not in DEFAULT_ICONS or BRANDING['files'][n] != DEFAULT_ICONS[n])) or 'default icons'}"
        + f"{' + styles' if BRANDING['css'] else ''}{f' (agent layer v{brands.current()})' if AGENT_BRANDING and brands.current() else ''}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    if sys.argv[1:2] == ["import"]:
        import importer
        importer.main(sys.argv[2:], store)
    else:
        main()
