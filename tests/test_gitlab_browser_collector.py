import importlib.util
from pathlib import Path

import httpx
import pytest


def collector():
    path = Path(__file__).resolve().parents[1] / "scripts/collect_gitlab_browser.py"
    spec = importlib.util.spec_from_file_location("gitlab_collector", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_collector_refuses_existing_output_before_source_or_api(tmp_path, monkeypatch):
    module = collector()
    monkeypatch.setattr(module, "source_identity", lambda: pytest.fail("must refuse before source check"))
    with pytest.raises(FileExistsError):
        module.collect(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "missing")
    with pytest.raises(FileExistsError):
        module.collect(link)


def test_collector_local_request_rejects_redirect_and_oversized_body():
    module = collector()
    for response in (httpx.Response(302, headers={"Location": "https://example.com"}),
                     httpx.Response(200, content=b"too large")):
        with httpx.Client(transport=httpx.MockTransport(lambda request: response), follow_redirects=False) as client:
            with pytest.raises(RuntimeError):
                module.request(client, "GET", "/api/browser/status", limit=2)
    with httpx.Client() as client:
        with pytest.raises(ValueError):
            module.request(client, "GET", "/api/../private")


def test_collector_requires_controller_revision_and_module_hash_match():
    module = collector()
    source = {"git_revision": "a" * 40, "controller_modules": {"driver": "b" * 64}}
    provenance = {"source_git_revision": source["git_revision"], "source_dirty": False,
                  "controller_modules": source["controller_modules"]}
    module.validate_source({"provenance": provenance}, source)
    with pytest.raises(RuntimeError):
        module.validate_source({"provenance": {**provenance, "source_dirty": True}}, source)
    with pytest.raises(RuntimeError):
        module.validate_source({"provenance": {**provenance, "controller_modules": {}}}, source)


def test_collector_preserves_rejected_http_reply_before_raising(tmp_path):
    module = collector()
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(409, content=b"rejected"))) as client:
        with pytest.raises(RuntimeError):
            module.request(client, "POST", "/api/browser/attempts", payload={}, evidence=tmp_path)
    assert (tmp_path / "0000.body").read_bytes() == b"rejected"
