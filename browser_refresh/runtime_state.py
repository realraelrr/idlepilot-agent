import json
import os
from dataclasses import dataclass


ACTIVE_RECOVERY_STATES = {
    "waiting_for_cookie",
    "validating_new_cookie",
    "validation_failed",
}


@dataclass(frozen=True)
class RuntimeState:
    state: str
    episode_id: str
    is_recovery_active: bool


def read_runtime_state(status_path: str) -> RuntimeState:
    if not os.path.exists(status_path):
        return RuntimeState(state="", episode_id="", is_recovery_active=False)

    with open(status_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    state = str(payload.get("state") or "").strip()
    episode_id = str(payload.get("cookie_invalid_episode_id") or "").strip()
    is_recovery_active = bool(episode_id) and state in ACTIVE_RECOVERY_STATES
    return RuntimeState(
        state=state,
        episode_id=episode_id,
        is_recovery_active=is_recovery_active,
    )
