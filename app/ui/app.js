// AgentReports: the app (panel + overview + report), the details page and the look page.
// No framework, no build step.
(() => {
  "use strict";
  const DATA = JSON.parse(document.getElementById("data").textContent);
  const W = DATA.words;
  const LANG = DATA.lang;
  const $ = (s, el = document) => el.querySelector(s);
  const HUES = [168, 32, 212, 340, 265, 95, 12, 190, 48, 290];

  const hue = (name) => {
    let h = 0;
    for (const ch of name || "") h = (h * 31 + ch.codePointAt(0)) >>> 0;
    return HUES[h % HUES.length];
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const store = {
    get(k, d) { try { return localStorage.getItem("ar." + k) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem("ar." + k, v); } catch { /* private mode */ } },
  };

  // --- time ---
  const rtf = new Intl.RelativeTimeFormat(LANG, { numeric: "auto" });
  const dtf = new Intl.DateTimeFormat(LANG, { dateStyle: "medium", timeStyle: "short" });
  const ago = (iso) => {
    if (!iso) return "";
    const s = (new Date(iso) - Date.now()) / 1000;
    const steps = [[60, "second"], [3600, "minute"], [86400, "hour"], [604800, "day"], [2629800, "week"], [31557600, "month"], [Infinity, "year"]];
    let prev = 1;
    for (const [limit, unit] of steps) {
      if (Math.abs(s) < limit) return rtf.format(Math.round(s / prev), unit);
      prev = limit;
    }
    return "";
  };
  const fresh = (iso, days = 3) => iso && Date.now() - new Date(iso) < days * 86400000;

  // --- toast ---
  let toastTimer;
  const toast = (text, action) => {
    const el = $("#toast");
    el.innerHTML = `<span>${esc(text)}</span>` + (action ? `<button type="button">${esc(action.label)}</button>` : "");
    if (action) $("button", el).onclick = () => { el.classList.remove("show"); action.run(); };
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), action ? 6000 : 2400);
  };

  // --- server actions (signed-in person only) ---
  const act = async (slug, action, body) => {
    const r = await fetch(`/api/reports/${encodeURIComponent(slug)}/${action}`, {
      method: "POST", credentials: "same-origin",
      headers: { "X-Requested-With": "agentreports", "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error(r.status);
    return r.json();
  };
  const copyLink = async (slug) => {
    const url = new URL(`/r/${slug}`, location.href).href;
    try { await navigator.clipboard.writeText(url); toast(W.copied); }
    catch { prompt(W.copy_link, url); }
  };
  document.querySelectorAll(".pill[data-cat]").forEach((p) => p.style.setProperty("--h", hue(p.dataset.cat)));
  document.querySelectorAll(".swatch[data-colour]").forEach((s) => { s.style.background = s.dataset.colour; });

  if (document.body.dataset.page === "brand") {
    document.querySelectorAll("time[datetime]").forEach((t) => { t.textContent = dtf.format(new Date(t.getAttribute("datetime"))); });
    document.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-action=brand-restore]");
      if (!b) return;
      if (!confirm(b.dataset.version === "0" ? W.brand_base_confirm : W.brand_restore_confirm)) return;
      b.disabled = true;
      try {
        const r = await fetch("/api/brand/restore", { method: "POST", credentials: "same-origin",
          headers: { "X-Requested-With": "agentreports", "Content-Type": "application/json" },
          body: JSON.stringify({ version: +b.dataset.version }) });
        if (!r.ok) throw new Error(r.status);
        location.reload();
      } catch { b.disabled = false; toast(W.error); }
    });
    return;
  }

  if (document.body.dataset.page === "details") {
    document.querySelectorAll("time[datetime]").forEach((t) => { t.textContent = dtf.format(new Date(t.getAttribute("datetime"))); t.title = ago(t.getAttribute("datetime")); });
    document.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-action]");
      if (!b) return;
      const { action, slug, version } = b.dataset;
      try {
        if (action === "copy") return copyLink(slug);
        if (action === "archive" && !confirm(W.archive_confirm)) return;
        if (action === "restore" && !confirm(W.restore_confirm)) return;
        b.disabled = true;
        await act(slug, action, version ? { version: +version } : null);
        location.reload();
      } catch { b.disabled = false; toast(W.error); }
    });
    return;
  }

  // --- start page ---
  const reports = DATA.reports;
  const el = { sq: $("#sq"), nav: $("#sidenav"), foot: $("#sidefoot"), home: $("#view-home"), view: $("#view-report"),
    frame: $("#frame"), archLabel: $("#arch + span"), q: $("#q"), sort: $("#sort"), arch: $("#arch"), cats: $("#cats"), grid: $("#grid"), empty: $("#empty"), stats: $("#stats") };
  const state = {
    q: "",
    cat: store.get("cat", ""),
    sort: store.get("sort", "updated"),
    arch: store.get("arch", "0") === "1",
    view: store.get("view", "cards") === "list" ? "list" : "cards",
  };
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.has("cat")) state.cat = hash.get("cat");
  if (hash.has("q")) state.q = hash.get("q");
  el.q.value = state.q;
  el.sort.value = state.sort;
  el.arch.checked = state.arch;

  const catName = (r) => r.category || W.uncategorized;
  // The switch shows the archive instead of the start page, not both mixed together.
  const visible = () => reports.filter((r) => !r.draft && (state.arch ? r.archived : !r.archived));
  const words = (q) => q.toLowerCase().split(/\s+/).filter(Boolean);
  const matches = (r, ws) => {
    const hay = [r.title, r.description, r.category, r.slug, r.updated_by_text, r.created_by_text, ...(r.tags || [])].join(" ").toLowerCase();
    return ws.every((w) => hay.includes(w));
  };
  const mark = (text, ws) => {
    let out = esc(text);
    for (const w of ws) {
      if (w.length < 2) continue;
      const re = new RegExp(`(${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/&/g, "&amp;").replace(/</g, "&lt;")})`, "gi");
      out = out.replace(/(^|>)([^<]*)/g, (m, a, t) => a + t.replace(re, "<mark>$1</mark>"));
    }
    return out;
  };

  const sorters = {
    updated: (a, b) => (b.updated || "").localeCompare(a.updated || ""),
    created: (a, b) => (b.created || "").localeCompare(a.created || ""),
    title: (a, b) => a.title.localeCompare(b.title, LANG, { sensitivity: "base" }),
    category: (a, b) => catName(a).localeCompare(catName(b), LANG) || (b.updated || "").localeCompare(a.updated || ""),
  };

  const renderStats = () => {
    const live = reports.filter((r) => !r.archived && !r.draft);
    const cats = new Set(live.map(catName));
    const last = live.reduce((m, r) => (r.updated > m ? r.updated : m), "");
    el.stats.innerHTML = live.length
      ? `<span><b>${live.length}</b> ${live.length === 1 ? W.report : W.reports}</span><span><b>${cats.size}</b> ${cats.size === 1 ? W.category : W.categories}</span>`
        + (last ? `<span>${W.last_updated} ${esc(ago(last))}</span>` : "")
      : "";
  };

  const renderChips = () => {
    const counts = new Map();
    for (const r of visible()) counts.set(catName(r), (counts.get(catName(r)) || 0) + 1);
    if (state.cat && !counts.has(state.cat)) state.cat = "";
    const names = [...counts.keys()].sort((a, b) => a.localeCompare(b, LANG));
    if (names.length < 2) { el.cats.innerHTML = ""; return; }
    el.cats.innerHTML = [`<button class="chip" data-cat="" aria-pressed="${!state.cat}">${esc(W.all)} <span class="n">${visible().length}</span></button>`]
      .concat(names.map((n) => `<button class="chip" data-cat="${esc(n)}" data-h="${hue(n)}" aria-pressed="${state.cat === n}"><span class="dot"></span>${esc(n)} <span class="n">${counts.get(n)}</span></button>`))
      .join("");
    paint(el.cats);
  };

  const card = (r, ws, i) => {
    const badge = r.archived ? `<span class="badge muted">${esc(W.archived)}</span>`
      : fresh(r.created) ? `<span class="badge">${esc(W.new)}</span>`
      : fresh(r.updated) && r.version > 1 ? `<span class="badge">${esc(W.updated)}</span>` : "";
    return `<article class="card${r.archived ? " archived" : ""}" data-h="${hue(catName(r))}" data-delay="${Math.min(i, 12) * 25}" data-slug="${esc(r.slug)}">
      <a class="card-link" href="/r/${esc(r.slug)}" data-open="${esc(r.slug)}" aria-label="${esc(W.open)}: ${esc(r.title)}"></a>
      <div class="card-top">
        <span class="pill" data-h="${hue(catName(r))}">${mark(catName(r), ws)}</span>${badge}
        <button class="more" type="button" aria-label="${esc(W.menu)}" aria-haspopup="menu" aria-expanded="false">
          <svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>
        </button>
      </div>
      <h3>${mark(r.title, ws)}</h3>
      <p class="desc">${mark(r.description || "", ws)}</p>
      <div class="card-foot">
        <time datetime="${esc(r.updated)}" title="${esc(r.updated ? dtf.format(new Date(r.updated)) : "")}">${esc(ago(r.updated))}</time>
        ${r.updated_by_text ? `<span class="sep">·</span><span class="who" title="${esc(r.updated_by)}">${esc(r.updated_by_text)}</span>` : ""}
        <span class="v">v${r.version}</span>
      </div>
    </article>`;
  };

  const row = (r, ws, i) => {
    const badge = r.archived ? `<span class="badge muted">${esc(W.archived)}</span>`
      : fresh(r.created) ? `<span class="badge">${esc(W.new)}</span>`
      : fresh(r.updated) && r.version > 1 ? `<span class="badge">${esc(W.updated)}</span>` : "";
    return `<article class="row card-like${r.archived ? " archived" : ""}" data-h="${hue(catName(r))}" data-delay="${Math.min(i, 16) * 15}" data-slug="${esc(r.slug)}">
      <a class="card-link" href="/r/${esc(r.slug)}" data-open="${esc(r.slug)}" aria-label="${esc(W.open)}: ${esc(r.title)}"></a>
      <div class="row-main">
        <div class="row-title"><span class="pill" data-h="${hue(catName(r))}">${mark(catName(r), ws)}</span><h3>${mark(r.title, ws)}</h3>${badge}</div>
        <p class="desc">${mark(r.description || "", ws)}</p>
      </div>
      <div class="row-meta"><time datetime="${esc(r.updated)}" title="${esc(r.updated ? dtf.format(new Date(r.updated)) : "")}">${esc(ago(r.updated))}</time>${r.updated_by_text ? `<span class="who" title="${esc(r.updated_by)}">${esc(r.updated_by_text)}</span>` : ""}</div>
      <span class="v">v${r.version}</span>
      <button class="more" type="button" aria-label="${esc(W.menu)}" aria-haspopup="menu" aria-expanded="false">
        <svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>
      </button>
    </article>`;
  };
  const block = (rs, ws, start) => state.view === "list"
    ? `<div class="list">${rs.map((r, i) => row(r, ws, start + i)).join("")}</div>`
    : `<div class="grid">${rs.map((r, i) => card(r, ws, start + i)).join("")}</div>`;

  const renderArchiveLabel = () => {
    const n = reports.filter((r) => r.archived).length;
    el.archLabel.textContent = n ? `${W.show_archived} (${n})` : W.show_archived;
    document.body.classList.toggle("viewing-archive", state.arch);
  };

  const render = () => {
    renderArchiveLabel();
    document.querySelectorAll(".seg [data-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === state.view)));
    renderStats();
    renderChips();
    const ws = words(state.q);
    const list = visible().filter((r) => (!state.cat || catName(r) === state.cat) && matches(r, ws)).sort(sorters[state.sort]);
    if (!list.length) {
      el.grid.innerHTML = "";
      el.empty.hidden = false;
      el.empty.textContent = state.arch && !visible().length ? W.empty_archive : reports.length ? W.empty_filtered : W.empty;
      return;
    }
    el.empty.hidden = true;
    if (state.sort === "category" && !state.cat) {
      const groups = new Map();
      for (const r of list) (groups.get(catName(r)) || groups.set(catName(r), []).get(catName(r))).push(r);
      let i = 0;
      el.grid.innerHTML = [...groups].map(([name, rs]) => {
        const html = `<div class="group-title"><span>${esc(name)}</span><span class="n">${rs.length}</span></div>${block(rs, ws, i)}`;
        i += rs.length;
        return html;
      }).join("");
    } else {
      el.grid.innerHTML = block(list, ws, 0);
    }
    paint(el.grid);
  };

  // The page's Content-Security-Policy blocks style="" attributes, so colours and delays are set here.
  const paint = (root) => root.querySelectorAll("[data-h]").forEach((e) => {
    e.style.setProperty("--h", e.dataset.h);
    if (e.dataset.delay) e.style.animationDelay = e.dataset.delay + "ms";
  });

  const save = () => {
    store.set("cat", state.cat);
    store.set("sort", state.sort);
    store.set("arch", state.arch ? "1" : "0");
    store.set("view", state.view);
    const h = new URLSearchParams();
    if (state.cat) h.set("cat", state.cat);
    if (state.q) h.set("q", state.q);
    if (location.pathname === "/") history.replaceState(null, "", h.toString() ? "#" + h : "/");
  };
  const update = () => { save(); render(); };

  el.q.addEventListener("input", () => { state.q = el.q.value.trim(); update(); });
  el.sort.addEventListener("change", () => { state.sort = el.sort.value; update(); });
  el.arch.addEventListener("change", () => { state.arch = el.arch.checked; update(); renderSide(); });
  document.querySelector(".seg").addEventListener("click", (e) => {
    const b = e.target.closest("[data-view]");
    if (b) { state.view = b.dataset.view; update(); }
  });
  el.cats.addEventListener("click", (e) => {
    const c = e.target.closest(".chip");
    if (c) { state.cat = c.dataset.cat; update(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !/input|textarea|select/i.test(document.activeElement.tagName)) {
      e.preventDefault(); (current ? el.sq : el.q).focus();
    } else if (e.key === "Escape") {
      if (closeMenu()) return;
      if (document.activeElement === el.q && el.q.value) { el.q.value = ""; state.q = ""; update(); }
    }
  });

  // --- card menu ---
  let openMenu = null;
  const closeMenu = () => {
    if (!openMenu) return false;
    openMenu.menu.remove();
    openMenu.button.setAttribute("aria-expanded", "false");
    openMenu = null;
    return true;
  };
  const setArchived = async (slug, archived) => {
    const r = reports.find((x) => x.slug === slug);
    const updated = await act(slug, archived ? "archive" : "unarchive");
    Object.assign(r, updated);
    render();
    renderSide();
    return r;
  };
  el.grid.addEventListener("click", async (e) => {
    const more = e.target.closest(".more");
    const item = e.target.closest(".menu [data-do]");
    if (more) {
      e.preventDefault();
      const cardEl = more.closest("[data-slug]");
      const was = openMenu && openMenu.button === more;
      closeMenu();
      if (was) return;
      const r = reports.find((x) => x.slug === cardEl.dataset.slug);
      const menu = document.createElement("div");
      menu.className = "menu";
      menu.setAttribute("role", "menu");
      menu.innerHTML = `<a role="menuitem" href="/r/${esc(r.slug)}" data-open="${esc(r.slug)}">${esc(W.open)}</a>
        <a role="menuitem" href="/${esc(r.slug)}.html" target="_blank" rel="noopener">${esc(W.open_tab)}</a>
        <a role="menuitem" href="/r/${esc(r.slug)}/info">${esc(W.details)}</a>
        <button role="menuitem" type="button" data-do="pin">${esc(isPinned(r.slug) ? W.unpin : W.pin)}</button>
        <button role="menuitem" type="button" data-do="copy">${esc(W.copy_link)}</button>
        <button role="menuitem" type="button" data-do="${r.archived ? "unarchive" : "archive"}">${esc(r.archived ? W.unarchive : W.archive)}</button>`;
      cardEl.append(menu);
      more.setAttribute("aria-expanded", "true");
      openMenu = { menu, button: more };
      $("a, button", menu).focus();
      return;
    }
    if (item) {
      const slug = item.closest("[data-slug]").dataset.slug;
      const what = item.dataset.do;
      closeMenu();
      try {
        if (what === "copy") return copyLink(slug);
        if (what === "pin") { togglePin(slug); return; }
        if (what === "archive") {
          if (!confirm(W.archive_confirm)) return;
          await setArchived(slug, true);
          toast(W.archived_toast, { label: W.undo, run: () => setArchived(slug, false).catch(() => toast(W.error)) });
        } else if (what === "unarchive") {
          await setArchived(slug, false);
        }
      } catch { toast(W.error); }
    }
  });
  document.addEventListener("click", (e) => { if (openMenu && !e.target.closest(".menu, .more")) closeMenu(); });


  // --- pins (this browser) ---
  const pins = () => { try { return JSON.parse(store.get("pins", "[]")); } catch { return []; } };
  const isPinned = (slug) => pins().includes(slug);
  const togglePin = (slug) => {
    const p = pins();
    store.set("pins", JSON.stringify(p.includes(slug) ? p.filter((x) => x !== slug) : [slug, ...p]));
    renderSide();
    if (current === slug) renderBar(find(slug));
  };

  // --- the panel ---
  const find = (slug) => reports.find((r) => r.slug === slug);
  const openCats = () => { try { return JSON.parse(store.get("closed", "[]")); } catch { return []; } };
  const item = (r) => `<a class="side-item${r.slug === current ? " active" : ""}" href="/r/${esc(r.slug)}" data-open="${esc(r.slug)}"
      title="${esc(r.title)}" ${r.slug === current ? 'aria-current="page"' : ""}><span class="dot" data-h="${hue(catName(r))}"></span>
      <span class="t">${esc(r.title)}</span>${fresh(r.created) || (fresh(r.updated) && r.version > 1) ? '<span class="new"></span>' : ""}</a>`;
  const renderSide = () => {
    const ws = words(el.sq.value.trim());
    const live = reports.filter((r) => !r.archived && !r.draft && matches(r, ws)).sort(sorters.updated);
    const drafts = reports.filter((r) => r.draft && !r.archived && matches(r, ws)).sort(sorters.updated);
    const closed = openCats();
    const parts = [`<a class="side-item home${current ? "" : " active"}" href="/" data-nav><svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg><span class="t">${esc(W.overview)}</span></a>`];
    const pinned = pins().map(find).filter((r) => r && !r.archived && matches(r, ws));
    if (pinned.length) parts.push(`<div class="side-group"><div class="side-label">${esc(W.pinned)}</div>${pinned.map(item).join("")}</div>`);
    const groups = new Map();
    for (const r of live) (groups.get(catName(r)) || groups.set(catName(r), []).get(catName(r))).push(r);
    for (const name of [...groups.keys()].sort((a, b) => a.localeCompare(b, LANG))) {
      const rs = groups.get(name);
      const open = ws.length || !closed.includes(name) || rs.some((r) => r.slug === current);
      parts.push(`<details class="side-group" data-cat="${esc(name)}"${open ? " open" : ""}><summary class="side-label">
        <span>${esc(name)}</span><span class="n">${rs.length}</span></summary>${rs.map(item).join("")}</details>`);
    }
    if (drafts.length) parts.push(`<details class="side-group drafts" data-cat="__drafts"${!openCats().includes("__drafts") || drafts.some((r) => r.slug === current) ? " open" : ""}><summary class="side-label">
        <span>${esc(W.drafts)}</span><span class="n">${drafts.length}</span></summary>${drafts.map(item).join("")}</details>`);
    if (ws.length && !live.length) parts.push(`<p class="side-empty">${esc(W.empty_filtered)}</p>`);
    el.nav.innerHTML = parts.join("");
    paint(el.nav);
    const archived = reports.filter((r) => r.archived).length;
    el.foot.innerHTML = `<a class="side-item" href="/" data-archive>${esc(W.show_archived)}${archived ? ` <span class="n">${archived}</span>` : ""}</a>`
      + (DATA.brand_page ? `<a class="side-item" href="/brand">${esc(W.brand)}</a>` : "")
      + `<div class="side-row"><form method="post" action="/logout"><button class="btn ghost small" type="submit">${esc(W.logout)}</button></form></div>`
      + `<div class="side-version" id="side-version">${versionLine()}</div>`;
  };
  el.nav.addEventListener("toggle", (e) => {
    const d = e.target.closest("details[data-cat]");
    if (!d) return;
    const closed = new Set(openCats());
    if (d.open) closed.delete(d.dataset.cat); else closed.add(d.dataset.cat);
    store.set("closed", JSON.stringify([...closed]));
  }, true);
  el.sq.addEventListener("input", renderSide);

  // --- version, and whether GitHub has a newer one ---
  let latest = null;
  const versionLine = () => {
    if (!latest || !latest.update) return `<span title="${esc(latest && latest.subject || "")}">AgentReports ${esc(DATA.version)}</span>`;
    const link = `<a href="${esc(latest.repo_url)}/commits/main" target="_blank" rel="noopener" title="${esc(latest.subject || W.whats_new)}">${esc(W.update_available)} ${esc(latest.latest)}</a>`;
    const button = latest.can_update ? ` <button class="btn small primary" type="button" id="update-now">${esc(W.update_now)}</button>` : "";
    return `<span class="update">AgentReports ${esc(DATA.version)} → ${link}</span>${button}`;
  };
  const checkVersion = async () => {
    if (!DATA.update_check) return;
    try {
      const r = await fetch("/api/system/version", { credentials: "same-origin" });
      if (!r.ok) return;
      latest = await r.json();
      const box = $("#side-version");
      if (box) box.innerHTML = versionLine();
    } catch { /* offline: the version line stays as it is */ }
  };
  document.addEventListener("click", async (e) => {
    if (!e.target.closest("#update-now")) return;
    if (!confirm(W.update_confirm)) return;
    e.target.disabled = true;
    try {
      const r = await fetch("/api/system/update", { method: "POST", credentials: "same-origin",
        headers: { "X-Requested-With": "agentreports", "Content-Type": "application/json" }, body: "{}" });
      if (!r.ok) throw new Error(r.status);
      toast(W.update_started);
      const from = DATA.version;
      for (let i = 0; i < 60; i++) {   // up to five minutes
        await new Promise((ok) => setTimeout(ok, 5000));
        try {
          const h = await (await fetch("/health", { cache: "no-store" })).json();
          if (h.version && h.version !== from) return location.reload();
        } catch { /* restarting */ }
      }
      location.reload();
    } catch { e.target.disabled = false; toast(W.error); }
  });

  // the theme switch, top right on the start page and in the report bar
  const THEME = `<div class="theme" role="group" aria-label="${esc(W.theme)}">
    <button type="button" data-theme-set="system" title="${esc(W.theme_system)}" aria-label="${esc(W.theme_system)}"><svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg></button>
    <button type="button" data-theme-set="light" title="${esc(W.theme_light)}" aria-label="${esc(W.theme_light)}"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg></button>
    <button type="button" data-theme-set="dark" title="${esc(W.theme_dark)}" aria-label="${esc(W.theme_dark)}"><svg viewBox="0 0 24 24"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg></button></div>`;
  const wireTheme = (root) => {
    const read = () => { try { return localStorage.getItem("ar.theme") || "system"; } catch { return "system"; } };
    const buttons = root.querySelectorAll("[data-theme-set]");
    const mark = (t) => buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeSet === t)));
    mark(read());
    buttons.forEach((b) => b.addEventListener("click", () => {
      const t = b.dataset.themeSet;
      try { localStorage.setItem("ar.theme", t); } catch { /* this page only */ }
      if (t === "light" || t === "dark") document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
      mark(t);
    }));
  };
  document.querySelectorAll(".theme-slot").forEach((slot) => { slot.innerHTML = THEME; });
  wireTheme(document);

  // --- one report in the main area ---
  let current = null;
  const renderBar = (r) => {
    const pill = $("#r-pill");
    pill.textContent = catName(r);
    pill.dataset.h = hue(catName(r));
    $("#r-title").textContent = r.title;
    $("#r-meta").textContent = `v${r.version} · ${ago(r.updated)}${r.updated_by_text ? " · " + r.updated_by_text : ""}`;
    $("#r-meta").title = r.updated ? dtf.format(new Date(r.updated)) : "";
    const pin = $("#r-pin");
    pin.setAttribute("aria-pressed", String(isPinned(r.slug)));
    pin.title = pin.ariaLabel = isPinned(r.slug) ? W.unpin : W.pin;
    $("#r-tab").href = `/${r.slug}.html`;
    $("#r-info").href = `/r/${r.slug}/info`;
    paint($("#view-report"));
  };
  const showReport = (slug, fromFrame) => {
    const r = find(slug);
    if (!r) { toast(W.not_found_report); return showHome(); }
    current = slug;
    el.home.hidden = true;
    el.view.hidden = false;
    renderBar(r);
    if (!fromFrame) el.frame.src = `/${r.slug}.html`;
    el.frame.title = r.title;
    document.title = `${r.title} · ${DATA.site}`;
    renderSide();
  };
  const showHome = () => {
    current = null;
    el.view.hidden = true;
    el.home.hidden = false;
    el.frame.removeAttribute("src");
    document.title = DATA.site;
    render();
    renderSide();
  };
  const route = () => {
    const m = location.pathname.match(/^\/r\/([a-z0-9-]+)\/?$/);
    if (m) showReport(m[1]); else showHome();
  };
  const go = (path) => {
    closeMenu();
    if (path !== location.pathname + location.hash) history.pushState(null, "", path);
    route();
    document.body.classList.remove("side-open");
  };
  window.addEventListener("popstate", route);
  // A report in the frame says which one it is when it loads (a link from one report to another).
  window.addEventListener("message", (e) => {
    if (e.source !== el.frame.contentWindow) return;
    const to = e.data && e.data.agentreportsGo;
    if (typeof to === "string" && /^\/(r\/[a-z0-9-]+\/?)?$/.test(to)) return go(to);
    const slug = e.data && e.data.agentreports;
    if (typeof slug !== "string" || !find(slug) || slug === current) return;
    history.replaceState(null, "", `/r/${slug}`);
    showReport(slug, true);
  });
  document.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target.closest("a[data-open], a[data-nav], a[data-archive]");
    if (!a) return;
    e.preventDefault();
    if (a.hasAttribute("data-archive")) { state.arch = true; el.arch.checked = true; save(); return go("/"); }
    if (a.hasAttribute("data-nav")) { if (state.arch && !current) { state.arch = false; el.arch.checked = false; save(); } return go("/"); }
    go(`/r/${a.dataset.open}`);
  });
  $("#r-pin").addEventListener("click", () => current && togglePin(current));
  $("#r-copy").addEventListener("click", () => current && copyLink(current));

  // the panel: hidden on a phone until asked for; on a wide screen it can be folded away
  const folded = () => store.get("side", "open") === "folded";
  document.body.classList.toggle("side-folded", folded());
  $("#side-hide").addEventListener("click", () => {
    if (matchMedia("(max-width: 900px)").matches) return document.body.classList.remove("side-open");
    store.set("side", folded() ? "open" : "folded");
    document.body.classList.toggle("side-folded", folded());
  });
  document.querySelectorAll(".menu-btn").forEach((b) => b.addEventListener("click", () => {
    if (matchMedia("(max-width: 900px)").matches) return document.body.classList.add("side-open");
    store.set("side", "open");
    document.body.classList.remove("side-folded");
  }));
  $("#scrim").addEventListener("click", () => document.body.classList.remove("side-open"));

  route();
  checkVersion();
})();
