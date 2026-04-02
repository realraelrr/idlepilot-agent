# Tailscale Browser Cookie Refresh Design

## Goal
Add a private browser-refresh path that keeps the existing file-backed Xianyu recovery loop intact, automatically re-submits refreshed browser cookies when possible, and falls back to manual slider solving through a private remote browser session.

## Context
The current project already supports:
- file-backed runtime cookies in `data/cookies.txt`
- automatic recovery after `CookieInvalidError` once a new cookie file is written
- Feishu private-chat alerts and manual cookie submission

The missing piece is not recovery. The missing piece is how to obtain a fresh browser cookie with less operator effort.

The user confirmed these constraints:
- the host is a shared Ubuntu server running other services
- the existing shared Cloudflare Tunnel should not be changed
- first login inside a remote browser is acceptable
- in practice, cookies expire every 1-2 hours and often trigger a slider challenge
- manual slider completion from both Mac and phone is required
- avoid extra infrastructure unless it materially reduces risk or complexity

## Scope
- Install `tailscaled` on the Ubuntu host as a private operator access path
- Add a new `browser-refresh` container with:
  - headful Chromium
  - virtual display
  - `x11vnc`
  - `noVNC`
  - a small browser automation agent
- Persist the Chromium user profile so login state survives container restarts
- Reuse the existing runtime recovery flow in `main.py`
- Reuse the existing Feishu control plane as the single cookie-write authority
- Automatically submit a fresh cookie when the remote browser can provide one
- Fall back to operator-facing Feishu alerts when the browser is blocked by slider, login, or validation pages

## Non-Goals
- No modification of the shared Cloudflare Tunnel
- No public exposure of `noVNC`
- No attempt to bypass or solve slider verification automatically
- No replacement of the existing file-backed recovery loop in `main.py`
- No direct browser-agent writes to `data/cookies.txt`
- No removal of the existing Feishu manual submission path

## Recommended Architecture

### Responsibility Split
- `main.py`
  - remains the Xianyu execution plane
  - detects `CookieInvalidError`
  - publishes runtime status
  - waits for a refreshed `data/cookies.txt`
  - validates the new cookie and reconnects
- `services/feishu_control_plane.py`
  - remains the control plane
  - sends operator alerts
  - accepts private-chat manual cookie submissions
  - adds a protected non-Feishu auto-submit endpoint for the browser agent
  - remains the only component allowed to write `data/cookies.txt`
- `browser-refresh` container
  - keeps a persistent logged-in Chromium profile
  - exposes a private `noVNC` session for manual slider/login intervention
  - runs a browser automation agent that watches runtime recovery state
  - exports and auto-submits refreshed cookies when possible
- `tailscaled` on the host
  - provides private access for Mac and phone to the host's `6080` port
  - avoids any change to the shared public ingress layer

### Network Boundary
- `noVNC` listens only on host-local or host-private interfaces
- Tailscale provides private reachability to the host
- the browser UI is accessed over the Tailscale address of the host, not through Cloudflare
- the existing Feishu callback ingress remains unchanged

### Access Policy Boundary
- Mac:
  - access to host port `22`
  - access to host port `6080`
- Phone:
  - access to host port `6080`
- no additional operator devices are allowed by default
- no unrelated application ports on the shared host should be newly exposed through Tailscale policy

## Browser Refresh Flow

### Trigger Condition
The browser agent should remain idle until `main.py` publishes `state: waiting_for_cookie` in `data/runtime_status.json`.

The browser agent should key its work to the current `cookie_invalid_episode_id` so repeated checks during the same invalid-cookie episode do not create duplicate operator alerts.

### Automatic Attempt Flow
1. Browser agent observes `waiting_for_cookie`
2. Browser agent activates the persistent Chromium session
3. Browser agent refreshes the current Xianyu tab when one is already open; otherwise it navigates in this order:
   - `https://www.goofish.com/im`
   - `https://www.goofish.com/`
4. Browser agent reads browser cookies from the active Chromium session
5. Browser agent builds a runtime cookie bundle using the same runtime-oriented cookie contract as the existing cookie exporter
6. Browser agent validates the bundle against a stricter runtime-readiness rule
7. If valid, browser agent submits the cookie bundle to a protected auto-submit control-plane endpoint
8. Control plane reuses its existing single-flight write path and writes `data/cookies.txt`
9. `main.py` validates and reconnects through the existing recovery loop

### Manual Intervention Flow
1. Browser agent observes that the current page is blocked by slider, login, or other human verification
2. Browser agent sends one operator-facing alert through the control plane for the current episode
3. Operator opens the private `noVNC` URL on Mac or phone over Tailscale
4. Operator manually completes the slider or login flow in the remote Chromium session
5. Browser agent continues polling for page recovery and refreshed cookies
6. Once a valid runtime cookie bundle becomes available, browser agent auto-submits it
7. `main.py` recovers through the existing file-backed loop

This changes the human action from "extract and paste cookie text" to "solve the blocker in the already logged-in remote browser."

## Cookie Export Strategy

### Reuse Boundary
Reuse the cookie-selection contract from the existing Chrome cookie exporter, especially:
- runtime-target URLs
- name-based deduplication rules
- runtime core key checks
- recommended extra-key checks
- final `key=value; key=value` serialization format

The popup-driven extension flow should not remain the primary runtime path. The reusable part is the cookie-bundle contract, not the manual clipboard UX.

### Browser Agent Implementation Default
Implement the browser agent in Python inside the `browser-refresh` container.

Reasons:
- the repository is already Python-first
- the control plane and runtime status files are already Python-side concerns
- packaging one Python agent inside the browser container is simpler than keeping a long-lived development-mode extension lifecycle reliable on the server

Implementation default:
- use a Python browser automation library to drive the headed Chromium session running inside the virtual display
- port the cookie-bundle contract from `tools/chrome-cookie-exporter/exporter.js` into a small Python helper module
- keep the exported bundle semantics aligned with the existing exporter tests and runtime contract

This intentionally reuses the cookie contract while avoiding a hard dependency on popup-driven extension execution during recovery.

### Runtime Readiness Gate
The browser auto-submit path should be stricter than the current Feishu private-message ingress check.

Automatic submission requires:
- all runtime core keys present:
  - `unb`
  - `_m_h5_tk`
  - `cookie2`
  - `cna`
- serialized output in the current runtime header format

Recommended extras such as `XSRF-TOKEN`, `x5sec`, `tfstk`, and `_m_h5_tk_enc` should remain advisory. Missing extras should be logged, but should not by themselves block auto-submit if runtime core keys are complete.

This avoids repeated submission of obviously incomplete cookies while still allowing recovery from realistic browser cookie sets.

## Page-State Classification

### States
The browser agent should classify the browser session into one of four states:
- `ready`
  - target page reachable
  - runtime-ready cookie bundle available
  - safe to auto-submit
- `needs_human_verification`
  - slider page
  - human verification page
  - anti-bot challenge page
  - target page reachable but cookie bundle still lacks runtime core keys after refresh
- `needs_login`
  - explicit login page
  - QR login page
  - account re-authentication page
- `unknown_error`
  - browser launch failure
  - repeated navigation failure
  - control-plane auto-submit failure
  - unexpected page shape

### Behavior By State
- `ready`
  - submit automatically
- `needs_human_verification`
  - send one deduplicated Feishu alert for the active episode
  - keep the `noVNC` session available for operator action
  - continue low-rate polling for recovery
- `needs_login`
  - send one deduplicated Feishu alert with login-specific wording
  - continue low-rate polling for recovery
- `unknown_error`
  - log the exact failure class
  - send an operator-facing technical alert once per episode

The browser agent should never pretend a slider problem is a plain cookie failure. Operator alerts must distinguish verification, login, and technical failure paths.

## Control Plane Changes

### New Protected Auto-Submit Endpoint
Add a small non-Feishu HTTP endpoint inside `services/feishu_control_plane.py` for browser-agent submissions.

Suggested shape:
- `POST /internal/browser-cookie-submit`

Required properties:
- protected by a dedicated shared secret, separate from Feishu callback verification
- only accepts plain cookie text or a minimal JSON envelope
- reuses the existing single-flight submission flow
- does not bypass `_submit_cookie()`
- does not write cookies through a second code path

Suggested request shape:

```json
{
  "source": "browser-refresh",
  "cookie": "unb=...; _m_h5_tk=...; cookie2=...; cna=...",
  "episode_id": "cookie-invalid-..."
}
```

Suggested auth header:

```text
Authorization: Bearer <BROWSER_REFRESH_SHARED_SECRET>
```

### Why The Control Plane Must Stay The Single Writer
Keeping the control plane as the only cookie-write authority preserves:
- single-flight locking
- atomic cookie replacement
- follow-up status tracking
- one place for audit-friendly operator-visible state transitions

Allowing the browser agent to write `data/cookies.txt` directly would create a second mutation path and increase race risk on a shared host.

## Tailscale Design

### Host-Level Deployment
Install `tailscaled` on the Ubuntu host rather than running Tailscale inside a container.

Reasoning:
- simpler network model
- clearer operator access path
- no dependency between private-access infrastructure and the browser container lifecycle
- lower blast radius than modifying the shared Cloudflare Tunnel

### Operator Access Path
Operators open the `noVNC` session using the host's Tailscale address and port `6080`.

Examples:
- `http://<tailscale-hostname>:6080`
- `http://<tailscale-ip>:6080`

The host should not advertise unrelated services through Tailscale policy. Tailscale is being introduced as a narrow operator access path, not as a general-purpose shared-host exposure mechanism.

## Deployment Model

### Docker Layout
Keep the existing services and add one more:
- `xianyu-main`
- `feishu-control-plane`
- `browser-refresh`

### Shared Volumes
- project `data/`
  - shared by `xianyu-main`, `feishu-control-plane`, and `browser-refresh`
- persistent Chromium profile volume
  - mounted only into `browser-refresh`

### Browser Container Runtime
The browser container should include:
- Chromium
- virtual display server such as `Xvfb`
- `x11vnc`
- `noVNC`
- browser automation runtime
- the cookie export bridge logic

Suggested host binding:
- `127.0.0.1:6080:6080`

Binding to loopback keeps the service off the public interface while still allowing host-level Tailscale exposure.

## Operator Experience

### First-Time Setup
1. Deploy the new browser container
2. Open the private `noVNC` URL over Tailscale
3. Log into Xianyu inside the remote Chromium session
4. Leave that persistent browser profile in place for future recovery episodes

### Normal Recovery
1. Runtime enters `waiting_for_cookie`
2. Browser agent attempts refresh and export automatically
3. If no human challenge is present, cookie auto-submits and the bot recovers

### Human Verification Recovery
1. Runtime enters `waiting_for_cookie`
2. Browser agent detects slider or login blocker
3. Feishu alert tells the operator to open the private browser session
4. Operator uses phone or Mac to solve the blocker
5. Cookie auto-submits after the browser session becomes valid again
6. Bot recovers without any manual cookie copy/paste

## Logging And State Rules
- never log raw cookie contents
- log state transitions and failure classes only
- align browser-agent alert deduplication with `cookie_invalid_episode_id`
- keep browser-agent polling conservative once human intervention is required
- do not emit repeated Feishu alerts for the same episode unless the episode changes

## Verification Strategy

### Functional Verification
- prove that `main.py` still recovers when `data/cookies.txt` is updated by the control plane
- prove that browser-agent auto-submit reaches the same write path as Feishu manual submission
- prove that one slider-blocked episode sends one operator alert
- prove that after manual slider completion in `noVNC`, the browser agent auto-submits and recovery succeeds

### Security Verification
- prove that `noVNC` is not exposed through the shared public ingress
- prove that only authorized Tailscale operator devices can reach port `6080`
- prove that the browser auto-submit endpoint rejects missing or invalid shared-secret requests

### Operational Verification
- container restart should preserve Chromium login state
- browser-container restart should not break the control plane or main bot
- stale browser-agent state should not prevent later recovery episodes from alerting and recovering

## Tradeoffs

### Accepted Tradeoffs
- adding host-level Tailscale is extra operational surface, but it is lower risk than modifying the shared Cloudflare Tunnel on a shared host
- slider solving remains manual, but the manual action is reduced to remote browser interaction rather than cookie extraction
- a persistent headful browser consumes more resources than a pure HTTP worker, but it matches the verified real-world login challenge behavior

### Rejected Alternatives
- Modifying the shared Cloudflare Tunnel to expose `noVNC`
  - rejected because the host serves other more important projects
- Keeping manual clipboard-based cookie export as the primary path
  - rejected because frequent slider events make copy/paste operationally expensive
- Direct database reads from Chromium cookie storage
  - rejected because the storage and encryption path is more brittle than driving the live browser session
- Full slider automation
  - rejected because it is high-maintenance, brittle, and outside the requested risk boundary
