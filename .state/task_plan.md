# Task Plan

## Goal
Implement file-backed cookie recovery so cookie invalidation no longer forces a process restart, then add one-way Feishu alerting for the invalid-cookie waiting state.

## Phases
- [completed] 1. Inspect current websocket and token-refresh flow, then align `.state/` to the cookie recovery scope
- [completed] 2. Add failing tests and implement file-backed cookie source selection plus non-interactive startup behavior
- [completed] 3. Add explicit cookie invalidation signaling, centralized runtime cookie application, and wait-for-refresh recovery
- [completed] 4. Add documentation updates and optional Feishu alerting
- [completed] 5. Run deterministic verification, record evidence, and capture deferred follow-up scope

## Verification Targets
- `data/cookies.txt` is created on startup, preferred when non-empty, and ignored by git
- Cookie invalidation raises an explicit exception instead of reading stdin or exiting the process
- Applying a new cookie refreshes HTTP session cookies, websocket headers, runtime identity, and device ID together
- Recovery waits for a changed cookie file, validates it, then reconnects without restarting the process
- Feishu alerting emits one alert per invalid-cookie episode and resets after successful recovery

## Unresolved Questions & Tradeoffs
- Manual live verification depends on a real valid and invalid cookie pair, so local automated coverage will prove control flow while the live smoke test may remain environment-dependent.
- `.env` remains a startup-only fallback during migration for compatibility, but runtime cookie writes are intentionally removed.
