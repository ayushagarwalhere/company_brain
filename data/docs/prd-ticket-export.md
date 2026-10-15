---
id: DOC-1
title: PRD — Ticket export
author: maya
created: 2026-09-12T06:00:00Z
updated: 2026-09-15T10:40:00Z
tickets: BD-101, BD-102
---
# Ticket export

## Problem
Admins can't get their ticket data out of Brightdesk for reporting.

## Requirements
- Admins can download tickets created in the **last 30 days** as a CSV file.
- Columns: id, subject, status, created_at, assignee (assignee added 2026-09-15 after Acme feedback).
- An "Export" button in the ticket list toolbar triggers the download (admin only).

## Out of scope
XLSX, scheduled exports.
