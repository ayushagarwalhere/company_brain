import { AnimatePresence, motion, useInView } from "framer-motion";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { api, type AskResult } from "../lib/api";
import { useBrain } from "../lib/brain";
import { useStill } from "../lib/fx";
import { DEMO_HREF } from "../lib/routes";
import { plural } from "../lib/ui";
import { AnswerGraph } from "./AnswerGraph";
import { Footer } from "./Chrome";
import { Connect } from "./Connect";
import { Features } from "./Features";
import { fadeIn, gsap, moving, revealHeading, scrambleIn, SplitText, useGSAP, WIDE } from "../lib/gsap";
import { CountUp, EASE } from "./Motion";
import { Sources } from "./Panels";
import { TryRepo } from "./TryRepo";

/* The overview at "/": the pain, the idea, the product working live on the demo graph, what it's worth and what
   it's built on. Every "Open the demo" goes to the app on a private sandbox company. */

const CHAPTERS = [["pain", "The pain"], ["vision", "The graph"], ["demo", "Live demo"], ["try", "Your repo"], ["features", "Features"], ["value", "Value"], ["stack", "Stack"], ["connect", "Connect"]];

function LandingNav() {
  const [line, setLine] = useState(false);
  const [active, setActive] = useState("");
  useEffect(() => {
    const onScroll = () => setLine(window.scrollY > 24);
    onScroll();
    addEventListener("scroll", onScroll, { passive: true });
    const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && setActive(e.target.id)), { rootMargin: "-45% 0px -50% 0px" });
    CHAPTERS.forEach(([id]) => { const el = document.getElementById(id); if (el) io.observe(el); });
    return () => { removeEventListener("scroll", onScroll); io.disconnect(); };
  }, []);
  return (
    <nav className={`nav ${line ? "nav--line" : ""}`}>
      <a className="brand" href="#top" aria-label="Drift Monitor overview"><span className="brand__mark" />Drift Monitor</a>
      <div className="nav__links mono">
        {CHAPTERS.map(([id, label]) => <a key={id} href={`#${id}`} className={active === id ? "active" : ""}>{label}</a>)}
      </div>
      <div className="nav__right">
        <a className="btn btn--ghost btn--sm" href="#connect">Connect Slack / Discord</a>
        <a className="btn btn--sm" href={DEMO_HREF}>Open the demo →</a>
      </div>
    </nav>
  );
}

/** A full-width chapter: "01 — The pain" label, big statement, then the body. */
function Chapter({ id, n, k, title, intro, children }: { id: string; n: string; k: string; title: ReactNode; intro?: ReactNode; children: ReactNode }) {
  const ref = useRef<HTMLElement>(null);
  useGSAP(() => {
    const el = ref.current;
    if (!el || !moving()) return;
    scrambleIn(el.querySelector(".hs__idx .hs__k"));
    revealHeading(el.querySelector(".ch__head h2"), { by: "lines" });
    gsap.from(el.querySelectorAll(".ch__head p, .hs__idx b"), { opacity: 0, y: 22, stagger: 0.1, delay: 0.2, scrollTrigger: { trigger: el.querySelector(".ch__head"), start: "top 85%", once: true } });
  }, { scope: ref });
  return (
    <section className="ch" id={id} ref={ref}>
      <div className="ch__head">
        <div className="hs__idx"><b>{n}</b><span>—</span><span className="hs__k">{k}</span></div>
        <h2>{title}</h2>
        {intro && <p>{intro}</p>}
      </div>
      <div className="ch__body">{children}</div>
    </section>
  );
}

/** The headline spans the whole screen: one font size, set so its longest line runs edge to edge. */
function useFullWidthTitle(ref: RefObject<HTMLElement>) {
  useLayoutEffect(() => {
    const h1 = ref.current?.querySelector<HTMLElement>(".hero__title");
    if (!h1) return;
    const fit = () => {
      h1.style.fontSize = "100px";
      const widest = Math.max(0, ...[...h1.querySelectorAll<HTMLElement>(".line")].map((l) => l.scrollWidth));
      if (widest) h1.style.fontSize = `${Math.floor((h1.clientWidth / widest) * 100 * 0.99)}px`;
    };
    fit();
    void document.fonts?.ready.then(fit);  // re-measure once Geist has loaded
    addEventListener("resize", fit);
    return () => removeEventListener("resize", fit);
  }, [ref]);
}

function LandingHero() {
  const { stats, drift } = useBrain();
  const sum = (xs?: { n: number }[]) => (xs || []).reduce((a, x) => a + x.n, 0);
  const n = (l: string) => stats?.nodes.find((x) => x.label === l)?.n ?? 0;
  const figures: [string, number, boolean?][] = [
    ["Graph nodes", sum(stats?.nodes)], ["Relationships", sum(stats?.relationships)], ["Messages read", n("Message")], ["Open drift right now", drift.length, true],
  ];
  const ref = useRef<HTMLElement>(null);
  useFullWidthTitle(ref);
  useGSAP(() => {
    const el = ref.current;
    if (!el || !moving()) return;
    const h1 = el.querySelector("h1")!, lines = h1.querySelectorAll(".line");
    const split = SplitText.create(lines, { type: "words,chars", mask: "words" });
    gsap.from(split.chars, { yPercent: 110, opacity: 0, stagger: 0.022, duration: 1, ease: "power3.out", delay: 0.1 });
    gsap.from(el.querySelectorAll(".eyebrow, .hero__sub, .lede, .hero__cta, .hero__stats"), { opacity: 0, y: 26, stagger: 0.08, delay: 0.65 });
    if (matchMedia("(pointer: fine)").matches) {
      const rx = gsap.quickTo(h1, "rotationX", { duration: 0.8, ease: "power3" }), ry = gsap.quickTo(h1, "rotationY", { duration: 0.8, ease: "power3" });
      gsap.set(h1, { transformPerspective: 900 });
      const move = (e: PointerEvent) => { rx((0.5 - e.clientY / innerHeight) * 9); ry((e.clientX / innerWidth - 0.5) * 12); };
      el.addEventListener("pointermove", move);
      return () => el.removeEventListener("pointermove", move);
    }
  }, { scope: ref });
  return (
    <header className="hero" id="top" ref={ref}>
     <div className="hero__3d">
      <div className="eyebrow">Company Brain · a context graph on FalkorDB</div>
      <h1 className="hero__title" aria-label="The graph that runs enterprise.">
        <span className="line" aria-hidden>The graph that</span>
        <span className="line dim" aria-hidden>runs enterprise.</span>
      </h1>
      <p className="hero__sub">“Where was that decided?” <span>One question, answered from a single graph of your chat, tickets, code and docs.</span></p>
      <div>
        <p className="lede">
          Your company's knowledge is spread across chat, tickets, code and docs, and none of them talk to each other.
          Drift Monitor connects them into one graph, so an agent can answer questions that span all four, and catch the
          decisions that never made it into the work.
        </p>
        <div className="hero__cta">
          <a className="btn" href={DEMO_HREF}>Open the demo →</a>
          <a className="btn btn--ghost" href="#try">Try it on your repo ↓</a>
          <a className="btn btn--ghost" href="#pain">How it works ↓</a>
          <a className="btn btn--ghost" href="#connect">Connect Slack or Discord</a>
        </div>
      </div>
      <dl className="hero__stats">
        {figures.map(([label, value, hot], i) => (
          <div key={label} className={hot && value ? "hot" : ""}><dt>{label}</dt><dd><CountUp value={value} delay={0.9 + i * 0.1} /></dd></div>
        ))}
      </dl>
     </div>
    </header>
  );
}

/** A band of what it does, on an endless loop under the nav. Hovering pauses it; reduced motion keeps it still. */
const TICKER: [string, string][] = [
  ["Drift detection", "--c-coral"], ["Slack → doc → ticket → HR in one answer", "--c-violet"], ["Live corporate stream", "--c-pink"], ["Company map", "--c-cyan"], ["Every alert with its graph path", "--c-blue"],
  ["Slack · Discord · GitHub · Jira · Docs", "--c-green"], ["What-if impact analysis", "--c-amber"], ["Only owners approve changes", "--c-coral"],
  ["Docs re-embedded chunk by chunk", "--c-cyan"], ["Answers only what you may see", "--c-cyan"], ["Sprint retro: decided vs shipped", "--c-pink"],
  ["Bus-factor risk", "--c-yellow"], ["39 ms drift query on FalkorDB", "--c-amber"],
];

function Marquee() {
  const row = TICKER.map(([t, c]) => <span key={t} style={{ ["--acc" as string]: `var(${c})` }}><i aria-hidden />{t}</span>);
  return (
    <div className="marquee mono" aria-label={TICKER.map(([t]) => t).join(", ")}>
      <div className="marquee__track" aria-hidden>
        <div className="marquee__row">{row}</div>
        <div className="marquee__row">{row}</div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- 01 the pain */

const SILOS = [
  { tool: "Slack · Discord", what: "Where decisions happen", item: "maya · #support-escalations · Sep 22", text: "“Decision: the export must support any custom date range up to 12 months (not a fixed 30 days)…”", state: "The decision", hot: true },
  { tool: "Jira · Linear", what: "Where work is tracked", item: "BD-101 · Ticket export", text: "“Admins can export tickets created in the last 30 days as a CSV file.”", state: "Never updated" },
  { tool: "Drive · Notion", what: "Where specs live", item: "DOC-1 · PRD — Ticket export", text: "“Admins can download tickets created in the last 30 days as a CSV file.”", state: "Still the old spec" },
  { tool: "GitHub", what: "Where it ships", item: "PR #6 · CSV export endpoint", text: "Merged Sep 25, three days after the decision, implementing the 30-day version.", state: "Shipped the old version" },
];

function Pain() {
  const ref = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    const el = ref.current;
    if (!el || !moving()) return;
    const wrap = el.querySelector<HTMLElement>(".silos")!, cards = gsap.utils.toArray<HTMLElement>(".silo", wrap);
    const mm = gsap.matchMedia();
    // the four tools start stacked in the middle, one behind the other, and spread out to their own places as you
    // scroll: one piece of the truth each
    mm.add(WIDE, () => {
      // offsets come from layout (offsetLeft), not from the moving boxes, so a refresh mid-scroll stays right
      const toCentre = (i: number, c: HTMLElement) => wrap.offsetWidth / 2 - (c.offsetLeft + c.offsetWidth / 2) + (i - 1.5) * 22;
      gsap.from(cards, {
        x: (i, c) => toCentre(i, c as HTMLElement), y: (i) => 70 - i * 10, z: (i) => -i * 110, rotationY: (i) => -28 + i * 5, rotationZ: (i) => (1.5 - i) * 3,
        scale: 0.94, ease: "none", stagger: 0,
        scrollTrigger: { trigger: wrap, start: "top 92%", end: "top 28%", scrub: 1, invalidateOnRefresh: true },
      });
    });
    mm.add("(max-width: 860px)", () => { fadeIn(cards, wrap, { stagger: 0.1 }); });
    fadeIn(el.querySelectorAll(".costs > div"), el.querySelector(".costs"));
  }, { scope: ref });
  return (
    <Chapter id="pain" n="01" k="The pain" title={<>Every tool holds a piece of the truth. <span className="muted">None holds all of it.</span></>}
      intro="A decision gets made in a thread. The ticket, the spec and the code never hear about it. Weeks later someone asks “where was that decided?” and nobody can find it. This is a real case from the demo company:">
     <div ref={ref}>
      <div className="silos">
        {SILOS.map((s) => (
          <div key={s.tool} className={`silo ${s.hot ? "silo--hot" : ""}`}>
            <span className="mono silo__tool">{s.tool}</span>
            <small>{s.what}</small>
            <div className="silo__card">
              <span className="mono muted">{s.item}</span>
              <p>{s.text}</p>
            </div>
            <span className={`tag ${s.hot ? "tag--inv" : "tag--dash"}`}>{s.state}</span>
          </div>
        ))}
      </div>
      <div className="costs">
        {[
          ["Hours lost to searching", "Which thread decided this? Which doc is current? People ask around instead of building."],
          ["Work ships against stale specs", "The PR follows the ticket, the ticket missed the chat. Nobody notices until a customer does."],
          ["New hires inherit the confusion", "Onboarding means reading four tools and guessing which one is right."],
          ["Knowledge walks out the door", "When the one person who knows leaves, the context leaves with them."],
        ].map(([h, p]) => <div key={h}><b>{h}</b><p>{p}</p></div>)}
      </div>
     </div>
    </Chapter>
  );
}

/* ---------------------------------------------------------------- 02 the vision: the data model */

type MNode = { id: string; label: string; sub: string; x: number; y: number; count?: string };
const MODEL_NODES: MNode[] = [
  { id: "Person", label: "People", sub: "with roles", x: 90, y: 210 },
  { id: "Message", label: "Messages", sub: "Slack · Discord", x: 290, y: 100 },
  { id: "Decision", label: "Decisions", sub: "who · when", x: 290, y: 320 },
  { id: "Requirement", label: "Requirements", sub: "every version", x: 500, y: 210 },
  { id: "Ticket", label: "Tickets", sub: "Jira · Linear", x: 710, y: 210 },
  { id: "Feature", label: "Projects", sub: "features", x: 910, y: 210 },
  { id: "PullRequest", label: "Pull requests", sub: "GitHub", x: 600, y: 390 },
  { id: "Document", label: "Docs", sub: "PRDs · notes", x: 830, y: 390 },
  { id: "Sprint", label: "Sprints", sub: "cycles", x: 830, y: 50 },
];
const MODEL_EDGES: [string, string, string, number?][] = [
  ["Person", "Message", "POSTED"], ["Person", "Decision", "MADE"], ["Decision", "Message", "RECORDED_IN"],
  ["Message", "Requirement", "CHANGES"], ["Decision", "Requirement", "CHANGES"], ["Requirement", "Ticket", "AMENDS"],
  ["Ticket", "Feature", "ABOUT"], ["PullRequest", "Requirement", "IMPLEMENTS"], ["PullRequest", "Ticket", "REFERENCES"],
  ["Document", "Ticket", "MENTIONS"], ["Document", "Feature", "ABOUT"], ["Ticket", "Sprint", "IN_SPRINT"],
];
const W = 150, H = 54;

function ModelMap() {
  const { stats } = useBrain();
  const ref = useRef<SVGSVGElement>(null);
  const seen = useInView(ref, { once: true, margin: "-100px" });
  const still = useStill();
  const [hover, setHover] = useState<string | null>(null);
  const at = (id: string) => MODEL_NODES.find((n) => n.id === id)!;
  const count = (id: string) => stats?.nodes.find((x) => x.label === id)?.n;
  // edge from box edge to box edge, along the line between centres
  const clipTo = (a: MNode, b: MNode) => {
    const dx = b.x - a.x, dy = b.y - a.y;
    const t = Math.min(Math.abs((W / 2 + 6) / (dx || 1e-6)), Math.abs((H / 2 + 6) / (dy || 1e-6)));
    return { x: a.x + dx * t, y: a.y + dy * t };
  };
  return (
    <div className="model">
      <svg ref={ref} viewBox="0 0 1000 450" role="img" aria-label="Data model: people post messages and make decisions; decisions change requirements; requirements amend tickets; tickets belong to projects; pull requests implement requirements; docs mention tickets.">
        <defs>
          <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0 L10 5 L0 10 z" fill="currentColor" />
          </marker>
        </defs>
        <path className="model__loop" d="M 470 183 C 450 130, 550 130, 530 183" markerEnd="url(#arr)" />
        <text className="model__rel" x="500" y="128" textAnchor="middle">SUPERSEDES</text>
        {MODEL_EDGES.map(([a, b, rel], i) => {
          const A = at(a), B = at(b), s = clipTo(A, B), e = clipTo(B, A);
          const on = !hover || hover === a || hover === b;
          return (
            <g key={i} className={`model__edge ${on ? "" : "model__edge--dim"} ${hover && on ? "model__edge--on" : ""}`}>
              <motion.line x1={s.x} y1={s.y} x2={e.x} y2={e.y} markerEnd="url(#arr)"
                initial={still ? false : { pathLength: 0, opacity: 0 }} animate={seen ? { pathLength: 1, opacity: 1 } : undefined}
                transition={{ duration: 0.7, delay: 0.2 + i * 0.1, ease: EASE }} />
              <motion.text className="model__rel" x={(s.x + e.x) / 2} y={(s.y + e.y) / 2 - 6} textAnchor="middle"
                initial={still ? false : { opacity: 0 }} animate={seen ? { opacity: 1 } : undefined} transition={{ delay: 0.6 + i * 0.1 }}>{rel}</motion.text>
            </g>
          );
        })}
        {MODEL_NODES.map((n, i) => (
          <motion.g key={n.id} className={`model__node ${n.id === "Requirement" ? "model__node--key" : ""}`} onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}
            initial={still ? false : { opacity: 0, scale: 0.9 }} animate={seen ? { opacity: 1, scale: 1 } : undefined}
            transition={{ duration: 0.5, delay: i * 0.06, ease: EASE }} style={{ transformOrigin: `${n.x}px ${n.y}px` }}>
            <rect x={n.x - W / 2} y={n.y - H / 2} width={W} height={H} rx={8} />
            <text x={n.x} y={n.y - 3} textAnchor="middle" className="model__label">{n.label}</text>
            <text x={n.x} y={n.y + 15} textAnchor="middle" className="model__sub">{count(n.id) != null ? `${count(n.id)} · ${n.sub}` : n.sub}</text>
          </motion.g>
        ))}
      </svg>
    </div>
  );
}

function Vision() {
  const ref = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    const el = ref.current;
    if (!el || !moving()) return;
    fadeIn(el.querySelector(".model"), el);
    fadeIn(el.querySelectorAll(".vision__notes > div"), el.querySelector(".vision__notes"));
  }, { scope: ref });
  return (
    <Chapter id="vision" n="02" k="The graph" title={<>One graph connects them. <span className="muted">The links are the knowledge.</span></>}
      intro="Every message, decision, ticket version, pull request and doc becomes a node. What connects them, who said it, what it changed, what shipped it, becomes an edge. Hover a node to see its links; the numbers are live from the demo graph.">
     <div ref={ref}>
      <div className="model-wrap"><ModelMap /></div>
      <div className="vision__notes">
        <div><b>Time-ordered</b><p>Each ticket version and each chat change is its own Requirement, chained by SUPERSEDES. “What's true now?” is a path question.</p></div>
        <div><b>Multi-hop</b><p>A support agent's message → a reply → a ticket → a PR. The graph walks it in milliseconds; keyword search never sees it.</p></div>
        <div><b>Evidence built in</b><p>Every answer and alert carries the path that produced it, so people can check it instead of trusting it.</p></div>
      </div>
     </div>
    </Chapter>
  );
}

/* ---------------------------------------------------------------- 03 live demo */

const CASES = [
  { k: "Four tools", q: "Why is the database migration delayed and who can approve an override?", why: "Slack points to a design doc, the doc names the ticket, and the (demo) HR records say the assignee is away and who their manager is." },
  { k: "Root cause", q: "How is Liam connected to PR #6?", why: "A customer-success message, a reply, a ticket and a PR. Four hops nobody would find by searching." },
  { k: "Alignment", q: "Did we ship what we decided about SLA notifications?", why: "Chat decided one thing, the PR shipped another. Needs the decision, its version chain and what implements it." },
  { k: "Impact", q: "If we delay the launch of Project Alpha by two weeks, which other teams and downstream client deliverables will be impacted?", why: "Project → tickets → the tickets they block → waiting projects, client deliverables and the teams doing the work." },
];

function LiveDemo() {
  const [i, setI] = useState(0);
  const [res, setRes] = useState<Record<number, AskResult & { ms: number }>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async (k: number) => {
    setI(k); setErr(null);
    if (res[k]) return;
    setBusy(k);
    const t0 = performance.now();
    try { const r = await api.ask(CASES[k].q); setRes((m) => ({ ...m, [k]: { ...r, ms: performance.now() - t0 } })); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  };
  const ref = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    const el = ref.current;
    if (!el || !moving()) return;
    fadeIn(el.querySelectorAll(".case"), el);
    fadeIn(el.querySelector(".ask"), el.querySelector(".ask"));
  }, { scope: ref });
  // start the first case as the page opens, so its answer is usually ready by the time you scroll here
  useEffect(() => { void run(0); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  const r = res[i];
  const body = r?.answer.split(/\n\n\**Evidence:?\**/)[0].replace(/\*\*/g, "");
  return (
    <Chapter id="demo" n="03" k="Live demo" title={<>Questions that cross every tool. <span className="muted">Answered live.</span></>}
      intro="These run right now against the demo graph: the agent picks read-only graph tools, walks the path, and answers with its sources. Pick a use case.">
     <div ref={ref}>
      <div className="cases">
        {CASES.map((c, k) => (
          <button key={c.k} className={`case ${k === i ? "case--on" : ""}`} onClick={() => void run(k)}>
            <span className="mono">{String(k + 1).padStart(2, "0")} · {c.k}</span>
            <b>{c.q}</b>
            <small>{c.why}</small>
          </button>
        ))}
      </div>
      <div className="ask" style={{ marginTop: 16 }}>
        <div className="console">
          <div className="console__bar mono">
            <span>Graph agent · live</span>
            <span>{busy === i ? "querying…" : r ? `${r.tool_calls.length} tool ${plural(r.tool_calls.length, "call", "calls")} · ${(r.ms / 1000).toFixed(1)} s` : ""}</span>
          </div>
          <div className="console__body">
            <div className="q">{CASES[i].q}</div>
            <AnimatePresence mode="wait">
              {busy === i && <motion.span key="t" className="typing" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><i /><i /><i /></motion.span>}
              {busy !== i && err && <p key="e" className="warn">{err}</p>}
              {busy !== i && r && (
                <motion.div key={i} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} style={{ display: "grid", gap: 16 }}>
                  <div className="a">{body}</div>
                  <Sources res={r} />
                  {r.tool_calls.length > 0 && (
                    <ol className="steps">{r.tool_calls.map((t, k) => (
                      <li key={k}><span className="mono">{String(k + 1).padStart(2, "0")}</span><code>{t.tool}({Object.values(t.args).join(", ")})</code><span className="mono">{t.rows} {plural(t.rows, "row", "rows")}</span></li>
                    ))}</ol>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
        <AnswerGraph paths={busy === i ? [] : r?.paths || []} busy={busy === i} />
      </div>
      <p className="demo__more mono">Want to ask your own, approve a fix or post as a teammate? <a className="link" href={`${DEMO_HREF}#ask`}>Open the demo →</a></p>
     </div>
    </Chapter>
  );
}

/* ---------------------------------------------------------------- 04 your repo */

function TryChapter() {
  return (
    <Chapter id="try" n="04" k="Your repo" title={<>Now on your own repo. <span className="muted">Any public GitHub repo.</span></>}
      intro="Paste a repo. The server reads its most recent issues, pull requests and comments, runs the same pipeline into a graph of its own (the rules extractor: fast, no LLM), and shows what the graph knows: who knows what, which PRs close which issues, open issues nobody is working on, decisions in comments, and drift.">
      <TryRepo />
    </Chapter>
  );
}

/* ---------------------------------------------------------------- 06 value + 07 stack */

function Value() {
  const ref = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    const el = ref.current;
    if (!el || !moving()) return;
    fadeIn(el.querySelectorAll(".value > div"), el.querySelector(".value"), { stagger: 0.1 });
    fadeIn(el.querySelectorAll(".nums > div"), el.querySelector(".nums"));
  }, { scope: ref });
  return (
    <Chapter id="value" n="06" k="Business value" title={<>Less searching. <span className="muted">Fewer surprises. Faster fixes.</span></>}>
     <div ref={ref}>
      <div className="value">
        {[
          ["Onboarding", "A new hire asks “who knows the most about export?” and gets a ranked answer with the threads, tickets and PRs behind it, instead of a week of asking around.", ["Who knows what, ranked from real work", "Every decision with its source", "Agent-ready spec per feature"]],
          ["Alignment", "When chat changes a requirement, the people on the ticket hear about it in the thread, within seconds, with proof. Specs stop drifting from decisions.", ["In-thread alerts on Slack and Discord", "Sprint retro: decided vs shipped", "Only owners can change scope"]],
          ["Execution", "The fix plan is read from the graph: who wrote the stale PR, who owns the doc. One approval updates the ticket and assigns the follow-ups.", ["Follow-ups assigned to the right people", "Bus-factor and coverage gaps", "Nothing changes without an owner"]],
        ].map(([h, p, pts]) => (
          <div key={h as string}>
            <h3>{h}</h3>
            <p>{p}</p>
            <ul>{(pts as string[]).map((x) => <li key={x}>{x}</li>)}</ul>
          </div>
        ))}
      </div>
      <span className="kicker" style={{ marginTop: 56 }}>Why it scales · measured, see the repo's results</span>
      <div className="nums">
        <div><b>100/100</b><span className="mono">planted drifts found in a 22,940-node graph, 0 false</span></div>
        <div><b>39 ms</b><span className="mono">drift query over the whole graph (p50)</span></div>
        <div><b>6.1 ms</b><span className="mono">multi-hop path between any two nodes (p50)</span></div>
        <div className="hot"><b>1.00 → 0.50</b><span className="mono">precision without the version edges: why it's a graph</span></div>
      </div>
     </div>
    </Chapter>
  );
}

const STACK: [string, string, string[]][] = [
  ["Graph", "FalkorDB", ["Cypher anti-patterns find drift with its evidence", "algo.SPpaths for multi-hop questions", "GRAPH.RO_QUERY: the agent can only read", "Vector index on doc chunks, filtered by who's asking", "Full-text + range indexes, one graph per tenant"]],
  ["Ingest", "Python pipeline", ["Connectors: Slack, Discord, GitHub, ticket tracker, docs, Google Drive", "Doc edits re-embed only the changed chunks", "Rules or LLM extraction (gpt-oss-120b, local qwen3)", "Idempotent UNWIND … MERGE writes"]],
  ["Agent", "16 graph tools", ["Fixed, read-only tools, no free-form queries", "Sees only what the asker may see", "Answers checked against tool output", "Says “not in the graph” instead of guessing"]],
  ["Delivery", "API, bots, dashboard", ["FastAPI with live events over SSE", "Slack and Discord bots reply in thread", "React + TypeScript + Cytoscape dashboard", "One Docker image runs it all"]],
];

function Stack() {
  const ref = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    const el = ref.current;
    if (!el || !moving()) return;
    fadeIn(el.querySelectorAll(".stack > div"), el, { stagger: 0.1 });
  }, { scope: ref });
  return (
    <Chapter id="stack" n="07" k="Tech stack" title={<>Built on a graph database. <span className="muted">Runs anywhere.</span></>}>
      <div className="stack" ref={ref}>
        {STACK.map(([k, h, pts]) => (
          <div key={k}>
            <span className="mono muted">{k}</span>
            <h3>{h}</h3>
            <ul>{pts.map((x) => <li key={x}>{x}</li>)}</ul>
          </div>
        ))}
      </div>
    </Chapter>
  );
}

function FinalCta() {
  const ref = useRef<HTMLElement>(null);
  useGSAP(() => {
    const el = ref.current;
    if (!el || !moving()) return;
    revealHeading(el.querySelector("h2"), { by: "chars", start: "top 80%" });
    gsap.from(el.querySelectorAll(".lede, .hero__cta"), { opacity: 0, y: 24, stagger: 0.1, delay: 0.4, scrollTrigger: { trigger: el, start: "top 80%", once: true } });
  }, { scope: ref });
  return (
    <section className="cta" ref={ref}>
      <div>
        <h2>See it on a real company's worth of data.</h2>
        <p className="lede" style={{ margin: "18px auto 0" }}>The demo opens a fresh private sandbox of Brightdesk, a synthetic software company (8 people, 300 messages, tickets, PRs and docs), and walks you through it: every step does the real thing, and each answer is highlighted with where it came from.</p>
        <div className="hero__cta" style={{ justifyContent: "center" }}>
          <a className="btn" href={DEMO_HREF}>Open the demo →</a>
        </div>
        <div className="spectrum" aria-hidden />
      </div>
    </section>
  );
}

export function Landing() {
  return (
    <>
      <LandingNav />
      <Marquee />
      <LandingHero />
      <Pain />
      <Vision />
      <LiveDemo />
      <TryChapter />
      <Features />
      <Value />
      <Stack />
      <Connect />
      <FinalCta />
      <Footer />
    </>
  );
}
