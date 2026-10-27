# AgentReports

**Your agents publish reports over MCP. Your people read them behind a password.**

*A companion to [AgentHotel](https://github.com/magnusfroste/agenthotel), like [AgentTake](https://github.com/magnusfroste/agenttake); it runs anywhere on its own.*

An agent that has worked something out — a month's costs, a reconciliation, an incident write-up — should be able to hand it to a person as a page they can open, not as a wall of chat. AgentReports is that page: one MCP call, and the report is on a start page with a title, a description and a category, next to everything else the agents have published.

```
agent ── publish_report ──► AgentReports ──► start page: cards, categories, search
                               │
                               └── every publish is a version; nothing is ever overwritten
```

## Agents can add, never take away

The start page used to be something an agent wrote, and an agent could rewrite it — and a report would quietly stop being listed. Here the line is drawn in the server, not in a prompt:

| Agents (MCP key) | People (password) |
|---|---|
| publish a report, or a new version of one | read every report and every version |
| change a report's title, description, category, tags | archive a report (hide it from the start page) and bring it back |
| list and read reports and their versions | restore an old version |
| — | — nobody deletes over the web; a report is a folder on disk |

- **The start page is generated** from each report's title, description and category. No agent writes it.
- **Every publish is a version.** Publishing the same slug again keeps the old one; a person can view any version and restore it (which publishes it again as the newest, so even a restore loses nothing). Publishing identical content adds no version.
- **Stale writes are refused** when the agent says which version it built on (`expected_version`), so two agents editing the same report don't silently undo each other.
- **Reports run in a sandbox.** A report is HTML an agent wrote, so it is served with `Content-Security-Policy: sandbox`: its scripts, charts and filters work, but it has no access to the reader's session and cannot archive, restore or read anything on their behalf.
- **One key per agent installation** (`MCP_KEYS=hermes:…,laptop:…`). Every version records who published it; one key can be revoked without touching the others.
- **Who asked, when an agent is shared.** An agent several people talk to can pass `requested_by`; the card then says *Ana Lind via Hermes*. That part is the agent's word, so it is always shown next to the key's name, never instead of it.

## The app

A panel on the left lists the reports by category, newest first, with search and the reports you pinned on top; the archive, the look and the theme switch (system, light, dark) sit at its foot. On the right is the overview — cards or a list, filter by category, search (`/` to focus), sort by updated, newest, title or category — or one report. Click a report and it opens next to the panel, so switching between them is one click; the address becomes `/r/<slug>`, which is the link to share. A bar above the report pins it, opens it bare in a new tab (`/<slug>.html`, also for printing), shows its versions and copies its link. On a phone the panel slides in from the left.

A report shown in the app tells the app which one it is, so a link from one report to another, or back to the start page, moves the app rather than nesting the site inside the frame; and it follows the theme picked in the panel (in Chromium-based browsers; others follow the system setting).

## Run it

```bash
git clone https://github.com/magnusfroste/agentreports.git && cd agentreports
cp .env.example .env    # set REPORTS_PASSWORD (20+ chars) and MCP_KEYS
docker compose up -d --build
```

Open `http://localhost:8000`, sign in, and give your agent the MCP endpoint `http://<host>:8000/mcp` with its key as a bearer token. One Python process, standard library only, no database: back it up by copying the data volume.

### Hermes

```yaml
# ~/.hermes/config.yaml — values from ~/.hermes/.env
mcp_servers:
  reports:
    url: ${REPORTS_MCP_URL}
    headers:
      Authorization: "Bearer ${REPORTS_MCP_KEY}"
```

## Tools

| Tool | What it does |
|---|---|
| `publish_report` | `title`, `content` (a full HTML page, or markdown with `format: markdown`), `description`, `category`, `tags`, `slug`, `note`, `expected_version`, `requested_by`. Returns the link and version. |
| `update_report_details` | Change title, description, category or tags without new content. |
| `report_style` | How reports should look here: the stylesheet, its classes, a page skeleton. |
| `get_brand`, `update_brand`, `restore_brand` | The site's look: read it, change it as a new version, or go back. |
| `list_reports` | Reports with their details and links, and the categories in use (so agents reuse them). |
| `read_report` | A report's content, current or an older `version`, to build on. |
| `report_versions` | Every version: when, by whom, the note, a link. |

Reports link to each other with relative links (`other-report.html`), so a set of pages works as one site, inside the app or on their own. The link agents get back is the app address, `/r/<slug>`.

## Configuration

| Variable | |
|---|---|
| `REPORTS_PASSWORD` | Required, 20+ characters. Ten wrong attempts lock an address out for 15 minutes. |
| `MCP_KEYS` | `name:key,name:key`, keys 32+ characters (`openssl rand -hex 32`). The name is who published, on every version. |
| `AGENT_NAMES` | Optional names to show instead: `ana=Ana Lind,server=Hermes`. Give a person's new laptop a new key with the same shown name; revoke the old key. |
| `SITE_TITLE`, `SITE_SUBTITLE` | Heading of the start page. |
| `REPORTS_LANG` | `en` or `sv`. |
| `PUBLIC_URL` | The address people use, for the links agents get back; `https://` also marks the session cookie Secure. |
| `TRUSTED_PROXY_HEADER` | e.g. `CF-Connecting-IP` behind Cloudflare, or `X-Forwarded-For` behind Caddy (the last address in it is used), so the lockout sees the real address. Only set it when every request comes through that proxy. |
| `FILES_DIR`, `FILES_ROUTE` | Optional read-only folder served to signed-in readers under `FILES_ROUTE` (default `/files`), e.g. the source documents reports link to. PDFs and images are shown; anything that could run is served as text. |
| `BRAND_DIR` | Optional folder with your own logo, fonts and colours; see below. |
| `AGENT_BRANDING` | `on` (default) or `off`: may agents change the look over MCP (see below). |
| `UPDATE_CHECK` | `on` (default) or `off`: compare the running version with `app/VERSION` on GitHub (`UPDATE_REPO`, default `magnusfroste/agentreports`) every six hours and show people "New version" in the panel. |
| `DEPLOY_HOOK_URL` | Optional: the platform's deploy trigger (e.g. Easypanel's *Deployment Trigger*). People then get an "Update now" button that calls it and reloads when the new version is up. An app cannot rebuild itself — that would need the Docker socket, i.e. the whole host — but it can ask the platform. Agents cannot press it. |
| `MAX_REPORT_BYTES` | Default 10 MB. |

### Your logo, colours and fonts

Mount a folder and point `BRAND_DIR` at it. Whatever is in it replaces the default; anything missing stays as it was.

```
brand/
  logo.svg | logo.png            header and sign-in page; may be wide (a wordmark), shown 32 px high
  logo-dark.svg | logo-dark.png  the same for dark mode (e.g. a light wordmark)
  favicon.svg | favicon.png      browser tab; without one, logo.svg is used
  favicon.ico                    optional, older browsers
  apple-touch-icon.png           optional, 180×180, home screen
  *.woff2                        font files named in brand.json, served from this site
  brand.json
```

```json
{
  "accent": "#7A1FA2", "accent_text": "#5E1780", "accent_dark": "#C58AF0",
  "background": "#F5F3F7", "surface": "#FFFFFF", "surface_2": "#F0EDF3",
  "text": "#1B1620", "muted": "#1B1620A6", "faint": "#1B162073", "line": "#1B16201F", "line_strong": "#1B162038",
  "dark": { "background": "#121016", "surface": "#1B1620", "text": "#F3F0F6", "muted": "#F3F0F6B3", "line": "#FFFFFF1F" },
  "heading_font": "Fraunces", "body_font": "Inter", "heading_weight": 500, "heading_scale": 1.15,
  "radius": 4,
  "series": ["#7A1FA2", "#D08A2E", "#2E7D6B", "#B2456E", "#4D6FB3", "#8C8577"],
  "fonts": [
    { "family": "Inter", "file": "inter.woff2", "weight": "400 700" },
    { "family": "Fraunces", "file": "fraunces.woff2", "weight": "500" }
  ]
}
```

Every key is optional. Colours are `#rrggbb` or `#rrggbbaa`. `accent` colours buttons, the selected filter and focus rings; text on it turns dark or light by itself unless `accent_ink` says otherwise; `accent_text` is the accent as text on a light background. `dark` sets the dark-mode palette. A font entry may carry `style` (`italic`) and `unicode_range` for subset files. `radius` (0–24 px) sets how round cards and buttons are. `series` (up to six colours) are the chart and tag colours reports use (`var(--c1)`…). Category colours stay as they are, so cards remain easy to tell apart.

## Reports that look like the site

With `REPORT_STYLE=on` (the default) agents are told, in the MCP instructions and by the tool `report_style`, to link `/static/report.css` and build reports from its `r-*` classes: header, page navigation, key figures, notes, tags, filters, tables with sticky headers, bars, legends and a sources footer, for screen, phone, dark mode and A4 print. The stylesheet carries the brand, so reports look like the start page — and follow it when the brand changes, even old ones. `REPORT_STYLE=off` removes the tool, the instruction and the stylesheet; agents then style reports as they like.

## Agents can change the look, too

With `AGENT_BRANDING=on` (the default) an agent can be asked to *"take the look from example.com"*: `get_brand` shows the current logo, fonts, colours and history; `update_brand` changes them in one call that becomes one version; `restore_brand` goes back (version 0 is the base look). It is a layer over `BRAND_DIR`, never a replacement, and people see the history at `/brand` and roll back from there.

What keeps it safe without a key of its own:

- Only the `brand.json` settings above can be set, each validated; anything else is refused.
- Files are checked by content (a PNG must be a PNG, a font a WOFF2), with size limits. SVGs with scripts, event handlers, external links or embedded documents are refused, and brand SVGs are served sandboxed.
- Files can be given as URLs, so a 100 kB font does not pass through the model: fetched over https only, from public addresses only (no private, loopback or link-local IPs, also after redirects), with a size cap and a timeout.
- Every change and every restore is a new version with who and why; nothing is overwritten.

`AGENT_BRANDING=off` removes the tools and ignores the agent layer.

## Bring existing reports

A folder of HTML files an agent has been writing keeps its addresses: `report.html` becomes the report `report`, still at `/report.html`.

```bash
docker compose exec reports python server.py import /import --by hermes --details details.json
```

`details.json` optionally sets title, description, category and tags per file: `{"report": {"category": "Finance", "description": "…"}}`. Running it again adds nothing that is already there.

## Storage

```
/data/reports/<slug>/meta.json    title, description, category, tags, current version, archived
/data/reports/<slug>/v0001.html   content of each version (.md for markdown)
/data/reports/<slug>/v0001.json   who, when, note, size, checksum
```

## Security check

`tools/security_check.py` checks a running site from the outside, as a stranger would: only the sign-in page and public assets answer without signing in; pages, reports, versions, details, the API, the look page and served files lead to the sign-in page (also for real reports and odd paths); forged sessions are refused; archive, restore and brand restore need a session from the site's own page; MCP takes only the keys in `MCP_KEYS` (no key, random keys, a changed, cut, extended or re-cased valid key, Basic, the key's name or a key in the URL are refused). It never tries passwords, so it locks nobody out.

```bash
AR_CHECK_KEY=<one key from MCP_KEYS> python3 tools/security_check.py https://reports.example.com --out protocol.md
```

The key (optional, read from the environment and never printed) adds a positive control and lets the check find real reports to probe. Exit code 1 when anything fails. Run it before and after changing sign-in or access, and keep the protocols.

## Development

```bash
python -m unittest discover -s tests    # starts the server and uses it as an agent and a person would
```

MIT licensed.
