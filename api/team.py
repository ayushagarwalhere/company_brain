"""A connected team's own setup, on its dashboard (?app&org=slack-... / discord-...): what's connected, its GitHub
repo, a sync on demand, and Who's who (people, roles, groups, the accounts behind each, merging two people).

Every route works only on a connected team's org (the X-Org of the request), never on the demo company. With no sign-in
yet, the org id in the dashboard link is the key, so it is shown only to that team (in the bot's welcome message).
"""

import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.integrations import _auth
from connectors import installs

router = APIRouter()


def team_org() -> str:
    from graph.db import current_org

    org = current_org()
    if not installs.is_team_org(org):
        raise HTTPException(403, "only a connected team's dashboard has a setup page")
    return org


@router.get("/api/team")
def team_status(org: str = Depends(team_org)):
    """What this team has connected and the last sync's result. No tokens."""
    from graph.db import get_graph

    out = installs.public_team(org)
    try:
        out["people"] = get_graph().ro_query("MATCH (p:Person) RETURN count(p)").result_set[0][0]
    except Exception:  # noqa: BLE001 - the graph doesn't exist until the first message or sync
        out["people"] = 0
    return out


class GithubIn(BaseModel):
    repo: str
    token: str = ""


@router.post("/api/team/github", dependencies=[Depends(_auth)])
def connect_github(body: GithubIn, org: str = Depends(team_org)):
    """Saves the team's GitHub repo (and a read-only token for a private repo), then starts the first full sync."""
    from connectors import github_work
    from pipeline import teamsync

    token = body.token.strip() or (installs.team(org).get("github") or {}).get("token")
    try:
        info = github_work.check_repo(body.repo.strip(), token)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"GitHub didn't let us read {body.repo}: {str(e)[:160]}") from e
    installs.set_team(org, github={"repo": info["repo"], "token": token, "since": None})
    teamsync.in_background(teamsync.sync_team, org, True)
    return {"repo": info["repo"], "private": info["private"], "syncing": True}


class JiraIn(BaseModel):
    site: str
    email: str
    token: str = ""
    project: str


@router.post("/api/team/jira", dependencies=[Depends(_auth)])
def connect_jira(body: JiraIn, org: str = Depends(team_org)):
    """Saves the team's Jira Cloud project (site, account email, API token), then starts the first full sync."""
    from connectors import jira
    from pipeline import teamsync

    token = body.token.strip() or (installs.team(org).get("jira") or {}).get("token")
    if not token:
        raise HTTPException(400, "an API token is needed (id.atlassian.com > Security > API tokens)")
    try:
        info = jira.check_project(body.site, body.email.strip(), token, body.project)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Jira didn't let us read {body.project.upper()}: {str(e)[:160]}") from e
    installs.set_team(org, jira={"site": info["site"], "email": body.email.strip(), "token": token, "project": info["project"], "since": None})
    teamsync.in_background(teamsync.sync_team, org, True)
    return {"project": info["project"], "name": info["name"], "syncing": True}


class LinearIn(BaseModel):
    token: str = ""
    team: str


@router.post("/api/team/linear", dependencies=[Depends(_auth)])
def connect_linear(body: LinearIn, org: str = Depends(team_org)):
    """Saves the team's Linear team (API key, team key), then starts the first full sync."""
    from connectors import linear
    from pipeline import teamsync

    token = body.token.strip() or (installs.team(org).get("linear") or {}).get("token")
    if not token:
        raise HTTPException(400, "an API key is needed (Linear > Settings > Security & access > API keys)")
    try:
        info = linear.check_team(token, body.team)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Linear didn't let us read team {body.team.upper()}: {str(e)[:160]}") from e
    installs.set_team(org, linear={"token": token, "team": info["team"], "since": None})
    teamsync.in_background(teamsync.sync_team, org, True)
    return {"team": info["team"], "name": info["name"], "syncing": True}


@router.post("/api/team/sync", dependencies=[Depends(_auth)])
def sync_now(org: str = Depends(team_org)):
    """A pass now instead of at the next interval (people, GitHub, re-resolve)."""
    from pipeline import teamsync

    teamsync.in_background(teamsync.sync_team, org)
    return {"syncing": True}


@router.get("/api/team/people")
def people(org: str = Depends(team_org)):
    """Who's who: every person, their role and groups, and each account linked to them (and how it was linked)."""
    from graph.db import get_graph
    from pipeline import identity

    try:
        return identity.directory(get_graph())
    except Exception:  # noqa: BLE001 - no graph yet
        return []


class MergeIn(BaseModel):
    keep: str
    drop: str


_merge_lock = threading.Lock()


@router.post("/api/team/people/merge", dependencies=[Depends(_auth)])
def merge_people(body: MergeIn, org: str = Depends(team_org)):
    """Two entries that are one human: everything of `drop` (messages, tickets, accounts) moves to `keep`."""
    from graph.db import get_graph
    from pipeline import identity
    from pipeline.live import mark_dirty

    with _merge_lock:
        try:
            out = identity.merge(get_graph(), body.keep, body.drop)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    mark_dirty(get_graph())  # ticket ownership may have changed: re-derive at the next pass
    return out


class PersonIn(BaseModel):
    role: str | None = None
    groups: list[str] | None = None


@router.post("/api/team/people/{pid}", dependencies=[Depends(_auth)])
def edit_person(pid: str, body: PersonIn, org: str = Depends(team_org)):
    """A role or groups set by hand (kept over what Slack or Discord say later)."""
    from graph.db import get_graph
    from pipeline import identity

    identity.set_person(get_graph(), pid, body.role, body.groups)
    return {"id": pid, "role": body.role, "groups": body.groups}
