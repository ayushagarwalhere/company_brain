"""Human actions on drift, kept apart from everything the pipeline can rebuild.

Derived data (Feature, Requirement, extractor Decisions) is recomputed by every resolve(). Human actions
are not derivable from the sources, so they carry `origin: 'human'` and the stable ids they attach to
(requirement ids are deterministic: req:<ticket>:vN and req:<message id>):

  dismissal   (Person)-[:MADE]->(Decision {origin: 'human', kind: 'dismissal', target})-[:DISMISSES]->(Requirement)
  write-back  the ticket's new description version, recorded on the Ticket as parallel lists
              wb_versions / wb_targets / wb_actors, plus SUPERSEDES from that version to the chat requirement

resolve() keeps human Decisions and calls relink() at the end. A full build wipes the graph, so it takes a
snapshot() first and restore()s it after ingest (pipeline.build.build_graph).
"""


def snapshot(g) -> dict:
    """Every human action in the graph, as plain data that survives a graph wipe."""

    def rows(q):
        try:
            res = g.query(q)
        except Exception:  # noqa: BLE001 - the graph may not exist yet
            return []
        cols = [c[1] if isinstance(c, (list, tuple)) else c for c in res.header]
        return [dict(zip(cols, r, strict=False)) for r in res.result_set]

    dismissals = rows("""MATCH (d:Decision {origin: 'human'}) OPTIONAL MATCH (p:Person)-[:MADE]->(d)
                         RETURN d.id AS id, d.kind AS kind, d.text AS text, d.at AS at, d.at_ms AS at_ms,
                                d.target AS target, p.id AS actor""")
    writebacks = rows("""MATCH (t:Ticket) WHERE t.wb_versions IS NOT NULL
                         RETURN t.id AS ticket, t.versions AS versions, t.version_times AS times,
                                t.wb_versions AS wb_versions, t.wb_targets AS wb_targets, t.wb_actors AS wb_actors,
                                t.description AS description, t.desc_updated_ms AS desc_ms, t.updated AS updated,
                                t.updated_ms AS updated_ms""")
    return {"dismissals": dismissals, "writebacks": writebacks}


def restore(g, snap: dict) -> None:
    """After a fresh ingest: put written-back ticket versions back on their tickets and recreate the
    human Decision nodes. resolve() then rebuilds requirements from the versions and relink() attaches."""
    for w in snap.get("writebacks", []):
        g.query(
            """MATCH (t:Ticket {id: $ticket})
                   SET t.versions = $versions, t.version_times = $times, t.description = $description,
                       t.desc_updated_ms = $desc_ms, t.updated = $updated, t.updated_ms = $updated_ms,
                       t.wb_versions = $wb_versions, t.wb_targets = $wb_targets, t.wb_actors = $wb_actors""",
            w,
        )
    for d in snap.get("dismissals", []):
        g.query(
            """MERGE (d:Decision {id: $id})
                   SET d.origin = 'human', d.kind = $kind, d.text = $text, d.at = $at, d.at_ms = $at_ms, d.target = $target
                   WITH d MATCH (p:Person {id: $actor}) MERGE (p)-[:MADE]->(d)""",
            d,
        )


def relink(g) -> dict:
    """Re-attach human actions to the freshly rebuilt requirements by their stable ids."""
    dis = g.query("""MATCH (d:Decision {origin: 'human', kind: 'dismissal'}) MATCH (r:Requirement {id: d.target})
                     MERGE (d)-[:DISMISSES]->(r) RETURN count(r)""").result_set[0][0]
    wb = g.query("""MATCH (t:Ticket) WHERE t.wb_versions IS NOT NULL
                    UNWIND range(0, size(t.wb_versions) - 1) AS i
                    MATCH (v:Requirement {id: t.wb_versions[i]}), (chat:Requirement {id: t.wb_targets[i]})
                    SET v.written_by = t.wb_actors[i]
                    MERGE (v)-[:SUPERSEDES]->(chat) RETURN count(v)""").result_set[0][0]
    return {"dismissals": dis, "writebacks": wb}
