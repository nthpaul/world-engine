"""Local operator routes; no credential or private sealed-state artifact exposure."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from world_engine.browser_contracts import BrowserAttemptConfig, BrowserError, relative_artifact_id
from world_engine.browser_runs import BrowserRunManager
from world_engine.browser_store import attempt_key


def browser_router() -> APIRouter:
    router = APIRouter(prefix="/api/browser")

    def manager(request: Request) -> BrowserRunManager:
        return request.app.state.browser_manager

    @router.get("/tasks")
    async def tasks(request: Request):
        return {"tasks": [task.model_dump() for task in manager(request).tasks.values()]}

    @router.get("/status")
    async def status(request: Request):
        return manager(request).status()

    @router.get("/attempts")
    async def attempts(request: Request, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0, le=100_000)):
        return {"attempts": manager(request).store.list(limit, offset)}

    @router.post("/attempts", status_code=202)
    async def create(config: BrowserAttemptConfig, request: Request):
        try:
            return manager(request).submit(config)
        except BrowserError as error:
            raise HTTPException(409, str(error)) from None

    @router.get("/attempts/{attempt_id}")
    async def detail(attempt_id: str, request: Request):
        try:
            result = manager(request).store.get(attempt_key(attempt_id), detail=True)
        except KeyError:
            raise HTTPException(404, "browser attempt not found") from None
        except BrowserError:
            raise HTTPException(409, "browser evidence integrity check failed") from None
        result["artifacts"] = [{**artifact, "url": f"/api/browser/attempts/{attempt_id}/artifacts/{artifact['id']}"}
                               for artifact in result["artifacts"]]
        return result

    @router.post("/attempts/{attempt_id}/cancel")
    async def cancel(attempt_id: str, request: Request):
        try:
            return await manager(request).cancel(attempt_key(attempt_id))
        except KeyError:
            raise HTTPException(404, "browser attempt not found") from None
        except BrowserError:
            raise HTTPException(409, "browser evidence integrity check failed") from None

    @router.get("/attempts/{attempt_id}/artifacts/{artifact_id:path}")
    async def artifact(attempt_id: str, artifact_id: str, request: Request):
        try:
            relative_artifact_id(artifact_id)
            path, descriptor = manager(request).store.artifact(attempt_key(attempt_id), artifact_id)
        except (KeyError, ValueError):
            raise HTTPException(404, "browser artifact not found") from None
        except BrowserError:
            raise HTTPException(409, "browser artifact integrity check failed") from None
        return FileResponse(path, media_type=descriptor["mime_type"],
                            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    return router
