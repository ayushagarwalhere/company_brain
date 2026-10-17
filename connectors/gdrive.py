"""Google Drive / Google Docs sync: keeps Document nodes, their chunks + embeddings and their access lists current.

    python -m connectors.gdrive sync        # one pass over Drive's change feed (run on a schedule, or from the webhook)

How it stays current
  * Drive's change feed (changes.list) is read from a saved page token, stored in the graph as
    (:SyncState {id: 'gdrive'}). Each pass sees only what changed since the last one.
  * For every changed Google Doc: export the text (files.export, text/plain), read its sharing (permissions.list),
    then pipeline.webhooks.doc_updated(), which re-embeds only the changed chunks and recomputes the doc's MENTIONS
    edges and stale-doc flags. A new doc is created first; a trashed or removed doc is deleted with its chunks.
  * Push: Drive can call POST /api/ingest/gdrive when anything changes (a "changes.watch" channel). The notification
    carries no content, so the endpoint just runs a sync pass.

Access control from Drive sharing (pipeline/access.py): shared with the domain or anyone with the link = no ACL
(everyone in the company); otherwise the ACL lists "email:<address>" per user or group it is shared with. A person's
grants include "email:<their address>" when people.json gives one.

Auth: GOOGLE_ACCESS_TOKEN (an OAuth access token with drive.readonly, e.g. from a service account). Tested against a
fake Drive API (tests/test_knowledge.py); not yet run against a real Drive.
"""

import os
import sys

import requests

API = "https://www.googleapis.com/drive/v3"
DOC_MIME = "application/vnd.google-apps.document"


def _get(path: str, **params):
    token = os.getenv("GOOGLE_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("GOOGLE_ACCESS_TOKEN not set")
    r = requests.get(f"{API}{path}", params=params, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    return r.json() if "json" in r.headers.get("content-type", "json") else r.text


def doc_id(file_id: str) -> str:
    return f"gdoc:{file_id}"


def acl_from_permissions(perms: list[dict]) -> list[str]:
    """[] (everyone) if shared with the domain or anyone; else one "email:<address>" per user/group."""
    if any(p.get("type") in ("domain", "anyone") for p in perms):
        return []
    return sorted({f"email:{p['emailAddress'].lower()}" for p in perms if p.get("emailAddress")})


def _person_for(g, email: str | None) -> str:
    if email:
        rows = g.ro_query("MATCH (p:Person) WHERE toLower(p.email) = $e RETURN p.id", {"e": email.lower()}).result_set
        if rows:
            return rows[0][0]
    return "unknown"


def sync(g) -> dict:
    """One pass over the change feed. Returns what changed."""
    from graph.writer import write_documents
    from pipeline.events import Event, find_ticket_refs
    from pipeline.webhooks import doc_updated

    state = g.query("MATCH (s:SyncState {id: 'gdrive'}) RETURN s.page_token").result_set
    token = state[0][0] if state else _get("/changes/startPageToken")["startPageToken"]
    created, updated, removed = [], [], []
    while True:
        page = _get(
            "/changes",
            pageToken=token,
            fields="nextPageToken,newStartPageToken,changes(fileId,removed,file(id,name,mimeType,modifiedTime,trashed,owners(emailAddress)))",
        )
        for ch in page.get("changes", []):
            f, did = ch.get("file") or {}, doc_id(ch["fileId"])
            if ch.get("removed") or f.get("trashed"):
                g.query("MATCH (d:Document {id: $id}) OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:Chunk) DETACH DELETE d, c", {"id": did})
                removed.append(did)
                continue
            if f.get("mimeType") != DOC_MIME:
                continue
            text = _get(f"/files/{f['id']}/export", mimeType="text/plain")
            acl = acl_from_permissions(_get(f"/files/{f['id']}/permissions", fields="permissions(type,emailAddress,domain,role)").get("permissions", []))
            author = _person_for(g, (f.get("owners") or [{}])[0].get("emailAddress"))
            if not g.query("MATCH (d:Document {id: $id}) RETURN 1", {"id": did}).result_set:
                write_documents(
                    g,
                    [
                        Event(
                            source="gdrive",
                            kind="document",
                            id=did,
                            author=author,
                            ts=f["modifiedTime"],
                            text=text,
                            url=f"https://docs.google.com/document/d/{f['id']}",
                            extra={"title": f["name"], "updated": f["modifiedTime"], "tickets": find_ticket_refs(text), "acl": acl},
                        )
                    ],
                )
                created.append(did)
            doc_updated(g, did, text, actor=author, title=f["name"], at=f["modifiedTime"], acl=acl)
            updated.append(did)
        if "nextPageToken" in page:
            token = page["nextPageToken"]
            continue
        token = page.get("newStartPageToken", token)
        break
    g.query("MERGE (s:SyncState {id: 'gdrive'}) SET s.page_token = $t", {"t": token})
    return {"created": created, "updated": updated, "removed": removed, "page_token": token}


if __name__ == "__main__":
    from graph.db import get_graph

    if sys.argv[1:] != ["sync"]:
        raise SystemExit("usage: python -m connectors.gdrive sync")
    print(sync(get_graph()))
