// GSAP, registered once. Scroll-driven and 3D motion lives here; framer-motion keeps the small interactive bits
// (panels opening, cards resolving). Every effect checks `moving()` so reduced motion and ?static get a still page.
// Call these helpers inside useGSAP: its context reverts every tween, ScrollTrigger and SplitText on unmount.
import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";
import { ScrambleTextPlugin } from "gsap/ScrambleTextPlugin";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";

gsap.registerPlugin(ScrollTrigger, SplitText, ScrambleTextPlugin, useGSAP);
gsap.defaults({ ease: "power3.out", duration: 0.9 });

export { gsap, ScrollTrigger, SplitText, useGSAP };

/** False under prefers-reduced-motion or ?static (screenshots, projectors): render the final state, animate nothing. */
export function moving() {
  if (typeof window === "undefined") return false;
  return !matchMedia("(prefers-reduced-motion: reduce)").matches && !document.documentElement.classList.contains("static");
}

/** Data arrives after first paint and sections grow: re-measure every trigger when the page height settles. */
export function watchLayout() {
  if (typeof ResizeObserver === "undefined") return;
  let t: ReturnType<typeof setTimeout> | undefined, last = 0;
  new ResizeObserver(() => {
    const h = document.documentElement.scrollHeight;
    if (Math.abs(h - last) < 2) return;
    last = h;
    clearTimeout(t);
    t = setTimeout(() => ScrollTrigger.refresh(), 220);
  }).observe(document.body);
}

/** Wide screens get the pinned / 3D scroll scenes; phones get simple entrances. */
export const WIDE = "(min-width: 861px)";

/** Split a heading into masked lines, words or characters and raise them in, tipping forward in 3D, when it scrolls
    into view. Only for headings whose text React won't change while mounted. */
export function revealHeading(el: Element | null, opts: { by?: "lines" | "words" | "chars"; delay?: number; start?: string } = {}) {
  if (!el || !moving()) return;
  const by = opts.by || "words";
  SplitText.create(el, {
    type: by === "chars" ? "words,chars" : by, mask: by === "chars" ? "words" : by, autoSplit: by === "lines",
    onSplit: (self) => gsap.from(by === "lines" ? self.lines : by === "chars" ? self.chars : self.words, {
      yPercent: 115, rotationX: -75, transformOrigin: "50% 100% -30px", opacity: 0, stagger: by === "chars" ? 0.02 : 0.07,
      duration: 1.1, delay: opts.delay || 0, ease: "expo.out",
      scrollTrigger: { trigger: el, start: opts.start || "top 86%", once: true },
    }),
  });
}

/** Decode a short static mono label ("The pain") from scrambled glyphs when it scrolls into view. */
export function scrambleIn(el: Element | null, start = "top 90%") {
  if (!el || !moving()) return;
  // the original is kept on the element: StrictMode and re-runs must never read back the placeholder
  const text = el.getAttribute("data-text") ?? el.textContent ?? "";
  el.setAttribute("data-text", text);
  el.textContent = text.replace(/\S/g, "·");
  gsap.to(el, {
    duration: 1.2, ease: "none", scrambleText: { text, chars: "01/\\_▮", speed: 0.5, revealDelay: 0.2 },
    scrollTrigger: { trigger: el, start, once: true },
  });
}
