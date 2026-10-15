---
id: DOC-2
title: Design note — SLA breach notifications
author: dev
created: 2026-09-14T09:00:00Z
updated: 2026-09-14T09:00:00Z
tickets: BD-103, BD-104
---
# SLA breach notifications

A periodic job scans open tickets every minute. When `now >= sla_deadline` and the ticket hasn't been
notified yet, it **sends an email to the assignee** using the existing mailer and marks the ticket.

SLA hours per priority come from the settings page (BD-104).
