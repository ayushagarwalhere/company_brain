import { animate, motion, useInView, useReducedMotion, type HTMLMotionProps } from "framer-motion";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useStaticMode } from "../lib/ui";

const EASE = [0.2, 0.7, 0.1, 1] as const;

/** Fade + rise when scrolled into view. */
export function Reveal({ children, delay = 0, y = 24, ...rest }: { children: ReactNode; delay?: number; y?: number } & HTMLMotionProps<"div">) {
  const still = useReducedMotion() || useStaticMode();
  return (
    <motion.div
      initial={still ? false : { opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.9, ease: EASE, delay }}
      {...rest}
    >
      {children}
    </motion.div>
  );
}

/** Headline that assembles character by character. */
export function SplitText({ text, className, offset = 0 }: { text: string; className?: string; offset?: number }) {
  const still = useReducedMotion() || useStaticMode();
  return (
    <span className={`line ${className || ""}`} aria-hidden>
      {[...text].map((c, i) =>
        c === " " ? <span key={i}> </span> : (
          <motion.span
            key={i}
            className="ch"
            initial={still ? false : { opacity: 0, y: "0.45em", rotate: 4, filter: "blur(8px)" }}
            animate={{ opacity: 1, y: 0, rotate: 0, filter: "blur(0px)" }}
            transition={{ duration: 0.9, ease: EASE, delay: 0.15 + (offset + i) * 0.028 }}
          >
            {c}
          </motion.span>
        ),
      )}
    </span>
  );
}

/** Headline that reveals word by word from behind a mask (each word slides up out of its own clip). */
export function WordReveal({ text, className, delay = 0 }: { text: string; className?: string; delay?: number }) {
  const still = useReducedMotion() || useStaticMode();
  return (
    <span className={`line ${className || ""}`} aria-hidden>
      {text.split(" ").map((w, i, all) => (
        <span key={i}>
          <span className="wmask">
            <motion.span className="w" initial={still ? false : { y: "112%" }} animate={{ y: "0%" }}
              transition={{ duration: 1.05, ease: EASE, delay: delay + i * 0.09 }}>{w}</motion.span>
          </span>
          {i < all.length - 1 ? " " : null}
        </span>
      ))}
    </span>
  );
}

/** Number that counts up the first time it's visible. */
export function CountUp({ value, duration = 1.2, delay = 0, className }: { value: number; duration?: number; delay?: number; className?: string }) {
  const ref = useRef<HTMLElement>(null);
  const inView = useInView(ref, { once: true });
  const still = useReducedMotion() || useStaticMode();
  const [shown, setShown] = useState(still ? value : 0);
  useEffect(() => {
    if (still) { setShown(value); return; }
    if (!inView) return;
    const c = animate(0, value, { duration, delay, ease: EASE, onUpdate: (v) => setShown(Math.round(v)) });
    return () => c.stop();
  }, [inView, value, duration, delay, still]);
  return <b ref={ref} className={className}>{shown.toLocaleString()}</b>;
}

export { EASE };
