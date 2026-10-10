from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from world_engine import __version__
from world_engine.environments import ENVIRONMENTS
from world_engine.exports import ExportFormat, Quality, export_records, jsonl
from world_engine.models import RunConfig
from world_engine.native_config import NativeRunConfig
from world_engine.providers import ProviderError, provider_metadata
from world_engine.rollout import RunManager
from world_engine.store import Store

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}
ALLOWED_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000", "http://127.0.0.1:8000"}


def create_app(db_path: str | Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(db_path or os.environ.get("WORLD_ENGINE_DB", ".world-engine/engine.sqlite3"))
        app.state.manager = RunManager(store)
        yield
        await app.state.manager.close()

    app = FastAPI(title="World Engine", version=__version__, lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def safe_validation_error(request: Request, error: RequestValidationError):
        return JSONResponse({"detail": [{"loc": issue["loc"], "type": issue["type"],
                                         "msg": "request field failed validation"} for issue in error.errors()]}, status_code=422)

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        authority = request.headers.get("host", "")
        try:
            if not authority or not authority.isascii() or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in authority):
                raise ValueError
            parsed = urlparse("http://" + authority)
            host, port = parsed.hostname, parsed.port
            if (host is None or parsed.netloc != authority or parsed.path or parsed.params or parsed.query or parsed.fragment
                    or parsed.username is not None or parsed.password is not None):
                raise ValueError
            host_part = f"[{host}]" if ":" in host else host
            suffix = authority[len(host_part):]
            if (authority[:len(host_part)].lower() != host_part
                    or suffix and (not suffix.startswith(":") or port is None)
                    or port is not None and not 1 <= port <= 65535):
                raise ValueError
        except ValueError:
            return JSONResponse({"detail": "invalid host authority"}, status_code=400)
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "host is not allowed"}, status_code=403)
        origin = request.headers.get("origin")
        if origin is not None and origin not in ALLOWED_ORIGINS:
            return JSONResponse({"detail": "browser origin is not allowed"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "cross-site browser requests are disabled"}, status_code=403)
        length = request.headers.get("content-length")
        if length is not None:
            try:
                too_large = int(length) > 32_768
            except ValueError:
                return JSONResponse({"detail": "invalid content length"}, status_code=400)
            if too_large:
                return JSONResponse({"detail": "request body exceeds 32 KB"}, status_code=413)
        if request.method in ("POST", "PUT", "PATCH"):
            if length is None or request.headers.get("transfer-encoding") is not None:
                return JSONResponse({"detail": "JSON mutations require a bounded Content-Length; chunked uploads are disabled"}, status_code=411)
            body = await request.body()
            if len(body) > 32_768:
                return JSONResponse({"detail": "request body exceeds 32 KB"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    def run_key(run_id: str) -> str:
        try:
            return str(UUID(run_id))
        except ValueError as error:
            raise HTTPException(404, "run not found") from error

    def manager(request: Request) -> RunManager:
        return request.app.state.manager

    @app.get("/api/health")
    async def health(request: Request):
        return {"status": "ok", "version": __version__, "execution": "in-process", "active_runs": len(manager(request).jobs),
                "paid_calls_enabled": os.environ.get("WORLD_ENGINE_ALLOW_PAID") == "1", "max_global_concurrency": 8}

    @app.get("/api/environments")
    async def environments():
        return {"environments": [world.metadata() for world in ENVIRONMENTS.values()]}

    @app.get("/api/providers")
    async def providers():
        return {"providers": await provider_metadata()}

    @app.get("/api/runs")
    async def runs(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100_000)):
        return {"runs": manager(request).store.list_runs(limit, offset)}

    @app.post("/api/runs", status_code=202)
    async def start_run(config: RunConfig | NativeRunConfig, request: Request):
        try:
            return manager(request).submit(config)
        except ProviderError as error:
            raise HTTPException(400, str(error)) from error
        except ValueError as error:
            raise HTTPException(429, str(error)) from error

    @app.get("/api/runs/{run_id}")
    async def run(run_id: str, request: Request):
        try:
            return manager(request).store.get_run(run_key(run_id), detail=True)
        except KeyError as error:
            raise HTTPException(404, "run not found") from error

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel(run_id: str, request: Request):
        try:
            return await manager(request).cancel(run_key(run_id))
        except KeyError as error:
            raise HTTPException(404, "run not found") from error

    @app.get("/api/runs/{run_id}/export")
    async def export(run_id: str, request: Request, format: ExportFormat = "sft", quality: Quality = "passed"):
        try:
            records, report = export_records(manager(request).store, run_key(run_id), format, quality)
        except KeyError as error:
            raise HTTPException(404, "run not found") from error
        return Response(jsonl(records), media_type="application/x-ndjson", headers={
            "Content-Disposition": f'attachment; filename="{run_key(run_id)}-{format}.jsonl"',
            "X-Export-Records": str(report["records"]), "X-Export-Skipped": str(report["skipped"]),
        })

    return app
