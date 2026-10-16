import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { edgeGlow, scrollToEl } from "./fx";
import { api, ORG, type Coverage, type Drift, type Feature, type LiveEvent, type SpecResult, type Sprint, type Stats } from "./api";

/** App-wide graph state + cross-section actions (open a person, focus a feature, generate a spec). */
type Brain = {
  stats: Stats | null; drift: Drift[]; features: Feature[]; sprints: Sprint[]; coverage: Coverage | null;
  loaded: number; total: number; version: number;
  refresh: () => Promise<void>;
  feature: string | null; setFeature: (f: string) => void;
  focus: { feature: string; node?: string; nonce: number } | null; focusOn: (feature: string | null, node?: string) => void;
  view: "graph" | "timeline"; setView: (v: "graph" | "timeline") => void;
  person: string | null; openPerson: (id: string | null) => void;
  spec: SpecResult | null; specFor: (feature: string) => Promise<void>;
  actor: string; setActor: (a: string) => void;
  paletteOpen: boolean; setPaletteOpen: (o: boolean) => void;
  toasts: (LiveEvent & { id: number })[]; dismissToast: (id: number) => void; live: boolean;
  /** The newest drift that arrived live (Simulate or a bot over SSE): the drift section scrolls to it and flashes it. */
  arrival: { ticket: string | null; requirement: string | null; nonce: number } | null;
  announce: (a: { ticket?: string | null; requirement?: string | null }) => void;
  newDrift: number; clearNew: () => void;
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

  const lastArrival = useRef<Brain["arrival"]>(null);
  const announce = useCallback((a: { ticket?: string | null; requirement?: string | null }) => {
    const prev = lastArrival.current;
    // Simulate gets the HTTP response AND the SSE event for the same drift: merge them into one arrival
    const same = prev && prev.ticket === (a.ticket ?? null) && Date.now() - prev.nonce < 4000;
    const next = same ? { ...prev!, requirement: a.requirement ?? prev!.requirement }
      : { ticket: a.ticket ?? null, requirement: a.requirement ?? null, nonce: Date.now() };
    if (!same) { setNewDrift((n) => n + 1); edgeGlow(); }
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

  useEffect(() => { void refresh(); }, [refresh]);

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
    for (const type of ["drift", "message", "resolved", "ticket", "pr", "doc", "rebuild"]) es.addEventListener(type, onEvent as EventListener);
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
    arrival, announce, newDrift, clearNew,
  }), [stats, drift, features, sprints, coverage, loaded, version, refresh, feature, focus, focusOn, view, person, spec, specFor, actor, paletteOpen, toasts, dismissToast, live, arrival, announce, newDrift, clearNew]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
