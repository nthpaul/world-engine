import traceback
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException, Request

from world_engine import make_environment
from world_engine.api import create_app
from world_engine.models import RunConfig
from world_engine.providers import HTTPProvider, ProviderError, make_provider

SENTINEL = "PRIVATE_REMOTE_ENDPOINT_SENTINEL"
REMOTE_KINDS = ["openai", "anthropic"]
INVALID_ENDPOINTS = [
    f"https://[{SENTINEL}]",
    f"https://[{SENTINEL}",
    "https://[::1",
    f"https://[::1]:{SENTINEL}",
    f"https://example.com:{SENTINEL}",
    "https://example.com:0",
    "https://example.com:65536",
    "https://example.com:-1",
    "https://example.com:",
    "https://[::1]:",
    "https://[::1]invalid",
    f"https://example.com:{SENTINEL}\uff0f",
    f"https://example.com/{SENTINEL}\n",
    f"https://example.com/{SENTINEL}\r",
    f"https://example.com/{SENTINEL}\t",
    f"https://example.com/{SENTINEL}\x7f",
    f"https://example.com/{SENTINEL}\u0085",
    f"https://{SENTINEL}:password@example.com/v1",
    f"https://user:{SENTINEL}@example.com/v1",
    "https://@example.com/v1",
    f"https://example.com/v1?key={SENTINEL}",
    f"https://example.com/v1#{SENTINEL}",
    " https://example.com/v1",
    "https://example.com/v1 ",
    "",
    "https:///missing-host",
    "http://example.com/v1",
    f"file:///{SENTINEL}",
]


def remote_config(kind):
    return RunConfig(environment_id="crm-merge", provider_id=kind, allow_paid=True)


def configure(monkeypatch, kind, endpoint):
    monkeypatch.setenv("WORLD_ENGINE_ALLOW_PAID", "1")
    monkeypatch.setenv("OPENAI_API_KEY" if kind == "openai" else "ANTHROPIC_API_KEY", "synthetic-key")
    monkeypatch.setenv("WORLD_ENGINE_OPENAI_URL" if kind == "openai" else "WORLD_ENGINE_ANTHROPIC_URL", endpoint)


def assert_redacted(error):
    assert SENTINEL not in str(error)
    assert SENTINEL not in "".join(traceback.format_exception(error))


class RawBody(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield SENTINEL.encode()


@pytest.mark.parametrize("kind", REMOTE_KINDS)
@pytest.mark.parametrize("endpoint", INVALID_ENDPOINTS)
def test_invalid_remote_endpoint_is_rejected_before_client_creation(monkeypatch, kind, endpoint):
    configure(monkeypatch, kind, endpoint)

    def forbidden(*args, **kwargs):
        pytest.fail("malformed endpoint must not create an HTTP client or contact a provider")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    with pytest.raises(ProviderError) as captured:
        HTTPProvider(remote_config(kind))
    assert_redacted(captured.value)
    assert captured.value.__cause__ is None


@pytest.mark.parametrize("kind", REMOTE_KINDS)
@pytest.mark.parametrize("endpoint", [
    "https://example.com/v1", "https://example.com/base/path/", "https://example.com:1/v1",
    "https://example.com:65535/v1", "https://[::1]:8443/v1", "http://[::1]:8000/base/path",
    "http://127.0.0.1:8000/v1", "http://LOCALHOST:8000/v1", "https://example.com/base%20path/v1",
])
def test_valid_remote_https_and_loopback_base_paths_are_preserved(monkeypatch, kind, endpoint):
    configure(monkeypatch, kind, endpoint)
    provider = HTTPProvider(remote_config(kind))
    assert provider.endpoint == endpoint.rstrip("/")
    assert provider.client is None


@pytest.mark.parametrize("kind", REMOTE_KINDS)
async def test_valid_remote_request_uses_base_path_with_mock_transport_only(monkeypatch, kind):
    configure(monkeypatch, kind, "https://example.com/base/v1/")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(403, stream=RawBody())

    provider = HTTPProvider(remote_config(kind))
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False)
    try:
        with pytest.raises(ProviderError, match="HTTP 403") as captured:
            await provider.decide(make_environment("crm-merge", 42).observe(), [])
        assert_redacted(captured.value)
    finally:
        await provider.close()
    path = "/base/v1/chat/completions" if kind == "openai" else "/base/v1/messages"
    assert len(requests) == 1 and requests[0].url.path == path


@pytest.mark.parametrize("kind", REMOTE_KINDS)
@pytest.mark.parametrize("operator_opt_in,run_opt_in", [(False, True), (True, False), (False, False)])
def test_spend_gate_still_precedes_malformed_endpoint_parsing(monkeypatch, kind, operator_opt_in, run_opt_in):
    configure(monkeypatch, kind, f"https://[{SENTINEL}]")
    monkeypatch.setenv("WORLD_ENGINE_ALLOW_PAID", "1" if operator_opt_in else "0")
    config = remote_config(kind).model_copy(update={"allow_paid": run_opt_in})
    with pytest.raises(ProviderError, match="remote inference disabled") as captured:
        HTTPProvider(config)
    assert_redacted(captured.value)


@pytest.mark.parametrize("kind", REMOTE_KINDS)
@pytest.mark.parametrize("endpoint", [f"https://[{SENTINEL}]", f"https://example.com:{SENTINEL}"])
async def test_api_constructor_boundary_returns_safe_400_without_store_or_jobs(monkeypatch, kind, endpoint):
    configure(monkeypatch, kind, endpoint)
    app = create_app()
    app.state.manager = SimpleNamespace(submit=make_provider)
    request = Request({"type": "http", "app": app})
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/runs" and "POST" in route.methods)
    with pytest.raises(HTTPException) as captured:
        await route.endpoint(remote_config(kind), request)
    assert captured.value.status_code == 400
    assert SENTINEL not in captured.value.detail
    assert_redacted(captured.value)
