import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { api, type AskResult, type Impact, type Project } from "../lib/api";
import { useBrain } from "../lib/brain";
import { plural } from "../lib/ui";
import { ColumnGraph } from "./ColumnGraph";
import { CountUp } from "./Motion";
import { Sources } from "./Panels";
import { Section } from "./Section";

/* "If we delay Project Alpha by two weeks, which other teams and downstream client deliverables are impacted?"
   Answered by walking the graph (pipeline/impact.py): Project -INCLUDES-> Ticket -BLOCKS->* Ticket <-INCLUDES- Project,
   Deliverable -NEEDS-> Project -> Client, and the people doing the work -> their teams. */

const WEEKS = [1, 2, 3, 4, 6];
const HEADERS: Record<number, string> = { 0: "Teams", 1: "People", 2: "Delayed", 3: "Its tickets", 4: "Blocked", 5: "Waiting", 6: "Deliverables", 7: "Clients" };
const words = ["zero", "one", "two", "three", "four", "five", "six"];
const fmt = (iso?: string) => (iso ? new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }) : "–");

/** Due date vs the new ready date on one small scale: where the deliverable lands relative to its promise. */
function Slack({ d }: { d: Impact["deliverables"][number] }) {
  const mid = 50, pos = Math.max(3, Math.min(97, mid - (d.slack_days / 28) * 47));  // the due date sits in the middle
  const lo = Math.min(pos, mid), hi = Math.max(pos, mid);
  return (
    <div className={`slack slack--${d.status.replace(" ", "-")}`} aria-label={`ready ${d.ready}, due ${d.due}`}>
      <span className="slack__bar" style={{ left: `${lo}%`, right: `${100 - hi}%` }} />
      <i className="slack__due" style={{ left: `${mid}%` }} title={`due ${d.due}`} />
      <i className="slack__ready" style={{ left: `${pos}%` }} title={`ready ${d.ready}`} />
    </div>
  );
}

export function ImpactSection() {
  const { version } = useBrain();
  const [projects, setProjects] = useState<Project[]>([]);
  const [target, setTarget] = useState("alpha");
  const [weeks, setWeeks] = useState(2);
  const [res, setRes] = useState<Impact | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [agent, setAgent] = useState<AskResult | null>(null);
  const [asking, setAsking] = useState(false);

  useEffect(() => { void api.projects().then(setProjects).catch((e) => setErr((e as Error).message)); }, [version]);
  useEffect(() => {
    setAgent(null);
    void api.impact(target, weeks * 7).then((r) => { setRes(r); setErr(null); }).catch((e) => setErr((e as Error).message));
  }, [target, weeks, version]);

  const project = projects.find((p) => p.id === target);
  const question = `If we delay the launch of ${project?.name || "Project Alpha"} by ${words[weeks] || weeks} ${plural(weeks, "week", "weeks")}, which other teams and downstream client deliverables will be impacted?`;
  const ask = async () => {
    setAsking(true);
    try { setAgent(await api.ask(question)); } catch (e) { setErr((e as Error).message); } finally { setAsking(false); }
  };
  const root = res?.projects.find((p) => p.root);
  const down = res?.projects.filter((p) => !p.root) || [];
  const hit = res?.deliverables.filter((d) => d.moved) || [];
  const misses = hit.filter((d) => d.status === "misses").length, tight = hit.filter((d) => d.status === "tight").length;

  return (
    <Section id="impact" index="03" title="Impact analysis"
      intro="What happens if a launch slips? The graph walks from the project to its tickets, through every ticket they block, to the projects waiting on them, the client deliverables that need them, and the teams doing the work."
      aside={<div className="tabs">{projects.map((p) => <button key={p.id} className={target === p.id ? "active" : ""} onClick={() => setTarget(p.id)}>{p.name}</button>)}</div>}>
      <div className="whatif">
        <p className="whatif__q">
          If we delay <b>{project?.name || "…"}</b> <span className="muted">({project?.about})</span> by
          <span className="tabs whatif__weeks">{WEEKS.map((w) => <button key={w} className={weeks === w ? "active" : ""} onClick={() => setWeeks(w)}>{w} {plural(w, "week", "weeks")}</button>)}</span>
        </p>
        <button className="btn btn--sm" disabled={asking} onClick={() => void ask()}>{asking ? "Asking…" : "Ask the agent this"}</button>
      </div>
      {err && <p className="warn">{err}</p>}
      {res && root && (
        <>
          <div className="nums" style={{ marginTop: 20 }}>
            <div className="hot"><b>{fmt(root.new_launch)}</b><span className="mono">new launch · was {fmt(root.launch)}</span></div>
            <div><CountUp value={down.filter((p) => p.slip_days > 0).length} /><span className="mono">{down.filter((p) => p.slip_days > 0).length === 1 ? "project slips" : "projects slip"} downstream</span></div>
            <div className={misses ? "hot" : ""}><CountUp value={misses} /><span className="mono">client {plural(misses, "deliverable misses", "deliverables miss")}{tight ? ` · ${tight} tight` : ""}</span></div>
            <div><CountUp value={res.teams.filter((t) => t.id).length} /><span className="mono">teams affected · {res.teams.reduce((a, t) => a + t.people.length, 0)} people</span></div>
          </div>
          <div style={{ marginTop: 16 }}>
            <ColumnGraph data={res.graph} headers={HEADERS} note={`delay ${res.days} days`} />
          </div>
          <div className="impact">
            <div>
              <span className="kicker">Client deliverables · due vs ready</span>
              <ul className="impact__list">
                {res.deliverables.map((d) => (
                  <li key={d.id} className={d.moved ? "" : "muted"}>
                    <div className="impact__top"><b>{d.client_name}</b>
                      <span className={`tag ${d.status === "misses" && d.moved ? "tag--inv" : d.status === "tight" && d.moved ? "tag--dash" : ""}`}>
                        {!d.moved ? "not affected" : d.status === "misses" ? `misses by ${-d.slack_days} d` : `${d.status} · ${d.slack_days} d left`}
                      </span>
                    </div>
                    <p>{d.title}</p>
                    <Slack d={d} />
                    <div className="mono muted impact__meta"><span>due {fmt(d.due)}</span><span>ready {fmt(d.ready)}</span><span>owner {d.owner}</span><span>needs {d.needs.join(", ")}</span></div>
                  </li>
                ))}
                {!res.deliverables.length && <li className="muted">No client deliverable depends on this.</li>}
              </ul>
              {down.length > 0 && <>
                <span className="kicker" style={{ marginTop: 28 }}>Downstream projects</span>
                <ul className="impact__list">
                  {down.map((p) => (
                    <li key={p.id}>
                      <div className="impact__top"><b>{p.name}</b><span className={`tag ${p.slip_days ? "tag--inv" : ""}`}>{p.slip_days ? `slips ${p.slip_days} d` : "has slack"}</span></div>
                      <p>{p.via ? <><span className="mono">{p.via.from} blocks {p.via.to}</span>: {p.via.why}.</> : null}</p>
                      <div className="mono muted impact__meta"><span>launch {fmt(p.launch)} → {fmt(p.new_launch)}</span></div>
                    </li>
                  ))}
                </ul>
              </>}
            </div>
            <div>
              <span className="kicker">Teams and the people doing the work</span>
              <ul className="impact__list">
                {res.teams.map((t) => (
                  <li key={t.id || "none"}>
                    <div className="impact__top"><b>{t.name}</b><span className="mono muted">{t.people.length} {plural(t.people.length, "person", "people")}</span></div>
                    {t.people.map((p) => <p key={p.id}><b className="impact__who">{p.name}</b> {p.roles.join(" · ")}</p>)}
                  </li>
                ))}
              </ul>
              {res.drift.length > 0 && <>
                <span className="kicker" style={{ marginTop: 28 }}>Worth folding into the new plan</span>
                <ul className="impact__list">
                  {res.drift.map((d) => <li key={d.ticket}><p><span className="mono">{d.ticket}</span> has an open chat decision by {d.by}: “{d.text}”</p></li>)}
                </ul>
              </>}
            </div>
          </div>
        </>
      )}
      <AnimatePresence>
        {(asking || agent) && (
          <motion.div className="console" style={{ minHeight: 0, marginTop: 24 }} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
            <div className="console__bar mono"><span>Graph agent</span><span>{agent ? (agent.engine === "rules" ? "rules agent · no LLM" : agent.engine) : "…"}</span>
              <span>{agent ? `${agent.tool_calls.map((t) => t.tool).join(", ")}` : ""}</span></div>
            <div className="console__body">
              <div className="q">{question}</div>
              {asking ? <span className="typing"><i /><i /><i /></span> : agent && <>
                <div className="a">{agent.answer.split(/\n\n\**Evidence:?\**/)[0].replace(/\*\*/g, "")}</div>
                <Sources res={agent} />
              </>}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Section>
  );
}
