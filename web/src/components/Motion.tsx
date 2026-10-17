import { animate, motion, useInView, type HTMLMotionProps } from "framer-motion";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useStill } from "../lib/fx";

const EASE = [0.2, 0.7, 0.1, 1] as const;

/** Fade + rise when scrolled into view. */
export function Reveal({ children, delay = 0, y = 20, ...rest }: { children: ReactNode; delay?: number; y?: number } & HTMLMotionProps<"div">) {
  const still = useStill();
  return (
    <motion.div initial={still ? false : { opacity: 0, y }} whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }} transition={{ duration: 0.8, ease: EASE, delay }} {...rest}>
      {children}
    </motion.div>
  );
}

/** Headline that reveals word by word from behind a mask. */
export function WordReveal({ text, className, delay = 0 }: { text: string; className?: string; delay?: number }) {
  const still = useStill();
  return (
    <span className={`line ${className || ""}`} aria-hidden>
      {text.split(" ").map((w, i, all) => (
        <span key={i}>
          <span className="wmask">
            <motion.span className="w" initial={still ? false : { y: "110%" }} animate={{ y: "0%" }}
              transition={{ duration: 1, ease: EASE, delay: delay + i * 0.08 }}>{w}</motion.span>
          </span>
          {i < all.length - 1 ? " " : null}
        </span>
      ))}
    </span>
  );
}

/** Number that counts up the first time it's visible. */
export function CountUp({ value, duration = 1.1, delay = 0, className }: { value: number; duration?: number; delay?: number; className?: string }) {
  const ref = useRef<HTMLElement>(null);
  const inView = useInView(ref, { once: true });
  const still = useStill();
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
