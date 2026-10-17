import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { api, type Person, type SearchHit } from "../lib/api";
import { useBrain } from "../lib/brain";
import { day, isExternal } from "../lib/ui";

/** "/" or Ctrl+K: FalkorDB full-text search over people, tickets, PRs, docs, messages. */
export function CommandPalette() {
  const { paletteOpen, setPaletteOpen, openPerson, focusOn } = useBrain();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [idx, setIdx] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = /INPUT|TEXTAREA|SELECT/.test((document.activeElement as HTMLElement)?.tagName || "");
      if ((e.key === "/" && !typing) || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k")) { e.preventDefault(); setPaletteOpen(true); }
      if (e.key === "Escape") { setPaletteOpen(false); openPerson(null); }
    };
    addEventListener("keydown", onKey);
    const deep = new URLSearchParams(location.search).get("q");
    if (deep) { setPaletteOpen(true); setQ(deep); }
    return () => removeEventListener("keydown", onKey);
  }, [setPaletteOpen, openPerson]);

  useEffect(() => { if (paletteOpen) setTimeout(() => input.current?.focus(), 20); }, [paletteOpen]);
  useEffect(() => {
    if (!q.trim()) { setHits([]); return; }
    const t = setTimeout(() => void api.search(q).then((h) => { setHits(h); setIdx(0); }), 140);
    return () => clearTimeout(t);
  }, [q]);

  const choose = (h: SearchHit) => {
    setPaletteOpen(false);
    if (h.type === "Person") openPerson(h.id);
    else focusOn(h.feature, h.id);
  };

  return (
    <AnimatePresence>
      {paletteOpen && (
        <motion.div className="palette" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(e) => e.target === e.currentTarget && setPaletteOpen(false)}>
          <motion.div className="palette__box" role="dialog" aria-label="Search" initial={{ y: 20, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 10, opacity: 0 }} transition={{ duration: 0.3, ease: [0.2, 0.7, 0.1, 1] }}>
            <div className="palette__input">
              <span className="mono">⌕</span>
              <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search people, tickets, PRs, docs, messages…" autoComplete="off"
                onKeyDown={(e) => {
                  if (e.key === "ArrowDown") { setIdx((i) => Math.min(hits.length - 1, i + 1)); e.preventDefault(); }
                  if (e.key === "ArrowUp") { setIdx((i) => Math.max(0, i - 1)); e.preventDefault(); }
                  if (e.key === "Enter" && hits[idx]) choose(hits[idx]);
                }} />
              <kbd className="mono">esc</kbd>
            </div>
            <div className="palette__hint mono">FalkorDB full-text index · stemming + prefix match</div>
            <ul className="palette__list">
              {!q.trim() && <li className="palette__empty">Try “breach email”, “maya”, “BD-101”, “#7”, “PRD”…</li>}
              {q.trim() && !hits.length && <li className="palette__empty">No matches.</li>}
              {hits.map((h, i) => (
                <li key={h.id} className={i === idx ? "on" : ""} onMouseEnter={() => setIdx(i)} onClick={() => choose(h)}>
                  <span className="mono t">{h.type}</span>
                  <span className="lab">{h.type === "Message" ? h.label : `${h.id} · ${h.label || ""}`}</span>
                  <span className="go mono">{h.type === "Person" ? "profile" : h.feature ? "graph" : "neighbours"} ↵</span>
                </li>
              ))}
            </ul>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** Person profile: who owns / shipped / decided / wrote what, and what they know about. */
export function PersonDrawer() {
  const { person, openPerson, version } = useBrain();
  const [p, setP] = useState<Person | null>(null);
  useEffect(() => {
    const deep = new URLSearchParams(location.search).get("person");
    if (deep) openPerson(deep);
  }, [openPerson]);
  useEffect(() => { setP(null); if (person) void api.person(person).then(setP).catch(() => openPerson(null)); }, [person, version, openPerson]);
  const max = Math.max(1, ...(p?.features.map((f) => f.score) || [1]));
  return (
    <AnimatePresence>
      {person && (
        <motion.aside className="drawer" aria-label="Person profile" initial={{ x: 60, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: 60, opacity: 0 }} transition={{ duration: 0.45, ease: [0.2, 0.7, 0.1, 1] }}>
          <button className="btn btn--ghost btn--sm drawer__close" onClick={() => openPerson(null)}>Close</button>
          {!p ? <p className="muted">Loading…</p> : (<>
            <span className="mono muted">Person · {p.id}</span>
            <h3>{p.name}</h3>
            <div className="muted" style={{ marginBottom: 18 }}>{p.role} · {p.messages} messages</div>
            {p.drift_caused.map((d) => <div key={d.requirement} className="note">Their decision on {day(d.changed_at)} (“{d.requirement_text}”) never reached {d.ticket}.</div>)}
            {p.stale_work.map((d) => <div key={"s" + d.requirement} className="note">Owns {d.ticket}, which is stale: {d.changed_by} changed it on {day(d.changed_at)}.</div>)}
            <div className="mono kicker">Knows about</div>
            <ul>{p.features.map((f) => <li key={f.id} className="fbar"><b>{f.name}</b><div className="bar"><span style={{ width: `${Math.round(f.score / max * 100)}%` }} /></div><span className="mono">{f.score}</span></li>)}
              {!p.features.length && <li>No feature involvement</li>}</ul>
            <div className="mono kicker">Owns · {p.owns.length}</div>
            <ul>{p.owns.map((t) => <li key={t.ticket}><b>{t.ticket}</b> {t.title} <span className="muted">· {t.role ? `${t.role} · ` : ""}{t.state}{t.feature ? ` · ${t.feature}` : ""}</span></li>)}{!p.owns.length && <li>No tickets created or assigned</li>}</ul>
            <div className="mono kicker">Shipped · {p.prs.length}</div>
            <ul>{p.prs.map((x) => <li key={x.pr}>{isExternal(x.url) ? <a href={x.url} target="_blank" rel="noopener">#{x.pr}</a> : `#${x.pr}`} {x.title} <span className="muted">· {x.tickets.join(", ") || "no ticket"}</span></li>)}{!p.prs.length && <li>No PRs</li>}</ul>
            <div className="mono kicker">Wrote · {p.docs.length}</div>
            <ul>{p.docs.map((x) => <li key={x.id}><b>{x.id}</b> {x.title} <span className="muted">· updated {day(x.updated)} · {x.tickets.join(", ")}</span></li>)}{!p.docs.length && <li>No docs</li>}</ul>
            <div className="mono kicker">Decided · {p.decisions.length}</div>
            <ul>{p.decisions.map((d) => <li key={d.id}><span className="muted">{day(d.at)} · {d.ticket}{d.kind === "dismissal" ? " · dismissal" : ""}</span><br />{d.text}</li>)}{!p.decisions.length && <li>No decisions recorded</li>}</ul>
          </>)}
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
