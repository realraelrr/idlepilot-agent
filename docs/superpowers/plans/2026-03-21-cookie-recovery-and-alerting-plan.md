# Cookie Recovery And Feishu Alerting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make cookie refresh a file-backed, non-interactive recovery flow so the bot can survive Xianyu cookie invalidation without process restart, then add Feishu alerting as an operational enhancement.

**Architecture:** The recovery core should be local and deterministic: `data/cookies.txt` becomes the runtime cookie source of truth, `XianyuApis.get_token()` stops blocking on stdin or exiting the process, and `main.py` owns the wait-validate-reconnect loop. Runtime identity state must be refreshed atomically when a new cookie is applied so both HTTP token calls and websocket reconnects use the same cookie, `unb`, and derived device ID. Feishu support stays one-way in this implementation: alert on cookie invalidation, but do not add remote cookie update control paths yet.

**Tech Stack:** Python 3.11, `unittest`, existing `requests`, existing websocket loop, polling-based file watching, optional Feishu/Lark outgoing webhook or app message API

---

## File Structure

- Modify: `main.py`
  Purpose: Add cookie file loading, wait-for-refresh loop, runtime cookie state application, and connection/task cleanup for recovery.
- Modify: `XianyuApis.py`
  Purpose: Stop interactive cookie handling, stop `.env` mutation, and surface cookie invalidation via explicit exceptions/helpers.
- Create: `tests/test_cookie_recovery.py`
  Purpose: Add focused regression coverage for cookie source selection, invalid-cookie signaling, recovery loop behavior, and runtime state refresh.
- Create: `utils/notifier.py`
  Purpose: Encapsulate Feishu alert sending behind a small optional interface.
- Create: `data/.gitkeep`
  Purpose: Keep `data/` tracked without committing live cookies.
- Create: `data/cookies.example.txt`
  Purpose: Show operator-facing cookie file format without storing secrets.
- Modify: `.gitignore`
  Purpose: Ignore `data/cookies.txt` while keeping placeholders/examples tracked.
- Modify: `.env.example`
  Purpose: Add cookie file path and optional Feishu alert configuration.
- Modify: `README.md`
  Purpose: Document the file-based recovery workflow and optional Feishu alerting.
- Modify: `.state/task_plan.md`
  Purpose: Replace stale task scope with the cookie recovery work.
- Modify: `.state/progress.md`
  Purpose: Record implementation evidence and pivots during execution.

## Scope Exclusions

- Do not implement browser automation, slider solving, or login automation.
- Do not keep `.env` as a mutable runtime cookie store after file-based recovery lands.
- Do not add Feishu remote cookie update in this implementation.
- Do not expand this task into unrelated LLM request refactors or chat behavior changes.

### Task 1: Cookie File Loading And Startup Strategy

**Files:**
- Create: `tests/test_cookie_recovery.py`
- Modify: `main.py`
- Create: `data/.gitkeep`
- Create: `data/cookies.example.txt`
- Modify: `.gitignore`

- [ ] **Step 1: Write the failing test for cookie file priority**

```python
def test_load_cookie_string_prefers_cookie_file_over_env(self):
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -p "$PWD/conda-env" python -m unittest tests.test_cookie_recovery.CookieRecoveryTests.test_load_cookie_string_prefers_cookie_file_over_env -v`
Expected: FAIL because no file-backed loader exists yet.

- [ ] **Step 3: Write the failing test for empty file fallback**

```python
def test_load_cookie_string_falls_back_to_env_when_file_empty(self):
    ...
```

- [ ] **Step 4: Run test to verify it fails**

Run: `conda run -p "$PWD/conda-env" python -m unittest tests.test_cookie_recovery.CookieRecoveryTests.test_load_cookie_string_falls_back_to_env_when_file_empty -v`
Expected: FAIL because the fallback logic does not exist yet.

- [ ] **Step 5: Implement minimal cookie file helpers in `main.py`**

Must include explicit helpers such as:

```python
def load_cookie_string(self) -> str:
    ...

def read_cookie_file(self) -> str:
    ...
```

Behavior:
- Prefer `data/cookies.txt` when non-empty
- Fall back to `.env` `COOKIES_STR` only when file missing or empty
- If `data/cookies.txt` does not exist, create it as an empty file during startup preparation
- Do not write back to `.env`

- [ ] **Step 6: Add tracked placeholders and ignore the real cookie file**

Required repo shape:
- Track `data/.gitkeep`
- Track `data/cookies.example.txt`
- Ignore `data/cookies.txt`

- [ ] **Step 7: Remove interactive startup dependence on `COOKIES_STR`**

Required behavior:
- `check_and_complete_env()` must not force `input()` for missing `COOKIES_STR`
- Startup must proceed using the file-backed cookie loader and empty-file semantics
- `API_KEY` may remain interactive or move to non-interactive validation separately, but cookie startup must no longer require terminal input

- [ ] **Step 8: Run focused tests to verify Task 1**

Run: `conda run -p "$PWD/conda-env" python -m unittest tests.test_cookie_recovery.CookieRecoveryTests.test_load_cookie_string_prefers_cookie_file_over_env tests.test_cookie_recovery.CookieRecoveryTests.test_load_cookie_string_falls_back_to_env_when_file_empty -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add main.py tests/test_cookie_recovery.py data/.gitkeep data/cookies.example.txt .gitignore
git commit -m "feat: add file-backed cookie source selection"
```

### Task 2: CookieInvalidError And Non-Interactive Token Failure Handling

**Files:**
- Modify: `XianyuApis.py`
- Test: `tests/test_cookie_recovery.py`

- [ ] **Step 1: Write the failing test for cookie invalidation signaling**

```python
def test_get_token_raises_cookie_invalid_error_on_rgv587(self):
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -p "$PWD/conda-env" python -m unittest tests.test_cookie_recovery.CookieRecoveryTests.test_get_token_raises_cookie_invalid_error_on_rgv587 -v`
Expected: FAIL because `get_token()` still reads from stdin or exits.

- [ ] **Step 3: Implement `CookieInvalidError` and remove interactive stdin flow**

Requirements:
- No `input()`
- No `sys.exit(1)` for cookie invalidation
- Raise explicit cookie-invalid exception on RGV587 / validation failure
- Keep bounded retry behavior for ordinary transient token failures

- [ ] **Step 4: Ensure `refresh_token()` does not swallow `CookieInvalidError`**

Required behavior:
- `XianyuLive.refresh_token()` may keep generic handling for ordinary failures
- It must allow `CookieInvalidError` to propagate so the main loop can enter waiting state

- [ ] **Step 5: Remove `.env` cookie mutation side effects**

Required changes:
- Delete or retire `update_env_cookies()` from runtime flow
- Stop calling `.env` mutation from `clear_duplicate_cookies()`

- [ ] **Step 6: Run focused tests to verify Task 2**

Run: `conda run -p "$PWD/conda-env" python -m unittest tests.test_cookie_recovery.CookieRecoveryTests.test_get_token_raises_cookie_invalid_error_on_rgv587 -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add XianyuApis.py tests/test_cookie_recovery.py
git commit -m "refactor: surface cookie invalidation without exiting"
```

### Task 3: Runtime State Synchronization And Cookie Application

**Files:**
- Modify: `main.py`
- Test: `tests/test_cookie_recovery.py`

- [ ] **Step 1: Write the failing test for runtime identity refresh**

```python
def test_apply_cookie_string_refreshes_cookie_headers_identity_and_device(self):
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -p "$PWD/conda-env" python -m unittest tests.test_cookie_recovery.CookieRecoveryTests.test_apply_cookie_string_refreshes_cookie_headers_identity_and_device -v`
Expected: FAIL because cookie-derived runtime state is only initialized once.

- [ ] **Step 3: Implement a single runtime cookie application helper**

Required helper shape:

```python
def apply_cookie_string(self, cookie_str: str) -> None:
    ...
```

It must update, together, in one place:
- `self.cookies_str`
- `self.cookies`
- `self.xianyu.session.cookies`
- `self.myid`
- `self.device_id`

- [ ] **Step 4: Ensure reconnect uses refreshed runtime state**

Verify:
- WebSocket headers use refreshed `self.cookies_str`
- Future token refreshes use refreshed session cookies

- [ ] **Step 5: Run focused tests to verify Task 3**

Run: `conda run -p "$PWD/conda-env" python -m unittest tests.test_cookie_recovery.CookieRecoveryTests.test_apply_cookie_string_refreshes_cookie_headers_identity_and_device -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_cookie_recovery.py
git commit -m "fix: centralize runtime cookie state application"
```

### Task 4: Wait For New Cookie And Validate Recovery

**Files:**
- Modify: `main.py`
- Test: `tests/test_cookie_recovery.py`

- [ ] **Step 1: Write the failing test for wait-and-recover behavior**

```python
async def test_wait_for_cookie_refresh_validates_before_reconnect(self):
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -p "$PWD/conda-env" python -m unittest tests.test_cookie_recovery.CookieRecoveryTests.test_wait_for_cookie_refresh_validates_before_reconnect -v`
Expected: FAIL because no wait loop exists.

- [ ] **Step 3: Implement cookie refresh waiting helper**

Required helper shape:

```python
async def wait_for_cookie_refresh(self) -> None:
    ...
```

Behavior:
- Poll `data/cookies.txt` every 5 seconds
- Ignore unchanged or empty content
- Apply candidate cookie
- Validate via `refresh_token()`
- Return only after validation succeeds

- [ ] **Step 4: Wire cookie-invalid state into the main loop**

Behavior:
- On `CookieInvalidError`, enter wait mode instead of terminating
- Log explicit state transition into “waiting for cookie refresh”
- Use `apply_cookie_string()` rather than ad-hoc cookie/session mutation

- [ ] **Step 5: Ensure old connection tasks are cleaned up before recovery**

Must cover:
- `self.ws`
- `heartbeat_task`
- `token_refresh_task`
- any connection restart flags that could cause duplicate reconnects

- [ ] **Step 6: Run focused tests to verify Task 4**

Run: `conda run -p "$PWD/conda-env" python -m unittest tests.test_cookie_recovery.CookieRecoveryTests.test_wait_for_cookie_refresh_validates_before_reconnect -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_cookie_recovery.py
git commit -m "feat: wait for cookie refresh and auto-resume"
```

### Task 5: Documentation And Repository Hygiene

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `.gitignore`

- [ ] **Step 1: Document the cookie file operator workflow**

Must cover:
- `data/cookies.txt` is the live cookie source
- Process no longer needs restart after cookie invalidation
- Operator refreshes cookie in file, process validates, then reconnects

- [ ] **Step 2: Document migration expectations**

Must state:
- `.env` fallback exists for startup compatibility only
- Runtime cookie updates no longer write back into `.env`

- [ ] **Step 3: Run docs sanity check**

Run: `rg -n "cookies.txt|CookieInvalidError|自动恢复|自动接续|.env" README.md .env.example .gitignore`
Expected: Matches the file-backed workflow and ignores `data/cookies.txt`.

- [ ] **Step 4: Commit**

```bash
git add README.md .env.example .gitignore
git commit -m "docs: explain cookie file recovery workflow"
```

### Task 6: Feishu Alerting

**Files:**
- Create: `utils/notifier.py`
- Modify: `main.py`
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Write the failing test for cookie-invalid alert sending**

```python
def test_cookie_invalid_transition_sends_single_feishu_alert(self):
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -p "$PWD/conda-env" python -m unittest tests.test_cookie_recovery.CookieRecoveryTests.test_cookie_invalid_transition_sends_single_feishu_alert -v`
Expected: FAIL because no notifier exists.

- [ ] **Step 3: Implement a minimal notifier abstraction**

Requirements:
- Optional enable flag
- Outgoing alert only
- No inbound command handling
- No raw cookie values in alerts or logs

- [ ] **Step 4: Trigger one alert per cookie-invalid episode**

Behavior:
- Send when entering waiting state
- Do not spam on each poll retry
- Reset alert suppression after successful recovery

- [ ] **Step 5: Run focused tests to verify Task 6**

Run: `conda run -p "$PWD/conda-env" python -m unittest tests.test_cookie_recovery.CookieRecoveryTests.test_cookie_invalid_transition_sends_single_feishu_alert -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add utils/notifier.py main.py .env.example README.md tests/test_cookie_recovery.py
git commit -m "feat: add feishu alerting for cookie invalidation"
```

### Task 7: Full Verification And Follow-Up Scope Record

**Files:**
- Modify: `.state/task_plan.md`
- Modify: `.state/progress.md`

- [ ] **Step 1: Rewrite `.state/task_plan.md` to this cookie recovery scope**

- [ ] **Step 2: Append implementation evidence to `.state/progress.md`**

- [ ] **Step 3: Run the full automated test suite**

Run: `conda run -p "$PWD/conda-env" python -m unittest discover -s tests -v`
Expected: PASS

- [ ] **Step 4: Run syntax verification**

Run: `conda run -p "$PWD/conda-env" python -m compileall XianyuApis.py main.py utils tests`
Expected: PASS

- [ ] **Step 5: Run a manual live smoke test**

Run: `conda run --no-capture-output -p "$PWD/conda-env" python -u main.py`
Expected:
- Valid cookie starts normally
- Invalid cookie does not exit the process
- Process logs waiting state
- Writing a fresh valid cookie into `data/cookies.txt` causes validation and reconnect
- If Feishu is enabled, one alert is sent when cookie invalidation begins

- [ ] **Step 6: Record remote-update follow-up explicitly**

Add to progress or handoff:
- Feishu remote cookie update is intentionally deferred
- It requires a separate control-plane design and authorization review

- [ ] **Step 7: Commit**

```bash
git add .state/task_plan.md .state/progress.md
git commit -m "chore: record cookie recovery verification and follow-up scope"
```

## Notes For Implementation

- Keep the cookie runtime source-of-truth singular: `data/cookies.txt`.
- `.env` is startup fallback only during migration; never mutate it at runtime.
- Avoid scattering cookie mutation logic. Centralize it in explicit helpers like `load_cookie_string()`, `apply_cookie_string()`, and `wait_for_cookie_refresh()`.
- Keep Feishu to one-way alerting in this implementation. Remote cookie updates need a separate design because they introduce an inbound control plane, authorization, and secret-handling risks.
- Never log or return full cookie values.
