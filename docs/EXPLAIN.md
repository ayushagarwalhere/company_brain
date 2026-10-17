# How the core parts work

This covers six pieces: the drift query, the supersession chain, the connection query, paged reads, the MCP server's `current_spec` and the try-your-repo pipeline. For each: what it does, why it's written this way, what breaks without it, and two questions a reviewer might ask.

---

## 1. `DRIFT`: the core query

[`graph/queries.py`](../graph/queries.py)

```cypher
MATCH (m:Message)-[:CHANGES]->(r:Requirement)-[:AMENDS]->(t:Ticket)-[:ABOUT]->(f:Feature)
WHERE NOT (r)<-[:SUPERSEDES]-(:Requirement)
  AND NOT (:PullRequest)-[:IMPLEMENTS]->(r)
  AND NOT (:Decision)-[:DISMISSES]->(r)
  AND ($feature IS NULL OR f.id = $feature)
  AND ($ticket IS NULL OR t.id = $ticket)
MATCH (author:Person)-[:POSTED]->(m)
OPTIONAL MATCH (r)-[:SUPERSEDES]->(prev:Requirement)
OPTIONAL MATCH (pr:PullRequest)-[:REFERENCES]->(t)
OPTIONAL MATCH (pr)-[:IMPLEMENTS]->(old:Requirement)
OPTIONAL MATCH (doc:Document)-[:MENTIONS]->(t) WHERE doc.updated_ms < r.at_ms
RETURN ..., collect(DISTINCT {pr: pr.number, implements: old.text}) AS stale_prs, collect(DISTINCT {...doc}) AS stale_docs
```

**What it does.** It finds every requirement that came from chat (`Message -CHANGES->`) where all three of these hold:
- it is still the newest requirement for its ticket (nothing `SUPERSEDES` it);
- no PR `IMPLEMENTS` it;
- nobody decided to keep the old scope (`DISMISSES`).

For each one it collects the evidence:
- who said it and where;
- what the ticket said before (`prev`);
- the PRs on that ticket and which older version they implement;
- docs about the ticket that were last edited before the change.

**Why it's written this way.**
- **Drift is defined by what's absent.** No newer version and no implementation. That makes it three `NOT` pattern predicates on one requirement node, not a search.
- **Each ticket version is its own `Requirement` node.** A requirement is current when nothing supersedes it, so the query never compares text or timestamps at read time. That work happens once, when the `SUPERSEDES` chain is built (section 2).
- **The evidence is `OPTIONAL`.** A drift with no PR yet is still drift.
- **`collect(DISTINCT …)`** stops one PR × two docs from becoming two rows.
- **Doc staleness is a time comparison** (`doc.updated_ms < r.at_ms`). A doc edited after the decision isn't stale.
- **`DRIFT_FOR_TICKET`** is the same query anchored on the `Requirement.ticket` index. The live monitor checks one ticket in about 1 ms instead of scanning every chat requirement (about 39 ms at 20k messages, `benchmark/results/scale_200x20000.json`).

**What breaks without it.**
- **Without the `SUPERSEDES` predicate,** every chat change that was later written into its ticket is still flagged. In the ablation that's half of all alerts (drift precision 0.50; [`benchmark/ablation.py`](../benchmark/ablation.py)).
- **Without the `IMPLEMENTS` predicate,** a decision that a PR did ship is still reported.
- **Without `DISMISSES`,** "keep old scope" on a drift card would have no lasting effect.

**Q: Why not store a `status: 'drift'` flag on the requirement and query that?**
A: Drift depends on edges that arrive from different sources at different times: a ticket webhook adds a version, a GitHub webhook adds `IMPLEMENTS`, a person dismisses. A stored flag has to be recomputed by every writer, and one that forgets leaves it wrong. Deriving drift from the edges means each writer only adds the fact it knows. The flag would only be a cache, and the per-ticket query is already about 1 ms.

**Q: Couldn't a relational database do this?**
A: Yes, and I measured it ([`benchmark/sql_baseline.py`](../benchmark/sql_baseline.py)). Load the same extracted facts and the same supersession pairs into SQLite, and drift is a 6-line anti-join that finds exactly the same requirements, faster. Without the version chain ("newest requirement per ticket wins"), SQL falls for the same noise trap the first version of this project did. So the work is in building the chain correctly; the graph gives the evidence path, variable-depth connection queries and schema flexibility on top.

**Q: Couldn't a vector search over messages and tickets find this?**
A: Similarity tells you a message and a ticket are about the same thing. Drift is about order and coverage: is there a *newer* version, and did a PR implement *this* one. Vectors carry neither. In my no-LLM benchmark, retrieval found the right passages for most questions but couldn't say whether BD-103 is still accurate. The graph could (q05).

---

## 2. `supersession_pairs`: building the version chain

[`pipeline/resolve.py`](../pipeline/resolve.py)

```python
def supersession_pairs(chain, reflects, replaces=None):
    pairs, heads, last_ticket_text = [], [], ""
    for r in chain:                                   # one ticket's requirements, in time order
        if r["origin"] == "ticket":
            r = {**r, "prev_text": last_ticket_text}  # lets reflects() see what this edit ADDED
            last_ticket_text = r["text"]
        keep = []
        for h in heads:
            if h["origin"] == "ticket":
                ok = True                             # anything supersedes an older ticket version
            elif r["origin"] == "ticket":
                ok = reflects(r, h)                   # a ticket edit must carry the chat change
            else:                                     # chat over chat: only when judged to, and as confident
                ok = (replaces is not None and (r.get("confidence") or 0) >= (h.get("confidence") or 0)
                      and replaces(r, h))
            if ok:
                pairs.append({"new": r["id"], "old": h["id"]})
            else:
                keep.append(h)
        heads = [r] + keep
    return pairs
```

**What it does.** It walks one ticket's requirements oldest to newest and keeps the set of current "heads". Each new requirement supersedes only the heads it actually replaces:
- **Anything supersedes an older ticket version.** A chat decision changes what the ticket should say.
- **A ticket version supersedes a chat change only if `reflects(new_version, chat_change)` is true.** Otherwise the chat change stays a head next to the new version, and the drift query keeps flagging it.
- **A chat change supersedes an earlier chat change only if `replaces(new, old)` judges that it revises that decision, and it is at least as confident.** The rules extractor has no such judgment (`replaces=None`), so with rules chat never supersedes chat.

**Why it's written this way.**
- **Ticket edits happen for unrelated reasons:** typo fixes, labels, formatting. "The ticket was edited after the decision" is the obvious rule and it's wrong. It would let a cosmetic edit silently hide drift.
- **Being the latest chat message is not evidence either.** That was the original rule ("a chat change supersedes every head"), and [`benchmark/noise.py`](../benchmark/noise.py) showed what it costs. One misread status update ("merged the fix for BD-101") became the newest requirement and buried the real decision: 0 of 2 real drifts found under 500 noise messages. With the current rule it's 2 of 2.
- **`prev_text` lets `reflects` judge only the words the edit *added*.** With rules, the added words must share content with the chat change, ignoring edit chatter like "typo fixed". If the change has numbers ("12 months"), at least one must be among the added words. The LLM makes the same judgment with a prompt.
- **More than one head at a time** is how "the ticket moved on, but not in the direction chat decided" is represented, and how two open decisions coexist.
- **It's a pure function over a list,** so the logic is unit-tested without a database. The batch build, the live monitor and the ticket webhook all use it ([`pipeline/webhooks.py`](../pipeline/webhooks.py)).

**What breaks without it.**
- **With no chain at all** (the ablation's `supersession` switch), every chat change looks current forever. Drift precision drops to 0.50.
- **With the naive "any later edit supersedes" rule,** the `(typo fixed)` edit in [`tests/test_api.py`](../tests/test_api.py) would resolve the BD-101 drift. That test exists to stop exactly this.
- **With "the latest chat message wins",** noise hides real drift (above).
- **The cost of the current rule:** a misread message now shows up as its own false alert instead of hiding a real one. Under noise, with the rule extractor, that's 14 noise-caused false alerts instead of 5 (`benchmark/results/noise.json`).

**Q: Why not let the newest chat message win? It usually is the latest intent.**
A: Because the extractor decides what counts as a "message that changes a requirement", and on real text it's often wrong. Under "newest wins", every extraction mistake silently deletes a real drift from the report. Under "replace only when judged to", the same mistake produces a visible alert someone can dismiss. Between a quiet miss and a noisy false positive, I chose the failure a human can see.

**Q: Isn't `reflects` (and now `replaces`) doing all the real work? What if they're wrong?**
A: Yes, the chain depends on those judgments, and the Limitations section says so.
- **A wrong "yes"** hides drift.
- **A wrong "no"** keeps a drift open. That's the safer failure, because a person can dismiss it.

Keeping each one as an injected function means it can be swapped (rules, LLM or oracle) and tested in isolation.

**Rebuild rule.** `resolve()` deletes and recomputes only what the pipeline derives (features, requirements, extractor-made decisions); human actions carry `origin: 'human'` and the stable ids they attach to (`req:<ticket>:vN`, `req:<message id>`), and are re-attached at the end of every resolve ([`pipeline/human.py`](../pipeline/human.py)). A full `pipeline.build` wipes the graph, so it snapshots dismissals and written-back ticket versions first and restores them after ingest; only "Reset demo data" deliberately throws them away (`tests/test_human_actions.py`).

---

## 3. `CONNECTION`: the shortest causal chain between two things

[`graph/queries.py`](../graph/queries.py)

```cypher
MATCH (a:__LA__ {id: $a}), (b:__LB__ {id: $b})
CALL algo.SPpaths({sourceNode: a, targetNode: b, relDirection: 'both', maxLen: 7, pathCount: 1,
                   relTypes: ['POSTED','REPLY_TO','CHANGES','AMENDS','STATES','REFERENCES','IMPLEMENTS','MADE',
                              'AUTHORED','ASSIGNED_TO','SUPERSEDES','MENTIONS','RECORDED_IN']})
YIELD path
RETURN [n IN nodes(path) | {id: n.id, type: labels(n)[0]}] AS nodes, [r IN relationships(path) | type(r)] AS rels, ...
```

**What it does.** It answers "how is `liam` connected to `PR-6`?" with the shortest path between any two ids, ignoring edge direction. For example: Liam posted a message → a reply → Maya's decision → requirement → BD-101 ← PR #6.

**Why it's written this way.**
- **`algo.SPpaths` with `relDirection: 'both'`.** Cypher's `shortestPath` in FalkorDB is directed-only, but causal chains go both ways along edges: a PR *references* a ticket, and a person *posted* a message.
- **`relTypes` leaves out `ABOUT`.** Without that, almost every pair connects in 2 hops through the Feature hub ("both are about export"). That's true but explains nothing.
- **`maxLen: 7` and `pathCount: 1`** bound the work.
- **Labelled endpoints.** `__LA__`/`__LB__` are replaced with labels from `label_of()`, which only returns names from a fixed whitelist, so nothing user-supplied reaches the query text. Both endpoints are then found through per-label id indexes. An unlabelled `MATCH (a {id: $a})` scans every node. [`scripts/explain_queries.py`](../scripts/explain_queries.py) fails CI if that comes back.
- **Placeholder replacement, not `str.format`.** Cypher's own `{…}` braces clash with Python formatting.

**What breaks without it.** The first version enumerated every undirected variable-length path up to 7 hops and then sorted by length. That grows exponentially with node degree. On the 20,800-message stress-test graph it timed out; `SPpaths` answers in about 4 ms (p50). Including `ABOUT` makes the answers useless rather than slow.

**Q: Why not just make every edge bidirectional, or store the reverse edges?**
A: It doubles the edges and the write cost, and it blurs meaning: `IMPLEMENTS` has a direction that the drift query relies on. Direction is a property of the query here (`relDirection: 'both'`), not of the data, so the same edges serve both directed questions like drift and undirected ones like connection.

**Q: Shortest isn't always most meaningful. How do you stop trivial paths?**
A: By choosing which edge types count. Leaving out `ABOUT` is the main lever. The rest are causal edges: someone posted it, it changes this, this implements that. A weighted path, for example preferring `CHANGES`/`IMPLEMENTS`, would be the next step. I haven't built it.

---

## 4. Paged reads: `_rows_paged`

[`pipeline/resolve.py`](../pipeline/resolve.py)

```python
PAGE = 5000

def _rows_paged(g, q, params=None, page=PAGE):
    out, skip = [], 0
    while True:
        batch = _rows(g, q + " SKIP $_skip LIMIT $_limit", {**(params or {}), "_skip": skip, "_limit": page})
        out += batch
        if len(batch) < page:
            return out
        skip += page
```

**What it does.** It reads a large result in pages of 5,000 rows until a short page comes back. It's used for messages and requirements, the two reads that grow with company size.

**Why it's written this way.**
- **The cap.** FalkorDB's Docker image caps result sets (`RESULTSET_SIZE`, 10,000 by default). Past that, a query returns the first 10k rows **without an error**.
- **Stable order.** The query must end in a stable `ORDER BY` (`ts_ms, id`), or `SKIP` could skip or repeat rows between pages. The `id` tie-breaker matters, because two messages can share a timestamp.
- **Page size.** 5,000 stays well under the cap and keeps the number of round-trips small.

**What breaks without it.** At 20,800 messages the resolver saw only the first 10,000. Drift recall in the stress test fell from 1.00 to 0.70, and nothing logged an error. That silence is why there is a regression test ([`tests/test_paging.py`](../tests/test_paging.py)): it writes more rows than the cap and checks every one comes back in order.

**Q: Why not raise `RESULTSET_SIZE` in the server config?**
A: It's a server setting I don't control on FalkorDB Cloud or someone else's deployment, and it exists to protect the server's memory. Paging works under any cap and never holds one huge reply. The cost is a few extra round-trips, which stay small next to resolution time.

**Q: `SKIP` gets slower as the offset grows. Isn't this quadratic?**
A: In principle each page re-scans up to its offset. At this size it's 5 pages, and resolve takes about 3 s in total for the whole 20k graph. At much larger scale, keyset pagination (`WHERE (m.ts_ms, m.id) > (last_ts, last_id) … LIMIT n`) on the `Message.ts_ms` index would avoid re-scanning. It's a small change I haven't needed yet.

---

## 5. `current_spec`: the MCP tool a coding agent calls first

[`agent/mcp_server.py`](../agent/mcp_server.py)

**What it does.** Given a ticket id, it answers "what should I build?" from the graph, not from the ticket text:
- the open drift on that ticket (the `DRIFT` query with `$ticket`): if there is one, the newest chat requirement is
  `current_requirement`, with who decided it, the channel, the time, the message and its link, plus what the ticket still
  says, the PRs that shipped the old version and the stale docs;
- otherwise the newest requirement nothing supersedes (`NOT (r)<-[:SUPERSEDES]-()`), which is the ticket's own text;
- the owners, the three people `WHO_KNOWS` ranks highest, the version history and the graph paths behind each fact.

The server's `instructions` (sent to the client at the MCP handshake) tell the agent to call it before implementing a
ticket and to build what it returns. That paragraph is the only prompt; there is no CLAUDE.md in the demo.

**Why it's written this way.**
- **Thin wrappers, no new queries.** Every fact comes from the same queries the dashboard uses (`Q.drift`,
  `DECISION_HISTORY`, `WHO_KNOWS`), through `GRAPH.RO_QUERY`, then `redact` for the viewer. An agent can't write, and
  can't see a doc its user couldn't.
- **One call, not six.** Agents skip tools. The tool an agent will call anyway (it has a ticket id) returns everything
  needed to build the right thing, so the correct behaviour doesn't depend on a chain of good choices.
- **Org and viewer per call.** Over HTTP they come from `X-Org` / `X-User` (or `?org=` / `?as=`), read from the request
  inside the tool; over stdio from `BRAIN_ORG` / `BRAIN_USER`. The tool doesn't rely on the API middleware's context
  variables reaching the MCP transport's task.

**What breaks without it.** The recorded runs ([`examples/mcp-demo/RUNS.md`](../examples/mcp-demo/RUNS.md)): without the
server, Claude Code built the ticket's 30-day export and left the custom fields out; with it, the 12-month export with
every custom field, citing the decision and PR #6.

**Q: Two runs prove nothing. How do you know it generalises?**
A: They don't, and the README says so. What is guaranteed is narrower: the current requirement and its source are one
call away, and the server tells the agent to make that call. Whether a given model makes it is the model's behaviour;
both runs are in the repo so anyone can repeat them.

**Q: On a real repo the extractor is often wrong. Won't `current_spec` mislead an agent?**
A: On a public repo's graph it adds the rules extractor's measured precision as a caveat, and any earlier hand-check of
that flag (both FalkorDB flags are known false positives). On the demo company, the rules were tuned on that very data,
which is exactly why the real-data numbers are published next to it.

---

## 6. Try your repo: a public repo's graph in under 20 seconds

[`pipeline/tryrepo.py`](../pipeline/tryrepo.py)

**What it does.** Reads a public repo's 150 most recently updated issues, 100 PRs, up to 25 older issues those PRs name,
and 400 recent comments; maps them with the real-data adapter (issue → `Ticket GH-n`, comment → `Message` that
`MENTIONS` it, PR → `PullRequest`, `#12` → `GH-12`); runs the full `resolve` with the rules extractor and one feature per
issue; then answers from graph queries: people, who knows what per label, issue ← PR chains (`REFERENCES`), open issues no
PR names, decisions (`CHANGES`) and drift.

**Why it's written this way.**
- **The same pipeline as the benchmark.** No new extraction code, so what judges see on their own repo is what the
  published real-data numbers measure.
- **Rules, not an LLM.** Fast, free, and deterministic; the cost is low precision on real text, shown on the page with
  the number (0.17 on 60 labelled comments).
- **One feature per issue.** The rules' label groups are named after an arbitrary member issue, which reads as nonsense
  on a real repo; per-issue features keep names true and make "who knows #3070" work.
- **Guards.** Private repos refused even if the server token could read them; two builds at a time; a 12-hour cache;
  at most 40 repo graphs; every write endpoint 403 on a repo's graph.

**What breaks without it.** Judges only see the synthetic company, whose 1.00 is an upper bound. Here they see where it
works (links GitHub already has) and where it doesn't (drift), on data nobody tuned for.

**Q: Why are issue ← PR chains reliable but drift isn't?**
A: Chains come from text GitHub users write to link things ("fixes #12"), which the hard-id resolver reads exactly. Drift
needs a judgement that a comment changes the requirement, which is the extractor's weak spot on review-heavy repos.

**Q: Why the most recently *updated* issues, not the newest?**
A: Activity is where knowledge and decisions are. The newest issues are often untriaged; recently updated ones carry
the discussion, the labels and the linked PRs.
