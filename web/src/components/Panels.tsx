import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { api, type AskResult, type Retro, type SimResult } from "../lib/api";
import { useBrain } from "../lib/brain";
import { day, isExternal, PEOPLE } from "../lib/ui";
import { PathChips } from "./PathChips";
import { Section } from "./Section";

const QUESTIONS: [string, string][] = [
  ["SLA decision shipped?", "What did we decide about the SLA notifications and did we ship it?"],
  ["Who knows export?", "Who knows the most about ticket export?"],
  ["Liam → PR #6", "How is liam connected to PR-6?"],
  ["Export button PR?", "Which PR added the export button, and which ticket does it belong to?"],
  ["Who owns BD-101?", "Who owns BD-101 and which decision makes their shipped work stale?"],
  ["What drifted?", "Which features have drifted and why?"],
];

export function AskSection() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<AskResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ask = async (question: string) => {
    setQ(question); setBusy(true); setErr(null);
    try { setRes(await api.ask(question)); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const body = res?.answer.split("\n\nEvidence:")[0];
  return (
    <Section id="ask" index="006" kicker="Ask the graph" title="Ask the graph" intro="The agent picks graph tools. Every answer lists the paths it used.">
      <form className="prompt" onSubmit={(e) => { e.preventDefault(); if (q.trim()) void ask(q.trim()); }}>
        <span className="mono prompt__sign">&gt;</span>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="What did we decide about export, and did we ship it?" autoComplete="off" />
        <button className="btn btn--sm" disabled={busy}>Ask</button>
      </form>
      <div className="chips">{QUESTIONS.map(([label, full]) => <button key={label} className="chip" onClick={() => void ask(full)}>{label}</button>)}</div>
      <AnimatePresence mode="wait">
        {busy && <motion.p key="t" className="answer thinking" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>Querying graph tools</motion.p>}
        {!busy && err && <motion.p key="e" className="warn">{err}</motion.p>}
        {!busy && res && (
          <motion.div key={res.answer} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            {res.engine === "rules" && <div className="notice"><b>Rules agent</b>: the LLM is unavailable{res.fallback_reason ? ` (${res.fallback_reason})` : ""}, so the question is routed to graph tools directly and the answer is assembled from their rows.</div>}
            <div className="answer">{body}</div>
            <div className="mono kicker">Tools called</div>
            <div className="chips" style={{ margin: "6px 0 0" }}>{res.tool_calls.map((t, i) => <span key={i} className="chip">{t.tool} {Object.values(t.args).join(", ")}</span>)}</div>
            {res.paths.length > 0 && <><div className="mono kicker">Graph paths</div>{res.paths.slice(0, 6).map((p) => <PathChips key={p} path={p} />)}</>}
          </motion.div>
        )}
      </AnimatePresence>
    </Section>
  );
}

export function RetroSection() {
  const { sprints, version, openPerson } = useBrain();
  const [sprint, setSprint] = useState<string | null>(null);
  const [r, setR] = useState<Retro | null>(null);
  useEffect(() => { if (!sprint && sprints.length) setSprint(sprints[0].id); }, [sprints, sprint]);
  useEffect(() => { if (sprint) void api.retro(sprint).then(setR); }, [sprint, version]);
  const status = (d: Retro["decided"][number]) =>
    d.dismissed_by ? <span className="badge">dismissed · {d.dismissed_by}</span>
      : d.shipped_in.length ? <span className="badge badge--ok">shipped {d.shipped_in.map((n) => `#${n}`).join(", ")}</span>
        : d.superseded_by === "ticket" ? <span className="badge">in ticket</span> : <span className="badge badge--warn">not shipped</span>;
  return (
    <Section id="retro-sec" index="007" kicker="Sprint retro" title="Sprint retro" intro="What we decided, what we shipped, where they diverge. Every line has a source."
      aside={<div className="tabs">{sprints.map((s) => <button key={s.id} className={sprint === s.id ? "active" : ""} onClick={() => setSprint(s.id)}>{s.name}</button>)}</div>}>
      {r && (
        <div className="retro-cols">
          <div><h3>Decided · {r.decided.length}</h3><ol>{r.decided.map((d, i) => (
            <motion.li key={d.decision} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}>
              <span className="idx">{String(i + 1).padStart(2, "0")}</span>{d.text} {status(d)}
              <span className="src"><button className="person-link" onClick={() => openPerson(d.by)}>{d.by}</button> · {day(d.at)} · {d.ticket} · {d.platform} #{d.channel}</span>
            </motion.li>))}{!r.decided.length && <li>No decisions in chat</li>}</ol></div>
          <div><h3>Shipped · {r.shipped.length}</h3><ol>{r.shipped.map((p, i) => (
            <motion.li key={p.pr} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
              <span className="idx">{String(i + 1).padStart(2, "0")}</span>{isExternal(p.url) ? <a href={p.url} target="_blank" rel="noopener">#{p.pr}</a> : `#${p.pr}`} {p.title}
              <span className="src">{p.author} · {p.tickets.join(", ") || "no ticket"}{p.link.includes("hard") ? "" : ` · linked by ${p.link.join(", ")}`}</span>
            </motion.li>))}</ol></div>
          <div><h3>Diverged · {r.diverged.length}</h3><ol>{r.diverged.map((d, i) => (
            <motion.li key={d.requirement} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.08 }}>
              <span className="idx">{String(i + 1).padStart(2, "0")}</span><b>{d.feature_name}</b>: decided “{d.requirement_text}”
              <span className="src">{d.ticket} still says “{d.ticket_text}”{d.stale_prs.length ? ` · ${d.stale_prs.map((p) => `#${p.pr}`).join(", ")} shipped old version` : ""}</span>
            </motion.li>))}{!r.diverged.length && <li>Nothing diverged</li>}</ol></div>
        </div>
      )}
    </Section>
  );
}

export function SimulateSection() {
  const { actor, setActor, refresh, focusOn } = useBrain();
  const [platform, setPlatform] = useState("slack");
  const [channel, setChannel] = useState("engineering");
  const [text, setText] = useState("Decision: dark mode must also ship a high-contrast theme, BD-105.");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<SimResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const post = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api.simulate({ text, author: actor, platform, channel });
      setRes(r);
      if (r.status === "drift") { await refresh(); if (r.feature) focusOn(r.feature); }
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Section id="simulate" index="008" kicker="Live monitor" title="Simulate a message" intro="Post as a teammate. The live monitor writes it to the graph, resolves it and runs the drift query.">
      <form className="sim" onSubmit={(e) => { e.preventDefault(); void post(); }}>
        <div className="sim__row">
          <label className="mono">Author<select className="field" value={actor} onChange={(e) => setActor(e.target.value)}>{PEOPLE.map((p) => <option key={p}>{p}</option>)}</select></label>
          <label className="mono">Platform<select className="field" value={platform} onChange={(e) => setPlatform(e.target.value)}><option>slack</option><option>discord</option></select></label>
          <label className="mono">Channel<input className="field" value={channel} onChange={(e) => setChannel(e.target.value)} /></label>
        </div>
        <textarea className="field" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
        <button className="btn" disabled={busy}>{busy ? "Running drift monitor…" : "Post message"}</button>
      </form>
      {err && <p className="warn">{err}</p>}
      {res && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
          <div className="result-line">
            <span className={`badge ${res.status === "drift" ? "badge--warn" : ""}`}>{res.status}</span>
            <span>{res.feature ? <>feature <b>{res.feature}</b> via {res.via}</> : "no feature matched"}</span>
            {res.ticket && <span>ticket <b>{res.ticket}</b></span>}
            <span>classified <b>{res.classification?.kind}</b></span>
          </div>
          {res.path && <PathChips path={res.path} />}
          {res.alert && <div className="alertbox">{res.alert.replace(/:warning:\s*/g, "⚠ ").replace(/\*/g, "")}</div>}
        </motion.div>
      )}
    </Section>
  );
}

export function CoverageSection() {
  const { coverage: c } = useBrain();
  const Card = ({ title, items, sub }: { title: string; items: React.ReactNode[]; sub: string }) => (
    <div className="cov__card handles"><span className="mono">{title}</span><span className="big">{items.length}</span><small className="muted">{sub}</small>
      <ul>{items.slice(0, 5).map((x, i) => <li key={i}>{x}</li>)}</ul></div>
  );
  return (
    <Section id="coverage" index="009" kicker="Coverage & risk" title="Coverage & risk" intro="Where the company brain has holes: work nobody linked, tickets nobody discussed, knowledge held by one person.">
      {c && <>
        <div className="cov">
          <Card title="PRs with no ticket" sub="shipped work nobody can trace" items={c.orphan_prs.map((x) => <>#{x.pr} {x.title} <span className="muted">· {x.author}</span></>)} />
          <Card title="Done, no PR" sub="closed tickets with no linked code" items={c.done_without_pr.map((x) => <>{x.ticket} {x.title}</>)} />
          <Card title="Never discussed" sub="tickets no message mentions" items={c.undiscussed_tickets.map((x) => <>{x.ticket} {x.title} <span className="muted">· {x.state}</span></>)} />
        </div>
        <div className="mono kicker">Knowledge concentration · share of a feature's involvement held by one person</div>
        {c.knowledge_risk.map((r) => (
          <div key={r.feature} className="risk__row">
            <div><b style={{ fontWeight: 500 }}>{r.name}</b><div className="muted" style={{ fontSize: 13 }}>{r.top_person} · {r.people} people involved</div></div>
            <div className="risk__bar"><motion.span className={r.top_share >= 0.5 ? "hot" : ""} initial={{ width: 0 }} whileInView={{ width: `${Math.round(r.top_share * 100)}%` }} viewport={{ once: true }} transition={{ duration: 1.2, ease: [0.2, 0.7, 0.1, 1] }} /></div>
            <span className="mono">{Math.round(r.top_share * 100)}%{r.top_share >= 0.5 ? " · bus factor 1" : ""}</span>
          </div>
        ))}
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
