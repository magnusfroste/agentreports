#!/usr/bin/env python3
"""Security check for a running AgentReports, from the outside, as a stranger would see it.

    python tools/security_check.py https://reports.example.com [--files-route /files] [--out protocol.md]

It checks that nothing but the sign-in page and the public assets answers without signing in, that forged
sessions and wrong agent keys are refused, and that the actions people take in the browser need both a
session and the site's own page. It never signs in with the password and never tries passwords, so it
cannot lock anyone out.

With AR_CHECK_KEY set to one agent key from MCP_KEYS (read from the environment, never printed) it also
checks that a valid key works, and uses it to find real report slugs and source-file links, so the
"no access without signing in" checks run against content that exists.

Exit code 0 when every check passed, 1 otherwise. Standard library only.
"""
import argparse
import datetime
import http.client
import json
import os
import re
import secrets
import ssl
import sys
import time
import urllib.parse

UA = "AgentReports security check"


class Site:
    def __init__(self, base):
        u = urllib.parse.urlsplit(base.rstrip("/"))
        self.base, self.host, self.https = base.rstrip("/"), u.hostname, u.scheme == "https"
        self.port = u.port or (443 if self.https else 80)

    def req(self, method, path, body=None, headers=None):
        conn = (http.client.HTTPSConnection(self.host, self.port, timeout=20, context=ssl.create_default_context())
                if self.https else http.client.HTTPConnection(self.host, self.port, timeout=20))
        try:
            h = {"User-Agent": UA, **(headers or {})}
            if body is not None and not isinstance(body, bytes):
                body = json.dumps(body).encode()
                h.setdefault("Content-Type", "application/json")
            conn.request(method, path, body=body, headers=h)
            r = conn.getresponse()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
        finally:
            conn.close()

    def mcp(self, payload, key=None, scheme="Bearer"):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if key is not None:
            h["Authorization"] = f"{scheme} {key}"
        return self.req("POST", "/mcp", payload, h)


class Protocol:
    def __init__(self):
        self.rows = []

    def check(self, group, name, ok, detail=""):
        self.rows.append((group, name, bool(ok), detail))
        print(f"{'PASS' if ok else 'FAIL'}  {group}: {name}" + (f"  [{detail}]" if detail and not ok else ""))

    @property
    def failed(self):
        return [r for r in self.rows if not r[2]]


def to_login(status, headers):
    return status == 303 and headers.get("location", "").startswith(("/login", "https://", "http://")) \
        and "/login" in headers.get("location", "")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("base", help="e.g. https://reports.example.com")
    ap.add_argument("--files-route", default="/files", help="FILES_ROUTE of the site, if it serves files")
    ap.add_argument("--slug", action="append", default=[], help="a report slug to test (found by key if not given)")
    ap.add_argument("--out", help="write the protocol as markdown here")
    a = ap.parse_args()
    site, p = Site(a.base), Protocol()
    key = os.environ.get("AR_CHECK_KEY", "").strip()
    started = datetime.datetime.now(datetime.timezone.utc)

    # --- what the site is ---
    s, h, b = site.req("GET", "/health")
    try:
        version = json.loads(b).get("version", "?")
    except ValueError:
        version = "?"
    p.check("Public", "/health answers without signing in", s == 200, f"{s}")

    # --- real content to probe, found with a valid key (positive control) ---
    slugs, files = list(a.slug), []
    if key:
        s, h, b = site.mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, key)
        p.check("Agents", "a key from MCP_KEYS is accepted (positive control)", s == 200, f"{s}")
        s, h, b = site.mcp({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                            "params": {"name": "list_reports", "arguments": {"include_archived": True}}}, key)
        try:
            reports = json.loads(b)["result"]["structuredContent"]["reports"]
            slugs = slugs or [r["slug"] for r in reports][:5]
        except (ValueError, KeyError, TypeError):
            reports = []
        for slug in slugs[:3]:
            s, h, b = site.mcp({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                "params": {"name": "read_report", "arguments": {"slug": slug}}}, key)
            try:
                content = json.loads(b)["result"]["structuredContent"]["content"]
            except (ValueError, KeyError, TypeError):
                continue
            files += re.findall(re.escape(a.files_route) + r"/[^\"'<>\s?#]+", content)
        files = sorted(set(files))[:3]
    if not slugs:
        slugs = ["report"]  # a made-up slug still has to lead to the sign-in page, not to a 404 or a page

    # --- 1. the only things that answer without signing in ---
    public = ["/login", "/robots.txt", "/favicon.svg", "/favicon.ico", "/apple-touch-icon.png",
              "/static/app.css", "/static/app.js", "/static/theme.js", "/static/brand.css"]
    for path in public:
        s, h, b = site.req("GET", path)
        p.check("Public", f"{path} is public (an asset or the sign-in page)", s in (200, 404), f"{s}")
    s, h, b = site.req("GET", "/login")
    p.check("Public", "the sign-in page sets no session", "ar_session" not in h.get("set-cookie", ""), "")
    p.check("Public", "the sign-in page may not be framed", "frame-ancestors 'none'" in h.get("content-security-policy", ""),
            h.get("content-security-policy", "")[:60])
    p.check("Public", "the sign-in page leaks no report data", b'"reports"' not in b and b"publish_report" not in b, "")

    # --- 2. nothing else without signing in ---
    protected = ["/", "/index.html", "/api/reports", "/api/system/version", "/brand", "/r/x", "/r/x/info", "/r/x/v/1", "/x", "/x.html", "/x.md",
                 a.files_route + "/", a.files_route + "/x.pdf"]
    for slug in slugs:
        protected += [f"/{slug}.html", f"/{slug}.md", f"/{slug}", f"/r/{slug}", f"/r/{slug}/info", f"/r/{slug}/v/1",
                      f"/r/{slug}/v/1/data/data.csv"]
    protected += files
    for path in dict.fromkeys(protected):
        s, h, b = site.req("GET", path)
        p.check("No sign-in", f"GET {path} leads to the sign-in page", to_login(s, h), f"{s} {h.get('location', '')}")
        s2, h2, b2 = site.req("HEAD", path)
        p.check("No sign-in", f"HEAD {path} leads to the sign-in page", to_login(s2, h2), f"{s2}")
    for path in ("/x/../" + (slugs[0] + ".html"), "/%2e%2e/" + slugs[0] + ".html", a.files_route + "/../../etc/passwd",
                 a.files_route + "/%2e%2e/%2e%2e/etc/passwd", "//" + slugs[0] + ".html"):
        s, h, b = site.req("GET", path)
        # Refused (400/404, also by a proxy in front) or sent to sign in; never a page.
        p.check("No sign-in", f"odd path {path} gives no content", s in (400, 404) or to_login(s, h), f"{s}")

    # --- 3. forged and stale sessions ---
    now = int(time.time())
    forged = [f"{now + 86400}.{secrets.token_hex(32)}", f"{now - 10}.{'0' * 64}", "123.abc", "x", "",
              f"{now + 86400}", f"{now + 86400}.", "../../etc/passwd", f"{now + 86400}.{secrets.token_hex(32)}; ar_session=y"]
    for value in forged:
        s, h, b = site.req("GET", "/api/reports", headers={"Cookie": f"ar_session={value}"})
        p.check("Sessions", f"forged session {value[:24]!r} is refused", to_login(s, h), f"{s}")

    # --- 4. browser actions need a session and the site's own page ---
    actions = [f"/api/reports/{slugs[0]}/archive", f"/api/reports/{slugs[0]}/unarchive",
               f"/api/reports/{slugs[0]}/restore", f"/api/reports/{slugs[0]}/details",
               f"/api/reports/{slugs[0]}/unlock", "/api/brand/restore", "/api/system/update"]
    for path in actions:
        for label, headers in (("no session", {}),
                               ("forged session", {"Cookie": f"ar_session={now + 86400}.{secrets.token_hex(32)}"}),
                               ("an agent key instead of a session", {"Authorization": f"Bearer {key or secrets.token_hex(32)}"})):
            s, h, b = site.req("POST", path, b"{}", {"Content-Type": "application/json",
                                                     "X-Requested-With": "agentreports", **headers})
            p.check("Actions", f"POST {path} with {label} is refused", s in (401, 403), f"{s}")
    s, h, b = site.req("POST", "/login", urllib.parse.urlencode({"password": "", "next": "/"}).encode(),
                       {"Content-Type": "application/x-www-form-urlencoded"})
    p.check("Sign-in", "an empty password is refused and sets no session",
            s in (401, 429) and "ar_session=" not in h.get("set-cookie", "").replace("ar_session=;", ""), f"{s}")

    # --- 5. agents: only the keys in MCP_KEYS ---
    hello = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    attempts = [("no Authorization header", None, "Bearer"), ("an empty key", "", "Bearer"),
                ("a random 64-character key", secrets.token_hex(32), "Bearer"),
                ("a random 32-character key", secrets.token_hex(16), "Bearer"),
                ("Basic instead of Bearer", secrets.token_hex(32), "Basic"),
                ("a quoted key", '"' + secrets.token_hex(32) + '"', "Bearer")]
    if key:
        attempts += [("the valid key with one character changed", key[:-1] + ("0" if key[-1] != "0" else "1"), "Bearer"),
                     ("the valid key cut short", key[:-8], "Bearer"),
                     ("the valid key with something added", key + "a", "Bearer"),
                     ("the valid key in upper case", key.upper() if key.upper() != key else key.lower(), "Bearer"),
                     ("the valid key as Basic", key, "Basic"),
                     ("the key name instead of the key", "hermes", "Bearer")]
    for label, k, scheme in attempts:
        s, h, b = site.mcp(hello, k, scheme)
        p.check("Agents", f"MCP with {label} is refused", s == 401 and b"publish_report" not in b, f"{s}")
    s, h, b = site.mcp([hello, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                "params": {"name": "list_reports", "arguments": {}}}], None)
    p.check("Agents", "an MCP batch without a key is refused", s == 401, f"{s}")
    s, h, b = site.req("GET", "/mcp", headers={"Authorization": f"Bearer {key or secrets.token_hex(32)}"})
    p.check("Agents", "GET /mcp gives nothing", s in (401, 405) and b"publish_report" not in b, f"{s}")
    s, h, b = site.req("GET", "/mcp?" + urllib.parse.urlencode({"key": key or "x"}))
    p.check("Agents", "a key in the URL is not accepted", s in (401, 405), f"{s}")

    # --- 6. other methods ---
    for method in ("PUT", "DELETE", "PATCH"):
        s, h, b = site.req(method, f"/{slugs[0]}.html", b"x")
        p.check("Methods", f"{method} /{slugs[0]}.html changes nothing", s >= 400, f"{s}")

    # --- protocol ---
    lines = [f"# Security check: {site.base}", "",
             f"- When: {started.strftime('%Y-%m-%d %H:%M UTC')}",
             f"- Version: {version}",
             f"- Checks: {len(p.rows)}, passed {len(p.rows) - len(p.failed)}, failed {len(p.failed)}",
             f"- With a valid agent key as positive control: {'yes' if key else 'no'}",
             f"- Report slugs probed: {', '.join(slugs)}; source files probed: {len(files)}",
             f"- Result: **{'PASS' if not p.failed else 'FAIL'}**", "",
             "| Group | Check | Result | Detail |", "|---|---|---|---|"]
    for group, name, ok, detail in p.rows:
        lines.append(f"| {group} | {name.replace('|', '/')} | {'PASS' if ok else '**FAIL**'} | "
                     f"{'' if ok else detail.replace('|', '/')} |")
    text = "\n".join(lines) + "\n"
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(f"\n{len(p.rows)} checks, {len(p.failed)} failed — {'PASS' if not p.failed else 'FAIL'}")
    return 0 if not p.failed else 1


if __name__ == "__main__":
    sys.exit(main())
