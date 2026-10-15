const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const link = (url, text) => (url && !url.startsWith("scenario://") ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text));

async function api(path, body) {
  const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const TYPES = { Feature: "--n-feature", Ticket: "--n-ticket", Requirement: "--n-req", Message: "--n-msg", PullRequest: "--n-pr", Person: "--n-person" };

async function loadStats() {
  const s = await api("/api/stats");
  const total = (xs) => xs.reduce((a, x) => a + x.n, 0);
  $("#stats").innerHTML = `<span class="stat"><b>${total(s.nodes)}</b> nodes</span><span class="stat"><b>${total(s.relationships)}</b> relationships</span>` +
    s.nodes.slice(0, 4).map((n) => `<span class="stat">${esc(n.label)} <b>${n.n}</b></span>`).join("");
}

async function loadDrift() {
  const rows = await api("/api/drift");
  if (!rows.length) { $("#drift").innerHTML = `<p class="ok">No open drift. Tickets and PRs match the latest decisions.</p>`; return; }
  $("#drift").innerHTML = rows.map((d) => `
    <div class="drift">
      <h3>${esc(d.feature_name)} <span class="badge warn">${esc(d.ticket)}</span></h3>
      <div class="muted">${esc(d.changed_by)} changed it in ${link(d.message_url, `${d.source} #${d.channel}`)} on ${esc(d.changed_at.slice(0, 10))}</div>
      <div class="cols">
        <div><div class="label">Latest decision</div><blockquote>${esc(d.requirement_text)}</blockquote></div>
        <div><div class="label">${esc(d.ticket)} still says</div><blockquote>${esc(d.ticket_text)}</blockquote></div>
      </div>
      ${d.stale_prs.length ? `<div><span class="label">Shipped the old version:</span> ${d.stale_prs.map((p) => link(p.url, `#${p.pr} ${p.title}`)).join(", ")}</div>` : ""}
      <div class="path">${esc(d.path)}</div>
      <div class="actions">
        <button class="secondary" data-graph="${esc(d.feature)}">Show in graph</button>
        <button data-spec="${esc(d.feature)}">Generate spec</button>
      </div>
    </div>`).join("");
}

let cy;
async function loadFeatures() {
  const fs = await api("/api/features");
  $("#feature-select").innerHTML = fs.map((f) => `<option value="${esc(f.id)}">${esc(f.name)}${f.drift ? " ⚠" : ""}</option>`).join("");
  $("#legend").innerHTML = Object.entries(TYPES).map(([t, v]) => `<span><i style="background:${css(v)}"></i>${t}</span>`).join("") +
    `<span><i style="background:${css("--warn")}"></i>drifted requirement</span>`;
  if (fs.length) showGraph(fs.find((f) => f.drift)?.id || fs[0].id);
}

async function showGraph(feature) {
  $("#feature-select").value = feature;
  const g = await api(`/api/features/${encodeURIComponent(feature)}/graph`);
  const els = [
    ...g.nodes.map((n) => ({ data: { ...n, color: n.drift ? css("--warn") : css(TYPES[n.type] || "--muted") } })),
    ...g.edges.map((e, i) => ({ data: { id: `e${i}`, source: e.from, target: e.to, label: e.rel } })),
  ];
  if (cy) cy.destroy();
  cy = cytoscape({
    container: $("#graph"), elements: els,
    style: [
      { selector: "node", style: { "background-color": "data(color)", label: "data(label)", "font-size": 9, color: css("--fg"),
          "text-wrap": "ellipsis", "text-max-width": 110, width: 18, height: 18 } },
      { selector: "node[type='Feature']", style: { width: 30, height: 30, "font-size": 11, "font-weight": "bold" } },
      { selector: "node[?drift]", style: { "border-width": 3, "border-color": css("--warn"), width: 26, height: 26 } },
      { selector: "edge", style: { width: 1.2, "line-color": css("--border"), "target-arrow-color": css("--muted"), "target-arrow-shape": "triangle",
          "curve-style": "bezier", label: "data(label)", "font-size": 7, color: css("--muted"), "text-rotation": "autorotate" } },
    ],
    layout: { name: "cose", animate: false, padding: 20, nodeRepulsion: 9000, idealEdgeLength: 90 },
  });
  cy.on("tap", "node", (e) => {
    const d = e.target.data();
    $("#graph-detail").innerHTML = `<b>${esc(d.type)}</b> ${esc(d.id)}${d.drift ? ' <span class="badge warn">drift</span>' : ""}<br>${esc(d.text || "")}`;
  });
}

async function ask(q) {
  $("#ask-input").value = q;
  $("#answer").innerHTML = `<p class="muted">Thinking with graph tools…</p>`;
  try {
    const r = await api("/api/ask", { question: q });
    $("#answer").innerHTML = `<div class="answer">${esc(r.answer)}</div>
      <div class="label" style="margin-top:10px">Tools used</div><div class="muted">${r.tool_calls.map((t) => esc(`${t.tool}(${JSON.stringify(t.args)})`)).join(", ") || "none"}</div>
      ${r.paths.length ? `<div class="label" style="margin-top:10px">Graph paths</div>${r.paths.slice(0, 6).map((p) => `<div class="path">${esc(p)}</div>`).join("")}` : ""}`;
  } catch (e) {
    $("#answer").innerHTML = `<p class="error">${esc(e.message)}</p>`;
  }
}

async function loadRetro(sprint) {
  document.querySelectorAll("#sprint-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.sprint === sprint));
  const r = await api(`/api/retro/${sprint}`);
  const status = (d) => d.shipped_in.length ? `<span class="badge ok">shipped in ${d.shipped_in.map((n) => "#" + n).join(", ")}</span>`
    : d.superseded_by === "ticket" ? `<span class="badge">in ticket</span>` : `<span class="badge warn">not in ticket · not shipped</span>`;
  $("#retro").innerHTML = `<div class="retro-grid">
    <div><h3>What we decided</h3><ul>${r.decided.map((d) => `<li>${esc(d.at.slice(0, 10))} <b>${esc(d.by)}</b>: ${esc(d.text)} ${status(d)}<br>
      <span class="muted">${esc(d.feature)} · ${esc(d.ticket)} · ${link(d.source, `${d.platform} #${d.channel}`)}</span></li>`).join("") || "<li class='muted'>No decisions in chat</li>"}</ul></div>
    <div><h3>What we shipped</h3><ul>${r.shipped.map((p) => `<li>${link(p.url, `#${p.pr}`)} ${esc(p.title)} <span class="muted">by ${esc(p.author)} · ${esc(p.tickets.join(", ") || "no ticket")}${p.link.includes("hard") ? "" : " · linked by " + esc(p.link.join(", "))}</span></li>`).join("")}</ul></div>
    <div><h3>Where they diverge</h3><ul>${r.diverged.map((d) => `<li><b>${esc(d.feature_name)}</b>: decided “${esc(d.requirement_text)}” but ${esc(d.ticket)} still says “${esc(d.ticket_text)}”${d.stale_prs.length ? `; ${d.stale_prs.map((p) => "#" + p.pr).join(", ")} shipped the old version` : ""}.</li>`).join("") || "<li class='ok'>Nothing diverged</li>"}</ul></div>
  </div>`;
}

async function loadSprints() {
  const ss = await api("/api/sprints");
  $("#sprint-tabs").innerHTML = ss.map((s) => `<button data-sprint="${esc(s.id)}">${esc(s.name)}</button>`).join("");
  if (ss.length) loadRetro(ss[0].id);
}

async function spec(feature, btn) {
  if (btn) btn.disabled = true;
  try {
    const r = await api("/api/spec", { feature });
    $("#spec-card").hidden = false;
    $("#spec").textContent = r.markdown;
    $("#spec-engine").textContent = `generated by ${r.engine} from graph context only`;
    $("#spec-card").scrollIntoView({ behavior: "smooth" });
  } finally { if (btn) btn.disabled = false; }
}

async function simulate(e) {
  e.preventDefault();
  const btn = e.submitter; btn.disabled = true;
  $("#sim-result").innerHTML = `<p class="muted">Running drift monitor…</p>`;
  try {
    const r = await api("/api/simulate", { text: $("#sim-text").value, author: $("#sim-author").value,
      platform: $("#sim-platform").value, channel: $("#sim-channel").value });
    const head = `<p><span class="badge ${r.status === "drift" ? "warn" : ""}">${esc(r.status)}</span>
      ${r.feature ? `feature <b>${esc(r.feature)}</b> (via ${esc(r.via)})` : "no feature matched"}${r.ticket ? ` · ticket <b>${esc(r.ticket)}</b>` : ""}
      · classified as <b>${esc(r.classification?.kind)}</b></p>`;
    $("#sim-result").innerHTML = head + (r.alert ? `<div class="path">${esc(r.alert)}</div>` : "");
    if (r.status === "drift") { loadDrift(); loadStats(); if (r.feature) showGraph(r.feature); }
  } catch (err) {
    $("#sim-result").innerHTML = `<p class="error">${esc(err.message)}</p>`;
  } finally { btn.disabled = false; }
}

document.addEventListener("click", (e) => {
  const t = e.target;
  if (t.dataset.graph) { showGraph(t.dataset.graph); $("#graph").scrollIntoView({ behavior: "smooth", block: "center" }); }
  if (t.dataset.spec) spec(t.dataset.spec, t);
  if (t.dataset.q) ask(t.dataset.q);
  if (t.dataset.sprint) loadRetro(t.dataset.sprint);
});
$("#feature-select").addEventListener("change", (e) => showGraph(e.target.value));
$("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); const q = $("#ask-input").value.trim(); if (q) ask(q); });
$("#sim-form").addEventListener("submit", simulate);
["maya", "arjun", "sofia", "dev", "kenji", "priya", "liam", "zara"].forEach((p) => $("#sim-author").insertAdjacentHTML("beforeend", `<option>${p}</option>`));

loadStats(); loadDrift(); loadFeatures(); loadSprints();
