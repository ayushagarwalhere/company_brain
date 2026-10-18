import { AnimatePresence, motion } from "framer-motion";
import { Children, cloneElement, isValidElement, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactElement, type ReactNode } from "react";
import { api, ORG, type Drift } from "../lib/api";
import { useBrain } from "../lib/brain";
import { scrollToEl } from "../lib/fx";
import { cleanAnswer } from "../lib/ui";
import { DEMO_HREF, isSandboxOrg, tourOn } from "../lib/routes";
import { ACTIVE_Q } from "./Stream";

/** The product tour: a guided walk through every feature on a fresh private sandbox of the demo company, where each
    button performs the real action through the real API and its answer is shown, highlighted, in the tour. It is
    always there in the demo: "Open the demo" (?org=demo&tour=1) starts it on a fresh sandbox, a #section in the link
    starts it at that section's step, and folding it away leaves a small pill, never in the way of the page.
    Each step leads with one instruction, big and in the step's colour, and the section it is about carries a label. */
export const TOUR_HREF = DEMO_HREF;
export const tourActive = () => tourOn() || isSandboxOrg(ORG);

/** Per-tab memory of where the tour was (step, folded), so coming back to the demo picks it up. */
function remember(k: string, v?: string): string | null {
  try {
    if (v === undefined) return sessionStorage.getItem(k);
    sessionStorage.setItem(k, v);
  } catch { /* storage blocked: just forget */ }
  return null;
}

/* ---- highlighting the answer: tickets, PRs, docs, tasks, people, dates, durations and verdicts stand out */
const PEOPLE_RE = "maya|arjun|sofia|dev|kenji|priya|liam|zara|Maya Chen|Kenji Watanabe|Sofia Alvarez|Priya Nair|Liam O'Connor";
const MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec";
const KEY = new RegExp(
  `(\\bBD-\\d+\\b|\\bPR[ -]?#?\\d+\\b|#\\d+\\b|\\bDOC-\\d+\\b|\\bT-\\d+\\b|\\b\\d{4}-\\d{2}-\\d{2}\\b|\\b\\d{1,2} (?:${MONTHS})\\w*\\b|` +
  `[−-]?\\b\\d+(?:\\.\\d+)? ?(?:d|days?|weeks?|ms)\\b|\\b(?:${PEOPLE_RE})\\b|\\b(?:misses|slips|drift|stale|resolved|refused|not in the graph|cancelled|out of office|blocked|OOO|active projects?|manager)\\b|\\bProject \\w+)`, "gi");

function Hl({ text }: { text: string }) {
  const parts = text.split(KEY);
  return <>{parts.map((t, k) => (k % 2 ? <mark key={k} className="hl">{t}</mark> : t))}</>;
}

/** Walk a step's output and highlight every piece of text in it, whatever the step built. */
function highlight(node: ReactNode): ReactNode {
  if (typeof node === "string") return <Hl text={node} />;
  if (Array.isArray(node)) return Children.map(node, highlight);
  if (isValidElement(node)) {
    const el = node as ReactElement<{ children?: ReactNode }>;
    return el.props.children === undefined ? el : cloneElement(el, undefined, highlight(el.props.children));
  }
  return node;
}

const DECISION = "Decision: the export button must also offer a JSON download, BD-102.";

type Out = { tone?: "ok" | "warn" | "info"; lines: ReactNode[] };
type Step = {
  kicker: string; title: string; body: ReactNode;
  todo: ReactNode;                         // the instruction: what to do (or look at) now
  after?: ReactNode;                       // what to look at once the step's action has run
  target?: string;                         // element id or selector to scroll to and highlight
  action?: { label: string; run: () => Promise<Out> };
  extra?: { label: string; run: () => Promise<Out> }[];
};

const latestDrift = (rows: Drift[], ticket: string) => rows.filter((d) => d.ticket === ticket).sort((a, b) => b.changed_ms - a.changed_ms)[0];

export function Tour() {
  const { refresh, focusOn, specFor, announce, workspace, workspaceError: err } = useBrain();
  const ready = workspace === "ready" ? "ready" : workspace === "failed" ? "failed" : "setting-up";
  const [i, setI] = useState(0);
  const [out, setOut] = useState<Out | null>(null);
  const [outKey, setOutKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [min, setMinState] = useState(() => !tourOn() && remember("tour-min") === "1");
  const setMin = useCallback((v: boolean) => { setMinState(v); remember("tour-min", v ? "1" : "0"); }, []);
  const [done, setDone] = useState(false);
  const [acc, setAcc] = useState("");
  const answer = useRef<HTMLDivElement>(null);

  const steps: Step[] = useMemo(() => [
    {
      kicker: "Welcome", target: "top",
      title: "A company brain that catches decisions that never shipped",
      todo: <>Press <b>Next →</b> to begin. Each step scrolls the page to its feature and labels the part to look at.</>,
      body: <>This is <b>Brightdesk</b>, a sandbox software company: 8 people, Slack and Discord chat, tickets, GitHub PRs and docs, all in one FalkorDB graph. It's a private copy just for this tour, so <b>every “Do it” button does the real thing</b>.</>,
    },
    {
      kicker: "The problem", target: "drift",
      title: "Two decisions made in chat never reached the work",
      todo: <>Look at the labelled <b>Open drift</b> cards: what the ticket still says, next to what chat decided.</>,
      body: <>Each card is a <b>drift</b>: someone with the right to change a ticket decided something new in chat, and nothing newer replaced it, no PR shipped it, nobody kept the old scope. The card shows what the ticket still says, what was decided, who, where, and the PRs and docs still on the old version.</>,
    },
    {
      kicker: "Live monitoring", target: "drift",
      title: "A decision lands in Slack",
      todo: <>Click <b>Post the message ▸</b> to send Maya's decision into Slack.</>,
      after: <>A new drift for <b>BD-102</b> just appeared in the labelled section. The bot's reply is below.</>,
      body: <>Maya, who owns BD-102, posts in <span className="mono">#engineering</span>: <i>“{DECISION}”</i>. The live monitor reads it like a Slack or Discord bot would, links it to the ticket through the graph, and alerts in the thread.</>,
      action: {
        label: "Post the message",
        run: async () => {
          const r = await api.simulate({ text: DECISION, author: "maya", platform: "slack", channel: "engineering" });
          announce({ ticket: r.ticket || "BD-102" });
          await refresh();
          return r.status === "drift"
            ? { tone: "warn", lines: [<b key="a">Drift raised on {r.ticket}.</b>, "The bot's reply in the Slack thread:", <pre key="b" className="tour__pre">{(r.alert || "").replace(/[*_`]/g, "").slice(0, 420)}</pre>] }
            : { tone: "info", lines: [`Monitor result: ${r.status}.`] };
        },
      },
    },
    {
      kicker: "Evidence", target: "graph-sec",
      title: "Every alert carries its proof",
      todo: <>Click <b>Show the path in the graph ▸</b>, then click any lit node to read it.</>,
      after: <>The lit path in the labelled graph is the evidence. Click a node for its text.</>,
      body: <>The graph path behind the alert: <span className="mono">person → message → requirement → ticket → feature</span>, plus the PR and doc still on the old version. Nobody has to trust the bot; they can read why it fired. In this company the deciding messages never name a ticket: threads, people and time connect them.</>,
      action: { label: "Show the path in the graph", run: async () => { focusOn("feat_ticket_export_to_csv"); return { tone: "info", lines: ["The lit path is the evidence. Click any node for its text."] }; } },
    },
    {
      kicker: "Company map", target: "map-sec",
      title: "The whole company, as one graph you can play with",
      todo: <>In the labelled map, set <b>Highlight relation layer</b> to <b>Reporting lines (HR)</b>, then drag a node or slide the spacing.</>,
      body: <>People, teams, projects, clients, deliverables, docs and tickets, with every link between them. Filter by category, light one kind of relation, and the counts and density follow what's on screen.</>,
    },
    {
      kicker: "Impact analysis", target: "impact",
      title: "“If we delay Project Alpha by two weeks…”",
      todo: <>Click <b>Run the what-if ▸</b> to push Project Alpha back two weeks.</>,
      after: <>Read the dates and slips below, then see them laid out in the labelled section.</>,
      body: <>…which other teams and client deliverables are hit? The graph walks <span className="mono">Project → Ticket → BLOCKS → Ticket → Project</span>, then <span className="mono">Deliverable → Client</span> and the people doing the work to their teams.</>,
      action: {
        label: "Run the what-if",
        run: async () => {
          const r = await api.impact("alpha", 14);
          const root = r.projects.find((p) => p.root);
          return { tone: "warn", lines: [
            <b key="l">{r.target.name} launches {root?.new_launch} instead of {root?.launch}.</b>,
            ...r.projects.filter((p) => !p.root && p.via).map((p) => <span key={p.id}>{p.name} slips {p.slip_days} d: {p.via!.from} blocks {p.via!.to}.</span>),
            ...r.deliverables.filter((d) => d.moved).map((d) => <span key={d.id}>{d.client_name}: {d.status === "misses" ? `misses by ${-d.slack_days} d` : `${d.status}, ${d.slack_days} d left`}</span>),
            <span key="t">Teams: {r.teams.map((t) => t.name).join(", ")}.</span>,
          ] };
        },
      },
    },
    {
      kicker: "Gets work done", target: "drift",
      title: "The agent plans the fix from the graph",
      todo: <>Click <b>Plan the fix for BD-102 ▸</b>.</>,
      after: <>Each line is a task, with the person the graph picked for it.</>,
      body: <>Who wrote the stale PR? Who owns the doc? Who may decide? The plan is a graph read: <span className="mono">AUTHORED</span>, <span className="mono">ASSIGNED_TO</span> and who's most involved in the feature.</>,
      action: {
        label: "Plan the fix for BD-102",
        run: async () => {
          const d = latestDrift(await api.drift(), "BD-102");
          if (!d) return { tone: "info", lines: ["Run the “decision lands in Slack” step first."] };
          const p = await api.plan(d.requirement);
          return { tone: "info", lines: [
            ...p.items.map((it, k) => <span key={k}>{k + 1}. {it.what}{it.kind !== "ticket" ? <> → <b>{it.assignee}</b></> : null}</span>),
            <span key="t">Also tell: {p.tell.join(", ")}. Can approve: <b>{p.can_apply.join(", ")}</b>.</span>,
          ] };
        },
      },
    },
    {
      kicker: "Who owns what", target: "drift",
      title: "Only the ticket's owners can decide",
      todo: <>Click <b>Approve as Zara ▸</b>. She isn't an owner, so watch it get refused.</>,
      after: <>Refused, and it names who can approve. Next, the owner tries.</>,
      body: <>Zara is in QA and doesn't own BD-102. If she tries to approve, the agent refuses and says who can. The same rule applies in Slack, Discord, the dashboard and the API.</>,
      action: {
        label: "Approve as Zara",
        run: async () => {
          const d = latestDrift(await api.drift(), "BD-102");
          if (!d) return { tone: "info", lines: ["Nothing open on BD-102."] };
          try { await api.applyPlan(d.requirement, "zara"); return { tone: "info", lines: ["(unexpectedly allowed)"] }; }
          catch (e) { return { tone: "warn", lines: [<span key="r">🔒 {(e as Error).message}</span>] }; }
        },
      },
    },
    {
      kicker: "Gets work done", target: "drift",
      title: "The owner approves, and the work is assigned",
      todo: <>Click <b>Approve as Maya ▸</b>. She owns BD-102.</>,
      after: <>The drift is resolved and the follow-up tasks are on the page, each with its owner.</>,
      body: <>Maya approves. The decision becomes BD-102's next version, and each stale PR and doc gets a follow-up task for the person who wrote it, kept in the graph and surviving every rebuild.</>,
      action: {
        label: "Approve as Maya",
        run: async () => {
          const d = latestDrift(await api.drift(), "BD-102");
          if (!d) return { tone: "info", lines: ["Nothing open on BD-102."] };
          const r = await api.applyPlan(d.requirement, "maya");
          await refresh();
          setTimeout(() => { const el = document.querySelector(".followups"); if (el) scrollToEl(el as HTMLElement, -160); }, 500);
          return { tone: "ok", lines: [<b key="d">✅ {r.ticket} now carries the decision ({r.version.split(":").pop()}).</b>,
            ...r.tasks.map((t) => <span key={t.id}>T-{t.num}: {t.title} → <b>{t.assignee}</b></span>)] };
        },
      },
    },
    {
      kicker: "Live stream", target: "stream",
      title: "The graph changes, so the answer changes",
      todo: <>Click <b>Cancel Project Gamma in Slack ▸</b>. Maya posts it, the graph updates, and the agent is asked again.</>,
      after: <>Gamma left the active list, and the answer says who cancelled it and where. The new message is at the top of the labelled stream.</>,
      body: <>Every message, ticket and doc edit reaches the graph as it happens. A lead's “we're cancelling Project Gamma” changes the project's status, with the message as evidence, and the next answer reflects it.</>,
      action: {
        label: "Cancel Project Gamma in Slack",
        run: async () => {
          const active = async () => (await api.projects()).filter((p) => !p.status || p.status === "active").map((p) => p.name).join(", ");
          const before = await active();
          const r = await api.simulate({ text: "We are cancelling Project Gamma effective immediately. Theming and dark mode move to next year.", author: "maya", platform: "slack", channel: "product" });
          await refresh();
          const [now, after] = await Promise.all([active(), api.ask(ACTIVE_Q)]);
          return { tone: "ok", lines: [
            <b key="c">{r.change?.status === "changed" ? `${r.change.name} is now ${r.change.to}.` : `${r.change?.name ?? "Project Gamma"} was already ${r.change?.to ?? "changed"}.`}</b>,
            <i key="q">“{ACTIVE_Q}”</i>,
            <span key="b">Active before: {before}</span>,
            <span key="n">Active now: <b>{now}</b></span>,
            <pre key="a" className="tour__pre">{cleanAnswer(after.answer).slice(0, 520)}</pre>,
          ] };
        },
      },
    },
    {
      kicker: "Four tools, one answer", target: "ask",
      title: "“Why is the database migration delayed, and who can approve an override?”",
      todo: <>Click <b>Ask across four tools ▸</b>. Watch the hops light up in the labelled graph.</>,
      after: <>Slack → doc → ticket → HR: the answer names the blocker and who can override, and the sources under it say where each piece came from (the doc, ticket and HR record are the demo company's sample data).</>,
      body: <>Nobody wrote the answer down anywhere. A Slack message points to a design doc, the doc names the ticket, the ticket's assignee is out of office in the HR records, and HR knows their manager. The agent walks all four in one go.</>,
      action: {
        label: "Ask across four tools",
        run: async () => {
          const q = "Why is the database migration delayed and who can approve an override?";
          const r = await api.ask(q);
          window.dispatchEvent(new CustomEvent("ask-show", { detail: { question: q, result: r } }));
          return { tone: "ok", lines: [<i key="q">“{q}”</i>, <pre key="a" className="tour__pre">{cleanAnswer(r.answer)}</pre>,
            <span key="s" className="mono tour__dim">Sources: {(r.sources || []).map((s) => s.label).join(" · ")}</span>] };
        },
      },
    },
    {
      kicker: "Ask the company brain", target: "ask",
      title: "Questions a team actually asks",
      todo: <>Pick a question below. Each answer comes from read-only graph tools.</>,
      after: <>Try another one, or type your own in the labelled Ask box.</>,
      body: <>The agent answers from fixed graph tools (read-only) and shows its sources. Try a few:</>,
      extra: [
        ["Who knows the most?", "Who knows the most about ticket export?"],
        ["How are they connected?", "How is liam connected to PR #6?"],
        ["Is it accurate?", "What does BD-103 say and is it still accurate?"],
        ["Not in the graph", "Is BD-999 stale?"],
      ].map(([label, q]) => ({
        label,
        run: async () => {
          const r = await api.ask(q);
          return { tone: "info", lines: [<i key="q">“{q}”</i>, <pre key="a" className="tour__pre">{cleanAnswer(r.answer).slice(0, 520)}</pre>,
            <span key="e" className="mono tour__dim">{r.engine === "rules" ? "rules agent, no LLM" : r.engine} · {r.tool_calls.length} tool call{r.tool_calls.length === 1 ? "" : "s"}</span>] };
        },
      })),
    },
    {
      kicker: "Stays current", target: "docs-sec",
      title: "A doc changes: only what changed is re-embedded",
      todo: <>Click <b>Edit the export PRD ▸</b>.</>,
      after: <>Only the changed chunk got a new vector. Try <b>Mention BD-104 too</b> for a new graph edge.</>,
      body: <>Docs are chunks in a FalkorDB vector index, linked to their author and tickets. Maya writes the chat decision into the export PRD, the way a Google Docs edit arrives: only the chunk she changed gets a new vector, and the doc's links to tickets are recomputed from the new text.</>,
      action: {
        label: "Edit the export PRD",
        run: async () => {
          const doc = (await api.docs("maya")).find((d) => d.id === "DOC-1");
          if (!doc) return { tone: "info", lines: ["DOC-1 isn't in this sandbox."] };
          const r = await api.updateDoc("DOC-1", doc.text.replace("last 30 days", "any custom date range up to 12 months"), "maya");
          await refresh();
          return { tone: "ok", lines: [
            <b key="v">Vectors: {r.sync.embedded} re-embedded, {r.sync.kept} kept, {r.sync.removed} removed.</b>,
            <span key="p" className="mono">{r.sync.parts.map((p) => `${p.id} ${p.status}`).join(" · ")}</span>,
            `Graph edges: MENTIONS ${r.sync.mentions.join(", ")}.`,
            r.no_longer_stale ? "DOC-1 is no longer stale for the BD-101 drift." : "",
          ] };
        },
      },
      extra: [{
        label: "Mention BD-104 too",
        run: async () => {
          const doc = (await api.docs("maya")).find((d) => d.id === "DOC-1");
          if (!doc) return { tone: "info", lines: ["DOC-1 isn't in this sandbox."] };
          const r = await api.updateDoc("DOC-1", `${doc.text.trimEnd()}\n\nRelated: BD-104.`, "maya");
          return { tone: "ok", lines: [<b key="v">Vectors: {r.sync.embedded} re-embedded, {r.sync.kept} kept.</b>, `New edge: DOC-1 MENTIONS ${r.sync.mentions.filter((t) => !doc.tickets.includes(t)).join(", ") || "none"}.`] };
        },
      }],
    },
    {
      kicker: "Permissions", target: "who-sees",
      title: "“What is everyone's salary?”",
      todo: <>Ask as <b>Zara</b>, then as <b>Maya</b>, and compare the answers.</>,
      after: <>Same question, different person, different answer. The doc never reaches someone who may not see it.</>,
      body: <>A confidential doc with salary bands is shared with <b>leads and HR</b> only. Ask the same question as different people: access is checked in the vector query, in every agent tool and on every API response, so a regular employee gets nothing, not even a hint that the doc exists.</>,
      extra: ([["Ask as Zara (QA)", "zara"], ["Ask as Maya (lead)", "maya"], ["Ask anonymously", null]] as [string, string | null][]).map(([label, who]) => ({
        label,
        run: async () => {
          const r = await api.ask("What is everyone's salary?", who);
          return { tone: who === "maya" ? "ok" : "warn", lines: [<i key="q">{who || "anonymous"}: “What is everyone's salary?”</i>,
            <pre key="a" className="tour__pre">{cleanAnswer(r.answer).slice(0, 360)}</pre>] };
        },
      })),
    },
    {
      kicker: "Sprint retro", target: "retro-sec",
      title: "What we decided, what we shipped, where they diverge",
      todo: <>Look at the labelled sprint retro: decided, shipped and diverged, each line with its source.</>,
      body: <>Every sprint, from the graph: decisions made in chat, PRs merged, and the ones that diverged, each line with its source. No status meeting needed to find out what slipped.</>,
    },
    {
      kicker: "Risk", target: "coverage",
      title: "Where the company is fragile",
      todo: <>Look at the labelled bars: how much of each feature one person holds.</>,
      body: <>Knowledge held by one person (bus factor), PRs with no ticket, closed tickets with no code, tickets nobody ever discussed. The same graph, read for gaps.</>,
    },
    {
      kicker: "Hand-off", target: "spec-sec",
      title: "An agent-ready spec, from the graph",
      todo: <>Click <b>Generate the spec ▸</b>. It appears in the labelled section.</>,
      after: <>Scroll the spec: the current requirement per ticket, with the decision behind it.</>,
      body: <>For a coding agent or a new teammate: the current requirement per ticket, with the decision behind it and what's stale, generated from graph context only.</>,
      action: { label: "Generate the spec", run: async () => { await specFor("feat_ticket_export_to_csv"); return { tone: "info", lines: ["Spec generated below."] }; } },
    },
    {
      kicker: "For your company", target: "top",
      title: "What it takes to run this on your team",
      todo: <>That's the tour. Keep using this sandbox: every button on the page works.</>,
      body: <ul className="tour__list">
        <li><b>Connects:</b> Slack, Discord, GitHub, your ticket tracker and docs; ran live on a real Slack workspace and GitHub repo.</li>
        <li><b>Scales:</b> 100 of 100 planted drifts found in a 22,940-node graph; whole-graph drift query ~39 ms.</li>
        <li><b>Safe by design:</b> the agent's tools are read-only; only a ticket's owner can approve a change; restricted docs never reach people (or the model) who may not see them; every answer shows its graph path.</li>
        <li><b>Precision first:</b> a false alert is spam, so it alerts rarely and is right when it does.</li>
        <li><b>Runs anywhere:</b> one Docker image (FalkorDB + API + dashboard); works without an LLM, better with one.</li>
      </ul>,
    },
  ], [announce, focusOn, refresh, specFor]);

  const step = steps[i];
  const go = useCallback((n: number) => {
    const k = Math.max(0, Math.min(steps.length - 1, n));
    setOut(null); setDone(false); setI(k); setMin(false); remember("tour-step", String(k));
  }, [steps.length, setMin]);

  // a link like /?app&org=demo&tour=1#impact starts the tour at that section's step; coming back to the demo
  // without a fresh start picks the tour up where it was
  useEffect(() => {
    const at = steps.findIndex((s) => s.target === location.hash.slice(1));
    const saved = Number(remember("tour-step"));
    if (at > 0) setI(at);
    else if (!tourOn() && saved > 0 && saved < steps.length) setI(saved);
    if (tourOn()) remember("tour-step", String(Math.max(0, at)));
  }, [steps]);

  // scroll to and highlight the step's section
  useEffect(() => {
    if (ready !== "ready" || !step.target) return;
    const el = document.getElementById(step.target);
    if (!el) return;
    scrollToEl(el, -90);
    el.classList.add("tour-focus");
    setAcc(getComputedStyle(el).getPropertyValue("--acc").trim());
    // a label on the section itself: this is where to look
    const tag = document.createElement("span");
    tag.className = "tour-tag mono";
    tag.textContent = `Tour · step ${i + 1} · look here`;
    el.prepend(tag);
    return () => { el.classList.remove("tour-focus"); tag.remove(); };
  }, [i, ready, step.target]);

  /** Run a step's action; its answer is shown highlighted in the tour, and the section it came from pulses. */
  const run = async (fn: () => Promise<Out>) => {
    setBusy(true);
    try { setOut(await fn()); } catch (e) { setOut({ tone: "warn", lines: [(e as Error).message] }); } finally { setBusy(false); }
    setOutKey((k) => k + 1);
    setDone(true);
    const el = step.target && document.getElementById(step.target);
    if (el) { el.classList.remove("tour-hit"); void el.offsetWidth; el.classList.add("tour-hit"); setTimeout(() => el.classList.remove("tour-hit"), 2600); }
    setTimeout(() => answer.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }), 80);
  };

  const total = steps.length;
  const hasAction = !!(step.action || step.extra);
  // the next thing to press glows: the step's action until it has run, then Next
  const nextHot = ready === "ready" && (!hasAction || done);
  const accStyle = acc ? ({ "--acc": acc } as CSSProperties) : undefined;

  if (min) {
    return (
      <motion.button className="tour-pill mono" style={accStyle} onClick={() => setMin(false)}
        initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} aria-label="Open the product tour">
        <i aria-hidden />Product tour · {ready === "ready" ? `${i + 1} / ${total}` : "setting up"}<b>Resume ▴</b>
      </motion.button>
    );
  }

  return (
    <motion.aside className="tour" style={accStyle} initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} role="dialog" aria-label="Product tour">
      <header className="tour__head">
        <span className="mono tour__k">Product tour · {ready === "ready" ? <><b>{String(i + 1).padStart(2, "0")}</b> / {total}</> : "sandbox"}</span>
        <span className="tour__ctl">
          <button onClick={() => setMin(true)} aria-label="Fold the tour away" title="Fold the tour away (it stays in the corner)">▾</button>
        </span>
      </header>
      {ready === "ready" && <div className="tour__prog" aria-hidden><span style={{ transform: `scaleX(${(i + 1) / total})` }} /></div>}
      {ready === "setting-up" ? (
        <p className="tour__body">Setting up a fresh private copy of the demo company for your tour…</p>
      ) : ready === "failed" ? (
        <p className="tour__body">The sandbox couldn't be created: {err}</p>
      ) : (
        <AnimatePresence mode="wait">
          <motion.div key={i} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }} transition={{ duration: 0.25 }}>
            <span className="mono tour__kicker">{step.kicker}</span>
            <h3 className="tour__title">{step.title}</h3>
            <motion.div key={done ? "after" : "todo"} className={`tour__do ${done ? "tour__do--after" : ""}`} role="status"
              initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
              <span className="tour__do-k mono">{done ? "Now look" : hasAction ? "Your move" : "Look"}</span>
              <p>{done && step.after ? step.after : step.todo}</p>
            </motion.div>
            {hasAction && (
              <div className="tour__actions">
                {step.action && <button className={`btn btn--sm ${done ? "" : "tour__hot"}`} disabled={busy} onClick={() => void run(step.action!.run)}>{busy ? "Working…" : step.action.label} ▸</button>}
                {step.extra?.map((x) => <button key={x.label} className={`btn btn--ghost btn--sm ${!done && !step.action ? "tour__hot" : ""}`} disabled={busy} onClick={() => void run(x.run)}>{x.label}</button>)}
              </div>
            )}
            {out && (
              <motion.div key={outKey} ref={answer} className={`tour__out tour__out--${out.tone || "info"}`}
                initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}>
                <span className="tour__ans mono">{out.tone === "ok" ? "Done · from the graph" : out.tone === "warn" ? "Answer · from the graph" : "Answer"}</span>
                {out.lines.filter(Boolean).map((l, k) => <div key={k}>{highlight(l)}</div>)}
              </motion.div>
            )}
            <details className="tour__why">
              <summary className="mono">Why it matters</summary>
              <div className="tour__body">{step.body}</div>
            </details>
          </motion.div>
        </AnimatePresence>
      )}
      {ready === "ready" && (
        <footer className="tour__foot">
          <button className="btn btn--ghost btn--sm" disabled={i === 0} onClick={() => go(i - 1)}>← Back</button>
          <span className="tour__dots" aria-hidden>{steps.map((_, k) => <i key={k} className={k === i ? "on" : k < i ? "past" : ""} onClick={() => go(k)} />)}</span>
          {i < total - 1
            ? <button className={`btn btn--sm ${nextHot ? "tour__hot" : ""}`} onClick={() => go(i + 1)}>Next →</button>
            : <button className="btn btn--sm" onClick={() => setMin(true)}>Explore on your own →</button>}
        </footer>
      )}
    </motion.aside>
  );
}
