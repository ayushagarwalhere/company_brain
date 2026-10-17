import cytoscape, { type Core } from "cytoscape";
import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type GEdge, type GNode, type GraphData, type TimelineEvent } from "../lib/api";
import { useBrain } from "../lib/brain";
import { useStill } from "../lib/fx";
import { cssVar, day, TYPE_VAR, typeColor } from "../lib/ui";
import { Section } from "./Section";

const LEGEND = ["Person", "Message", "Requirement", "Ticket", "PullRequest", "Document"];

function useThemeVersion() {
  const [v, setV] = useState(0);
  useEffect(() => {
    const on = () => setTimeout(() => setV((x) => x + 1), 30);
    addEventListener("themechange", on);
    return () => removeEventListener("themechange", on);
  }, []);
  return v;
}

/* ---------------------------------------------------------------- layout

   Left to right in causal order: who said it -> the message -> the requirement it created ->
   the ticket it amends -> the PRs and docs on that ticket. Within a column, nodes are ordered by
   the ticket they belong to (drifted tickets first), which keeps edges short and uncrossed. */

const COL: Record<string, number> = { Person: 0, Message: 1, Requirement: 2, Ticket: 3, PullRequest: 4, Document: 4, Feature: 3 };
const DX = 230, DY = 66;

type Pos = Record<string, { x: number; y: number }>;

export function layered(g: GraphData): Pos {
  const by = (rel: string) => g.edges.filter((e) => e.rel === rel);
  const drifted = new Set(g.nodes.filter((n) => n.drift).map((n) => n.id));
  const amends = by("AMENDS"), states = by("STATES");
  const ticketOfReq = new Map<string, string>([...states.map((e) => [e.to, e.from] as [string, string]), ...amends.map((e) => [e.from, e.to] as [string, string])]);
  const tickets = g.nodes.filter((n) => n.type === "Ticket").map((n) => n.id)
    .sort((a, b) => Number(amends.some((e) => e.to === b && drifted.has(e.from))) - Number(amends.some((e) => e.to === a && drifted.has(e.from))) || a.localeCompare(b));
  const rank = new Map<string, number>(tickets.map((t, i) => [t, i]));
  const reqs = g.nodes.filter((n) => n.type === "Requirement").map((n) => n.id).sort((a, b) =>
    (rank.get(ticketOfReq.get(a) || "") ?? 99) - (rank.get(ticketOfReq.get(b) || "") ?? 99) || a.localeCompare(b, undefined, { numeric: true }));
  reqs.forEach((r, i) => rank.set(r, i));
  const anchor = (id: string, rels: [string, "from" | "to"][]) => {  // rank of the first linked node already placed
    for (const [rel, side] of rels) for (const e of by(rel)) {
      const self = side === "from" ? e.from : e.to, other = side === "from" ? e.to : e.from;
      if (self === id && rank.has(other)) return rank.get(other)!;
    }
    return 99;
  };
  const cols: string[][] = [[], [], [], [], []];
  cols[2] = reqs;
  cols[3] = tickets;
  const msgs = g.nodes.filter((n) => n.type === "Message").map((n) => n.id).sort((a, b) => anchor(a, [["CHANGES", "from"], ["MENTIONS", "from"]]) - anchor(b, [["CHANGES", "from"], ["MENTIONS", "from"]]));
  msgs.forEach((m, i) => rank.set(m, i));
  cols[1] = msgs;
  cols[0] = g.nodes.filter((n) => n.type === "Person").map((n) => n.id).sort((a, b) => anchor(a, [["POSTED", "from"], ["AUTHORED", "from"]]) - anchor(b, [["POSTED", "from"], ["AUTHORED", "from"]]));
  cols[4] = g.nodes.filter((n) => n.type === "PullRequest" || n.type === "Document").map((n) => n.id)
    .sort((a, b) => anchor(a, [["REFERENCES", "from"], ["MENTIONS", "from"]]) - anchor(b, [["REFERENCES", "from"], ["MENTIONS", "from"]]));
  const tallest = Math.max(...cols.map((c) => c.length), 1);
  const pos: Pos = {};
  cols.forEach((c, x) => c.forEach((id, i) => { pos[id] = { x: x * DX, y: (i - (c.length - 1) / 2) * DY * Math.min(1.6, tallest / Math.max(c.length, 1) * 0.55 + 0.45) }; }));
  const top = Math.min(0, ...Object.values(pos).map((p) => p.y));
  for (const n of g.nodes) if (n.type === "Feature") pos[n.id] = { x: COL.Feature * DX, y: top - DY * 1.3 };
  for (const n of g.nodes) if (!pos[n.id]) pos[n.id] = { x: (COL[n.type] ?? 4) * DX, y: top - DY * 2.4 };
  return pos;
}

/** The drift path: who decided, the message, the unshipped requirement, its ticket, and the PRs/docs still on the old version. */
export function driftPath(g: GraphData): { nodes: Set<string>; edges: Set<string> } {
  const nodes = new Set<string>(), edges = new Set<string>();
  const key = (e: GEdge) => `${e.from}|${e.rel}|${e.to}`;
  const stale = new Set(g.nodes.filter((n) => n.stale).map((n) => n.id));
  for (const r of g.nodes.filter((n) => n.drift)) {
    nodes.add(r.id);
    const add = (e: GEdge) => { edges.add(key(e)); nodes.add(e.from); nodes.add(e.to); };
    const msgs = g.edges.filter((e) => e.rel === "CHANGES" && e.to === r.id);
    msgs.forEach(add);
    g.edges.filter((e) => e.rel === "POSTED" && msgs.some((m) => m.from === e.to)).forEach(add);
    const tks = g.edges.filter((e) => e.rel === "AMENDS" && e.from === r.id);
    tks.forEach(add);
    for (const t of tks) {
      const prs = g.edges.filter((e) => e.rel === "REFERENCES" && e.to === t.to);
      prs.forEach(add);
      g.edges.filter((e) => e.rel === "IMPLEMENTS" && prs.some((p) => p.from === e.from)).forEach(add);
      g.edges.filter((e) => e.rel === "MENTIONS" && e.to === t.to && stale.has(e.from)).forEach(add);
    }
  }
  return { nodes, edges };
}

/** Short, non-overlapping labels; the full text lives in the side panel. */
function shortLabel(n: GNode, g: GraphData, when: Map<string, string>): string {
  if (n.type === "Person") return (n.label || n.id).split(" ")[0].toLowerCase();
  if (n.type === "Message") {
    const who = g.edges.find((e) => e.rel === "POSTED" && e.to === n.id)?.from;
    return [who, when.get(n.id)?.slice(5, 10)].filter(Boolean).join(" · ") || n.id;
  }
  if (n.type === "Requirement") {
    const v = n.id.match(/^req:([A-Z]+-\d+):v(\d+)$/);
    return v ? `${v[1]} v${v[2]}` : n.drift ? "chat · DRIFT" : "chat change";
  }
  if (n.type === "Document") return n.id;
  return n.label || n.id;
}

function styleFor(): cytoscape.StylesheetStyle[] {
  const c = (v: string) => cssVar(v);
  return [
    { selector: "node", style: { "background-color": "data(color)", label: "data(short)", "font-family": "Geist Mono, monospace", "font-size": 10.5,
        color: c("--soft"), "text-wrap": "ellipsis", "text-max-width": "120px", "text-valign": "bottom", "text-margin-y": 6, width: 14, height: 14,
        "transition-property": "opacity, background-color, width, height", "transition-duration": 0.35 } as cytoscape.Css.Node },
    { selector: "node[type='Feature']", style: { width: 22, height: 22, "font-size": 12, color: c("--ink"), "font-family": "Geist, sans-serif", "text-valign": "top", "text-margin-y": -8, shape: "round-rectangle" } },
    { selector: "node[type='Ticket']", style: { shape: "rectangle", width: 18, height: 12 } },
    { selector: "node[type='PullRequest']", style: { shape: "diamond", width: 16, height: 16 } },
    { selector: "node[type='Document']", style: { shape: "tag", width: 16, height: 16 } },
    { selector: "node[type='Person']", style: { width: 12, height: 12 } },
    { selector: "node[?drift]", style: { width: 20, height: 20, "border-width": 6, "border-color": c("--accent"), "border-opacity": 0.3, color: c("--accent-ink") } },
    { selector: "node[?stale]", style: { "border-width": 2, "border-color": c("--accent"), "border-style": "dashed" } },
    { selector: "edge", style: { width: 1, "line-color": c("--line"), "target-arrow-color": c("--line"), "target-arrow-shape": "triangle", "arrow-scale": 0.7,
        "curve-style": "bezier", "font-family": "Geist Mono, monospace", "font-size": 9, color: c("--soft"), "text-rotation": "autorotate",
        "text-background-color": c("--card"), "text-background-opacity": 1, "text-background-padding": "2px",
        "transition-property": "opacity, line-color", "transition-duration": 0.35 } as cytoscape.Css.Edge },
    { selector: "edge[bend]", style: { "curve-style": "unbundled-bezier", "control-point-distances": "data(bend)", "control-point-weights": 0.5 } as cytoscape.Css.Edge },
    { selector: "edge.path", style: { width: 2, "line-color": c("--accent"), "target-arrow-color": c("--accent"), "line-style": "dashed", "line-dash-pattern": [7, 5] } },
    { selector: "edge.hover, edge:selected", style: { label: "data(label)", "line-color": c("--violet-2"), "target-arrow-color": c("--violet-2"), width: 1.6 } },
    { selector: "edge.path.hover", style: { "line-color": c("--accent-ink"), "target-arrow-color": c("--accent-ink") } },
    { selector: ".dim", style: { opacity: 0.3 } },
    { selector: "node:selected", style: { "border-width": 3, "border-color": c("--violet-2"), "border-opacity": 1 } },
  ];
}

type Sel = GNode & { links: { id: string; label: string; rel: string; out: boolean; type: string }[] };

function GraphCanvas({ feature, focusNode, focusNonce }: { feature: string; focusNode?: string; focusNonce?: number }) {
  const { openPerson, drift } = useBrain();
  const host = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const data = useRef<GraphData | null>(null);
  const [selected, setSelected] = useState<Sel | null>(null);
  const [meta, setMeta] = useState("");
  const [showAll, setShowAll] = useState(false);
  const themeV = useThemeVersion();
  const still = useStill();
  const when = useMemo(() => new Map(drift.map((d) => [d.message, d.changed_at])), [drift]);

  const select = useCallback((id: string) => {
    const c = cy.current, g = data.current;
    if (!c || !g) return;
    const n = c.getElementById(id);
    if (!n.length) return;
    c.$(":selected").unselect();
    n.select();
    c.animate({ center: { eles: n }, zoom: Math.max(c.zoom(), 1.15) }, { duration: still ? 0 : 550, easing: "ease-in-out-cubic" });
    const links = n.connectedEdges().map((e) => {
      const out = e.source().id() === id, o = out ? e.target() : e.source();
      return { id: o.id(), label: o.data("short") as string, rel: e.data("label") as string, out, type: o.data("type") as string };
    });
    setSelected({ ...(n.data() as GNode), links });
  }, [still]);

  // double-click: pull a node's neighbours into the view, stacked in a column beside it
  const expand = useCallback(async (id: string) => {
    const c = cy.current, g = data.current;
    if (!c || !g) return;
    const more = await api.neighbors(id);
    const at = c.getElementById(id).position() || { x: 0, y: 0 };
    const fresh = more.nodes.filter((n) => !c.getElementById(n.id).length);
    const short = (n: GNode) => shortLabel(n, { nodes: [...g.nodes, ...more.nodes], edges: [...g.edges, ...more.edges] }, when);
    const add: cytoscape.ElementDefinition[] = fresh.map((n, i) => ({ group: "nodes", data: { ...n, short: short(n),
      color: n.drift ? cssVar("--accent") : cssVar(TYPE_VAR[n.type] || "--muted") }, position: { x: at.x + DX * 0.75, y: at.y + (i - (fresh.length - 1) / 2) * DY * 0.8 } }));
    for (const e of more.edges) { const eid = `${e.from}|${e.rel}|${e.to}`; if (!c.getElementById(eid).length) add.push({ group: "edges", data: { id: eid, source: e.from, target: e.to, label: e.rel } }); }
    if (!add.length) return;
    const added = c.add(add);
    data.current = { nodes: [...g.nodes, ...fresh], edges: [...g.edges, ...more.edges.filter((e) => !g.edges.some((x) => x.from === e.from && x.rel === e.rel && x.to === e.to))] };
    if (!still) { added.style({ opacity: 0 }); added.animate({ style: { opacity: 1 } }, { duration: 450 }); }
    setMeta(`${c.nodes().length} nodes · ${c.edges().length} edges · expanded ${id}`);
  }, [still, when]);

  const applyFocus = useCallback((all: boolean) => {
    const c = cy.current, g = data.current;
    if (!c || !g) return;
    const path = driftPath(g);
    c.batch(() => {
      c.elements().removeClass("dim path");
      c.edges().forEach((e) => { if (path.edges.has(`${e.data("source")}|${e.data("label")}|${e.data("target")}`)) e.addClass("path"); });
      if (!all && path.nodes.size) {
        c.nodes().forEach((n) => { if (!path.nodes.has(n.id())) n.addClass("dim"); });
        c.edges().not(".path").addClass("dim");
      }
    });
  }, []);

  // build once, then diff on every feature change so nodes tween instead of jumping
  useEffect(() => {
    let alive = true;
    void api.graph(feature).then((g) => {
      if (!alive || !host.current) return;
      data.current = g;
      const pos = layered(g);
      const color = (n: GNode) => (n.drift ? cssVar("--accent") : cssVar(TYPE_VAR[n.type] || "--muted"));
      const els = [
        ...g.nodes.map((n) => ({ group: "nodes" as const, data: { ...n, short: shortLabel(n, g, when), color: color(n) }, position: pos[n.id] })),
        ...g.edges.map((e, i) => {
          // an edge that skips a column would run straight through the node between (PR #5 -> BD-103 v1 crosses BD-103):
          // curve it, alternating sides so neighbouring long edges don't stack
          const a = pos[e.from], z = pos[e.to];
          const span = a && z ? Math.round(Math.abs(a.x - z.x) / DX) : 0;
          const bend = span > 1 ? (i % 2 ? 1 : -1) * 64 * (span - 1) : undefined;
          return { group: "edges" as const, data: { id: `${e.from}|${e.rel}|${e.to}`, source: e.from, target: e.to, label: e.rel, ...(bend ? { bend } : {}) } };
        }),
      ];
      let c = cy.current;
      if (!c || c.destroyed()) {
        c = cytoscape({ container: host.current, wheelSensitivity: 0.2, minZoom: 0.35, maxZoom: 2.6, style: styleFor(), elements: els, layout: { name: "preset" } });
        cy.current = c;
        c.on("tap", "node", (e) => select(e.target.id()));
        c.on("tap", (e) => { if (e.target === c) { c!.$(":selected").unselect(); setSelected(null); } });
        c.on("dbltap", "node", (e) => { const d = e.target.data() as GNode; if (d.type === "Person") openPerson(d.id); else void expandRef.current(d.id); });
        c.on("mouseover", "node", (e) => e.target.connectedEdges().addClass("hover"));
        c.on("mouseout", "node", (e) => e.target.connectedEdges().removeClass("hover"));
        c.on("mouseover", "edge", (e) => e.target.addClass("hover"));
        c.on("mouseout", "edge", (e) => e.target.removeClass("hover"));
        c.fit(undefined, 40);
      } else {
        c.style(styleFor());
        const keep = new Set(els.map((x) => x.data.id));
        const gone = c.elements().filter((x) => !keep.has(x.id()));
        if (still) gone.remove();
        else gone.animate({ style: { opacity: 0 } }, { duration: 300, complete: () => gone.remove() });
        for (const x of els) {
          const cur = c.getElementById(x.data.id);
          if (cur.length) {
            cur.data(x.data);
            if (x.group === "nodes" && "position" in x) cur.animate({ position: x.position }, { duration: still ? 0 : 650, easing: "ease-in-out-cubic" });
          } else {
            const added = c.add(x);
            if (!still) { added.style({ opacity: 0 }); added.animate({ style: { opacity: 1 } }, { duration: 500 }); }
          }
        }
        setTimeout(() => { if (!c!.destroyed()) c!.animate({ fit: { eles: c!.elements(), padding: 40 } }, { duration: still ? 0 : 600 }); }, still ? 0 : 320);
      }
      setSelected(null);
      setMeta(`${g.nodes.length} nodes · ${g.edges.length} edges`);
      applyFocus(showAll);
    });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feature, themeV]);

  useEffect(() => { applyFocus(showAll); }, [showAll, applyFocus]);
  const expandRef = useRef(expand);
  expandRef.current = expand;

  // flowing dashes along the drift path
  useEffect(() => {
    if (still) return;
    let raf = 0, off = 0;
    const tick = () => {
      off = (off + 0.35) % 1200;
      const c = cy.current;
      if (c && !c.destroyed()) c.edges(".path").style("line-dash-offset", -off);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [still]);

  useEffect(() => () => { cy.current?.destroy(); }, []);

  useEffect(() => {
    if (!focusNode) return;
    const t = setTimeout(async () => {
      if (cy.current && !cy.current.getElementById(focusNode).length) await expandRef.current(focusNode);
      select(focusNode);
    }, 700);
    return () => clearTimeout(t);
  }, [focusNode, focusNonce, select]);

  const drifts = drift.filter((d) => d.feature === feature);
  return (
    <div className="gview">
      <div className="canvas brackets">
        <div className="canvas__graph" ref={host} />
        <div className="canvas__meta canvas__meta--tl mono">{meta}</div>
        <div className="canvas__tools mono">
          <button className={!showAll ? "on" : ""} onClick={() => setShowAll(false)}>Drift path</button>
          <button className={showAll ? "on" : ""} onClick={() => setShowAll(true)}>Show all</button>
          <button onClick={() => cy.current?.animate({ fit: { eles: cy.current.elements(), padding: 40 } }, { duration: 500 })}>Fit</button>
        </div>
        <div className="canvas__cols mono" aria-hidden><span>Who</span><span>Message</span><span>Requirement</span><span>Ticket</span><span>PR · Doc</span></div>
      </div>
      <aside className="gpanel">
        <AnimatePresence mode="wait">
          {selected ? (
            <motion.div key={selected.id} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -8 }} transition={{ duration: 0.25 }}>
              <span className="mono gpanel__type" style={{ color: typeColor(selected.type) }}>{selected.type}{selected.drift && <span className="badge badge--warn">drift</span>}{selected.stale && <span className="badge badge--warn">stale</span>}</span>
              <h4>{selected.label}</h4>
              <span className="mono muted gpanel__id">{selected.id}{when.get(selected.id) ? ` · ${day(when.get(selected.id))}` : ""}</span>
              {selected.text && <p className="gpanel__text">{selected.text}</p>}
              <div className="mono kicker">Linked · {selected.links.length}</div>
              <ul className="gpanel__links">
                {selected.links.map((l, i) => (
                  <li key={i}><button onClick={() => select(l.id)}>
                    <span className="mono">{l.out ? `-[:${l.rel}]->` : `<-[:${l.rel}]-`}</span><i style={{ background: typeColor(l.type) }} />{l.label}
                  </button></li>
                ))}
              </ul>
            </motion.div>
          ) : (
            <motion.div key="none" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <span className="mono gpanel__type">{drifts.length ? "Drift path" : "No drift"}</span>
              <h4>{drifts.length ? `${drifts.length} unshipped decision${drifts.length > 1 ? "s" : ""}` : "Tickets and PRs match the latest decision"}</h4>
              {drifts.map((d) => <p key={d.requirement} className="gpanel__text">“{d.requirement_text}” <span className="muted">· {d.changed_by}, {day(d.changed_at)} · {d.ticket} still says the old thing.</span></p>)}
              <p className="muted gpanel__hint">Click a node for its full text and links. Double-click to expand its neighbours, or a person for their profile.</p>
              <div className="legend mono">
                {LEGEND.map((t) => <span key={t}><i style={{ background: typeColor(t) }} />{t}</span>)}
                <span><i style={{ background: "var(--accent)" }} />Drift</span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </aside>
    </div>
  );
}

function Timeline({ feature }: { feature: string }) {
  const [evs, setEvs] = useState<TimelineEvent[] | null>(null);
  const [sel, setSel] = useState<number>(-1);
  useEffect(() => { setEvs(null); void api.timeline(feature).then((e) => { setEvs(e); const d = e.findIndex((x) => x.drift); setSel(d >= 0 ? d : 0); }); }, [feature]);
  if (!evs) return <div className="timeline"><p className="muted">Loading timeline…</p></div>;
  if (!evs.length) return <div className="timeline"><p className="muted">No events.</p></div>;
  const t0 = evs[0].at, t1 = evs[evs.length - 1].at, span = Math.max(1, t1 - t0);
  const x = (t: number) => `${(0.04 + 0.92 * ((t - t0) / span)) * 100}%`;
  const DAY = 86400000;
  const step = DAY * Math.max(1, Math.round(span / DAY / 8));
  const ticks: number[] = [];
  for (let t = Math.ceil(t0 / DAY) * DAY; t <= t1; t += step) ticks.push(t);
  const drift = evs.find((e) => e.drift);
  const lanes: [TimelineEvent["lane"], string][] = [["chat", "Chat"], ["ticket", "Tickets"], ["doc", "Docs"], ["pr", "PRs"]];
  const e = evs[sel];
  return (
    <div className="timeline brackets">
      <div className="tl__axis">{ticks.map((t) => <span key={t} className="tl__tick" style={{ left: x(t) }}>{new Date(t).toISOString().slice(5, 10)}</span>)}</div>
      {lanes.map(([lane, label]) => (
        <div key={lane} className="tl__lane">
          <em>{label}</em>
          {drift && <div className="tl__gap" style={{ left: x(drift.at) }}>{lane === "pr" && <span>ticket, docs + PRs never caught up</span>}</div>}
          {evs.map((ev, i) => ev.lane !== lane ? null : (
            <motion.button key={ev.id + i} aria-label={ev.title}
              className={`tl__ev tl__ev--${lane} ${ev.drift ? "tl__ev--drift" : ""} ${ev.superseded ? "tl__ev--super" : ""} ${i === sel ? "tl__ev--sel" : ""}`}
              style={{ left: x(ev.at) }} initial={{ scale: 0.2, opacity: 0 }} animate={{ scale: 1, opacity: ev.superseded ? 0.45 : 1 }}
              transition={{ delay: i * 0.05, duration: 0.4 }} whileHover={{ scale: 1.5 }} onMouseEnter={() => setSel(i)} onClick={() => setSel(i)}>
              {ev.drift && <span className="tl__drift">DRIFT</span>}
            </motion.button>
          ))}
        </div>
      ))}
      {e && (
        <dl className="spec" style={{ marginTop: 16 }}>
          <div><dt>When</dt><dd>{e.iso.replace("T", " ").slice(0, 16)} UTC</dd></div>
          <div><dt>{({ pr: "Pull request", chat: "Chat change", doc: "Doc (last updated)", ticket: "Ticket version" } as const)[e.lane]}</dt>
            <dd>{e.title}{e.who ? ` · ${e.who}` : ""}{e.ref && e.lane === "chat" ? ` → amends ${e.ref}` : ""}</dd></div>
          <div><dt>Says</dt><dd>{e.text}</dd></div>
          <div><dt>Status</dt><dd>{e.drift ? <span className="warn">drift: newest, unimplemented, ticket never updated</span> : e.superseded ? "superseded by a later version" : e.lane === "pr" ? "shipped" : "current"}</dd></div>
        </dl>
      )}
    </div>
  );
}

export function GraphSection() {
  const { features, feature, setFeature, view, setView, focus } = useBrain();
  useEffect(() => {
    const v = new URLSearchParams(location.search).get("view");
    if (v === "timeline") setView("timeline");
  }, [setView]);
  return (
    <Section id="graph-sec" index="005" kicker="Feature graph" title="Feature graph" wide
      intro="Who decided, the message, the requirement it created, the ticket it amends, and the PRs and docs on that ticket. The drift path is lit; everything else waits in the dark."
      aside={
        <div className="controls">
          <select className="field" value={feature || ""} onChange={(e) => setFeature(e.target.value)} aria-label="Feature">
            {features.map((f) => <option key={f.id} value={f.id}>{f.name}{f.drift ? "  · drift" : ""}</option>)}
          </select>
          <div className="tabs" role="tablist">
            {(["graph", "timeline"] as const).map((v) => <button key={v} role="tab" className={view === v ? "active" : ""} onClick={() => setView(v)}>{v}</button>)}
          </div>
        </div>
      }>
      {feature && (view === "graph"
        ? <GraphCanvas feature={feature} focusNode={focus?.node} focusNonce={focus?.nonce} />
        : <Timeline feature={feature} />)}
    </Section>
  );
}
