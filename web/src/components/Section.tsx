import { animate, useInView } from "framer-motion";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useStill } from "../lib/fx";
import { Reveal } from "./Motion";

/** "004" that ticks up from 000 the first time the section bar scrolls into view. */
export function TickIndex({ value }: { value: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-40px" });
  const still = useStill();
  const target = parseInt(value, 10) || 0;
  const [n, setN] = useState(still ? target : 0);
  useEffect(() => {
    if (still || !inView) { if (still) setN(target); return; }
    const c = animate(0, target, { duration: 0.6, ease: "easeOut", onUpdate: (v) => setN(Math.round(v)) });
    return () => c.stop();
  }, [inView, target, still]);
  return <span ref={ref} className="tick">{String(n).padStart(value.length, "0")}</span>;
}

/** Numbered section: "● 004  OPEN DRIFT ———" bar, large faded "04" behind the title, sticky label column, body. `wide`: heading row on top, full-width body. */
export function Section({ id, index, kicker, title, intro, aside, children, wide = false }: {
  id: string; index: string; kicker: string; title: string; intro: ReactNode; aside?: ReactNode; children: ReactNode; wide?: boolean;
}) {
  return (
    <section className={`sec ${wide ? "sec--wide" : ""}`} id={id}>
      <div className="sec__bar mono"><span><i className="sq" /><TickIndex value={index} /></span><span><i className="sq" />{kicker}</span></div>
      <Reveal className="sec__label">
        <span className="sec__num" aria-hidden>{index.slice(-2)}</span>
        <div className="sec__head">
          <h2>{title}</h2>
          <p>{intro}</p>
        </div>
        {aside}
      </Reveal>
      <Reveal className="sec__body" delay={0.08}>{children}</Reveal>
    </section>
  );
}
