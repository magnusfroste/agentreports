"""End-to-end: start the server on a free port with a temporary data folder and use it like an agent
and a person would. Standard library only:  python -m unittest discover -s tests"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
PASSWORD = "correct horse battery staple 42"
KEY = "k" * 40
KEY2 = "q" * 40


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.files = os.path.join(cls.tmp.name, "files")
        os.makedirs(os.path.join(cls.files, "sub"))
        os.makedirs(os.path.join(cls.tmp.name, "brand"))
        for path, data in (("files/sub/a.pdf", b"%PDF-1.4 test"), ("files/page.html", b"<script>alert(1)</script>"),
                           ("files/.secret", b"no"), ("outside.txt", b"no"),
                           ("brand/logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg" id="brandlogo"/>'),
                           ("brand/brand.json", b'{"accent": "#7a1fa2", "accent_dark": "red"}')):
            with open(os.path.join(cls.tmp.name, path), "wb") as f:
                f.write(data)
        cls.port = free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        env = {**os.environ, "DATA_DIR": os.path.join(cls.tmp.name, "data"), "PORT": str(cls.port),
               "REPORTS_PASSWORD": PASSWORD, "MCP_KEYS": f"hermes:{KEY},laptop:{KEY2},short:abc",
               "FILES_DIR": cls.files, "FILES_ROUTE": "/sources", "BRAND_DIR": os.path.join(cls.tmp.name, "brand"), "AGENT_NAMES": "hermes=Hermes,laptop=Ana Lind", "REPORTS_LANG": "sv", "SITE_TITLE": "Test & Co",
               "PYTHONDONTWRITEBYTECODE": "1"}
        cls.proc = subprocess.Popen([sys.executable, "server.py"], cwd=APP, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        for _ in range(50):
            try:
                urllib.request.urlopen(cls.base + "/health", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        cls.opener = urllib.request.build_opener(NoRedirect)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.tmp.cleanup()

    # --- helpers ---

    def req(self, path, data=None, headers=None, method=None, cookie=None):
        h = dict(headers or {})
        if cookie:
            h["Cookie"] = cookie
        r = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            resp = self.opener.open(r, timeout=10)
        except urllib.error.HTTPError as e:
            resp = e
        return resp.status if hasattr(resp, "status") else resp.code, dict(resp.headers), resp.read()

    def mcp(self, method, params=None, key=KEY):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode()
        code, _, out = self.req("/mcp", body, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        self.assertEqual(code, 200, out)
        return json.loads(out)["result"]

    def tool(self, name, key=KEY, **args):
        r = self.mcp("tools/call", {"name": name, "arguments": args}, key)
        return r if r["isError"] else r["structuredContent"]

    def login(self, ip=None):
        h = {"Content-Type": "application/x-www-form-urlencoded"}
        code, headers, _ = self.req("/login", urllib.parse.urlencode({"password": PASSWORD, "next": "/"}).encode(), h)
        self.assertEqual(code, 303)
        return headers["Set-Cookie"].split(";")[0]

    # --- tests ---

    def test_01_people_must_sign_in(self):
        for path in ("/", "/x.html", "/r/x", "/api/reports", "/sources/sub/a.pdf"):
            code, h, _ = self.req(path)
            self.assertEqual(code, 303, path)
            self.assertTrue(h["Location"].startswith("/login?next="), path)
        self.assertEqual(self.req("/favicon.svg")[0], 200)
        self.assertEqual(self.req("/health")[0], 200)
        code, _, body = self.req("/login")
        self.assertEqual(code, 200)
        self.assertIn(b"Test &amp; Co", body)

    def test_02_agents_need_a_key(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
        self.assertEqual(self.req("/mcp", body, {"Content-Type": "application/json"})[0], 401)
        self.assertEqual(self.req("/mcp", body, {"Authorization": "Bearer abc"})[0], 401)  # too short, ignored
        self.assertEqual(self.req("/mcp", body, {"Authorization": "Bearer " + "z" * 40})[0], 401)
        tools = [t["name"] for t in self.mcp("tools/list")["tools"]]
        self.assertEqual(tools, ["publish_report", "report_style", "update_report_details", "list_reports",
                                 "read_report", "report_versions", "get_brand", "update_brand", "restore_brand"])
        self.assertFalse(any("delete" in t or "archive" in t for t in tools))
        init = self.mcp("initialize", {"protocolVersion": "2025-03-26"})
        self.assertEqual(init["protocolVersion"], "2025-03-26")
        self.assertIn("report.css", init["instructions"])

    def test_03_publish_versions_and_history(self):
        r = self.tool("publish_report", title="Overview — Q3 2026", content="<h1>v1</h1>",
                      description="Key figures", category="Finance", tags=["2026"])
        self.assertEqual(r["slug"], "overview-q3-2026")
        self.assertTrue(r["new_report"] and r["new_version"])
        self.assertEqual(r["version"], 1)
        r = self.tool("publish_report", slug="overview-q3-2026", title="Overview — Q3 2026",
                      content="<h1>v2</h1>", note="new figures", key=KEY2)
        self.assertEqual((r["version"], r["updated_by"], r["description"], r["category"]), (2, "laptop", "Key figures", "Finance"))
        same = self.tool("publish_report", slug="overview-q3-2026", title="Overview — Q3 2026", content="<h1>v2</h1>")
        self.assertFalse(same["new_version"])
        self.assertEqual(same["version"], 2)
        stale = self.tool("publish_report", slug="overview-q3-2026", title="x", content="<h1>v3</h1>", expected_version=1)
        self.assertTrue(stale["isError"])
        self.assertIn("version 2", stale["content"][0]["text"])
        vs = self.tool("report_versions", slug="overview-q3-2026")
        self.assertEqual([(v["version"], v["by"]) for v in vs["versions"]], [(2, "laptop"), (1, "hermes")])
        old = self.tool("read_report", slug="overview-q3-2026", version=1)
        self.assertEqual(old["content"], "<h1>v1</h1>")

    def test_04_bad_input_is_refused(self):
        for args in ({"title": "x", "content": "a", "slug": "index"}, {"title": "x", "content": "a", "slug": "../etc"},
                     {"title": "x", "content": "a", "slug": "mcp"}, {"title": "x", "content": "a", "slug": "sources"}, {"title": "x", "content": "  "},
                     {"content": "a", "slug": "no-title"}, {"title": "x", "content": "a", "format": "pdf"}):
            r = self.tool("publish_report", **args)
            self.assertTrue(r["isError"], args)

    def test_05_start_page_lists_and_reports_are_sandboxed(self):
        self.tool("publish_report", title="Customer letter", slug="letter", content="<p>hello</p>", category="Customers")
        self.tool("publish_report", title="Notes", slug="notes", content="# Heading\n\ntext", format="markdown")
        c = self.login()
        code, h, body = self.req("/", cookie=c)
        self.assertEqual(code, 200)
        self.assertIn("script-src 'self'", h["Content-Security-Policy"])
        data = json.loads(body.split(b'id="data">')[1].split(b"</script>")[0])
        slugs = {r["slug"] for r in data["reports"]}
        self.assertTrue({"letter", "notes", "overview-q3-2026"} <= slugs)
        code, h, body = self.req("/letter.html", cookie=c)
        self.assertEqual((code, body), (200, b"<p>hello</p>"))
        self.assertTrue(h["Content-Security-Policy"].startswith("sandbox"))
        self.assertNotIn("allow-same-origin", h["Content-Security-Policy"])
        code, h, body = self.req("/notes.html", cookie=c)
        self.assertIn(b"marked.min.js", body)
        self.assertIn("sandbox", h["Content-Security-Policy"])
        self.assertEqual(self.req("/letter", cookie=c)[1]["Location"], "/letter.html")
        self.assertEqual(self.req("/letter.md", cookie=c)[1]["Location"], "/letter.html")
        self.assertEqual(self.req("/index.html", cookie=c)[1]["Location"], "/")
        self.assertEqual(self.req("/nope.html", cookie=c)[0], 404)
        code, _, body = self.req("/r/overview-q3-2026", cookie=c)
        self.assertEqual(code, 200)
        self.assertIn(b"new figures", body)
        self.assertEqual(self.req("/r/overview-q3-2026/v/1", cookie=c)[2], b"<h1>v1</h1>")

    def test_06_only_people_archive_and_restore(self):
        c = self.login()
        url = "/api/reports/letter/archive"
        self.assertEqual(self.req(url, b"{}", {"X-Requested-With": "agentreports"}, "POST")[0], 401)
        self.assertEqual(self.req(url, b"{}", {}, "POST", cookie=c)[0], 403)  # no header: not from our page
        self.assertEqual(self.req(url, b"{}", {"X-Requested-With": "agentreports", "Origin": "https://evil.example"},
                                  "POST", cookie=c)[0], 403)
        self.assertEqual(self.req(url, b"{}", {"Authorization": f"Bearer {KEY}", "X-Requested-With": "agentreports"},
                                  "POST")[0], 401)  # an agent key is not a session
        code, _, body = self.req(url, b"{}", {"X-Requested-With": "agentreports"}, "POST", cookie=c)
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["archived"])
        listed = self.tool("list_reports")
        self.assertNotIn("letter", [r["slug"] for r in listed["reports"]])
        self.assertIn("letter", [r["slug"] for r in self.tool("list_reports", include_archived=True)["reports"]])
        self.assertEqual(self.req("/letter.html", cookie=c)[0], 200)  # archived, still readable
        again = self.tool("publish_report", slug="letter", title="Customer letter", content="<p>new</p>")
        self.assertTrue(again["archived"])  # an agent can not bring it back to the start page either
        code, _, body = self.req("/api/reports/overview-q3-2026/restore", json.dumps({"version": 1}).encode(),
                                 {"X-Requested-With": "agentreports"}, "POST", cookie=c)
        self.assertEqual(json.loads(body)["version"], 3)
        self.assertEqual(self.tool("read_report", slug="overview-q3-2026")["content"], "<h1>v1</h1>")

    def test_07_files_are_served_safely(self):
        c = self.login()
        code, h, body = self.req("/sources/sub/a.pdf", cookie=c)
        self.assertEqual((code, h["Content-Type"], body), (200, "application/pdf", b"%PDF-1.4 test"))
        code, h, _ = self.req("/sources/page.html", cookie=c)
        self.assertEqual((code, h["Content-Type"]), (200, "text/plain; charset=utf-8"))
        self.assertEqual(h["Content-Security-Policy"], "sandbox")
        for bad in ("/sources/.secret", "/sources/../outside.txt", "/sources/%2e%2e/outside.txt", "/sources/sub", "/sources/"):
            self.assertEqual(self.req(bad, cookie=c)[0], 404, bad)

    def test_08_details_tool_and_categories(self):
        r = self.tool("update_report_details", slug="notes", category="Operations", description="Short")
        self.assertEqual((r["category"], r["description"], r["version"]), ("Operations", "Short", 1))
        cats = self.tool("list_reports")["categories"]
        self.assertIn("Operations", cats)
        self.assertTrue(self.tool("update_report_details", slug="missing", title="x")["isError"])

    def test_08a_who(self):
        r = self.tool("publish_report", slug="requested", title="Requested", content="<p>1</p>", requested_by="Sam  Berg")
        self.assertEqual((r["created_by"], r["created_for"], r["created_by_text"]), ("hermes", "Sam Berg", "Sam Berg via Hermes"))
        r = self.tool("publish_report", slug="requested", title="Requested", content="<p>2</p>", key=KEY2)
        self.assertEqual((r["updated_by_text"], r["created_by_text"]), ("Ana Lind", "Sam Berg via Hermes"))
        vs = self.tool("report_versions", slug="requested")["versions"]
        self.assertEqual([(v["by"], v["requested_by"]) for v in vs], [("laptop", None), ("hermes", "Sam Berg")])
        code, _, body = self.req("/r/requested", cookie=self.login())
        self.assertIn(b"Sam Berg via Hermes", body)

    def test_08b_brand(self):
        code, h, body = self.req("/logo.svg")
        self.assertEqual((code, h["Content-Type"]), (200, "image/svg+xml"))
        self.assertIn(b"brandlogo", body)
        self.assertIn(b"brandlogo", self.req("/favicon.svg")[2])  # no favicon.svg given: the logo is the icon
        self.assertEqual(self.req("/logo.png")[0], 303)  # not provided, so not a public file
        css = self.req("/static/brand.css")[2].decode()
        self.assertIn("--accent: #7a1fa2", css)
        self.assertIn("--accent-ink: #ffffff", css)
        self.assertNotIn("red", css)  # not a colour like #rrggbb: the light accent is used in dark mode too
        self.assertIn(b'src="/logo.svg?v=', self.req("/login")[2])

    def test_08c_report_style(self):
        st = self.tool("report_style")
        self.assertIn('href="/static/report.css"', st["stylesheet"])
        self.assertIn("r-kpis", st["skeleton"])
        self.assertIn("r-table-wrap > table.r-table", st["classes"])
        code, h, css = self.req("/static/report.css")
        self.assertEqual(code, 200)  # public: a sandboxed report loads it without the session
        self.assertIn(b".r-kpi", css)
        self.assertIn(b"--accent: #7a1fa2", css)  # the brand comes after the defaults
        self.assertLess(css.index(b".r-kpi"), css.index(b"--accent: #7a1fa2"))

    def test_08d_agents_change_the_look_and_people_roll_it_back(self):
        import base64
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 64).decode()
        r = self.tool("update_brand", note="green", settings={"accent": "#1f7a3a", "radius": 2},
                      files=[{"name": "logo.png", "base64": png}])
        self.assertEqual((r["version"], r["by"], r["settings"], r["files"]), (1, "hermes", ["accent", "radius"], ["logo.png"]))
        css = self.req("/static/brand.css")[2].decode()
        self.assertIn("--accent: #1f7a3a", css)  # live, no restart
        self.assertIn("--radius: 2px", css)
        self.assertIn(b"brandlogo", self.req("/logo.svg")[2])  # the site's own file is still there
        self.assertEqual(self.req("/logo.png")[2][:4], b"\x89PNG")
        code, h, _ = self.req("/logo.svg")
        self.assertIn("sandbox", h["Content-Security-Policy"])  # a brand SVG is shown, never run
        g = self.tool("get_brand")
        self.assertEqual((g["version"], g["agent_layer"]["accent"], g["settings"]["accent"]), (1, "#1f7a3a", "#1f7a3a"))
        # refused: unknown keys, bad colours, scripts in an SVG, files that are not what they say, private addresses
        for args in ({"settings": {"site_title": "x"}}, {"settings": {"accent": "green"}},
                     {"files": [{"name": "logo.svg", "base64": base64.b64encode(b'<svg onload="alert(1)"/>').decode()}]},
                     {"files": [{"name": "logo.svg", "base64": base64.b64encode(b'<svg><image href="https://x.example/a.png"/></svg>').decode()}]},
                     {"files": [{"name": "logo.png", "base64": base64.b64encode(b"GIF89a").decode()}]},
                     {"files": [{"name": "evil.js", "base64": "YQ=="}]},
                     {"files": [{"name": "logo.png", "url": "http://example.com/logo.png"}]},
                     {"files": [{"name": "logo.png", "url": "https://127.0.0.1/logo.png"}]},
                     {"files": [{"name": "logo.png", "url": "https://localhost/logo.png"}]},
                     {"settings": {"fonts": [{"family": "X", "file": "missing.woff2"}]}}):
            r = self.tool("update_brand", note="bad", **args)
            self.assertTrue(r["isError"], args)
        self.assertEqual(self.tool("get_brand")["version"], 1)  # nothing refused became a version
        r = self.tool("update_brand", note="purple again", settings={"accent": None}, key=KEY2)
        self.assertEqual(r["version"], 2)
        self.assertIn("--accent: #7a1fa2", self.req("/static/brand.css")[2].decode())  # the site's own accent again
        # a person rolls back in the browser
        c = self.login()
        code, _, body = self.req("/brand", cookie=c)
        self.assertEqual(code, 200)
        self.assertIn(b"purple again", body)
        self.assertEqual(self.req("/api/brand/restore", b'{"version": 0}', {}, "POST", cookie=c)[0], 403)
        code, _, body = self.req("/api/brand/restore", b'{"version": 1}', {"X-Requested-With": "agentreports"}, "POST", cookie=c)
        self.assertEqual((code, json.loads(body)["version"]), (200, 3))
        self.assertIn("--accent: #1f7a3a", self.req("/static/brand.css")[2].decode())
        r = self.tool("restore_brand", version=0)
        self.assertEqual(r["version"], 4)
        self.assertEqual(self.req("/logo.png")[0], 303)  # the agent's file is gone from the live site
        self.assertEqual([h["version"] for h in self.tool("get_brand")["history"]], [4, 3, 2, 1])

    def test_09_wrong_passwords_lock_out(self):
        h = {"Content-Type": "application/x-www-form-urlencoded", "X-Forwarded-For": "ignored"}
        codes = [self.req("/login", b"password=nope", h)[0] for _ in range(10)]
        self.assertEqual(set(codes), {401})
        self.assertEqual(self.req("/login", b"password=nope", h)[0], 429)
        body = urllib.parse.urlencode({"password": PASSWORD}).encode()
        self.assertEqual(self.req("/login", body, h)[0], 429)  # even the right one, while locked
        self.assertEqual(self.req("/", cookie="ar_session=123.abc")[0], 303)  # forged cookie

    def test_00_next_must_stay_on_this_site(self):
        h = {"Content-Type": "application/x-www-form-urlencoded"}
        for nxt, where in (("//evil.example", "/"), ("https://evil.example", "/"), ("/r/x", "/r/x")):
            body = urllib.parse.urlencode({"password": PASSWORD, "next": nxt}).encode()
            self.assertEqual(self.req("/login", body, h)[1]["Location"], where, nxt)

if __name__ == "__main__":
    unittest.main()
