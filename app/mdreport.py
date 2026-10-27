"""Markdown reports, rendered by the server in the site's report kit.

An agent writes a short markdown file instead of a whole HTML page: less to write, less to get wrong,
and the result always has the site's look. Plain markdown works as usual; a few blocks add what reports
need:

    ::kpis                         key figures, one per line: value | label | note
    - 3 752 294 kr | Total cost | +8 % on September
    ::

    ::note warn                    a highlighted remark (warn, bad, good or nothing)
    252 832 kr is missing from the books.
    ::

    ```chart bar                   bar, stacked, hbar, line or donut; CSV with a header row
    Month, Transport, Storage
    2026-09, 412000, 88000
    ```

    ::details Title                a section the reader can fold out
    ::sources                      the footer: what the report is built on

Everything is escaped; links may only be http(s), mailto, relative or #anchors. Standard library only.
"""
import csv
import html
import io
import json
import re

CHART_TYPES = ("bar", "stacked", "hbar", "line", "donut")
NOTE_KINDS = ("warn", "bad", "good")


class MarkdownError(ValueError):
    pass


def _esc(s):
    return html.escape(s, quote=True)


def _url(u):
    u = u.strip()
    if re.match(r"^(https?:|mailto:|#|/|\./|\.\./|[\w.-]+(\.html|\.md)?([?#].*)?$)", u, re.I) and not re.match(
            r"^\s*(javascript|data|vbscript):", u, re.I):
        return u
    return "#"


def inline(text):
    """Escape, then bold, italics, code and links."""
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{_esc(part[1:-1])}</code>")
            continue
        s = _esc(part)
        s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: f'<a href="{_esc(_url(html.unescape(m.group(2))))}">{m.group(1)}</a>', s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
        s = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"<em>\1</em>", s)
        out.append(s)
    return "".join(out)


NUMBER = re.compile(r"^[−-]?[\d\s  ]+([.,]\d+)?\s*(%|kr|sek|eur|€|\$|st|h|pall|pallar)?$", re.I)


def parse_number(s):
    t = s.strip().replace(" ", "").replace(" ", "").replace(" ", "").replace("−", "-")
    t = re.sub(r"(?i)(%|kr|sek|eur|€|\$|st|h|pallar|pall)$", "", t)
    if re.fullmatch(r"-?\d+,\d+", t):
        t = t.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", t):
        t = t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def chart(kind, args, body):
    if kind not in CHART_TYPES:
        raise MarkdownError(f"chart: type must be one of {', '.join(CHART_TYPES)}, not {kind!r}")
    rows = [r for r in csv.reader(io.StringIO(body.strip()), skipinitialspace=True) if any(c.strip() for c in r)]
    if len(rows) < 2 or len(rows[0]) < 2:
        raise MarkdownError("chart: a header row and at least one data row, like 'Month, Cost' then '2026-09, 412000'")
    header, data = rows[0], rows[1:]
    labels, series = [], [{"name": h.strip(), "values": []} for h in header[1:]]
    for n, r in enumerate(data, 2):
        if len(r) != len(header):
            raise MarkdownError(f"chart: row {n} has {len(r)} values, the header has {len(header)}")
        labels.append(r[0].strip())
        for s, cell in zip(series, r[1:]):
            v = parse_number(cell)
            if v is None and cell.strip():
                raise MarkdownError(f"chart: row {n}: {cell.strip()!r} is not a number")
            s["values"].append(v)
    opts = dict(re.findall(r'(\w+)="([^"]*)"', args))
    spec = {"type": kind, "labels": labels, "series": series,
            "title": opts.get("title", ""), "unit": opts.get("unit", "")}
    data_json = json.dumps(spec, ensure_ascii=False).replace("</", "<\\/")
    title = f'<p class="r-chart-title">{_esc(spec["title"])}</p>' if spec["title"] else ""
    return (f'<figure class="r-chart-wrap">{title}<div class="r-chart" data-type="{kind}">'
            f'<script type="application/json">{data_json}</script></div></figure>')


def table(lines):
    def cells(line):
        line = line.strip()
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]
        return [c.strip() for c in re.split(r"(?<!\\)\|", line)]
    head, align, body = cells(lines[0]), cells(lines[1]), [cells(l) for l in lines[2:]]
    nums = []
    for i in range(len(head)):
        a = align[i] if i < len(align) else ""
        col = [r[i] for r in body if i < len(r) and r[i]]
        nums.append(a.endswith(":") and not a.startswith(":") or (col and all(NUMBER.match(c) for c in col)))
    cls = lambda i: ' class="num"' if i < len(nums) and nums[i] else ""
    out = ['<div class="r-table-wrap"><table class="r-table"><thead><tr>']
    out += [f"<th{cls(i)}>{inline(h)}</th>" for i, h in enumerate(head)]
    out.append("</tr></thead><tbody>")
    for r in body:
        total = r and re.match(r"^\*\*.*\*\*$", r[0] or "")
        out.append(f'<tr{" class=\"r-total\"" if total else ""}>')
        out += [f"<td{cls(i)}>{inline(r[i]) if i < len(r) else ''}</td>" for i in range(len(head))]
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def render_blocks(lines):
    """Markdown lines to HTML."""
    out, i, para, lead_next = [], 0, [], False

    def flush():
        nonlocal para, lead_next
        if para:
            text = " ".join(l.strip() for l in para)
            out.append(f'<p class="r-lead">{inline(text)}</p>' if lead_next else f"<p>{inline(text)}</p>")
            para, lead_next = [], False

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            flush(); i += 1; continue
        m = re.match(r"^```\s*(\w+)?\s*(\w+)?(.*)$", s)
        if m:
            flush()
            lead_next = False
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            if j >= len(lines):
                raise MarkdownError(f"line {i + 1}: a ``` block is not closed")
            body = "\n".join(lines[i + 1:j])
            if m.group(1) == "chart":
                try:
                    out.append(chart(m.group(2) or "bar", m.group(3) or "", body))
                except MarkdownError as e:
                    raise MarkdownError(f"line {i + 1}: {e}")
            else:
                out.append(f"<pre><code>{_esc(body)}</code></pre>")
            i = j + 1
            continue
        m = re.match(r"^::(\w+)\s*(.*)$", s)
        if m and m.group(1) != "":
            flush()
            lead_next = False
            name, arg = m.group(1), m.group(2).strip()
            j, depth = i + 1, 0
            while j < len(lines):
                t = lines[j].strip()
                if re.match(r"^::\w+", t):
                    depth += 1
                elif t == "::":
                    if depth == 0:
                        break
                    depth -= 1
                j += 1
            if j >= len(lines):
                raise MarkdownError(f"line {i + 1}: ::{name} is not closed with a line '::'")
            inner = lines[i + 1:j]
            if name == "kpis":
                items = []
                for k in inner:
                    k = re.sub(r"^[-*]\s+", "", k.strip())
                    if not k:
                        continue
                    p = [x.strip() for x in k.split("|")]
                    note = p[2] if len(p) > 2 else ""
                    trend = " r-up" if note.startswith("+") else " r-down" if note.startswith(("−", "-")) else ""
                    items.append(f'<div class="r-kpi"><div class="r-kpi-value">{inline(p[0])}</div>'
                                 f'<div class="r-kpi-label">{inline(p[1]) if len(p) > 1 else ""}</div>'
                                 + (f'<div class="r-kpi-note{trend}">{inline(note)}</div>' if note else "") + "</div>")
                out.append(f'<div class="r-kpis">{"".join(items)}</div>')
            elif name == "note":
                kind = arg if arg in NOTE_KINDS else ""
                out.append(f'<div class="r-note{" " + kind if kind else ""}">{render_blocks(inner)}</div>')
            elif name == "details":
                out.append(f'<details class="r-details"><summary>{inline(arg or "…")}</summary>{render_blocks(inner)}</details>')
            elif name == "sources":
                out.append(f'<footer class="r-sources">{render_blocks(inner)}</footer>')
            elif name == "grid":
                out.append(f'<div class="r-grid">{render_blocks(inner)}</div>')
            elif name == "card":
                out.append(f'<div class="r-card">{render_blocks(inner)}</div>')
            else:
                raise MarkdownError(f"line {i + 1}: unknown block ::{name} (kpis, note, details, sources, grid, card)")
            i = j + 1
            continue
        m = re.match(r"^(#{1,4})\s+(.+)$", s)
        if m:
            flush()
            lead_next = False
            level = len(m.group(1))
            text = m.group(2).strip().rstrip("#").strip()
            if level == 1:
                out.append(f"<h1>{inline(text)}</h1>")
                lead_next = True
            else:
                anchor = re.sub(r"[^\w]+", "-", text.lower()).strip("-")
                out.append(f'<h{level} id="{_esc(anchor)}">{inline(text)}</h{level}>')
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            flush(); lead_next = False; out.append("<hr>"); i += 1; continue
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{2,}", lines[i + 1].strip()):
            flush()
            lead_next = False
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            out.append(table([l for l in lines[i:j]]))
            i = j
            continue
        if s.startswith(">"):
            flush()
            lead_next = False
            j = i
            while j < len(lines) and lines[j].strip().startswith(">"):
                j += 1
            out.append(f"<blockquote>{render_blocks([l.strip()[1:] for l in lines[i:j]])}</blockquote>")
            i = j
            continue
        m = re.match(r"^([-*+]|\d+[.)])\s+(.*)$", s)
        if m:
            flush()
            lead_next = False
            ordered = m.group(1)[0].isdigit()
            items, j = [], i
            while j < len(lines):
                mm = re.match(r"^\s*([-*+]|\d+[.)])\s+(.*)$", lines[j])
                if mm:
                    items.append(mm.group(2)); j += 1
                elif lines[j].startswith(("  ", "\t")) and lines[j].strip() and items:
                    items[-1] += " " + lines[j].strip(); j += 1
                else:
                    break
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(t)}</li>" for t in items) + f"</{tag}>")
            i = j
            continue
        para.append(line)
        i += 1
    flush()
    return "".join(out)


def title_of(text):
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else None


def render(text, title="", category="", lang="en"):
    """A complete report page from markdown, in the site's report kit."""
    body = render_blocks(text.replace("\r\n", "\n").split("\n"))
    eyebrow = f'<p class="r-eyebrow">{_esc(category)}</p>' if category else ""
    if "<h1>" not in body and title:
        body = f"<h1>{_esc(title)}</h1>" + body
    return (f'<!doctype html><html lang="{_esc(lang)}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_esc(title)}</title>'
            f'<link rel="stylesheet" href="/static/report.css"><script src="/static/report.js" defer></script>'
            f'</head><body><main class="r-page">{eyebrow}{body}</main></body></html>')
