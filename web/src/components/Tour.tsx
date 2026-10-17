import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ORG, type Drift } from "../lib/api";
import { useBrain } from "../lib/brain";
import { scrollToEl } from "../lib/fx";

/** The product tour: a guided walk through every feature on a private sandbox company (its own graph, `?org=tour`),
    where each "Do it" button performs the real action through the real API. Opened from the hero with ?org=tour&tour=1. */
export const TOUR_ORG = "tour";
export const TOUR_HREF = `/?org=${TOUR_ORG}&tour=1`;
export const tourActive = () => typeof window !== "undefined" && new URLSearchParams(window.location.search).has("tour") && ORG === TOUR_ORG;

const DECISION = "Decision: the export button must also offer a JSON download, BD-102.";

type Out = { tone?: "ok" | "warn" | "info"; lines: ReactNode[] };
type Step = {
  kicker: string; title: string; body: ReactNode;
  target?: string;                         // element id or selector to scroll to and highlight
  action?: { label: string; run: () => Promise<Out> };
  extra?: { label: string; run: () => Promise<Out> }[];
};

const latestDrift = (rows: Drift[], ticket: string) => rows.filter((d) => d.ticket === ticket).sort((a, b) => b.changed_ms - a.changed_ms)[0];

export function Tour() {
  const { refresh, focusOn, specFor, announce } = useBrain();
  const [ready, setReady] = useState<"setting-up" | "ready" | "failed">("setting-up");
  const [err, setErr] = useState<string | null>(null);
  const [i, setI] = useState(0);
  const [out, setOut] = useState<Out | null>(null);
  const [busy, setBusy] = useState(false);
  const [min, setMin] = useState(false);

  // a fresh sandbox company every time the tour starts
  useEffect(() => {
    api.bootstrap(TOUR_ORG).then(() => refresh()).then(() => setReady("ready")).catch((e) => { setErr((e as Error).message); setReady("failed"); });
  }, [refresh]);

  const steps: Step[] = useMemo(() => [
    {
      kicker: "Welcome", target: "top",
      title: "A company brain that catches decisions that never shipped",
      body: <>This is <b>Brightdesk</b>, a sandbox software company: 8 people, Slack and Discord chat, tickets, GitHub PRs and docs, all in one FalkorDB graph. It's a private copy just for this tour, so <b>every “Do it” button does the real thing</b>.</>,
    },
    {
      kicker: "The problem", target: "drift",
      title: "Two decisions made in chat never reached the work",
      body: <>Each card is a <b>drift</b>: someone with the right to change a ticket decided something new in chat, and nothing newer replaced it, no PR shipped it, nobody kept the old scope. The card shows what the ticket still says, what was decided, who, where, and the PRs and docs still on the old version.</>,
    },
    {
      kicker: "Live monitoring", target: "drift",
      title: "A decision lands in Slack",
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
      body: <>The graph path behind the alert: <span className="mono">person → message → requirement → ticket → feature</span>, plus the PR and doc still on the old version. Nobody has to trust the bot; they can read why it fired. In this company the deciding messages never name a ticket: threads, people and time connect them.</>,
      action: { label: "Show the path in the graph", run: async () => { focusOn("feat_ticket_export_to_csv"); return { tone: "info", lines: ["The lit path is the evidence. Click any node for its text."] }; } },
    },
    {
      kicker: "Impact analysis", target: "impact",
      title: "“If we delay Project Alpha by two weeks…”",
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
      kicker: "Ask the company brain", target: "ask",
      title: "Questions a team actually asks",
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
          return { tone: "info", lines: [<i key="q">“{q}”</i>, <pre key="a" className="tour__pre">{r.answer.split("\n\nEvidence:")[0].slice(0, 520)}</pre>,
            <span key="e" className="mono tour__dim">{r.engine === "rules" ? "rules agent, no LLM" : r.engine} · {r.tool_calls.length} tool call{r.tool_calls.length === 1 ? "" : "s"}</span>] };
        },
      })),
    },
    {
      kicker: "Stays current", target: "docs-sec",
      title: "A doc changes: only what changed is re-embedded",
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
      body: <>A confidential doc with salary bands is shared with <b>leads and HR</b> only. Ask the same question as different people: access is checked in the vector query, in every agent tool and on every API response, so a regular employee gets nothing, not even a hint that the doc exists.</>,
      extra: ([["Ask as Zara (QA)", "zara"], ["Ask as Maya (lead)", "maya"], ["Ask anonymously", null]] as [string, string | null][]).map(([label, who]) => ({
        label,
        run: async () => {
          const r = await api.ask("What is everyone's salary?", who);
          return { tone: who === "maya" ? "ok" : "warn", lines: [<i key="q">{who || "anonymous"}: “What is everyone's salary?”</i>,
            <pre key="a" className="tour__pre">{r.answer.split("\n\nEvidence:")[0].slice(0, 360)}</pre>] };
        },
      })),
    },
    {
      kicker: "Sprint retro", target: "retro-sec",
      title: "What we decided, what we shipped, where they diverge",
      body: <>Every sprint, from the graph: decisions made in chat, PRs merged, and the ones that diverged, each line with its source. No status meeting needed to find out what slipped.</>,
    },
    {
      kicker: "Risk", target: "coverage",
      title: "Where the company is fragile",
      body: <>Knowledge held by one person (bus factor), PRs with no ticket, closed tickets with no code, tickets nobody ever discussed. The same graph, read for gaps.</>,
    },
    {
      kicker: "Hand-off", target: "spec-sec",
      title: "An agent-ready spec, from the graph",
      body: <>For a coding agent or a new teammate: the current requirement per ticket, with the decision behind it and what's stale, generated from graph context only.</>,
      action: { label: "Generate the spec", run: async () => { await specFor("feat_ticket_export_to_csv"); return { tone: "info", lines: ["Spec generated below."] }; } },
    },
    {
      kicker: "For your company", target: "top",
      title: "What it takes to run this on your team",
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
  const go = useCallback((n: number) => { setOut(null); setI(Math.max(0, Math.min(steps.length - 1, n))); setMin(false); }, [steps.length]);

  // scroll to and highlight the step's section
  useEffect(() => {
    if (ready !== "ready" || !step.target) return;
    const el = document.getElementById(step.target);
    if (!el) return;
    scrollToEl(el, -90);
    el.classList.add("tour-focus");
    return () => el.classList.remove("tour-focus");
  }, [i, ready, step.target]);

  const run = async (fn: () => Promise<Out>) => {
    setBusy(true);
    try { setOut(await fn()); } catch (e) { setOut({ tone: "warn", lines: [(e as Error).message] }); } finally { setBusy(false); }
  };

  return (
    <motion.aside className={`tour ${min ? "tour--min" : ""}`} initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} role="dialog" aria-label="Product tour">
      <header className="tour__head">
        <span className="mono tour__k">Product tour · {ready === "ready" ? `${i + 1} / ${steps.length}` : "sandbox"}</span>
        <span className="tour__ctl">
          <button onClick={() => setMin((m) => !m)} aria-label={min ? "Expand" : "Minimise"}>{min ? "▴" : "▾"}</button>
          <a href="/" aria-label="Exit the tour">✕</a>
        </span>
      </header>
      {!min && (ready === "setting-up" ? (
        <p className="tour__body">Setting up a private sandbox company for you…</p>
      ) : ready === "failed" ? (
        <p className="tour__body">The sandbox couldn't be created: {err}</p>
      ) : (
        <AnimatePresence mode="wait">
          <motion.div key={i} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }} transition={{ duration: 0.25 }}>
            <span className="mono tour__kicker">{step.kicker}</span>
            <h3 className="tour__title">{step.title}</h3>
            <div className="tour__body">{step.body}</div>
            {(step.action || step.extra) && (
              <div className="tour__actions">
                {step.action && <button className="btn btn--sm" disabled={busy} onClick={() => void run(step.action!.run)}>{busy ? "Working…" : step.action.label} ▸</button>}
                {step.extra?.map((x) => <button key={x.label} className="btn btn--ghost btn--sm" disabled={busy} onClick={() => void run(x.run)}>{x.label}</button>)}
              </div>
            )}
            {out && <div className={`tour__out tour__out--${out.tone || "info"}`}>{out.lines.map((l, k) => <div key={k}>{l}</div>)}</div>}
          </motion.div>
        </AnimatePresence>
      ))}
      {!min && ready === "ready" && (
        <footer className="tour__foot">
          <button className="btn btn--ghost btn--sm" disabled={i === 0} onClick={() => go(i - 1)}>← Back</button>
          <span className="tour__dots" aria-hidden>{steps.map((_, k) => <i key={k} className={k === i ? "on" : ""} onClick={() => go(k)} />)}</span>
          {i < steps.length - 1
            ? <button className="btn btn--sm" onClick={() => go(i + 1)}>Next →</button>
            : <a className="btn btn--sm" href="/">Open the live app</a>}
        </footer>
      )}
    </motion.aside>
  );
}
