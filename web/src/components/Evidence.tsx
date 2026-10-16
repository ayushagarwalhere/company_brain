import type { ReactNode } from "react";

const HUES = [262, 18, 190, 140, 330, 45, 210, 100];
const hue = (s: string) => HUES[[...s].reduce((a, c) => a + c.charCodeAt(0), 0) % HUES.length];

/** Initials in a tinted circle; the same person always gets the same colour. */
export function Avatar({ name, size = 28 }: { name: string; size?: number }) {
  const h = hue(name);
  return (
    <span className="avatar" aria-hidden style={{ width: size, height: size, fontSize: size * 0.42,
      background: `hsl(${h} 70% 62% / .18)`, color: `hsl(${h} 85% 78%)`, boxShadow: `inset 0 0 0 1px hsl(${h} 70% 62% / .5)` }}>
      {name.slice(0, 1).toUpperCase()}
    </span>
  );
}

type Node = { kind: "msg" | "req" | "ticket"; title: string; sub: string };
type Stale = { kind: "pr" | "doc"; label: string; href?: string };

/** The evidence path drawn as a small diagram: message -> requirement -> ticket, then dashed orange
    edges to the PRs and docs still on the old version. A light pulse flows along the chain when `run`. */
export function EvidenceChain({ nodes, stale, run }: { nodes: Node[]; stale: Stale[]; run: boolean }) {
  const W = 760, step = 190, y = 46;
  const xs = nodes.map((_, i) => 40 + i * step);
  const tx = xs[xs.length - 1];
  const sx = tx + 150;
  const sy = (i: number) => (stale.length === 1 ? y : 18 + (i * 58) / Math.max(1, stale.length - 1));
  const rels = ["CHANGES", "AMENDS"];
  return (
    <svg className={`chain ${run ? "chain--run" : ""}`} viewBox={`0 0 ${W} 96`} role="img"
      aria-label={`${nodes.map((n) => n.title).join(" → ")}${stale.length ? `; still on the old version: ${stale.map((s) => s.label).join(", ")}` : ""}`}>
      {xs.slice(1).map((x, i) => (
        <g key={i}>
          <line x1={xs[i] + 10} y1={y} x2={x - 10} y2={y} className="chain__edge" />
          <line x1={xs[i] + 10} y1={y} x2={x - 10} y2={y} className="chain__flow" />
          <text x={(xs[i] + x) / 2} y={y - 9} className="chain__rel">{rels[i]}</text>
        </g>
      ))}
      {stale.map((s, i) => (
        <g key={s.label}>
          <path d={`M ${tx + 12} ${y} C ${tx + 70} ${y}, ${sx - 70} ${sy(i)}, ${sx - 12} ${sy(i)}`} className="chain__stale" />
          <g transform={`translate(${sx} ${sy(i)})`} className="chain__snode">
            {s.kind === "pr" ? <path d="M0 -8 L8 0 L0 8 L-8 0 Z" /> : <path d="M-6 -7 h8 l4 4 v10 h-12 z" />}
            <text x={14} y={4}>{s.label}</text>
          </g>
        </g>
      ))}
      {stale.length > 0 && <text x={sx - 66} y={y + 4} className="chain__rel chain__rel--hot chain__rel--start">STILL ON OLD</text>}
      {nodes.map((n, i) => (
        <g key={i} transform={`translate(${xs[i]} ${y})`} className={`chain__node chain__node--${n.kind}`}>
          <circle r={14} className="chain__halo" />
          {n.kind === "ticket" ? <rect x={-6} y={-6} width={12} height={12} /> : <circle r={6} />}
          <text y={30} className="chain__t">{n.title}</text>
          <text y={44} className="chain__s">{n.sub}</text>
        </g>
      ))}
    </svg>
  );
}

/** Small labelled metric used in card headers. */
export function Pill({ tone = "", children }: { tone?: "" | "hot" | "ok"; children: ReactNode }) {
  return <span className={`pill2 ${tone ? `pill2--${tone}` : ""}`}>{children}</span>;
}
