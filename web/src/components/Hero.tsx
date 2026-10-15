import { motion, useReducedMotion, useScroll, useTransform } from "framer-motion";
import { useRef } from "react";
import { useBrain } from "../lib/brain";
import { day, useStaticMode } from "../lib/ui";
import { CountUp, EASE, Reveal, SplitText } from "./Motion";

export function Hero() {
  const { setPaletteOpen } = useBrain();
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const planetY = useTransform(scrollYProgress, [0, 1], ["0%", "18%"]);
  const starsY = useTransform(scrollYProgress, [0, 1], ["0%", "8%"]);
  return (
    <header className="hero" id="top" ref={ref}>
      <div className="sky" aria-hidden>
        <motion.span className="stars" style={{ y: starsY }} />
        <motion.span className="stars stars--2" style={{ y: starsY }} />
        <motion.span className="atmosphere" style={{ y: planetY }} />
        <span className="orbit-line" />
      </div>
      <div className="hero__center">
        <Reveal className="hero__eyebrow mono"><i className="sq sq--violet" />Company Brain · FalkorDB context graph</Reveal>
        <h1 className="hero__title" aria-label="Decided in chat. Never shipped.">
          <SplitText text="Decided in chat." />
          <SplitText text="Never shipped." className="accent" offset={16} />
        </h1>
        <Reveal className="hero__cta" delay={0.9}>
          <a className="btn" href="#drift">See open drift</a>
          <button className="btn btn--ghost" onClick={() => setPaletteOpen(true)}>Search the graph</button>
        </Reveal>
      </div>
      <Reveal className="hero__bar mono" delay={1.1}>
        <span><i className="sq" />001</span>
        <span><i className="sq" />Context with purpose</span>
        <span><i className="sq" />Linking chat, docs, tickets and code<br />in one FalkorDB graph</span>
      </Reveal>
    </header>
  );
}

/** 002: orbit diagram of how drift happens + live spec sheet. */
export function OrbitBand() {
  const { stats, drift } = useBrain();
  const still = useReducedMotion() || useStaticMode();
  const total = (xs?: { n: number }[]) => (xs || []).reduce((a, x) => a + x.n, 0);
  const draw = (delay: number) => (still ? {} : {
    initial: { pathLength: 0, opacity: 0 }, whileInView: { pathLength: 1, opacity: 1 }, viewport: { once: true },
    transition: { duration: 1.4, ease: EASE, delay },
  });
  const pop = (delay: number) => (still ? {} : {
    initial: { opacity: 0, scale: 0.6 }, whileInView: { opacity: 1, scale: 1 }, viewport: { once: true },
    transition: { duration: 0.6, ease: EASE, delay },
  });
  const extractor = stats?.build?.extractor;
  return (
    <section className="band" id="system" aria-label="How drift happens">
      <div className="band__bar mono"><span><i className="sq" />002</span><span><i className="sq" />A context graph</span><span className="band__right">How drift happens</span></div>
      <div className="band__grid">
        <figure className="orbit" style={{ margin: 0 }} aria-label="Message changes requirement, requirement amends ticket; PR and doc stay on the old version">
          <svg viewBox="0 0 820 560" role="img">
            <defs>
              <radialGradient id="planet" cx="0" cy="1" r="1">
                <stop offset="0" style={{ stopColor: "var(--planet-core)" }} />
                <stop offset=".55" style={{ stopColor: "var(--planet-mid)" }} />
                <stop offset="1" style={{ stopColor: "var(--bg)", stopOpacity: 0 }} />
              </radialGradient>
              <linearGradient id="hotpath" x1="0" x2="1">
                <stop offset="0" style={{ stopColor: "var(--violet-2)" }} /><stop offset="1" style={{ stopColor: "var(--violet)" }} />
              </linearGradient>
            </defs>
            <circle cx="0" cy="560" r="320" fill="url(#planet)" />
            <circle cx="0" cy="560" r="190" className="orbit__ring orbit__ring--solid" />
            {[300, 420, 560, 700].map((r, i) => <circle key={r} cx="0" cy="560" r={r} className={`orbit__ring ${i > 1 ? "orbit__ring--faint" : ""}`} />)}
            <motion.path className="orbit__path" d="M 110 330 Q 200 250 300 250 Q 400 250 430 140" {...draw(0.2)} />
            <motion.path className="orbit__broken" d="M 430 140 Q 530 80 620 110" {...draw(1.3)} />
            <motion.path className="orbit__broken" d="M 430 140 Q 500 260 560 330" {...draw(1.5)} />
            <motion.g className="orbit__node" {...pop(0.1)}><g transform="translate(110 330)"><circle r="6" /><text x="14" y="4">MESSAGE</text><text x="14" y="20" className="sub">“12 months, not 30 days”</text></g></motion.g>
            <motion.g className="orbit__node orbit__node--hot" {...pop(0.8)}>
              <g transform="translate(300 250)">
                {!still && <motion.circle className="orbit__pulse" r={8} animate={{ r: [8, 26], opacity: [0.8, 0] }} transition={{ duration: 2, repeat: Infinity, ease: "easeOut" }} />}
                <circle r="8" />
                <path className="bracket" d="M-16 -10 v-6 h6 M10 -16 h6 v6 M16 10 v6 h-6 M-10 16 h-6 v-6" />
                <text x="24" y="4">REQUIREMENT</text><text x="24" y="20" className="sub">newest · not superseded</text>
              </g>
            </motion.g>
            <motion.g className="orbit__node" {...pop(1.1)}><g transform="translate(430 140)"><rect x="-7" y="-7" width="14" height="14" /><text x="16" y="-8">TICKET BD-101</text><text x="16" y="8" className="sub">“last 30 days”</text></g></motion.g>
            <motion.g className="orbit__node orbit__node--stale" {...pop(1.6)}><g transform="translate(620 110)"><path d="M0 -9 L9 0 L0 9 L-9 0 Z" /><text x="16" y="4">PR #6</text><text x="16" y="20" className="sub">shipped the old version</text></g></motion.g>
            <motion.g className="orbit__node orbit__node--stale" {...pop(1.8)}><g transform="translate(560 330)"><path d="M-7 -8 h10 l4 4 v12 h-14 z" /><text x="16" y="4">PRD · DOC-1</text><text x="16" y="20" className="sub">still says 30 days</text></g></motion.g>
            <text className="orbit__tag" x="276" y="212">DRIFT</text>
            <text className="orbit__label" x="40" y="282">CHAT</text>
            <text className="orbit__label" x="380" y="78">TICKETS</text>
            <text className="orbit__label" x="660" y="56">CODE · DOCS</text>
          </svg>
        </figure>
        <div>
          <Reveal className="kicker-line mono"><i className="sq sq--violet" />The gap we close</Reveal>
          <Reveal delay={0.05}><h2 className="display">Decisions move faster than tickets.</h2></Reveal>
          <Reveal delay={0.1}><p className="lede">A requirement changes in a thread. The ticket keeps the old text, the PRD keeps the old scope, and the PR ships it. Drift Monitor puts chat, docs, tickets and code on one graph and flags the exact path where they split.</p></Reveal>
          <Reveal delay={0.15}>
            <dl className="spec">
              <div><dt>Sources</dt><dd>Slack · Discord · Docs · GitHub · Tickets</dd></div>
              <div><dt>Graph</dt><dd>{stats ? `${total(stats.nodes)} nodes · ${total(stats.relationships)} relationships · ${stats.nodes.length} labels` : "…"}</dd></div>
              <div><dt>Open drift</dt><dd className={drift.length ? "warn" : ""}>{drift.length ? `${drift.length} requirement${drift.length > 1 ? "s" : ""} · ${[...new Set(drift.map((d) => d.feature_name))].join(", ")}` : "none"}</dd></div>
              <div><dt>Extraction</dt><dd>{extractor === "heuristic" ? "Rule-based heuristics · no LLM" : extractor === "oracle" ? <span className="warn">answer-key oracle (test mode)</span> : extractor === "deepseek" ? "DeepSeek LLM" : "…"}{stats?.build?.at ? <span className="muted"> · built {day(stats.build.at)}</span> : null}</dd></div>
              <div><dt>LLM</dt><dd>{stats ? (stats.llm.available ? `${stats.llm.model} · online` : <span className="muted">offline ({stats.llm.reason}) · rules agent answering</span>) : "…"}</dd></div>
            </dl>
          </Reveal>
        </div>
      </div>
      <div className="band__foot mono">Orbits not to scale · Drift = requirement has no newer version and nothing implements it</div>
    </section>
  );
}

const TILES = [
  "radial-gradient(120% 90% at 20% 10%, #8b7bd8, #3b2a7a 45%, #120d2a)",
  "radial-gradient(120% 90% at 80% 20%, #d7c9ff, #7c5fd6 40%, #1c1440)",
  "linear-gradient(160deg, #2b2340, #6b5b8f 50%, #c9bde6)",
  "radial-gradient(100% 100% at 30% 70%, #a78bfa, #4c1d95 55%, #0b0820)",
  "radial-gradient(120% 90% at 70% 30%, #ff9b7a, #b4361b 45%, #2a0c06)",
];

/** 003: what's in the graph, as image-like tiles with corner handles. */
export function Stats() {
  const { stats, drift } = useBrain();
  const n = (l: string) => stats?.nodes.find((x) => x.label === l)?.n ?? 0;
  const cards: [string, number, string, boolean?][] = [
    ["Messages", n("Message"), "Slack + Discord"], ["Tickets", n("Ticket"), "Linear-style"],
    ["Pull requests", n("PullRequest"), "GitHub"], ["Docs", n("Document"), "PRDs + design notes"], ["Open drift", drift.length, "requirements", true],
  ];
  const tick = stats ? [["NODES", stats.nodes.reduce((a, x) => a + x.n, 0)], ["RELATIONSHIPS", stats.relationships.reduce((a, x) => a + x.n, 0)],
    ...stats.relationships.slice(0, 12).map((r) => [r.type, r.n])] : [];
  return (
    <section className="band" aria-label="Graph metrics">
      <div className="band__bar mono"><span><i className="sq" />003</span><span><i className="sq" />Proof of context</span></div>
      <div className="stats-head">
        <Reveal><span className="pill mono">What's in the graph</span></Reveal>
        <Reveal delay={0.05}><h2 className="display display--center">Operating on your graph today</h2></Reveal>
      </div>
      <div className="metrics">
        {cards.map(([label, value, sub, hot], i) => (
          <Reveal key={label} delay={i * 0.08} className={`metric handles ${hot ? "metric--hot" : ""}`}>
            <div className="metric__bg" style={{ ["--tile" as string]: TILES[i] }} />
            <small className="mono">{sub}</small>
            <div className="metric__row"><CountUp value={value} /><span>{label}</span></div>
          </Reveal>
        ))}
      </div>
      {tick.length > 0 && (
        <div className="ticker mono" aria-hidden>
          <div className="ticker__track">{[...tick, ...tick].map(([k, v], i) => <span key={i}><b>{k}</b>{v}</span>)}</div>
        </div>
      )}
    </section>
  );
}
