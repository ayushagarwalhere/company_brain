const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const link = (url, text) => (url && !url.startsWith("scenario://") ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
let cy, currentFeature;
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
  const tokens = str.split(/(<-\[:[A-Z_|]+\]-|-\[:[A-Z_|]+\]->|\s;\s)/);
  return `<div class="path">${tokens.map((t) => {
    if (!t) return "";
    if (t.trim() === ";") return `<span class="sep"></span>`;
    const rel = t.match(/^(<-|-)\[:([A-Z_|]+)\](->|-)$/);
    if (rel) return `<span class="r">${rel[1] === "<-" ? "←" : ""}${esc(rel[2])}${rel[3] === "->" ? "→" : ""}</span>`;
    return t.split(/(\([^)]*\))/).map((part) => {
      const m = part.match(/^\((\w+)\s+([\s\S]*)\)$/);
      if (m) return `<span class="n" style="color:${css(TYPES[m[1]] || "--muted")}" title="${esc(m[2])}"><b>${esc(m[1])}</b>${esc(m[2])}</span>`;
      const txt = part.trim().replace(/^,\s*/, "");
      return txt ? `<span class="t">${esc(txt)}</span>` : "";
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
  $("#syslog").innerHTML = log.map(([i, t]) => `<li><b>${i}</b>${esc(t)}</li>`).join("");
  [...document.querySelectorAll("#syslog li")].forEach((li, i) => setTimeout(() => li.classList.add("on"), 250 + i * 140));
}

/* ---------- drift ---------- */
async function loadDrift() {
  const rows = await api("/api/drift");
  $("#spec-drift").innerHTML = rows.length
    ? `<span class="warn">${rows.length} requirement${rows.length > 1 ? "s" : ""} · ${[...new Set(rows.map((d) => d.feature_name))].join(", ")}</span>`
    : "none";
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
    $("#answer").innerHTML = `<p class="error">${esc(e.message)}</p>`;
  }
}

/* ---------- retro ---------- */
async function loadRetro(sprint) {
  document.querySelectorAll("#sprint-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.sprint === sprint));
  const r = await api(`/api/retro/${sprint}`);
  const status = (d) => d.shipped_in.length ? `<span class="badge ok">shipped ${d.shipped_in.map((n) => "#" + n).join(", ")}</span>`
    : d.superseded_by === "ticket" ? `<span class="badge">in ticket</span>` : `<span class="badge warn">not shipped</span>`;
  $("#retro").innerHTML = `<div class="retro-cols">
    <div><h3>Decided · ${r.decided.length}</h3><ol>${r.decided.map((d) => `<li>${esc(d.text)} ${status(d)}
      <span class="src">${esc(d.by)} · ${esc(d.at.slice(0, 10))} · ${esc(d.ticket)} · ${link(d.source, `${d.platform} #${d.channel}`)}</span></li>`).join("") || "<li>No decisions in chat</li>"}</ol></div>
    <div><h3>Shipped · ${r.shipped.length}</h3><ol>${r.shipped.map((p) => `<li>${link(p.url, `#${p.pr}`)} ${esc(p.title)}
      <span class="src">${esc(p.author)} · ${esc(p.tickets.join(", ") || "no ticket")}${p.link.includes("hard") ? "" : " · linked by " + esc(p.link.join(", "))}</span></li>`).join("")}</ol></div>
    <div><h3>Diverged · ${r.diverged.length}</h3><ol>${r.diverged.map((d) => `<li><b>${esc(d.feature_name)}</b>: decided “${esc(d.requirement_text)}”
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
