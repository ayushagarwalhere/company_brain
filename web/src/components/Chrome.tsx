import { useEffect, useState } from "react";
import { ORG } from "../lib/api";
import { useBrain } from "../lib/brain";
import { LiveDot } from "./Toasts";
import { DEMO_HREF, isAppMode, isTeamOrg } from "../lib/routes";

const ALL_SECTIONS = [["setup", "Setup"], ["drift", "Drift"], ["graph-sec", "Graph"], ["map-sec", "Map"], ["impact", "Impact"], ["simulate", "Monitor"], ["stream", "Stream"], ["ask", "Ask"], ["docs-sec", "Docs"], ["retro-sec", "Retro"], ["coverage", "Risk"]];
/** The nav links: a connected team's dashboard has a Setup section and none of the demo-only ones (App.tsx). */
export const SECTIONS = ALL_SECTIONS.filter(([id]) => (isTeamOrg(ORG) ? !["impact", "simulate", "docs-sec"].includes(id) : id !== "setup"));

export function Nav() {
  const { setPaletteOpen, newDrift, clearNew } = useBrain();
  const [line, setLine] = useState(false);
  const [active, setActive] = useState("");

  useEffect(() => {
    const onScroll = () => setLine(window.scrollY > 24);
    onScroll();
    addEventListener("scroll", onScroll, { passive: true });
    const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && setActive(e.target.id)), { rootMargin: "-45% 0px -50% 0px" });
    const t = setTimeout(() => SECTIONS.forEach(([id]) => { const el = document.getElementById(id); if (el) io.observe(el); }), 500);
    return () => { removeEventListener("scroll", onScroll); io.disconnect(); clearTimeout(t); };
  }, []);
  useEffect(() => { if (active === "drift" && newDrift) { const t = setTimeout(clearNew, 1500); return () => clearTimeout(t); } }, [active, newDrift, clearNew]);

  return (
    <nav className={`nav ${line ? "nav--line" : ""}`}>
      <a className="brand" href="#top" aria-label="Drift Monitor home"><span className="brand__mark" />Drift Monitor</a>
      <div className="nav__links mono">
        {SECTIONS.map(([id, label]) => (
          <a key={id} href={`#${id}`} className={active === id ? "active" : ""}>
            {label}
            {id === "drift" && newDrift > 0 && <span className="nav__badge" aria-label={`${newDrift} new`}>{newDrift}</span>}
          </a>
        ))}
      </div>
      <div className="nav__right">
        <LiveDot />
        <button className="btn btn--ghost btn--sm nav__search" onClick={() => setPaletteOpen(true)} aria-label="Search the graph">
          Search <kbd>/</kbd>
        </button>
      </div>
    </nav>
  );
}

const REPO = "https://github.com/ayushagarwalhere/company_brain";

/** Every feature and its colour, the same hue as its section; in the app a chip jumps there, elsewhere it opens the
    demo tour at that feature's step. */
const FEATURE_MAP: [string, string, string][] = [
  ["drift", "Drift", "--c-coral"], ["graph-sec", "Graph", "--c-blue"], ["map-sec", "Company map", "--c-cyan"], ["impact", "Impact", "--c-amber"],
  ["simulate", "Live monitor", "--c-green"], ["stream", "Live stream", "--c-pink"], ["ask", "Ask", "--c-violet"], ["docs-sec", "Docs & access", "--c-cyan"], ["retro-sec", "Retro", "--c-pink"], ["coverage", "Risk", "--c-yellow"],
];
const CHAPTERS: [string, string][] = [["pain", "The pain"], ["vision", "The graph"], ["demo", "Live demo"], ["features", "Features"], ["value", "Business value"], ["stack", "Tech stack"]];

export function Footer() {
  const { stats, drift } = useBrain();
  const inApp = isAppMode();
  const sum = (xs?: { n: number }[]) => (xs || []).reduce((t, x) => t + x.n, 0);
  return (
    <footer className="foot">
      <div className="foot__cta">
        <div>
          <span className="eyebrow">Company Brain · a context graph on FalkorDB</span>
          <h3>Stop asking around. <span>Ask the graph.</span></h3>
        </div>
        <a className="btn" href={DEMO_HREF}>{inApp ? "Restart the guided tour →" : "Open the demo →"}</a>
      </div>
      <div className="spectrum" aria-hidden />
      <nav className="foot__map" aria-label="Features">
        {FEATURE_MAP.map(([id, label, c]) => (
          <a key={id} href={inApp ? `#${id}` : `${DEMO_HREF}#${id}`} style={{ ["--acc" as string]: `var(${c})` }}><i aria-hidden />{label}</a>
        ))}
      </nav>
      <div className="foot__in">
        <div>
          <a className="brand" href={inApp ? "/" : "#top"}><span className="brand__mark" />Drift Monitor</a>
          <p>Chat, tickets, pull requests and docs in one graph. It catches decisions that never shipped, answers questions that cross every tool, and every answer carries the path that proves it.</p>
        </div>
        <div>
          <h5>Overview</h5>
          {CHAPTERS.map(([id, label]) => <a key={id} href={`/#${id}`}>{label}</a>)}
        </div>
        <div>
          <h5>Project</h5>
          <a href={REPO} target="_blank" rel="noopener">GitHub ↗</a>
          <a href={`${REPO}#readme`} target="_blank" rel="noopener">README ↗</a>
          <a href={`${REPO}/blob/main/docs/RESULTS.md`} target="_blank" rel="noopener">Benchmarks ↗</a>
          <a href={`${REPO}/blob/main/docs/EXPLAIN.md`} target="_blank" rel="noopener">The drift query, explained ↗</a>
          <a href={`${REPO}/blob/main/docs/QUERIES.md`} target="_blank" rel="noopener">Every Cypher query ↗</a>
        </div>
        <div>
          <h5>Built with</h5>
          <span>FalkorDB</span>
          <span>FastAPI · Python</span>
          <span>React · TypeScript</span>
          <span>Cytoscape · GSAP</span>
        </div>
      </div>
      <div className="foot__bar mono">
        <span className="foot__live"><i aria-hidden />{stats ? `${sum(stats.nodes)} nodes · ${sum(stats.relationships)} relationships · ${drift.length} open drift` : "Connecting to the graph…"}</span>
        <span>Graph Hacks · Company Brain</span>
        <a href="#top">Back to top ↑</a>
      </div>
      <div className="foot__word" aria-hidden>DRIFT MONITOR</div>
    </footer>
  );
}
