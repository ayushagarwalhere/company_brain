/** Initials in an outlined circle. */
export function Avatar({ name, size = 28 }: { name: string; size?: number }) {
  return (
    <span className="avatar" aria-hidden style={{ width: size, height: size, fontSize: size * 0.4 }}>
      {name.slice(0, 1).toUpperCase()}
    </span>
  );
}

type Node = { kind: "msg" | "req" | "ticket"; title: string; sub?: string };
/** A PR or doc on the drifted ticket. `unmatched`: merged after the decision with no IMPLEMENTS link, so not stale. */
type Stale = { kind: "pr" | "doc"; label: string; href?: string; unmatched?: boolean };

/** The evidence path as a small diagram: message -> requirement -> ticket, then dashed edges to the PRs and docs
    still on the old version. A pulse flows along the chain when `run`. */
export function EvidenceChain({ nodes, stale, run }: { nodes: Node[]; stale: Stale[]; run: boolean }) {
  const W = 760, step = 190, y = 40;
  const xs = nodes.map((_, i) => 40 + i * step);
  const tx = xs[xs.length - 1];
  const sx = tx + 150;
  const sy = (i: number) => (stale.length === 1 ? y : 14 + (i * 52) / Math.max(1, stale.length - 1));
  const rels = ["CHANGES", "AMENDS"];
  const old = stale.filter((s) => !s.unmatched), loose = stale.filter((s) => s.unmatched);
  return (
    <svg className={`chain ${run ? "chain--run" : ""}`} viewBox={`0 0 ${W} 80`} role="img"
      aria-label={`${nodes.map((n) => n.title).join(" → ")}${old.length ? `; still on the old version: ${old.map((s) => s.label).join(", ")}` : ""}${
        loose.length ? `; unmatched, may implement the new scope: ${loose.map((s) => s.label).join(", ")}` : ""}`}>
      {xs.slice(1).map((x, i) => (
        <g key={i}>
          <line x1={xs[i] + 10} y1={y} x2={x - 10} y2={y} className="chain__edge" />
          <line x1={xs[i] + 10} y1={y} x2={x - 10} y2={y} className="chain__flow" />
          <text x={(xs[i] + x) / 2} y={y - 9} className="chain__rel">{rels[i]}</text>
        </g>
      ))}
      {stale.map((s, i) => (
        <g key={s.label}>
          <path d={`M ${tx + 12} ${y} C ${tx + 70} ${y}, ${sx - 70} ${sy(i)}, ${sx - 12} ${sy(i)}`} className={s.unmatched ? "chain__loose" : "chain__stale"} />
          <g transform={`translate(${sx} ${sy(i)})`} className={`chain__snode ${s.unmatched ? "chain__snode--loose" : ""}`}>
            {s.kind === "pr" ? <path d="M0 -8 L8 0 L0 8 L-8 0 Z" /> : <path d="M-6 -7 h8 l4 4 v10 h-12 z" />}
            <text x={14} y={4}>{s.label}</text>
          </g>
        </g>
      ))}
      {nodes.map((n, i) => (
        <g key={i} transform={`translate(${xs[i]} ${y})`} className={`chain__node chain__node--${n.kind}`}>
          <circle r={14} className="chain__halo" />
          {n.kind === "ticket" ? <rect x={-6} y={-6} width={12} height={12} /> : <circle r={6} />}
          <text y={30} className="chain__t">{n.title}</text>
        </g>
      ))}
    </svg>
  );
}
