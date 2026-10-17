// Small shared helpers: CSS tokens, node colours, path parsing.

export const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export const TYPE_VAR: Record<string, string> = {
  Feature: "--n-feature", Ticket: "--n-ticket", Requirement: "--n-req", Message: "--n-msg",
  PullRequest: "--n-pr", Person: "--n-person", Decision: "--accent", Document: "--n-doc",
};
export const typeColor = (t: string) => `var(${TYPE_VAR[t] || "--muted"})`;

export const PEOPLE = ["maya", "arjun", "sofia", "dev", "kenji", "priya", "liam", "zara"];

export const isExternal = (url?: string | null) => !!url && !url.startsWith("scenario://");

export const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

export const day = (iso?: string | null) => (iso || "").slice(0, 10);

/** Graph path string "(Type id)-[:REL]->(Type id) ; …" -> tokens for rendering as chips. */
export type PathToken =
  | { kind: "node"; type: string; label: string }
  | { kind: "rel"; rel: string; dir: "out" | "in" }
  | { kind: "text"; text: string }
  | { kind: "sep" };

export function parsePath(path: string): PathToken[] {
  const out: PathToken[] = [];
  for (const part of path.split(/(<-\[:[A-Z_|]+\]-|-\[:[A-Z_|]+\]->|\s;\s)/)) {
    if (!part) continue;
    if (part.trim() === ";") { out.push({ kind: "sep" }); continue; }
    const rel = part.match(/^(<-|-)\[:([A-Z_|]+)\](->|-)$/);
    if (rel) { out.push({ kind: "rel", rel: rel[2], dir: rel[1] === "<-" ? "in" : "out" }); continue; }
    for (const piece of part.split(/(\([^)]*\))/)) {
      const m = piece.match(/^\((\w+)\s+([\s\S]*)\)$/);
      if (m) out.push({ kind: "node", type: m[1], label: m[2] });
      else if (piece.trim()) out.push({ kind: "text", text: piece.trim().replace(/^,\s*/, "") });
    }
  }
  return out;
}

export function useStaticMode() {
  return typeof window !== "undefined" && new URLSearchParams(window.location.search).has("static");
}
