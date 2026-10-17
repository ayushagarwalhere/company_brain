import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { scrollToEl } from "./fx";
import { DEMO_ORG, tourOn } from "./routes";
import { api, holdRequests, ORG, type Coverage, type Drift, type Feature, type LiveEvent, type SpecResult, type Sprint, type Stats } from "./api";

/** Sandboxes are built from the demo data: ?org=demo (the demo) and ?org=tour (older tour links). */
const SANDBOX = ORG === DEMO_ORG || ORG === "tour";
/** One sandbox build per page load, however often the mount effect runs (StrictMode runs it twice in dev). */
let sandboxBuild: Promise<unknown> | null = null;
/** The tour always starts on a fresh sandbox: hold every section's first requests from the very start (before any
    component mounts), and let them through once it's built. */
let releaseRequests: (() => void) | null = null;
if (SANDBOX && tourOn()) holdRequests(new Promise<void>((ok) => { releaseRequests = ok; }));

/** App-wide graph state + cross-section actions (open a person, focus a feature, generate a spec). */
type Brain = {
  stats: Stats | null; drift: Drift[]; features: Feature[]; sprints: Sprint[]; coverage: Coverage | null;
  loaded: number; total: number; version: number;
  refresh: () => Promise<void>;
  feature: string | null; setFeature: (f: string) => void;
  focus: { feature: string; node?: string; nonce: number } | null; focusOn: (feature: string | null, node?: string) => void;
  view: "graph" | "map" | "timeline"; setView: (v: "graph" | "map" | "timeline") => void;
  person: string | null; openPerson: (id: string | null) => void;
  spec: SpecResult | null; specFor: (feature: string) => Promise<void>;
  actor: string; setActor: (a: string) => void;
  paletteOpen: boolean; setPaletteOpen: (o: boolean) => void;
  toasts: (LiveEvent & { id: number })[]; dismissToast: (id: number) => void; live: boolean;
  /** The newest drift that arrived live (Simulate or a bot over SSE): the drift section scrolls to it and flashes it. */
  arrival: { ticket: string | null; requirement: string | null; nonce: number } | null;
  announce: (a: { ticket?: string | null; requirement?: string | null }) => void;
  newDrift: number; clearNew: () => void;
  /** The demo sandbox (?org=demo) is built from the demo data the first time it's opened. */
  workspace: "ready" | "preparing" | "failed"; workspaceError: string | null;
};

const Ctx = createContext<Brain | null>(null);
export const useBrain = () => {
  const b = useContext(Ctx);
  if (!b) throw new Error("useBrain outside BrainProvider");
  return b;
};

export function BrainProvider({ children }: { children: ReactNode }) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [drift, setDrift] = useState<Drift[]>([]);
  const [features, setFeatures] = useState<Feature[]>([]);
  const [sprints, setSprints] = useState<Sprint[]>([]);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [loaded, setLoaded] = useState(0);
  const [version, setVersion] = useState(0);
  const [feature, setFeature] = useState<string | null>(null);
  const [focus, setFocus] = useState<Brain["focus"]>(null);
  const [view, setView] = useState<Brain["view"]>("graph");
  const [person, openPerson] = useState<string | null>(null);
  const [spec, setSpec] = useState<SpecResult | null>(null);
  const [actor, setActor] = useState("maya");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [toasts, setToasts] = useState<(LiveEvent & { id: number })[]>([]);
  const [live, setLive] = useState(false);
  const [arrival, setArrival] = useState<Brain["arrival"]>(null);
  const [newDrift, setNewDrift] = useState(0);
  const total = 5;
  const [workspace, setWorkspace] = useState<Brain["workspace"]>(SANDBOX ? "preparing" : "ready");
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);

  const lastArrival = useRef<Brain["arrival"]>(null);
  const announce = useCallback((a: { ticket?: string | null; requirement?: string | null }) => {
    const prev = lastArrival.current;
    // Simulate gets the HTTP response AND the SSE event for the same drift: merge them into one arrival
    const same = prev && prev.ticket === (a.ticket ?? null) && Date.now() - prev.nonce < 4000;
    const next = same ? { ...prev!, requirement: a.requirement ?? prev!.requirement }
      : { ticket: a.ticket ?? null, requirement: a.requirement ?? null, nonce: Date.now() };
    if (!same) setNewDrift((n) => n + 1);
    lastArrival.current = next;
    setArrival(next);
  }, []);
  const clearNew = useCallback(() => setNewDrift(0), []);

  const refresh = useCallback(async () => {
    const tick = <T,>(p: Promise<T>, set: (v: T) => void) => p.then(set).finally(() => setLoaded((n) => n + 1));
    setLoaded(0);
    await Promise.allSettled([
      tick(api.stats(), setStats), tick(api.drift(), setDrift), tick(api.features(), setFeatures),
      tick(api.sprints(), setSprints), tick(api.coverage(), setCoverage),
    ]);
    setVersion((v) => v + 1);
  }, []);

  useEffect(() => {
    void (async () => {
      if (SANDBOX && ORG) {
        // the guided tour always starts on a fresh sandbox (its steps take real actions). Without the tour: first visit
        // (or a wiped server) builds it, later visits keep what was done in it; a sandbox built before projects and doc
        // chunks existed is rebuilt too, so every section has its data
        const empty = tourOn() || await api.stats().then((s) => s.nodes.reduce((a, x) => a + x.n, 0) === 0 || !["Project", "Chunk"].every((l) => s.nodes.some((x) => x.label === l))).catch(() => true);
        if (empty) {
          if (!sandboxBuild) { sandboxBuild = api.bootstrap(ORG); holdRequests(sandboxBuild); }
          try { await sandboxBuild; } catch (e) { setWorkspaceError((e as Error).message); setWorkspace("failed"); return; } finally { releaseRequests?.(); }
        }
        setWorkspace("ready");
      }
      await refresh();
    })();
  }, [refresh]);

  // Live updates: the API pushes drift / resolution / ticket / PR / rebuild events over SSE
  useEffect(() => {
    // ?static (screenshots, projectors) skips the stream: an always-open request never lets the page go idle
    if (typeof EventSource === "undefined" || new URLSearchParams(location.search).has("static")) return;
    const es = new EventSource(`/api/events${ORG ? `?org=${encodeURIComponent(ORG)}` : ""}`);  // EventSource can't send headers
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onEvent = (e: MessageEvent) => {
      const evt = JSON.parse(e.data) as LiveEvent;
      if (evt.type === "drift") announce({ ticket: (evt.ticket as string) || null });
      if (evt.type !== "message") {
        const id = Date.now() + Math.random();
        setToasts((t) => [...t.slice(-3), { ...evt, id }]);
        setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 7000);
      }
      clearTimeout(timer);
      timer = setTimeout(() => void refresh(), 250);  // coalesce bursts
    };
    for (const type of ["drift", "message", "resolved", "ticket", "pr", "doc", "rebuild", "project"]) es.addEventListener(type, onEvent as EventListener);
    es.onopen = () => setLive(true);
    es.onerror = () => setLive(false);
    return () => { es.close(); clearTimeout(timer); };
  }, [refresh, announce]);
  const dismissToast = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  useEffect(() => {
    if (!feature && features.length) setFeature((features.find((f) => f.drift) || features[0]).id);
  }, [features, feature]);

  const focusOn = useCallback((f: string | null, node?: string) => {
    if (f) setFeature(f);
    setView("graph");
    setFocus({ feature: f || "", node, nonce: Date.now() });
    scrollToEl("graph-sec");
  }, []);

  const specFor = useCallback(async (f: string) => {
    const out = await api.spec(f);
    setSpec(out);
    setTimeout(() => scrollToEl("spec-sec"), 60);
  }, []);

  const value = useMemo<Brain>(() => ({
    stats, drift, features, sprints, coverage, loaded, total, version, refresh, feature, setFeature, focus, focusOn,
    view, setView, person, openPerson, spec, specFor, actor, setActor, paletteOpen, setPaletteOpen, toasts, dismissToast, live,
    arrival, announce, newDrift, clearNew, workspace, workspaceError,
  }), [workspace, workspaceError, stats, drift, features, sprints, coverage, loaded, version, refresh, feature, focus, focusOn, view, person, spec, specFor, actor, paletteOpen, toasts, dismissToast, live, arrival, announce, newDrift, clearNew]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
