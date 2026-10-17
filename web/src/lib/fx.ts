// Motion plumbing shared by every section: one reduced-motion switch and native smooth scrolling.
import { useReducedMotion } from "framer-motion";
import { useStaticMode } from "./ui";

/** True when motion should be minimal: OS reduced-motion setting or ?static (screenshots, projectors). */
export function useStill() {
  return !!useReducedMotion() || useStaticMode();
}

/** Scroll to a section or element, leaving room for the fixed nav. */
export function scrollToEl(target: string | HTMLElement, offset = -76) {
  const el = typeof target === "string" ? document.getElementById(target) : target;
  if (!el) return;
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches || document.documentElement.classList.contains("static");
  window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY + offset, behavior: still ? "auto" : "smooth" });
}
