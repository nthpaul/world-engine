"""BrowserGym observations and bounded browser actions for a local app instance."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlparse

from world_engine.browser_contracts import (
    MAX_ATTEMPT_BYTES,
    BrowserAction,
    BrowserArtifact,
    BrowserError,
    BrowserObservation,
    RuntimeHandle,
)

BLOCKED_DOCUMENT_PATHS = ("/admin", "/api/", "/-/metrics", "/-/health", "/-/readiness")
MAX_MEDIA_BYTES = 96 * 1024 * 1024


def app_origin(value: str) -> str:
    try:
        parsed = urlparse(value)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port is None
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment
                or value != f"http://127.0.0.1:{parsed.port}" or not 1 <= parsed.port <= 65535):
            raise ValueError
    except ValueError:
        raise BrowserError("browser requires an explicit loopback application origin") from None
    return value


def allowed_app_url(value: str, origin: str, *, document: bool = False) -> bool:
    try:
        parsed = urlparse(value)
        expected = urlparse(origin)
        if (parsed.scheme != expected.scheme or parsed.hostname != expected.hostname
                or parsed.port != expected.port or parsed.username is not None or parsed.password is not None
                or not value.isascii() or any(ord(char) < 32 for char in value)):
            return False
        path = unquote(parsed.path)
        if document and any(path == prefix or path.startswith(prefix.rstrip("/") + "/")
                            for prefix in BLOCKED_DOCUMENT_PATHS):
            return False
        return True
    except ValueError:
        return False


def artifact_descriptor(root: Path, file: Path, kind: str, mime: str) -> BrowserArtifact:
    if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(root.resolve()):
        raise BrowserError("browser artifact is not a regular episode file")
    relative = file.relative_to(root).as_posix()
    data = file.read_bytes()
    if len(data) > MAX_ATTEMPT_BYTES:
        raise BrowserError("browser artifact exceeds its byte budget")
    return BrowserArtifact(id=relative, kind=kind, mime_type=mime, size_bytes=len(data),
                           sha256=hashlib.sha256(data).hexdigest())


class BrowserGymDriver:
    """One thread owns Playwright's synchronous objects for one episode.

    The model receives BrowserGym's AX text and node IDs, never Python code,
    arbitrary selectors, HTTP clients, storage state, or the login password.
    """

    def __init__(self, handle: RuntimeHandle, artifact_root: Path):
        self.handle = handle
        self.root = artifact_root
        self.origin = app_origin(handle.origin)
        if not allowed_app_url(handle.start_url, self.origin, document=True):
            raise BrowserError("browser start URL is outside the application")
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser-episode")
        self.closed = False
        self.prepared = False
        self.index = 0
        self._bids: set[str] = set()
        self.evidence_metadata: dict = {}

    async def _call(self, method, *args):
        if self.closed:
            raise BrowserError("browser capability is closed")
        return await asyncio.get_running_loop().run_in_executor(self.pool, method, *args)

    async def prepare(self) -> None:
        try:
            await self._call(self._prepare)
        except Exception:
            raise BrowserError("browser preparation failed; local browser dependencies and app login required") from None

    def _route(self, route) -> None:
        if allowed_app_url(route.request.url, self.origin, document=route.request.resource_type == "document"):
            route.continue_()
        else:
            route.abort("blockedbyclient")

    def _prepare(self) -> None:
        from playwright.sync_api import sync_playwright

        if self.prepared:
            raise BrowserError("browser already prepared")
        self.playwright = sync_playwright().start()
        self.playwright.selectors.set_test_id_attribute("bid")
        executable = os.environ.get("WORLD_ENGINE_BROWSER_EXECUTABLE_PATH")
        options = {"headless": True, "chromium_sandbox": True,
                   "env": {key: value for key, value in os.environ.items()
                           if key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT")},
                   "args": ["--disable-background-networking", "--disable-sync", "--no-first-run"]}
        if executable:
            options["executable_path"] = str(Path(executable).resolve(strict=True))
        self.browser = self.playwright.chromium.launch(**options)
        self.evidence_metadata = {"browsergym_version": importlib.metadata.version("browsergym-core"),
                                  "playwright_version": importlib.metadata.version("playwright"),
                                  "browser_version": self.browser.version,
                                  "observation_mode": "AX", "image_not_sent_to_model": True,
                                  "network_scope": "episode application origin only",
                                  "browser_location": "local host browser; development-only isolation"}
        if executable:
            self.evidence_metadata["browser_executable_sha256"] = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
        login = self.browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=False,
                                         service_workers="block")
        login.route("**/*", self._route)
        page = login.new_page()
        page.set_default_timeout(5000)
        page.goto(self.origin + "/users/sign_in", wait_until="domcontentloaded", timeout=30_000)
        page.locator("#user_login").fill(self.handle.agent_credentials.username)
        page.locator("#user_password").fill(self.handle.agent_credentials.password.get_secret_value())
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_url(lambda url: "/users/sign_in" not in url, timeout=30_000)
        # Transfer cookies in memory. Recording starts only after authentication.
        cookies = login.cookies()
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000},
                                               accept_downloads=False, service_workers="block",
                                               record_video_dir=str(self.root / "video"),
                                               record_video_size={"width": 1440, "height": 1000})
        self.context.route("**/*", self._route)
        self.context.add_cookies(cookies)
        login.close()
        self.page = self.context.new_page()
        self.page.set_default_timeout(5000)
        self.page.on("popup", lambda popup: popup.close())
        self.page.goto(self.handle.start_url, wait_until="domcontentloaded", timeout=30_000)
        self.page.wait_for_timeout(300)
        self.prepared = True

    async def observe(self) -> BrowserObservation:
        try:
            return await self._call(self._observe)
        except Exception:
            raise BrowserError("browser observation failed") from None

    def _observe(self) -> BrowserObservation:
        from browsergym.core.observation import (
            _post_extract,
            _pre_extract,
            extract_dom_extra_properties,
            extract_dom_snapshot,
            extract_merged_axtree,
        )
        from browsergym.utils.obs import flatten_axtree_to_str

        if not self.prepared or not allowed_app_url(self.page.url, self.origin, document=True):
            raise BrowserError("browser is not on an allowed application page")
        _pre_extract(self.page)
        try:
            ax = extract_merged_axtree(self.page)
            properties = extract_dom_extra_properties(extract_dom_snapshot(self.page), scale_factor=1)
            text = flatten_axtree_to_str(ax, extra_properties=properties, with_visible=True,
                                        filter_visible_only=True, hide_bid_if_invisible=True)
        finally:
            _post_extract(self.page)
        if len(text) > 65_536:
            raise BrowserError("browser accessibility observation exceeds its bound")
        self._bids = set(re.findall(r"\[([a-zA-Z0-9_-]+)\]", text))
        directory = self.root / "screenshots"
        directory.mkdir(exist_ok=True)
        file = directory / f"{self.index:04d}.png"
        self.index += 1
        if file.exists() or file.is_symlink():
            raise BrowserError("refusing to overwrite a browser screenshot")
        self.page.screenshot(path=str(file), full_page=False, timeout=5000)
        self._check_budget()
        return BrowserObservation(url=self.page.url, title=self.page.title(), accessibility_text=text,
                                  screenshot_artifact_id=file.relative_to(self.root).as_posix())

    def _check_budget(self) -> None:
        size = sum(file.stat().st_size for directory in ("screenshots", "video")
                   for file in (self.root / directory).glob("*") if file.is_file())
        if size > MAX_MEDIA_BYTES:
            raise BrowserError("browser recording exceeded the episode artifact budget")

    async def execute(self, action: BrowserAction) -> dict:
        try:
            return await self._call(self._execute, action)
        except BrowserError:
            raise
        except Exception:
            # Third-party exception text can contain URL parameters or typed input.
            return {"ok": False, "error": "browser_action_failed", "uncertain_effect": True}

    def _execute(self, action: BrowserAction) -> dict:
        from browsergym.core.action.utils import get_elem_by_bid

        if not self.prepared:
            raise BrowserError("browser is not prepared")
        if action.kind in ("click", "fill", "press"):
            if action.bid not in self._bids:
                return {"ok": False, "error": "node_not_in_current_observation", "uncertain_effect": False}
            element = get_elem_by_bid(self.page, action.bid)
            if not element.is_visible():
                return {"ok": False, "error": "node_not_visible", "uncertain_effect": False}
            if action.kind == "click":
                element.click(timeout=5000)
            elif action.kind == "fill":
                if element.get_attribute("type") == "password":
                    return {"ok": False, "error": "password_input_not_available", "uncertain_effect": False}
                element.fill(action.text, timeout=5000)
            else:
                element.press(action.key, timeout=5000)
        elif action.kind == "navigate":
            if not allowed_app_url(action.url, self.origin, document=True):
                return {"ok": False, "error": "navigation_outside_application", "uncertain_effect": False}
            self.page.goto(action.url, wait_until="domcontentloaded", timeout=10_000)
        elif action.kind == "scroll":
            delta = {"up": (0, -700), "down": (0, 700), "left": (-700, 0), "right": (700, 0)}[action.direction]
            self.page.mouse.wheel(*delta)
        elif action.kind == "wait":
            self.page.wait_for_timeout(action.seconds * 1000)
        elif action.kind == "finish":
            return {"ok": True, "finished": True}
        else:
            raise BrowserError("unsupported browser action")
        self.page.wait_for_timeout(300)
        return {"ok": True}

    async def close(self) -> list[BrowserArtifact]:
        if self.closed:
            return []
        try:
            return await self._call(self._close)
        finally:
            self.closed = True
            await asyncio.to_thread(self.pool.shutdown, wait=True, cancel_futures=True)

    def _close(self) -> list[BrowserArtifact]:
        try:
            # Playwright flushes recordings when their context closes, before browser shutdown.
            if hasattr(self, "context"):
                self.context.close()
            if hasattr(self, "browser"):
                self.browser.close()
        finally:
            if hasattr(self, "playwright"):
                self.playwright.stop()
        self._check_budget()
        files = [(file, "screenshot", "image/png") for file in sorted((self.root / "screenshots").glob("*.png"))]
        files.extend((file, "video", "video/webm") for file in sorted((self.root / "video").glob("*.webm")))
        if self.prepared and not any(kind == "video" and file.stat().st_size > 0 for file, kind, _ in files):
            raise BrowserError("browser recording did not finalize")
        return [artifact_descriptor(self.root, file, kind, mime) for file, kind, mime in files]
