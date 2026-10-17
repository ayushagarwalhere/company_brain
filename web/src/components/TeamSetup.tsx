import { useCallback, useEffect, useState } from "react";
import { api, type TeamPerson, type TeamStatus } from "../lib/api";
import { useBrain } from "../lib/brain";
import { plural } from "../lib/ui";
import { Section } from "./Section";

/* A connected team's own setup (api/team.py): what's connected, its GitHub repo, the last sync, and Who's who.
   Shown only on a team's dashboard (?app&org=slack-… / discord-…), never on the demo company. */

const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "never");

function GithubCard({ st, onChange }: { st: TeamStatus; onChange: () => void }) {
  const [repo, setRepo] = useState(st.github?.repo || "");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState(!st.github);
  const gh = st.status.github;
  const save = async () => {
    setBusy(true); setErr(null);
    try { await api.connectGithub(repo.trim(), token.trim()); setToken(""); setEditing(false); onChange(); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="connect__card">
      <div className="connect__top">
        <span className="connect__mark" aria-hidden>GH</span>
        <div><h3>Work · GitHub</h3><span className="mono muted">PRs · issues → tickets (optional with Jira or Linear)</span></div>
        <span className={`tag ${st.github ? "tag--inv" : ""}`}>{st.github ? "Connected" : "Not connected"}</span>
      </div>
      <p>Drift needs your tickets and pull requests. Each issue becomes a ticket (a changed body becomes its next version), each comment counts like a chat message, and every author is matched to the same person as in Slack.</p>
      {editing ? (
        <form className="setup__form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <label className="mono">Repository<input className="field" placeholder="owner/name" value={repo} onChange={(e) => setRepo(e.target.value)} required /></label>
          <label className="mono">Token {st.github?.token_set && <span className="muted">(saved; leave empty to keep it)</span>}
            <input className="field" type="password" placeholder="github_pat_… (read-only: Issues, Pull requests, Metadata)" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" />
          </label>
          <div className="connect__row">
            <button className="btn btn--sm" disabled={busy || !repo.trim()}>{busy ? "Checking…" : "Connect and sync"}</button>
            {st.github && <button type="button" className="link" onClick={() => setEditing(false)}>Cancel</button>}
          </div>
          <p className="connect__note mono">A public repo works without a token (60 requests an hour). The token stays on the server and is never shown again.</p>
        </form>
      ) : (
        <div className="setup__facts">
          <div><span className="mono muted">Repository</span><b>{st.github!.repo}</b></div>
          <div><span className="mono muted">Last pass</span><b>{when(st.status.at)}</b></div>
          {gh && <div><span className="mono muted">Last pass read</span><b>{gh.tickets} {plural(gh.tickets, "issue", "issues")} · {gh.prs} PRs · {gh.comments} comments · {gh.new_versions} new {plural(gh.new_versions, "version", "versions")}</b></div>}
          <button className="link" onClick={() => setEditing(true)}>Change repository or token</button>
        </div>
      )}
      {err && <p className="connect__err">{err}</p>}
    </div>
  );
}

type Field = { key: string; label: string; placeholder: string; secret?: boolean };
const TRACKERS: Record<"jira" | "linear", { title: string; mark: string; sub: string; about: string; fields: Field[]; note: string }> = {
  jira: {
    title: "Tickets · Jira", mark: "J", sub: "one project · full description history",
    about: "Each issue becomes a ticket with every description version from Jira's changelog (who wrote it, when), and its comments count like chat messages.",
    fields: [
      { key: "site", label: "Site", placeholder: "acme.atlassian.net" },
      { key: "email", label: "Account email", placeholder: "you@acme.io" },
      { key: "token", label: "API token", placeholder: "id.atlassian.com → Security → API tokens", secret: true },
      { key: "project", label: "Project key", placeholder: "ACME" },
    ],
    note: "Read access to the project is enough. The token stays on the server. Keys of up to five letters (ACME-12) are also recognised in chat.",
  },
  linear: {
    title: "Tickets · Linear", mark: "L", sub: "one team · comments · edits dated",
    about: "Each issue becomes a ticket (the current text dated to its last edit, later edits added as versions), and its comments count like chat messages.",
    fields: [
      { key: "token", label: "API key", placeholder: "lin_api_… (Settings → Security & access → API keys)", secret: true },
      { key: "team", label: "Team key", placeholder: "ENG" },
    ],
    note: "A personal API key with read access. It stays on the server and is never shown again.",
  },
};

function TrackerCard({ kind, st, onChange }: { kind: "jira" | "linear"; st: TeamStatus; onChange: () => void }) {
  const t = TRACKERS[kind];
  const saved = kind === "jira" ? st.jira : st.linear;
  const [vals, setVals] = useState<Record<string, string>>(() => ({ site: st.jira?.site || "", email: st.jira?.email || "", project: st.jira?.project || "", team: st.linear?.team || "", token: "" }));
  const [editing, setEditing] = useState(!saved);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const pass = st.status[kind];
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      if (kind === "jira") await api.connectJira(vals.site.trim(), vals.email.trim(), vals.token.trim(), vals.project.trim());
      else await api.connectLinear(vals.token.trim(), vals.team.trim());
      setVals((v) => ({ ...v, token: "" })); setEditing(false); onChange();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="connect__card">
      <div className="connect__top">
        <span className="connect__mark" aria-hidden>{t.mark}</span>
        <div><h3>{t.title}</h3><span className="mono muted">{t.sub}</span></div>
        <span className={`tag ${saved ? "tag--inv" : ""}`}>{saved ? "Connected" : "Not connected"}</span>
      </div>
      <p>{t.about}</p>
      {editing ? (
        <form className="setup__form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          {t.fields.map((f) => (
            <label key={f.key} className="mono">{f.label}{f.secret && saved && <span className="muted"> (saved; leave empty to keep it)</span>}
              <input className="field" type={f.secret ? "password" : "text"} placeholder={f.placeholder} value={vals[f.key] || ""} autoComplete="off"
                onChange={(e) => setVals((v) => ({ ...v, [f.key]: e.target.value }))} required={!f.secret || !saved} />
            </label>
          ))}
          <div className="connect__row">
            <button className="btn btn--sm" disabled={busy}>{busy ? "Checking…" : "Connect and sync"}</button>
            {saved && <button type="button" className="link" onClick={() => setEditing(false)}>Cancel</button>}
          </div>
          <p className="connect__note mono">{t.note}</p>
        </form>
      ) : (
        <div className="setup__facts">
          {kind === "jira" && st.jira && <div><span className="mono muted">Project</span><b>{st.jira.project} · {st.jira.site.replace("https://", "")}</b></div>}
          {kind === "linear" && st.linear && <div><span className="mono muted">Team</span><b>{st.linear.team}</b></div>}
          <div><span className="mono muted">Last pass</span><b>{when(st.status.at)}</b></div>
          {pass && <div><span className="mono muted">Last pass read</span><b>{pass.tickets} {plural(pass.tickets, "ticket", "tickets")} · {pass.comments} comments · {pass.new_versions} new {plural(pass.new_versions, "version", "versions")}</b></div>}
          <button className="link" onClick={() => setEditing(true)}>Change settings</button>
        </div>
      )}
      {err && <p className="connect__err">{err}</p>}
    </div>
  );
}

function PeopleTable({ people, reload }: { people: TeamPerson[]; reload: () => void }) {
  const [edit, setEdit] = useState<string | null>(null);
  const [role, setRole] = useState("");
  const [groups, setGroups] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const start = (p: TeamPerson) => { setEdit(p.id); setRole(p.role || ""); setGroups(p.groups.join(", ")); };
  const save = async (id: string) => {
    try { await api.editPerson(id, role.trim(), groups.split(",").map((g) => g.trim()).filter(Boolean)); setEdit(null); reload(); }
    catch (e) { setErr((e as Error).message); }
  };
  const merge = async (keep: string, drop: string) => {
    if (!confirm(`Merge ${drop} into ${keep}? Their messages, tickets and accounts move to ${keep}.`)) return;
    try { await api.mergePeople(keep, drop); reload(); } catch (e) { setErr((e as Error).message); }
  };
  if (!people.length) return <p className="muted">Nobody yet: people appear as soon as the bot reads a message or the first sync runs.</p>;
  return (
    <>
      {err && <p className="connect__err">{err}</p>}
      <ul className="who">
        {people.map((p) => (
          <li key={p.id}>
            <div className="who__main">
              <b>{p.name || p.id}</b>
              <span className="mono muted">{p.id}{p.email ? ` · ${p.email}` : ""}</span>
            </div>
            {edit === p.id ? (
              <div className="who__edit">
                <input className="field" value={role} onChange={(e) => setRole(e.target.value)} placeholder="Role" aria-label="Role" />
                <input className="field" value={groups} onChange={(e) => setGroups(e.target.value)} placeholder="groups, comma separated" aria-label="Groups" />
                <button className="btn btn--sm" onClick={() => void save(p.id)}>Save</button>
                <button className="link" onClick={() => setEdit(null)}>Cancel</button>
              </div>
            ) : (
              <div className="who__role">
                <span>{p.role || <span className="muted">no role</span>}</span>
                <span className="who__groups">{p.groups.map((g) => <span key={g} className="tag">{g}</span>)}</span>
              </div>
            )}
            <div className="who__accounts">
              {p.accounts.map((a) => (
                <span key={`${a.platform}:${a.handle}`} className="src mono" title={`linked by: ${a.via}`}>
                  <b>{a.platform}</b>{a.handle}{a.via && !["account", "new"].includes(a.via) ? ` · ${a.via}` : ""}
                </span>
              ))}
            </div>
            <div className="who__act">
              <span className="mono muted">{p.activity} {plural(p.activity, "item", "items")}</span>
              {edit !== p.id && <button className="link" onClick={() => start(p)}>Edit</button>}
              <select className="sel" value="" onChange={(e) => e.target.value && void merge(p.id, e.target.value)} aria-label={`Merge someone into ${p.id}`}>
                <option value="">Merge into this…</option>
                {people.filter((x) => x.id !== p.id).map((x) => <option key={x.id} value={x.id}>{x.name || x.id}</option>)}
              </select>
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

export function TeamSetup() {
  const { refresh } = useBrain();
  const [st, setSt] = useState<TeamStatus | null>(null);
  const [people, setPeople] = useState<TeamPerson[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    api.team().then(setSt).catch((e) => setErr((e as Error).message));
    api.teamPeople().then(setPeople).catch(() => undefined);
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);
  const syncNow = async () => { await api.teamSync(); setTimeout(() => { load(); void refresh(); }, 4000); };
  const s = st?.status;
  return (
    <Section id="setup" index="00" title="Your setup"
      intro="What this team has connected, and who's who. People come from Slack, Discord, GitHub, Jira and Linear on their own; tickets come from Jira, Linear or GitHub issues, PRs from GitHub. Everything re-syncs every few minutes."
      aside={<button className="btn btn--ghost btn--sm" onClick={() => void syncNow()}>Sync now</button>}>
      {err && <p className="connect__err">{err}</p>}
      {st && (
        <>
          <div className="connect">
            <div className="connect__card">
              <div className="connect__top">
                <span className="connect__mark" aria-hidden>#</span>
                <div><h3>Chat</h3><span className="mono muted">live: every message as it's posted</span></div>
                <span className="tag tag--inv">Connected</span>
              </div>
              {st.slack && <p>Slack <b>{st.slack.team}</b>: {st.slack.channels.length ? st.slack.channels.map((c) => `#${c.name}`).join(" ") : "no channels picked yet"}.</p>}
              {st.discord && <p>Discord server <b>{st.discord.server}</b>: every channel the bot can see.</p>}
              {s?.history && <p className="connect__note mono">History imported: {s.history.messages} messages from {s.history.channels.map((c) => `#${c}`).join(" ")}, {when(s.history.at)}.</p>}
              <p className="connect__note mono">Edits and deletions follow too; so do new people and changed titles or roles.</p>
            </div>
            <GithubCard st={st} onChange={() => { load(); setTimeout(load, 5000); }} />
            <TrackerCard kind="jira" st={st} onChange={() => { load(); setTimeout(load, 5000); }} />
            <TrackerCard kind="linear" st={st} onChange={() => { load(); setTimeout(load, 5000); }} />
          </div>
          <div className="setup__status mono">
            <span>Last pass {when(s?.at)}</span>
            {s?.graph && <span>{st.people} people · {s.graph.Message || 0} messages · {s.graph.Ticket || 0} tickets · {s.graph.PullRequest || 0} PRs</span>}
            {s?.open_drift != null && <span className={s.open_drift ? "setup__hot" : ""}>{s.open_drift} open drift</span>}
            {s?.errors?.map((e) => <span key={e} className="setup__err">{e}</span>)}
          </div>
          <span className="kicker" style={{ marginTop: 40 }}>Who's who · {people.length} {plural(people.length, "person", "people")}</span>
          <p className="muted" style={{ fontSize: 14, marginBottom: 12 }}>Each human's accounts are linked by email, full name or handle; how each was linked is shown. Only a ticket's creator or assignee can change it from chat, so a missed link matters: merge two entries that are one person. Groups decide who may see restricted documents.</p>
          <PeopleTable people={people} reload={load} />
        </>
      )}
    </Section>
  );
}
