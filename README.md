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

## The start page

Cards with a category colour, title, description, who updated it and when. Filter by category, search across title, description and tags (`/` to focus), sort by recently updated, newest, title or grouped by category. Archived reports appear behind a toggle. Light and dark follow the system; it works on a phone.

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
| `list_reports` | Reports with their details and links, and the categories in use (so agents reuse them). |
| `read_report` | A report's content, current or an older `version`, to build on. |
| `report_versions` | Every version: when, by whom, the note, a link. |

Reports link to each other with relative links (`other-report.html`), so a set of pages works as one site.

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
| `BRAND_DIR` | Optional folder with your own logo and colour; see below. |
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

## Development

```bash
python -m unittest discover -s tests    # starts the server and uses it as an agent and a person would
```

MIT licensed.
