// Motion plumbing shared by every section: one reduced-motion switch, smooth scrolling, and small
// pointer effects. Everything here is transform/opacity only, and a no-op under reduced motion.
import type Lenis from "lenis";
import { useReducedMotion } from "framer-motion";
import { useEffect, useRef, type RefObject } from "react";
import { useStaticMode } from "./ui";

/** True when motion should be minimal: OS reduced-motion setting or ?static (screenshots, projectors). */
export function useStill() {
  return !!useReducedMotion() || useStaticMode();
}

export const finePointer = () => typeof window !== "undefined" && window.matchMedia("(pointer: fine)").matches;

let lenis: Lenis | null = null;
export const setLenis = (l: Lenis | null) => { lenis = l; };

/** Scroll to a section or element: through Lenis when it's running, natively otherwise. */
export function scrollToEl(target: string | HTMLElement, offset = -72) {
  const el = typeof target === "string" ? document.getElementById(target) : target;
  if (!el) return;
  if (lenis) lenis.scrollTo(el, { offset, duration: 1.2 });
  else window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY + offset, behavior: "smooth" });
}

/** Magnetic hover: the element leans a few px toward the cursor and springs back on leave. */
export function useMagnetic<T extends HTMLElement>(strength = 0.25): RefObject<T> {
  const ref = useRef<T>(null);
  const still = useStill();
  useEffect(() => {
    const el = ref.current;
    if (!el || still || !finePointer()) return;
    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const x = (e.clientX - (r.left + r.width / 2)) * strength, y = (e.clientY - (r.top + r.height / 2)) * strength;
      el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
    };
    const leave = () => { el.style.transform = ""; };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", leave);
    return () => { el.removeEventListener("pointermove", move); el.removeEventListener("pointerleave", leave); };
  }, [strength, still]);
  return ref;
}

/** 3D tilt (max `deg`) plus a radial glow that follows the cursor (--gx/--gy CSS variables). */
export function useTilt<T extends HTMLElement>(deg = 6): RefObject<T> {
  const ref = useRef<T>(null);
  const still = useStill();
  useEffect(() => {
    const el = ref.current;
    if (!el || !finePointer()) return;
    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width, py = (e.clientY - r.top) / r.height;
      el.style.setProperty("--gx", `${(px * 100).toFixed(1)}%`);
      el.style.setProperty("--gy", `${(py * 100).toFixed(1)}%`);
      if (!still) el.style.transform = `perspective(900px) rotateX(${((0.5 - py) * deg).toFixed(2)}deg) rotateY(${((px - 0.5) * deg).toFixed(2)}deg)`;
    };
    const leave = () => { el.style.transform = ""; };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", leave);
    return () => { el.removeEventListener("pointermove", move); el.removeEventListener("pointerleave", leave); };
  }, [deg, still]);
  return ref;
}

/** A brief orange glow around the viewport edge: the "new drift detected" signal. */
export function edgeGlow() {
  window.dispatchEvent(new Event("edge-glow"));
}
