from __future__ import annotations

import logging
from hashlib import sha256

from browser_refresh.cookie_bundle import build_runtime_cookie_bundle


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

    def run_once(self) -> None:
        runtime_state = self._status_reader()
        if not runtime_state.is_recovery_active:
            self._prepared_episode_id = ""
            return

        if runtime_state.episode_id != self._prepared_episode_id:
            self._browser_client.prepare_target_page()
            self._transition_episode(runtime_state.episode_id)
        page_state = self._browser_client.classify_page_state()
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

        bundle = build_runtime_cookie_bundle(self._browser_client.get_cookies())
        if not bundle.has_runtime_core_keys:
            self._logger.info("browser refresh waiting for runtime-ready cookies")
            return

        fingerprint = sha256(bundle.text.encode("utf-8")).hexdigest()
        seen_fingerprints = self._submitted_fingerprints_by_episode.setdefault(runtime_state.episode_id, set())
        if fingerprint in seen_fingerprints:
            return

        self._submitter.submit(bundle.text, runtime_state.episode_id)
        seen_fingerprints.add(fingerprint)
