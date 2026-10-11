import asyncio
import json
import time

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from world_engine.api import create_app
from world_engine.models import RunConfig
from world_engine.providers import ProviderError, local_endpoint, make_provider


def test_api_lifecycle_downloads_and_browser_boundaries(tmp_path):
    with TestClient(create_app(tmp_path / "engine.sqlite3")) as client:
        assert client.get("/api/health").json()["execution"] == "in-process"
        assert len(client.get("/api/environments").json()["environments"]) == 4
        assert client.get("/api/runs").json() == {"runs": []}
        assert client.post("/api/runs", json={"environment_id": "crm-merge"}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 403
        assert client.post("/api/runs", json={"environment_id": "crm-merge"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert client.post("/api/runs", json={"environment_id": "crm-merge", "reward": 1}).status_code == 422
        secret = "synthetic-secret-sentinel-NEVER-REFLECT"
        invalid = client.post("/api/runs", json={"environment_id": "crm-merge", "api_key": secret})
        assert invalid.status_code == 422 and secret not in invalid.text
        assert client.post("/api/runs", json={"environment_id": "crm-merge", "episodes": 10001}).status_code == 422
        response = client.post("/api/runs", json={"environment_id": "crm-merge", "episodes": 2})
        assert response.status_code == 202
        run_id = response.json()["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            run = client.get(f"/api/runs/{run_id}").json()
            if run["status"] == "completed":
                break
            time.sleep(.01)
        assert run["status"] == "completed" and run["passed_episodes"] == 2
        assert len(run["episodes"]) == 2
        export = client.get(f"/api/runs/{run_id}/export?format=traces")
        assert export.status_code == 200
        assert export.headers["x-export-records"] == "2"
        assert export.headers["content-type"].startswith("application/x-ndjson")
        assert client.get(f"/api/runs/{run_id}/export?format=wrong").status_code == 422
        assert client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "completed"
        assert client.get("/api/runs/not-a-run").status_code == 404
        assert client.get("/api/runs?limit=10000").status_code == 422
        assert client.post("/api/runs", content='{"environment_id":"crm-merge"}', headers={"Transfer-Encoding": "chunked"}).status_code == 411


def test_remote_requires_both_operator_and_per_run_opt_in(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.delenv("WORLD_ENGINE_ALLOW_PAID", raising=False)
    with pytest.raises(ProviderError, match="disabled"):
        make_provider(RunConfig(environment_id="crm-merge", provider_id="openai", allow_paid=True))
    monkeypatch.setenv("WORLD_ENGINE_ALLOW_PAID", "1")
    with pytest.raises(ProviderError, match="disabled"):
        make_provider(RunConfig(environment_id="crm-merge", provider_id="openai", allow_paid=False))
    provider = make_provider(RunConfig(environment_id="crm-merge", provider_id="openai", allow_paid=True))
    assert provider.key == "test-secret"


@pytest.mark.parametrize("endpoint", ["http://example.com", "http://user:password@localhost:11434", "file:///etc/passwd", "http://127.0.0.1:11434?secret=x"])
def test_local_endpoint_cannot_redirect_to_paid_or_credential_urls(monkeypatch, endpoint):
    monkeypatch.setenv("WORLD_ENGINE_LOCAL_URL", endpoint)
    with pytest.raises(ProviderError):
        local_endpoint()


def boundary_request(host):
    app = create_app()
    dispatch = app.user_middleware[0].kwargs["dispatch"]
    request = Request({"type": "http", "method": "GET", "path": "/probe", "scheme": "http",
                       "headers": [(b"host", host.encode("latin-1"))]})
    reached = []

    async def downstream(request):
        reached.append(True)
        return JSONResponse({"downstream": True})

    return asyncio.run(dispatch(request, downstream)), reached


@pytest.mark.parametrize("host", [
    "[", "[::1", "[not-an-ip]", "::1", "[::1]junk", "[::1]evil.example:8000",
    "[::1]:", "[::1]:bad", "[::1]:0", "[::1]:65536", "localhost:", "localhost:bad",
    "localhost:-1", "localhost:0", "localhost:65536", "localhost:80:90",
    "127.0.0.1:bad", "127.0.0.1:0", "testserver:65536",
    "user:API_HOST_SECRET_SENTINEL@localhost", "@localhost", "localhost@evil.example",
    "localhost/path", "localhost/", "localhost?query", "localhost?", "localhost#fragment", "localhost#",
    " localhost", "localhost ", "local\thost", "local\rhost", "local\nhost", "localhost\x00", "localhost\x7f",
    "localhost\x85", "localhost\xa0", "", "http://localhost",
])
def test_malformed_host_authority_is_generic400_before_downstream(host):
    response, reached = boundary_request(host)
    assert response.status_code == 400
    assert reached == []
    assert json.loads(response.body) == {"detail": "invalid host authority"}
    assert "API_HOST_SECRET_SENTINEL" not in response.body.decode()


@pytest.mark.parametrize("host", [
    "127.0.0.1", "127.0.0.1:8000", "127.0.0.1:1", "127.0.0.1:65535", "127.0.0.1:08000",
    "localhost", "LOCALHOST:8000", "localhost:443", "[::1]", "[::1]:8000", "[::1]:65535",
    "testserver", "TESTSERVER:80",
])
def test_valid_loopback_host_authorities_preserve_behavior(host):
    response, reached = boundary_request(host)
    assert response.status_code == 200 and reached == [True]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "127.0.0.2:80", "[::2]:8000", "localhost.:8000", "localhost;parameter"])
def test_well_formed_wrong_host_still403_before_downstream(host):
    response, reached = boundary_request(host)
    assert response.status_code == 403 and reached == []
    assert json.loads(response.body) == {"detail": "host is not allowed"}
