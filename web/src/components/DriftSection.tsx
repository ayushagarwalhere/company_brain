import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { api, type Drift } from "../lib/api";
import { useBrain } from "../lib/brain";
import { day, isExternal } from "../lib/ui";
import { PathChips } from "./PathChips";
import { Section } from "./Section";

const Link = ({ url, children }: { url?: string | null; children: React.ReactNode }) =>
  isExternal(url) ? <a href={url!} target="_blank" rel="noopener">{children}</a> : <>{children}</>;

function DriftCard({ d, i }: { d: Drift; i: number }) {
  const { refresh, openPerson, focusOn, specFor, actor } = useBrain();
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const act = async (kind: "write-to-ticket" | "dismiss") => {
    setBusy(kind);
    try {
      const r = await api.driftAction(kind, d.requirement, actor);
      setDone(kind === "dismiss"
        ? `Dismissed by ${r.by}: (${r.by})-[:MADE]->(Decision)-[:DISMISSES]->(Requirement)`
        : `Written to ${r.ticket} as ${r.version}: (Ticket)-[:STATES]->(new version)-[:SUPERSEDES]->(chat requirement)`);
      setTimeout(() => void refresh(), 1400);
    } catch (e) {
      alert((e as Error).message);
      setBusy(null);
    }
  };

  return (
    <motion.article layout className={`violation ${done ? "resolving" : ""}`}
      initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: 40, transition: { duration: 0.4 } }}
      transition={{ duration: 0.7, delay: i * 0.08, ease: [0.2, 0.7, 0.1, 1] }}>
      <div className="violation__head">
        <span className="mono violation__tag">Drift {String(i + 1).padStart(2, "0")} · {d.ticket}</span>
        <span className="mono muted">{day(d.changed_at)} · {d.source} #{d.channel}</span>
      </div>
      <h3>{d.feature_name}</h3>
      <div className="violation__meta">
        <button className="person-link" onClick={() => openPerson(d.changed_by)}>{d.changed_by}</button> changed the requirement in{" "}
        <Link url={d.message_url}>{d.source} #{d.channel}</Link>. {d.ticket} was never updated.
      </div>
      <div className="diff">
        <div><span className="mono">{d.ticket} still says</span><p>{d.ticket_text}</p></div>
        <div className="now"><span className="mono">Decided in chat</span><p>{d.requirement_text}</p></div>
      </div>
      {d.stale_prs.length > 0 && (
        <div className="stale">Shipped the old version: {d.stale_prs.map((p, k) => <span key={p.pr}>{k ? ", " : ""}<Link url={p.url}>#{p.pr} {p.title}</Link></span>)}</div>
      )}
      {d.stale_docs.length > 0 && (
        <div className="stale">Docs still describing the old version: {d.stale_docs.map((x, k) => <span key={x.id}>{k ? ", " : ""}{x.title} <span className="muted">(updated {day(x.updated)})</span></span>)}</div>
      )}
      <div className="mono kicker">Evidence path</div>
      <PathChips path={d.path} />
      {done && <div className="resolved-note mono">{done}</div>}
      <div className="actions">
        <button className="btn btn--sm" disabled={!!busy} onClick={() => act("write-to-ticket")} title="Make the decided requirement the ticket's next version">
          {busy === "write-to-ticket" ? "Writing…" : `Write to ${d.ticket}`}
        </button>
        <button className="btn btn--ghost btn--sm" disabled={!!busy} onClick={() => act("dismiss")} title="Record a decision to keep the old scope">Keep old scope</button>
        <button className="btn btn--ghost btn--sm" onClick={() => focusOn(d.feature)}>Show in graph</button>
        <button className="btn btn--ghost btn--sm" onClick={() => void specFor(d.feature)}>Generate spec</button>
      </div>
    </motion.article>
  );
}

export function DriftSection() {
  const { drift, version } = useBrain();
  return (
    <Section id="drift" index="004" kicker="Open drift" title="Open drift"
      intro="A chat message changed a requirement. Nothing newer replaced it, no PR implements it, and nobody chose to keep the old scope.">
      {version > 0 && drift.length === 0 && <p className="empty">No open drift. Tickets, docs and PRs match the latest decisions.</p>}
      <AnimatePresence mode="popLayout">
        {drift.map((d, i) => <DriftCard key={d.requirement} d={d} i={i} />)}
      </AnimatePresence>
    </Section>
  );
}
