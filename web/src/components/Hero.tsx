import { useRef, useState } from "react";
import { api, ORG } from "../lib/api";
import { useBrain } from "../lib/brain";
import { DEMO_ORG } from "../lib/routes";
import { gsap, moving, revealHeading, useGSAP } from "../lib/gsap";
import { CountUp } from "./Motion";
import { TOUR_HREF } from "./Tour";

/** Top of the app: which workspace this is, what's in it, and how to start over. */
export function AppHeader() {
  const { stats, drift, refresh, workspace, workspaceError } = useBrain();
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLElement>(null);
  useGSAP(() => {
    const el = ref.current;
    if (!el || !moving()) return;
    revealHeading(el.querySelector("h1 .apphead__name"), { by: "chars", start: "top 100%" });
    gsap.from(el.querySelectorAll(".eyebrow, .lede, .apphead__actions, .hero__stats > div"), { opacity: 0, y: 18, stagger: 0.05, delay: 0.25 });
  }, { scope: ref });
  const n = (l: string) => stats?.nodes.find((x) => x.label === l)?.n ?? 0;
  const demo = ORG === DEMO_ORG;
  const team = !!ORG && /^(slack|discord)-/.test(ORG);  // a connected team's own graph
  const reset = async () => {
    setBusy(true);
    try { if (demo) await api.bootstrap(DEMO_ORG); else await api.resetDemo(); await refresh(); } finally { setBusy(false); }
  };
  const figures: [string, number, boolean?][] = [
    ["Messages", n("Message")], ["Tickets", n("Ticket")], ["Pull requests", n("PullRequest")], ["Docs", n("Document")], ["Open drift", drift.length, true],
  ];
  return (
    <header className="apphead" id="top" ref={ref}>
      <div className="hero__3d">
        <div className="apphead__row">
          <div>
            <span className="eyebrow">{demo ? "Demo workspace · private sandbox" : team ? "Your team · private graph" : ORG ? `Workspace · ${ORG}` : "Workspace"}</span>
            {team
              ? <h1><span className="apphead__name">Your team</span> <span className="muted">({ORG!.startsWith("slack-") ? "Slack" : "Discord"})</span></h1>
              : <h1><span className="apphead__name">Brightdesk</span> <span className="muted">(synthetic company)</span></h1>}
            <p className="lede">
              {demo
                ? "Your own copy of the demo company. Every button does the real thing: approve fixes, post as a teammate, edit tickets, ask the graph. Reset it whenever you like."
                : team
                  ? "Messages from the channels your bot reads, in a graph only your team's link opens. Drift checks start once your tickets and pull requests are connected too, which the site's admin sets up for now."
                  : "8 people, Slack and Discord chat, tickets, GitHub PRs and docs, all in one FalkorDB graph."}
            </p>
          </div>
          <div className="apphead__actions">
            <a className="btn btn--ghost btn--sm" href="/">← Overview</a>
            <a className="btn btn--ghost btn--sm" href={TOUR_HREF} title="A fresh sandbox, from the first step">Restart the tour</a>
            {!team && (
              <button className="btn btn--sm" onClick={reset} disabled={busy || workspace !== "ready"} title="Rebuild this workspace from the demo data">
                {busy ? "Resetting…" : "Reset demo"}
              </button>
            )}
          </div>
        </div>
        {workspace === "preparing" && <p className="apphead__note mono">Setting up your private demo workspace… (a few seconds, once)</p>}
        {workspace === "failed" && <p className="apphead__note mono">The demo workspace couldn't be created: {workspaceError}</p>}
        <dl className="hero__stats hero__stats--5">
          {figures.map(([label, value, hot], i) => (
            <div key={label} className={hot && value ? "hot" : ""}><dt>{label}</dt><dd><CountUp value={value} delay={0.1 + i * 0.08} /></dd></div>
          ))}
        </dl>
      </div>
    </header>
  );
}
