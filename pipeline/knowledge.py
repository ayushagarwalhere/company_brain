"""Document knowledge kept in sync: chunks, embeddings in a FalkorDB vector index, and the graph edges around them.

(Document)-[:HAS_CHUNK]->(Chunk {id: "<doc>#<n>", text, hash, vec, acl})

* One store: the vectors live in the same FalkorDB graph as the entities, in a vector index on Chunk.vec, so a
  semantic hit is one hop from its document, author, tickets and access list. No second database to keep in step.
* Incremental: sync_document() splits the new text, keeps every chunk whose content hash is unchanged (no
  re-embedding), embeds only new or changed chunks, and deletes chunks that disappeared. The document's MENTIONS
  edges are recomputed (tickets named in the new text plus those declared in its metadata; added AND removed), and its
  ACL is copied onto its chunks.
* Embeddings: any OpenAI-compatible /embeddings endpoint (EMBED_BASE_URL / EMBED_MODEL / EMBED_API_KEY). Without
  one, a deterministic local embedding (signed feature hashing of words and word pairs, 1024 dims, L2-normalised):
  lexical rather than semantic, but stable, free and offline. Each chunk records which embedder made it, and
  switching embedder re-embeds everything on the next sync (the hash includes the embedder).
* Retrieval is hybrid: nearest chunks from the vector index, kept only if they share at least one content word with
  the question (a guard against hash collisions in the local embedding). The thresholds were set on 12 hand-written
  questions (7 relevant, 5 not), so they are a starting point, not a measured result; a real embedding model is better.
"""

import hashlib
import math
import re

from graph import queries as Q
from pipeline.access import VISIBLE, grants
from pipeline.textsim import tokens

DIM = 1024
CHUNK_CHARS = 400


def _embed_cfg() -> tuple[str, str, str]:
    import os

    return os.getenv("EMBED_BASE_URL", ""), os.getenv("EMBED_MODEL", ""), os.getenv("EMBED_API_KEY", "")


def embedder_name() -> str:
    base, model, _ = _embed_cfg()
    return f"api:{model}" if base and model else f"hash{DIM}"


def _hash_embed(text: str) -> list[float]:
    toks = tokens(text)
    feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:], strict=False)]
    v = [0.0] * DIM
    for f in feats:
        h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
        v[h % DIM] += 1.0 if (h >> 32) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def embed(texts: list[str]) -> list[list[float]]:
    base, model, key = _embed_cfg()
    if not (base and model):
        return [_hash_embed(t) for t in texts]
    from openai import OpenAI

    out = OpenAI(api_key=key or "none", base_url=base).embeddings.create(model=model, input=texts)
    return [d.embedding for d in out.data]


def chunk(text: str) -> list[str]:
    """Paragraph-aware chunks of about CHUNK_CHARS characters."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    out, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) > CHUNK_CHARS:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        out.append(cur)
    return out


def _hash(text: str) -> str:
    return hashlib.sha1(f"{embedder_name()}|{text}".encode()).hexdigest()[:16]


def ensure_index(g, dim: int | None = None) -> None:
    try:
        g.query(f"CREATE VECTOR INDEX FOR (c:Chunk) ON (c.vec) OPTIONS {{dimension: {dim or _dim()}, similarityFunction: 'cosine'}}")
    except Exception as e:  # noqa: BLE001 - already exists
        if "already" not in str(e).lower():
            raise


def _dim() -> int:
    return DIM if embedder_name().startswith("hash") else len(embed(["dimension probe"])[0])


def sync_document(g, doc_id: str) -> dict:
    """Bring a document's chunks, embeddings, MENTIONS edges and ACL in line with its current text."""
    from pipeline.events import find_ticket_refs

    d = Q.rows(g, "MATCH (d:Document {id: $id}) RETURN d.text AS text, d.acl AS acl, coalesce(d.declared, []) AS declared", id=doc_id)
    if not d:
        raise ValueError(f"unknown doc {doc_id}")
    text, acl = d[0]["text"] or "", d[0]["acl"] or []
    parts = chunk(text)
    want = {f"{doc_id}#{i}": (p, _hash(p)) for i, p in enumerate(parts)}
    have = {r["id"]: r["hash"] for r in Q.rows(g, "MATCH (:Document {id: $id})-[:HAS_CHUNK]->(c:Chunk) RETURN c.id AS id, c.hash AS hash", id=doc_id)}
    changed = [cid for cid, (_, h) in want.items() if have.get(cid) != h]
    removed = [cid for cid in have if cid not in want]
    if changed:
        ensure_index(g)
        vecs = embed([want[c][0] for c in changed])
        g.query(
            """UNWIND $rows AS r MATCH (d:Document {id: $doc})
               MERGE (c:Chunk {id: r.id}) SET c.text = r.text, c.hash = r.hash, c.vec = vecf32(r.vec), c.embedder = $emb
               MERGE (d)-[:HAS_CHUNK]->(c)""",
            {
                "doc": doc_id,
                "emb": embedder_name(),
                "rows": [{"id": c, "text": want[c][0], "hash": want[c][1], "vec": v} for c, v in zip(changed, vecs, strict=True)],
            },
        )
    if removed:
        g.query("MATCH (c:Chunk) WHERE c.id IN $ids DETACH DELETE c", {"ids": removed})
    g.query("MATCH (:Document {id: $id})-[:HAS_CHUNK]->(c:Chunk) SET c.acl = $acl", {"id": doc_id, "acl": acl})
    # graph edges follow the text: a ticket the doc no longer mentions loses its MENTIONS edge
    refs = sorted(set(find_ticket_refs(text)) | set(d[0]["declared"]))  # named in the text, or declared in the doc's metadata
    dropped = Q.rows(g, "MATCH (d:Document {id: $id})-[m:MENTIONS]->(t:Ticket) WHERE NOT t.id IN $refs DELETE m RETURN t.id AS t", id=doc_id, refs=refs)
    g.query("UNWIND $refs AS ref MATCH (d:Document {id: $id}), (t:Ticket {id: ref}) MERGE (d)-[:MENTIONS]->(t)", {"id": doc_id, "refs": refs})
    return {
        "doc": doc_id,
        "chunks": len(want),
        "embedded": len(changed),
        "kept": len(want) - len(changed),
        "removed": len(removed),
        "mentions": refs,
        "mentions_dropped": [r["t"] for r in dropped],
        "embedder": embedder_name(),
        # per chunk, in document order: what happened to its vector
        "parts": [{"id": c, "status": "embedded" if c in changed else "kept", "chars": len(want[c][0])} for c in want]
        + [{"id": c, "status": "removed", "chars": 0} for c in removed],
    }


def index_all(g) -> dict:
    """Sync every document (used after a full ingest)."""
    out = [sync_document(g, r["id"]) for r in Q.rows(g, "MATCH (d:Document) RETURN d.id AS id ORDER BY id")]
    return {"docs": len(out), "chunks": sum(o["chunks"] for o in out), "embedded": sum(o["embedded"] for o in out)}


def _with_singulars(query: str) -> str:
    """'salaries' also searches 'salary': tokens() drops a plural -s ('bands' -> 'band') but turns '-ies' into '-ie',
    so a question with 'salaries' would miss a doc that says 'salary'. Only the query is expanded; stored vectors are unchanged."""
    extra = [w[:-3] + "y" for w in re.findall(r"[a-z]+", query.lower()) if len(w) > 4 and w.endswith("ies")]
    return " ".join([query, *extra])


def search(g, query: str, viewer: str | None, k: int = 5) -> list[dict]:
    """Nearest chunks the viewer may see, with their document. The ACL filter is part of the vector query itself."""
    if not query.strip() or not g.ro_query("MATCH (c:Chunk) RETURN c LIMIT 1").result_set:
        return []
    query = _with_singulars(query)
    q = embed([query])[0]
    rows = Q.rows(
        g,
        f"""CALL db.idx.vector.queryNodes('Chunk', 'vec', $k, vecf32($q)) YIELD node AS n, score
            WHERE {VISIBLE}
            MATCH (d:Document)-[:HAS_CHUNK]->(n) OPTIONAL MATCH (a:Person)-[:AUTHORED]->(d)
            RETURN d.id AS doc, d.title AS title, a.id AS author, d.updated AS updated, n.id AS chunk, n.text AS text,
                   round(1000 * (1 - score)) / 1000.0 AS similarity
            ORDER BY score""",
        k=max(k * 4, 20),
        q=q,
        grants=grants(g, viewer),
    )
    qt = set(tokens(query))
    return [r for r in rows if qt & set(tokens(r["text"] or ""))][:k]  # hybrid: must share a content word
