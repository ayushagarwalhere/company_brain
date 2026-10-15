import { BrainProvider } from "./lib/brain";
import { Footer, Loader, Nav } from "./components/Chrome";
import { DriftSection } from "./components/DriftSection";
import { GraphSection } from "./components/GraphSection";
import { Hero, OrbitBand, Stats } from "./components/Hero";
import { CommandPalette, PersonDrawer } from "./components/Overlays";
import { AskSection, CoverageSection, RetroSection, SimulateSection, SpecSection } from "./components/Panels";

export default function App() {
  return (
    <BrainProvider>
      <Loader />
      <Nav />
      <Hero />
      <OrbitBand />
      <Stats />
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
    </BrainProvider>
  );
}
