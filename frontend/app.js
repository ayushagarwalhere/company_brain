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
    ? ({ oracle: `<span class="warn">answer-key oracle (test mode)</span>`, heuristic: "rule-based heuristics · no LLM",
         deepseek: "DeepSeek LLM" }[s.build.extractor] || esc(s.build.extractor))
    : "not recorded";
  $("#spec-llm").innerHTML = s.llm?.available
    ? `${esc(s.llm.model)} · online`
    : `<span class="muted">offline (${esc(s.llm?.reason || "unknown")}) · rules agent + heuristic extractor answering</span>`;
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
      <div class="violation__meta"><button class="person-link" data-person="${esc(d.changed_by)}">${esc(d.changed_by)}</button> changed the requirement in ${link(d.message_url, `${d.source} #${d.channel}`)}. ${esc(d.ticket)} was never updated.</div>
      <div class="diff">
        <div><span class="mono">${esc(d.ticket)} still says</span><p>${esc(d.ticket_text)}</p></div>
        <div class="now"><span class="mono">Decided in chat</span><p>${esc(d.requirement_text)}</p></div>
      </div>
      ${d.stale_prs.length ? `<div class="stale">Shipped the old version: ${d.stale_prs.map((p) => link(p.url, `#${p.pr} ${p.title}`)).join(", ")}</div>` : ""}
      <div class="mono kicker">Evidence path</div>
      ${renderPath(d.path)}
      <div class="actions">
        <button class="btn" data-act="write-to-ticket" data-req="${esc(d.requirement)}" title="Make the decided requirement the ticket's next version">Write to ${esc(d.ticket)}</button>
        <button class="btn btn--ghost" data-act="dismiss" data-req="${esc(d.requirement)}" title="Record a decision to keep the old scope">Keep old scope</button>
        <button class="btn btn--ghost" data-graph="${esc(d.feature)}">Show in graph</button>
        <button class="btn btn--ghost" data-spec="${esc(d.feature)}">Generate spec</button>
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

/* ---------- timeline ---------- */
let view = "graph";
function setView(v) {
  view = v;
  document.querySelectorAll("[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  $("#timeline").hidden = v !== "timeline";
  $("#canvas").hidden = v !== "graph";
  $("#node-detail").hidden = v !== "graph";
  if (v === "timeline" && currentFeature) loadTimeline(currentFeature);
  if (v === "graph" && cy) cy.resize().fit(undefined, 30);
}

async function loadTimeline(feature) {
  const evs = await api(`/api/features/${encodeURIComponent(feature)}/timeline`);
  if (!evs.length) { $("#timeline").innerHTML = `<p class="muted">No events.</p>`; return; }
  const t0 = evs[0].at, t1 = evs[evs.length - 1].at, span = Math.max(1, t1 - t0);
  const pad = 0.04;
  const x = (t) => `${(pad + (1 - 2 * pad) * ((t - t0) / span)) * 100}%`;
  const DAY = 86400000;
  const ticks = [];
  for (let t = Math.ceil(t0 / DAY) * DAY; t <= t1; t += DAY * Math.max(1, Math.round(span / DAY / 8))) ticks.push(t);
  const fmt = (t) => new Date(t).toISOString().slice(5, 10);
  const lanes = [["chat", "Chat"], ["ticket", "Tickets"], ["pr", "PRs"]];
  let k = 0;
  const drift = evs.find((e) => e.drift);
  const gap = (label) => (drift ? `<div class="tl__gap" style="left:${x(drift.at)};right:0">${label ? "<span>ticket + PRs never caught up</span>" : ""}</div>` : "");
  $("#timeline").innerHTML = `
    <div class="tl__axis">${ticks.map((t) => `<span class="tl__tick" style="left:${x(t)}">${fmt(t)}</span>`).join("")}</div>
    ${lanes.map(([lane, label]) => `<div class="tl__lane" data-label="${label}">${gap(lane === "pr")}
      ${evs.map((e, i) => e.lane !== lane ? "" : `<button class="tl__ev tl__ev--${lane}${e.drift ? " tl__ev--drift" : ""}${e.superseded ? " tl__ev--super" : ""}"
         style="left:${x(e.at)};--k:${k++}" data-ev="${i}" aria-label="${esc(e.title)}"></button>`).join("")}</div>`).join("")}
    <dl class="spec tl__detail" id="tl-detail"><div><dt>Event</dt><dd>Hover or click a marker. Faded markers were superseded by a later version.</dd></div></dl>`;
  const show = (el) => {
    const e = evs[+el.dataset.ev];
    document.querySelectorAll(".tl__ev.sel").forEach((n) => n.classList.remove("sel"));
    el.classList.add("sel");
    $("#tl-detail").innerHTML = `
      <div><dt>When</dt><dd>${esc(e.iso.replace("T", " ").slice(0, 16))} UTC</dd></div>
      <div><dt>${esc(e.lane === "pr" ? "Pull request" : e.lane === "chat" ? "Chat change" : "Ticket version")}</dt><dd>${esc(e.title)}${e.who ? ` · ${esc(e.who)}` : ""}${e.ref && e.lane === "chat" ? ` → amends ${esc(e.ref)}` : ""}</dd></div>
      <div><dt>Says</dt><dd>${esc(e.text)}</dd></div>
      <div><dt>Status</dt><dd>${e.drift ? '<span class="warn">drift: newest, unimplemented, ticket never updated</span>' : e.superseded ? "superseded by a later version" : e.lane === "pr" ? "shipped" : "current"}</dd></div>`;
  };
  document.querySelectorAll(".tl__ev").forEach((el) => { el.addEventListener("mouseenter", () => show(el)); el.addEventListener("click", () => show(el)); });
  const first = document.querySelector(".tl__ev--drift") || document.querySelector(".tl__ev");
  if (first) show(first);
}

/* ---------- coverage & risk ---------- */
async function loadCoverage() {
  const c = await api("/api/coverage");
  const card = (title, list, sub, fmt) => `<div class="cov__card reveal"><span class="mono">${esc(title)}</span><b class="big">${list.length}</b>
    <small class="muted">${esc(sub)}</small><ul>${list.slice(0, 5).map((x) => `<li>${fmt(x)}</li>`).join("")}</ul></div>`;
  $("#coverage-body").innerHTML = `
    <div class="cov">
      ${card("PRs with no ticket", c.orphan_prs, "shipped work nobody can trace", (x) => `${link(x.url, "#" + x.pr)} ${esc(x.title)} <span class="muted">· ${esc(x.author)}</span>`)}
      ${card("Done, no PR", c.done_without_pr, "closed tickets with no linked code", (x) => `${esc(x.ticket)} ${esc(x.title)}`)}
      ${card("Never discussed", c.undiscussed_tickets, "tickets no message mentions", (x) => `${esc(x.ticket)} ${esc(x.title)} <span class="muted">· ${esc(x.state)}</span>`)}
    </div>
    <div class="mono kicker">Knowledge concentration · share of a feature's involvement held by one person</div>
    ${c.knowledge_risk.map((r) => `<div class="risk__row">
        <div><b>${esc(r.name)}</b><div class="muted" style="font-size:13px">${esc(r.top_person)} · ${r.people} people involved</div></div>
        <div class="risk__bar"><span class="${r.top_share >= 0.5 ? "hot" : ""}" data-w="${Math.round(r.top_share * 100)}"></span></div>
        <span class="mono">${Math.round(r.top_share * 100)}%${r.top_share >= 0.5 ? " · bus factor 1" : ""}</span>
      </div>`).join("")}`;
  requestAnimationFrame(() => setTimeout(() => document.querySelectorAll(".risk__bar span").forEach((b) => (b.style.width = b.dataset.w + "%")), 120));
  observeReveals();
}

/* ---------- closing the loop on drift ---------- */
async function refreshAll() {
  await Promise.allSettled([loadDrift(), loadStats(), loadCoverage(), loadSprints()]);
  if (currentFeature) { showGraph(currentFeature); if (view === "timeline") loadTimeline(currentFeature); }
}

async function driftAction(act, requirement, btn) {
  const card = btn.closest(".violation");
  btn.disabled = true;
  try {
    const actor = $("#sim-author")?.value || "maya";
    const r = await api(`/api/drift/${act}`, { requirement, actor });
    if (card) {
      card.classList.add("resolving");
      card.insertAdjacentHTML("beforeend", `<div class="resolved-note mono">${act === "dismiss"
        ? `Dismissed by ${esc(r.by)}: (${esc(r.by)})-[:MADE]->(Decision)-[:DISMISSES]->(Requirement)`
        : `Written to ${esc(r.ticket)} as ${esc(r.version)}: (Ticket)-[:STATES]->(new version)-[:SUPERSEDES]->(chat requirement)`}</div>`);
      await new Promise((res) => setTimeout(res, 1400));
    }
    await refreshAll();
  } catch (e) {
    btn.disabled = false;
    alert(e.message);
  }
}

async function resetDemo(btn) {
  btn.disabled = true; btn.textContent = "Rebuilding graph…";
  try { await api("/api/demo/reset", {}); await refreshAll(); $("#sim-result").innerHTML = ""; }
  finally { btn.disabled = false; btn.textContent = "Reset demo data"; }
}

/* ---------- ask ---------- */
async function ask(q) {
  $("#ask-input").value = q;
  $("#answer").innerHTML = `<p class="answer thinking">Querying graph tools</p>`;
  try {
    const r = await api("/api/ask", { question: q });
    const body = r.answer.split("\n\nEvidence:")[0];
    $("#answer").innerHTML = `${r.engine === "rules" ? `<div class="notice"><b>Rules agent</b>: the LLM is unavailable${r.fallback_reason ? ` (${esc(r.fallback_reason)})` : ""}, so the question is routed to graph tools directly and the answer is assembled from their rows.</div>` : ""}
      <div class="answer">${esc(body)}</div>
      <div class="mono kicker">Tools called</div>
      <div class="chips" style="margin:6px 0 0">${r.tool_calls.map((t) => `<span class="chip mono">${esc(t.tool)} ${esc(Object.values(t.args).join(", "))}</span>`).join("") || "<span class='mono'>none</span>"}</div>
      ${r.paths.length ? `<div class="mono kicker">Graph paths</div>${r.paths.slice(0, 6).map(renderPath).join("")}` : ""}`;
  } catch (e) {
    $("#answer").innerHTML = `<p class="error">${esc(e.message)}</p>`;
  }
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
  const status = (d) => d.dismissed_by ? `<span class="badge">dismissed · ${esc(d.dismissed_by)}</span>` : d.shipped_in.length ? `<span class="badge ok">shipped ${d.shipped_in.map((n) => "#" + n).join(", ")}</span>`
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
    if (r.status === "drift") { loadDrift(); loadStats(); loadCoverage(); if (r.feature) { showGraph(r.feature); if (view === "timeline") loadTimeline(r.feature); } }
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
  const t = e.target.closest("[data-graph],[data-spec],[data-q],[data-sprint],[data-view],[data-act]");
  if (!t) return;
  if (t.dataset.act) driftAction(t.dataset.act, t.dataset.req, t);
  if (t.dataset.view) setView(t.dataset.view);
  if (t.dataset.graph) { showGraph(t.dataset.graph); $("#graph-sec").scrollIntoView({ behavior: "smooth" }); }
  if (t.dataset.spec) spec(t.dataset.spec, t);
  if (t.dataset.q) ask(t.dataset.q);
  if (t.dataset.sprint) loadRetro(t.dataset.sprint);
});
$("#feature-select").addEventListener("change", (e) => { showGraph(e.target.value); if (view === "timeline") loadTimeline(e.target.value); });
$("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); const q = $("#ask-input").value.trim(); if (q) ask(q); });
$("#sim-form").addEventListener("submit", simulate);
["maya", "arjun", "sofia", "dev", "kenji", "priya", "liam", "zara"].forEach((p) => $("#sim-author").insertAdjacentHTML("beforeend", `<option>${p}</option>`));

/* loader tracks real data loading */
(async () => {
  const tasks = [loadStats(), loadDrift(), loadFeatures(), loadSprints(), loadCoverage()];
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

/* ?view=timeline deep link */
if (new URLSearchParams(location.search).get("view") === "timeline") {
  const wait = setInterval(() => { if (currentFeature) { clearInterval(wait); setView("timeline"); } }, 100);
}

$("#reset-demo")?.addEventListener("click", (e) => resetDemo(e.currentTarget));


/* ---------- command palette: FalkorDB full-text search ---------- */
let palIdx = 0, palRows = [], palTimer;
function openPalette() {
  $("#palette").hidden = false;
  $("#palette-input").value = "";
  $("#palette-list").innerHTML = `<li class="palette__empty">Try “breach email”, “maya”, “BD-101”, “#7”, “export”…</li>`;
  setTimeout(() => $("#palette-input").focus(), 10);
}
function closePalette() { $("#palette").hidden = true; }
function renderPalette() {
  $("#palette-list").innerHTML = palRows.length ? palRows.map((r, i) => `
    <li class="${i === palIdx ? "on" : ""}" data-pal="${i}">
      <span class="mono" style="color:${css(TYPES[r.type] || "--muted")}">${esc(r.type)}</span>
      <span class="lab">${esc(r.type === "Message" ? r.label : `${r.id} · ${r.label || ""}`)}</span>
      <span class="go mono">${r.type === "Person" ? "profile" : r.feature ? "graph" : "neighbours"} ↵</span>
    </li>`).join("") : `<li class="palette__empty">No matches.</li>`;
}
async function runSearch(q) {
  if (!q.trim()) { palRows = []; renderPalette(); return; }
  palRows = await api(`/api/search?q=${encodeURIComponent(q)}`);
  palIdx = 0;
  renderPalette();
}
async function choose(r) {
  closePalette();
  if (r.type === "Person") return openPerson(r.id);
  setView("graph");
  if (r.feature) await showGraph(r.feature);
  $("#graph-sec").scrollIntoView({ behavior: "smooth" });
  setTimeout(() => focusNode(r.id), 400);
}
$("#search-open").addEventListener("click", openPalette);
$("#palette").addEventListener("click", (e) => {
  if (e.target.id === "palette") return closePalette();
  const li = e.target.closest("[data-pal]");
  if (li) choose(palRows[+li.dataset.pal]);
});
$("#palette-input").addEventListener("input", (e) => { clearTimeout(palTimer); palTimer = setTimeout(() => runSearch(e.target.value), 140); });
$("#palette-input").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { palIdx = Math.min(palRows.length - 1, palIdx + 1); renderPalette(); e.preventDefault(); }
  if (e.key === "ArrowUp") { palIdx = Math.max(0, palIdx - 1); renderPalette(); e.preventDefault(); }
  if (e.key === "Enter" && palRows[palIdx]) choose(palRows[palIdx]);
});
document.addEventListener("keydown", (e) => {
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "");
  if ((e.key === "/" && !typing) || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k")) { e.preventDefault(); openPalette(); }
  if (e.key === "Escape") { closePalette(); $("#drawer").hidden = true; }
});

/* ---------- graph: focus + expand neighbours ---------- */
async function focusNode(id) {
  if (!cy) return;
  let n = cy.getElementById(id);
  if (!n.length) await expandNode(id, true);
  n = cy.getElementById(id);
  if (!n.length) return;
  cy.animate({ center: { eles: n }, zoom: 1.4 }, { duration: 500 });
  cy.$(":selected").unselect(); n.select(); n.emit("tap");
}
async function expandNode(id, includeSelf) {
  const g = await api(`/api/nodes/${encodeURIComponent(id)}/neighbors`);
  const add = [];
  if (includeSelf && !cy.getElementById(id).length) {
    const hit = palRows.find((r) => r.id === id);
    add.push({ group: "nodes", data: { id, label: id, type: hit?.type || "Message", text: hit?.label, color: css(TYPES[hit?.type] || "--muted") } });
  }
  for (const n of g.nodes) if (!cy.getElementById(n.id).length) add.push({ group: "nodes", data: { ...n, color: css(TYPES[n.type] || "--muted") } });
  for (const e of g.edges) {
    const eid = `x:${e.from}:${e.rel}:${e.to}`;
    if (!cy.getElementById(eid).length) add.push({ group: "edges", data: { id: eid, source: e.from, target: e.to, label: e.rel } });
  }
  if (!add.length) return;
  const center = cy.getElementById(id).position() || { x: 0, y: 0 };
  const added = cy.add(add.map((x) => (x.group === "nodes" ? { ...x, position: { x: center.x + (Math.random() - .5) * 160, y: center.y + (Math.random() - .5) * 160 } } : x)));
  added.nodes().style("opacity", 0).animate({ style: { opacity: 1 } }, { duration: 400 });
  cy.layout({ name: "cose", animate: true, animationDuration: 600, fit: false, randomize: false, nodeRepulsion: 18000, idealEdgeLength: 80 }).run();
  $("#canvas-tag").textContent = `${cy.nodes().length} nodes · ${cy.edges().length} edges · expanded ${id}`;
}
function wireGraphExplore() {
  if (!cy || cy._explore) return;
  cy._explore = true;
  cy.on("dbltap", "node", (e) => {
    const d = e.target.data();
    if (d.type === "Person") return openPerson(d.id);
    expandNode(d.id);
  });
}
setInterval(wireGraphExplore, 500);
document.querySelector(".canvas")?.insertAdjacentHTML("beforeend", `<div class="canvas__hint mono">double-click a node to expand</div>`);

/* ---------- person profile drawer ---------- */
async function openPerson(pid) {
  const p = await api(`/api/people/${encodeURIComponent(pid)}`);
  const max = Math.max(1, ...p.features.map((f) => f.score));
  $("#drawer-body").innerHTML = `
    <span class="mono" style="color:var(--accent)">Person · ${esc(p.id)}</span>
    <h3>${esc(p.name)}</h3><div class="role">${esc(p.role)} · ${p.messages} messages</div>
    ${p.drift_caused.map((d) => `<div class="warnbox">Their decision on ${esc(d.changed_at.slice(0, 10))} (“${esc(d.requirement_text)}”) never reached ${esc(d.ticket)}.</div>`).join("")}
    ${p.stale_work.map((d) => `<div class="warnbox">Owns ${esc(d.ticket)}, which is stale: ${esc(d.changed_by)} changed it on ${esc(d.changed_at.slice(0, 10))}.</div>`).join("")}
    <div class="mono kicker">Knows about</div>
    <ul>${p.features.map((f) => `<li class="fbar"><b>${esc(f.name)}</b><div class="risk__bar"><span style="width:${Math.round(f.score / max * 100)}%"></span></div><span class="mono">${f.score}</span></li>`).join("") || "<li>No feature involvement</li>"}</ul>
    <div class="mono kicker">Owns · ${p.owns.length}</div>
    <ul>${p.owns.map((t) => `<li><b>${esc(t.ticket)}</b> ${esc(t.title)} <span class="muted">· ${esc(t.state)}${t.feature ? " · " + esc(t.feature) : ""}</span></li>`).join("") || "<li>Nothing assigned</li>"}</ul>
    <div class="mono kicker">Shipped · ${p.prs.length}</div>
    <ul>${p.prs.map((x) => `<li>${link(x.url, "#" + x.pr)} ${esc(x.title)} <span class="muted">· ${esc(x.tickets.join(", ") || "no ticket")}</span></li>`).join("") || "<li>No PRs</li>"}</ul>
    <div class="mono kicker">Decided · ${p.decisions.length}</div>
    <ul>${p.decisions.map((d) => `<li><span class="muted">${esc((d.at || "").slice(0, 10))} · ${esc(d.ticket || "")}${d.kind === "dismissal" ? " · dismissal" : ""}</span><br>${esc(d.text)}</li>`).join("") || "<li>No decisions recorded</li>"}</ul>`;
  $("#drawer").hidden = false;
  $("#drawer").scrollTop = 0;
}
$("#drawer-close").addEventListener("click", () => ($("#drawer").hidden = true));
document.addEventListener("click", (e) => {
  const pl = e.target.closest("[data-person]");
  if (pl) { e.preventDefault(); openPerson(pl.dataset.person); }
});

/* deep links: ?person=maya opens a profile, ?q=breach opens search */
{
  const qs = new URLSearchParams(location.search);
  if (qs.get("person")) setTimeout(() => openPerson(qs.get("person")), 600);
  if (qs.get("q")) setTimeout(() => { openPalette(); $("#palette-input").value = qs.get("q"); runSearch(qs.get("q")); }, 600);
}
