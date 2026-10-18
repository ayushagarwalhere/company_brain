// Typed client for the FastAPI backend (api/main.py). Shapes mirror the JSON it returns.
import { sandboxFor } from "./routes";

export type Count = { label?: string; type?: string; n: number };
export type Stats = {
  nodes: { label: string; n: number }[];
  relationships: { type: string; n: number }[];
  build: { extractor: string; model?: string | null; at: string; reference_date?: string | null; llm_errors?: number | null; classified?: number | null } | null;
  llm: { model: string; available: boolean; reason: string };
};
/** status, from one backend rule (graph/queries.py PR_STATUS_LABEL): "old" = merged before the decision, "old_after" = merged after
    it but implements an older requirement (both stale); "unmatched" = merged after with no IMPLEMENTS link (not stale). */
export type StalePR = {
  pr: number; title: string; url: string; merged: string | null; merged_after?: boolean; implements: string | null;
  status: "old" | "old_after" | "unmatched"; label: string;
};
export type StaleDoc = { id: string; title: string; updated: string; url: string };
export type Drift = {
  feature: string; feature_name: string; ticket: string; ticket_title: string; ticket_url: string; ticket_text: string;
  requirement: string; requirement_text: string; changed_at: string; changed_ms: number;
  message: string; message_text: string; message_url: string; source: string; channel: string; changed_by: string;
  decision: string | null; previous_requirement: string | null;
  stale_prs: StalePR[]; unmatched_prs?: StalePR[]; stale_docs: StaleDoc[]; path: string;
};
export type Feature = { id: string; name: string; tickets: string[]; prs: number[]; messages: number; drift: boolean };
export type Sprint = { id: string; name: string; start: string; end: string };
export type RetroDecision = {
  decision: string; text: string; at: string; by: string; ticket: string; feature: string | null; source: string;
  platform: string; channel: string; superseded_by: string | null; shipped_in: number[]; dismissed_by: string | null;
};
export type RetroShipped = { pr: number; title: string; url: string; merged: string; author: string; tickets: string[]; link: string[] };
export type Retro = { sprint: string; name: string; start: string; end: string; decided: RetroDecision[]; shipped: RetroShipped[]; diverged: Drift[] };
export type GNode = { id: string; label: string; type: string; text?: string | null; drift?: boolean; stale?: boolean };
export type GEdge = { from: string; rel: string; to: string };
export type GraphData = { nodes: GNode[]; edges: GEdge[] };
export type TimelineEvent = {
  lane: "chat" | "ticket" | "doc" | "pr"; id: string; at: number; iso: string; title: string; text: string;
  ref: string | null; who: string | null; drift: boolean; superseded: boolean;
};
export type Coverage = {
  orphan_prs: { pr: number; title: string; url: string; author: string }[];
  done_without_pr: { ticket: string; title: string; owner: string | null }[];
  undiscussed_tickets: { ticket: string; title: string; state: string; feature: string | null }[];
  knowledge_risk: { feature: string; name: string; top_person: string; top_share: number; people: number; total: number }[];
  unverified_changes?: { id: string; text: string; at: string; message: string; author: string; ticket: string; ticket_title: string }[];
};
export type AskResult = {
  answer: string; tool_calls: { tool: string; args: Record<string, string>; rows: number }[]; paths: string[];
  engine?: string; fallback_reason?: string;
  /** where the evidence lives: Slack/Discord channel, GitHub, the tracker, docs (api/main.py answer_sources) */
  sources?: { system: string; label: string; refs: string[] }[];
};
export type SimResult = {
  status: string; message?: string; feature?: string | null; via?: string | null; ticket?: string;
  classification?: { kind: string }; path?: string; alert?: string;
  /** a message about a whole project ("we're cancelling Project Gamma"): what it did to the project */
  change?: { project: string; name: string; from: string; to: string; by: string; status: "changed" | "no-rights" | "unchanged" };
};
export type StreamItem = {
  kind: "message" | "ticket" | "doc"; id: string; ts: string; ms: number; who: string | null; source: string | null; text: string;
  channel?: string; project?: string | null; project_to?: string | null; tickets?: string[]; docs?: string[]; changes?: boolean;
  state?: string; assignee?: string | null;
};
export type NewTicket = { ticket: string; title: string; creator: string; assignee: string | null; project: string | null; project_name: string | null };
export type CompanyNode = { id: string; type: string; label: string; text: string | null; status: string | null; launch?: string | null; due?: string | null; ooo_until?: string | null; source?: string | null };
export type CompanyGraph = { nodes: CompanyNode[]; edges: { source: string; rel: string; target: string }[] };
export type SearchHit = { id: string; type: string; label: string | null; score: number; feature: string | null };
export type Person = {
  id: string; name: string; role: string; messages: number;
  owns: { ticket: string; title: string; state: string; feature: string | null; role?: string }[];
  prs: { pr: number; title: string; url: string; tickets: string[] }[];
  decisions: { id: string; text: string; at: string; kind: string; ticket: string | null }[];
  features: { id: string; name: string; score: number }[];
  docs: { id: string; title: string; updated: string; tickets: string[] }[];
  drift_caused: Drift[]; stale_work: Drift[];
};
export type SpecResult = { feature: string; markdown: string; engine: string };
export type TicketRow = { id: string; title: string; description: string; state: string; feature: string | null };
export type TicketUpdate = { status: string; ticket: string; version?: string; resolved?: string[]; still_drifting?: string[]; new_drift?: string[] };
export type PlanItem = { kind: "ticket" | "pr" | "doc"; target: string; assignee: string | null; what: string; why: string };
export type FixPlan = { owners: Record<string, string | null>; decided_by: string; items: PlanItem[]; tell: string[]; can_apply: string[] };
export type Task = { id: string; num: number; kind: string; title: string; why: string; status: string; assignee: string | null; approved_by: string; target: string; created: string };
export type Applied = { status: string; ticket: string; version: string; tasks: Task[]; tell: string[]; by: string };
/** A document as the graph holds it: who may see it (acl: [] = everyone), its chunks in the vector index, the tickets
    it mentions (MENTIONS edges) and the open drift it is stale for. */
export type Doc = {
  id: string; title: string; author: string | null; updated: string; acl: string[]; text: string; tickets: string[];
  chunks: { id: string; chars: number }[]; embedder: string | null; stale_for: string[];
};
export type DocSync = {
  status: string; doc: string; by: string; no_longer_stale: boolean; tickets: string[];
  sync: {
    chunks: number; embedded: number; kept: number; removed: number; mentions: string[]; mentions_dropped: string[]; embedder: string;
    parts: { id: string; status: "embedded" | "kept" | "removed"; chars: number }[];
  };
};
/** A node in a layered view: `col` is its column (left to right), `status` drives its emphasis. */
export type CNode = { id: string; type: string; label: string; col: number; text?: string | null; status?: string; drift?: boolean };
export type CGraph = { nodes: CNode[]; edges: GEdge[] };
export type Project = {
  id: string; name: string; about: string; launch: string; owner: string | null; tickets: string[]; features: string[];
  deliverables: { id: string; title: string; due: string; client: string }[];
  status?: string; status_by?: string | null; status_at?: string | null;
};
export type Impact = {
  target: { kind: string; id: string; name: string }; days: number;
  projects: { id: string; name: string; launch: string; new_launch: string; slip_days: number; root: boolean; via: { from: string; to: string; why: string } | null }[];
  tickets: { id: string; title: string; state: string; assignee: string | null; root: boolean; blocked_by: string[] }[];
  deliverables: { id: string; title: string; due: string; ready: string; client: string; client_name: string; owner: string | null; needs: string[]; moved: boolean; slack_days: number; status: "misses" | "tight" | "on track" }[];
  teams: { id: string | null; name: string; people: { id: string; name: string; roles: string[]; tickets: string[] }[] }[];
  drift: { ticket: string; text: string; by: string }[];
  paths: string[]; graph: CGraph;
};
export type Integrations = {
  /** counts only: which teams are connected is nobody else's business */
  slack: { ready: boolean; bot_from_env: boolean; scopes: string[]; workspaces: number };
  discord: { ready: boolean; bot_token_set: boolean; servers: number };
};
export type SlackChannels = { team: string; channels: { id: string; name: string; members: number | null; watched: boolean }[] };
export type SourcePass = { tickets: number; new_versions: number; comments: number; prs: number; people: number };
/** A flag's earlier hand-check (benchmark/real_data_labels.json, labelled by the AI assistant). */
export type TryLabel = { verdict: string; pattern: string | null; note: string | null };
/** "Try it on your own repo" (pipeline/tryrepo.py): what a public repo's graph shows. */
export type TryResult = {
  repo: string; url: string; org: string; description: string | null; stars: number | null; fetched_at: string; source: string; build_seconds: number;
  window: { issues: number; older_issues?: number; prs: number; comments: number; cap_issues: number; cap_prs: number };
  counts: { people: number; issues: number; open_issues: number; prs: number; merged: number; chains: number; decisions: number; drift: number; open_no_pr: number };
  people: { person: string; url: string; issues: number; prs: number; merged: number; comments: number; assigned: number; reviews: number; areas: string[]; score: number }[];
  areas: { label: string; issues: number; open: number; with_pr: number; url: string; people: { person: string; score: number }[] }[];
  chains: { issue: string; issue_title: string; issue_url: string; issue_state: string; opened_by: string | null; pr: number; pr_title: string; pr_url: string; pr_state: string; pr_by: string; how: string }[];
  decisions: { by: string; comment: string; url: string; at: string; requirement: string; requirement_text: string; issue: string; issue_title: string; issue_url: string; implemented_by: number[]; drift: boolean; label: TryLabel | null }[];
  no_pr: { issue: string; title: string; url: string; labels: string[]; opened_by: string | null; assignee: string | null; comments: number }[];
  drift: { issue: string; title: string; url: string; issue_says: string; comment: string; comment_url: string; by: string; at: string; stale_prs: number[]; label: TryLabel | null }[];
  graph: CGraph;
  note: string;
};
export type TryState = { state: "ready" | "queued" | "running" | "error" | "none"; repo: string; org: string; step?: string; error?: string; since?: number; result?: TryResult };
export type TryRecent = { repo: string; org: string; fetched_at: string; counts: TryResult["counts"] };
export type TeamStatus = {
  org: string; people: number;
  slack: { team: string; channels: { id: string; name: string }[] } | null;
  discord: { server: string } | null;
  github: { repo: string; token_set: boolean; since: string | null } | null;
  jira: { site: string; project: string; email: string; since: string | null } | null;
  linear: { team: string; since: string | null } | null;
  status: {
    at?: string; errors?: string[]; people_from_slack?: number; open_drift?: number; graph?: Record<string, number>;
    github?: SourcePass; jira?: SourcePass; linear?: SourcePass;
    history?: { messages: number; channels: string[]; at: string };
  };
};
export type TeamPerson = {
  id: string; name: string | null; role: string | null; email: string | null; groups: string[]; activity: number;
  accounts: { platform: string; handle: string; name: string | null; title: string | null; via: string }[];
};
export type WhoAmI = { viewer: string | null; grants: string[] };
export type LiveEvent = { type: "drift" | "message" | "resolved" | "ticket" | "pr" | "doc" | "rebuild" | "project"; at: number; [k: string]: unknown };

/** Multi-tenancy: ?org=acme in the page URL scopes every request to that org's graph; ?org=demo is this browser's
    own sandbox of the demo company. */
export const ORG = typeof window !== "undefined" ? sandboxFor(new URLSearchParams(window.location.search).get("org")) : null;

/** Write token: when the server sets INGEST_TOKEN, actions (resolve, dismiss, simulate) need it. Opening the page
    once with ?token=... keeps it for this tab. */
const TOKEN = (() => {
  const fromUrl = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("token") : null;
  try {
    if (fromUrl) sessionStorage.setItem("drift-token", fromUrl);
    return fromUrl || sessionStorage.getItem("drift-token");
  } catch {
    return fromUrl;
  }
})();

/** While the demo sandbox is being rebuilt, every request but the rebuild itself waits for it: a half-built graph
    gives half answers, or errors. */
let gate: Promise<unknown> = Promise.resolve();
export function holdRequests(until: Promise<unknown>) { gate = until.catch(() => undefined); }

/** `as`: the person this request acts for (X-User). The server answers with only what that person may see; without
    one the request is anonymous. In production this comes from the sign-in, not from the page. */
async function req<T>(path: string, body?: unknown, as?: string | null): Promise<T> {
  if (!path.includes("/bootstrap")) await gate;
  const headers: Record<string, string> = { ...(ORG ? { "X-Org": ORG } : {}), ...(as ? { "X-User": as } : {}) };
  const res = await fetch(path, body === undefined ? { headers } : {
    method: "POST", headers: { ...headers, ...(TOKEN ? { "X-Ingest-Token": TOKEN } : {}), "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (res.status === 401) throw new Error("This action needs the demo's write token: open the page with ?token=…");
  if (res.status === 403) throw new Error((await res.json().then((j) => j.detail).catch(() => null)) || "Not allowed");
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail).catch(() => null);
    throw new Error(detail || res.statusText);
  }
  return res.json() as Promise<T>;
}

const enc = encodeURIComponent;
export const api = {
  stats: () => req<Stats>("/api/stats"),
  drift: (feature?: string) => req<Drift[]>(`/api/drift${feature ? `?feature=${enc(feature)}` : ""}`),
  features: () => req<Feature[]>("/api/features"),
  sprints: () => req<Sprint[]>("/api/sprints"),
  retro: (sprint: string) => req<Retro>(`/api/retro/${enc(sprint)}`),
  graph: (feature: string) => req<GraphData>(`/api/features/${enc(feature)}/graph`),
  timeline: (feature: string) => req<TimelineEvent[]>(`/api/features/${enc(feature)}/timeline`),
  neighbors: (id: string) => req<GraphData>(`/api/nodes/${enc(id)}/neighbors`),
  coverage: () => req<Coverage>("/api/coverage"),
  ask: (question: string, as?: string | null) => req<AskResult>("/api/ask", { question }, as),
  docs: (as?: string | null) => req<Doc[]>("/api/docs", undefined, as),
  updateDoc: (doc: string, text: string, actor: string, acl?: string[]) => req<DocSync>("/api/ingest/doc", { doc, text, actor, acl }, actor),
  whoami: (as?: string | null) => req<WhoAmI>("/api/whoami", undefined, as),
  projects: () => req<Project[]>("/api/projects"),
  integrations: () => req<Integrations>("/api/integrations"),
  team: () => req<TeamStatus>("/api/team"),
  teamPeople: () => req<TeamPerson[]>("/api/team/people"),
  teamSync: () => req<{ syncing: boolean }>("/api/team/sync", {}),
  connectGithub: (repo: string, token: string) => req<{ repo: string; private: boolean }>("/api/team/github", { repo, token }),
  connectJira: (site: string, email: string, token: string, project: string) => req<{ project: string; name: string }>("/api/team/jira", { site, email, token, project }),
  connectLinear: (token: string, team: string) => req<{ team: string; name: string }>("/api/team/linear", { token, team }),
  tryRepo: (repo: string) => req<TryState>("/api/try", { repo }),
  tryStatus: (repo: string) => req<TryState>(`/api/try/status?repo=${enc(repo)}`),
  tryRecent: () => req<{ repos: TryRecent[] }>("/api/try/recent"),
  mergePeople: (keep: string, drop: string) => req<{ kept: string; merged: string }>("/api/team/people/merge", { keep, drop }),
  editPerson: (id: string, role: string, groups: string[]) => req<{ id: string }>(`/api/team/people/${enc(id)}`, { role, groups }),
  /** `key`: the setup key Slack's redirect handed to the person who just installed */
  slackChannels: (team: string, key: string) => req<SlackChannels>(`/api/connect/slack/channels?team=${enc(team)}&key=${enc(key)}`),
  watchSlack: (team: string, key: string, channels: string[]) =>
    req<{ joined: { id: string; name: string }[]; failed: { id: string; error: string }[]; private_graph: boolean }>("/api/connect/slack/channels", { team, key, channels }),
  impact: (target: string, days: number) => req<Impact>(`/api/impact?target=${enc(target)}&days=${days}`),
  featureMap: (feature: string) => req<CGraph>(`/api/features/${enc(feature)}/map`),
  spec: (feature: string) => req<SpecResult>("/api/spec", { feature }),
  simulate: (b: { text: string; author: string; platform: string; channel: string }) => req<SimResult>("/api/simulate", b),
  search: (q: string) => req<SearchHit[]>(`/api/search?q=${enc(q)}`),
  person: (id: string) => req<Person>(`/api/people/${enc(id)}`),
  driftAction: (act: "write-to-ticket" | "dismiss", requirement: string, actor: string) =>
    req<{ status: string; ticket?: string; version?: string; by?: string }>(`/api/drift/${act}`, { requirement, actor }),
  plan: (requirement: string) => req<FixPlan>("/api/drift/plan", { requirement }),
  applyPlan: (requirement: string, actor: string) => req<Applied>("/api/drift/apply", { requirement, actor }),
  keepScope: (requirement: string, actor: string) => req<{ status: string; by: string }>("/api/drift/keep", { requirement, actor }),
  tasks: (person?: string) => req<Task[]>(`/api/tasks${person ? `?person=${enc(person)}` : ""}`),
  bootstrap: (org: string) => req<{ org: string; nodes: number }>(`/api/orgs/${enc(org)}/bootstrap?extractor=heuristic`, {}),
  resetDemo: () => req<{ rebuilt_with: string }>("/api/demo/reset", {}),
  tickets: () => req<TicketRow[]>("/api/tickets"),
  newTicket: (b: { title: string; description?: string; creator: string; assignee?: string; project?: string }) => req<NewTicket>("/api/ingest/ticket/new", b),
  stream: (limit = 14) => req<StreamItem[]>(`/api/stream?limit=${limit}`),
  companyGraph: (as?: string | null) => req<CompanyGraph>("/api/company-graph", undefined, as),
  updateTicket: (ticket: string, description: string, actor: string) => req<TicketUpdate>("/api/ingest/ticket", { ticket, description, actor }),
};
