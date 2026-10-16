import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { api, type AskResult, type Retro, type SimResult, type TicketRow, type TicketUpdate } from "../lib/api";
import { useBrain } from "../lib/brain";
import { useStill, useTilt } from "../lib/fx";
import { day, isExternal, PEOPLE } from "../lib/ui";
import { CountUp } from "./Motion";
import { Avatar } from "./Evidence";
import { PathChips } from "./PathChips";
import { Section } from "./Section";

const QUESTIONS: string[] = [
  "Did we ship what we decided about SLA notifications?",
  "Who knows the most about ticket export?",
  "How is Liam connected to PR #6?",
  "Which PR added the export button?",
  "Who owns BD-101, and why is their work stale?",
  "Which features have drifted, and why?",
];
const FIRST = "What does BD-103 say, and is it still accurate?";

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
  const body = res?.answer.split("\n\nEvidence:")[0];
  const engine = res ? (res.engine === "rules" ? "rules agent · no LLM" : res.engine || "LLM agent") : "…";
  return (
    <Section id="ask" index="006" kicker="Ask the graph" title="Ask the graph" intro="The agent picks graph tools and answers from their rows. Every answer shows the steps it took and the graph paths behind it."
      aside={<div className="tries">
        <span className="mono kicker">Try</span>
        {QUESTIONS.map((full) => <button key={full} className="try" disabled={busy} onClick={() => void ask(full)}>{full}<span aria-hidden>→</span></button>)}
      </div>}>
      <div className="console brackets">
        <div className="console__bar mono">
          <span className="console__dots" aria-hidden><i /><i /><i /></span>
          <span>graph agent</span>
          <span className={`console__mode ${res?.engine === "rules" ? "" : "on"}`}>{engine}</span>
          <span className="console__meta">{res ? `${res.tool_calls.length} tool call${res.tool_calls.length === 1 ? "" : "s"} · ${res.paths.length} path${res.paths.length === 1 ? "" : "s"}` : ""}</span>
        </div>
        <div className="console__body">
          {asked && (
            <motion.div key={asked} className="bubble bubble--q" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
              <span>{asked}</span><Avatar name="you" size={28} />
            </motion.div>
          )}
          <AnimatePresence mode="wait">
            {busy && <motion.div key="t" className="bubble bubble--a" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <span className="bubble__bot" aria-hidden>◎</span><span className="typing" aria-label="Querying graph tools"><i /><i /><i /></span></motion.div>}
            {!busy && err && <motion.p key="e" className="warn">{err}</motion.p>}
            {!busy && res && (
              <motion.div key={res.answer} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
                <div className="bubble bubble--a">
                  <span className="bubble__bot" aria-hidden>◎</span>
                  <div className="answer"><Typewriter text={body || ""} /></div>
                </div>
                {res.tool_calls.length > 0 && (
                  <ol className="steps2">
                    {res.tool_calls.map((t, i) => (
                      <motion.li key={i} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.3 + i * 0.12 }}>
                        <span className="mono steps2__n">{String(i + 1).padStart(2, "0")}</span>
                        <code>{t.tool}({Object.values(t.args).join(", ")})</code>
                        <span className="mono steps2__rows">{t.rows} row{t.rows === 1 ? "" : "s"}</span>
                      </motion.li>
                    ))}
                  </ol>
                )}
                {res.paths.length > 0 && <div className="console__paths"><div className="mono kicker">Graph paths used</div>{res.paths.slice(0, 4).map((p) => <PathChips key={p} path={p} />)}</div>}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        <form className="prompt console__prompt" onSubmit={(e) => { e.preventDefault(); if (q.trim()) void ask(q.trim()); }}>
          <span className="mono prompt__sign">&gt;</span>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask anything about decisions, tickets and PRs…" autoComplete="off" />
          <button className="btn btn--sm" disabled={busy || !q.trim()}>Ask</button>
        </form>
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
      : d.shipped_in.length ? { cls: "ok", label: `Shipped ${d.shipped_in.map((n) => `#${n}`).join(", ")}` }
        : divergedBy.has(d.decision) ? { cls: "warn", label: "Not shipped" }
          : d.superseded_by === "ticket" ? { cls: "", label: "In ticket" } : { cls: "warn", label: "Not shipped" };

  return (
    <Section id="retro-sec" index="007" kicker="Sprint retro" title="Sprint retro" intro="What we decided, what we shipped, where they diverge. Every line has a source."
      aside={<div className="tabs">{sprints.map((s) => <button key={s.id} className={sprint === s.id ? "active" : ""} onClick={() => setSprint(s.id)}>{s.name}</button>)}</div>}>
      {r && (
        <motion.div key={r.sprint} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
          <div className="rt-sum">
            <div><CountUp value={r.decided.length} /><span className="mono">Decided in chat</span></div>
            <div><CountUp value={shippedCount} delay={0.1} /><span className="mono">Decisions shipped</span></div>
            <div className={r.diverged.length ? "warn rt-pulse" : ""}><CountUp value={r.diverged.length} delay={0.2} /><span className="mono">Diverged</span></div>
            <div><CountUp value={r.shipped.length} delay={0.3} /><span className="mono">PRs merged</span></div>
          </div>

          <h3 className="rt-h mono">Decisions</h3>
          {!r.decided.length && <p className="muted">No decisions recorded in chat this sprint.</p>}
          <ul className="rt-list">
            {r.decided.map((d) => {
              const st = state(d), dv = divergedBy.get(d.decision);
              return (
                <li key={d.decision} className={`rt-row ${st.cls === "warn" ? "rt-row--warn" : ""}`}>
                  <div className="rt-title"><b>{d.feature || d.ticket}</b><span className={`rt-pill ${st.cls}`}>{st.label}</span></div>
                  <p className="rt-text" title={d.text}>{d.text}</p>
                  {dv && <p className="rt-gap"><span className="mono">{dv.ticket} still says</span> {dv.ticket_text}</p>}
                  <div className="rt-meta">
                    <button className="person-link" onClick={() => openPerson(d.by)}>{d.by}</button>
                    <span>{day(d.at)}</span><span>{d.platform} #{d.channel}</span><span>{d.ticket}</span>
                    {dv && <button className="rt-link" onClick={() => focusOn(dv.feature)}>Show in graph ↗</button>}
                  </div>
                </li>
              );
            })}
          </ul>

          {carried.length > 0 && <>
            <h3 className="rt-h mono">Still open from earlier sprints</h3>
            <ul className="rt-list">
              {carried.map((d) => (
                <li key={d.requirement} className="rt-row rt-row--warn rt-row--slim">
                  <div className="rt-title"><b>{d.feature_name}</b><span className="rt-pill warn">Not shipped</span></div>
                  <p className="rt-gap"><span className="mono">{d.ticket} still says</span> {d.ticket_text}</p>
                </li>
              ))}
            </ul>
          </>}

          <h3 className="rt-h mono">Shipped · {r.shipped.length} PRs</h3>
          <ul className="rt-prs">
            {r.shipped.map((p) => (
              <li key={p.pr}>
                <span className="mono rt-num">{isExternal(p.url) ? <a href={p.url} target="_blank" rel="noopener">#{p.pr}</a> : `#${p.pr}`}</span>
                <span className="rt-pr-title" title={p.title}>{p.title}</span>
                <span className="mono rt-tk">{p.tickets.join(", ") || "no ticket"}</span>
              </li>
            ))}
          </ul>
        </motion.div>
      )}
    </Section>
  );
}

const PIPELINE = [["Ingest", "message -> graph"], ["Extract", "is it a change?"], ["Resolve", "feature · ticket"], ["Drift check", "DRIFT query"]] as const;

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
        <div key={name} className={`pipe__step ${k < lit ? "on" : ""} ${k === 3 && outcome === "drift" ? "hot" : ""}`}>
          <i /><b>{name}</b><small>{k === 3 && outcome ? outcome : sub}</small>
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
  const [mode, setMode] = useState<"chat" | "ticket">("chat");
  const outcome = (r: SimResult) => ({
    drift: null, ok: `Not a requirement change (classified “${r.classification?.kind ?? "other"}”). Nothing to flag.`,
    "no-decision-rights": `${posted?.author} doesn't own ${r.ticket}, so this isn't counted as a decision. Only the ticket's creator or assignee can change it from chat.`,
    "change-reflected": `${r.ticket} already says this. No drift.`, cooldown: `Already alerted on ${r.ticket} in the last 5 minutes.`,
    "already-alerted": "Already alerted on this requirement.", "low-confidence": "Looks like a change, but below the confidence bar. Not flagged.",
    "no-features": "No features in the graph yet.",
  } as Record<string, string | null>)[r.status] ?? `Status: ${r.status}`;
  return (
    <Section id="simulate" index="008" kicker="Live monitor" title="Simulate the team"
      intro="Post as anyone on the team. The live monitor runs the same pipeline a Slack or Discord bot does, and replies in the thread when a decision never reached the ticket."
      aside={<div className="tabs">{(["chat", "ticket"] as const).map((m) => <button key={m} className={mode === m ? "active" : ""} onClick={() => setMode(m)}>{m === "chat" ? "Chat message" : "Ticket edit"}</button>)}</div>}>
      {mode === "ticket" ? <TicketEditor /> : (
        <div className="chat brackets">
          <div className="chat__head">
            <span className="chat__chan"><b>#</b>
              <input className="chat__chaninput" value={channel} onChange={(e) => setChannel(e.target.value)} aria-label="Channel" />
            </span>
            <div className="chat__plat mono" role="tablist">
              {["slack", "discord"].map((p) => <button key={p} className={platform === p ? "on" : ""} onClick={() => setPlatform(p)}>{p}</button>)}
            </div>
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
                <motion.div className={`msg msg--bot ${res.status === "drift" ? "msg--hot" : ""}`} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
                  <span className="bubble__bot" aria-hidden>◎</span>
                  <div>
                    <div className="msg__who"><b>Drift Monitor</b><span className="app mono">app</span><span className="mono">{posted?.at}</span></div>
                    {res.status === "drift" && res.alert ? <div className="msg__alert"><AlertText text={res.alert} /></div> : <p className="muted">{outcome(res)}</p>}
                    <div className="msg__meta mono">
                      {res.feature ? <span>feature <b>{res.feature}</b> · via {res.via}</span> : <span>no feature matched</span>}
                      {res.ticket && <span>ticket <b>{res.ticket}</b></span>}
                      <span>classified <b>{res.classification?.kind}</b></span>
                    </div>
                    {res.path && res.status !== "drift" && <PathChips path={res.path} />}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          <form className="composer" onSubmit={(e) => { e.preventDefault(); void post(); }}>
            <label className="composer__who" title="Post as">
              <Avatar name={actor} size={30} />
              <select className="composer__sel mono" value={actor} onChange={(e) => setActor(e.target.value)} aria-label="Author">{PEOPLE.map((p) => <option key={p}>{p}</option>)}</select>
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
    <form className="sim" onSubmit={(e) => { e.preventDefault(); void save(); }}>
      <div className="sim__row">
        <label className="mono">Ticket<select className="field" value={id} onChange={(e) => setId(e.target.value)}>
          {tickets.map((t) => <option key={t.id} value={t.id}>{t.id} · {t.title}{drifted.has(t.id) ? "  · drift" : ""}</option>)}</select></label>
        <label className="mono">Editor<input className="field" value={actor} readOnly /></label>
        <label className="mono">Source<input className="field" value="tracker webhook" readOnly /></label>
      </div>
      <textarea className="field" rows={4} value={text} onChange={(e) => setText(e.target.value)} />
      <p className="muted" style={{ fontSize: 13.5, margin: "0 0 14px" }}>
        Try a cosmetic edit first (it must <b>not</b> clear the drift), then write the decided requirement in. The “reflects” check decides which edits count.
      </p>
      <button className="btn" disabled={busy}>{busy ? "Updating graph…" : "Save ticket"}</button>
      {err && <p className="warn">{err}</p>}
      {res && (
        <motion.div className="result-line" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <span className={`badge ${res.resolved?.length ? "badge--ok" : res.still_drifting?.length ? "badge--warn" : ""}`}>{res.status}</span>
          {res.version && <span>new version <b>{res.version}</b></span>}
          {!!res.resolved?.length && <span className="ok">resolves {res.resolved.join(", ")}</span>}
          {!!res.still_drifting?.length && <span className="warn">still drifting: {res.still_drifting.join(", ")}</span>}
          {!res.resolved?.length && !res.still_drifting?.length && res.status === "updated" && <span>no drift on this ticket</span>}
        </motion.div>
      )}
    </form>
  );
}

const COV_ICON = {
  orphan: <svg viewBox="0 0 24 24" aria-hidden><path d="M12 3 L21 12 L12 21 L3 12 Z" /><path d="M16 8 L8 16" /></svg>,
  done: <svg viewBox="0 0 24 24" aria-hidden><rect x="5" y="5" width="14" height="14" /><path d="M8.5 12.5 L11 15 L15.5 9.5" /></svg>,
  silent: <svg viewBox="0 0 24 24" aria-hidden><path d="M4 6 h16 v10 h-9 l-4 3 v-3 h-3 z" /><path d="M8 11 h8" /></svg>,
  unverified: <svg viewBox="0 0 24 24" aria-hidden><circle cx="12" cy="12" r="8" /><path d="M10 9.5 a2 2 0 1 1 2.5 2 v1.5" /><path d="M12 16 v.5" /></svg>,
};

function CovCard({ tone, icon, title, sub, items }: { tone: string; icon: React.ReactNode; title: string; sub: string; items: React.ReactNode[] }) {
  const tilt = useTilt<HTMLDivElement>(4);
  return (
    <div ref={tilt} className={`cov2 cov2--${tone} brackets`}>
      <div className="cov2__glow" aria-hidden />
      <div className="cov2__top"><span className="cov2__icon">{icon}</span><span className="mono">{title}</span></div>
      <CountUp value={items.length} className="cov2__n" />
      <small>{sub}</small>
      <ul>{items.slice(0, 4).map((x, i) => <li key={i}>{x}</li>)}</ul>
      {items.length > 4 && <span className="mono cov2__more">+{items.length - 4} more</span>}
    </div>
  );
}

export function CoverageSection() {
  const { coverage: c, openPerson } = useBrain();
  return (
    <Section id="coverage" index="009" kicker="Coverage & risk" title="Coverage & risk" intro="Where the company brain has holes: work nobody linked, tickets nobody discussed, knowledge held by one person.">
      {c && <>
        <div className="cov">
          <CovCard tone="pr" icon={COV_ICON.orphan} title="PRs with no ticket" sub="shipped work nobody can trace"
            items={c.orphan_prs.map((x) => <><span className="mono">#{x.pr}</span> {x.title} <span className="muted">· {x.author}</span></>)} />
          <CovCard tone="ticket" icon={COV_ICON.done} title="Done, no PR" sub="closed tickets with no linked code"
            items={c.done_without_pr.map((x) => <><span className="mono">{x.ticket}</span> {x.title}</>)} />
          <CovCard tone="msg" icon={COV_ICON.silent} title="Never discussed" sub="tickets no message mentions"
            items={c.undiscussed_tickets.map((x) => <><span className="mono">{x.ticket}</span> {x.title} <span className="muted">· {x.state}</span></>)} />
          <CovCard tone="req" icon={COV_ICON.unverified} title="Unverified changes" sub="decisions by non-owners on a guessed ticket"
            items={(c.unverified_changes || []).map((x) => <><span className="mono">{x.ticket}?</span> “{x.text}” <span className="muted">· {x.author}</span></>)} />
        </div>
        <div className="mono kicker risk__h">Knowledge concentration · share of a feature's involvement held by one person</div>
        {c.knowledge_risk.map((r) => {
          const pct = Math.round(r.top_share * 100), hot = r.top_share >= 0.5;
          const person = r.top_person.split(" ")[0].toLowerCase();
          return (
            <div key={r.feature} className={`risk2 ${hot ? "risk2--hot" : ""}`}>
              <button className="risk2__who" onClick={() => openPerson(person)} title={`Open ${r.top_person}`}>
                <Avatar name={person} size={34} />
                <span><b>{r.name}</b><small>{r.top_person} · {r.people} people involved</small></span>
              </button>
              <div className="risk2__bar" aria-label={`${pct}% held by ${r.top_person}`}>
                <motion.span initial={{ scaleX: 0 }} whileInView={{ scaleX: r.top_share }} viewport={{ once: true }} transition={{ duration: 1.2, ease: [0.2, 0.7, 0.1, 1] }} />
                <i style={{ left: "50%" }} title="bus-factor line" />
              </div>
              <span className="mono risk2__pct">{hot && <i className="risk__dot" aria-hidden />}{pct}%{hot ? " · bus factor 1" : ""}</span>
            </div>
          );
        })}
      </>}
    </Section>
  );
}

export function SpecSection() {
  const { spec } = useBrain();
  if (!spec) return null;
  return (
    <Section id="spec-sec" index="010" kicker="Agent-ready spec" title="Agent-ready spec" intro={`Generated by ${spec.engine} from graph context only. Not executed.`}>
      <pre className="specdoc">{spec.markdown}</pre>
    </Section>
  );
}
