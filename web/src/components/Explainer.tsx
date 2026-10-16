import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { useStill } from "../lib/fx";
import { useBrain } from "../lib/brain";
import { day } from "../lib/ui";
import { EASE } from "./Motion";

/* 002: how drift happens, pinned while you scroll. Each step adds one link of the chain:
   message -> requirement -> ticket, then the PR and doc that still follow the OLD version, then DRIFT. */

const STEPS = [
  { k: "Chat", h: "A decision lands in chat.", p: "Maya, in #support-escalations: the export should cover any range up to 12 months, not 30 days. Nobody opens the ticket." },
  { k: "Changes", h: "It changes a requirement.", p: "The message becomes a Requirement node: Message -[:CHANGES]-> Requirement. It is now the newest version of what BD-101 must do." },
  { k: "Amends", h: "The requirement amends the ticket.", p: "Requirement -[:AMENDS]-> Ticket BD-101. But the ticket text still says “last 30 days”. Nothing wrote the change back." },
  { k: "Still on old", h: "Code and docs follow the old version.", p: "PR #6 shipped the 30-day export and the PRD still describes it. Both point at the version chat already replaced." },
  { k: "Drift", h: "That gap is drift.", p: "A requirement nothing SUPERSEDES and no PR IMPLEMENTS. One Cypher query finds every one, with the path as evidence." },
];
const N = STEPS.length;
const clamp = (x: number) => Math.max(0, Math.min(1, x));

function Diagram({ s }: { s: (i: number) => number }) {
  // s(i): 0..1 progress of step i
  const node = (i: number) => ({ opacity: clamp(s(i) * 1.6), transform: `scale(${0.6 + 0.4 * clamp(s(i) * 1.6)})` });
  const draw = (i: number) => ({ strokeDashoffset: 1 - s(i) });
  const pulse = s(4);
  return (
    <svg viewBox="0 0 820 560" role="img" aria-label="Message changes requirement, requirement amends ticket BD-101; PR #6 and DOC-1 stay on the old version">
      <defs>
        <radialGradient id="planet" cx="0" cy="1" r="1">
          <stop offset="0" style={{ stopColor: "var(--planet-core)" }} />
          <stop offset=".55" style={{ stopColor: "var(--planet-mid)" }} />
          <stop offset="1" style={{ stopColor: "var(--bg)", stopOpacity: 0 }} />
        </radialGradient>
        <linearGradient id="hotpath" x1="0" x2="1">
          <stop offset="0" style={{ stopColor: "var(--violet-2)" }} /><stop offset="1" style={{ stopColor: "var(--violet)" }} />
        </linearGradient>
        {[["m-pr", "M 430 140 Q 530 80 620 110"], ["m-doc", "M 430 140 Q 500 260 560 330"]].map(([id, d]) => (
          <mask id={id} key={id} maskUnits="userSpaceOnUse"><path d={d} pathLength={1} stroke="#fff" strokeWidth={6} fill="none" strokeDasharray="1" style={draw(3)} /></mask>
        ))}
      </defs>
      <circle cx="0" cy="560" r="320" fill="url(#planet)" />
      <circle cx="0" cy="560" r="190" className="orbit__ring orbit__ring--solid" />
      {[300, 420, 560, 700].map((r, i) => <circle key={r} cx="0" cy="560" r={r} className={`orbit__ring ${i > 1 ? "orbit__ring--faint" : ""}`} />)}
      <path className="orbit__path" d="M 110 330 Q 200 250 300 250" pathLength={1} strokeDasharray="1" style={draw(1)} />
      <path className="orbit__path" d="M 300 250 Q 400 250 430 140" pathLength={1} strokeDasharray="1" style={draw(2)} />
      <path className="orbit__broken" d="M 430 140 Q 530 80 620 110" mask="url(#m-pr)" />
      <path className="orbit__broken" d="M 430 140 Q 500 260 560 330" mask="url(#m-doc)" />
      <g className="orbit__node" transform="translate(110 330)"><g style={node(0)} className="xnode">
        <circle r="6" /><text x="14" y="4">MESSAGE</text><text x="14" y="20" className="sub">“12 months, not 30 days”</text></g></g>
      <g className="orbit__node orbit__node--hot" transform="translate(300 250)"><g style={node(1)} className="xnode">
        {pulse > 0 && <circle className="orbit__pulse xpulse" r={8} />}
        <circle r="8" />
        <path className="bracket" d="M-16 -10 v-6 h6 M10 -16 h6 v6 M16 10 v6 h-6 M-10 16 h-6 v-6" style={{ opacity: pulse, transform: `scale(${1.6 - 0.6 * pulse})` }} />
        <text x="24" y="4">REQUIREMENT</text><text x="24" y="20" className="sub">newest · not superseded</text></g></g>
      <g className="orbit__node" transform="translate(430 140)"><g style={node(2)} className="xnode">
        <rect x="-7" y="-7" width="14" height="14" /><text x="16" y="-8">TICKET BD-101</text><text x="16" y="8" className="sub">still says “last 30 days”</text></g></g>
      <g className="orbit__node orbit__node--stale" transform="translate(620 110)"><g style={node(3)} className="xnode">
        <path d="M0 -9 L9 0 L0 9 L-9 0 Z" /><text x="16" y="4">PR #6</text><text x="16" y="20" className="sub">shipped the old version</text></g></g>
      <g className="orbit__node orbit__node--stale" transform="translate(560 330)"><g style={node(3)} className="xnode">
        <path d="M-7 -8 h10 l4 4 v12 h-14 z" /><text x="16" y="4">PRD · DOC-1</text><text x="16" y="20" className="sub">still says 30 days</text></g></g>
      <text className="orbit__tag" x="276" y="212" style={{ opacity: pulse }}>DRIFT</text>
      <text className="orbit__label" x="40" y="282">CHAT</text>
      <text className="orbit__label" x="380" y="78">TICKETS</text>
      <text className="orbit__label" x="660" y="56">CODE · DOCS</text>
    </svg>
  );
}

function SpecSheet() {
  const { stats, drift } = useBrain();
  const total = (xs?: { n: number }[]) => (xs || []).reduce((a, x) => a + x.n, 0);
  const extractor = stats?.build?.extractor;
  return (
    <dl className="spec">
      <div><dt>Graph</dt><dd>{stats ? `${total(stats.nodes)} nodes · ${total(stats.relationships)} relationships` : "…"}</dd></div>
      <div><dt>Open drift</dt><dd className={drift.length ? "warn" : ""}>{drift.length ? `${drift.length} · ${[...new Set(drift.map((d) => d.feature_name))].join(", ")}` : "none"}</dd></div>
      <div><dt>Extraction</dt><dd>{extractor === "heuristic" ? "Rules mode" : extractor === "oracle" ? <span className="warn">answer-key oracle (test mode)</span> : extractor ? `LLM · ${stats?.build?.model || "DeepSeek"}` : "…"}{stats?.build?.at ? <span className="muted"> · built {day(stats.build.at)}</span> : null}</dd></div>
      <div><dt>LLM</dt><dd>{!stats ? "…" : stats.llm.available ? `online (${stats.llm.model})` : <span className="muted">Rules mode · LLM not configured</span>}</dd></div>
    </dl>
  );
}

export function OrbitBand() {
  const still = useStill();
  const section = useRef<HTMLElement>(null);
  const pinned = useRef<HTMLDivElement>(null);
  const [p, setP] = useState(still ? 1 : 0);

  useEffect(() => {
    if (still) { setP(1); return; }
    let kill: (() => void) | undefined, alive = true;
    void Promise.all([import("gsap"), import("gsap/ScrollTrigger")]).then(([{ gsap }, { ScrollTrigger }]) => {
      if (!alive || !section.current || !pinned.current) return;
      gsap.registerPlugin(ScrollTrigger);
      const st = ScrollTrigger.create({
        trigger: section.current, start: "top 72px", end: () => `+=${Math.round(window.innerHeight * 2.6)}`,
        pin: pinned.current, scrub: 0.6, anticipatePin: 1, onUpdate: (self) => setP(self.progress),
      });
      kill = () => st.kill();
    });
    return () => { alive = false; kill?.(); };
  }, [still]);

  const sf = p * N;  // step float
  const s = (i: number) => clamp(sf - i);
  const step = Math.min(N - 1, Math.floor(sf));
  return (
    <section className="band band--explainer" id="system" aria-label="How drift happens" ref={section}>
      <div ref={pinned} className="explainer">
        <div className="band__bar mono"><span><i className="sq" />002</span><span><i className="sq" />A context graph</span><span className="band__right">How drift happens</span></div>
        <div className="band__grid">
          <figure className="orbit" style={{ margin: 0 }}><Diagram s={still ? () => 1 : s} /></figure>
          <div>
            <div className="steps mono" role="progressbar" aria-valuemin={1} aria-valuemax={N} aria-valuenow={step + 1}>
              {STEPS.map((x, i) => (
                <span key={x.k} className={i <= step ? "on" : ""}><i style={{ transform: `scaleX(${still ? 1 : s(i)})` }} />{x.k}</span>
              ))}
            </div>
            {still ? (
              <ol className="steps__all">{STEPS.map((x) => <li key={x.k}><b>{x.h}</b> {x.p}</li>)}</ol>
            ) : (
              <div className="steps__copy">
                <AnimatePresence mode="wait">
                  <motion.div key={step} initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -14 }} transition={{ duration: 0.45, ease: EASE }}>
                    <div className="kicker-line mono"><i className="sq sq--violet" />Step {step + 1} of {N}</div>
                    <h2 className="display">{STEPS[step].h}</h2>
                    <p className="lede">{STEPS[step].p}</p>
                  </motion.div>
                </AnimatePresence>
              </div>
            )}
            <SpecSheet />
          </div>
        </div>
        <div className="band__foot mono">Orbits not to scale · Drift = requirement has no newer version and nothing implements it</div>
      </div>
    </section>
  );
}
