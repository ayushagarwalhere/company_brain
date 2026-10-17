import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AskResult, type Project, type StreamItem } from "../lib/api";
import { useBrain } from "../lib/brain";
import { cleanAnswer, day } from "../lib/ui";
import { Avatar } from "./Evidence";
import { Sources } from "./Panels";
import { Section } from "./Section";

/* The live corporate stream: everything that reaches the graph, newest first, with what it changed. Two buttons
   fire real events through the same endpoints a Slack bot and a tracker webhook use; after each one the agent is
   asked the same question again, and the lines of its answer that changed are marked. */

export const ACTIVE_Q = "What projects are currently active?";

const SLACK = {
  cancel: { author: "maya", platform: "slack", channel: "product", text: "We are cancelling Project Gamma effective immediately. Theming and dark mode move to next year." },
  resume: { author: "maya", platform: "slack", channel: "product", text: "Change of plan: we're resuming Project Gamma. Dark mode is back on for this quarter." },
};
const TICKETS = [
  { title: "PDF version of the weekly SLA report", description: "Globex wants the weekly SLA report as a PDF as well.", creator: "maya", assignee: "sofia", project: "beta" },
  { title: "Audit log entry for every export", description: "Record who exported what and when, for Acme's audit.", creator: "maya", assignee: "kenji", project: "alpha" },
  { title: "SLA breach webhook for Globex", description: "Send breach events to Globex's incident tool.", creator: "arjun", assignee: "dev", project: "beta" },
];

const SYSTEM: Record<string, string> = { slack: "Slack", discord: "Discord", linear: "Linear", jira: "Jira", tracker: "Tracker", notion: "Notion (demo)", gdrive: "Google Drive" };

function where(it: StreamItem) {
  if (it.kind === "message") return `${SYSTEM[it.source || ""] || "Chat"} #${it.channel}`;
  if (it.kind === "ticket") return SYSTEM[it.source || ""] || "Tracker";
  return SYSTEM[it.source || ""] || "Docs";
}

function when(it: StreamItem) {
  const d = new Date(it.ms);
  const today = new Date().toDateString() === d.toDateString();
  return today ? d.toTimeString().slice(0, 5) : day(it.ts).slice(5).replace("-", "/");
}

/** What the event did to the graph, as small chips. */
function Effects({ it }: { it: StreamItem }) {
  const chips: [string, boolean?][] = [];
  if (it.project_to) chips.push([`${it.project} → ${it.project_to}`, true]);
  if (it.kind === "ticket" && it.project) chips.push([`${it.id} in ${it.project}`, true]);
  if (it.kind === "ticket" && it.assignee) chips.push([`assigned to ${it.assignee}`]);
  if (it.changes) chips.push(["changes a requirement", true]);
  for (const t of it.tickets || []) chips.push([`names ${t}`]);
  for (const d of it.docs || []) chips.push([`points to ${d}`]);
  if (!chips.length) return null;
  return <div className="strm__fx mono">{chips.map(([c, hot]) => <span key={c} className={hot ? "hot" : ""}>{c}</span>)}</div>;
}

/** What the graph holds right now, per project, with what changed since the last ask marked: a status that changed
    is struck through, a ticket that's new is lit. Read from the graph, so it's exact whatever the agent's wording. */
function ProjectStrip({ now, before }: { now: Project[]; before: Project[] | null }) {
  return (
    <div className="strm__proj">
      {now.map((p) => {
        const was = before?.find((b) => b.id === p.id);
        const off = !!p.status && p.status !== "active";
        const flipped = !!was && (was.status || "active") !== (p.status || "active");
        const added = was ? p.tickets.filter((t) => !was.tickets.includes(t)) : [];
        return (
          <div key={p.id} className={`${off ? "off" : ""} ${flipped ? "flip" : ""}`}>
            <b>{p.name}</b>
            <span className="mono">{off ? p.status : "active"} · {p.tickets.length} tickets{added.length ? <i> +{added.join(", ")}</i> : null}</span>
          </div>
        );
      })}
    </div>
  );
}


/** The answer, line by line. With the rules agent (same wording every time) the lines that changed since the last
    answer are marked; an LLM rewords everything, so its answer is shown as is. */
function DiffAnswer({ now, before, exact }: { now: string; before: string | null; exact: boolean }) {
  const body = (s: string) => cleanAnswer(s).split("\n").map((l) => l.trim()).filter(Boolean);
  const lines = body(now), old = before && exact ? body(before) : null;
  const gone = old ? old.filter((l) => !lines.includes(l)) : [];
  return (
    <div className="strm__ans">
      {lines.map((l, i) => {
        const added = old && !old.includes(l);
        return <motion.div key={`${i}${l}`} className={added ? "add" : ""} initial={added ? { opacity: 0, x: -6 } : false} animate={{ opacity: 1, x: 0 }}>{l}</motion.div>;
      })}
      {gone.map((l) => <div key={`gone${l}`} className="del">{l}</div>)}
    </div>
  );
}

export function StreamSection() {
  const { refresh, version, workspace } = useBrain();
  const [items, setItems] = useState<StreamItem[]>([]);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<"slack" | "ticket" | "ask" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<AskResult | null>(null);
  const [before, setBefore] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [gammaOff, setGammaOff] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsBefore, setProjectsBefore] = useState<Project[] | null>(null);
  const seen = useRef<Set<string> | null>(null);
  const nextTicket = useRef(0);
  const last = useRef<string | null>(null);
  const projectsAt = useRef<Project[] | null>(null);

  const load = useCallback(async () => {
    const xs = await api.stream(12).catch(() => null);
    if (!xs) return;
    const known = seen.current;
    if (known) setFresh(new Set(xs.filter((x) => !known.has(`${x.kind}:${x.id}`)).map((x) => `${x.kind}:${x.id}`)));
    seen.current = new Set(xs.map((x) => `${x.kind}:${x.id}`));
    setItems(xs);
  }, []);
  // live events elsewhere (bots, webhooks, the tour) land here too
  useEffect(() => { if (workspace === "ready") void load(); }, [load, version, workspace]);
  useEffect(() => {
    if (workspace !== "ready") return;
    api.projects().then((ps) => { setProjects(ps); setGammaOff(ps.some((p) => p.id === "gamma" && p.status && p.status !== "active")); }).catch(() => undefined);
  }, [version, workspace]);

  const ask = useCallback(async (auto = false) => {
    setBusy("ask");
    try {
      const [r, ps] = await Promise.all([api.ask(ACTIVE_Q), api.projects()]);
      setProjectsBefore(auto ? projectsAt.current : null);
      projectsAt.current = ps;
      setProjects(ps);
      setBefore(last.current);
      last.current = r.answer;
      setRes(r);
      if (!auto) setNote(null);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  }, []);

  const fire = async (kind: "slack" | "ticket") => {
    setBusy(kind); setErr(null);
    try {
      if (kind === "slack") {
        const msg = gammaOff ? SLACK.resume : SLACK.cancel;
        const r = await api.simulate(msg);
        setGammaOff(r.change?.status === "changed" ? r.change.to !== "active" : gammaOff);
        setNote(`${msg.author} posted in Slack #${msg.channel}. The agent was asked again:`);
      } else {
        const t = TICKETS[nextTicket.current++ % TICKETS.length];
        const r = await api.newTicket(t);
        setNote(`${r.ticket} was opened in the tracker, in ${r.project_name}. The agent was asked again:`);
      }
      await Promise.all([refresh(), load()]);
      await ask(true);
    } catch (e) { setErr((e as Error).message); setBusy(null); }
  };

  return (
    <Section id="stream" index="06" title="Live stream"
      intro="Everything that reaches the graph, as it arrives: chat, tickets, doc edits, and what each one changed. Fire an event, and the agent's answer to the same question changes, because the graph did.">
      <div className="strm">
        <div className="strm__col">
          <div className="strm__head">
            <span className="mono"><i className="strm__dot" aria-hidden />Live corporate stream</span>
            <span className="strm__btns">
              <button className="btn btn--sm" onClick={() => void fire("slack")} disabled={!!busy}>
                {busy === "slack" ? "Posting…" : gammaOff ? "Simulate Slack message: resume Gamma" : "Simulate Slack message"}
              </button>
              <button className="btn btn--ghost btn--sm" onClick={() => void fire("ticket")} disabled={!!busy}>{busy === "ticket" ? "Opening…" : "Simulate new ticket"}</button>
            </span>
          </div>
          <ol className="strm__list">
            <AnimatePresence initial={false}>
              {items.map((it) => {
                const k = `${it.kind}:${it.id}`;
                return (
                  <motion.li key={k} layout className={`strm__item strm__item--${it.kind} ${fresh.has(k) ? "strm__item--new" : ""}`}
                    initial={{ opacity: 0, y: -14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.35 }}>
                    <Avatar name={it.who || "?"} size={30} />
                    <div>
                      <div className="strm__meta mono"><span className="src"><b>{where(it)}</b>{it.kind === "message" ? it.id.startsWith("sim:") ? "live" : it.id : it.id}</span><span>{it.who}</span><span>{when(it)}</span></div>
                      <p>{it.kind === "doc" ? <>Edited <b>{it.text}</b></> : it.kind === "ticket" ? <>New ticket: <b>{it.text}</b>{it.state ? ` · ${it.state}` : ""}</> : it.text}</p>
                      <Effects it={it} />
                    </div>
                  </motion.li>
                );
              })}
            </AnimatePresence>
          </ol>
        </div>
        <div className="strm__col strm__agent">
          <div className="strm__head"><span className="mono">Ask the agent</span>{res && <span className="mono muted">{res.tool_calls.map((t) => t.tool).join(", ")}</span>}</div>
          <div className="q">{ACTIVE_Q}</div>
          {!res && <button className="btn btn--sm" onClick={() => void ask()} disabled={!!busy} style={{ justifySelf: "start" }}>{busy === "ask" ? "Asking…" : "Ask it now"}</button>}
          {note && <p className="strm__note mono">{note}</p>}
          {err && <p className="warn">{err}</p>}
          {res && (
            <>
              <span className="mono strm__k">In the graph</span>
              <ProjectStrip now={projects} before={projectsBefore} />
              <span className="mono strm__k">The agent's answer{res.engine === "rules" ? "" : ` · ${res.engine || "LLM"}`}</span>
              <DiffAnswer now={res.answer} before={before} exact={res.engine === "rules"} />
              <Sources res={res} />
              <button className="link mono" onClick={() => void ask()} disabled={!!busy} style={{ justifySelf: "start" }}>{busy === "ask" ? "asking…" : "Ask again"}</button>
            </>
          )}
          {!res && <p className="muted strm__how">Ask first, then fire an event on the left: the answer is asked again on its own, with what changed marked.</p>}
        </div>
      </div>
    </Section>
  );
}
