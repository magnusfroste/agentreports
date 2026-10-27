"""What an agent gets told about a report before people see it.

errors stop a publish (the page would be broken); warnings come back with every publish and from the
tool check_report, so the agent can fix them. The checks are about what goes wrong in practice: a script
sent instead of the page it writes, a page of its own colours instead of the site's look, a menu of its
own next to the site's panel, a table too wide for a phone, no word on where the numbers come from.
"""
import re

import mdreport

CODE_LINE = re.compile(r"^\s*(def |import |from \w+ import |class \w+[:(]|[A-Z_][A-Z0-9_]* = |print\(|for \w+ in )", re.M)


def _visible(html):
    """The page without scripts, styles and tags, roughly as a reader sees it."""
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    return re.sub(r"(?s)<[^>]+>", " ", s)


def check(content, fmt="html", details=None, report_style=True):
    """(errors, warnings) for a report about to be published."""
    errors, warnings = [], []
    details = details or {}
    text = content if isinstance(content, str) else content.decode("utf-8", "replace")
    if not text.strip():
        return ["The content is empty."], []
    if not details.get("description"):
        warnings.append("No description: the card on the start page will only show the title. One or two sentences "
                        "on what the reader learns, ideally with a key figure.")
    if fmt == "markdown":
        try:
            page = mdreport.render(text)
        except mdreport.MarkdownError as e:
            return [f"Markdown: {e}"], warnings
        if "<h1>" not in page:
            warnings.append("No '# Title' line: the report starts without a heading.")
        if "r-sources" not in page:
            warnings.append("No ::sources block: say what the numbers are built on and when, at the end.")
        if CODE_LINE.search(text) and "```" not in text:
            warnings.append("Some lines look like program code; is this the report, or the script that makes it?")
        return errors, warnings

    lead = text.lstrip("﻿ \t\r\n")
    if not lead.startswith("<"):
        errors.append("This is not an HTML page: it must start with <!doctype html> or a tag. It looks like the script "
                      "that builds the page was sent instead of the page it writes; run it and send its output, or "
                      "write the report in markdown (format=markdown).")
        return errors, warnings
    visible = _visible(text)
    code_lines = len(CODE_LINE.findall(visible))
    if code_lines >= 3 or '"""' in visible:
        errors.append(f"About {code_lines} lines of the visible page look like program code (def, import, X = \"\"\"…). "
                      "Send the page the script writes, not the script.")
    if not re.search(r"(?i)<title>[^<]+</title>", text):
        warnings.append("No <title>: the browser tab and the shared link get no name.")
    if report_style:
        if "/static/report.css" not in text:
            warnings.append("Does not link /static/report.css: the report will not look like the site or follow its "
                            "light/dark theme. Link it and use the r-* classes (see report_style), or write markdown.")
        colours = re.findall(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|rgba?\(", re.sub(r"(?is)<script\b.*?</script>", "", text))
        if len(colours) > 8:
            warnings.append(f"{len(colours)} colours of its own: use the site's (var(--accent), var(--c1)…var(--c6)) "
                            "so the report matches the site and works in dark mode.")
    nav_links = re.findall(r"(?is)<nav\b.*?</nav>", text)
    if any(re.search(r'href="[\w-]+\.html', n) or 'href="/"' in n for n in nav_links) or re.search(r'class="r-back"', text):
        warnings.append("A menu or back link of its own: the site's panel already lists the reports and links them. "
                        "Leave it out; link related reports from the text instead.")
    if re.search(r"(?i)\b(localStorage|sessionStorage|document\.cookie)\b", text):
        warnings.append("Uses localStorage/sessionStorage/cookies: reports run in a sandbox where they do not work. "
                        "Keep filter state in the URL (?project=…).")
    ext = [u for u in re.findall(r'(?i)<script[^>]+src="([^"]+)"', text) if not u.startswith("/static/")]
    if ext:
        warnings.append(f"External scripts ({', '.join(ext[:3])}): they may be slow, blocked or change under you. "
                        "Charts: use /static/report.js (class r-chart).")
    wide = re.findall(r"(?i)(?:min-)?width\s*:\s*(\d{4,})px", text)
    if wide:
        warnings.append(f"Fixed widths of {', '.join(wide[:3])}px: the page will scroll sideways on a phone. Put "
                        "tables in r-table-wrap and avoid fixed widths.")
    if re.search(r"(?i)<table\b", text) and "r-table-wrap" not in text and "overflow" not in text:
        warnings.append("A table outside r-table-wrap: wide tables then push the whole page sideways on a phone.")
    if report_style and "r-sources" not in text and not re.search(r"(?i)<footer", text):
        warnings.append("No sources footer (r-sources): say what the numbers are built on and when.")
    return errors, warnings
