from __future__ import annotations

import itertools
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect as open_websocket

from browser_refresh.cookie_bundle import RUNTIME_TARGET_URLS


GOOFISH_IM_URL = "https://www.goofish.com/im"
GOOFISH_ROOT_URL = "https://www.goofish.com/"
CDP_TIMEOUT_SECONDS = 10
CDP_READY_POLL_INTERVAL_SECONDS = 0.25
CDP_INSPECT_EXPRESSION = """(() => ({
    url: window.location.href,
    title: document.title,
    html: document.documentElement ? document.documentElement.outerHTML : ""
}))()"""
BROWSER_CLIENT_RECOVERABLE_EXCEPTIONS = (
    RuntimeError,
    requests.RequestException,
    OSError,
    WebSocketException,
)


@dataclass
class _CdpAttachedBrowser:
    debugger_url: str
    http_client: Any
    websocket_factory: Any
    timeout_seconds: float = CDP_TIMEOUT_SECONDS
    _current_tab: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self._message_ids = itertools.count(1)

    def _url_for(self, path: str) -> str:
        return f"{self.debugger_url.rstrip('/')}/{path.lstrip('/')}"

    def _get_json(self, path: str) -> Any:
        response = self.http_client.get(self._url_for(path), timeout=self.timeout_seconds)
        raise_for_status = getattr(response, "raise_for_status", None)
        if callable(raise_for_status):
            raise_for_status()
        return response.json()

    def _put_json(self, path: str) -> Any:
        response = self.http_client.put(self._url_for(path), timeout=self.timeout_seconds)
        raise_for_status = getattr(response, "raise_for_status", None)
        if callable(raise_for_status):
            raise_for_status()
        return response.json()

    @staticmethod
    def _is_goofish_tab(tab: dict[str, Any]) -> bool:
        if str(tab.get("type") or "").strip() != "page":
            return False
        return "goofish.com" in str(tab.get("url") or "").lower()

    def _ensure_tab(self, tab: dict[str, Any] | None = None) -> dict[str, Any]:
        resolved = tab or self._current_tab or self.find_target_tab()
        if resolved is None:
            raise RuntimeError("no attached goofish page is available in the remote debugger session")
        return resolved

    def _send_cdp_command(self, tab: dict[str, Any], method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        websocket_url = str(tab.get("webSocketDebuggerUrl") or "").strip()
        if not websocket_url:
            raise RuntimeError(f"tab {tab.get('id', '<unknown>')} is missing webSocketDebuggerUrl")

        message_id = next(self._message_ids)
        websocket = self.websocket_factory(websocket_url)
        try:
            websocket.send(
                json.dumps(
                    {
                        "id": message_id,
                        "method": method,
                        "params": params or {},
                    }
                )
            )
            deadline = time.monotonic() + self.timeout_seconds
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(f"timed out waiting for CDP response to {method}")
                try:
                    payload = json.loads(websocket.recv(timeout=remaining))
                except TimeoutError as exc:
                    raise RuntimeError(f"timed out waiting for CDP response to {method}") from exc
                if payload.get("id") != message_id:
                    continue
                if payload.get("error"):
                    raise RuntimeError(f"CDP {method} failed: {payload['error']}")
                return payload.get("result") or {}
        finally:
            close = getattr(websocket, "close", None)
            if callable(close):
                close()

    def find_target_tab(self) -> dict[str, Any] | None:
        for tab in self._get_json("/json/list") or []:
            if self._is_goofish_tab(tab):
                self._current_tab = tab
                return tab
        return None

    def refresh_tab(self, tab: Any | None = None) -> None:
        resolved_tab = self._ensure_tab(tab)
        self._send_cdp_command(resolved_tab, "Page.reload", {"ignoreCache": True})
        self._current_tab = resolved_tab

    def open_url(self, url: str) -> None:
        encoded_url = quote(url, safe=":/?=&")
        new_tab = self._put_json(f"/json/new?{encoded_url}")
        if isinstance(new_tab, dict):
            self._current_tab = new_tab

    def wait_for_ready_state(self) -> bool:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            tab = self._ensure_tab()
            result = self._send_cdp_command(
                tab,
                "Runtime.evaluate",
                {
                    "expression": "document.readyState",
                    "returnByValue": True,
                },
            )
            ready_state = str((result.get("result") or {}).get("value") or "").strip().lower()
            if ready_state == "complete":
                return True
            time.sleep(CDP_READY_POLL_INTERVAL_SECONDS)
        return False

    def inspect_page(self) -> dict[str, str]:
        tab = self._ensure_tab()
        result = self._send_cdp_command(
            tab,
            "Runtime.evaluate",
            {
                "expression": CDP_INSPECT_EXPRESSION,
                "returnByValue": True,
            },
        )
        value = (result.get("result") or {}).get("value") or {}
        return {
            "url": str(value.get("url") or ""),
            "title": str(value.get("title") or ""),
            "html": str(value.get("html") or ""),
        }

    def get_cookies(self) -> list[dict[str, object]]:
        tab = self._ensure_tab()
        result = self._send_cdp_command(
            tab,
            "Network.getCookies",
            {"urls": list(RUNTIME_TARGET_URLS)},
        )
        cookies = result.get("cookies") or []
        return list(cookies) if isinstance(cookies, list) else []


class BrowserSessionClient:
    def __init__(self, *, attached_browser: Any):
        self._attached_browser = attached_browser
        self._last_page_state = ""
        self._last_page_snapshot: dict[str, str] = {}

    @classmethod
    def connect(
        cls,
        debugger_url: str,
        *,
        http_client: Any | None = None,
        websocket_factory: Any | None = None,
    ) -> "BrowserSessionClient":
        normalized_url = str(debugger_url or "").strip()
        if not normalized_url:
            raise ValueError("debugger_url is required")
        return cls(
            attached_browser=_CdpAttachedBrowser(
                debugger_url=normalized_url,
                http_client=http_client or requests,
                websocket_factory=websocket_factory or open_websocket,
            )
        )

    @property
    def last_page_snapshot(self) -> dict[str, str]:
        return dict(self._last_page_snapshot)

    def prepare_target_page(self) -> None:
        target_tab = self._attached_browser.find_target_tab()
        if target_tab is not None:
            self._attached_browser.refresh_tab(target_tab)
            return

        for url in (GOOFISH_IM_URL, GOOFISH_ROOT_URL):
            self._attached_browser.open_url(url)
            if self._attached_browser.wait_for_ready_state():
                return

    def classify_page_state(self) -> str:
        snapshot = self._attached_browser.inspect_page() or {}
        self._last_page_snapshot = {
            "url": str(snapshot.get("url") or ""),
            "title": str(snapshot.get("title") or ""),
            "html": str(snapshot.get("html") or ""),
        }
        haystack = " ".join(self._last_page_snapshot.values()).lower()
        url = self._last_page_snapshot["url"].lower()

        if any(marker in haystack for marker in ("滑块", "验证", "challenge", "captcha")):
            self._last_page_state = "needs_human_verification"
            return self._last_page_state

        if any(marker in haystack for marker in ("登录", "login", "扫码登录", "signin")):
            self._last_page_state = "needs_login"
            return self._last_page_state

        if "goofish.com" in url and not any(
            marker in haystack for marker in ("502", "bad gateway", "error", "upstream")
        ):
            self._last_page_state = "ready"
            return self._last_page_state

        self._last_page_state = "unknown_error"
        return self._last_page_state

    def get_cookies(self) -> list[dict[str, object]]:
        if self._last_page_state != "ready":
            raise RuntimeError("browser cookies are only available after the page is classified as ready")
        return list(self._attached_browser.get_cookies())
