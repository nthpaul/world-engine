from pathlib import Path

import pytest

from world_engine.browser_contracts import BrowserError
from world_engine.browser_driver import BrowserGymDriver, allowed_app_url, app_origin, artifact_descriptor

ORIGIN = "http://127.0.0.1:8929"


@pytest.mark.parametrize("url", [
    "https://example.com", "http://localhost:8929", "http://127.0.0.1:8000/api/browser/attempts",
    "file:///etc/passwd", "javascript:alert(1)", "http://user:secret@127.0.0.1:8929/",
    "http://127.0.0.1:8929/admin", "http://127.0.0.1:8929/api/v4/projects",
    "http://127.0.0.1:8929/%61dmin/users", "http://127.0.0.1:8929/-/metrics",
])
def test_browser_navigation_rejects_other_origins_and_admin_documents(url):
    assert allowed_app_url(url, ORIGIN, document=True) is False


def test_browser_internal_app_requests_are_allowed_but_not_agent_api_navigation():
    url = ORIGIN + "/api/graphql"
    assert allowed_app_url(url, ORIGIN) is True
    assert allowed_app_url(url, ORIGIN, document=True) is False
    assert allowed_app_url(ORIGIN + "/root/release-operations/-/issues/2", ORIGIN, document=True) is True


@pytest.mark.parametrize("path", [
    "/-/user_settings/personal_access_tokens", "/-/user_settings/ssh_keys", "/user_settings/applications", "/-/profile/account",
    "/profile/personal_access_tokens", "/oauth/applications", "/users/edit", "/users/password",
    "/root/release-operations/-/settings/access_tokens", "/root/release-operations/-/settings",
    "/%2d/user_settings/personal_access_tokens", "/%252d/user_settings/personal_access_tokens",
    "/root/../-/user_settings/personal_access_tokens", "/root/%5c../-/user_settings",
    "//-/user_settings/personal_access_tokens", "/-//user_settings/personal_access_tokens",
    "/root/release-operations/-//settings/access_tokens", "/%2f-/user_settings/personal_access_tokens",
    "/-/user_settings;variant/personal_access_tokens",
    "/root/release-operations/-/runners/new", "/groups/release/-/runners/1/register",
    "/root/release-operations/-/issues.atom?feed_token=ephemeral-fixture-value",
    "/root/release-operations/-/issues?%74oken=ephemeral-fixture-value",
])
def test_browser_blocks_credential_documents_and_spa_requests(path):
    assert allowed_app_url(ORIGIN + path, ORIGIN, document=True) is False
    assert allowed_app_url(ORIGIN + path, ORIGIN, document=False) is False


def test_browser_preserves_trusted_login_and_public_work_item_requests():
    assert allowed_app_url(ORIGIN + "/users/sign_in", ORIGIN, document=True)
    assert allowed_app_url(ORIGIN + "/root/release-operations/-/work_items?state=opened", ORIGIN, document=True)
    assert allowed_app_url(ORIGIN + "/root/release-operations/-/issues/2/notes", ORIGIN)
    assert allowed_app_url(ORIGIN + "/profiled", ORIGIN)


@pytest.mark.parametrize("value", ["http://localhost:8929", "http://127.0.0.1:8929/", "http://127.0.0.1:8929/path",
                                     "http://secret@127.0.0.1:8929", "http://127.0.0.1:8929?token=private"])
def test_operator_origin_requires_exact_literal_loopback(value):
    with pytest.raises(BrowserError):
        app_origin(value)


def test_browser_artifact_cannot_follow_symlink_or_escape_root(tmp_path):
    root = tmp_path / "episode"
    root.mkdir()
    outside = tmp_path / "secret"
    outside.write_bytes(b"do not export")
    link = root / "image.png"
    link.symlink_to(outside)
    with pytest.raises(BrowserError):
        artifact_descriptor(root, link, "screenshot", "image/png")
    folder = root / "linked"
    folder.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(BrowserError):
        artifact_descriptor(root, folder / "secret", "screenshot", "image/png")
    image = root / "real.png"
    image.write_bytes(b"known fixture")
    assert artifact_descriptor(root, image, "screenshot", "image/png").id == "real.png"
    assert isinstance(Path(image), Path)


def test_close_flushes_context_video_before_browser_shutdown(tmp_path):
    from types import SimpleNamespace

    events = []
    directory = tmp_path / "video"
    directory.mkdir()

    def flush():
        events.append("context")
        (directory / "recording.webm").write_bytes(b"finalized recording")

    driver = object.__new__(BrowserGymDriver)
    driver.root = tmp_path
    driver.prepared = True
    driver.context = SimpleNamespace(close=flush)
    driver.browser = SimpleNamespace(close=lambda: events.append("browser"))
    driver.playwright = SimpleNamespace(stop=lambda: events.append("playwright"))
    artifacts = driver._close()
    assert events == ["context", "browser", "playwright"]
    assert artifacts[0].size_bytes > 0


def test_empty_recording_is_not_certified_as_closed(tmp_path):
    driver = object.__new__(BrowserGymDriver)
    driver.root = tmp_path
    driver.prepared = True
    with pytest.raises(BrowserError, match="did not finalize"):
        driver._close()


def test_failed_context_closure_still_attempts_browser_and_playwright_cleanup():
    from types import SimpleNamespace

    events = []

    def fail():
        events.append("context")
        raise RuntimeError("failed context closure")

    driver = object.__new__(BrowserGymDriver)
    driver.context = SimpleNamespace(close=fail)
    driver.browser = SimpleNamespace(close=lambda: events.append("browser"))
    driver.playwright = SimpleNamespace(stop=lambda: events.append("playwright"))
    with pytest.raises(RuntimeError, match="failed context closure"):
        driver._close()
    assert events == ["context", "browser", "playwright"]
