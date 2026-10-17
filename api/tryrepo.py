"""Try it on your own repo (pipeline/tryrepo.py): paste a public GitHub repo, get its graph.

POST /api/try {repo}            start a build (or get the cached result at once)
GET  /api/try/status?repo=...   poll a build; the result when it's ready
GET  /api/try/recent            repos with a fresh result, for one-click examples
"""

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from pipeline import tryrepo

router = APIRouter()


class TryBody(BaseModel):
    repo: str


@router.post("/api/try")
async def try_repo(body: TryBody):
    try:
        return await run_in_threadpool(tryrepo.request, body.repo)
    except tryrepo.TryError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/api/try/status")
async def try_status(repo: str):
    try:
        return await run_in_threadpool(tryrepo.status, repo)
    except tryrepo.TryError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/api/try/recent")
async def try_recent():
    return {"repos": await run_in_threadpool(tryrepo.recent)}
