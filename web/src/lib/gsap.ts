// GSAP, registered once. Motion here is deliberately quiet: content fades or rises in once when it first appears, and
// nothing is tied to the scroll position (no scrubbing, no 3D scroll scenes). The one scroll behaviour is the feature
// pages, which step one page per gesture (components/Features.tsx). framer-motion keeps the small interactive bits.
// Every effect checks `moving()` so reduced motion and ?static get a still page. Call these helpers inside useGSAP:
// its context reverts every tween, ScrollTrigger and SplitText on unmount.
import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";
import { ScrambleTextPlugin } from "gsap/ScrambleTextPlugin";
import { ScrollToPlugin } from "gsap/ScrollToPlugin";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";

gsap.registerPlugin(ScrollTrigger, ScrollToPlugin, SplitText, ScrambleTextPlugin, useGSAP);
gsap.defaults({ ease: "power3.out", duration: 0.8 });

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

/** Wide screens get the paged feature section; phones get a simple stack. */
export const WIDE = "(min-width: 861px)";

/** Scroll the window to `y` with GSAP. CSS smooth scrolling is paused meanwhile: the two fight each other. */
export function scrollWindowTo(y: number, duration = 0.7, onComplete?: () => void) {
  const html = document.documentElement;
  html.style.scrollBehavior = "auto";
  gsap.to(window, {
    scrollTo: { y, autoKill: false }, duration: moving() ? duration : 0, ease: "power2.inOut", overwrite: true,
    onComplete: () => { html.style.scrollBehavior = ""; onComplete?.(); },
  });
}

/** Split a heading into masked lines, words or characters and raise them in once, when it first comes into view.
    Only for headings whose text React won't change while mounted. */
export function revealHeading(el: Element | null, opts: { by?: "lines" | "words" | "chars"; delay?: number; start?: string } = {}) {
  if (!el || !moving()) return;
  const by = opts.by || "words";
  SplitText.create(el, {
    type: by === "chars" ? "words,chars" : by, mask: by === "chars" ? "words" : by, autoSplit: by === "lines",
    onSplit: (self) => gsap.from(by === "lines" ? self.lines : by === "chars" ? self.chars : self.words, {
      yPercent: 105, opacity: 0, stagger: by === "chars" ? 0.018 : 0.05, duration: 0.8, delay: opts.delay || 0, ease: "power3.out",
      scrollTrigger: { trigger: el, start: opts.start || "top 88%", once: true },
    }),
  });
}

/** Fade elements up a little, once, when they first come into view. The only entrance used across the pages. */
export function fadeIn(targets: gsap.TweenTarget, trigger: Element | null, opts: { stagger?: number; delay?: number } = {}) {
  if (!trigger || !moving()) return;
  gsap.from(targets, { opacity: 0, y: 18, duration: 0.7, stagger: opts.stagger ?? 0.08, delay: opts.delay || 0, ease: "power2.out",
    clearProps: "opacity,transform", scrollTrigger: { trigger, start: "top 90%", once: true } });
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
