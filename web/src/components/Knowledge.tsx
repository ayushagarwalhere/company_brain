import { AnimatePresence, motion, useInView } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AskResult, type Doc, type DocSync, type WhoAmI } from "../lib/api";
import { useBrain } from "../lib/brain";
import { day, PEOPLE, plural } from "../lib/ui";
import { Avatar } from "./Evidence";
import { Sources } from "./Panels";
import { Section } from "./Section";

/* Docs & access: (1) a doc changes -> only the changed chunks are re-embedded and its graph edges follow the text;
   (2) the same question asked as three people -> each gets only what they may see. Everything here is the real API:
   the docs webhook (POST /api/ingest/doc) and the agent (POST /api/ask) with the viewer in X-User. */

/** "leads, hr + arjun" from an access list; [] = everyone in the company. */
export function aclLabel(acl: string[]) {
  if (!acl.length) return "Everyone";
  const groups = acl.filter((g) => !g.includes(":"));
  const people = acl.filter((g) => g.includes(":")).map((g) => g.split(":")[1]);
  return [groups.join(", "), people.join(", ")].filter(Boolean).join(" + ");
}

const SHARING: { k: string; label: string; acl: (author: string) => string[] }[] = [
  { k: "everyone", label: "Everyone", acl: () => [] },
  { k: "leads", label: "Leads and HR", acl: () => ["leads", "hr"] },
  { k: "author", label: "Only the author", acl: (a) => [`person:${a}`] },
];
const sharingOf = (acl: string[]) =>
  !acl.length ? "everyone" : acl.includes("leads") ? "leads" : acl.every((g) => g.startsWith("person:")) ? "author" : "custom";

type Part = { id: string; chars: number; status: "idle" | DocSync["sync"]["parts"][number]["status"] };

/** The doc's entries in the vector index, sized by length; after a save, which were re-embedded, kept or removed. */
function ChunkStrip({ parts }: { parts: Part[] }) {
  return (
    <div className="chunks" role="list" aria-label="Chunks in the vector index">
      {parts.map((c, i) => (
        <motion.div key={`${c.id}-${c.status}`} role="listitem" className={`chunk chunk--${c.status}`} style={{ flexGrow: Math.max(c.chars, 80) }}
          initial={c.status === "embedded" ? { opacity: 0.15, y: 4 } : false} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + i * 0.08 }}>
          <span>#{c.id.split("#")[1]}</span>
          <small>{c.status === "idle" ? `${c.chars} chars` : c.status === "embedded" ? "re-embedded" : c.status}</small>
        </motion.div>
      ))}
    </div>
  );
}

function DocEditor() {
  const { actor, setActor, drift, features, version, refresh } = useBrain();
  const [docs, setDocs] = useState<Doc[]>([]);
  const [sel, setSel] = useState("DOC-1");
  const [text, setText] = useState("");
  const [share, setShare] = useState("everyone");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ out: DocSync; before: Doc; after: Doc | null } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const original = useRef<Record<string, string>>({});
  const loadedFor = useRef<string | null>(null);

  // the list is fetched AS the person editing: a doc they may not see is simply not in it
  const load = useCallback(() => api.docs(actor).then((d) => { setDocs(d); return d; }), [actor]);
  useEffect(() => { void load().catch((e) => setErr((e as Error).message)); }, [load, version]);

  const doc = docs.find((d) => d.id === sel) || null;
  useEffect(() => { if (docs.length && !doc) setSel(docs[0].id); }, [docs, doc]);
  useEffect(() => {
    if (!doc || loadedFor.current === doc.id) return;
    loadedFor.current = doc.id;
    original.current[doc.id] ??= doc.text;
    setText(doc.text); setShare(sharingOf(doc.acl)); setRes(null); setErr(null);
  }, [doc]);

  const other = doc && features.flatMap((f) => f.tickets).find((t) => !doc.tickets.includes(t));
  const decision = doc && drift.find((d) => doc.stale_for.includes(d.ticket));
  const presets: [string, () => void][] = doc ? [
    ...(decision ? [[`Write the ${decision.ticket} decision in`, () => setText((t) => `${t.trimEnd()}\n\n## Decision (chat, ${day(decision.changed_at)})\n${decision.requirement_text}`)] as [string, () => void]] : []),
    ...(other ? [[`Mention ${other}`, () => setText((t) => `${t.trimEnd()}\n\nRelated: ${other}.`)] as [string, () => void]] : []),
    ["Restore the original", () => setText(original.current[doc.id] ?? doc.text)],
  ] : [];

  const save = async () => {
    if (!doc) return;
    setBusy(true); setErr(null);
    const want = SHARING.find((s) => s.k === share);
    const acl = want && share !== sharingOf(doc.acl) ? want.acl(doc.author || actor) : undefined;
    try {
      const [out] = await Promise.all([api.updateDoc(doc.id, text, actor, acl), new Promise((ok) => setTimeout(ok, 450))]);
      const fresh = await load();
      setRes({ out, before: doc, after: fresh.find((d) => d.id === doc.id) || null });
      void refresh();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  const parts: Part[] = res ? res.out.sync.parts : (doc?.chunks || []).map((c) => ({ ...c, status: "idle" }));
  const added = res ? res.out.sync.mentions.filter((t) => !res.before.tickets.includes(t)) : [];
  const dirty = !!doc && (text !== doc.text || share !== sharingOf(doc.acl));

  return (
    <div className="kdoc">
      <div>
        <ul className="kdoc__list">
          {docs.map((d) => (
            <li key={d.id}>
              <button className={d.id === sel ? "on" : ""} onClick={() => setSel(d.id)}>
                <span className="mono">{d.id}</span>
                <b>{d.title}</b>
                <small>{d.author} · {d.chunks.length} {plural(d.chunks.length, "chunk", "chunks")}</small>
                <span className="kdoc__tags">
                  <span className={`tag ${d.acl.length ? "tag--inv" : ""}`}>{d.acl.length ? `Restricted · ${aclLabel(d.acl)}` : "Everyone"}</span>
                  {d.stale_for.length > 0 && <span className="tag tag--dash">Stale · {d.stale_for.join(", ")}</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
        <p className="kdoc__note mono">
          Listed as <b>{actor}</b> sees them.{" "}
          {actor === "zara" ? "The confidential doc isn't here: the server never sent it." : "Switch to zara and the confidential doc disappears: not hidden, not counted, never sent."}
        </p>
      </div>

      <div className="kdoc__ed">
        {!doc ? <p className="muted">{err || "Loading docs…"}</p> : <>
          <div className="kdoc__head">
            <h3>{doc.title}</h3>
            <div className="kdoc__meta mono">
              <span>{doc.id}</span><span>by {doc.author}</span><span>updated {day(doc.updated)}</span>
              <span>MENTIONS {doc.tickets.join(", ") || "no ticket"}</span>
            </div>
          </div>
          <div>
            <span className="kicker" style={{ marginTop: 0 }}>Vector index · {parts.filter((p) => p.status !== "removed").length} {plural(parts.length, "chunk", "chunks")} · {res?.out.sync.embedder || doc.embedder}</span>
            <ChunkStrip parts={parts} />
          </div>
          <textarea className="field" rows={11} value={text} onChange={(e) => setText(e.target.value)} aria-label={`Text of ${doc.id}`} spellCheck={false} />
          <div className="kdoc__bar">
            <label className="mono">Editing as
              <select className="sel" value={actor} onChange={(e) => setActor(e.target.value)} aria-label="Editing as">{PEOPLE.map((p) => <option key={p}>{p}</option>)}</select>
            </label>
            <label className="mono">Shared with
              <select className="sel" value={share} onChange={(e) => setShare(e.target.value)} aria-label="Shared with">
                {SHARING.map((s) => <option key={s.k} value={s.k}>{s.label}</option>)}
                {sharingOf(doc.acl) === "custom" && <option value="custom">{aclLabel(doc.acl)}</option>}
              </select>
            </label>
            <button className="btn btn--sm" disabled={busy || !dirty} onClick={() => void save()}>{busy ? "Syncing…" : "Save and sync"}</button>
          </div>
          <div className="tries" style={{ margin: 0 }}>
            {presets.map(([label, fn]) => <button key={label} disabled={busy} onClick={fn}>{label}</button>)}
          </div>
          {err && <p className="warn">{err}</p>}
          <AnimatePresence>
            {res && (
              <motion.div className="sync" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                <div>
                  <span>Vectors</span>
                  <p><b>{res.out.sync.embedded}</b> re-embedded · <b>{res.out.sync.kept}</b> kept · <b>{res.out.sync.removed}</b> removed
                    <span className="muted"> · unchanged chunks keep their vector</span></p>
                </div>
                <div>
                  <span>Graph edges</span>
                  <p className="sync__edges">
                    {res.out.sync.mentions.map((t) => <span key={t} className={`tag ${added.includes(t) ? "tag--inv" : ""}`}>{added.includes(t) ? "+ " : ""}MENTIONS {t}</span>)}
                    {res.out.sync.mentions_dropped.map((t) => <span key={t} className="tag tag--gone">− MENTIONS {t}</span>)}
                    {!res.out.sync.mentions.length && !res.out.sync.mentions_dropped.length && <span className="muted">no ticket links</span>}
                  </p>
                </div>
                {res.out.no_longer_stale && (
                  <div><span>Drift</span><p>No longer stale for {res.before.stale_for.join(", ")}: it was edited after the decision.</p></div>
                )}
                {res.after && aclLabel(res.after.acl) !== aclLabel(res.before.acl) && (
                  <div><span>Access</span><p>Now shared with <b>{aclLabel(res.after.acl)}</b>. Search, the agent and every API response follow at once.</p></div>
                )}
                {!res.after && <div><span>Access</span><p>{actor} can no longer see this doc, so it left their list.</p></div>}
              </motion.div>
            )}
          </AnimatePresence>
        </>}
      </div>
    </div>
  );
}

const VIEWERS: { who: string | null; sub: string }[] = [
  { who: "zara", sub: "QA engineer" },
  { who: "maya", sub: "Product manager · lead" },
  { who: null, sub: "not signed in" },
];
const QUESTIONS = ["What is everyone's salary?", "What is the salary band for a Senior Engineer?", "What does the theming RFC say about dark mode?"];
const DENIED = "I don't have information on that you can access.";
const key = (who: string | null) => who || "anonymous";

function WhoSees() {
  const [q, setQ] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [res, setRes] = useState<Record<string, AskResult | Error>>({});
  const [grants, setGrants] = useState<Record<string, WhoAmI>>({});
  const ref = useRef<HTMLDivElement>(null);
  const seen = useInView(ref, { once: true, margin: "-120px" });

  const run = useCallback(async (question: string) => {
    setAsked(question); setQ(""); setRes({});
    await Promise.all(VIEWERS.map(async ({ who }) => {
      try { const r = await api.ask(question, who); setRes((m) => ({ ...m, [key(who)]: r })); }
      catch (e) { setRes((m) => ({ ...m, [key(who)]: e as Error })); }
    }));
  }, []);
  // answered as soon as it scrolls into view, so the comparison is never empty
  useEffect(() => { if (seen && !asked) void run(QUESTIONS[0]); }, [seen, asked, run]);
  useEffect(() => {
    VIEWERS.forEach(({ who }) => void api.whoami(who).then((w) => setGrants((m) => ({ ...m, [key(who)]: w }))).catch(() => undefined));
  }, []);
  const busy = !!asked && Object.keys(res).length < VIEWERS.length;

  return (
    <div ref={ref} id="who-sees">
      <div className="tries">
        {QUESTIONS.map((x) => <button key={x} disabled={busy} className={x === asked ? "on" : ""} onClick={() => void run(x)}>{x}</button>)}
      </div>
      <div className="kask">
        {VIEWERS.map(({ who, sub }) => {
          const r = res[key(who)];
          const body = r && !(r instanceof Error) ? r.answer.split(/\n\n\**Evidence:?\**/)[0].replace(/\*\*/g, "") : "";
          const denied = body.startsWith(DENIED);
          return (
            <div key={key(who)} className="kask__col">
              <div className="kask__who">
                <Avatar name={who || "?"} size={34} />
                <div><b>{key(who)}</b><small>{sub}</small></div>
              </div>
              <div className="kask__grants mono" title="What can unlock a document for this person">
                grants: {grants[key(who)]?.grants.join(" · ") || "…"}
              </div>
              <div className="kask__body">
                {asked && <div className="q">{asked}</div>}
                {asked && !r && <span className="typing" aria-label="Asking"><i /><i /><i /></span>}
                {r instanceof Error && <p className="warn">{r.message}</p>}
                {r && !(r instanceof Error) && (
                  <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} style={{ display: "grid", gap: 12 }}>
                    <div className={`a ${denied ? "a--deny" : ""}`}>{body.length > 420 ? `${body.slice(0, 420)}…` : body}</div>
                    <Sources res={r} />
                    <span className="mono muted">
                      {denied ? "nothing it may see matched" : `${r.tool_calls.length} tool ${plural(r.tool_calls.length, "call", "calls")} · ${r.paths.length} ${plural(r.paths.length, "path", "paths")}`}
                    </span>
                  </motion.div>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <form className="prompt kask__prompt" onSubmit={(e) => { e.preventDefault(); if (q.trim()) void run(q.trim()); }}>
        <span className="mono">&gt;</span>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask anything, as all three people at once…" autoComplete="off" />
        <button className="btn btn--sm" disabled={busy || !q.trim()}>Ask as all three</button>
      </form>
      <div className="vision__notes">
        <div><b>1 · In the query</b><p>The vector search filters chunks by the viewer's grants inside FalkorDB, in the same query that finds them.</p></div>
        <div><b>2 · In every agent tool</b><p>Rows and paths about a doc the viewer can't see are dropped before the rules agent or the LLM reads them. A model can't leak what it never received.</p></div>
        <div><b>3 · On every response</b><p>Each API response is checked again for the viewer, including endpoints added later. Counts too: a hidden doc isn't counted.</p></div>
      </div>
    </div>
  );
}

export function DocsSection() {
  return (
    <Section id="docs-sec" index="06" title="Docs & access"
      intro="Docs live in the graph as chunks in a FalkorDB vector index, one hop from their authors and tickets. Edit one: only the chunks that changed are re-embedded, and its ticket links follow the new text. Then ask the same question as three different people.">
      <span className="kicker" style={{ marginTop: 0 }}>When a doc changes</span>
      <DocEditor />
      <span className="kicker" style={{ marginTop: 56 }}>Who can see what</span>
      <WhoSees />
    </Section>
  );
}
