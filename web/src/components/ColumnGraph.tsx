import cytoscape, { type Core } from "cytoscape";
import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import type { CGraph, CNode } from "../lib/api";
import { useBrain } from "../lib/brain";
import { useStill } from "../lib/fx";
import { cssVar, TYPE_VAR } from "../lib/ui";
import { GraphBar, GraphOverlay, KeysHint, styleFor, TypeFilters, TypeGlyph, useGraphKit } from "./GraphKit";

/* A layered graph view: nodes in columns (the backend says which), each column ordered so nodes sit near what they
   connect to. Used by the impact view and the feature map. Click a node to light its neighbours. */

const DY = 62;

/** Columns left to right, `dx` apart; within a column, barycenter sweeps put each node next to its neighbours. */
export function columnLayout(g: CGraph, dx: number): Record<string, { x: number; y: number }> {
  const cols = new Map<number, CNode[]>();
  for (const n of g.nodes) cols.set(n.col, [...(cols.get(n.col) || []), n]);
  const keys = [...cols.keys()].sort((a, b) => a - b);
  const nb = new Map<string, string[]>();
  for (const e of g.edges) {
    nb.set(e.from, [...(nb.get(e.from) || []), e.to]);
    nb.set(e.to, [...(nb.get(e.to) || []), e.from]);
  }
  const colOf = new Map(g.nodes.map((n) => [n.id, n.col]));
  const at = new Map<string, number>();  // position within its column, 0..1
  const place = (k: number) => cols.get(k)!.forEach((n, i, arr) => at.set(n.id, (i + 0.5) / arr.length));
  keys.forEach((k) => { cols.get(k)!.sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true })); place(k); });
  const sweep = (order: number[]) => {
    for (const k of order) {
      const score = new Map(cols.get(k)!.map((n) => {
        const r = (nb.get(n.id) || []).filter((x) => colOf.get(x) !== k && at.has(x)).map((x) => at.get(x)!);
        return [n.id, r.length ? r.reduce((a, b) => a + b, 0) / r.length : at.get(n.id)!];
      }));
      cols.get(k)!.sort((a, b) => score.get(a.id)! - score.get(b.id)!);
      place(k);
    }
  };
  sweep(keys); sweep([...keys].reverse()); sweep(keys);
  const tallest = Math.max(1, ...keys.map((k) => cols.get(k)!.length));
  const pos: Record<string, { x: number; y: number }> = {};
  keys.forEach((k, xi) => cols.get(k)!.forEach((n, i, arr) => {
    const gap = DY * Math.min(1.8, Math.max(1, (tallest / arr.length) * 0.7));
    pos[n.id] = { x: xi * dx, y: (i - (arr.length - 1) / 2) * gap };
  }));
  return pos;
}

/** Shapes for the planning types, and status: coral = misses / slips, amber = tight, faded = not affected. */
function extra(): cytoscape.StylesheetStyle[] {
  const coral = cssVar("--c-coral"), amber = cssVar("--c-amber");
  const hit = { "background-color": "#000", "border-width": 3, "border-color": coral, color: coral, "font-weight": 600,
    "underlay-color": coral, "underlay-padding": 6, "underlay-opacity": 0.16, "underlay-shape": "ellipse" } as unknown as cytoscape.Css.Node;
  return [
    { selector: "node", style: { "font-size": 11 } },
    { selector: "node[type='Team']", style: { shape: "round-rectangle", width: 30, height: 14, "font-size": 11.5, color: "#fff" } },
    { selector: "node[type='Project']", style: { shape: "round-rectangle", width: 26, height: 26, "font-size": 12.5, color: "#fff", "font-family": "Geist, sans-serif" } },
    { selector: "node[type='Feature']", style: { "text-valign": "bottom", "text-margin-y": 6 } },
    { selector: "node[type='Deliverable']", style: { shape: "star", width: 22, height: 22 } },
    { selector: "node[type='Client']", style: { shape: "barrel", width: 26, height: 17, "font-size": 11.5, color: "#fff" } },
    { selector: "node[type='Task']", style: { shape: "triangle", width: 14, height: 14 } },
    { selector: ".st-misses, .st-delayed, .st-slips, .st-drift", style: hit },
    { selector: ".st-tight", style: { "border-width": 2, "border-color": amber, "border-style": "dashed", color: amber } },
    { selector: ".st-unaffected, .st-superseded", style: { "background-opacity": 0.38, "border-opacity": 0.38, "text-opacity": 0.85 } },
    { selector: "node:selected", style: { "border-color": cssVar("--c-blue"), "border-style": "solid" } },
  ];
}

const STATUS_LABEL: Record<string, string> = {
  misses: "misses its date", tight: "tight", "on track": "on track", delayed: "delayed", slips: "slips", waits: "waits, has slack",
  late: "late", unaffected: "not affected", drift: "drift", superseded: "superseded", shipped: "shipped", current: "current",
};
const LEGEND = ["Team", "Person", "Requirement", "Ticket", "PullRequest", "Document", "Project", "Deliverable", "Client"];

type Sel = CNode & { links: { id: string; label: string; rel: string; out: boolean; type: string }[] };

export function ColumnGraph({ data, headers, note }: { data: CGraph | null; headers: Record<number, string>; note?: string }) {
  const host = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [sel, setSel] = useState<Sel | null>(null);
  const { openPerson } = useBrain();
  const still = useStill();

  const clear = useCallback(() => { setSel(null); cy.current?.elements().removeClass("dim hover"); cy.current?.$(":selected").unselect(); }, []);
  const kit = useGraphKit(cy, { pad: 44, onEscape: clear, describe: (n) => (n.data("status") ? STATUS_LABEL[n.data("status")] || n.data("status") : undefined) });
  const select = useCallback((id: string) => {
    const c = cy.current;
    if (!c) return;
    const n = c.getElementById(id);
    c.$(":selected").unselect();
    n.select();
    c.elements().addClass("dim").removeClass("hover ghost");
    n.closedNeighborhood().removeClass("dim");
    n.connectedEdges().addClass("hover");
    const links = n.connectedEdges().map((e) => {
      const out = e.source().id() === id, o = out ? e.target() : e.source();
      return { id: o.id(), label: o.data("label") as string, rel: e.data("label") as string, out, type: o.data("type") as string };
    });
    setSel({ ...(n.data() as CNode), links });
  }, []);

  const present = data ? [...new Set(data.nodes.map((n) => n.col))].sort((a, b) => a - b) : [];
  const tallest = data ? Math.max(1, ...present.map((k) => data.nodes.filter((n) => n.col === k).length)) : 4;
  const height = Math.max(380, Math.min(680, tallest * DY + 150));

  useEffect(() => {
    if (!host.current || !data) return;
    cy.current?.destroy();
    setSel(null);
    const width = host.current.clientWidth || 1000;
    const dx = Math.max(120, Math.min(220, (width - 120) / Math.max(1, present.length - 1)));
    const pos = columnLayout(data, dx);
    const label = Math.round(dx - 18);
    const c = cytoscape({
      container: host.current, minZoom: 0.3, maxZoom: 2.4, layout: { name: "preset" },
      style: [...styleFor(), ...extra(), { selector: "node", style: { "text-max-width": `${label}px` } }],
      elements: [
        ...data.nodes.map((n) => ({ group: "nodes" as const, data: { ...n, short: n.type === "Person" ? n.label.split(" ")[0] : n.label, color: cssVar(TYPE_VAR[n.type] || "--muted") },
          position: pos[n.id], classes: n.status ? `st-${n.status.replace(/\s+/g, "-")}` : "" })),
        ...data.edges.map((e) => ({ group: "edges" as const, data: { id: `${e.from}|${e.rel}|${e.to}`, source: e.from, target: e.to, label: e.rel } })),
      ],
    });
    cy.current = c;
    kit.attach(c);
    c.fit(undefined, 44);
    if (c.zoom() > 1.15) { c.zoom(1.15); c.center(); }
    c.on("tap", "node", (e) => select(e.target.id()));
    c.on("tap", (e) => { if (e.target === c) clear(); });
    c.on("dbltap", "node[type='Person']", (e) => openPerson(e.target.id()));
    c.on("mouseover", "node", (e) => e.target.connectedEdges().addClass("hover"));
    c.on("mouseout", "node", (e) => { if (!e.target.selected()) e.target.connectedEdges().removeClass("hover"); });
    if (!still) {
      c.elements().style("opacity", 0);
      c.elements().animate({ style: { opacity: 1 } }, { duration: 550, complete: () => c.elements().removeStyle("opacity") });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, select, clear, openPerson, still]);
  useEffect(() => () => { cy.current?.destroy(); }, []);

  return (
    <div className="cg">
      <div ref={kit.wrap} className={`canvas gk ${kit.full ? "gk--full" : ""}`} style={{ height }}>
        <div className="canvas__graph" ref={host} tabIndex={0} aria-label="Graph. Plus and minus zoom, F fits, arrows pan." />
        <GraphBar kit={kit} />
        <GraphOverlay kit={kit} />
        <div className="cg__heads mono" aria-hidden>{present.map((k) => <span key={k}>{headers[k] || ""}</span>)}</div>
        <AnimatePresence>
          {sel && (
            <motion.aside key={sel.id} className="cg__panel" initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 16 }} transition={{ duration: 0.2 }}>
              <button className="cg__close" onClick={clear} aria-label="Close">✕</button>
              <span className="mono gpanel__type"><TypeGlyph type={sel.type} />{sel.type}
                {sel.status && <span className={`tag ${["misses", "delayed", "slips", "drift"].includes(sel.status) ? "tag--drift" : sel.status === "tight" ? "tag--dash" : ""}`}>{STATUS_LABEL[sel.status] || sel.status}</span>}
              </span>
              <h4>{sel.label}</h4>
              <span className="mono muted">{sel.id}</span>
              {sel.text && <p className="gpanel__text">{sel.text}</p>}
              <div className="mono kicker">Linked · {sel.links.length}</div>
              <ul className="gpanel__links">
                {sel.links.map((l, i) => (
                  <li key={i}><button onClick={() => select(l.id)}>
                    <span className="mono">{l.out ? `-[:${l.rel}]->` : `<-[:${l.rel}]-`}</span><TypeGlyph type={l.type} />{l.label}
                  </button></li>
                ))}
              </ul>
            </motion.aside>
          )}
        </AnimatePresence>
      </div>
      <div className="gk__under">
        <TypeFilters kit={kit} types={LEGEND.filter((t) => !data || data.nodes.some((n) => n.type === t))} />
        <span className="mono muted">{data ? `${data.nodes.length} nodes · ${data.edges.length} edges${note ? ` · ${note}` : ""}` : "Loading…"}</span>
      </div>
      <div className="gk__under">
        <KeysHint />
        <span className="cg__key mono"><i className="cg__sw cg__sw--hit" />misses / slips <i className="cg__sw cg__sw--tight" />tight <i className="cg__sw cg__sw--off" />not affected · double-click a person for their profile</span>
      </div>
    </div>
  );
}
