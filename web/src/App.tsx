import { useEffect } from "react";
import { BrainProvider, useBrain } from "./lib/brain";
import { scrollToEl } from "./lib/fx";
import { ORG } from "./lib/api";
import { isAppMode, isTeamOrg } from "./lib/routes";
import { Footer, Nav } from "./components/Chrome";
import { CompanyMapSection } from "./components/CompanyMap";
import { DriftSection } from "./components/DriftSection";
import { GraphSection } from "./components/GraphSection";
import { AppHeader } from "./components/Hero";
import { ImpactSection } from "./components/ImpactSection";
import { DocsSection } from "./components/Knowledge";
import { Landing } from "./components/Landing";
import { CommandPalette, PersonDrawer } from "./components/Overlays";
import { AskSection, CoverageSection, RetroSection, SimulateSection, SpecSection } from "./components/Panels";
import { StreamSection } from "./components/Stream";
import { TeamSetup } from "./components/TeamSetup";
import { Toasts } from "./components/Toasts";
import { Tour, tourActive } from "./components/Tour";

/** "/?app#ask" from the overview: once the data is in, scroll to the section the link named. */
function ScrollToHash() {
  const { version } = useBrain();
  useEffect(() => {
    const id = location.hash.slice(1);
    if (version === 1 && id) setTimeout(() => scrollToEl(id), 300);
  }, [version]);
  return null;
}

/** The working app: every feature on the live graph (the demo sandbox when opened from the overview). */
function Workspace() {
  const team = isTeamOrg(ORG);  // a real team: its setup first; the demo-only sections (personas, projects, sample docs) are left out
  return (
    <>
      <a className="skip" href="#drift">Skip to open drift</a>
      <Nav />
      <AppHeader />
      <main>
        {team && <TeamSetup />}
        <DriftSection />
        <GraphSection />
        <CompanyMapSection />
        {!team && <ImpactSection />}
        {!team && <SimulateSection />}
        <StreamSection />
        <AskSection />
        {!team && <DocsSection />}
        <RetroSection />
        <CoverageSection />
        <SpecSection />
      </main>
      <Footer />
      <CommandPalette />
      <PersonDrawer />
      <Toasts />
      <ScrollToHash />
      {tourActive() && <Tour />}
    </>
  );
}

export default function App() {
  return <BrainProvider>{isAppMode() ? <Workspace /> : <Landing />}</BrainProvider>;
}
