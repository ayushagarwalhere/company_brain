import { parsePath } from "../lib/ui";

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

/** Renders a graph path string as typed node chips joined by relationship labels. Each sub-path (separated by ";")
    is one wrapped row. Trailing notes after a node render as dashed labels, clipped with the full text in a tooltip. */
export function PathChips({ path }: { path: string }) {
  return (
    <div className="path">
      {parsePath(path).map((t, k) => {
        if (t.kind === "sep") return <span key={k} className="sep" />;
        if (t.kind === "rel") return <span key={k} className="r">{t.dir === "in" ? "←" : ""}{t.rel}{t.dir === "out" ? "→" : ""}</span>;
        if (t.kind === "text") {
          return splitNotes(t.text).map((note, i) => (
            <span key={`${k}-${i}`} className="r r--note" title={note.length > MAX_NOTE ? note : undefined}>{clip(note, MAX_NOTE)}</span>
          ));
        }
        return <span key={k} className="n" title={t.label.length > MAX_NODE ? t.label : undefined}><b>{t.type}</b>{clip(t.label, MAX_NODE)}</span>;
      })}
    </div>
  );
}
