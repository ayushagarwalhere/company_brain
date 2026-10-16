import { motion, useScroll, useTransform } from "framer-motion";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useBrain } from "../lib/brain";
import { ErrorBoundary } from "./ErrorBoundary";
import { useMagnetic, useTilt } from "../lib/fx";
import { CountUp, Reveal, WordReveal } from "./Motion";

const Planet3D = lazy(() => import("./Planet3D"));

function webglOK() {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch { return false; }
}

/** Tracks the effective theme: explicit data-theme wins, otherwise the OS preference. */
function useLightTheme() {
  const read = () => {
    const t = document.documentElement.dataset.theme;
    return t ? t === "light" : window.matchMedia("(prefers-color-scheme: light)").matches;
  };
  const [light, setLight] = useState(read);
  useEffect(() => {
    const update = () => setLight(read());
    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    mq.addEventListener("change", update);
    update();
    return () => { mo.disconnect(); mq.removeEventListener("change", update); };
  }, []);
  return light;
}

export function Hero() {
  const [gl, setGl] = useState(webglOK);
  const [ready, setReady] = useState(false);
  const light = useLightTheme();
  const { setPaletteOpen } = useBrain();
  const ref = useRef<HTMLElement>(null);
  const primary = useMagnetic<HTMLAnchorElement>(0.28);
  const ghost = useMagnetic<HTMLButtonElement>(0.28);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const planetY = useTransform(scrollYProgress, [0, 1], ["0%", "18%"]);
  const starsY = useTransform(scrollYProgress, [0, 1], ["0%", "8%"]);
  return (
    <header className={`hero ${gl && ready ? "hero--3d" : ""}`} id="top" ref={ref}>
      {gl && (
        <ErrorBoundary onError={() => { setGl(false); setReady(false); }}>
          <Suspense fallback={null}>
            <Planet3DReady key={light ? "light" : "dark"} light={light} onReady={() => setReady(true)} />
          </Suspense>
        </ErrorBoundary>
      )}
      <div className="sky" aria-hidden>
        <motion.span className="stars" style={{ y: starsY }} />
        <motion.span className="stars stars--2" style={{ y: starsY }} />
        <motion.span className="atmosphere" style={{ y: planetY }} />
        <span className="orbit-line" />
      </div>
      <div className="hero__center">
        <Reveal className="hero__eyebrow mono"><i className="sq sq--violet" />Company Brain · FalkorDB context graph</Reveal>
        <h1 className="hero__title" aria-label="Decided in chat. Never shipped.">
          <WordReveal text="Decided in chat." delay={0.2} />
          <WordReveal text="Never shipped." className="accent" delay={0.5} />
        </h1>
        <Reveal className="hero__cta" delay={0.9}>
          <a ref={primary} className="btn btn--magnetic" href="#drift">See open drift <span className="btn__arrow" aria-hidden>→</span></a>
          <button ref={ghost} className="btn btn--ghost btn--magnetic" onClick={() => setPaletteOpen(true)}>Search the graph <span className="btn__arrow" aria-hidden>↗</span></button>
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

function Planet3DReady({ light, onReady }: { light: boolean; onReady: () => void }) {
  useEffect(() => { onReady(); }, [onReady]);
  return <motion.div className="planet3d-fade" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 1.6 }}><Planet3D light={light} /></motion.div>;
}

const TILES = [
  "radial-gradient(120% 90% at 20% 10%, #8b7bd8, #3b2a7a 45%, #120d2a)",
  "radial-gradient(120% 90% at 80% 20%, #d7c9ff, #7c5fd6 40%, #1c1440)",
  "linear-gradient(160deg, #2b2340, #6b5b8f 50%, #c9bde6)",
  "radial-gradient(100% 100% at 30% 70%, #a78bfa, #4c1d95 55%, #0b0820)",
  "radial-gradient(120% 90% at 70% 30%, #ff9b7a, #b4361b 45%, #2a0c06)",
];

function MetricCard({ i, label, value, sub, hot }: { i: number; label: string; value: number; sub: string; hot?: boolean }) {
  const tilt = useTilt<HTMLDivElement>(6);
  return (
    <Reveal delay={i * 0.08} className="metric-wrap">
      <div ref={tilt} className={`metric brackets ${hot ? "metric--hot" : ""}`}>
        <div className="metric__bg" style={{ ["--tile" as string]: TILES[i] }} />
        <div className="metric__glow" aria-hidden />
        <small className="mono">{sub}</small>
        <div className="metric__row"><CountUp value={value} delay={0.15 + i * 0.12} /><span>{label}</span></div>
      </div>
    </Reveal>
  );
}

/** 003: what's in the demo graph, as image-like tiles. */
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
        <Reveal delay={0.05}><h2 className="display display--center">Demo company: Brightdesk <span className="muted">(synthetic)</span></h2></Reveal>
      </div>
      <div className="metrics">
        {cards.map(([label, value, sub, hot], i) => <MetricCard key={label} i={i} label={label} value={value} sub={sub} hot={hot} />)}
      </div>
      {tick.length > 0 && (
        <div className="ticker mono" aria-hidden>
          <div className="ticker__track">{[...tick, ...tick].map(([k, v], i) => <span key={i}><b>{k}</b>{v}</span>)}</div>
        </div>
      )}
    </section>
  );
}
