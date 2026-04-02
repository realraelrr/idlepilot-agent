from __future__ import annotations

import logging
import os
import time

from browser_refresh.agent import BrowserRefreshAgent, BrowserRefreshRecoverableError
from browser_refresh.browser_client import BrowserSessionClient
from browser_refresh.runtime_state import read_runtime_state
from browser_refresh.submitter import BrowserCookieSubmitter


DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_RUNTIME_STATUS_PATH = os.path.join("data", "runtime_status.json")


def _read_required_env(name: str) -> str:
    value = str(os.getenv(name) or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _read_poll_interval_seconds() -> float:
    raw_value = str(os.getenv("BROWSER_REFRESH_POLL_INTERVAL_SECONDS") or DEFAULT_POLL_INTERVAL_SECONDS).strip()
    return max(float(raw_value), 0.0)


def run_agent_iteration(agent: BrowserRefreshAgent, *, logger=None) -> None:
    active_logger = logger or logging.getLogger(__name__)
    try:
        agent.run_once()
    except BrowserRefreshRecoverableError as exc:
        active_logger.warning("browser refresh iteration failed recoverably: %s", exc)


def main() -> None:
    logging.basicConfig(level=os.getenv("BROWSER_REFRESH_LOG_LEVEL", "INFO").upper())
    logger = logging.getLogger(__name__)

    runtime_status_path = str(
        os.getenv("BROWSER_REFRESH_RUNTIME_STATUS_PATH") or DEFAULT_RUNTIME_STATUS_PATH
    ).strip()
    browser_client = BrowserSessionClient.connect(
        debugger_url=_read_required_env("BROWSER_REFRESH_DEBUGGER_URL")
    )
    submitter = BrowserCookieSubmitter.from_env()
    agent = BrowserRefreshAgent(
        status_reader=lambda: read_runtime_state(runtime_status_path),
        browser_client=browser_client,
        submitter=submitter,
    )
    poll_interval_seconds = _read_poll_interval_seconds()

    while True:
        run_agent_iteration(agent, logger=logger)
        time.sleep(poll_interval_seconds)
