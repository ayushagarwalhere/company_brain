---
id: DOC-6
title: Database Config v2
author: sofia
source: notion
created: 2026-10-05T08:00:00Z
updated: 2026-10-08T09:20:00Z
tickets: BD-116
---
# Database Config v2

Migrated to AWS. The primary Postgres now runs on Amazon RDS (eu-west-1); the old host is read-only until the cutover.
Project managed under ticket BD-116 by Dev.

## Connecting
- Host, port and database name: the `brightdesk-prod` entry in the team vault (never paste credentials into chat).
- Credentials were rotated on 8 Oct as part of the move. Services pick them up from the vault on restart.
- Read replicas: one, for reporting queries and exports.

## Cutover
The final cutover (switching writes to RDS) needs the platform owner on hand. See BD-116 for its status.
