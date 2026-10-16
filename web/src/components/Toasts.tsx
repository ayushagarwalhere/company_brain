import { AnimatePresence, motion } from "framer-motion";
import type { LiveEvent } from "../lib/api";
import { useBrain } from "../lib/brain";

const label = (e: LiveEvent): [string, string, "warn" | "ok" | "info"] => {
  const list = (x: unknown) => (Array.isArray(x) ? x.join(", ") : "");
  switch (e.type) {
    case "drift": return ["New drift", `${e.author} changed ${e.ticket ?? "a requirement"}: “${e.text}”`, "warn"];
    case "resolved": return ["Drift resolved", `${e.how} by ${e.by}${e.ticket ? ` · ${e.ticket}` : ""}`, "ok"];
    case "ticket": return [`Ticket ${e.ticket} updated`, list(e.resolved) ? `resolves ${list(e.resolved)}` : list(e.still_drifting) ? `still drifting: ${list(e.still_drifting)}` : `by ${e.by}`,
      list(e.resolved) ? "ok" : list(e.still_drifting) ? "warn" : "info"];
    case "pr": return [`PR #${e.pr} received`, list(e.resolved) ? `implements the latest decision · resolves ${list(e.resolved)}` : `linked to ${list(e.tickets) || "no ticket"}`, list(e.resolved) ? "ok" : "info"];
    case "doc": return [`Doc ${e.doc} updated`, e.no_longer_stale ? "no longer describes the old version" : `by ${e.by}`, e.no_longer_stale ? "ok" : "info"];
    case "rebuild": return ["Graph rebuilt", `extraction: ${e.extractor}`, "info"];
    default: return [e.type, "", "info"];
  }
};

/** Live events pushed by the API over SSE. */
export function Toasts() {
  const { toasts, dismissToast } = useBrain();
  return (
    <div className="toasts" aria-live="polite">
      <AnimatePresence>
        {toasts.map((t) => {
          const [title, body, tone] = label(t);
          return (
            <motion.button key={t.id} className={`toast toast--${tone}`} onClick={() => dismissToast(t.id)}
              initial={{ opacity: 0, x: 40 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 40 }} transition={{ duration: 0.35 }}>
              <span className="mono toast__title"><i className={`sq ${tone === "warn" ? "sq--accent" : "sq--violet"}`} />{title}</span>
              <span className="toast__body">{body}</span>
            </motion.button>
          );
        })}
      </AnimatePresence>
    </div>
  );
}

export function LiveDot() {
  const { live } = useBrain();
  return <span className={`live-dot mono ${live ? "on" : ""}`} title={live ? "Connected to live updates (SSE)" : "Live updates disconnected"}>{live ? "Live" : "Offline"}</span>;
}
