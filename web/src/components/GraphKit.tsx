import type cytoscape from "cytoscape";
import type { Core, NodeSingular } from "cytoscape";
import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState, type MutableRefObject, type ReactNode } from "react";
import { cssVar, typeColor } from "../lib/ui";

/* Shared by every graph view (feature graph, feature map, impact, answer graph): one stylesheet, the type glyphs,
   and the interaction kit. Page scroll stays page scroll: zoom is Ctrl/⌘ + wheel (or pinch, or the buttons).
   Hovering a node shows its full text and fades everything it isn't linked to. Find highlights matches in amber.
   Type chips hide and show node types. Fullscreen, and keys: + − to zoom, F to fit, arrows to pan, Esc. */

const TOUCH = typeof window !== "undefined" && matchMedia("(pointer: coarse)").matches;
const MAC = typeof navigator !== "undefined" && /Mac|iP(hone|ad)/.test(navigator.platform);
export const ZOOM_KEY = MAC ? "⌘" : "Ctrl";

export function styleFor(): cytoscape.StylesheetStyle[] {
  const c = (v: string) => cssVar(v);
  const coral = c("--c-coral"), blue = c("--c-blue"), amber = c("--c-amber"), violet = c("--c-violet");
  return [
    // labels always readable: bright text on a dark chip with a dark halo, whether or not the node is selected or dimmed
    { selector: "node", style: { "background-color": "data(color)", label: "data(short)", "font-family": "Geist Mono, monospace", "font-size": 11,
        color: "#f4f4f4", "text-outline-color": "#000", "text-outline-width": 2, "text-outline-opacity": 0.9,
        "text-background-color": "#050505", "text-background-opacity": 0.78, "text-background-padding": "3px", "text-background-shape": "roundrectangle",
        "text-wrap": "ellipsis", "text-max-width": "130px", "text-valign": "bottom", "text-margin-y": 7, width: 13, height: 13,
        "border-width": 1, "border-color": "#000", "transition-property": "opacity, background-color, width, height, border-color", "transition-duration": 0.3 } as cytoscape.Css.Node },
    { selector: "node[type='Feature']", style: { width: 22, height: 22, "font-size": 12, color: c("--ink"), "font-family": "Geist, sans-serif", "text-valign": "top", "text-margin-y": -8, shape: "round-rectangle" } },
    { selector: "node[type='Ticket']", style: { shape: "rectangle", width: 18, height: 12 } },
    { selector: "node[type='PullRequest']", style: { shape: "diamond", width: 16, height: 16 } },
    { selector: "node[type='Document']", style: { shape: "tag", width: 16, height: 16 } },
    { selector: "node[type='Message']", style: { shape: "round-rectangle", width: 14, height: 10 } },
    { selector: "node[type='Requirement']", style: { shape: "hexagon", width: 15, height: 15 } },
    { selector: "node[type='Person']", style: { width: 12, height: 12 } },
    // drift is the one thing graphs colour on their own: coral ring, coral label, coral path
    { selector: "node[?drift]", style: { width: 20, height: 20, "background-color": "#000", "border-width": 3, "border-color": coral, color: coral, "font-weight": 600,
        "underlay-color": coral, "underlay-padding": 6, "underlay-opacity": 0.18, "underlay-shape": "ellipse" } as unknown as cytoscape.Css.Node },
    { selector: "node[?stale]", style: { "border-width": 2, "border-color": coral, "border-style": "dashed" } },
    { selector: "edge", style: { width: 1, "line-color": c("--line-3"), "target-arrow-color": c("--line-3"), "target-arrow-shape": "triangle", "arrow-scale": 0.7,
        "curve-style": "bezier", "font-family": "Geist Mono, monospace", "font-size": 9.5, color: "#e6e6e6", "text-rotation": "autorotate",
        "text-background-color": "#000", "text-background-opacity": 1, "text-background-padding": "2px",
        "transition-property": "opacity, line-color, width", "transition-duration": 0.3 } as cytoscape.Css.Edge },
    { selector: "edge[bend]", style: { "curve-style": "unbundled-bezier", "control-point-distances": "data(bend)", "control-point-weights": 0.5 } as cytoscape.Css.Edge },
    { selector: "edge.path", style: { width: 2, "line-color": coral, "target-arrow-color": coral, "line-style": "dashed", "line-dash-pattern": [7, 5] } },
    { selector: "edge.lit", style: { width: 2.2, "line-color": violet, "target-arrow-color": violet, "line-style": "dashed", "line-dash-pattern": [7, 5], label: "data(label)", color: violet } },
    { selector: "edge.hover, edge:selected", style: { label: "data(label)", "line-color": "#fff", "target-arrow-color": "#fff", width: 1.6 } },
    { selector: "edge.path.hover", style: { "line-color": coral, "target-arrow-color": coral, color: coral } },
    { selector: "node.dim", style: { "background-opacity": 0.25, "border-opacity": 0.25, "text-opacity": 0.85 } },
    { selector: "node.faded", style: { "background-opacity": 0.14, "border-opacity": 0.14, "text-opacity": 0.7 } },
    { selector: "node.ghost", style: { "background-opacity": 0.1, "border-opacity": 0.1, "text-opacity": 0.6 } },
    { selector: "edge.dim", style: { opacity: 0.22 } },
    { selector: "edge.faded", style: { opacity: 0.12 } },
    { selector: "edge.ghost", style: { opacity: 0.1 } },
    { selector: ".hidden", style: { display: "none" } },
    { selector: "node.match", style: { "underlay-color": amber, "underlay-padding": 9, "underlay-opacity": 0.5, "underlay-shape": "ellipse", color: amber, "text-opacity": 1, "z-index": 9 } as unknown as cytoscape.Css.Node },
    { selector: "node:selected", style: { "border-width": 3, "border-color": blue, "border-style": "solid", color: "#fff", "text-opacity": 1, "font-weight": 600, "z-index": 10,
        "text-background-color": blue, "text-background-opacity": 0.35,
        "underlay-color": blue, "underlay-padding": 9, "underlay-opacity": 0.35, "underlay-shape": "ellipse" } as unknown as cytoscape.Css.Node },
  ];
}

/** Node-type glyphs for legends and chips: shape tells the type apart. */
export function TypeGlyph({ type }: { type: string }) {
  const f = typeColor(type);
  const shape = ({
    Person: <circle cx="7" cy="7" r="5" fill={f} />,
    Message: <rect x="1.5" y="3.5" width="11" height="7" rx="2" fill={f} />,
    Requirement: <path d="M7 1.5 L12 4.3 V9.7 L7 12.5 L2 9.7 V4.3 Z" fill={f} />,
    Ticket: <rect x="1.5" y="3" width="11" height="8" fill={f} />,
    PullRequest: <path d="M7 1 L13 7 L7 13 L1 7 Z" fill={f} />,
    Document: <path d="M2 2 H9 L12.5 7 L9 12 H2 Z" fill={f} />,
    Team: <rect x="0.5" y="4" width="13" height="6" rx="2" fill={f} />,
    Project: <rect x="1.5" y="1.5" width="11" height="11" rx="3" fill={f} />,
    Deliverable: <path d="M7 1 L8.8 5.2 L13 5.5 L9.8 8.4 L10.8 13 L7 10.6 L3.2 13 L4.2 8.4 L1 5.5 L5.2 5.2 Z" fill={f} />,
    Client: <path d="M2 3 Q7 1 12 3 V11 Q7 13 2 11 Z" fill={f} />,
    Task: <path d="M7 1.5 L13 12.5 H1 Z" fill={f} />,
    Drift: <circle cx="7" cy="7" r="5" fill="#000" stroke="var(--c-coral)" strokeWidth="2" />,
  } as Record<string, JSX.Element>)[type] || <circle cx="7" cy="7" r="5" fill={f} />;
  return <svg viewBox="0 0 14 14" aria-hidden>{shape}</svg>;
}

type Tip = { x: number; y: number; type: string; label: string; text?: string | null; links: number; extra?: string };

const nodeLabel = (n: NodeSingular) => String(n.data("label") || n.data("short") || n.id());

/** The interaction kit for one cytoscape instance. Call `attach(cy)` each time the instance is (re)created. */
export function useGraphKit(cy: MutableRefObject<Core | null>, opts: { pad?: number; onEscape?: () => void; describe?: (n: NodeSingular) => string | undefined } = {}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  const [full, setFull] = useState(false);
  const [tip, setTip] = useState<Tip | null>(null);
  const [hint, setHint] = useState(false);
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<string[]>([]);
  const [at, setAt] = useState(0);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const hiddenRef = useRef(hidden);
  hiddenRef.current = hidden;
  const optsRef = useRef(opts);
  optsRef.current = opts;
  const pad = opts.pad ?? 40;

  const fit = useCallback(() => {
    const c = cy.current;
    if (c && !c.destroyed()) c.animate({ fit: { eles: c.elements(":visible"), padding: pad } }, { duration: 420, easing: "ease-in-out-cubic" });
  }, [cy, pad]);
  const zoomBy = useCallback((k: number) => {
    const c = cy.current;
    if (!c || c.destroyed()) return;
    const level = Math.max(c.minZoom(), Math.min(c.maxZoom(), c.zoom() * k));
    c.animate({ zoom: { level, renderedPosition: { x: c.width() / 2, y: c.height() / 2 } } }, { duration: 200 });
  }, [cy]);
  const panBy = useCallback((x: number, y: number) => { const c = cy.current; if (c && !c.destroyed()) c.animate({ panBy: { x, y } }, { duration: 160 }); }, [cy]);

  const applyHidden = useCallback((c: Core) => {
    c.batch(() => { c.nodes().forEach((n) => { n.toggleClass("hidden", hiddenRef.current.has(n.data("type"))); }); });
  }, []);

  const attach = useCallback((c: Core) => {
    c.userZoomingEnabled(TOUCH);  // touch keeps pinch-zoom; with a mouse the wheel scrolls the page unless Ctrl/⌘ is held
    c.boxSelectionEnabled(false);
    setZoom(c.zoom());
    c.on("zoom", () => setZoom(c.zoom()));
    c.on("zoom pan", () => setTip(null));
    c.on("mouseover", "node", (e) => {
      const n = e.target as NodeSingular;
      const p = n.renderedPosition();
      setTip({ x: p.x, y: p.y - n.renderedOuterHeight() / 2, type: n.data("type"), label: nodeLabel(n), text: n.data("text"),
        links: n.connectedEdges(":visible").length, extra: optsRef.current.describe?.(n) });
      if (!c.$("node:selected").length) {
        c.batch(() => { c.elements().addClass("ghost"); n.closedNeighborhood().removeClass("ghost"); });
      }
    });
    c.on("mouseout", "node", () => { setTip(null); c.elements().removeClass("ghost"); });
    c.on("tap", () => setTip(null));
    c.on("add", "node", (e) => { if (hiddenRef.current.has(e.target.data("type"))) e.target.addClass("hidden"); });
    applyHidden(c);
  }, [applyHidden]);

  // Ctrl/⌘ + wheel zooms toward the pointer; a plain wheel scrolls the page and shows how to zoom
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    let hintTimer: ReturnType<typeof setTimeout> | undefined, lastHint = 0;
    const onWheel = (e: WheelEvent) => {
      const c = cy.current;
      if (!c || c.destroyed()) return;
      if (e.ctrlKey || e.metaKey || full) {
        e.preventDefault();
        const r = c.container()!.getBoundingClientRect();
        const level = Math.max(c.minZoom(), Math.min(c.maxZoom(), c.zoom() * Math.pow(1.0018, -e.deltaY)));
        c.zoom({ level, renderedPosition: { x: e.clientX - r.left, y: e.clientY - r.top } });
      } else if (Math.abs(e.deltaY) > 4 && Date.now() - lastHint > 5000) {
        lastHint = Date.now();
        setHint(true);
        clearTimeout(hintTimer);
        hintTimer = setTimeout(() => setHint(false), 1600);
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => { el.removeEventListener("wheel", onWheel); clearTimeout(hintTimer); };
  }, [cy, full]);

  // keys, when focus is inside the graph
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      const k = e.key;
      if (k === "+" || k === "=") zoomBy(1.25);
      else if (k === "-" || k === "_") zoomBy(0.8);
      else if (k === "f" || k === "F" || k === "0") fit();
      else if (k === "ArrowLeft") panBy(60, 0);
      else if (k === "ArrowRight") panBy(-60, 0);
      else if (k === "ArrowUp") panBy(0, 60);
      else if (k === "ArrowDown") panBy(0, -60);
      else if (k === "Escape") { if (full) setFull(false); else optsRef.current.onEscape?.(); }
      else return;
      e.preventDefault();
    };
    el.addEventListener("keydown", onKey);
    return () => el.removeEventListener("keydown", onKey);
  }, [zoomBy, fit, panBy, full]);

  // fullscreen: lock the page, resize the canvas, refit; Esc anywhere leaves (only on a real toggle, not on mount)
  const wasFull = useRef(full);
  useEffect(() => {
    if (wasFull.current === full) return;
    wasFull.current = full;
    document.body.classList.toggle("gk-lock", full);
    const t = setTimeout(() => { const c = cy.current; if (c && !c.destroyed()) { c.resize(); fit(); } }, 40);
    if (!full) return () => clearTimeout(t);
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setFull(false); };
    addEventListener("keydown", esc);
    return () => { clearTimeout(t); removeEventListener("keydown", esc); document.body.classList.remove("gk-lock"); };
  }, [full, cy, fit]);

  // find: highlight every match, centre the current one
  const find = useCallback((q: string) => {
    setQuery(q);
    const c = cy.current;
    if (!c || c.destroyed()) return;
    c.nodes().removeClass("match");
    const s = q.trim().toLowerCase();
    if (!s) { setMatches([]); return; }
    const hits = c.nodes(":visible").filter((n) => `${nodeLabel(n)} ${n.id()} ${n.data("short") || ""}`.toLowerCase().includes(s));
    hits.addClass("match");
    setMatches(hits.map((n) => n.id()));
    setAt(0);
    if (hits.length) c.animate({ center: { eles: hits[0] }, zoom: Math.max(c.zoom(), 1.1) }, { duration: 380 });
  }, [cy]);
  const next = useCallback(() => {
    const c = cy.current;
    if (!c || !matches.length) return;
    const i = (at + 1) % matches.length;
    setAt(i);
    c.animate({ center: { eles: c.getElementById(matches[i]) }, zoom: Math.max(c.zoom(), 1.1) }, { duration: 320 });
  }, [cy, matches, at]);

  const toggleType = useCallback((t: string) => {
    setHidden((h) => {
      const n = new Set(h);
      if (n.has(t)) n.delete(t); else n.add(t);
      hiddenRef.current = n;
      const c = cy.current;
      if (c && !c.destroyed()) applyHidden(c);
      return n;
    });
  }, [cy, applyHidden]);

  return { wrap, attach, zoom, full, setFull, tip, hint, query, find, matches, at, next, hidden, toggleType, fit, zoomBy };
}
export type Kit = ReturnType<typeof useGraphKit>;

/** Top bar over a canvas: optional view controls on the left, find, zoom, fit, fullscreen on the right. */
export function GraphBar({ kit, left, findable = true }: { kit: Kit; left?: ReactNode; findable?: boolean }) {
  return (
    <div className="gk__bar">
      {left}
      {findable && (
        <label className="gk__find">
          <span aria-hidden>⌕</span>
          <input value={kit.query} onChange={(e) => kit.find(e.target.value)} placeholder="Find a node…" aria-label="Find a node in the graph"
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); kit.next(); } if (e.key === "Escape") kit.find(""); }} />
          {kit.query && <span>{kit.matches.length ? `${kit.at + 1}/${kit.matches.length}` : "0"}</span>}
        </label>
      )}
      <span className="gk__spacer" />
      <div className="gk__group" role="group" aria-label="Zoom">
        <button onClick={() => kit.zoomBy(0.8)} aria-label="Zoom out" title="Zoom out (−)">−</button>
        <span className="gk__zoom">{Math.round(kit.zoom * 100)}%</span>
        <button onClick={() => kit.zoomBy(1.25)} aria-label="Zoom in" title="Zoom in (+)">+</button>
        <button onClick={kit.fit} title="Fit everything (F)">Fit</button>
        <button onClick={() => kit.setFull(!kit.full)} aria-pressed={kit.full} title={kit.full ? "Exit fullscreen (Esc)" : "Fullscreen"}>{kit.full ? "✕" : "⤢"}</button>
      </div>
    </div>
  );
}

/** Hover card and the "hold Ctrl to zoom" hint, drawn over the canvas. */
export function GraphOverlay({ kit }: { kit: Kit }) {
  const t = kit.tip;
  return (
    <>
      {t && (
        <div className="gk__tip" style={{ left: t.x, top: t.y }} role="tooltip">
          <span className="mono gpanel__type"><TypeGlyph type={t.type} />{t.type}</span>
          <b>{t.label}</b>
          {t.text && t.text !== t.label && <p>{t.text.length > 180 ? `${t.text.slice(0, 179)}…` : t.text}</p>}
          <small>{t.extra ? `${t.extra} · ` : ""}{t.links} {t.links === 1 ? "link" : "links"} · click for details</small>
        </div>
      )}
      <AnimatePresence>
        {kit.hint && (
          <motion.div className="gk__hint" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
            Hold {ZOOM_KEY} and scroll to zoom · or use + −
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

/** Legend that doubles as a filter: click a type to hide or show it. */
export function TypeFilters({ kit, types, extra }: { kit: Kit; types: string[]; extra?: ReactNode }) {
  return (
    <div className="gk__filters" role="group" aria-label="Show or hide node types">
      {types.map((t) => {
        const off = kit.hidden.has(t);
        return (
          <button key={t} className={`gk__chip ${off ? "gk__chip--off" : ""}`} onClick={() => kit.toggleType(t)} aria-pressed={!off} title={off ? `Show ${t}` : `Hide ${t}`}>
            <TypeGlyph type={t} />{t}
          </button>
        );
      })}
      {extra}
    </div>
  );
}

export function KeysHint() {
  return <span className="gk__keys">Hover to trace · click for details · <kbd>{ZOOM_KEY}</kbd>+scroll zoom · <kbd>F</kbd> fit · <kbd>Esc</kbd></span>;
}
