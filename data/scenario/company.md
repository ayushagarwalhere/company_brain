# Fictional company: Brightdesk

**Brightdesk** is a 9-person startup that sells a helpdesk SaaS for small support teams: a shared inbox, tickets, SLAs and reporting. Everything in this folder is synthetic.

- Product: web app (React frontend, Python backend)
- Chat: Slack (`#product`, `#engineering`, `#support-escalations`) and Discord (`#engineering`, `#design`, `#random`)
- Tickets: Linear-style, IDs `BD-101` to `BD-115`
- Code: one public GitHub repo, with PRs that refer to tickets inconsistently (on purpose)
- Docs: 4 Markdown product docs in [`data/docs/`](../docs/): the export PRD (`DOC-1`, last updated 09-15), the SLA design note (`DOC-2`, never updated), the theming RFC (`DOC-3`, updated 10-02 06:10, right after the toggle decision) and an unrelated onboarding copy guide (`DOC-4`)

## People

| id | Name | Role | Mostly active in |
|---|---|---|---|
| `maya` | Maya Chen | Product Manager | Slack #product, Discord #engineering |
| `arjun` | Arjun Mehta | Engineering Lead | everywhere |
| `sofia` | Sofia Alvarez | Backend Engineer | Slack #engineering |
| `dev` | Dev Patel | Backend Engineer (platform) | Discord #engineering |
| `kenji` | Kenji Watanabe | Frontend Engineer | Discord #design, Slack #engineering |
| `priya` | Priya Nair | Product Designer | Discord #design |
| `liam` | Liam O'Connor | Customer Success | Slack #support-escalations |
| `zara` | Zara Ahmed | QA Engineer | Discord #engineering |

Every PR is opened from the repo owner's real GitHub account. The fictional author goes in the PR body as an `Authored-by: <id>` trailer, which the GitHub connector reads.

## Sprints

| id | Name | Dates |
|---|---|---|
| `s1` | Sprint 1 | 2026-09-14 to 2026-09-25 |
| `s2` | Sprint 2 | 2026-09-28 to 2026-10-09 |

## Features

| id | Feature | Planted outcome |
|---|---|---|
| `feat_export` | Ticket CSV export | **Drift.** On 09-22 a Slack decision widened the scope to any date range up to 12 months plus custom fields. BD-101 was never updated, and PR #6 shipped the old 30-day export. |
| `feat_sla` | SLA breach notifications | **Drift.** On 09-17 a Discord decision changed it to warn 15 minutes *before* breach in the team's Slack channel, with no email. BD-103 still says email at breach, and PR #5 shipped exactly that. |
| `feat_dark` | Dark mode | **Clean control.** The one requirement change (toggle placement) was written back into BD-105 the same day, and PR #12 implements the updated ticket. |

### Traps planted for the extractor
- **Resolved change (feat_export, 09-15):** an "add assignee column" request that *was* copied into BD-101. Flagging it is a false positive.
- **Rejected proposal (feat_export, 09-23):** "should we also do XLSX?" followed by "not this quarter". Not a requirement change.
- **Reaffirmation (feat_dark, 09-29):** "should we drop System?" answered with "no, keep it". No change.
- **PR with no ticket reference:** PR #7 (export button) never mentions BD-102. It has to be linked by author, timing and topic.
- **Cross-platform:** the SLA decision happened on Discord, but the ticket and PR live elsewhere.
- **Stale vs. current docs:** DOC-1 and DOC-2 still describe the old behaviour after the decisions; DOC-3 was updated minutes after its decision and must not be flagged.
