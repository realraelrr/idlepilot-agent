from __future__ import annotations

from dataclasses import dataclass
from typing import Any


GOOFISH_IM_URL = "https://www.goofish.com/im"
GOOFISH_ROOT_URL = "https://www.goofish.com/"


@dataclass
class _RemoteDebuggerBrowser:
    debugger_url: str

    def _unsupported(self, operation: str) -> None:
        raise RuntimeError(
            f"{operation} requires an attached browser transport for {self.debugger_url}; "
            "BrowserSessionClient.connect() does not launch Chromium or implement a full CDP client in Task 5."
        )

    def find_target_tab(self) -> None:
        return None

    def refresh_tab(self, tab: Any | None = None) -> None:
        self._unsupported("refresh_tab")

    def open_url(self, url: str) -> None:
        self._unsupported(f"open_url({url})")

    def wait_for_ready_state(self) -> bool:
        self._unsupported("wait_for_ready_state")

    def inspect_page(self) -> dict[str, str]:
        self._unsupported("inspect_page")

    def get_cookies(self) -> list[dict[str, object]]:
        self._unsupported("get_cookies")


class BrowserSessionClient:
    def __init__(self, *, attached_browser: Any):
        self._attached_browser = attached_browser
        self._last_page_state = ""
        self._last_page_snapshot: dict[str, str] = {}

    @classmethod
    def connect(cls, debugger_url: str) -> "BrowserSessionClient":
        normalized_url = str(debugger_url or "").strip()
        if not normalized_url:
            raise ValueError("debugger_url is required")
        return cls(attached_browser=_RemoteDebuggerBrowser(debugger_url=normalized_url))

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
