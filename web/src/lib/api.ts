// Typed client for the FastAPI backend (api/main.py). Shapes mirror the JSON it returns.

export type Count = { label?: string; type?: string; n: number };
export type Stats = {
  nodes: { label: string; n: number }[];
  relationships: { type: string; n: number }[];
  build: { extractor: string; at: string } | null;
  llm: { model: string; available: boolean; reason: string };
};
export type StalePR = { pr: number; title: string; url: string; merged: string | null; implements: string | null };
export type StaleDoc = { id: string; title: string; updated: string; url: string };
export type Drift = {
  feature: string; feature_name: string; ticket: string; ticket_title: string; ticket_url: string; ticket_text: string;
  requirement: string; requirement_text: string; changed_at: string; changed_ms: number;
  message: string; message_text: string; message_url: string; source: string; channel: string; changed_by: string;
  decision: string | null; previous_requirement: string | null;
  stale_prs: StalePR[]; stale_docs: StaleDoc[]; path: string;
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
};
export type AskResult = {
  answer: string; tool_calls: { tool: string; args: Record<string, string>; rows: number }[]; paths: string[];
  engine?: string; fallback_reason?: string;
};
export type SimResult = {
  status: string; message?: string; feature?: string | null; via?: string | null; ticket?: string;
  classification?: { kind: string }; path?: string; alert?: string;
};
export type SearchHit = { id: string; type: string; label: string | null; score: number; feature: string | null };
export type Person = {
  id: string; name: string; role: string; messages: number;
  owns: { ticket: string; title: string; state: string; feature: string | null }[];
  prs: { pr: number; title: string; url: string; tickets: string[] }[];
  decisions: { id: string; text: string; at: string; kind: string; ticket: string | null }[];
  features: { id: string; name: string; score: number }[];
  docs: { id: string; title: string; updated: string; tickets: string[] }[];
  drift_caused: Drift[]; stale_work: Drift[];
};
export type SpecResult = { feature: string; markdown: string; engine: string };
export type TicketRow = { id: string; title: string; description: string; state: string; feature: string | null };
export type TicketUpdate = { status: string; ticket: string; version?: string; resolved?: string[]; still_drifting?: string[]; new_drift?: string[] };
export type LiveEvent = { type: "drift" | "message" | "resolved" | "ticket" | "pr" | "rebuild"; at: number; [k: string]: unknown };

/** Multi-tenancy: ?org=acme in the page URL scopes every request to that org's graph. */
export const ORG = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("org") : null;

async function req<T>(path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = ORG ? { "X-Org": ORG } : {};
  const res = await fetch(path, body === undefined ? { headers } : {
    method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
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
  ask: (question: string) => req<AskResult>("/api/ask", { question }),
  spec: (feature: string) => req<SpecResult>("/api/spec", { feature }),
  simulate: (b: { text: string; author: string; platform: string; channel: string }) => req<SimResult>("/api/simulate", b),
  search: (q: string) => req<SearchHit[]>(`/api/search?q=${enc(q)}`),
  person: (id: string) => req<Person>(`/api/people/${enc(id)}`),
  driftAction: (act: "write-to-ticket" | "dismiss", requirement: string, actor: string) =>
    req<{ status: string; ticket?: string; version?: string; by?: string }>(`/api/drift/${act}`, { requirement, actor }),
  resetDemo: () => req<{ rebuilt_with: string }>("/api/demo/reset", {}),
  tickets: () => req<TicketRow[]>("/api/tickets"),
  updateTicket: (ticket: string, description: string, actor: string) => req<TicketUpdate>("/api/ingest/ticket", { ticket, description, actor }),
};
