import cytoscape, { type Core } from "cytoscape";
import { useCallback, useEffect, useRef, useState } from "react";
import { useStill } from "../lib/fx";
import { cssVar, parsePath, TYPE_VAR } from "../lib/ui";
import { GraphBar, GraphOverlay, styleFor, TypeGlyph, useGraphKit } from "./GraphKit";

type Hop = { from: string; rel: string; to: string };

/** Graph path strings -> nodes in first-seen order and the hops between them, in the order the agent walked them. */
function hopsOf(paths: string[]) {
  const nodes = new Map<string, { id: string; type: string; row: number; col: number }>();
  const hops: Hop[] = [];
  paths.forEach((p, row) => {
    let prev: string | null = null, rel: { rel: string; dir: "in" | "out" } | null = null, col = 0;
    for (const t of parsePath(p)) {
      if (t.kind === "sep") { prev = null; rel = null; continue; }
      if (t.kind === "rel") { rel = t; continue; }
      if (t.kind !== "node") continue;
      const id = t.label.split(" @ ")[0].trim();
      if (!nodes.has(id)) nodes.set(id, { id, type: t.type, row, col });
      if (prev && rel && prev !== id) hops.push(rel.dir === "out" ? { from: prev, rel: rel.rel, to: id } : { from: id, rel: rel.rel, to: prev });
      prev = id; rel = null; col++;
    }
  });
  return { nodes: [...nodes.values()], hops };
}

const short = (id: string, type: string) =>
  type === "PullRequest" ? id.replace(/^PR-/, "PR #") : type === "Requirement" ? id.replace(/^req:/, "").replace(/:v(\d+)$/, " v$1") : id.replace(/^dec:/, "");

/** Right half of "Ask the graph": the nodes behind the answer, lit hop by hop (violet) as the agent walked them.
    Replay re-walks it; the hop chips below trace one hop at a time. */
export function AnswerGraph({ paths, busy }: { paths: string[]; busy: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const still = useStill();
  const [lit, setLit] = useState(0);
  const [run, setRun] = useState(0);
  const [focus, setFocus] = useState<number | null>(null);
  const { nodes, hops } = hopsOf(paths.slice(0, 6));
  const kit = useGraphKit(cy, { pad: 36 });

  useEffect(() => {
    if (!host.current) return;
    let c = cy.current;
    if (!c || c.destroyed()) {
      c = cytoscape({ container: host.current, style: styleFor(), minZoom: 0.4, maxZoom: 2.2 });
      cy.current = c;
      kit.attach(c);
    }
    const g = c;
    g.elements().remove();
    g.add([
      ...nodes.map((n) => ({ group: "nodes" as const, data: { id: n.id, type: n.type, short: short(n.id, n.type), label: short(n.id, n.type), color: cssVar(TYPE_VAR[n.type] || "--muted") },
        position: { x: n.col * 140, y: n.row * 120 + (n.col % 2) * 70 } })),
      ...hops.map((h, i) => ({ group: "edges" as const, data: { id: `h${i}`, source: h.from, target: h.to, label: h.rel } })),
    ]);
    g.nodes().style({ "font-size": 12, width: 18, height: 18 });
    g.elements().addClass("dim");
    g.fit(undefined, 40);
    if (!hops.length) { g.elements().removeClass("dim"); return; }
    // light the walk: each hop's edge and both ends, one after another
    setLit(0);
    const step = (i: number) => {
      const e = g.getElementById(`h${i}`);
      e.removeClass("dim").addClass("lit");
      e.connectedNodes().removeClass("dim");
      setLit(i + 1);
    };
    if (still) { hops.forEach((_, i) => step(i)); return; }
    const ts = hops.map((_, i) => setTimeout(() => step(i), 350 + i * 420));
    return () => ts.forEach(clearTimeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paths.join("|"), still, run]);

  // flowing dashes along the lit hops
  useEffect(() => {
    if (still) return;
    let raf = 0, off = 0;
    const tick = () => {
      off = (off + 0.4) % 1200;
      const c = cy.current;
      if (c && !c.destroyed()) c.edges(".lit").style("line-dash-offset", -off);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [still]);
  useEffect(() => () => { cy.current?.destroy(); }, []);

  /** Trace one hop: fade everything but that edge and its two ends. */
  const trace = useCallback((i: number | null) => {
    setFocus(i);
    const c = cy.current;
    if (!c || c.destroyed()) return;
    c.elements().removeClass("ghost");
    if (i === null) return;
    const e = c.getElementById(`h${i}`);
    c.elements().addClass("ghost");
    e.removeClass("ghost");
    e.connectedNodes().removeClass("ghost");
  }, []);

  const types = [...new Set(nodes.map((n) => n.type))];
  return (
    <div className="agraph">
      <div className="console__bar mono">
        <span>Answer graph</span>
        <span>{busy ? "walking the graph…" : hops.length ? `${lit} / ${hops.length} hops` : nodes.length ? `${nodes.length} nodes` : "no path"}</span>
      </div>
      <div ref={kit.wrap} className={`agraph__canvas gk ${kit.full ? "gk--full" : ""}`}>
        <div ref={host} className="canvas__graph" tabIndex={0} aria-label="Answer graph. Plus and minus zoom, F fits." />
        {nodes.length > 0 && (
          <GraphBar kit={kit} findable={false} left={hops.length > 0 && !busy ? (
            <div className="gk__group"><button onClick={() => setRun((r) => r + 1)} title="Walk the path again">↻ Replay</button></div>
          ) : undefined} />
        )}
        <GraphOverlay kit={kit} />
        {!busy && !nodes.length && <p className="agraph__empty muted">This answer didn't need a path.</p>}
      </div>
      {hops.length > 0 && !busy && (
        <div className="agraph__hops mono" onMouseLeave={() => trace(null)}>
          {hops.map((h, i) => (
            <button key={i} className={i < lit || focus === i ? "on" : ""} onMouseEnter={() => trace(i)} onFocus={() => trace(i)} onBlur={() => trace(null)}>
              <b>{i + 1}</b>{short(h.from, nodes.find((n) => n.id === h.from)?.type || "")} → {h.rel} → {short(h.to, nodes.find((n) => n.id === h.to)?.type || "")}
            </button>
          ))}
        </div>
      )}
      {types.length > 0 && <div className="agraph__legend mono">{types.map((t) => <span key={t}><TypeGlyph type={t} />{t}</span>)}</div>}
    </div>
  );
}
