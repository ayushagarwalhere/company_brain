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

/** Days since the decision, counted from the scenario's reference date when the graph was built from the scenario
    (so demo numbers don't change as real time passes), otherwise from now. */
const daysOpen = (iso: string, reference?: string | null) =>
  Math.max(0, Math.floor(((reference ? new Date(reference).getTime() : Date.now()) - new Date(iso).getTime()) / 86400000));

export const cardId = (requirement: string) => `drift-card-${requirement.replace(/[^a-zA-Z0-9_-]/g, "_")}`;

type Phase = "open" | "resolving" | "resolved" | "dismissing" | "dismissed";

const expand = { initial: { height: 0, opacity: 0 }, animate: { height: "auto", opacity: 1 }, exit: { height: 0, opacity: 0 }, transition: { duration: 0.3 } };

function DriftCard({ d, i, flash }: { d: Drift; i: number; flash: boolean }) {
  const { refresh, openPerson, focusOn, specFor, actor, setActor, stats } = useBrain();
  const still = useStill();
  const [phase, setPhase] = useState<Phase>("open");
  const [note, setNote] = useState<string | null>(null);
  const [pathOpen, setPathOpen] = useState(false);
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
    setPhase(kind === "keep" ? "dismissing" : "resolving");
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

  return (
    <motion.article layout ref={ref} id={cardId(d.requirement)} className={`drift ${flash ? "drift--flash" : ""}`}
      initial={still ? false : { opacity: 0, y: 16 }} animate={{ opacity: phase === "dismissed" ? 0.55 : 1, y: 0 }}
      exit={{ opacity: 0, height: 0, marginBottom: 0, transition: { duration: 0.45, ease: EASE } }}
      transition={{ duration: 0.6, delay: still ? 0 : i * 0.08, ease: EASE }}>
      <AnimatePresence initial={false} mode="wait">
        {done ? (
          <motion.div key="done" className="done" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
            <span className={`done__mark ${phase === "resolved" ? "done__mark--ok" : ""}`} aria-hidden>{phase === "resolved" ? "✓" : "–"}</span>
            <div>
              <b>{d.feature_name} · {d.ticket}</b>
              <p className="mono">{phase === "resolved" ? "Resolved" : "Dismissed"} · {note}</p>
              {made.length > 0 && (
                <ul>{made.map((t) => <li key={t.id}><b className="mono">T-{t.num}</b> {t.title} <span className="mono muted">→ {t.assignee}</span></li>)}</ul>
              )}
            </div>
          </motion.div>
        ) : (
          <motion.div key="full" exit={{ opacity: 0, height: 0, transition: { duration: 0.45, ease: EASE } }} style={{ overflow: "hidden" }}>
            <header className="drift__head">
              <div>
                <span className="tag tag--inv">Drift {String(i + 1).padStart(2, "0")} · {d.ticket}</span>
                {typeof confidence === "number" && <span className="tag" style={{ marginLeft: 6 }} title="Extractor confidence">conf {confidence.toFixed(2)}</span>}
                <h3>{d.feature_name}</h3>
              </div>
              <p className="mono drift__stats">
                <span><b>{openDays}</b> {plural(openDays, "day", "days")} open</span>
                <span><b>{d.stale_prs.length}</b> stale {plural(d.stale_prs.length, "PR", "PRs")}</span>
                <span><b>{d.stale_docs.length}</b> stale {plural(d.stale_docs.length, "doc", "docs")}</span>
              </p>
            </header>

            <div className="vs">
              <div className="vs__old">
                <span className="mono vs__k">{d.ticket} still says</span>
                <p>{d.ticket_text}</p>
              </div>
              <div className="vs__new">
                <span className="mono vs__k">Decided in chat</span>
                <p title={quote ? `Source message: "${quote}"` : undefined}>{d.requirement_text}</p>
                <div className="vs__who mono">
                  <Avatar name={d.changed_by} size={24} />
                  <button className="person" onClick={() => openPerson(d.changed_by)}>{d.changed_by}</button>
                  <span>{day(d.changed_at)} · {d.source} #{d.channel}</span>
                  {d.message_url && isExternal(d.message_url) && <a className="link" href={d.message_url} target="_blank" rel="noopener">open ↗</a>}
                </div>
              </div>
            </div>

            <EvidenceChain run={seen && !still}
              nodes={[{ kind: "msg", title: "MESSAGE" }, { kind: "req", title: "REQUIREMENT" }, { kind: "ticket", title: d.ticket }]}
              stale={[...d.stale_prs.map((p) => ({ kind: "pr" as const, label: `PR #${p.pr}${p.status === "old_after" ? " · after decision" : ""}` })),
                      ...(d.unmatched_prs || []).map((p) => ({ kind: "pr" as const, unmatched: true, label: `PR #${p.pr} · may implement new` })),
                      ...d.stale_docs.map((x) => ({ kind: "doc" as const, label: x.id }))]} />

            <footer className="drift__foot">
              <div className="drift__actions">
                <button className="btn btn--sm" disabled={phase !== "open"} onClick={() => act("apply")}
                  title="Write the decision into the ticket and assign follow-ups for the stale PRs and docs (owners only)">
                  {phase === "resolving" ? "Applying…" : `Approve fix as ${actor}`}
                </button>
                <button className="btn btn--ghost btn--sm" disabled={phase !== "open"} onClick={() => act("keep")} title="Record a decision to keep the old scope (owners only)">
                  {phase === "dismissing" ? "Recording…" : "Keep old scope"}
                </button>
              </div>
              <div className="drift__links">
                <button className="link" onClick={() => void togglePlan()} aria-expanded={planOpen}>Fix plan {planOpen ? "−" : "+"}</button>
                <button className="link" onClick={() => setPathOpen((o) => !o)} aria-expanded={pathOpen}>Graph path {pathOpen ? "−" : "+"}</button>
                <button className="link" onClick={() => focusOn(d.feature)}>Graph ↗</button>
                <button className="link" onClick={() => void specFor(d.feature)}>Spec ↗</button>
              </div>
            </footer>
            {err && <p className="drift__err" role="alert">{err}</p>}
            <AnimatePresence initial={false}>
              {planOpen && plan && (
                <motion.div className="drift__more" {...expand}>
                  <span className="kicker" style={{ marginTop: 4 }}>Fix plan · read from the graph</span>
                  <ol className="plan">
                    {plan.items.map((it) => (
                      <li key={it.target}>
                        <span className={`pk pk--${it.kind}`}>{it.kind === "pr" ? "PR" : it.kind}</span>
                        <span>{it.what} <em>({it.why})</em></span>
                        {it.kind !== "ticket" && it.assignee
                          ? <button className="who" onClick={() => openPerson(it.assignee!)}><Avatar name={it.assignee} size={22} />{it.assignee}</button>
                          : <span />}
                      </li>
                    ))}
                  </ol>
                  {plan.tell.length > 0 && <p className="mono plan__note">Also tell: {plan.tell.join(", ")}</p>}
                  <p className="mono plan__note">
                    Who can approve: {plan.can_apply.join(", ")} · approve as
                    <select className="sel" value={actor} onChange={(e) => setActor(e.target.value)} aria-label="Approve as">
                      {PEOPLE.map((x) => <option key={x}>{x}</option>)}
                    </select>
                  </p>
                </motion.div>
              )}
            </AnimatePresence>
            <AnimatePresence initial={false}>
              {pathOpen && <motion.div className="drift__more" {...expand}><PathChips path={d.path} /></motion.div>}
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
      <span className="kicker">Open follow-ups · assigned by the graph</span>
      {rows.map((t) => (
        <div key={t.id} className="followups__row">
          <b className="mono">T-{t.num}</b>
          <span>{t.title} <em>({t.why})</em></span>
          <button className="who" onClick={() => t.assignee && openPerson(t.assignee)}><Avatar name={t.assignee || "?"} size={22} />{t.assignee}</button>
          <span className="mono muted">approved by {t.approved_by}</span>
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
    <Section id="drift" index="01" title="Open drift"
      intro="A chat message changed a requirement. Nothing newer replaced it, no PR implements it, and nobody chose to keep the old scope."
      aside={<span className={`tag ${drift.length ? "tag--inv" : ""}`}>{drift.length} open</span>}>
      {version > 0 && drift.length === 0 && <p className="empty">No open drift. Tickets, docs and PRs match the latest decisions.</p>}
      <AnimatePresence mode="popLayout">
        {drift.map((d, i) => <DriftCard key={d.requirement} d={d} i={i} flash={flash === d.requirement} />)}
      </AnimatePresence>
      <FollowUps />
    </Section>
  );
}
