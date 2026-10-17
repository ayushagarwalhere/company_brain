import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { api, type AskResult, type Retro, type SimResult, type TicketRow, type TicketUpdate } from "../lib/api";
import { useBrain } from "../lib/brain";
import { useStill } from "../lib/fx";
import { day, isExternal, PEOPLE, plural } from "../lib/ui";
import { AnswerGraph } from "./AnswerGraph";
import { Avatar } from "./Evidence";
import { CountUp } from "./Motion";
import { PathChips } from "./PathChips";
import { Section } from "./Section";

const QUESTIONS: string[] = [
  "How is Liam connected to PR #6?",
  "Why is the database migration delayed and who can approve an override?",
  "What projects are currently active?",
  "If we delay Project Alpha by two weeks, which teams and client deliverables are impacted?",
  "Did we ship what we decided about SLA notifications?",
  "Who knows the most about ticket export?",
  "Which PR added the export button?",
  "Who owns BD-101, and why is their work stale?",
  "Which features have drifted, and why?",
];
const FIRST = "How is Liam connected to PR #6?";

/** Types text out at a steady pace; instant under reduced motion. */
function Typewriter({ text }: { text: string }) {
  const still = useStill();
  const [n, setN] = useState(still ? text.length : 0);
  useEffect(() => {
    if (still) { setN(text.length); return; }
    setN(0);
    const step = Math.max(2, Math.round(text.length / 90));  // about 1.5 s whatever the length
    const t = setInterval(() => setN((x) => { if (x >= text.length) { clearInterval(t); return x; } return Math.min(text.length, x + step); }), 16);
    return () => clearInterval(t);
  }, [text, still]);
  return <>{text.slice(0, n)}{n < text.length && <span className="caret" aria-hidden>▍</span>}</>;
}

/** "[Slack #engineering] m_exp_05" badges: which connected system each piece of evidence came from. */
export function Sources({ res }: { res: AskResult }) {
  if (!res.sources?.length) return null;
  return (
    <div className="srcs">
      <span className="mono muted">Sources</span>
      {res.sources.map((s) => (
        <span key={s.label} className="src mono" title={s.refs.join(", ")}>
          <b>{s.label}</b>{s.refs.slice(0, 3).join(", ")}{s.refs.length > 3 ? ` +${s.refs.length - 3}` : ""}
        </span>
      ))}
    </div>
  );
}

export function AskSection() {
  const [q, setQ] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<AskResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ask = async (question: string) => {
    setAsked(question); setQ(""); setBusy(true); setErr(null);
    try { setRes(await api.ask(question)); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  // never empty: one example question is answered on load
  useEffect(() => { void ask(FIRST); }, []);
  // the tour asks too: show its question and answer here, so the hops light up in this section's graph
  useEffect(() => {
    const show = (e: Event) => { const d = (e as CustomEvent<{ question: string; result: AskResult }>).detail; setAsked(d.question); setRes(d.result); setErr(null); setBusy(false); };
    addEventListener("ask-show", show);
    return () => removeEventListener("ask-show", show);
  }, []);
  const body = res?.answer.split(/\n\n\**Evidence:?\**/)[0];
  const engine = res ? (res.engine === "rules" ? "rules agent · no LLM" : res.engine || "LLM agent") : "…";
  return (
    <Section id="ask" index="07" title="Ask the graph"
      intro="Type a question on the left. On the right, the graph lights up as the agent hops from person to message to ticket to PR, and every answer says which system its evidence came from.">
      <div className="tries">
        {QUESTIONS.map((full) => <button key={full} disabled={busy} onClick={() => void ask(full)}>{full}</button>)}
      </div>
      <div className="ask">
        <div className="console">
          <div className="console__bar mono">
            <span>Graph agent</span>
            <span>{engine}</span>
            <span>{res ? `${res.tool_calls.length} tool ${plural(res.tool_calls.length, "call", "calls")} · ${res.paths.length} ${plural(res.paths.length, "path", "paths")}` : ""}</span>
          </div>
          <div className="console__body">
            {asked && <motion.div key={asked} className="q" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>{asked}</motion.div>}
            <AnimatePresence mode="wait">
              {busy && <motion.span key="t" className="typing" aria-label="Querying graph tools" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><i /><i /><i /></motion.span>}
              {!busy && err && <motion.p key="e" className="warn">{err}</motion.p>}
              {!busy && res && (
                <motion.div key={res.answer} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} style={{ display: "grid", gap: 16 }}>
                  <div className="a"><Typewriter text={(body || "").replace(/\*\*/g, "")} /></div>
                  <Sources res={res} />
                  {res.tool_calls.length > 0 && (
                    <ol className="steps">
                      {res.tool_calls.map((t, i) => (
                        <li key={i}>
                          <span className="mono">{String(i + 1).padStart(2, "0")}</span>
                          <code>{t.tool}({Object.values(t.args).join(", ")})</code>
                          <span className="mono">{t.rows} {plural(t.rows, "row", "rows")}</span>
                        </li>
                      ))}
                    </ol>
                  )}
                  {res.paths.length > 0 && (
                    <details className="paths">
                      <summary className="mono muted">Graph paths used ({Math.min(res.paths.length, 4)})</summary>
                      {res.paths.slice(0, 4).map((p) => <PathChips key={p} path={p} />)}
                    </details>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          <form className="prompt" onSubmit={(e) => { e.preventDefault(); if (q.trim()) void ask(q.trim()); }}>
            <span className="mono">&gt;</span>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about decisions, tickets, people and PRs…" autoComplete="off" />
            <button className="btn btn--sm" disabled={busy || !q.trim()}>Ask</button>
          </form>
        </div>
        <AnswerGraph paths={busy ? [] : res?.paths || []} busy={busy} />
      </div>
    </Section>
  );
}

export function RetroSection() {
  const { sprints, version, openPerson, focusOn } = useBrain();
  const [sprint, setSprint] = useState<string | null>(null);
  const [r, setR] = useState<Retro | null>(null);
  useEffect(() => { if (!sprint && sprints.length) setSprint(sprints[0].id); }, [sprints, sprint]);
  useEffect(() => { if (sprint) void api.retro(sprint).then(setR); }, [sprint, version]);

  const divergedBy = new Map((r?.diverged || []).map((d) => [`dec:${d.message}`, d]));
  const decidedIds = new Set((r?.decided || []).map((d) => d.decision));
  const carried = (r?.diverged || []).filter((d) => !decidedIds.has(`dec:${d.message}`));
  const shippedCount = (r?.decided || []).filter((d) => d.shipped_in.length).length;
  const state = (d: Retro["decided"][number]) =>
    d.dismissed_by ? { cls: "", label: `Dismissed · ${d.dismissed_by}` }
      : d.shipped_in.length ? { cls: "", label: `Shipped ${d.shipped_in.map((n) => `#${n}`).join(", ")}` }
        : divergedBy.has(d.decision) ? { cls: "tag--inv", label: "Not shipped" }
          : d.superseded_by === "ticket" ? { cls: "", label: "In ticket" } : { cls: "tag--inv", label: "Not shipped" };

  return (
    <Section id="retro-sec" index="09" title="Sprint retro" intro="What we decided, what we shipped, where they diverge. Every line has a source."
      aside={<div className="tabs">{sprints.map((s) => <button key={s.id} className={sprint === s.id ? "active" : ""} onClick={() => setSprint(s.id)}>{s.name}</button>)}</div>}>
      {r && (
        <motion.div key={r.sprint} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
          <div className="nums">
            <div><CountUp value={r.decided.length} /><span className="mono">{plural(r.decided.length, "Decision", "Decisions")} in chat</span></div>
            <div><CountUp value={shippedCount} delay={0.1} /><span className="mono">{plural(shippedCount, "Decision", "Decisions")} shipped</span></div>
            <div className={r.diverged.length ? "hot" : ""}><CountUp value={r.diverged.length} delay={0.2} /><span className="mono">Diverged</span></div>
            <div><CountUp value={r.shipped.length} delay={0.3} /><span className="mono">{plural(r.shipped.length, "PR", "PRs")} merged</span></div>
          </div>

          <span className="kicker" style={{ marginTop: 40 }}>Decisions</span>
          {!r.decided.length && <p className="muted">No decisions recorded in chat this sprint.</p>}
          <ul className="rows">
            {r.decided.map((d) => {
              const st = state(d), dv = divergedBy.get(d.decision);
              return (
                <li key={d.decision}>
                  <div className="rows__top"><b>{d.feature || d.ticket}</b><span className={`tag ${st.cls}`}>{st.label}</span></div>
                  <p title={d.text}>{d.text}</p>
                  {dv && <p className="gap"><span className="mono">{dv.ticket} still says</span> {dv.ticket_text}</p>}
                  <div className="rows__meta">
                    <button className="person" onClick={() => openPerson(d.by)}>{d.by}</button>
                    <span>{day(d.at)}</span><span>{d.platform} #{d.channel}</span><span>{d.ticket}</span>
                    {dv && <button className="link" onClick={() => focusOn(dv.feature)}>Show in graph ↗</button>}
                  </div>
                </li>
              );
            })}
          </ul>

          {carried.length > 0 && <>
            <span className="kicker" style={{ marginTop: 40 }}>Still open from earlier sprints</span>
            <ul className="rows">
              {carried.map((d) => (
                <li key={d.requirement}>
                  <div className="rows__top"><b>{d.feature_name}</b><span className="tag tag--inv">Not shipped</span></div>
                  <p className="gap"><span className="mono">{d.ticket} still says</span> {d.ticket_text}</p>
                </li>
              ))}
            </ul>
          </>}

          <span className="kicker" style={{ marginTop: 40 }}>Shipped · {r.shipped.length} {plural(r.shipped.length, "PR", "PRs")}</span>
          <ul className="prs">
            {r.shipped.map((p) => (
              <li key={p.pr}>
                <span className="mono">{isExternal(p.url) ? <a href={p.url} target="_blank" rel="noopener">#{p.pr}</a> : `#${p.pr}`}</span>
                <span title={p.title}>{p.title}</span>
                <span className="mono">{p.tickets.join(", ") || "no ticket"}</span>
              </li>
            ))}
          </ul>
        </motion.div>
      )}
    </Section>
  );
}

const PIPELINE = [["Ingest", "message → graph"], ["Extract", "is it a change?"], ["Resolve", "feature · ticket"], ["Drift check", "DRIFT query"]] as const;

/** Lights the four stages while the request runs, then settles on the real outcome. */
function PipelineStrip({ busy, res }: { busy: boolean; res: SimResult | null }) {
  const [lit, setLit] = useState(0);
  useEffect(() => {
    if (!busy) return;
    setLit(1);
    const ts = [1, 2, 3].map((k) => setTimeout(() => setLit(k + 1), k * 380));
    return () => ts.forEach(clearTimeout);
  }, [busy]);
  useEffect(() => { if (!busy && res) setLit(4); }, [busy, res]);
  if (!busy && !res) return null;
  const outcome = res && !busy ? (res.status === "drift" ? "drift" : res.status === "ok" ? "no change" : res.status) : null;
  return (
    <div className="pipe mono" aria-live="polite">
      {PIPELINE.map(([name, sub], k) => (
        <div key={name} className={`${k < lit ? "on" : ""} ${k === 3 && outcome === "drift" ? "hot" : ""}`}>
          <b>{name}</b><small>{k === 3 && outcome ? outcome : sub}</small>
        </div>
      ))}
    </div>
  );
}

/** Slack-style bold (*x*) and line breaks in the bot's alert text. */
function AlertText({ text }: { text: string }) {
  const lines = text.replace(/:warning:\s*/g, "").replace(/`/g, "").split("\n").filter((l) => l.trim());
  return <>{lines.map((l, i) => (
    <p key={i} className={l.startsWith(">") ? "quote" : ""}>
      {l.replace(/^>\s?/, "").split(/(\*[^*]+\*)/).map((part, k) => part.startsWith("*") && part.endsWith("*") ? <b key={k}>{part.slice(1, -1)}</b> : <span key={k}>{part}</span>)}
    </p>
  ))}</>;
}

export function SimulateSection() {
  const { actor, setActor, refresh, announce } = useBrain();
  const [platform, setPlatform] = useState("slack");
  const [channel, setChannel] = useState("engineering");
  const [text, setText] = useState("Decision: the export button must also offer a JSON download, BD-102.");
  const [busy, setBusy] = useState(false);
  const [posted, setPosted] = useState<{ text: string; author: string; at: string } | null>(null);
  const [res, setRes] = useState<SimResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<"chat" | "ticket">("chat");
  const post = async () => {
    if (!text.trim()) return;
    setBusy(true); setErr(null); setRes(null);
    setPosted({ text, author: actor, at: new Date().toTimeString().slice(0, 5) });
    try {
      const [r] = await Promise.all([api.simulate({ text, author: actor, platform, channel }), new Promise((ok) => setTimeout(ok, 1300))]);
      setRes(r);
      if (r.status === "drift") {
        await refresh();
        announce({ ticket: r.ticket ?? null, requirement: r.message ? `req:${r.message}` : null });  // -> toast, badge, scroll, flash
      }
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const outcome = (r: SimResult) => ({
    drift: null, ok: `Not a requirement change (classified “${r.classification?.kind ?? "other"}”). Nothing to flag.`,
    "no-decision-rights": `${posted?.author} doesn't own ${r.ticket}, so this isn't counted as a decision. Only the ticket's creator or assignee can change it from chat.`,
    "change-reflected": `${r.ticket} already says this. No drift.`, cooldown: `Already alerted on ${r.ticket} in the last 5 minutes.`,
    "already-alerted": "Already alerted on this requirement.", "low-confidence": "Looks like a change, but below the confidence bar. Not flagged.",
    "no-features": "No features in the graph yet.",
    "project-status": r.change?.status === "changed" ? `${r.change.name} is now ${r.change.to}. The graph changed; ask “What projects are currently active?” to see it.`
      : r.change?.status === "no-rights" ? `${posted?.author} can't change ${r.change.name}: only its owner, a lead or the owner's manager can.` : `${r.change?.name} is already ${r.change?.to}.`,
  } as Record<string, string | null>)[r.status] ?? `Status: ${r.status}`;
  return (
    <Section id="simulate" index="05" title="Live monitor"
      intro="Post as anyone on the team. The monitor runs the same pipeline the Slack and Discord bots do, and replies in the thread when a decision never reached the ticket."
      aside={<div className="tabs">{(["chat", "ticket"] as const).map((m) => <button key={m} className={mode === m ? "active" : ""} onClick={() => setMode(m)}>{m === "chat" ? "Chat message" : "Ticket edit"}</button>)}</div>}>
      {mode === "ticket" ? <TicketEditor /> : (
        <div className="chat">
          <div className="chat__head">
            <span className="chat__chan">#<input value={channel} onChange={(e) => setChannel(e.target.value)} aria-label="Channel" /></span>
            <div className="tabs">{["slack", "discord"].map((p) => <button key={p} className={platform === p ? "active" : ""} onClick={() => setPlatform(p)}>{p}</button>)}</div>
          </div>
          <div className="chat__thread">
            {!posted && <p className="chat__empty">Pick who is speaking, write a message and send it. Try it as <b>maya</b>, then as <b>zara</b>, who doesn't own BD-102.</p>}
            {posted && (
              <motion.div className="msg" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
                <Avatar name={posted.author} size={36} />
                <div><div className="msg__who"><b>{posted.author}</b><span className="mono">{posted.at}</span></div><p>{posted.text}</p></div>
              </motion.div>
            )}
            {posted && <PipelineStrip busy={busy} res={res} />}
            {err && <p className="warn">{err}</p>}
            <AnimatePresence>
              {res && !busy && (
                <motion.div className="msg msg--bot" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
                  <span className="bot" aria-hidden>DM</span>
                  <div>
                    <div className="msg__who"><b>Drift Monitor</b><span className="app mono">app</span><span className="mono">{posted?.at}</span></div>
                    {res.status === "drift" && res.alert ? <div className="msg__alert"><AlertText text={res.alert} /></div> : <p>{outcome(res)}</p>}
                    <div className="msg__meta mono">
                      {res.feature ? <span>feature <b>{res.feature}</b> · via {res.via}</span> : <span>no feature matched</span>}
                      {res.ticket && <span>ticket <b>{res.ticket}</b></span>}
                      <span>classified <b>{res.classification?.kind}</b></span>
                    </div>
                    {res.path && res.status !== "drift" && <div style={{ marginTop: 10 }}><PathChips path={res.path} /></div>}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          <form className="composer" onSubmit={(e) => { e.preventDefault(); void post(); }}>
            <label title="Post as">
              <Avatar name={actor} size={30} />
              <select className="sel" value={actor} onChange={(e) => setActor(e.target.value)} aria-label="Author">{PEOPLE.map((p) => <option key={p}>{p}</option>)}</select>
            </label>
            <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} aria-label="Message"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void post(); } }} />
            <button className="btn btn--sm" disabled={busy || !text.trim()}>{busy ? "Running…" : "Send ↵"}</button>
          </form>
        </div>
      )}
    </Section>
  );
}

/** Ticket edit = the ticket-tracker webhook (POST /api/ingest/ticket). */
function TicketEditor() {
  const { actor, drift } = useBrain();
  const [tickets, setTickets] = useState<TicketRow[]>([]);
  const [id, setId] = useState("BD-101");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<TicketUpdate | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { void api.tickets().then(setTickets); }, []);
  useEffect(() => { const t = tickets.find((x) => x.id === id); if (t) setText(t.description); setRes(null); }, [id, tickets]);
  const drifted = new Set(drift.map((d) => d.ticket));
  const save = async () => {
    setBusy(true); setErr(null);
    try { setRes(await api.updateTicket(id, text, actor)); void api.tickets().then(setTickets); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <form className="form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
      <div className="form__row">
        <label className="mono">Ticket<select className="field" value={id} onChange={(e) => setId(e.target.value)}>
          {tickets.map((t) => <option key={t.id} value={t.id}>{t.id} · {t.title}{drifted.has(t.id) ? "  · drift" : ""}</option>)}</select></label>
        <label className="mono">Editor<input className="field" value={actor} readOnly /></label>
        <label className="mono">Source<input className="field" value="tracker webhook" readOnly /></label>
      </div>
      <textarea className="field" rows={4} value={text} onChange={(e) => setText(e.target.value)} aria-label="Ticket description" />
      <p className="muted" style={{ fontSize: 14 }}>
        Try a cosmetic edit first (it must <b>not</b> clear the drift), then write the decided requirement in. The “reflects” check decides which edits count.
      </p>
      <div><button className="btn" disabled={busy}>{busy ? "Updating graph…" : "Save ticket"}</button></div>
      {err && <p className="warn">{err}</p>}
      {res && (
        <motion.div className="result" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <span className={`tag ${res.resolved?.length ? "tag--inv" : res.still_drifting?.length ? "tag--dash" : ""}`}>{res.status}</span>
          {res.version && <span>new version <b>{res.version}</b></span>}
          {!!res.resolved?.length && <span className="ok">resolves {res.resolved.join(", ")}</span>}
          {!!res.still_drifting?.length && <span className="warn">still drifting: {res.still_drifting.join(", ")}</span>}
          {!res.resolved?.length && !res.still_drifting?.length && res.status === "updated" && <span>no drift on this ticket</span>}
        </motion.div>
      )}
    </form>
  );
}

function CovCard({ title, sub, items }: { title: string; sub: string; items: React.ReactNode[] }) {
  return (
    <div>
      <span className="mono muted">{title}</span>
      <CountUp value={items.length} className="cov__n" />
      <small>{sub}</small>
      <ul>{items.slice(0, 4).map((x, i) => <li key={i}>{x}</li>)}</ul>
      {items.length > 4 && <span className="mono muted">+{items.length - 4} more</span>}
    </div>
  );
}

export function CoverageSection() {
  const { coverage: c, openPerson } = useBrain();
  return (
    <Section id="coverage" index="10" title="Coverage & risk" intro="Where the company brain has holes: work nobody linked, tickets nobody discussed, knowledge held by one person.">
      {c && <>
        <div className="cov">
          <CovCard title="PRs with no ticket" sub="shipped work nobody can trace"
            items={c.orphan_prs.map((x) => <><span className="mono">#{x.pr}</span> {x.title} <span className="muted">· {x.author}</span></>)} />
          <CovCard title="Done, no PR" sub="closed tickets with no linked code"
            items={c.done_without_pr.map((x) => <><span className="mono">{x.ticket}</span> {x.title}</>)} />
          <CovCard title="Never discussed" sub="tickets no message mentions"
            items={c.undiscussed_tickets.map((x) => <><span className="mono">{x.ticket}</span> {x.title} <span className="muted">· {x.state}</span></>)} />
          {(c.unverified_changes || []).length > 0 && (
            <CovCard title="Possible decisions by non-owners" sub="read like a decision, but the author doesn't own the ticket"
              items={(c.unverified_changes || []).map((x) => <><span className="mono">{x.ticket}?</span> “{x.text}” <span className="muted">· {x.author}</span></>)} />
          )}
        </div>
        <span className="kicker" style={{ marginTop: 48 }}>Knowledge concentration · share of a feature's involvement held by one person</span>
        <div className="risk">
          {c.knowledge_risk.map((r) => {
            const pct = Math.round(r.top_share * 100), hot = r.top_share >= 0.5;
            const person = r.top_person.split(" ")[0].toLowerCase();
            return (
              <div key={r.feature} className={`risk__row ${hot ? "risk__row--hot" : ""}`}>
                <button className="risk__who" onClick={() => openPerson(person)} title={`Open ${r.top_person}`}>
                  <Avatar name={person} size={34} />
                  <span><b>{r.name}</b><small>{r.top_person} · {r.people} people involved</small></span>
                </button>
                <div className="bar" aria-label={`${pct}% held by ${r.top_person}`}>
                  <motion.span style={{ transformOrigin: "left", width: "100%" }} initial={{ scaleX: 0 }} whileInView={{ scaleX: r.top_share }} viewport={{ once: true }} transition={{ duration: 1.1, ease: [0.2, 0.7, 0.1, 1] }} />
                  <i style={{ left: "50%" }} title="bus-factor line" />
                </div>
                <span className="mono risk__pct">{pct}%{hot ? " · bus factor 1" : ""}</span>
              </div>
            );
          })}
        </div>
      </>}
    </Section>
  );
}

export function SpecSection() {
  const { spec } = useBrain();
  if (!spec) return null;
  return (
    <Section id="spec-sec" index="11" title="Agent-ready spec" intro={`Generated by ${spec.engine} from graph context only. Not executed.`}>
      <pre className="specdoc">{spec.markdown}</pre>
    </Section>
  );
}
