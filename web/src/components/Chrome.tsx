import { AnimatePresence, motion, useScroll, useSpring } from "framer-motion";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useBrain } from "../lib/brain";
import { useStaticMode } from "../lib/ui";
import { LiveDot } from "./Toasts";

const SECTIONS = [["drift", "Drift"], ["graph-sec", "Graph"], ["ask", "Ask"], ["retro-sec", "Retro"], ["simulate", "Simulate"], ["coverage", "Risk"]];
const THEME_KEY = "drift-theme";

export function Loader() {
  const { loaded, total } = useBrain();
  const pct = Math.round((loaded / total) * 100);
  const still = useStaticMode();
  const [gone, setGone] = useState(still);
  useEffect(() => { if (pct >= 100) { const t = setTimeout(() => setGone(true), 350); return () => clearTimeout(t); } }, [pct]);
  return (
    <AnimatePresence>
      {!gone && (
        <motion.div className="loader" exit={{ opacity: 0 }} transition={{ duration: 0.6 }} aria-hidden>
          <div className="loader__inner">
            <div className="mono loader__label"><i className="sq sq--violet" />Initializing context graph</div>
            <div className="loader__pct">{pct}%</div>
            <div className="loader__bar"><span style={{ width: `${pct}%` }} /></div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function useTheme() {
  // dark is the default; ?theme= or the visitor's own choice (remembered) overrides it
  const initial = new URLSearchParams(location.search).get("theme") || (() => { try { return localStorage.getItem(THEME_KEY); } catch { return null; } })() || "dark";
  const [theme, setTheme] = useState<string>(initial);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  const toggle = () => {
    const next = theme === "light" ? "dark" : "light";
    try { localStorage.setItem(THEME_KEY, next); } catch { /* storage blocked */ }
    setTheme(next);
    window.dispatchEvent(new Event("themechange"));
  };
  return toggle;
}

export function Nav() {
  const { setPaletteOpen, newDrift, clearNew } = useBrain();
  const toggleTheme = useTheme();
  const [solid, setSolid] = useState(false);
  const [active, setActive] = useState("");
  const { scrollYProgress } = useScroll();
  const scaleX = useSpring(scrollYProgress, { stiffness: 140, damping: 30 });

  useEffect(() => {
    // the nav gets its blurred backdrop once the hero has scrolled away
    const onScroll = () => setSolid(window.scrollY > window.innerHeight * 0.8);
    onScroll();
    addEventListener("scroll", onScroll, { passive: true });
    const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && setActive(e.target.id)), { rootMargin: "-45% 0px -50% 0px" });
    const t = setTimeout(() => SECTIONS.forEach(([id]) => { const el = document.getElementById(id); if (el) io.observe(el); }), 800);
    return () => { removeEventListener("scroll", onScroll); io.disconnect(); clearTimeout(t); };
  }, []);
  useEffect(() => { if (active === "drift" && newDrift) { const t = setTimeout(clearNew, 1500); return () => clearTimeout(t); } }, [active, newDrift, clearNew]);

  return (
    <>
      <motion.div className="progress" style={{ scaleX, width: "100%" }} />
      <nav className={`nav ${solid ? "nav--solid" : ""}`}>
        <a className="brand" href="#top" aria-label="Drift Monitor home"><span className="brand__mark" /><span className="brand__word">DRIFT</span></a>
        <div className="nav__links mono">
          {SECTIONS.map(([id, label]) => (
            <a key={id} href={`#${id}`} className={active === id ? "active" : ""}>
              {label}
              {id === "drift" && newDrift > 0 && (
                <motion.span className="nav__badge" key={newDrift} initial={{ scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
                  aria-label={`${newDrift} new`}>{newDrift}</motion.span>
              )}
              {active === id && <motion.span className="nav__underline" layoutId="nav-underline" transition={{ type: "spring", stiffness: 420, damping: 36 }} />}
            </a>
          ))}
        </div>
        <div className="nav__right">
          <LiveDot />
          <button className="btn btn--sm" onClick={() => setPaletteOpen(true)} aria-label="Search the graph">
            <span className="search-label">Search</span><kbd style={{ margin: 0, color: "inherit", borderColor: "currentColor" }}>/</kbd>
          </button>
          <button className="icon-btn mono" onClick={toggleTheme} aria-label="Toggle theme">◐</button>
        </div>
      </nav>
    </>
  );
}

const REPO = "https://github.com/ayushagarwalhere/company_brain";

export function Footer() {
  const { refresh } = useBrain();
  const [busy, setBusy] = useState(false);
  const reset = async () => {
    setBusy(true);
    try { await api.resetDemo(); await refresh(); } finally { setBusy(false); }
  };
  return (
    <footer className="foot">
      <div className="foot__sky" aria-hidden />
      <div className="foot__cols mono">
        <div>
          <span className="foot__h">Project</span>
          <a href={REPO} target="_blank" rel="noopener">GitHub ↗</a>
          <a href={`${REPO}#readme`} target="_blank" rel="noopener">README ↗</a>
          <a href={`${REPO}#results`} target="_blank" rel="noopener">Benchmarks ↗</a>
          <a href={`${REPO}/blob/main/docs/demo.gif`} target="_blank" rel="noopener">Demo video ↗</a>
        </div>
        <div>
          <span className="foot__h">How it works</span>
          <a href={`${REPO}/blob/main/docs/EXPLAIN.md`} target="_blank" rel="noopener">Drift query, explained ↗</a>
          <a href={`${REPO}/blob/main/docs/QUERIES.md`} target="_blank" rel="noopener">Every Cypher query ↗</a>
        </div>
        <div>
          <span className="foot__h">Demo</span>
          <button className="foot__link" onClick={reset} disabled={busy} title="Rebuild the graph from source data (undoes simulated messages and drift actions)">
            {busy ? "Rebuilding graph…" : "Reset demo data"}
          </button>
          <span>Graph Hacks · Company Brain</span>
        </div>
      </div>
      <div className="foot__legal mono"><span>Every alert and answer is backed by a graph path</span><span>Built on FalkorDB</span></div>
      <motion.div className="wordmark" aria-hidden initial={{ opacity: 0, y: 40 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 1.2, ease: [0.2, 0.7, 0.1, 1] }}>
        DRIFT
      </motion.div>
    </footer>
  );
}
