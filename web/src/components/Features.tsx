import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, type Retro } from "../lib/api";
import { useBrain } from "../lib/brain";
import { useStill } from "../lib/fx";
import { gsap, useGSAP } from "../lib/gsap";
import { DEMO_HREF } from "../lib/routes";
import { day } from "../lib/ui";

/* What the product does, one page per feature. On wide screens the section pins and the pages slide in
   horizontally as you scroll down, as a 3D cover-flow: each page's screen swings in from the right in depth, faces
   you at the centre and swings away to the left. On narrow screens or with reduced motion they simply stack. */

function useWide() {
  const q = "(min-width: 861px)";
  const [wide, setWide] = useState(() => typeof window !== "undefined" && matchMedia(q).matches);
  useEffect(() => {
    const m = matchMedia(q);
    const on = () => setWide(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return wide;
}

const pad = (n: number) => String(n).padStart(2, "0");

function Screen({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <div className="screen">
      <div className="screen__bar mono"><span>{title}</span>{right && <span>{right}</span>}</div>
      <div className="screen__body">{children}</div>
    </div>
  );
}

function DetectVis() {
  const { drift } = useBrain();
  const d = drift[0];
  return (
    <Screen title="Open drift" right={<span className="tag tag--inv">{drift.length} open</span>}>
      <div className="vs" style={{ margin: 0 }}>
        <div className="vs__old">
          <span className="mono vs__k">{d ? d.ticket : "BD-101"} still says</span>
          <p>{d ? d.ticket_text : "Export the last 30 days of tickets to CSV."}</p>
        </div>
        <div className="vs__new">
          <span className="mono vs__k">Decided in chat</span>
          <p>{d ? d.requirement_text : "Any range up to 12 months, not 30 days."}</p>
          <div className="vs__who mono">{d ? `${d.changed_by} · ${d.source} #${d.channel} · ${day(d.changed_at)}` : "maya · slack #support-escalations"}</div>
        </div>
      </div>
      {d && <div className="mono muted">{d.stale_prs.length} stale PR · {d.stale_docs.length} stale doc · nothing implements the new version</div>}
    </Screen>
  );
}

const CYPHER = (
  <pre className="code">
    <b>MATCH</b> (m:Message)-[:CHANGES]-&gt;(r:Requirement){"\n"}
    {"      "}-[:AMENDS]-&gt;(t:Ticket)-[:ABOUT]-&gt;(f:Feature){"\n"}
    <b>WHERE NOT</b> (r)&lt;-[:SUPERSEDES]-(:Requirement)  <i>// still newest</i>{"\n"}
    {"  "}<b>AND NOT</b> (:PullRequest)-[:IMPLEMENTS]-&gt;(r)  <i>// nothing shipped it</i>{"\n"}
    {"  "}<b>AND NOT</b> (:Decision)-[:DISMISSES]-&gt;(r)     <i>// nobody kept the old</i>{"\n"}
    <b>RETURN</b> f, t, r, m  <i>// the path is the evidence</i>
  </pre>
);

function ActVis() {
  return (
    <Screen title="#engineering · thread" right="Slack / Discord">
      <div className="convo">
        <div><span>zara</span><p>@Drift Monitor fix it</p></div>
        <div className="bot"><span>bot</span><p>Only BD-102's owners can decide this: Maya Chen or Kenji Watanabe. zara can't.</p></div>
        <div><span>maya</span><p>@Drift Monitor plan</p></div>
        <div className="bot"><span>bot</span><p>1. Write the decision into BD-102<br />2. Change PR #7 to the new requirement → kenji<br />3. Update DOC-1 → maya</p></div>
        <div><span>maya</span><p>@Drift Monitor fix it</p></div>
        <div className="bot"><span>bot</span><p>Done. BD-102 carries the decision. Follow-ups: T-1 → kenji, T-2 → maya</p></div>
      </div>
    </Screen>
  );
}

function ListenVis() {
  return (
    <Screen title="Live monitor" right="per message">
      <div className="convo"><div><span>maya</span><p>Decision: the export button must also offer a JSON download, BD-102.</p></div></div>
      <div className="flow">
        <div><b>Ingest</b><small>message → graph</small></div>
        <div><b>Extract</b><small>is it a change?</small></div>
        <div><b>Resolve</b><small>feature · ticket</small></div>
        <div><b>Drift check</b><small>alert in thread</small></div>
      </div>
    </Screen>
  );
}

const TOOLS = ["list_features", "drift_for_feature", "decision_history", "feature_timeline", "who_knows", "decision_impact",
  "list_decisions", "how_connected", "feature_prs", "plan_fix", "follow_ups", "ticket_owners", "search_knowledge", "list_projects", "impact_of_delay"];

function AskVis() {
  return (
    <Screen title="Graph agent" right="GRAPH.RO_QUERY">
      <div className="q" style={{ justifySelf: "start" }}>How is Liam connected to PR #6?</div>
      <div className="mono muted">{TOOLS.length} read-only tools the agent can call</div>
      <div className="path">{TOOLS.map((t) => <span key={t} className="n">{t}</span>)}</div>
    </Screen>
  );
}

function ImpactVis() {
  return (
    <Screen title="What if Project Alpha slips 2 weeks?" right="graph traversal">
      <div className="minis">
        <div style={{ background: "var(--ink)", color: "var(--bg)" }}><b>6 Nov</b><small style={{ color: "#444" }}>new launch, was 23 Oct</small></div>
        <div><b>+3 d</b><small>Project Beta, blocked through BD-108 → BD-109</small></div>
        <div><b>−7 d</b><small>Acme's audit export misses its date</small></div>
      </div>
      <div className="path">
        <span className="n"><b>Client</b>acme</span><span className="r">&lt;-FOR-</span><span className="n"><b>Deliverable</b>acme-audit</span>
        <span className="r">-NEEDS-&gt;</span><span className="n"><b>Project</b>alpha</span>
      </div>
      <div className="mono muted">4 teams hit: Backend, Web, Product & Design, Customer Success</div>
    </Screen>
  );
}

function SyncVis() {
  return (
    <Screen title="DOC-1 · PRD — Ticket export" right="edited in Google Docs">
      <div className="chunks">
        <div className="chunk chunk--embedded" style={{ flexGrow: 395 }}><span>#0</span><small>re-embedded</small></div>
        <div className="chunk chunk--kept" style={{ flexGrow: 120 }}><span>#1</span><small>kept</small></div>
      </div>
      <div className="sync">
        <div><span>Vectors</span><p><b>1</b> re-embedded · <b>1</b> kept · <b>0</b> removed</p></div>
        <div><span>Graph edges</span><p className="sync__edges"><span className="tag">MENTIONS BD-101</span><span className="tag">MENTIONS BD-102</span><span className="tag tag--inv">+ MENTIONS BD-104</span></p></div>
        <div><span>Drift</span><p>No longer stale for BD-101</p></div>
      </div>
    </Screen>
  );
}

function ProtectVis() {
  return (
    <Screen title="Same question, two people" right="entity-level access">
      <div className="convo">
        <div><span>zara</span><p>What is everyone's salary?</p></div>
        <div className="bot"><span>bot</span><p>I don't have information on that you can access.</p></div>
        <div><span>maya</span><p>What is everyone's salary?</p></div>
        <div className="bot"><span>bot</span><p>From Compensation bands 2026 (DOC-5, by arjun): Senior Engineer: 120,000 to 155,000…</p></div>
      </div>
      <div className="mono muted">DOC-5 is shared with leads and HR. zara's request never receives it, so it can't leak.</div>
    </Screen>
  );
}

function RetroVis() {
  const { sprints, drift } = useBrain();
  const [r, setR] = useState<Retro | null>(null);
  useEffect(() => { if (sprints[0]) api.retro(sprints[0].id).then(setR).catch(() => undefined); }, [sprints]);
  const shipped = r ? r.decided.filter((d) => d.shipped_in.length).length : 0;
  return (
    <Screen title={r ? r.name : "Sprint retro"} right="from the graph">
      <div className="minis">
        <div><b>{r ? r.decided.length : "–"}</b><small>decided in chat</small></div>
        <div><b>{r ? shipped : "–"}</b><small>decisions shipped</small></div>
        <div style={{ background: "var(--ink)", color: "var(--bg)" }}><b>{r ? r.diverged.length : drift.length}</b><small style={{ color: "#444" }}>diverged</small></div>
      </div>
      <div className="mono muted">{r ? `${r.shipped.length} PRs merged · every line links to its source` : "Loading sprint…"}</div>
    </Screen>
  );
}

function RiskVis() {
  const { coverage: c } = useBrain();
  return (
    <Screen title="Coverage & risk" right="bus factor">
      {(c?.knowledge_risk || []).slice(0, 3).map((k) => (
        <div key={k.feature} className="meter">
          <span>{k.name}<small>{k.top_person}</small></span>
          <span className="bar"><span style={{ width: `${Math.round(k.top_share * 100)}%` }} /><i style={{ left: "50%" }} /></span>
          <span className="mono" style={{ textAlign: "right" }}>{Math.round(k.top_share * 100)}%</span>
        </div>
      ))}
      <div className="minis">
        <div><b>{c?.orphan_prs.length ?? "–"}</b><small>PRs, no ticket</small></div>
        <div><b>{c?.done_without_pr.length ?? "–"}</b><small>done, no PR</small></div>
        <div><b>{c?.undiscussed_tickets.length ?? "–"}</b><small>never discussed</small></div>
      </div>
    </Screen>
  );
}

const PANELS: { k: string; title: string; body: string; points: string[]; go: [string, string]; vis: () => ReactNode }[] = [
  { k: "Detect", title: "Catches decisions that never shipped.", go: ["drift", "See open drift"], vis: () => <DetectVis />,
    body: "An owner decides something new in chat. The ticket keeps the old text and the PR ships the old version. That gap is drift.",
    points: ["Reads Slack, Discord, tickets, GitHub and docs", "Links messages to tickets through threads, people and time", "Precision first: it alerts rarely, and is right when it does"] },
  { k: "Prove", title: "Every alert carries its graph path.", go: ["graph-sec", "Explore the graph"], vis: () => <Screen title="DRIFT query" right="Cypher">{CYPHER}</Screen>,
    body: "Drift is a time-ordered path question. One Cypher query finds every case, and the path it walks is the evidence.",
    points: ["Every version is its own Requirement, linked by SUPERSEDES", "Shortest causal paths with algo.SPpaths", "Nobody has to trust the bot: they can read why it fired"] },
  { k: "Listen", title: "Watches chat as it happens.", go: ["simulate", "Simulate a message"], vis: () => <ListenVis />,
    body: "Each new message runs the same pipeline the Slack and Discord bots use, and the alert lands in the thread within seconds.",
    points: ["Only a ticket's creator or assignee can change it from chat", "Cosmetic ticket edits don't clear drift", "Live updates stream to this page"] },
  { k: "Act", title: "Plans the fix and assigns it.", go: ["drift", "Approve a fix"], vis: () => <ActVis />,
    body: "It doesn't stop at the alert. The plan is a graph read: who wrote each stale PR and doc, who owns the ticket, who else to tell.",
    points: ["Only owners can approve, everyone else is refused", "Approving writes the decision into the ticket", "Follow-up tasks go to the right people and survive rebuilds"] },
  { k: "Ask", title: "Answers questions a team actually asks.", go: ["ask", "Ask the graph"], vis: () => <AskVis />,
    body: "Who owns this? Who knows the most? How are these two connected? The agent picks graph tools and answers from their rows.",
    points: ["Read-only tools, no free-form queries", "Every answer shows its steps and paths", "Says \"not in the graph\" instead of guessing"] },
  { k: "Impact", title: "Sees what a delay ripples into.", go: ["impact", "Run a what-if"], vis: () => <ImpactVis />,
    body: "If a launch slips two weeks, the graph walks from the project to every ticket it blocks, the projects waiting on them, the client deliverables that need them and the teams doing the work.",
    points: ["Downstream projects through BLOCKS chains, at any depth", "Client deliverables that miss or get tight", "A map per feature: every spec, who introduced it, the work on it"] },
  { k: "Sync", title: "Stays current when a doc changes.", go: ["docs-sec", "Edit a doc"], vis: () => <SyncVis />,
    body: "Docs are chunks in a FalkorDB vector index, one hop from their authors and tickets. An edit re-embeds only the chunks that changed, and the doc's links to tickets follow the new text.",
    points: ["Google Drive change feed and push webhook", "Unchanged chunks keep their vectors", "Ticket links added and removed with the text, so stale flags stay right"] },
  { k: "Protect", title: "Answers only what you may see.", go: ["docs-sec", "Ask as someone else"], vis: () => <ProtectVis />,
    body: "A doc can be shared with groups or people, from its metadata or its Google Drive sharing. Ask for salaries as a regular employee and the agent has nothing to say, not even that the doc exists.",
    points: ["Filtered inside the vector query", "Every agent tool drops what you can't see before the model reads it", "Every API response is checked again"] },
  { k: "Review", title: "Shows what the sprint decided and shipped.", go: ["retro-sec", "Open the retro"], vis: () => <RetroVis />,
    body: "Decisions made in chat, PRs merged, and where the two diverge. No status meeting needed to find out what slipped.",
    points: ["Each line links to its message or PR", "Carries open drift over from earlier sprints", "Generates an agent-ready spec per feature"] },
  { k: "Risk", title: "Finds where the company is fragile.", go: ["coverage", "See the risks"], vis: () => <RiskVis />,
    body: "The same graph, read for gaps: knowledge held by one person, work nobody linked, tickets nobody discussed.",
    points: ["Bus factor per feature", "PRs with no ticket, tickets with no PR", "Possible decisions by people who don't own the ticket"] },
];

export function Features() {
  const still = useStill();
  const wide = useWide();
  const on = wide && !still;
  const section = useRef<HTMLElement>(null);
  const track = useRef<HTMLDivElement>(null);
  const bar = useRef<HTMLSpanElement>(null);
  const [idx, setIdx] = useState(0);
  const idxRef = useRef(0);

  useGSAP(() => {
    const el = section.current, tr = track.current;
    if (!el || !tr) return;
    const panels = gsap.utils.toArray<HTMLElement>(".hs__panel", tr);
    if (!on) {
      if (still) return;
      panels.forEach((p) => gsap.from(p.children, { opacity: 0, y: 40, stagger: 0.12, scrollTrigger: { trigger: p, start: "top 85%", once: true } }));
      return;
    }
    const dist = () => tr.scrollWidth - window.innerWidth;
    const n = panels.length;
    const slide = gsap.to(tr, {
      x: () => -dist(), ease: "none",
      scrollTrigger: {
        trigger: el, pin: true, start: "top top", end: () => `+=${dist()}`, scrub: 0.7, invalidateOnRefresh: true, anticipatePin: 1,
        snap: { snapTo: 1 / (n - 1), duration: { min: 0.2, max: 0.6 }, delay: 0.08, ease: "power2.inOut" },
        onUpdate: (self) => {
          if (bar.current) bar.current.style.transform = `scaleX(${self.progress})`;
          const i = Math.min(n - 1, Math.round(self.progress * (n - 1)));
          if (i !== idxRef.current) { idxRef.current = i; setIdx(i); }
        },
      },
    });
    // per page: swing in from the right in depth, face the viewer at the centre, swing out to the left
    panels.forEach((p) => {
      const vis = p.querySelector(".hs__vis"), copy = p.querySelector(".hs__copy");
      const tl = gsap.timeline({ scrollTrigger: { trigger: p, containerAnimation: slide, start: "left right", end: "right left", scrub: true } });
      tl.fromTo(vis, { rotationY: -42, z: -320, x: 60, opacity: 0.25 }, { rotationY: 0, z: 0, x: 0, opacity: 1, ease: "none", duration: 1 }, 0)
        .fromTo(copy, { x: 140, opacity: 0 }, { x: 0, opacity: 1, ease: "none", duration: 0.8 }, 0.2)
        .to(vis, { rotationY: 38, z: -320, x: -60, opacity: 0.2, ease: "none", duration: 1 }, 1)
        .to(copy, { x: -120, opacity: 0, ease: "none", duration: 0.8 }, 1);
    });
  }, { dependencies: [on, still], scope: section, revertOnUpdate: true });

  return (
    <section ref={section} id="features" className={`hs ${on ? "hs--on" : ""}`} aria-label="What it does" data-i={idx}>
      <div className="hs__sticky">
        <div className="hs__top mono">
          <span>04 — Features</span>
          {on && <span className="hs__dots" aria-hidden>{PANELS.map((_, i) => <i key={i} className={i === idx ? "on" : ""} />)}</span>}
          <span className="hs__count">{on ? <><b>{pad(idx + 1)}</b> / {pad(PANELS.length)} · {PANELS[idx].k}</> : `${PANELS.length} features`}</span>
        </div>
        <div ref={track} className="hs__track">
          {PANELS.map((p, i) => (
            <article key={p.k} className="hs__panel" aria-label={p.k}>
              <div className="hs__copy">
                <div className="hs__idx"><b>{pad(i + 1)}</b><span>—</span><span>{p.k}</span></div>
                <h2>{p.title}</h2>
                <p>{p.body}</p>
                <ul>{p.points.map((x) => <li key={x}>{x}</li>)}</ul>
                <a className="btn btn--ghost btn--sm hs__go" href={`${DEMO_HREF}#${p.go[0]}`}>{p.go[1]} →</a>
              </div>
              <div className="hs__vis">{p.vis()}</div>
            </article>
          ))}
        </div>
        {on && <div className="hs__bar"><span ref={bar} style={{ transform: "scaleX(0)" }} /></div>}
      </div>
    </section>
  );
}
