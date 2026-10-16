"""Tiny TF-IDF cosine similarity: resolution signal 3 (semantic) without a model download.

DeepSeek has no embeddings endpoint, and a local transformer is heavy for a
hackathon box; TF-IDF over feature/ticket text is deterministic and explainable.
"""
import math
import re
from collections import Counter

STOP = set("""a an the and or but if of to in on for with at by from as is are was were be been it this that
these those we you i they he she our your their my me us them can could should would will just so not no yes
do does did have has had there here what when where who how which also too very about into than then out up
let lets let's ok okay still only all any some one two get got make made need needs want wants""".split())


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    out = []
    for w in words:
        if w in STOP or len(w) < 2:
            continue
        if len(w) > 4 and w.endswith("s"):
            w = w[:-1]
        out.append(w)
    return out


class TfIdf:
    def __init__(self, docs: dict[str, str]):
        self.ids = list(docs)
        tfs = {k: Counter(tokens(v)) for k, v in docs.items()}
        df = Counter(t for tf in tfs.values() for t in tf)
        n = len(docs)
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
        self.vecs = {k: self._vec(tf) for k, tf in tfs.items()}
        # inverted index: token -> [(doc, weight)]. A query only touches docs that share a token with it,
        # instead of walking every doc's vector (profiled: 92% of resolve time at 20k messages before this).
        self.postings: dict[str, list[tuple[str, float]]] = {}
        for k, vec in self.vecs.items():
            for t, w in vec.items():
                self.postings.setdefault(t, []).append((k, w))

    def _vec(self, tf: Counter) -> dict[str, float]:
        v = {t: c * self.idf.get(t, 0.0) for t, c in tf.items() if t in self.idf}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def scores(self, text: str) -> dict[str, float]:
        q = self._vec(Counter(tokens(text)))
        out = dict.fromkeys(self.ids, 0.0)  # every doc, in insertion order: same ties and zeros as a dense scan
        for t, qw in q.items():
            for k, w in self.postings.get(t, ()):
                out[k] += qw * w
        return out

    def best(self, text: str, among: list[str] | None = None) -> tuple[str | None, float]:
        s = self.scores(text)
        cands = [(k, v) for k, v in s.items() if among is None or k in among]
        if not cands:
            return None, 0.0
        return max(cands, key=lambda kv: kv[1])
