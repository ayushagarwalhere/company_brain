import { AnimatePresence, motion, useInView } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { api, type Drift } from "../lib/api";
import { useBrain } from "../lib/brain";
import { scrollToEl, useStill } from "../lib/fx";
import { day, isExternal, plural } from "../lib/ui";
import { EASE } from "./Motion";
import { Avatar, EvidenceChain } from "./Evidence";
import { PathChips } from "./PathChips";
import { Section } from "./Section";

const Link = ({ url, children }: { url?: string | null; children: React.ReactNode }) =>
  isExternal(url) ? <a href={url!} target="_blank" rel="noopener">{children}</a> : <>{children}</>;

/** Days since the decision, counted from the scenario's reference date when the graph was built from the scenario
    (so demo numbers don't change as real time passes), otherwise from now. */
const daysOpen = (iso: string, reference?: string | null) =>
  Math.max(0, Math.floor(((reference ? new Date(reference).getTime() : Date.now()) - new Date(iso).getTime()) / 86400000));

export const cardId = (requirement: string) => `drift-card-${requirement.replace(/[^a-zA-Z0-9_-]/g, "_")}`;

type Phase = "open" | "resolving" | "resolved" | "dismissing" | "dismissed";

function DriftCard({ d, i, flash }: { d: Drift; i: number; flash: boolean }) {
  const { refresh, openPerson, focusOn, specFor, actor, stats } = useBrain();
  const still = useStill();
  const [phase, setPhase] = useState<Phase>("open");
  const [note, setNote] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLElement>(null);
  const seen = useInView(ref, { once: true, margin: "-80px" });
  const confidence = (d as Drift & { confidence?: number | null }).confidence;
  const openDays = daysOpen(d.changed_at, stats?.build?.reference_date);
  const quote = d.message_text && d.message_text.trim() !== d.requirement_text.trim() ? d.message_text : null;

  const act = async (kind: "write-to-ticket" | "dismiss") => {
    setPhase(kind === "dismiss" ? "dismissing" : "resolving");  // optimistic: the card starts resolving at once
    try {
      const r = await api.driftAction(kind, d.requirement, actor);
      setNote(kind === "dismiss"
        ? `Kept the old scope · ${r.by} -[:MADE]-> Decision -[:DISMISSES]-> requirement`
        : `${r.ticket} now carries the decision as ${r.version} · Ticket -[:STATES]-> new version -[:SUPERSEDES]-> chat requirement`);
      setPhase(kind === "dismiss" ? "dismissed" : "resolved");
      setTimeout(() => void refresh(), still ? 400 : 2200);
    } catch (e) {
      setPhase("open");
      alert((e as Error).message);
    }
  };

  const done = phase === "resolved" || phase === "dismissed";
  const tone = phase === "resolving" || phase === "resolved" ? "ok" : phase === "dismissing" || phase === "dismissed" ? "grey" : "drift";

  return (
    <motion.article layout ref={ref} id={cardId(d.requirement)}
      className={`violation violation--${tone} ${done ? "violation--done" : ""} ${flash ? "violation--flash" : ""}`}
      initial={still ? false : { opacity: 0, x: -28 }} animate={{ opacity: phase === "dismissed" ? 0.55 : 1, x: 0 }}
      exit={{ opacity: 0, height: 0, marginBottom: 0, transition: { duration: 0.45, ease: EASE } }}
      transition={{ duration: 0.75, delay: still ? 0 : i * 0.1, ease: EASE }}>
      <motion.span className="violation__edge" aria-hidden initial={still ? false : { scaleY: 0 }} animate={{ scaleY: 1 }}
        transition={{ duration: 0.9, delay: still ? 0 : 0.25 + i * 0.1, ease: EASE }} />

      <AnimatePresence initial={false} mode="wait">
        {done ? (
          <motion.div key="done" className="dc__done" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
            <span className={`dc__check ${tone}`} aria-hidden>{phase === "resolved" ? "✓" : "–"}</span>
            <div>
              <b>{d.feature_name} · {d.ticket}</b>
              <p className="mono">{phase === "resolved" ? "Resolved" : "Dismissed"} · {note}</p>
            </div>
          </motion.div>
        ) : (
          <motion.div key="full" exit={{ opacity: 0, height: 0, transition: { duration: 0.45, ease: EASE } }} style={{ overflow: "hidden" }}>
            <header className="dc__head">
              <div>
                <span className="mono dc__tag"><i className="dc__dot" />Drift {String(i + 1).padStart(2, "0")} · {d.ticket}
                  {typeof confidence === "number" && <span className="dc__conf" title="Extractor confidence">conf {confidence.toFixed(2)}</span>}
                </span>
                <h3>{d.feature_name}</h3>
                <p className="mono dc__stats">
                  <b className="hot">{openDays}</b> {plural(openDays, "day", "days")} open
                  <i>·</i><b>{d.stale_prs.length}</b> stale {plural(d.stale_prs.length, "PR", "PRs")}
                  <i>·</i><b>{d.stale_docs.length}</b> stale {plural(d.stale_docs.length, "doc", "docs")}
                </p>
              </div>
            </header>

            <div className="vs">
              <div className="vs__old">
                <span className="mono vs__k">{d.ticket} still says <em>old</em></span>
                <p>{d.ticket_text}</p>
              </div>
              <span className="vs__neq" aria-hidden>≠</span>
              <div className="vs__new">
                <span className="mono vs__k">Decided in chat <em>new</em></span>
                <p title={quote ? `Source message: "${quote}"` : undefined}>{d.requirement_text}</p>
                <div className="vs__who">
                  <Avatar name={d.changed_by} size={26} />
                  <button className="person-link" onClick={() => openPerson(d.changed_by)}>{d.changed_by}</button>
                  <span className="mono">{day(d.changed_at)} · {d.source} #{d.channel}</span>
                  {d.message_url && isExternal(d.message_url) && <Link url={d.message_url}>open ↗</Link>}
                </div>
              </div>
            </div>

            <EvidenceChain run={seen && !still}
              nodes={[{ kind: "msg", title: "MESSAGE" }, { kind: "req", title: "REQUIREMENT" }, { kind: "ticket", title: d.ticket }]}
              stale={[...d.stale_prs.map((p) => ({ kind: "pr" as const, label: `PR #${p.pr}${p.status === "old_after" ? " · after decision" : ""}` })),
                      ...(d.unmatched_prs || []).map((p) => ({ kind: "pr" as const, unmatched: true, label: `PR #${p.pr} · may implement new` })),
                      ...d.stale_docs.map((x) => ({ kind: "doc" as const, label: x.id }))]} />

            <footer className="dc__foot">
              <div className="dc__actions">
                <button className="btn btn--sm" disabled={phase !== "open"} onClick={() => act("write-to-ticket")} title="Make the decided requirement the ticket's next version">
                  {phase === "resolving" ? "Writing…" : `Write to ${d.ticket}`}
                </button>
                <button className="btn btn--ghost btn--sm" disabled={phase !== "open"} onClick={() => act("dismiss")} title="Record a decision to keep the old scope">
                  {phase === "dismissing" ? "Recording…" : "Keep old scope"}
                </button>
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
          </motion.div>
        )}
      </AnimatePresence>
    </motion.article>
  );
}

export function DriftSection() {
  const { drift, version, arrival } = useBrain();
  const [flash, setFlash] = useState<string | null>(null);

  // A drift that just arrived (Simulate, or a bot over SSE): once its card exists, scroll to it and flash it.
  useEffect(() => {
    if (!arrival) return;
    const target = drift.find((d) => d.requirement === arrival.requirement)
      || [...drift].filter((d) => d.ticket === arrival.ticket).sort((a, b) => b.changed_ms - a.changed_ms)[0];
    if (!target) return;
    setFlash(target.requirement);
    const t1 = setTimeout(() => { const el = document.getElementById(cardId(target.requirement)); if (el) scrollToEl(el, -110); }, 250);
    const t2 = setTimeout(() => setFlash(null), 3200);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [arrival, drift]);

  return (
    <Section id="drift" index="004" kicker="Open drift" title="Open drift"
      intro="A chat message changed a requirement. Nothing newer replaced it, no PR implements it, and nobody chose to keep the old scope.">
      {version > 0 && drift.length === 0 && <p className="empty">No open drift. Tickets, docs and PRs match the latest decisions.</p>}
      <AnimatePresence mode="popLayout">
        {drift.map((d, i) => <DriftCard key={d.requirement} d={d} i={i} flash={flash === d.requirement} />)}
      </AnimatePresence>
    </Section>
  );
}
