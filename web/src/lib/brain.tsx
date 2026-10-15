import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type Coverage, type Drift, type Feature, type SpecResult, type Sprint, type Stats } from "./api";

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
  const total = 5;

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
  useEffect(() => {
    if (!feature && features.length) setFeature((features.find((f) => f.drift) || features[0]).id);
  }, [features, feature]);

  const focusOn = useCallback((f: string | null, node?: string) => {
    if (f) setFeature(f);
    setView("graph");
    setFocus({ feature: f || "", node, nonce: Date.now() });
    document.getElementById("graph-sec")?.scrollIntoView({ behavior: "smooth" });
  }, []);

  const specFor = useCallback(async (f: string) => {
    const out = await api.spec(f);
    setSpec(out);
    setTimeout(() => document.getElementById("spec-sec")?.scrollIntoView({ behavior: "smooth" }), 60);
  }, []);

  const value = useMemo<Brain>(() => ({
    stats, drift, features, sprints, coverage, loaded, total, version, refresh, feature, setFeature, focus, focusOn,
    view, setView, person, openPerson, spec, specFor, actor, setActor, paletteOpen, setPaletteOpen,
  }), [stats, drift, features, sprints, coverage, loaded, version, refresh, feature, focus, focusOn, view, person, spec, specFor, actor, paletteOpen]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
