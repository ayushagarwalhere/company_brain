import { motion, useReducedMotion } from "framer-motion";
import { parsePath, typeColor, useStaticMode } from "../lib/ui";

const MAX_NODE = 56; // characters of node text shown; the full text is in the tooltip
const MAX_NOTE = 72;

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);

/** Splits ", a note, another note" on commas that are outside double quotes (quoted requirement text keeps its commas). */
function splitNotes(text: string): string[] {
  const out: string[] = [];
  let cur = "", quoted = false;
  for (const ch of text) {
    if (ch === '"') quoted = !quoted;
    if (ch === "," && !quoted) { out.push(cur); cur = ""; continue; }
    cur += ch;
  }
  out.push(cur);
  return out.map((x) => x.trim()).filter(Boolean);
}

/** Renders a graph path string as typed, coloured node chips joined by relationship labels. Each sub-path
    (separated by ";") is one wrapped row: node chip, edge label, node chip. Trailing notes after a node
    (", shipped the old version …", ", IMPLEMENTS older …") render as inline edge-style labels, clipped
    with the full text in a tooltip. */
export function PathChips({ path }: { path: string }) {
  const still = useReducedMotion() || useStaticMode();
  const tokens = parsePath(path);
  return (
    <div className="path">
      {tokens.map((t, k) => {
        const anim = still ? {} : { initial: { opacity: 0, y: 4 }, animate: { opacity: 1, y: 0 }, transition: { delay: 0.12 + k * 0.035, duration: 0.4 } };
        if (t.kind === "sep") return <span key={k} className="sep" />;
        if (t.kind === "rel") return <motion.span key={k} className="r" {...anim}>{t.dir === "in" ? "←" : ""}{t.rel}{t.dir === "out" ? "→" : ""}</motion.span>;
        if (t.kind === "text") {
          const notes = splitNotes(t.text);
          return notes.map((note, i) => (
            <motion.span key={`${k}-${i}`} className="r r--note" title={note.length > MAX_NOTE ? note : undefined} {...anim}>{clip(note, MAX_NOTE)}</motion.span>
          ));
        }
        return (
          <motion.span key={k} className="n" style={{ color: typeColor(t.type) }} title={t.label.length > MAX_NODE ? t.label : undefined} {...anim}>
            <b>{t.type}</b>{clip(t.label, MAX_NODE)}
          </motion.span>
        );
      })}
    </div>
  );
}
