import { useEffect, useRef, useState } from "react";
import { api, type TryLabel, type TryRecent, type TryResult, type TryState } from "../lib/api";
import { plural } from "../lib/ui";
import { ColumnGraph } from "./ColumnGraph";

/* "Try it on your own repo": paste a public GitHub repo; the server reads its recent issues, PRs and comments, builds
   a graph of its own with the same pipeline (rules extractor, no LLM) and answers what the graph shows. */

const EXAMPLE = "FalkorDB/FalkorDB";
const fromUrl = () => (typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("try"));
const who = (login: string | null | undefined) => (login ? <a className="link" href={`https://github.com/${login}`} target="_blank" rel="noreferrer">@{login}</a> : <span className="muted">—</span>);
const num = (id: string) => id.replace(/^GH-/, "#");
const day = (s: string | null | undefined) => (s || "").slice(0, 10);

function Stat({ label, value, hot }: { label: string; value: number; hot?: boolean }) {
  return <div className={hot && value ? "hot" : ""}><dt>{label}</dt><dd>{value.toLocaleString()}</dd></div>;
}

function Card({ title, sub, children, wide }: { title: string; sub?: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <section className={`try__card ${wide ? "try__card--wide" : ""}`}>
      <header><h3>{title}</h3>{sub && <span className="mono muted">{sub}</span>}</header>
      {children}
    </section>
  );
}

/** A flag we hand-checked before (the real-data label set): its verdict, so a known false positive says so. */
function Checked({ label }: { label: TryLabel | null }) {
  if (!label) return null;
  const bad = label.verdict === "false_positive";
  return (
    <p className={`try__checked mono ${bad ? "try__checked--bad" : ""}`}>
      Checked before (AI-made label, <a className="link" href="https://github.com/ayushagarwalhere/company_brain/blob/main/docs/LABEL_RECHECK.md" target="_blank" rel="noreferrer">re-check sheet</a>):{" "}
      <b>{bad ? `false positive${label.pattern ? ` (${label.pattern.replace("_", " ")})` : ""}` : label.verdict.replace("_", " ")}</b>{label.note ? `. ${label.note}` : ""}
    </p>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="try__empty">{children}</p>;
}

function Result({ r }: { r: TryResult }) {
  const [copied, setCopied] = useState(false);
  const mcp = `claude mcp add --transport http company-brain ${location.origin}/mcp --header "X-Org: ${r.org}"`;
  const c = r.counts;
  return (
    <div className="try__result">
      <div className="try__head">
        <div>
          <h3><a href={r.url} target="_blank" rel="noreferrer">{r.repo}</a></h3>
          {r.description && <p className="muted">{r.description}</p>}
        </div>
        <p className="mono muted">
          Read the {r.window.issues - (r.window.older_issues || 0)} most recently updated issues{r.window.older_issues ? ` (plus ${r.window.older_issues} older ones their PRs name)` : ""}, {r.window.prs} PRs and {r.window.comments} comments
          · {r.source === "live" ? `fetched ${day(r.fetched_at)}` : r.source} · built in {r.build_seconds}s with the rules extractor
        </p>
      </div>
      <dl className="try__stats">
        <Stat label="People" value={c.people} />
        <Stat label="Issue → PR links" value={c.chains} />
        <Stat label="Open issues, no PR" value={c.open_no_pr} />
        <Stat label="Decisions in comments" value={c.decisions} />
        <Stat label="Drift candidates" value={c.drift} hot />
      </dl>

      <div className="try__grid">
        <Card title="Who knows what" sub="per label: who opened, discussed, owns and fixed its issues">
          {r.areas.length ? (
            <ul className="try__list">
              {r.areas.map((a) => (
                <li key={a.label}>
                  <div className="try__row">
                    <a className="tag" href={a.url} target="_blank" rel="noreferrer">{a.label}</a>
                    <span className="mono muted">{a.issues} {plural(a.issues, "issue", "issues")} · {a.with_pr} with a PR</span>
                  </div>
                  <div className="try__people">{a.people.map((p, i) => <span key={p.person}>{i > 0 && " · "}{who(p.person)}</span>)}</div>
                </li>
              ))}
            </ul>
          ) : <Empty>No labels on these issues, so no areas: see the people on the right.</Empty>}
        </Card>

        <Card title="People" sub="what each one did in the window">
          <ul className="try__list">
            {r.people.slice(0, 10).map((p) => (
              <li key={p.person} className="try__row">
                <span>{who(p.person)}</span>
                <span className="mono muted">
                  {[p.prs && `${p.prs} ${plural(p.prs, "PR", "PRs")}${p.merged ? ` (${p.merged} merged)` : ""}`, p.issues && `${p.issues} ${plural(p.issues, "issue", "issues")}`,
                    p.comments && `${p.comments} ${plural(p.comments, "comment", "comments")}`, p.reviews && `${p.reviews} ${plural(p.reviews, "review", "reviews")}`]
                    .filter(Boolean).join(" · ")}
                  {p.areas.length > 0 && <> · <span className="try__areas">{p.areas.join(", ")}</span></>}
                </span>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Issue → PR chains" sub={`${c.chains} links, newest first: PR text that names the issue ("fixes #12")`} wide>
          {r.chains.length ? (
            <ul className="try__list">
              {r.chains.slice(0, 12).map((ch) => (
                <li key={`${ch.issue}-${ch.pr}`} className="try__chain">
                  <span>{who(ch.opened_by)} opened <a className="link" href={ch.issue_url} target="_blank" rel="noreferrer">{num(ch.issue)}</a> {ch.issue_title}</span>
                  <span className="try__arrow mono">←</span>
                  <span><a className="link" href={ch.pr_url} target="_blank" rel="noreferrer">PR #{ch.pr}</a> by {who(ch.pr_by)} <span className={`tag ${ch.pr_state === "merged" ? "tag--inv" : ""}`}>{ch.pr_state}</span></span>
                </li>
              ))}
            </ul>
          ) : <Empty>No PR in the window names an issue in the window.</Empty>}
        </Card>

        <Card title="Open issues no PR touches" sub={`${c.open_no_pr} of ${c.open_issues} open issues · most discussed first`}>
          {r.no_pr.length ? (
            <ul className="try__list">
              {r.no_pr.slice(0, 8).map((t) => (
                <li key={t.issue} className="try__row">
                  <span><a className="link" href={t.url} target="_blank" rel="noreferrer">{num(t.issue)}</a> {t.title}</span>
                  <span className="mono muted">{t.comments} {plural(t.comments, "comment", "comments")}{t.assignee ? <> · {who(t.assignee)}</> : " · unassigned"}</span>
                </li>
              ))}
            </ul>
          ) : <Empty>Every open issue in the window has a PR naming it.</Empty>}
          <p className="try__fine mono muted">Within the window: a PR older than it may still reference one of these.</p>
        </Card>

        <Card title="Decisions in comments" sub="candidates from the rules extractor: read them">
          {r.decisions.length ? (
            <ul className="try__list">
              {r.decisions.map((d) => (
                <li key={d.requirement}>
                  <div className="try__row">
                    <span>{who(d.by)} on <a className="link" href={d.issue_url} target="_blank" rel="noreferrer">{num(d.issue)}</a></span>
                    <span className="mono muted">{day(d.at)}{d.drift ? " · drift" : d.implemented_by.length ? ` · PR #${d.implemented_by.join(", #")}` : ""}</span>
                  </div>
                  <blockquote className="try__quote"><a href={d.url} target="_blank" rel="noreferrer">{d.comment.slice(0, 280)}</a></blockquote>
                  <Checked label={d.label} />
                </li>
              ))}
            </ul>
          ) : <Empty>No explicitly worded change of plan in these comments ("decision:", "let's switch to", "we'll support"). That's common on real repos: see the note below.</Empty>}
        </Card>

        <Card title="Drift" sub="a decision in the comments the issue body never caught up with" wide>
          {r.drift.length ? (
            <ul className="try__list">
              {r.drift.map((d) => (
                <li key={`${d.issue}-${d.comment_url}`}>
                  <div className="try__row">
                    <span><a className="link" href={d.url} target="_blank" rel="noreferrer">{num(d.issue)}</a> {d.title}</span>
                    <span className="mono muted">{who(d.by)} · {day(d.at)}</span>
                  </div>
                  <blockquote className="try__quote"><a href={d.comment_url} target="_blank" rel="noreferrer">{d.comment.slice(0, 280)}</a></blockquote>
                  <Checked label={d.label} />
                </li>
              ))}
            </ul>
          ) : <Empty>None found in this window. Drift on real text is the weakest part (see the note): empty usually means nothing explicitly worded, not that every issue is current.</Empty>}
        </Card>
      </div>

      {r.graph.nodes.length > 0 && (
        <div className="try__graph">
          <ColumnGraph data={r.graph} headers={{ 0: "People", 1: "Decisions", 2: "Issues", 3: "Pull requests" }} note="The newest issue → PR chains and decisions, as stored in the repo's graph. Click a node to light what it touches." />
        </div>
      )}

      <p className="try__note">{r.note}</p>

      <div className="try__next">
        <a className="btn" href={`/?app&org=${encodeURIComponent(r.org)}&repo=${encodeURIComponent(r.repo)}`}>Open the full dashboard on {r.repo} →</a>
        <div className="try__mcp">
          <span className="mono muted">Give your coding agent this repo's context (MCP):</span>
          <code>{mcp}</code>
          <button className="btn btn--ghost btn--sm" onClick={() => { void navigator.clipboard?.writeText(mcp); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>{copied ? "Copied" : "Copy"}</button>
        </div>
      </div>
    </div>
  );
}

/** The chapter body on the overview page (Landing wraps it in its chapter frame). */
export function TryRepo() {
  const [text, setText] = useState(fromUrl() || "");
  const [state, setState] = useState<TryState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [recent, setRecent] = useState<TryRecent[]>([]);
  const [tick, setTick] = useState(0);
  const poll = useRef<number | null>(null);

  const stop = () => { if (poll.current) { clearInterval(poll.current); poll.current = null; } };
  const show = (s: TryState) => {
    setState(s);
    if (s.state === "ready" || s.state === "error") {
      stop();
      if (s.state === "ready") {
        const u = new URL(location.href);
        u.searchParams.set("try", s.repo);
        u.hash = "try";
        history.replaceState(null, "", u);
        void api.tryRecent().then((x) => setRecent(x.repos)).catch(() => undefined);
      }
    }
  };
  const run = async (repo: string) => {
    stop(); setErr(null); setText(repo);
    setState({ state: "queued", repo, org: "", step: "Starting" });
    try {
      const s = await api.tryRepo(repo);
      show(s);
      if (s.state === "queued" || s.state === "running") {
        poll.current = window.setInterval(async () => {
          setTick((t) => t + 1);
          try { show(await api.tryStatus(s.repo)); } catch (e) { stop(); setErr((e as Error).message); setState(null); }
        }, 1500);
      }
    } catch (e) { setErr((e as Error).message); setState(null); }
  };

  useEffect(() => {
    void api.tryRecent().then((x) => setRecent(x.repos)).catch(() => undefined);
    const q = fromUrl();
    if (q) {
      void run(q);
      setTimeout(() => document.getElementById("try")?.scrollIntoView({ behavior: "smooth" }), 400);
    }
    return stop;
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const busy = state && (state.state === "queued" || state.state === "running");
  const examples = [EXAMPLE, ...recent.map((r) => r.repo).filter((r) => r.toLowerCase() !== EXAMPLE.toLowerCase())].slice(0, 6);
  const ready = new Set(recent.map((r) => r.repo.toLowerCase()));
  return (
    <div className="try">
      <form className="try__form" onSubmit={(e) => { e.preventDefault(); if (text.trim()) void run(text.trim()); }}>
        <input className="field" value={text} onChange={(e) => setText(e.target.value)} placeholder="owner/repo or https://github.com/owner/repo"
          aria-label="Public GitHub repo" autoComplete="off" spellCheck={false} />
        <button className="btn" disabled={!!busy || !text.trim()}>{busy ? "Building…" : "Build its graph →"}</button>
      </form>
      <div className="try__examples mono">
        <span className="muted">Try</span>
        {examples.map((x) => (
          <button key={x} type="button" className="try__chip" onClick={() => void run(x)} disabled={!!busy}>
            {x}{ready.has(x.toLowerCase()) && <span className="try__ready">ready</span>}
          </button>
        ))}
      </div>
      <p className="try__fine mono muted">
        Public repos only. Reads the 150 most recently updated issues, 100 PRs and up to 400 comments; bots are left out.
        Nothing is written to GitHub. Results are kept for 12 hours.
      </p>
      {err && <p className="connect__err">{err}</p>}
      {busy && (
        <div className="try__progress mono" aria-live="polite">
          <span className="typing"><i /><i /><i /></span>
          <span>{state?.step || "Working"}…</span>
          <span className="muted">{state?.since ? `${Math.max(0, Math.round(Date.now() / 1000 - state.since))}s` : ""}</span>
          <span hidden>{tick}</span>
        </div>
      )}
      {state?.state === "error" && <p className="connect__err">{state.error}</p>}
      {state?.state === "ready" && state.result && <Result r={state.result} />}
    </div>
  );
}
