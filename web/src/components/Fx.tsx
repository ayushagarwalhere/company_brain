import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { finePointer, scrollToEl, setLenis, useStill } from "../lib/fx";

/** Lenis smooth scroll for the whole page, plus in-page anchor links routed through it. */
export function SmoothScroll() {
  const still = useStill();
  useEffect(() => {
    if (still) return;
    let raf = 0, alive = true, instance: { raf: (t: number) => void; destroy: () => void } | null = null;
    void import("lenis").then(({ default: Lenis }) => {
      if (!alive) return;
      const l = new Lenis({ lerp: 0.11, wheelMultiplier: 0.95, smoothWheel: true });
      instance = l;
      setLenis(l);
      const loop = (t: number) => { l.raf(t); raf = requestAnimationFrame(loop); };
      raf = requestAnimationFrame(loop);
    });
    const onClick = (e: MouseEvent) => {
      const a = (e.target as HTMLElement).closest?.("a[href^='#']") as HTMLAnchorElement | null;
      if (!a || a.getAttribute("href") === "#") return;
      const id = a.getAttribute("href")!.slice(1);
      if (!document.getElementById(id)) return;
      e.preventDefault();
      scrollToEl(id, id === "top" ? 0 : -72);
      history.replaceState(null, "", `#${id}`);
    };
    document.addEventListener("click", onClick);
    return () => { alive = false; cancelAnimationFrame(raf); instance?.destroy(); setLenis(null); document.removeEventListener("click", onClick); };
  }, [still]);
  return null;
}

const INTERACTIVE = "a, button, select, input, textarea, label, [role='button'], [role='tab'], .chip, .canvas__graph";

/** Small ring cursor that grows over interactive elements. Fine pointers only. */
export function Cursor() {
  const ring = useRef<HTMLDivElement>(null);
  const [on, setOn] = useState(false);
  useEffect(() => {
    if (!finePointer()) return;
    setOn(true);
    document.documentElement.classList.add("has-cursor");
    let x = innerWidth / 2, y = innerHeight / 2, cx = x, cy = y, raf = 0;
    const move = (e: PointerEvent) => {
      x = e.clientX; y = e.clientY;
      const hot = !!(e.target as HTMLElement).closest?.(INTERACTIVE);
      ring.current?.classList.toggle("cursor--hot", hot);
      ring.current?.classList.remove("cursor--hidden");
    };
    const leave = () => ring.current?.classList.add("cursor--hidden");
    const loop = () => {
      cx += (x - cx) * 0.25; cy += (y - cy) * 0.25;
      if (ring.current) ring.current.style.transform = `translate3d(${cx.toFixed(1)}px, ${cy.toFixed(1)}px, 0)`;
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    addEventListener("pointermove", move, { passive: true });
    document.addEventListener("pointerleave", leave);
    return () => {
      cancelAnimationFrame(raf); removeEventListener("pointermove", move); document.removeEventListener("pointerleave", leave);
      document.documentElement.classList.remove("has-cursor");
    };
  }, []);
  if (!on) return null;
  return <div ref={ring} className="cursor cursor--hidden" aria-hidden><span /></div>;
}

/** Orange glow around the viewport edge when a new drift arrives (see lib/fx edgeGlow). */
export function EdgeGlow() {
  const [n, setN] = useState(0);
  const still = useStill();
  useEffect(() => {
    const on = () => setN((x) => x + 1);
    addEventListener("edge-glow", on);
    return () => removeEventListener("edge-glow", on);
  }, []);
  return (
    <AnimatePresence>
      {n > 0 && (
        <motion.div key={n} className="edge-glow" aria-hidden initial={{ opacity: 0 }} animate={{ opacity: still ? 0.6 : [0, 1, 0.7, 0] }}
          exit={{ opacity: 0 }} transition={{ duration: still ? 0.3 : 1.8, times: still ? undefined : [0, 0.15, 0.45, 1] }}
          onAnimationComplete={() => setN(0)} />
      )}
    </AnimatePresence>
  );
}

/** Soft gradient seam between sections instead of a hard cut. */
export function Seam() {
  return <div className="seam" aria-hidden />;
}
