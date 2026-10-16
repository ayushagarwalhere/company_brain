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
  const [open, setOpen] = useState(false);

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
      <header className="dc__head">
        <div>
          <span className="mono dc__tag">Drift {String(i + 1).padStart(2, "0")}</span>
          <h3>{d.feature_name}</h3>
        </div>
        <span className="mono dc__when">{day(d.changed_at)}<br />{d.source} #{d.channel}</span>
      </header>

      <div className="diff">
        <div><span className="mono">{d.ticket} still says</span><p>{d.ticket_text}</p></div>
        <div className="now">
          <span className="mono">Decided in chat · <button className="person-link" onClick={() => openPerson(d.changed_by)}>{d.changed_by}</button></span>
          <p>{d.requirement_text}</p>
        </div>
      </div>

      <div className="trail" aria-label="How the drift happened">
        <span className="trail__node trail__node--msg"><i />Message<small><Link url={d.message_url}>{d.changed_by} · {day(d.changed_at)}</Link></small></span>
        <span className="trail__edge">changes</span>
        <span className="trail__node trail__node--req"><i />Requirement<small>newest · unshipped</small></span>
        <span className="trail__edge">amends</span>
        <span className="trail__node trail__node--ticket"><i />{d.ticket}<small>never updated</small></span>
        {(d.stale_prs.length > 0 || d.stale_docs.length > 0) && <>
          <span className="trail__edge trail__edge--broken">still on old</span>
          <span className="trail__stale">
            {d.stale_prs.map((p) => <span key={p.pr} className="stale-chip"><b>PR</b><Link url={p.url}>#{p.pr}</Link></span>)}
            {d.stale_docs.map((x) => <span key={x.id} className="stale-chip" title={`${x.title} · updated ${day(x.updated)}`}><b>DOC</b>{x.id}</span>)}
          </span>
        </>}
      </div>

      {done && <div className="resolved-note mono">{done}</div>}

      <footer className="dc__foot">
        <div className="dc__actions">
          <button className="btn btn--sm" disabled={!!busy} onClick={() => act("write-to-ticket")} title="Make the decided requirement the ticket's next version">
            {busy === "write-to-ticket" ? "Writing…" : `Write to ${d.ticket}`}
          </button>
          <button className="btn btn--ghost btn--sm" disabled={!!busy} onClick={() => act("dismiss")} title="Record a decision to keep the old scope">Keep old scope</button>
        </div>
        <div className="dc__links mono">
          <button onClick={() => focusOn(d.feature)}>Graph ↗</button>
          <button onClick={() => void specFor(d.feature)}>Spec ↗</button>
          <button onClick={() => setOpen((o) => !o)} aria-expanded={open}>{open ? "Hide path" : "Graph path"} {open ? "▴" : "▾"}</button>
        </div>
      </footer>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div className="dc__path" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.3 }}>
            <PathChips path={d.path} />
          </motion.div>
        )}
      </AnimatePresence>
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
