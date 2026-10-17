import { AnimatePresence, motion, useInView } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { api, type Drift, type FixPlan, type Task } from "../lib/api";
import { useBrain } from "../lib/brain";
import { scrollToEl, useStill } from "../lib/fx";
import { day, isExternal, PEOPLE, plural } from "../lib/ui";
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
  const { refresh, openPerson, focusOn, specFor, actor, setActor, stats } = useBrain();
  const still = useStill();
  const [phase, setPhase] = useState<Phase>("open");
  const [note, setNote] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [plan, setPlan] = useState<FixPlan | null>(null);
  const [planOpen, setPlanOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [made, setMade] = useState<Task[]>([]);
  const ref = useRef<HTMLElement>(null);
  const seen = useInView(ref, { once: true, margin: "-80px" });
  const confidence = (d as Drift & { confidence?: number | null }).confidence;
  const openDays = daysOpen(d.changed_at, stats?.build?.reference_date);
  const quote = d.message_text && d.message_text.trim() !== d.requirement_text.trim() ? d.message_text : null;

  const togglePlan = async () => {
    setPlanOpen((o) => !o);
    if (!plan) {
      try { setPlan(await api.plan(d.requirement)); } catch (e) { setErr((e as Error).message); }
    }
  };

  /** Approve the fix plan, or keep the old scope. Both check decision rights on the server (pipeline.work):
      only the ticket's creator or assignee may decide, and a refusal names who can. */
  const act = async (kind: "apply" | "keep") => {
    setErr(null);
    setPhase(kind === "keep" ? "dismissing" : "resolving");  // optimistic: the card starts resolving at once
    try {
      if (kind === "keep") {
        const r = await api.keepScope(d.requirement, actor);
        setNote(`Kept the old scope · ${r.by} -[:MADE]-> Decision -[:DISMISSES]-> requirement`);
        setPhase("dismissed");
      } else {
        const r = await api.applyPlan(d.requirement, actor);
        setMade(r.tasks);
        setNote(`${r.ticket} now carries the decision (${r.version.split(":").pop()}) · approved by ${r.by}`
          + (r.tasks.length ? ` · ${r.tasks.length} ${plural(r.tasks.length, "follow-up", "follow-ups")} assigned` : ""));
        setPhase("resolved");
      }
      setTimeout(() => void refresh(), still ? 600 : 3200);
    } catch (e) {
      setPhase("open");
      setErr((e as Error).message);
      setPlanOpen(true);
      if (!plan) api.plan(d.requirement).then(setPlan).catch(() => undefined);
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
              {made.length > 0 && (
                <ul className="dc__made">
                  {made.map((t) => <li key={t.id}><b className="mono">T-{t.num}</b> {t.title} <span className="mono">→ {t.assignee}</span></li>)}
                </ul>
              )}
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
                <button className="btn btn--sm" disabled={phase !== "open"} onClick={() => act("apply")}
                  title="Write the decision into the ticket and assign follow-ups for the stale PRs and docs (owners only)">
                  {phase === "resolving" ? "Applying…" : `Approve fix as ${actor}`}
                </button>
                <button className="btn btn--ghost btn--sm" disabled={phase !== "open"} onClick={() => act("keep")} title="Record a decision to keep the old scope (owners only)">
                  {phase === "dismissing" ? "Recording…" : "Keep old scope"}
                </button>
              </div>
              <div className="dc__links mono">
                <button onClick={() => void togglePlan()} aria-expanded={planOpen}>Fix plan {planOpen ? "▴" : "▾"}</button>
                <button onClick={() => focusOn(d.feature)}>Graph ↗</button>
                <button onClick={() => void specFor(d.feature)}>Spec ↗</button>
                <button onClick={() => setOpen((o) => !o)} aria-expanded={open}>{open ? "Hide path" : "Graph path"} {open ? "▴" : "▾"}</button>
              </div>
            </footer>
            {err && <p className="dc__err" role="alert">🔒 {err}</p>}
            <AnimatePresence initial={false}>
              {planOpen && plan && (
                <motion.div className="dc__plan" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.3 }}>
                  <span className="mono kicker">Fix plan · from the graph</span>
                  <ol>
                    {plan.items.map((it) => (
                      <li key={it.target}>
                        <span className={`dc__pk mono dc__pk--${it.kind}`}>{it.kind === "pr" ? "PR" : it.kind}</span>
                        <span>{it.what} <em>({it.why})</em></span>
                        {it.kind !== "ticket" && it.assignee && (
                          <button className="dc__who" onClick={() => openPerson(it.assignee!)}><Avatar name={it.assignee} size={22} />{it.assignee}</button>
                        )}
                      </li>
                    ))}
                  </ol>
                  {plan.tell.length > 0 && <p className="mono dc__tell">Also tell: {plan.tell.join(", ")}</p>}
                  <p className="mono dc__tell">
                    Who can approve: {plan.can_apply.join(", ")} · approve as{" "}
                    <select className="composer__sel mono" value={actor} onChange={(e) => setActor(e.target.value)} aria-label="Approve as">
                      {PEOPLE.map((x) => <option key={x}>{x}</option>)}
                    </select>
                  </p>
                </motion.div>
              )}
            </AnimatePresence>
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

/** Follow-ups the fix-it agent opened when an owner approved a plan (pipeline/work.py), kept as Task nodes. */
function FollowUps() {
  const { version, openPerson } = useBrain();
  const [rows, setRows] = useState<Task[]>([]);
  useEffect(() => { api.tasks().then(setRows).catch(() => setRows([])); }, [version]);
  if (!rows.length) return null;
  return (
    <div className="followups">
      <span className="mono kicker">Open follow-ups · assigned by the graph</span>
      {rows.map((t) => (
        <div key={t.id} className="followups__row">
          <b className="mono">T-{t.num}</b>
          <span>{t.title} <em>({t.why})</em></span>
          <button className="dc__who" onClick={() => t.assignee && openPerson(t.assignee)}><Avatar name={t.assignee || "?"} size={22} />{t.assignee}</button>
          <span className="mono followups__by">approved by {t.approved_by}</span>
        </div>
      ))}
    </div>
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
      <FollowUps />
    </Section>
  );
}
