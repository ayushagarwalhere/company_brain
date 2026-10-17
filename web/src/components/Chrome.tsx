import { useEffect, useState } from "react";
import { useBrain } from "../lib/brain";
import { LiveDot } from "./Toasts";
import { DEMO_HREF } from "../lib/routes";
import { TOUR_HREF } from "./Tour";

export const SECTIONS = [["drift", "Drift"], ["graph-sec", "Graph"], ["impact", "Impact"], ["simulate", "Monitor"], ["ask", "Ask"], ["docs-sec", "Docs"], ["retro-sec", "Retro"], ["coverage", "Risk"]];

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

export function Footer() {
  return (
    <footer className="foot">
      <div className="foot__in">
        <div>
          <a className="brand" href="#top"><span className="brand__mark" />Drift Monitor</a>
          <p>A FalkorDB context graph of chat, tickets, PRs and docs. Every alert and answer is backed by a graph path.</p>
        </div>
        <div>
          <h5>Project</h5>
          <a href={REPO} target="_blank" rel="noopener">GitHub ↗</a>
          <a href={`${REPO}#readme`} target="_blank" rel="noopener">README ↗</a>
          <a href={`${REPO}/blob/main/docs/RESULTS.md`} target="_blank" rel="noopener">Benchmarks ↗</a>
        </div>
        <div>
          <h5>How it works</h5>
          <a href={`${REPO}/blob/main/docs/EXPLAIN.md`} target="_blank" rel="noopener">Drift query, explained ↗</a>
          <a href={`${REPO}/blob/main/docs/QUERIES.md`} target="_blank" rel="noopener">Every Cypher query ↗</a>
        </div>
        <div>
          <h5>Demo</h5>
          <a href="/">Overview</a>
          <a href={DEMO_HREF}>Open the demo</a>
          <a href={TOUR_HREF}>Guided tour</a>
        </div>
      </div>
      <div className="foot__word" aria-hidden>DRIFT</div>
    </footer>
  );
}
