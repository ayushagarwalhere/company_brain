import { BrainProvider } from "./lib/brain";
import { Footer, Loader, Nav } from "./components/Chrome";
import { DriftSection } from "./components/DriftSection";
import { GraphSection } from "./components/GraphSection";
import { Hero, Stats } from "./components/Hero";
import { OrbitBand } from "./components/Explainer";
import { Cursor, EdgeGlow, Seam, SmoothScroll } from "./components/Fx";
import { CommandPalette, PersonDrawer } from "./components/Overlays";
import { AskSection, CoverageSection, RetroSection, SimulateSection, SpecSection } from "./components/Panels";
import { Toasts } from "./components/Toasts";

export default function App() {
  return (
    <BrainProvider>
      <SmoothScroll />
      <a className="skip" href="#drift">Skip to open drift</a>
      <Loader />
      <Nav />
      <Hero />
      <OrbitBand />
      <Seam />
      <Stats />
      <Seam />
      <main>
        <DriftSection />
        <GraphSection />
        <AskSection />
        <RetroSection />
        <SimulateSection />
        <CoverageSection />
        <SpecSection />
      </main>
      <Footer />
      <CommandPalette />
      <PersonDrawer />
      <Toasts />
      <EdgeGlow />
      <Cursor />
    </BrainProvider>
  );
}
