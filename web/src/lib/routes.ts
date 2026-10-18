// Two views on one page: the overview (what it is, why, how) at "/", and the working app.
// "Open the demo" always starts the guided tour on a fresh private sandbox of the demo company (?org=demo&tour=1).
// Leaving the tour keeps that sandbox, so whatever the tour did is still there to explore.

export const DEMO_ORG = "demo";
/** Every "Open the demo": a fresh sandbox with the guided tour running. Add #section to start the tour there. */
export const DEMO_HREF = `/?app&org=${DEMO_ORG}&tour=1`;
/** The same sandbox without the tour and without rebuilding it: where the tour hands over. */
export const EXPLORE_HREF = `/?app&org=${DEMO_ORG}`;

const SANDBOX_KEY = "demo-sandbox";
const SANDBOX_RE = /^demo-[a-z0-9]{10}$/;
/** A sandbox of the demo company: this browser's own (demo-<random>), or ?org=tour from older tour links. */
export const isSandboxOrg = (org: string | null | undefined) => !!org && (org === "tour" || SANDBOX_RE.test(org));

/** Every "Open the demo" link says ?org=demo, and each browser gets its own sandbox behind it, so two visitors never
    rebuild each other's graph mid-tour. The id stays the same for this browser (reloads and new tabs keep what was
    done); the address bar keeps ?org=demo, so a copied link gives the next person a sandbox of their own. */
export function sandboxFor(org: string | null): string | null {
  if (org !== DEMO_ORG) return org;
  let id: string | null = null;
  try { id = localStorage.getItem(SANDBOX_KEY); } catch { /* storage blocked: a new sandbox per page load */ }
  if (!id || !SANDBOX_RE.test(id)) {
    const bytes = crypto.getRandomValues(new Uint8Array(10));
    id = `demo-${Array.from(bytes, (b) => "abcdefghijklmnopqrstuvwxyz0123456789"[b % 36]).join("")}`;
    try { localStorage.setItem(SANDBOX_KEY, id); } catch { /* as above */ }
  }
  return id;
}

const APP_PARAMS = ["app", "org", "tour", "q", "person", "view"];
/** Section ids that exist only in the app; overview chapter anchors (#pain, #vision, …) stay on the overview. */
const APP_SECTIONS = ["setup", "drift", "graph-sec", "map-sec", "impact", "simulate", "stream", "ask", "docs-sec", "who-sees", "retro-sec", "coverage", "spec-sec"];

/** The app view: any app deep link (?app, ?org=, ?tour, ?q=, ?person=, ?view=) or an app section anchor. */
export function isAppMode() {
  if (typeof window === "undefined") return false;
  const p = new URLSearchParams(window.location.search);
  return APP_PARAMS.some((k) => p.has(k)) || APP_SECTIONS.includes(window.location.hash.slice(1));
}

/** The guided tour is running (?tour). */
export const tourOn = () => typeof window !== "undefined" && new URLSearchParams(window.location.search).has("tour");

/** A connected team's own graph (?org=slack-… / discord-…): real people and work, no demo-only sections. */
export const isTeamOrg = (org: string | null | undefined) => !!org && /^(slack|discord)-/.test(org);

/** A public GitHub repo's graph, built by "Try it on your repo" (?org=gh-…): read-only, no demo-only sections. */
export const isRepoOrg = (org: string | null | undefined) => !!org && org.startsWith("gh-");
/** The repo's name, for the header (?repo=owner/name; the org id can be a hash). */
export const repoName = () => (typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("repo"));
