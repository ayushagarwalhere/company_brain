const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const link = (url, text) => (url && !url.startsWith("scenario://") ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
let cy, currentFeature, driftCount = null;
const TYPES = { Feature: "--n-feature", Ticket: "--n-ticket", Requirement: "--n-req", Message: "--n-msg", PullRequest: "--n-pr", Person: "--n-person", Decision: "--accent" };

async function api(path, body) {
  const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

/* ---------- theme ---------- */
const THEME_KEY = "drift-theme";
function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  if (currentFeature) showGraph(currentFeature);
  renderLegend();
}
const urlTheme = new URLSearchParams(location.search).get("theme");
try { applyTheme(urlTheme || localStorage.getItem(THEME_KEY)); } catch { applyTheme(urlTheme); }
$("#theme-toggle").addEventListener("click", () => {
  const dark = css("color-scheme") === "dark";
  const next = dark ? "light" : "dark";
  try { localStorage.setItem(THEME_KEY, next); } catch { /* ignore */ }
  applyTheme(next);
});

/* ---------- graph path strings -> chips ---------- */
function renderPath(str) {
  let k = 0;
  const tokens = str.split(/(<-\[:[A-Z_|]+\]-|-\[:[A-Z_|]+\]->|\s;\s)/);
  return `<div class="path">${tokens.map((t) => {
    if (!t) return "";
    if (t.trim() === ";") return `<span class="sep"></span>`;
    const rel = t.match(/^(<-|-)\[:([A-Z_|]+)\](->|-)$/);
    if (rel) return `<span class="r" style="--k:${k++}">${rel[1] === "<-" ? "←" : ""}${esc(rel[2])}${rel[3] === "->" ? "→" : ""}</span>`;
    return t.split(/(\([^)]*\))/).map((part) => {
      const m = part.match(/^\((\w+)\s+([\s\S]*)\)$/);
      if (m) return `<span class="n" style="--k:${k++};color:${css(TYPES[m[1]] || "--muted")}" title="${esc(m[2])}"><b>${esc(m[1])}</b>${esc(m[2])}</span>`;
      const txt = part.trim().replace(/^,\s*/, "");
      return txt ? `<span class="t" style="--k:${k++}">${esc(txt)}</span>` : "";
    }).join("");
  }).join("")}</div>`;
}

/* ---------- hero ---------- */
async function loadStats() {
  const s = await api("/api/stats");
  const total = (xs) => xs.reduce((a, x) => a + x.n, 0);
  $("#spec-graph").textContent = `${total(s.nodes)} nodes · ${total(s.relationships)} relationships · ${s.nodes.length} labels`;
  $("#spec-build").innerHTML = s.build
    ? (s.build.extractor === "oracle" ? `<span class="warn">answer-key oracle (demo mode)</span>` : esc(s.build.extractor))
    : "not recorded";
  const log = [
    ["001", `Ingest ${s.nodes.find((n) => n.label === "Message")?.n ?? 0} messages`],
    ["002", `Load ${s.nodes.find((n) => n.label === "Ticket")?.n ?? 0} tickets · ${s.nodes.find((n) => n.label === "PullRequest")?.n ?? 0} PRs`],
    ["003", `Resolve ${s.nodes.find((n) => n.label === "Feature")?.n ?? 0} features`],
    ["004", `Version ${s.nodes.find((n) => n.label === "Requirement")?.n ?? 0} requirements`],
    ["005", `Record ${s.nodes.find((n) => n.label === "Decision")?.n ?? 0} decisions`],
    ["006", "Run drift query"],
  ];
  const n = (l) => s.nodes.find((x) => x.label === l)?.n ?? 0;
  const metrics = [
    ["Messages", n("Message"), "Slack + Discord"], ["Tickets", n("Ticket"), "Linear-style"], ["Pull requests", n("PullRequest"), "GitHub"],
    ["Decisions", n("Decision"), "found in chat"], ["Open drift", driftCount ?? 0, "requirements", true],
  ];
  $("#metrics").innerHTML = metrics.map(([k, v, sub, hot]) => `<div class="metric${hot ? " metric--hot" : ""}"><span class="mono">${esc(k)}</span>
    <b data-count="${v}"${hot ? ' id="metric-drift"' : ""}>${v}</b><small>${esc(sub)}</small></div>`).join("");
  const tick = [
    ["NODES", total(s.nodes)], ["RELATIONSHIPS", total(s.relationships)],
    ...s.relationships.slice(0, 10).map((r) => [r.type, r.n]),
  ].map(([k, v]) => `<span><b>${esc(k)}</b>${esc(v)}</span>`).join("");
  $("#ticker").innerHTML = tick + tick;
  countUp();
  $("#syslog").innerHTML = log.map(([i, t]) => `<li><b>${i}</b>${esc(t)}</li>`).join("");
  [...document.querySelectorAll("#syslog li")].forEach((li, i) => setTimeout(() => li.classList.add("on"), 250 + i * 140));
}

/* ---------- drift ---------- */
async function loadDrift() {
  const rows = await api("/api/drift");
  $("#spec-drift").innerHTML = rows.length
    ? `<span class="warn">${rows.length} requirement${rows.length > 1 ? "s" : ""} · ${[...new Set(rows.map((d) => d.feature_name))].join(", ")}</span>`
    : "none";
  driftCount = rows.length;
  const md = $("#metric-drift");
  if (md) { md.dataset.count = rows.length; countUp(md); }
  if (!rows.length) { $("#drift-list").innerHTML = `<p class="empty">No open drift. Tickets and PRs match the latest decisions.</p>`; return; }
  $("#drift-list").innerHTML = rows.map((d, i) => `
    <article class="violation reveal">
      <div class="violation__head">
        <span class="mono violation__tag">Drift ${String(i + 1).padStart(2, "0")} · ${esc(d.ticket)}</span>
        <span class="mono" style="color:var(--note)">${esc(d.changed_at.slice(0, 10))} · ${esc(d.source)} #${esc(d.channel)}</span>
      </div>
      <h3>${esc(d.feature_name)}</h3>
      <div class="violation__meta">${esc(d.changed_by)} changed the requirement in ${link(d.message_url, `${d.source} #${d.channel}`)}. ${esc(d.ticket)} was never updated.</div>
      <div class="diff">
        <div><span class="mono">${esc(d.ticket)} still says</span><p>${esc(d.ticket_text)}</p></div>
        <div class="now"><span class="mono">Decided in chat</span><p>${esc(d.requirement_text)}</p></div>
      </div>
      ${d.stale_prs.length ? `<div class="stale">Shipped the old version: ${d.stale_prs.map((p) => link(p.url, `#${p.pr} ${p.title}`)).join(", ")}</div>` : ""}
      <div class="mono kicker">Evidence path</div>
      ${renderPath(d.path)}
      <div class="actions">
        <button class="btn btn--ghost" data-graph="${esc(d.feature)}">Show in graph</button>
        <button class="btn" data-spec="${esc(d.feature)}">Generate spec</button>
      </div>
    </article>`).join("");
  observeReveals();
}

/* ---------- graph ---------- */
function renderLegend() {
  const items = ["Feature", "Ticket", "Requirement", "Message", "PullRequest", "Person"];
  $("#legend").innerHTML = items.map((t) => `<span><i style="background:${css(TYPES[t])}"></i>${t}</span>`).join("") +
    `<span><i style="background:${css("--accent")}"></i>Drift</span>`;
}

async function loadFeatures() {
  const fs = await api("/api/features");
  $("#feature-select").innerHTML = fs.map((f) => `<option value="${esc(f.id)}">${esc(f.name)}${f.drift ? "  · drift" : ""}</option>`).join("");
  renderLegend();
  if (fs.length) showGraph(fs.find((f) => f.drift)?.id || fs[0].id);
}

async function showGraph(feature) {
  currentFeature = feature;
  $("#feature-select").value = feature;
  const g = await api(`/api/features/${encodeURIComponent(feature)}/graph`);
  $("#canvas-tag").textContent = `${g.nodes.length} nodes · ${g.edges.length} edges · ${feature}`;
  const els = [
    ...g.nodes.map((n) => ({ data: { ...n, color: n.drift ? css("--accent") : css(TYPES[n.type] || "--muted") } })),
    ...g.edges.map((e, i) => ({ data: { id: `e${i}`, source: e.from, target: e.to, label: e.rel } })),
  ];
  if (cy) cy.destroy();
  cy = cytoscape({
    container: $("#graph"), elements: els, wheelSensitivity: 0.2,
    style: [
      { selector: "node", style: { "background-color": "data(color)", label: "data(label)", "font-family": "Geist Mono, monospace", "font-size": 9,
          color: css("--muted"), "text-wrap": "ellipsis", "text-max-width": 130, "text-valign": "bottom", "text-margin-y": 5, width: 15, height: 15 } },
      { selector: "node[type='Feature']", style: { width: 26, height: 26, "font-size": 11, "text-valign": "top", "text-margin-y": -6, color: css("--ink"), "font-family": "Geist, sans-serif",
          "border-width": 1, "border-color": css("--line") } },
      { selector: "node[type='Ticket']", style: { shape: "round-rectangle", width: 18, height: 12 } },
      { selector: "node[type='PullRequest']", style: { shape: "diamond", width: 16, height: 16 } },
      { selector: "node[?drift]", style: { width: 22, height: 22, "border-width": 6, "border-color": css("--accent"), "border-opacity": 0.25, color: css("--accent") } },
      { selector: "edge", style: { width: 1, "line-color": css("--line"), "target-arrow-color": css("--line"), "target-arrow-shape": "triangle", "arrow-scale": 0.7,
          "curve-style": "bezier", "font-family": "Geist Mono, monospace", "font-size": 6.5, color: css("--note"), "text-rotation": "autorotate",
          "text-background-color": css("--card"), "text-background-opacity": 1, "text-background-padding": 1 } },
      { selector: "edge[label='CHANGES'], edge[label='AMENDS'], edge[label='IMPLEMENTS'], edge[label='SUPERSEDES']", style: { label: "data(label)" } },
      { selector: "edge[label='CHANGES'], edge[label='AMENDS']", style: { "line-color": css("--accent"), "target-arrow-color": css("--accent"), width: 1.4 } },
      { selector: "edge.hover", style: { label: "data(label)", color: css("--ink"), "line-color": css("--muted") } },
      { selector: ":selected", style: { "border-width": 2, "border-color": css("--ink") } },
    ],
    layout: { name: "concentric", animate: false, padding: 30, minNodeSpacing: 26, startAngle: -Math.PI / 2,
              concentric: (n) => ({ Feature: 5, Ticket: 4, Requirement: 3, Message: 2, PullRequest: 2, Person: 1 }[n.data("type")] || 1),
              levelWidth: () => 1 },
    minZoom: 0.4, maxZoom: 2.2,
  });
  const hot = cy.nodes("[?drift]");
  const pulse = () => {
    if (!cy || cy.destroyed() || !hot.length) return;
    hot.animate({ style: { "border-opacity": 0.6, "border-width": 10 } }, { duration: 900, easing: "ease-in-out-sine",
      complete: () => hot.animate({ style: { "border-opacity": 0.15, "border-width": 4 } }, { duration: 900, easing: "ease-in-out-sine", complete: pulse }) });
  };
  if (!document.documentElement.classList.contains("static")) pulse();
  cy.on("mouseover", "node", (e) => e.target.connectedEdges().addClass("hover"));
  cy.on("mouseout", "node", (e) => e.target.connectedEdges().removeClass("hover"));
  cy.on("tap", "node", (e) => {
    const d = e.target.data();
    const nb = e.target.connectedEdges().map((x) => `${x.data("label")}`);
    $("#node-detail").innerHTML = `
      <div><dt>Type</dt><dd>${esc(d.type)}${d.drift ? ' <span class="badge warn">drift</span>' : ""}</dd></div>
      <div><dt>Id</dt><dd>${esc(d.id)}</dd></div>
      <div><dt>Text</dt><dd>${esc(d.text || "n/a")}</dd></div>
      <div><dt>Edges</dt><dd>${esc([...new Set(nb)].join(" · ") || "none")}</dd></div>`;
  });
}
$("#graph").addEventListener("mousemove", (e) => {
  const r = e.currentTarget.getBoundingClientRect();
  $("#coords").textContent = `X:${String(Math.round(e.clientX - r.left)).padStart(4, "0")} Y:${String(Math.round(e.clientY - r.top)).padStart(4, "0")}`;
});

/* ---------- ask ---------- */
async function ask(q) {
  $("#ask-input").value = q;
  $("#answer").innerHTML = `<p class="answer thinking">Querying graph tools</p>`;
  try {
    const r = await api("/api/ask", { question: q });
    $("#answer").innerHTML = `<div class="answer">${esc(r.answer)}</div>
      <div class="mono kicker">Tools called</div>
      <div class="chips" style="margin:6px 0 0">${r.tool_calls.map((t) => `<span class="chip mono">${esc(t.tool)} ${esc(Object.values(t.args).join(", "))}</span>`).join("") || "<span class='mono'>none</span>"}</div>
      ${r.paths.length ? `<div class="mono kicker">Graph paths</div>${r.paths.slice(0, 6).map(renderPath).join("")}` : ""}`;
  } catch (e) {
    if (!/DEEPSEEK|Service Unavailable/i.test(e.message)) { $("#answer").innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
    try { await askOffline(q); } catch (err) { $("#answer").innerHTML = `<p class="error">${esc(err.message)}</p>`; }
  }
}

/* No LLM configured: run the graph tools directly, so the section still answers from the graph. */
async function askOffline(q) {
  const ql = q.toLowerCase();
  let html = `<div class="notice"><b>LLM not configured</b>: running the graph tools directly. Set DEEPSEEK_API_KEY for written answers.</div>`;
  const conn = q.match(/([\w:-]+)\s+(?:connected to|to|→)\s+([\w:-]+)\??\s*$/i);
  const norm = (x) => (/^(pr|bd)-\d+$/i.test(x) ? x.toUpperCase() : x.toLowerCase());
  if (conn && /connect|→/.test(ql)) {
    const r = await api(`/api/connect?a=${encodeURIComponent(norm(conn[1]))}&b=${encodeURIComponent(norm(conn[2]))}`);
    html += `<div class="mono kicker">how_connected(${esc(norm(conn[1]))}, ${esc(norm(conn[2]))})</div>` + (r.paths.map(renderPath).join("") || "<p class='muted'>No path within 7 hops.</p>");
  } else {
    const fs = await api("/api/features");
    const f = fs.find((x) => (ql.includes("sla") && x.id.includes("sla")) || (ql.includes("export") && x.id.includes("export"))
      || (ql.includes("dark") && x.id.includes("dark")) || x.tickets.some((t) => ql.includes(t.toLowerCase())));
    if (/who|know|expert/.test(ql) && f) {
      const ex = await api(`/api/features/${f.id}/experts`);
      html += `<div class="mono kicker">who_knows(${esc(f.id)})</div><ol class="experts">${ex.map((p) => `<li><b>${esc(p.name)}</b> <span class="muted">${esc(p.role)} · score ${p.score} · ${p.items} items</span></li>`).join("")}</ol>`;
    } else if (f) {
      const [d, h] = await Promise.all([api(`/api/drift?feature=${f.id}`), api(`/api/features/${f.id}/history`)]);
      html += `<div class="mono kicker">drift_for_feature(${esc(f.id)})</div>` + (d.length
        ? d.map((x) => `<p class="answer">⚠ ${esc(x.requirement_text)} ${esc(x.ticket)} still says “${esc(x.ticket_text)}”.</p>` + renderPath(x.path)).join("")
        : `<p class="answer">No open drift on ${esc(f.name)}.</p>`);
      html += `<div class="mono kicker">decision_history(${esc(f.id)})</div>` + h.paths.slice(0, 6).map(renderPath).join("");
    } else {
      const d = await api("/api/drift");
      html += `<div class="mono kicker">drift_for_feature()</div>` + d.map((x) => `<p class="answer">⚠ <b>${esc(x.feature_name)}</b>: ${esc(x.requirement_text)}</p>` + renderPath(x.path)).join("");
    }
  }
  $("#answer").innerHTML = html;
}

function countUp(only) {
  const els = only ? [only] : [...document.querySelectorAll("[data-count]")];
  els.forEach((el) => {
    const target = Number(el.dataset.count);
    if (!Number.isFinite(target)) return;
    if (document.documentElement.classList.contains("static")) { el.textContent = target; return; }
    const t0 = performance.now();
    const step = (t) => { const p = Math.min(1, (t - t0) / 1100); el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  });
}

/* split hero headline into characters */
document.querySelectorAll("[data-split]").forEach((line, li) => {
  let i = li * 16;
  line.innerHTML = [...line.textContent].map((c) => (c === " " ? `<span class="sp"></span>` : `<span class="ch" style="--i:${i++}">${esc(c)}</span>`)).join("");
});

/* nav: highlight the section in view; scroll progress bar */
document.body.insertAdjacentHTML("afterbegin", `<div class="progress" id="progress"></div>`);
addEventListener("scroll", () => {
  const h = document.documentElement;
  $("#progress").style.width = `${(h.scrollTop / Math.max(1, h.scrollHeight - h.clientHeight)) * 100}%`;
}, { passive: true });
if ("IntersectionObserver" in window) {
  const links = [...document.querySelectorAll(".nav__links a")];
  const nio = new IntersectionObserver((es) => es.forEach((x) => {
    if (x.isIntersecting) links.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === `#${x.target.id}`));
  }), { rootMargin: "-45% 0px -50% 0px" });
  document.querySelectorAll("main .sec").forEach((sec) => nio.observe(sec));
}

/* ---------- retro ---------- */
async function loadRetro(sprint) {
  document.querySelectorAll("#sprint-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.sprint === sprint));
  const r = await api(`/api/retro/${sprint}`);
  const status = (d) => d.shipped_in.length ? `<span class="badge ok">shipped ${d.shipped_in.map((n) => "#" + n).join(", ")}</span>`
    : d.superseded_by === "ticket" ? `<span class="badge">in ticket</span>` : `<span class="badge warn">not shipped</span>`;
  let k = 0;
  $("#retro").innerHTML = `<div class="retro-cols">
    <div><h3>Decided · ${r.decided.length}</h3><ol>${r.decided.map((d) => `<li style="--k:${k++}">${esc(d.text)} ${status(d)}
      <span class="src">${esc(d.by)} · ${esc(d.at.slice(0, 10))} · ${esc(d.ticket)} · ${link(d.source, `${d.platform} #${d.channel}`)}</span></li>`).join("") || "<li>No decisions in chat</li>"}</ol></div>
    <div><h3>Shipped · ${r.shipped.length}</h3><ol>${r.shipped.map((p) => `<li style="--k:${k++}">${link(p.url, `#${p.pr}`)} ${esc(p.title)}
      <span class="src">${esc(p.author)} · ${esc(p.tickets.join(", ") || "no ticket")}${p.link.includes("hard") ? "" : " · linked by " + esc(p.link.join(", "))}</span></li>`).join("")}</ol></div>
    <div><h3>Diverged · ${r.diverged.length}</h3><ol>${r.diverged.map((d) => `<li style="--k:${k++}"><b>${esc(d.feature_name)}</b>: decided “${esc(d.requirement_text)}”
      <span class="src">${esc(d.ticket)} still says “${esc(d.ticket_text)}”${d.stale_prs.length ? ` · ${d.stale_prs.map((p) => "#" + p.pr).join(", ")} shipped old version` : ""}</span></li>`).join("") || "<li>Nothing diverged</li>"}</ol></div>
  </div>`;
}

async function loadSprints() {
  const ss = await api("/api/sprints");
  $("#sprint-tabs").innerHTML = ss.map((s) => `<button data-sprint="${esc(s.id)}">${esc(s.name)}</button>`).join("");
  if (ss.length) await loadRetro(ss[0].id);
}

/* ---------- spec ---------- */
async function spec(feature, btn) {
  if (btn) btn.disabled = true;
  try {
    const r = await api("/api/spec", { feature });
    $("#spec-sec").hidden = false;
    $("#spec-doc").textContent = r.markdown;
    $("#spec-engine").textContent = `Generated by ${r.engine} from graph context only. Not executed.`;
    $("#spec-sec").scrollIntoView({ behavior: "smooth" });
  } finally { if (btn) btn.disabled = false; }
}

/* ---------- simulate ---------- */
async function simulate(e) {
  e.preventDefault();
  const btn = e.submitter; btn.disabled = true;
  $("#sim-result").innerHTML = `<p class="result-line thinking">Running live drift monitor</p>`;
  try {
    const r = await api("/api/simulate", { text: $("#sim-text").value, author: $("#sim-author").value,
      platform: $("#sim-platform").value, channel: $("#sim-channel").value });
    $("#sim-result").innerHTML = `<div class="result-line">
        <span class="badge ${r.status === "drift" ? "warn" : ""}">${esc(r.status)}</span>
        <span>${r.feature ? `feature <b>${esc(r.feature)}</b> via ${esc(r.via)}` : "no feature matched"}</span>
        ${r.ticket ? `<span>ticket <b>${esc(r.ticket)}</b></span>` : ""}
        <span>classified <b>${esc(r.classification?.kind)}</b></span></div>
      ${r.path ? renderPath(r.path) : ""}
      ${r.alert ? `<div class="alertbox">${esc(r.alert.replace(/:warning:\s*/g, "⚠ ").replace(/\*/g, ""))}</div>` : ""}`;
    if (r.status === "drift") { loadDrift(); loadStats(); if (r.feature) showGraph(r.feature); }
  } catch (err) {
    $("#sim-result").innerHTML = `<p class="error">${esc(err.message)}</p>`;
  } finally { btn.disabled = false; }
}

/* ---------- reveal on scroll ---------- */
const io = "IntersectionObserver" in window
  ? new IntersectionObserver((es) => es.forEach((x) => { if (x.isIntersecting) { x.target.classList.add("in"); io.unobserve(x.target); } }), { threshold: 0.08 })
  : null;
function observeReveals() {
  document.querySelectorAll(".reveal:not(.in)").forEach((el) => (io ? io.observe(el) : el.classList.add("in")));
}
document.querySelectorAll(".sec__label, .sec__body").forEach((el) => el.classList.add("reveal"));

/* ---------- wiring ---------- */
document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-graph],[data-spec],[data-q],[data-sprint]");
  if (!t) return;
  if (t.dataset.graph) { showGraph(t.dataset.graph); $("#graph-sec").scrollIntoView({ behavior: "smooth" }); }
  if (t.dataset.spec) spec(t.dataset.spec, t);
  if (t.dataset.q) ask(t.dataset.q);
  if (t.dataset.sprint) loadRetro(t.dataset.sprint);
});
$("#feature-select").addEventListener("change", (e) => showGraph(e.target.value));
$("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); const q = $("#ask-input").value.trim(); if (q) ask(q); });
$("#sim-form").addEventListener("submit", simulate);
["maya", "arjun", "sofia", "dev", "kenji", "priya", "liam", "zara"].forEach((p) => $("#sim-author").insertAdjacentHTML("beforeend", `<option>${p}</option>`));

/* loader tracks real data loading */
(async () => {
  const tasks = [loadStats(), loadDrift(), loadFeatures(), loadSprints()];
  let done = 0;
  const tick = () => { done++; const p = Math.round((done / tasks.length) * 100); $("#loader-pct").textContent = `${p}%`; $("#loader-bar").style.width = `${p}%`; };
  await Promise.allSettled(tasks.map((t) => t.then(tick, tick)));
  setTimeout(() => { $("#loader").classList.add("done"); observeReveals(); }, 250);
  setTimeout(() => $("#loader").remove(), 900);
})();

/* ?static: no animations (screenshots, slow machines) */
if (new URLSearchParams(location.search).has("static")) {
  document.documentElement.classList.add("static");
  document.querySelectorAll(".reveal").forEach((el) => el.classList.add("in"));
}
