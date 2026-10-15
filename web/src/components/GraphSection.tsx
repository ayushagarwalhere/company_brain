import cytoscape, { type Core } from "cytoscape";
import { motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type GNode, type TimelineEvent } from "../lib/api";
import { useBrain } from "../lib/brain";
import { cssVar, TYPE_VAR, typeColor, useStaticMode } from "../lib/ui";
import { Section } from "./Section";

const LEGEND = ["Feature", "Ticket", "Requirement", "Message", "PullRequest", "Document", "Person"];

function useThemeVersion() {
  const [v, setV] = useState(0);
  useEffect(() => {
    const on = () => setTimeout(() => setV((x) => x + 1), 30);
    addEventListener("themechange", on);
    return () => removeEventListener("themechange", on);
  }, []);
  return v;
}

function styleFor() {
  const c = (v: string) => cssVar(v);
  return [
    { selector: "node", style: { "background-color": "data(color)", label: "data(label)", "font-family": "Geist Mono, monospace", "font-size": 9,
        color: c("--muted"), "text-wrap": "ellipsis", "text-max-width": "130px", "text-valign": "bottom", "text-margin-y": 5, width: 15, height: 15 } },
    { selector: "node[type='Feature']", style: { width: 28, height: 28, "font-size": 11, color: c("--ink"), "font-family": "Geist, sans-serif", "text-valign": "top", "text-margin-y": -6 } },
    { selector: "node[type='Ticket']", style: { shape: "rectangle", width: 18, height: 12 } },
    { selector: "node[type='PullRequest']", style: { shape: "diamond", width: 16, height: 16 } },
    { selector: "node[type='Document']", style: { shape: "tag", width: 16, height: 16 } },
    { selector: "node[?drift]", style: { width: 22, height: 22, "border-width": 6, "border-color": c("--accent"), "border-opacity": 0.3, color: c("--accent") } },
    { selector: "node[?stale]", style: { "border-width": 2, "border-color": c("--accent"), "border-style": "dashed" } },
    { selector: "edge", style: { width: 1, "line-color": c("--line"), "target-arrow-color": c("--line"), "target-arrow-shape": "triangle", "arrow-scale": 0.7,
        "curve-style": "bezier", "font-family": "Geist Mono, monospace", "font-size": 6.5, color: c("--note"), "text-rotation": "autorotate",
        "text-background-color": c("--card"), "text-background-opacity": 1, "text-background-padding": "1px" } },
    { selector: "edge[label='CHANGES'], edge[label='AMENDS'], edge[label='IMPLEMENTS'], edge[label='SUPERSEDES']", style: { label: "data(label)" } },
    { selector: "edge[label='CHANGES'], edge[label='AMENDS']", style: { "line-color": c("--accent"), "target-arrow-color": c("--accent"), width: 1.4 } },
    { selector: "edge.hover", style: { label: "data(label)", color: c("--ink"), "line-color": c("--violet-2") } },
    { selector: ":selected", style: { "border-width": 2, "border-color": c("--violet-2") } },
  ] as cytoscape.StylesheetStyle[];
}

const nodeEl = (n: GNode) => ({ data: { ...n, color: n.drift ? cssVar("--accent") : cssVar(TYPE_VAR[n.type] || "--muted") } });

function GraphCanvas({ feature, focusNode, focusNonce }: { feature: string; focusNode?: string; focusNonce?: number }) {
  const { openPerson } = useBrain();
  const host = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [selected, setSelected] = useState<GNode & { edges?: string } | null>(null);
  const [meta, setMeta] = useState("");
  const [coords, setCoords] = useState("X:0000 Y:0000");
  const themeV = useThemeVersion();
  const still = useStaticMode();

  const expand = useCallback(async (id: string) => {
    const c = cy.current; if (!c) return;
    const g = await api.neighbors(id);
    const center = c.getElementById(id).position() || { x: 0, y: 0 };
    const add: cytoscape.ElementDefinition[] = [];
    for (const n of g.nodes) if (!c.getElementById(n.id).length) add.push({ ...nodeEl(n), position: { x: center.x + (Math.random() - 0.5) * 160, y: center.y + (Math.random() - 0.5) * 160 } });
    for (const e of g.edges) { const eid = `x:${e.from}:${e.rel}:${e.to}`; if (!c.getElementById(eid).length) add.push({ data: { id: eid, source: e.from, target: e.to, label: e.rel } }); }
    if (!add.length) return;
    c.add(add);
    c.layout({ name: "cose", animate: !still, animationDuration: 600, fit: false, randomize: false, nodeRepulsion: () => 18000, idealEdgeLength: () => 80 } as cytoscape.LayoutOptions).run();
    setMeta(`${c.nodes().length} nodes · ${c.edges().length} edges · expanded ${id}`);
  }, [still]);

  useEffect(() => {
    let alive = true;
    void api.graph(feature).then((g) => {
      if (!alive || !host.current) return;
      cy.current?.destroy();
      const c = cytoscape({
        container: host.current, wheelSensitivity: 0.2, minZoom: 0.4, maxZoom: 2.4, style: styleFor(),
        elements: [...g.nodes.map(nodeEl), ...g.edges.map((e, i) => ({ data: { id: `e${i}`, source: e.from, target: e.to, label: e.rel } }))],
        layout: { name: "concentric", animate: false, padding: 30, minNodeSpacing: 26, startAngle: -Math.PI / 2, levelWidth: () => 1,
          concentric: (n: cytoscape.NodeSingular) => ({ Feature: 5, Ticket: 4, Requirement: 3, Message: 2, PullRequest: 2, Document: 2, Person: 1 } as Record<string, number>)[n.data("type")] || 1 } as cytoscape.LayoutOptions,
      });
      cy.current = c;
      setMeta(`${g.nodes.length} nodes · ${g.edges.length} edges · ${feature}`);
      c.on("tap", "node", (e) => setSelected({ ...(e.target.data() as GNode), edges: [...new Set(e.target.connectedEdges().map((x: cytoscape.EdgeSingular) => x.data("label") as string))].join(" · ") }));
      c.on("dbltap", "node", (e) => { const d = e.target.data() as GNode; if (d.type === "Person") openPerson(d.id); else void expand(d.id); });
      c.on("mouseover", "node", (e) => e.target.connectedEdges().addClass("hover"));
      c.on("mouseout", "node", (e) => e.target.connectedEdges().removeClass("hover"));
      const hot = c.nodes("[?drift]");
      const pulse = () => {
        if (c.destroyed() || !hot.length || still) return;
        hot.animate({ style: { "border-opacity": 0.65, "border-width": 10 } }, { duration: 900, complete: () =>
          hot.animate({ style: { "border-opacity": 0.15, "border-width": 4 } }, { duration: 900, complete: pulse }) });
      };
      pulse();
    });
    return () => { alive = false; };
  }, [feature, themeV, expand, openPerson, still]);

  useEffect(() => () => { cy.current?.destroy(); }, []);

  useEffect(() => {
    if (!focusNode || !cy.current) return;
    const go = async () => {
      const c = cy.current!;
      if (!c.getElementById(focusNode).length) await expand(focusNode);
      const n = c.getElementById(focusNode);
      if (!n.length) return;
      c.animate({ center: { eles: n }, zoom: 1.4 }, { duration: 500 });
      c.$(":selected").unselect(); n.select(); n.emit("tap");
    };
    const t = setTimeout(go, 500);
    return () => clearTimeout(t);
  }, [focusNode, focusNonce, expand]);

  return (
    <>
      <div className="canvas handles" onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        setCoords(`X:${String(Math.round(e.clientX - r.left)).padStart(4, "0")} Y:${String(Math.round(e.clientY - r.top)).padStart(4, "0")}`);
      }}>
        <div className="canvas__graph" ref={host} />
        <div className="canvas__meta canvas__meta--tl mono">{meta}</div>
        <div className="canvas__meta canvas__meta--tr mono">Double-click a node to expand</div>
        <div className="canvas__meta canvas__meta--br mono">{coords}</div>
      </div>
      <dl className="spec" style={{ marginTop: 18 }}>
        {selected ? (<>
          <div><dt>Type</dt><dd>{selected.type}{selected.drift && <span className="badge badge--warn" style={{ marginLeft: 8 }}>drift</span>}{selected.stale && <span className="badge badge--warn" style={{ marginLeft: 8 }}>stale doc</span>}</dd></div>
          <div><dt>Id</dt><dd>{selected.id}</dd></div>
          <div><dt>Text</dt><dd>{selected.text || "n/a"}</dd></div>
          <div><dt>Edges</dt><dd>{selected.edges || "none"}</dd></div>
        </>) : <div><dt>Node</dt><dd>Select a node</dd></div>}
      </dl>
    </>
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
    <div className="timeline handles">
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
    <Section id="graph-sec" index="005" kicker="Feature graph" title="Feature graph"
      intro="Tickets, requirement versions, the messages that changed them, the docs that describe them, and the PRs that implement them."
      aside={
        <div className="controls">
          <select className="field" value={feature || ""} onChange={(e) => setFeature(e.target.value)} aria-label="Feature">
            {features.map((f) => <option key={f.id} value={f.id}>{f.name}{f.drift ? "  · drift" : ""}</option>)}
          </select>
          <div className="tabs" role="tablist">
            {(["graph", "timeline"] as const).map((v) => <button key={v} role="tab" className={view === v ? "active" : ""} onClick={() => setView(v)}>{v}</button>)}
          </div>
          <div className="legend mono">
            {LEGEND.map((t) => <span key={t}><i style={{ background: typeColor(t) }} />{t}</span>)}
            <span><i style={{ background: "var(--accent)" }} />Drift</span>
          </div>
        </div>
      }>
      {feature && (view === "graph"
        ? <GraphCanvas feature={feature} focusNode={focus?.node} focusNonce={focus?.nonce} />
        : <Timeline feature={feature} />)}
    </Section>
  );
}
