// AgentReports report kit: charts. Link it from a report with
//   <script src="/static/report.js" defer></script>
// and describe a chart as data; it is drawn as SVG in the site's colours (var(--c1)…var(--c6)),
// with hover values, light and dark, and redrawn when the page width changes.
//
//   <div class="r-chart" data-type="bar|stacked|hbar|line|donut">
//     <script type="application/json">
//       {"labels": ["2026-08", "2026-09"], "unit": "kr",
//        "series": [{"name": "Transport", "values": [412000, 380000]}, {"name": "Storage", "values": [88000, 91000]}]}
//     </script>
//   </div>
(() => {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const lang = document.documentElement.lang || navigator.language || "en";
  const nf = new Intl.NumberFormat(lang, { maximumFractionDigits: 1 });
  const compact = new Intl.NumberFormat(lang, { notation: "compact", maximumFractionDigits: 1 });
  const colour = (i) => `var(--c${(i % 6) + 1})`;

  const el = (name, attrs = {}, parent) => {
    const e = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  };
  const tip = (node, text) => { el("title", {}, node).textContent = text; };
  const fmt = (v, unit) => (v == null ? "–" : nf.format(v) + (unit ? " " + unit : ""));

  // Round axis steps: 1, 2, 2.5, 5 × 10^n.
  const ticks = (max, min = 0, count = 5) => {
    const span = max - min || Math.abs(max) || 1;
    const raw = span / count;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
    const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
    const out = [];
    for (let v = lo; v <= hi + step / 2; v += step) out.push(+v.toFixed(10));
    return out;
  };

  const legend = (wrap, spec) => {
    if (spec.series.length < 2 && spec.type !== "donut") return;
    const names = spec.type === "donut" ? spec.labels : spec.series.map((s) => s.name);
    const div = document.createElement("div");
    div.className = "r-legend";
    names.forEach((n, i) => {
      const span = document.createElement("span");
      const sw = document.createElement("i");
      sw.style.background = colour(i);
      span.append(sw, document.createTextNode(n));
      div.appendChild(span);
    });
    wrap.appendChild(div);
  };

  const axisFont = { "font-size": 11.5, fill: "var(--faint)" };

  function columns(svg, spec, W, H, stacked) {
    const pad = { l: 56, r: 8, t: 10, b: 30 };
    const n = spec.labels.length, k = spec.series.length;
    const sums = spec.labels.map((_, i) => spec.series.reduce((a, s) => a + (s.values[i] || 0), 0));
    const maxV = stacked ? Math.max(...sums, 0) : Math.max(...spec.series.flatMap((s) => s.values.map((v) => v || 0)), 0);
    const minV = stacked ? 0 : Math.min(0, ...spec.series.flatMap((s) => s.values.map((v) => v || 0)));
    const t = ticks(maxV, minV);
    const lo = t[0], hi = t[t.length - 1];
    const y = (v) => pad.t + (H - pad.t - pad.b) * (1 - (v - lo) / (hi - lo || 1));
    for (const v of t) {
      el("line", { x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v), stroke: "var(--line)", "stroke-width": 1 }, svg);
      el("text", { x: pad.l - 8, y: y(v) + 4, "text-anchor": "end", ...axisFont }, svg).textContent = compact.format(v);
    }
    const band = (W - pad.l - pad.r) / n, gap = Math.min(18, band * 0.25);
    // Few bars on a wide page: keep them slender, centred in their band.
    const full = stacked || k === 1 ? band - gap : (band - gap) / k;
    const bw = Math.min(full, stacked || k === 1 ? 72 : 40);
    const inset = ((stacked || k === 1 ? band - gap : (band - gap)) - (stacked || k === 1 ? bw : bw * k)) / 2;
    const every = Math.ceil(n / Math.max(1, Math.floor((W - pad.l) / 64)));
    spec.labels.forEach((label, i) => {
      const x0 = pad.l + i * band + gap / 2 + inset;
      let acc = 0;
      spec.series.forEach((s, j) => {
        const v = s.values[i] || 0;
        const x = stacked ? x0 : x0 + j * bw;
        const top = stacked ? y(acc + v) : y(Math.max(v, 0));
        const bottom = stacked ? y(acc) : y(Math.min(v, 0));
        const r = el("rect", { x, y: top, width: Math.max(1, bw - (stacked || k === 1 ? 0 : 2)), height: Math.max(0, bottom - top),
          rx: 2, style: `fill:${colour(j)}` }, svg);
        tip(r, `${label} · ${s.name}: ${fmt(s.values[i], spec.unit)}`);
        acc += stacked ? v : 0;
      });
      if (i % every === 0) {
        el("text", { x: pad.l + i * band + band / 2, y: H - 10, "text-anchor": "middle", ...axisFont }, svg).textContent = label;
      }
    });
  }

  function hbars(svg, spec, W, H) {
    const s0 = spec.series[0];
    const pad = { l: Math.min(200, Math.max(70, ...spec.labels.map((l) => l.length * 7))), r: 70, t: 6, b: 6 };
    const n = spec.labels.length, row = (H - pad.t - pad.b) / n;
    const maxV = Math.max(...s0.values.map((v) => v || 0), 1);
    spec.labels.forEach((label, i) => {
      const v = s0.values[i] || 0, yy = pad.t + i * row;
      const w = (W - pad.l - pad.r) * (v / maxV);
      el("text", { x: pad.l - 8, y: yy + row / 2 + 4, "text-anchor": "end", "font-size": 12.5, fill: "var(--text)" }, svg).textContent = label;
      const r = el("rect", { x: pad.l, y: yy + row * 0.18, width: Math.max(1, w), height: row * 0.64, rx: 3, style: `fill:${colour(0)}` }, svg);
      tip(r, `${label}: ${fmt(s0.values[i], spec.unit)}`);
      el("text", { x: pad.l + w + 6, y: yy + row / 2 + 4, "font-size": 12, fill: "var(--muted)" }, svg).textContent = fmt(s0.values[i], spec.unit);
    });
  }

  function lines(svg, spec, W, H) {
    const pad = { l: 56, r: 12, t: 10, b: 30 };
    const all = spec.series.flatMap((s) => s.values.filter((v) => v != null));
    const t = ticks(Math.max(...all, 0), Math.min(0, ...all));
    const lo = t[0], hi = t[t.length - 1], n = spec.labels.length;
    const x = (i) => pad.l + (n === 1 ? (W - pad.l - pad.r) / 2 : (W - pad.l - pad.r) * i / (n - 1));
    const y = (v) => pad.t + (H - pad.t - pad.b) * (1 - (v - lo) / (hi - lo || 1));
    for (const v of t) {
      el("line", { x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v), stroke: "var(--line)" }, svg);
      el("text", { x: pad.l - 8, y: y(v) + 4, "text-anchor": "end", ...axisFont }, svg).textContent = compact.format(v);
    }
    const every = Math.ceil(n / Math.max(1, Math.floor((W - pad.l) / 64)));
    spec.labels.forEach((l, i) => {
      if (i % every === 0) el("text", { x: x(i), y: H - 10, "text-anchor": "middle", ...axisFont }, svg).textContent = l;
    });
    spec.series.forEach((s, j) => {
      const pts = s.values.map((v, i) => (v == null ? null : [x(i), y(v)]));
      const d = pts.reduce((acc, p, i) => (p ? acc + (acc && pts[i - 1] ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1) : acc), "");
      el("path", { d, fill: "none", style: `stroke:${colour(j)}`, "stroke-width": 2.2, "stroke-linejoin": "round" }, svg);
      pts.forEach((p, i) => {
        if (!p) return;
        const c = el("circle", { cx: p[0], cy: p[1], r: 3.5, style: `fill:${colour(j)}` }, svg);
        tip(c, `${spec.labels[i]} · ${s.name}: ${fmt(s.values[i], spec.unit)}`);
      });
    });
  }

  function donut(svg, spec, W, H) {
    const s0 = spec.series[0];
    const total = s0.values.reduce((a, v) => a + (v || 0), 0) || 1;
    const R = Math.min(W, H) / 2 - 6, r0 = R * 0.6, cx = W / 2, cy = H / 2;
    let a = -Math.PI / 2;
    s0.values.forEach((v, i) => {
      const frac = (v || 0) / total;
      if (frac <= 0) return;
      const a2 = a + frac * Math.PI * 2 - (frac >= 1 ? 1e-4 : 0);
      const large = a2 - a > Math.PI ? 1 : 0;
      const p = (rad, ang) => `${(cx + rad * Math.cos(ang)).toFixed(2)} ${(cy + rad * Math.sin(ang)).toFixed(2)}`;
      const d = `M${p(R, a)}A${R} ${R} 0 ${large} 1 ${p(R, a2)}L${p(r0, a2)}A${r0} ${r0} 0 ${large} 0 ${p(r0, a)}Z`;
      const seg = el("path", { d, style: `fill:${colour(i)}`, stroke: "var(--surface)", "stroke-width": 1.5 }, svg);
      tip(seg, `${spec.labels[i]}: ${fmt(v, spec.unit)} (${nf.format(frac * 100)} %)`);
      a = a2;
    });
    el("text", { x: cx, y: cy - 2, "text-anchor": "middle", "font-size": 20, "font-weight": 600, fill: "var(--text)",
      style: "font-family:var(--font-heading)" }, svg).textContent = compact.format(total);
    if (spec.unit) el("text", { x: cx, y: cy + 16, "text-anchor": "middle", ...axisFont }, svg).textContent = spec.unit;
  }

  function draw(node) {
    let spec;
    try {
      spec = JSON.parse(node.querySelector('script[type="application/json"]').textContent);
    } catch {
      node.textContent = "Chart data is not valid JSON.";
      return;
    }
    spec.type = spec.type || node.dataset.type || "bar";
    spec.series = (spec.series || []).map((s) => ({ name: s.name || "", values: (s.values || []).map((v) => (v == null ? null : +v)) }));
    spec.labels = (spec.labels || []).map(String);
    if (!spec.series.length || !spec.labels.length) return;
    node.querySelectorAll("svg, .r-legend").forEach((e) => e.remove());
    const W = Math.max(280, node.clientWidth || 640);
    const H = spec.type === "hbar" ? Math.max(120, spec.labels.length * 30 + 12)
      : spec.type === "donut" ? Math.min(260, W) : Math.round(Math.min(340, Math.max(220, W * 0.42)));
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, role: "img",
      "aria-label": spec.title || spec.series.map((s) => s.name).join(", ") }, node);
    svg.style.fontFamily = "inherit";
    if (spec.type === "hbar") hbars(svg, spec, W, H);
    else if (spec.type === "line") lines(svg, spec, W, H);
    else if (spec.type === "donut") donut(svg, spec, W, H);
    else columns(svg, spec, W, H, spec.type === "stacked");
    legend(node, spec);
  }

  // --- interactive tables: <div class="r-datatable"><script type="application/json">{columns, types, rows,
  //     show, filter, sum, sort, search, page, download, title}</script></div> (markdown ```datatable makes these)
  const WORDS = /^sv/.test(lang)
    ? { search: "Sök", all: "Alla", rows: "rader", of: "av", more: "Visa fler", download: "Ladda ned CSV", total: "Summa" }
    : { search: "Search", all: "All", rows: "rows", of: "of", more: "Show more", download: "Download CSV", total: "Total" };
  const plain = (v) => (v == null ? "" : typeof v === "object" ? v.t : String(v));

  function datatable(node) {
    let spec;
    try { spec = JSON.parse(node.querySelector('script[type="application/json"]').textContent); } catch { return; }
    const cols = spec.columns, type = (c) => spec.types[cols.indexOf(c)], at = (c) => cols.indexOf(c);
    const show = spec.show && spec.show.length ? spec.show : cols;
    const params = new URLSearchParams(location.search);
    const state = { q: params.get("q") || "", filters: {}, sort: spec.sort || null, shown: spec.page || 50 };
    for (const f of spec.filter || []) {                 // ?Carrier=Logarta preselects a filter (deep links)
      for (const [k, v] of params) if (k.toLowerCase() === f.toLowerCase()) state.filters[f] = v;
    }
    node.textContent = "";
    const bar = document.createElement("div");
    bar.className = "r-toolbar";
    let input = null;
    if (spec.search) {
      input = document.createElement("input");
      input.type = "search"; input.className = "r-search"; input.placeholder = WORDS.search; input.value = state.q;
      input.addEventListener("input", () => { state.q = input.value.trim().toLowerCase(); state.shown = spec.page || 50; render(); });
      bar.appendChild(input);
    }
    const selects = (spec.filter || []).map((f) => {
      const sel = document.createElement("select");
      sel.className = "r-select"; sel.setAttribute("aria-label", f);
      const values = [...new Set(spec.rows.map((r) => plain(r[at(f)])).filter(Boolean))]
        .sort((a, b) => a.localeCompare(b, lang, { numeric: true }));
      sel.innerHTML = "";
      const all = new Option(`${f}: ${WORDS.all}`, "");
      sel.add(all);
      values.forEach((v) => sel.add(new Option(v, v)));
      sel.value = state.filters[f] || "";
      sel.addEventListener("change", () => { state.filters[f] = sel.value; state.shown = spec.page || 50; render(); });
      bar.appendChild(sel);
      return sel;
    });
    const count = document.createElement("span");
    count.className = "r-count";
    bar.appendChild(count);
    if (spec.download) {
      const dl = document.createElement("button");
      dl.type = "button"; dl.className = "r-chip"; dl.textContent = WORDS.download;
      dl.addEventListener("click", () => download(filtered()));
      bar.appendChild(dl);
    }
    if (spec.search || (spec.filter || []).length || spec.download) node.appendChild(bar);
    const wrap = document.createElement("div");
    wrap.className = "r-table-wrap";
    const table = document.createElement("table");
    table.className = "r-table";
    wrap.appendChild(table);
    node.appendChild(wrap);
    const more = document.createElement("button");
    more.type = "button"; more.className = "r-chip r-more"; more.textContent = WORDS.more;
    more.addEventListener("click", () => { state.shown += spec.page || 50; render(); });
    node.appendChild(more);

    // Short values (dates, months, codes, invoice numbers) stay on one line; long text may wrap.
    const short = new Set(show.filter((c) => spec.rows.every((r) => plain(r[at(c)]).length <= 16)));
    const filtered = () => {
      const q = (input ? input.value.trim().toLowerCase() : state.q.toLowerCase());
      let rows = spec.rows.filter((r) => Object.entries(state.filters).every(([f, v]) => !v || plain(r[at(f)]) === v)
        && (!q || r.some((c) => plain(c).toLowerCase().includes(q))));
      if (state.sort) {
        const i = at(state.sort.col), dir = state.sort.dir === "desc" ? -1 : 1, num = type(state.sort.col) === "number";
        rows = rows.slice().sort((a, b) => {
          const x = a[i], y = b[i];
          if (x == null) return 1;
          if (y == null) return -1;
          return dir * (num ? x - y : plain(x).localeCompare(plain(y), lang, { numeric: true }));
        });
      }
      return rows;
    };
    const cell = (v, t, c) => {
      const td = document.createElement("td");
      if (short.has(c)) td.style.whiteSpace = "nowrap";
      if (t === "number") { td.className = "num"; td.textContent = v == null ? "" : nf.format(v); }
      else if (t === "link" && v) {
        const a = document.createElement("a");
        a.href = v.u; a.textContent = v.t; a.target = "_blank"; a.rel = "noopener";
        td.appendChild(a);
      } else td.textContent = plain(v);
      return td;
    };
    function render() {
      const rows = filtered();
      table.textContent = "";
      const thead = table.createTHead().insertRow();
      for (const c of show) {
        const th = document.createElement("th");
        if (type(c) === "number") th.className = "num";
        th.textContent = c + (state.sort && state.sort.col === c ? (state.sort.dir === "desc" ? " ↓" : " ↑") : "");
        th.style.cursor = "pointer";
        th.addEventListener("click", () => {
          state.sort = { col: c, dir: state.sort && state.sort.col === c && state.sort.dir === "asc" ? "desc" : "asc" };
          render();
        });
        thead.appendChild(th);
      }
      const tbody = table.createTBody();
      for (const r of rows.slice(0, state.shown)) {
        const tr = tbody.insertRow();
        for (const c of show) tr.appendChild(cell(r[at(c)], type(c), c));
      }
      if ((spec.sum || []).length) {
        const tr = table.createTFoot().insertRow();
        show.forEach((c, n) => {
          const td = document.createElement("td");
          if ((spec.sum || []).includes(c)) {
            td.className = "num";
            td.textContent = nf.format(rows.reduce((a, r) => a + (r[at(c)] || 0), 0));
          } else if (n === 0) td.textContent = WORDS.total;
          tr.appendChild(td);
        });
      }
      count.textContent = rows.length === spec.rows.length ? `${rows.length} ${WORDS.rows}`
        : `${rows.length} ${WORDS.of} ${spec.rows.length} ${WORDS.rows}`;
      more.hidden = rows.length <= state.shown;
    }
    function download(rows) {
      const q = (v) => { const s = plain(v); return /[",;\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
      const text = [cols.map(q).join(",")].concat(rows.map((r) => r.map((v) => (v && typeof v === "object" ? v.u : q(v))).join(","))).join("\n");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob(["\ufeff" + text], { type: "text/csv;charset=utf-8" }));
      a.download = spec.download || "data.csv";
      document.body.appendChild(a); a.click(); a.remove();
    }
    render();
  }

  const all = () => document.querySelectorAll(".r-chart").forEach(draw);
  const tables = () => document.querySelectorAll(".r-datatable").forEach(datatable);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", tables); else tables();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", all); else all();
  let width = window.innerWidth;
  window.addEventListener("resize", () => {
    if (Math.abs(window.innerWidth - width) < 40) return;
    width = window.innerWidth;
    clearTimeout(draw.t);
    draw.t = setTimeout(all, 150);
  });
})();
