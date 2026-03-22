# Task Plan

## Goal
Migrate cookie-expiration alerting from the legacy webhook notifier to the Feishu app control plane so admins receive one proactive private-chat alert per invalid-cookie episode, deduplicated across restarts.

## Phases
- [completed] 1. Create an isolated worktree off `main`, verify the worktree directory is ignored, and confirm a clean automated baseline with the shared conda environment
- [completed] 2. Execute Task 1 in TDD order: remove the webhook notifier path from `main.py`, mint and publish stable `cookie_invalid_episode_id` values, and retire webhook-era tests/code
- [completed] 3. Execute Task 2 in TDD order: add a runtime-status watcher in `services/feishu_control_plane.py` with persisted alert deduplication in `data/alert_state.json`
- [completed] 4. Execute Task 3: clean up `.gitignore`, `.env.example`, and `README.md` so docs/config match the app-bot alert architecture
- [completed] 5. Execute Task 4: append implementation evidence to `.state/progress.md`, run full test and syntax verification, then review the branch state for handoff

## Verification Targets
- `enter_cookie_invalid_state()` only flags/logs invalid-cookie state and no longer depends on webhook delivery
- Runtime status writes carry one stable `cookie_invalid_episode_id` across `waiting_for_cookie`, `validating_new_cookie`, `validation_failed`, and `recovered` for the same invalid-cookie episode
- The Feishu control plane sends one proactive private-chat alert per waiting episode to all whitelisted admins and suppresses duplicates across restarts using `data/alert_state.json`
- Terminal runtime states for the same episode (`recovered`, `validation_failed`) close suppression so the next episode can alert again
- Docs and example config no longer mention the retired webhook env vars and do document proactive app-bot alerting plus `data/alert_state.json`

## Unresolved Questions & Tradeoffs
- The implementation plan assumes the control plane should tolerate missing `cookie_invalid_episode_id` temporarily by falling back to a compatibility key, but that fallback should remain internal and not become a long-term contract.
