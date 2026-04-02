from __future__ import annotations

import os
from typing import Any

import requests


DEFAULT_TIMEOUT_SECONDS = 10


def _read_required_env(name: str) -> str:
    value = str(os.getenv(name) or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


class BrowserCookieSubmitter:
    def __init__(
        self,
        *,
        submit_url: str,
        shared_secret: str,
        transport: Any = requests,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        self._submit_url = submit_url
        self._shared_secret = shared_secret
        self._transport = transport
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> "BrowserCookieSubmitter":
        return cls(
            submit_url=_read_required_env("BROWSER_REFRESH_SUBMIT_URL"),
            shared_secret=_read_required_env("BROWSER_REFRESH_SHARED_SECRET"),
        )

    def submit(self, cookie: str, episode_id: str):
        response = self._transport.post(
            self._submit_url,
            headers={"Authorization": f"Bearer {self._shared_secret}"},
            json={
                "source": "browser-refresh",
                "cookie": cookie,
                "episode_id": episode_id,
            },
            timeout=self._timeout_seconds,
        )
        raise_for_status = getattr(response, "raise_for_status", None)
        if callable(raise_for_status):
            raise_for_status()
        return response
