import asyncio
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest


def example():
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples" / "gitlab_browser.py"))


@pytest.mark.parametrize("symlink", [False, True])
def test_gitlab_sdk_refuses_existing_evidence_before_runtime_or_model(tmp_path, symlink):
    namespace = example()
    path = tmp_path / "evidence"
    if symlink:
        path.symlink_to(tmp_path / "absent")
    else:
        path.mkdir()
    with pytest.raises(FileExistsError, match="refusing"):
        asyncio.run(namespace["collect"](SimpleNamespace(output=path)))


def test_gitlab_sdk_plan_has_no_docker_or_model_calls(tmp_path, monkeypatch):
    namespace = example()

    def forbidden(*args, **kwargs):
        raise AssertionError("plan must not create resources")

    monkeypatch.setitem(namespace["collect"].__globals__, "BrowserRunManager", forbidden)
    args = SimpleNamespace(output=tmp_path / "fresh", provider="local-browser", model="qwen3:8b",
                           seed=42, max_steps=30, timeout=600, plan=True)
    result = asyncio.run(namespace["collect"](args))
    assert result["paid_resources"] is False
    assert result["automatic_retries"] == 0
    assert not args.output.exists()
