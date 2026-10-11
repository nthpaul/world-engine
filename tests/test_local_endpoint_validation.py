import traceback

import httpx
import pytest

from world_engine.models import RunConfig
from world_engine.ollama_tools import OllamaToolsProvider
from world_engine.providers import HTTPProvider, ProviderError, local_endpoint, provider_metadata

SENTINEL = "PRIVATE_INVALID_ENDPOINT_SENTINEL"
INVALID_ENDPOINTS = [
    f"http://127.0.0.1:{SENTINEL}",
    f"http://[::1]:{SENTINEL}",
    "http://127.0.0.1:0",
    "http://localhost:65536",
    "http://localhost:-1",
    "http://localhost:",
    "http://[::1]:",
    f"http://[{SENTINEL}",
    f"http://localhost:{SENTINEL}\uff0f",
    f"http://localhost/{SENTINEL}\n",
    f"http://localhost/{SENTINEL}\r",
    f"http://localhost/{SENTINEL}\t",
    f"http://localhost/{SENTINEL}\x7f",
    f"http://localhost/{SENTINEL}\u0085",
    " http://localhost",
    "http://localhost ",
    "",
]


def assert_redacted(error):
    assert SENTINEL not in str(error)
    assert SENTINEL not in "".join(traceback.format_exception(error))
    assert error.__cause__ is None


@pytest.mark.parametrize("endpoint", INVALID_ENDPOINTS)
@pytest.mark.parametrize("provider_class", [HTTPProvider, OllamaToolsProvider])
def test_invalid_local_endpoint_is_redacted_before_client_creation(monkeypatch, endpoint, provider_class):
    monkeypatch.setenv("WORLD_ENGINE_LOCAL_URL", endpoint)

    def forbidden(*args, **kwargs):
        pytest.fail("invalid endpoint must be rejected before HTTPX construction or contact")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    with pytest.raises(ProviderError) as captured:
        provider_class(RunConfig(environment_id="crm-merge", provider_id="local"))
    assert_redacted(captured.value)


@pytest.mark.parametrize("endpoint,expected", [
    ("http://localhost", "http://localhost"),
    ("https://localhost/", "https://localhost"),
    ("http://127.0.0.1:1/base/path/", "http://127.0.0.1:1/base/path"),
    ("https://127.0.0.1:65535/base/path", "https://127.0.0.1:65535/base/path"),
    ("http://[::1]", "http://[::1]"),
    ("https://[::1]:8000/base/path/", "https://[::1]:8000/base/path"),
    ("http://LOCALHOST:11434/base/path", "http://LOCALHOST:11434/base/path"),
])
def test_valid_local_origins_ports_and_base_paths_are_preserved(monkeypatch, endpoint, expected):
    monkeypatch.setenv("WORLD_ENGINE_LOCAL_URL", endpoint)
    assert local_endpoint() == expected
    for provider_class in (HTTPProvider, OllamaToolsProvider):
        assert provider_class(RunConfig(environment_id="crm-merge", provider_id="local")).endpoint == expected


def test_default_local_endpoint_without_configuration_is_preserved(monkeypatch):
    monkeypatch.delenv("WORLD_ENGINE_LOCAL_URL", raising=False)
    assert local_endpoint() == "http://127.0.0.1:11434"


@pytest.mark.parametrize("endpoint", INVALID_ENDPOINTS)
async def test_catalog_marks_invalid_local_configuration_unavailable_without_contact(monkeypatch, endpoint):
    monkeypatch.setenv("WORLD_ENGINE_LOCAL_URL", endpoint)
    contacts = []

    def respond(request):
        contacts.append(request)
        pytest.fail("invalid local configuration must never contact a provider")

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: client)
    result = await provider_metadata()
    local = next(row for row in result if row["id"] == "local")
    assert local["configured"] is False and local["models"] == []
    assert contacts == [] and client.is_closed
