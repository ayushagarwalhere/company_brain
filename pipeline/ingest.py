"""Phase 3 ingestion: sources -> Events -> base graph (people, messages, tickets, PRs, sprints).

python -m pipeline.ingest                 # offline: scenario files (default)
python -m pipeline.ingest --live          # Slack + Discord + GitHub APIs, tickets from JSON
python -m pipeline.ingest --reset         # drop the graph first
"""

import argparse

from connectors import docs, github, scenario, tickets
from graph import writer
from graph.db import get_graph


def collect(live: bool, log=print):
    """--live reads every configured source from its real API; a source with no credentials falls back to the
    scenario files, and the log says which is which (a Slack-only workspace is enough for a real run)."""
    if not live:
        return scenario.messages(), tickets.tickets(), github.pull_requests_from_scenario()
    from config import settings

    messages, used = [], []
    if settings.slack_bot_token:
        from connectors import slack as slack_conn

        messages += slack_conn.fetch_history()
        used.append("slack: live API")
    else:
        messages += [m for m in scenario.messages() if m.source == "slack"]
        used.append("slack: scenario files (SLACK_BOT_TOKEN not set)")
    if settings.discord_bot_token:
        from connectors import discord as discord_conn

        messages += discord_conn.fetch_history()
        used.append("discord: live API")
    else:
        messages += [m for m in scenario.messages() if m.source == "discord"]
        used.append("discord: scenario files (DISCORD_BOT_TOKEN not set)")
    if settings.github_repo:
        prs = github.pull_requests_from_api()
        used.append(f"github: live API ({settings.github_repo})")
    else:
        prs = github.pull_requests_from_scenario()
        used.append("github: scenario files (GITHUB_REPO not set)")
    log("sources: " + "; ".join(used))
    return messages, tickets.tickets(), prs


def ingest(live: bool = False, reset: bool = False, graph_name: str | None = None) -> dict:
    g = get_graph(graph_name)
    if reset:
        try:
            g.delete()
        except Exception:  # graph didn't exist yet
            pass
        g = get_graph(graph_name)
    writer.apply_schema(g)
    messages, ticket_events, prs = collect(live)

    writer.write_people(g, scenario.people())
    hr = scenario.hr()
    if hr:  # managers, access groups, time off
        writer.write_hr(g, hr)
    writer.write_sprints(g, scenario.sprints())
    writer.write_tickets(g, ticket_events)  # tickets before messages, so MENTIONS can link
    writer.write_messages(g, messages)
    writer.write_pull_requests(g, prs)
    writer.write_documents(g, docs.documents())  # docs come from files in both modes
    writer.link_doc_references(g)  # chat that names a doc by its title
    org = scenario.org()
    if org:  # teams, projects with launch dates, ticket dependencies, clients and deliverables (impact analysis)
        writer.write_org(g, org)
    from pipeline.knowledge import index_all

    index_all(g)  # chunks + embeddings in the vector index, MENTIONS edges and ACLs from the text
    return counts(g)


def counts(g) -> dict:
    nodes = g.query("MATCH (n) RETURN labels(n)[0] AS l, count(*) ORDER BY l").result_set
    rels = g.query("MATCH ()-[r]->() RETURN type(r) AS t, count(*) ORDER BY t").result_set
    return {"nodes": dict(nodes), "relationships": dict(rels)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--graph")
    a = ap.parse_args()
    c = ingest(live=a.live, reset=a.reset, graph_name=a.graph)
    for section, d in c.items():
        print(section + ":", ", ".join(f"{k}={v}" for k, v in d.items()))
