# Task Plan

## Goal
Implement a Feishu app-based private-chat control plane so whitelisted admins can submit cookies, write them safely to `data/cookies.txt`, and receive recovery results correlated to the existing cookie-recovery loop.

## Phases
- [completed] 1. Set up an isolated worktree, review the Feishu control-plane design/plan, and align `.state/` to the new implementation scope
- [completed] 2. Add the Feishu control-plane module, configuration parsing, callback bootstrap, and trusted-event intake behind focused failing tests
- [completed] 3. Add the Feishu API client, private-chat authorization, command parsing, and single-flight cookie submission flow with correlated state files
- [completed] 4. Publish correlated runtime recovery status from `main.py`, add the final acknowledgement loop, and wire the callback service entrypoint
- [completed] 5. Update operator docs/example files, run deterministic verification, and record evidence plus residual risks

## Verification Targets
- Feishu control-plane config validates required app credentials, whitelist, callback settings, and stale-lock policy
- Trusted callback intake verifies the configured mode, handles URL verification, and deduplicates retried events before side effects
- Whitelisted private-chat cookie submissions write `data/cookies.txt` atomically, create correlated submission metadata, and reject overlapping submissions
- `main.py` publishes machine-readable runtime recovery status with `submission_id` correlation and without leaking cookie contents
- Accepted submissions get an immediate acknowledgement plus a bounded final Feishu reply for `recovered`, `validation_failed`, or timeout

## Unresolved Questions & Tradeoffs
- Live end-to-end verification still depends on a reachable Feishu callback deployment, real app credentials, and a real whitelisted admin chat, so the current evidence stops at local loopback callback smoke plus automated coverage.
- `FEISHU_CALLBACK_MODE=encrypt` is intentionally not implemented in this build because the repo has no crypto dependency; the service now validates and documents token mode explicitly, and returns `501` for encrypted callback payloads instead of pretending support.
