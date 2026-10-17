// Two views on one page: the overview (what it is, why, how) at "/", and the working app.
// "Open the demo" always starts the guided tour on a fresh private sandbox of the demo company (?org=demo&tour=1).
// Leaving the tour keeps that sandbox, so whatever the tour did is still there to explore.

export const DEMO_ORG = "demo";
/** Every "Open the demo": a fresh sandbox with the guided tour running. Add #section to start the tour there. */
export const DEMO_HREF = `/?app&org=${DEMO_ORG}&tour=1`;
/** The same sandbox without the tour and without rebuilding it: where the tour hands over. */
export const EXPLORE_HREF = `/?app&org=${DEMO_ORG}`;

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
