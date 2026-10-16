import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./motion.css";
import "./sections.css";

// ?static: no entrance animations (screenshots, slow machines, demos on a projector)
if (new URLSearchParams(location.search).has("static")) document.documentElement.classList.add("static");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
