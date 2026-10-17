# "Implement BD-101": a coding agent with and without company context

A tiny helpdesk app with one unimplemented function, `helpdesk/export.py`, and `tickets/BD-101.md`, the ticket as the
tracker shows it: "export tickets created in the last 30 days". A week after the ticket was written, the product
manager changed it in Slack: any date range up to 12 months, plus every custom field as a column. The ticket was
never updated, and PR #6 shipped the 30-day version anyway. That's the demo company's drift on BD-101.

Ask a coding agent to "implement BD-101" twice:

| | What the agent sees | What it builds |
|---|---|---|
| **Without MCP** | the ticket | last 30 days, five columns, custom fields left out "since the ticket lists only five columns" |
| **With MCP** | `current_spec("BD-101")` from the graph | any range up to 12 months, custom fields as columns, cites Maya's Slack decision, says PR #6 and the PRD carry the old version |

Both runs, word for word with the code they wrote: [RUNS.md](RUNS.md).

## Record it (about a minute)

1. Run Company Brain with the demo company (the README's quick start, from the repo root), or point `.mcp.json` at
   the hosted server (below):

   ```bash
   docker run -d --name falkordb-brain -p 6379:6379 falkordb/falkordb:v4.22.1
   python -m pipeline.build
   uvicorn api.main:app --port 8000
   ```

2. Without company context (`--strict-mcp-config` with no config means no MCP servers):

   ```bash
   cd examples/mcp-demo
   claude --strict-mcp-config
   > implement BD-101
   ```

3. Reset the file, then the same prompt with the MCP server from [`.mcp.json`](.mcp.json) (approve it when asked):

   ```bash
   git checkout helpdesk/export.py
   claude
   > implement BD-101
   ```

## Connect your own agent

The server exposes six read-only tools: `current_spec(ticket)`, `drift(feature?)`, `who_knows(topic)`,
`decision_history(topic)`, `impact(target, days)` and `find(query)`.

```bash
# hosted: the API serves MCP at /mcp (X-Org picks a team's graph; the demo company is the default)
claude mcp add --transport http company-brain https://<your-host>/mcp
claude mcp add --transport http company-brain https://<your-host>/mcp --header "X-Org: slack-ab12cd34"

# local, over stdio, from the repo root
claude mcp add company-brain -- python -m agent.mcp_server
```

Any MCP client works the same way (Cursor, Windsurf, VS Code). The tools are read-only: every query runs as FalkorDB's
`GRAPH.RO_QUERY`, and answers are filtered for the viewer (`X-User`) like the dashboard's.
