import cytoscape, { type Core, type NodeSingular } from "cytoscape";
import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type CompanyGraph, type CompanyNode } from "../lib/api";
import { useBrain } from "../lib/brain";
import { useStill } from "../lib/fx";
import { cssVar } from "../lib/ui";
import { GraphBar, GraphOverlay, KeysHint, styleFor, useGraphKit } from "./GraphKit";
import { Section } from "./Section";

/* The company map: people, teams, projects, clients, deliverables, docs, tickets and features in one force-directed
   graph you can play with. Filter by category, light one layer of relations (reporting lines, teams, ownership,
   dependencies, documents), set how far apart nodes sit, drag anything, and read the live counts and density. */

const TYPES: { type: string; label: string; color: string; shape: string; size: number }[] = [
  { type: "Person", label: "People", color: "--c-blue", shape: "ellipse", size: 24 },
  { type: "Team", label: "Teams", color: "--c-cyan", shape: "round-rectangle", size: 28 },
  { type: "Project", label: "Projects", color: "--c-amber", shape: "round-rectangle", size: 32 },
  { type: "Client", label: "Clients", color: "--c-pink", shape: "barrel", size: 26 },
  { type: "Deliverable", label: "Deliverables", color: "--c-yellow", shape: "star", size: 26 },
  { type: "Document", label: "Docs", color: "--c-green", shape: "tag", size: 22 },
  { type: "Ticket", label: "Tickets", color: "--c-violet", shape: "rectangle", size: 16 },
  { type: "Feature", label: "Features", color: "--ink", shape: "hexagon", size: 22 },
];
const T = Object.fromEntries(TYPES.map((t) => [t.type, t]));

const CATEGORIES: [string, string, string[] | null][] = [
  ["all", "All corporate elements", null],
  ["people", "People & teams", ["Person", "Team"]],
  ["delivery", "Projects & delivery", ["Project", "Client", "Deliverable", "Ticket", "Person"]],
  ["knowledge", "Knowledge", ["Document", "Ticket", "Person"]],
  ["product", "Product", ["Feature", "Ticket", "Project"]],
];

const LAYERS: [string, string, string[] | null][] = [
  ["all", "Show all connections", null],
  ["reports", "Reporting lines (HR)", ["REPORTS_TO"]],
  ["teams", "Team membership", ["MEMBER_OF"]],
  ["owns", "Ownership & assignment", ["OWNS", "ASSIGNED_TO", "AUTHORED"]],
  ["deps", "Dependencies", ["BLOCKS", "NEEDS", "INCLUDES", "FOR"]],
  ["docs", "Documents", ["MENTIONS", "AUTHORED"]],
];

type Sel = CompanyNode & { links: { id: string; label: string; rel: string; out: boolean; type: string }[] };

function mapStyle(): cytoscape.StylesheetStyle[] {
  const c = (v: string) => cssVar(v);
  return [
    ...styleFor(),
    ...TYPES.map((t) => ({ selector: `node[type='${t.type}']`, style: { shape: t.shape, width: t.size, height: t.size, "background-color": c(t.color), "border-width": 2, "border-color": "#000" } }) as cytoscape.StylesheetStyle),
    { selector: "node[type='Project'], node[type='Team']", style: { "font-size": 12, color: c("--ink"), "font-family": "Geist, sans-serif" } },
    { selector: "node[?inactive]", style: { opacity: 0.45, "border-style": "dashed", "border-color": c("--c-coral"), "border-width": 2 } },
    { selector: "node[?away]", style: { "border-style": "dashed", "border-color": c("--c-amber"), "border-width": 3 } },
    { selector: "edge", style: { width: 1.1, opacity: 0.75 } },
    { selector: "edge.layer", style: { width: 2.4, opacity: 1, "line-color": c("--c-cyan"), "target-arrow-color": c("--c-cyan"), label: "data(label)", color: c("--c-cyan"), "z-index": 5 } },
    { selector: ".off", style: { display: "none" } },
  ];
}

const short = (n: CompanyNode) => (n.type === "Person" ? n.id : n.type === "Ticket" || n.type === "Document" ? n.id : n.label.length > 22 ? `${n.label.slice(0, 21)}…` : n.label);

export function CompanyMapSection() {
  const { version, openPerson, workspace } = useBrain();
  const still = useStill();
  const host = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [data, setData] = useState<CompanyGraph | null>(null);
  const [cat, setCat] = useState("all");
  const [layer, setLayer] = useState("all");
  const [spacing, setSpacing] = useState(80);
  const [counts, setCounts] = useState({ n: 0, e: 0 });
  const [selected, setSelected] = useState<Sel | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const clearSel = useCallback(() => {
    const c = cy.current;
    if (c && !c.destroyed()) { c.$(":selected").unselect(); c.elements().removeClass("faded"); }
    setSelected(null);
  }, []);
  const kit = useGraphKit(cy, {
    pad: 30, onEscape: clearSel,
    describe: (n: NodeSingular) => [n.data("status") && n.data("type") === "Project" ? n.data("status") : null, n.data("away") ? `out of office until ${n.data("ooo_until")}` : null].filter(Boolean).join(" · ") || undefined,
  });

  useEffect(() => { if (workspace === "ready") api.companyGraph().then(setData).catch((e) => setErr((e as Error).message)); }, [version, workspace]);

  const layout = useCallback((c: Core, gap: number, animate: boolean) => {
    c.layout({
      name: "cose", animate: animate && !still, animationDuration: 650, fit: true, padding: 30, randomize: false,
      idealEdgeLength: () => gap * 1.4, nodeRepulsion: () => 9000 + gap * 900, nodeOverlap: 16, gravity: 0.18, componentSpacing: gap * 1.4, numIter: 1500, nestingFactor: 1.1,
      eles: c.elements(":visible"),
    } as cytoscape.LayoutOptions).run();
  }, [still]);

  // count what's on screen: nodes shown, edges between them (in the lit layer, if one is), and how dense that is
  const recount = useCallback(() => {
    const c = cy.current;
    if (!c || c.destroyed()) return;
    const ns = c.nodes().not(".off");
    const es = c.edges().filter((e) => !e.source().hasClass("off") && !e.target().hasClass("off") && (layer === "all" || e.hasClass("layer")));
    setCounts({ n: ns.length, e: es.length });
  }, [layer]);

  // build, or update in place when the graph changes (a cancelled project, a new ticket)
  useEffect(() => {
    if (!data || !host.current) return;
    const els = [
      ...data.nodes.map((n) => ({
        group: "nodes" as const,
        data: { ...n, short: short(n), color: cssVar(T[n.type]?.color || "--muted"), inactive: n.type === "Project" && !!n.status && n.status !== "active", away: !!n.ooo_until },
      })),
      ...data.edges.map((e) => ({ group: "edges" as const, data: { id: `${e.source}|${e.rel}|${e.target}`, source: e.source, target: e.target, label: e.rel } })),
    ];
    let c = cy.current;
    if (!c || c.destroyed()) {
      c = cytoscape({ container: host.current, minZoom: 0.25, maxZoom: 3, style: mapStyle(), elements: els });
      cy.current = c;
      kit.attach(c);
      c.on("tap", "node", (e) => select(e.target.id()));
      c.on("tap", (e) => { if (e.target === c) clearSel(); });
      c.on("dbltap", "node[type='Person']", (e) => openPerson(e.target.id()));
      c.on("mouseover", "node", (e) => e.target.connectedEdges().addClass("hover"));
      c.on("mouseout", "node", (e) => e.target.connectedEdges().removeClass("hover"));
      layout(c, spacing, false);
    } else {
      const keep = new Set(els.map((x) => x.data.id));
      c.elements().filter((x) => !keep.has(x.id())).remove();
      let added = false;
      for (const x of els) {
        const cur = c.getElementById(x.data.id);
        if (cur.length) cur.data(x.data);
        else { c.add(x); added = true; }
      }
      if (added) layout(c, spacing, true);
    }
    applyView();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const applyView = useCallback(() => {
    const c = cy.current;
    if (!c || c.destroyed()) return;
    const types = CATEGORIES.find(([k]) => k === cat)?.[2];
    const rels = LAYERS.find(([k]) => k === layer)?.[2];
    c.batch(() => {
      c.nodes().forEach((n) => { n.toggleClass("off", !!types && !types.includes(n.data("type"))); });
      c.elements().removeClass("layer dim");
      if (rels) {
        const lit = c.edges().filter((e) => rels.includes(e.data("label")));
        lit.addClass("layer");
        c.edges().not(lit).addClass("dim");
        c.nodes().not(lit.connectedNodes()).addClass("dim");
      }
    });
    recount();
  }, [cat, layer, recount]);

  // a new category re-lays out what's left; a new layer only re-colours
  const firstCat = useRef(true);
  useEffect(() => {
    applyView();
    if (firstCat.current) { firstCat.current = false; return; }
    const c = cy.current;
    if (c && !c.destroyed()) layout(c, spacing, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cat]);
  useEffect(() => { applyView(); }, [layer, applyView]);

  // spacing: re-run the layout, debounced while the slider moves
  const firstGap = useRef(true);
  useEffect(() => {
    if (firstGap.current) { firstGap.current = false; return; }
    const t = setTimeout(() => { const c = cy.current; if (c && !c.destroyed()) layout(c, spacing, true); }, 160);
    return () => clearTimeout(t);
  }, [spacing, layout]);

  useEffect(() => () => { cy.current?.destroy(); }, []);

  const select = useCallback((id: string) => {
    const c = cy.current;
    if (!c) return;
    const n = c.getElementById(id);
    if (!n.length) return;
    c.$(":selected").unselect();
    n.select();
    c.batch(() => { c.elements().removeClass("ghost").addClass("faded"); n.closedNeighborhood().removeClass("faded"); });
    const links = n.connectedEdges().map((e) => {
      const out = e.source().id() === id, o = out ? e.target() : e.source();
      return { id: o.id(), label: o.data("label") as string, rel: e.data("label") as string, out, type: o.data("type") as string };
    });
    setSelected({ ...(n.data() as CompanyNode), links });
  }, []);

  const density = counts.n > 1 ? (counts.e / (counts.n * (counts.n - 1))) * 100 : 0;
  const byType = useMemo(() => {
    const m = new Map<string, number>();
    for (const n of data?.nodes || []) m.set(n.type, (m.get(n.type) || 0) + 1);
    return m;
  }, [data]);

  return (
    <Section id="map-sec" index="03" title="Company map"
      intro="The whole company as one graph: who reports to whom, who's on which team, who owns what, what depends on what, and which doc names which ticket. Filter it, light one kind of relation, spread it out, and drag anything.">
      <div className="cmap">
        <div className="cmap__controls">
          <label><span className="mono">Filter corporate category</span>
            <select className="field" value={cat} onChange={(e) => setCat(e.target.value)}>{CATEGORIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          </label>
          <label><span className="mono">Highlight relation layer</span>
            <select className="field" value={layer} onChange={(e) => setLayer(e.target.value)}>{LAYERS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          </label>
          <label className="cmap__range"><span className="mono">Node spacing <b>{spacing} px</b></span>
            <input type="range" min={20} max={140} step={5} value={spacing} onChange={(e) => setSpacing(Number(e.target.value))} aria-label="Node spacing" />
          </label>
        </div>
        <div className="gview">
          <div>
            <div ref={kit.wrap} className={`canvas gk cmap__canvas ${kit.full ? "gk--full" : ""}`}>
              <div className="canvas__graph" ref={host} tabIndex={0} aria-label="Company map. Drag nodes; plus and minus zoom, F fits." />
              <GraphBar kit={kit} />
              <GraphOverlay kit={kit} />
              {err && <p className="warn cmap__err">{err}</p>}
            </div>
            <dl className="cmap__stats">
              <div><dt className="mono">Active nodes</dt><dd>{counts.n}</dd></div>
              <div><dt className="mono">Active edges</dt><dd>{counts.e}</dd></div>
              <div><dt className="mono">Graph density</dt><dd>{density.toFixed(1)}%</dd></div>
            </dl>
            <div className="cmap__legend mono">
              {TYPES.filter((t) => byType.get(t.type)).map((t) => <span key={t.type}><i style={{ background: `var(${t.color})` }} />{t.label} {byType.get(t.type)}</span>)}
              <span><i className="cmap__dash cmap__dash--amber" />out of office</span>
              <span><i className="cmap__dash" />cancelled or paused</span>
            </div>
            <KeysHint />
          </div>
          <aside className="gpanel">
            <AnimatePresence mode="wait">
              {selected ? (
                <motion.div key={selected.id} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -8 }} transition={{ duration: 0.25 }}>
                  <span className="mono gpanel__type"><i className="cmap__sw" style={{ background: `var(${T[selected.type]?.color})` }} />{selected.type}
                    {selected.status && selected.type === "Project" && <span className={`tag ${selected.status === "active" ? "" : "tag--drift"}`}>{selected.status}</span>}
                    {selected.ooo_until && <span className="tag tag--dash">away until {selected.ooo_until}</span>}
                  </span>
                  <h4>{selected.label}</h4>
                  <span className="mono muted gpanel__id">{selected.id}{selected.launch ? ` · launch ${selected.launch}` : ""}{selected.due ? ` · due ${selected.due}` : ""}</span>
                  {selected.text && selected.text !== selected.label && <p className="gpanel__text">{selected.text}</p>}
                  <div className="mono kicker">Linked · {selected.links.length}</div>
                  <ul className="gpanel__links">
                    {selected.links.map((l, i) => (
                      <li key={i}><button onClick={() => select(l.id)}>
                        <span className="mono">{l.out ? `-[:${l.rel}]->` : `<-[:${l.rel}]-`}</span><i className="cmap__sw" style={{ background: `var(${T[l.type]?.color})` }} />{l.label}
                      </button></li>
                    ))}
                  </ul>
                  {selected.type === "Person" && <button className="link mono" onClick={() => openPerson(selected.id)}>Open profile →</button>}
                </motion.div>
              ) : (
                <motion.div key="none" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                  <span className="mono gpanel__type">Company map</span>
                  <h4>{data ? `${data.nodes.length} things, ${data.edges.length} links` : "Loading…"}</h4>
                  <p className="muted gpanel__hint">Hover a node to see what it touches, click it for its links, drag it anywhere. Pick <b>Reporting lines (HR)</b> to see who can approve for whom, or <b>Dependencies</b> to see what a project waits on.</p>
                </motion.div>
              )}
            </AnimatePresence>
          </aside>
        </div>
      </div>
    </Section>
  );
}
