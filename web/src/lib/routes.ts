// Two views on one page: the overview (what it is, why, how) at "/", and the working app.
// The app opens on a private sandbox copy of the demo company (?org=demo), so every action is real and safe.

export const DEMO_ORG = "demo";
export const DEMO_HREF = `/?app&org=${DEMO_ORG}`;

const APP_PARAMS = ["app", "org", "tour", "q", "person", "view"];

/** The app view: any app deep link (?app, ?org=, ?tour, ?q=, ?person=, ?view=) or an in-app #anchor. */
export function isAppMode() {
  if (typeof window === "undefined") return false;
  const p = new URLSearchParams(window.location.search);
  return APP_PARAMS.some((k) => p.has(k)) || (!!window.location.hash && window.location.hash !== "#top");
}
