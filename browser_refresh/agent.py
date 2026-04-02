from __future__ import annotations

import logging
from hashlib import sha256

import requests

from browser_refresh.browser_client import BROWSER_CLIENT_RECOVERABLE_EXCEPTIONS, BrowserClientNoTargetError
from browser_refresh.cookie_bundle import build_runtime_cookie_bundle


class BrowserRefreshRecoverableError(RuntimeError):
    pass


class BrowserRefreshAgent:
    def __init__(self, *, status_reader, browser_client, submitter, logger=None):
        self._status_reader = status_reader
        self._browser_client = browser_client
        self._submitter = submitter
        self._submitted_fingerprints_by_episode: dict[str, set[str]] = {}
        self._prepared_episode_id = ""
        self._logger = logger or logging.getLogger(__name__)

    def _transition_episode(self, episode_id: str) -> None:
        self._prepared_episode_id = episode_id
        existing = self._submitted_fingerprints_by_episode.get(episode_id, set())
        self._submitted_fingerprints_by_episode = {episode_id: existing}

    @staticmethod
    def _wrap_browser_client_error(step: str, exc: Exception) -> BrowserRefreshRecoverableError:
        return BrowserRefreshRecoverableError(f"browser client {step} failed: {exc}")

    def _handle_browser_client_error(self, step: str, exc: Exception) -> BrowserRefreshRecoverableError:
        if isinstance(exc, BrowserClientNoTargetError):
            self._prepared_episode_id = ""
        return self._wrap_browser_client_error(step, exc)

    @staticmethod
    def _wrap_submit_error(exc: requests.RequestException) -> BrowserRefreshRecoverableError:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code is not None:
            return BrowserRefreshRecoverableError(f"submit failed with status {status_code}: {exc}")
        return BrowserRefreshRecoverableError(f"submit failed: {exc}")

    def run_once(self) -> None:
        runtime_state = self._status_reader()
        if not runtime_state.is_recovery_active:
            self._prepared_episode_id = ""
            return

        if runtime_state.episode_id != self._prepared_episode_id:
            try:
                self._browser_client.prepare_target_page()
            except BROWSER_CLIENT_RECOVERABLE_EXCEPTIONS as exc:
                raise self._handle_browser_client_error("prepare_target_page", exc) from exc
            self._transition_episode(runtime_state.episode_id)
        try:
            page_state = self._browser_client.classify_page_state()
        except BROWSER_CLIENT_RECOVERABLE_EXCEPTIONS as exc:
            raise self._handle_browser_client_error("classify_page_state", exc) from exc
        if page_state != "ready":
            if page_state == "unknown_error":
                self._logger.info(
                    "browser refresh page state: %s snapshot=%s",
                    page_state,
                    getattr(self._browser_client, "last_page_snapshot", {}),
                )
            else:
                self._logger.info("browser refresh page state: %s", page_state)
            return

        try:
            browser_cookies = self._browser_client.get_cookies()
        except BROWSER_CLIENT_RECOVERABLE_EXCEPTIONS as exc:
            raise self._handle_browser_client_error("get_cookies", exc) from exc

        bundle = build_runtime_cookie_bundle(browser_cookies)
        if not bundle.has_runtime_core_keys:
            self._logger.info("browser refresh waiting for runtime-ready cookies")
            return

        fingerprint = sha256(bundle.text.encode("utf-8")).hexdigest()
        seen_fingerprints = self._submitted_fingerprints_by_episode.setdefault(runtime_state.episode_id, set())
        if fingerprint in seen_fingerprints:
            return

        try:
            self._submitter.submit(bundle.text, runtime_state.episode_id)
        except requests.RequestException as exc:
            raise self._wrap_submit_error(exc) from exc
        seen_fingerprints.add(fingerprint)
