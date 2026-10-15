import { motion, useReducedMotion } from "framer-motion";
import { parsePath, typeColor, useStaticMode } from "../lib/ui";

/** Renders a graph path string as typed, coloured node chips joined by relationship labels. */
export function PathChips({ path }: { path: string }) {
  const still = useReducedMotion() || useStaticMode();
  const tokens = parsePath(path);
  return (
    <div className="path">
      {tokens.map((t, k) => {
        const anim = still ? {} : { initial: { opacity: 0, y: 4 }, animate: { opacity: 1, y: 0 }, transition: { delay: 0.12 + k * 0.035, duration: 0.4 } };
        if (t.kind === "sep") return <span key={k} className="sep" />;
        if (t.kind === "rel") return <motion.span key={k} className="r" {...anim}>{t.dir === "in" ? "←" : ""}{t.rel}{t.dir === "out" ? "→" : ""}</motion.span>;
        if (t.kind === "text") return <motion.span key={k} className="t" {...anim}>{t.text}</motion.span>;
        return (
          <motion.span key={k} className="n" style={{ color: typeColor(t.type) }} title={t.label} {...anim}>
            <b>{t.type}</b>{t.label}
          </motion.span>
        );
      })}
    </div>
  );
}
