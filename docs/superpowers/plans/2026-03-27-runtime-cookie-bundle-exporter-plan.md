# Runtime Cookie Bundle Exporter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Chrome cookie exporter so the default popup path exports a full runtime cookie bundle that is much closer to the browser state the project actually uses for recovery, while keeping the old short key summary only as a secondary diagnostic mode.

**Architecture:** Keep the existing standalone Manifest V3 extension under `tools/chrome-cookie-exporter/`, but replace the current “default key mode vs full export mode” model with explicit export profiles. The default profile should build a runtime cookie bundle centered on the cookie set Chrome would send to `https://h5api.m.goofish.com/`, then merge in additional request-surface cookies that the current runtime demonstrably depends on. The popup must report Feishu ingress readiness and runtime readiness as separate signals.

**Tech Stack:** Chrome Extension Manifest V3, plain JavaScript, HTML/CSS, Node built-in test runner

---

## File Map

- Modify: `tools/chrome-cookie-exporter/exporter.js`
- Modify: `tools/chrome-cookie-exporter/exporter.test.js`
- Modify: `tools/chrome-cookie-exporter/popup.js`
- Modify: `tools/chrome-cookie-exporter/popup.test.js`
- Modify: `tools/chrome-cookie-exporter/popup.html`
- Modify: `tools/chrome-cookie-exporter/popup.css`
- Modify: `tools/chrome-cookie-exporter/README.md`

## Runtime Evidence To Preserve

- `main.py` writes the submitted cookie text into both:
  - `requests.Session().cookies.update(parsed_cookies)`
  - websocket handshake header `Cookie: self.cookies_str`
- `XianyuApis.py` reads these named cookies directly during recovery:
  - `unb`
  - `_m_h5_tk`
  - `cookie2`
  - `cna`
  - `XSRF-TOKEN`
- A known-good user cookie string that actually restored the runtime is much longer than the current extension output and contains additional keys such as:
  - `tfstk`
  - `x5sec`
  - `_m_h5_tk_enc`
  - `sdkSilent`
  - `csg`
  - `havana_lgc2_77`
  - `havana_lgc_exp`
  - `sgcookie`
  - `_tb_token_`
  - `t`
  - others

The redesign must therefore stop treating the short key set as the default “good enough” export.

## Export Profiles

The extension should expose these profiles explicitly:

1. `runtime`
   - Default profile
   - Intended for actual recovery
   - Builds a full cookie bundle centered on the cookies Chrome would send to `https://h5api.m.goofish.com/`
   - Merges in additional cookies from `https://www.goofish.com/` and `https://passport.goofish.com/` when those names are not already present

2. `diagnostic`
   - Secondary profile
   - Replaces the old “关键 Cookie” idea
   - Outputs only the small runtime summary keys in stable order
   - Exists for troubleshooting and quick inspection, not as the primary recovery path

Do not keep the old generic `exportAll` product behavior as the main UX concept. If a broad raw-domain export remains available internally, it should stay behind the diagnostic path or be removed.

## Serialization Contract

The exported text must remain a plain single-line Cookie-header string that the current runtime can consume without any server-side changes.

The helper and popup implementation must preserve all of these rules exactly:

- serialized format is `key=value; key=value; key=value`
- separator is exactly `"; "` (semicolon + single ASCII space)
- no JSON wrapper
- no line breaks
- no trailing semicolon
- no alternate pretty-printing format

This is required because:

- `utils/xianyu_utils.py::trans_cookies()` currently splits strictly on `"; "`
- `main.py` stores the raw submitted text as `self.cookies_str`
- websocket handshake code forwards that raw string directly as the `Cookie` header

## Readiness Signals

The popup must separate three ideas:

1. Feishu ingress readiness
   - `2 of 4` among `unb`, `_m_h5_tk`, `cookie2`, `cna`

2. Runtime named-key readiness
   - presence of `unb`, `_m_h5_tk`, `cookie2`, `cna`, `XSRF-TOKEN`

3. Runtime bundle richness
   - exported cookie count
   - exported string length
   - presence of recommended/session-shaping extras such as `x5sec`, `_m_h5_tk_enc`, `tfstk`

The popup must never present Feishu ingress success as if it means runtime recovery is likely.

### Task 1: Replace the helper model with export profiles and layered readiness

**Files:**
- Modify: `tools/chrome-cookie-exporter/exporter.js`
- Modify: `tools/chrome-cookie-exporter/exporter.test.js`

- [ ] **Step 1: Write the failing helper tests for export profiles**

Add focused failing tests for:
- default `runtime` profile returning a full bundle instead of the old 5-6 key subset
- `diagnostic` profile preserving the old stable summary order
- runtime and diagnostic profiles serializing to the exact plain Cookie-header form:
  - single line
  - `"; "` separators
  - no trailing semicolon
- layered readiness fields:
  - `hasFeishuIngressKeys`
  - `hasRuntimeCoreKeys`
  - `recommendedExtrasPresent`
  - `exportedCookieCount`
  - `exportedTextLength`
- runtime profile warnings mentioning missing runtime core keys rather than only the old `2 of 4` gate

- [ ] **Step 2: Run the helper tests to verify they fail**

Run: `node --test tools/chrome-cookie-exporter/exporter.test.js`
Expected: FAIL because the helper still models only key-order mode plus generic full-export mode

- [ ] **Step 3: Write the minimal helper implementation**

Implement in `exporter.js`:
- profile constants such as:

```javascript
const EXPORT_PROFILES = {
  runtime: "runtime",
  diagnostic: "diagnostic",
};
```

- helper constants for:
  - Feishu ingress keys
  - runtime core keys
  - recommended extras
  - runtime target URLs
- `buildExportResult({ cookies, profile })` that:
  - preserves first occurrence in caller-prioritized order
  - defaults to `runtime`
  - outputs full deduped bundle for `runtime`
  - outputs stable summary order for `diagnostic`
  - serializes `text` strictly as `key=value; key=value` with `"; "` separators and no trailing delimiter
  - returns layered readiness metadata and structured warning inputs

- [ ] **Step 4: Run the helper tests to verify they pass**

Run: `node --test tools/chrome-cookie-exporter/exporter.test.js`
Expected: PASS for the new profile model and layered readiness contract

- [ ] **Step 5: Expand the helper tests in small TDD cycles**

Add and pass focused tests for:
- duplicate-name handling across merged request-surface buckets
- runtime profile preserving first-seen ordering from caller-prioritized cookie collection
- empty runtime export
- warnings for missing runtime core keys even when Feishu ingress is satisfied
- recommended extra reporting without treating extras as hard requirements
- serialization staying stable when values contain `=` characters

### Task 2: Rebuild cookie collection around the runtime request surface

**Files:**
- Modify: `tools/chrome-cookie-exporter/popup.js`
- Modify: `tools/chrome-cookie-exporter/popup.test.js`

- [ ] **Step 1: Write the failing popup tests for runtime-bundle collection**

Add failing tests covering:
- default popup load using the `runtime` profile
- runtime collection querying `chrome.cookies.getAll({ url })` or equivalent URL-scoped collection for `https://h5api.m.goofish.com/`
- fallback merge of additional request surfaces:
  - `https://www.goofish.com/`
  - `https://passport.goofish.com/`
- preserving first occurrence in request-surface priority order
- status/warnings showing runtime readiness separately from Feishu ingress readiness
- clipboard write rejection still leaving preview text and manual-copy warnings intact
- missing clipboard API still leaving preview text and manual-copy warnings intact

- [ ] **Step 2: Run the popup tests to verify they fail**

Run: `node --test tools/chrome-cookie-exporter/popup.test.js`
Expected: FAIL because the popup still defaults to the short summary-key flow

- [ ] **Step 3: Write the minimal popup implementation**

Implement in `popup.js`:
- `state.profile = "runtime"` as the default
- collection helpers such as:
  - `collectRuntimeCookies()`
  - `collectDiagnosticCookies()`
- runtime collection priority:
  1. cookie set for `https://h5api.m.goofish.com/`
  2. additional cookies from `https://www.goofish.com/`
  3. additional cookies from `https://passport.goofish.com/`
- dedupe by first occurrence in that priority order
- popup status text that says:
  - `已复制运行时 Cookie 包到剪贴板。`
  - not `已复制关键 Cookie到剪贴板。`
- warning rendering that can show:
  - Feishu ingress satisfied / unsatisfied
  - runtime core keys missing
  - recommended extras missing
- preserve the current preview fallback behavior when automatic copy is rejected or unavailable

- [ ] **Step 4: Run popup plus helper tests together**

Run: `node --test tools/chrome-cookie-exporter/exporter.test.js tools/chrome-cookie-exporter/popup.test.js`
Expected: PASS

- [ ] **Step 5: Add a regression test for the user-observed failure mode**

Add and pass a focused test proving:
- a short summary-like cookie set can satisfy Feishu ingress while still triggering a runtime-readiness warning

### Task 3: Update popup markup and control labels for the new UX

**Files:**
- Modify: `tools/chrome-cookie-exporter/popup.html`
- Modify: `tools/chrome-cookie-exporter/popup.css`
- Modify: `tools/chrome-cookie-exporter/popup.test.js`

- [ ] **Step 1: Write the failing UI contract expectations**

Document and test the required DOM labels/regions for:
- current profile badge
- status text
- warning list
- cookie preview
- profile toggle button that switches between:
  - runtime bundle export
  - diagnostic summary export

- [ ] **Step 2: Update the popup markup and styles**

Adjust the UI so it clearly communicates:
- runtime bundle is the default recovery-oriented path
- diagnostic summary is secondary
- exported text stays selectable
- warning list is visually distinct from success status

- [ ] **Step 3: Review the wording against the runtime contract**

Expected:
- no wording that implies “Feishu accepted” means “runtime will recover”
- no wording that treats the diagnostic summary as the primary recommended path
- explicit hint that after refresh / slider verification the user should export again

### Task 4: Rewrite extension docs around runtime export instead of key summaries

**Files:**
- Modify: `tools/chrome-cookie-exporter/README.md`

- [ ] **Step 1: Write the README changes**

Document:
- default runtime bundle export behavior
- diagnostic summary mode and its limited purpose
- why the default export is intentionally longer than the previous version
- why post-slider or post-refresh re-export may be necessary
- the distinction between Feishu ingress checks and runtime recovery readiness

- [ ] **Step 2: Review docs against live evidence**

Expected:
- the README no longer recommends the short key set as the main export path
- the README explains why a longer runtime-oriented cookie string is normal

### Task 5: Deterministic verification and manual-gap recording

**Files:**
- Review only: `tools/chrome-cookie-exporter/*`

- [ ] **Step 1: Run the full automated test set**

Run: `node --test tools/chrome-cookie-exporter/exporter.test.js tools/chrome-cookie-exporter/popup.test.js`
Expected: PASS

- [ ] **Step 2: Syntax-check the scripts**

Run: `node --check tools/chrome-cookie-exporter/popup.js && node --check tools/chrome-cookie-exporter/exporter.js`
Expected: exit `0`

- [ ] **Step 3: Re-read the popup labels and README excerpts**

Run: `sed -n '1,220p' tools/chrome-cookie-exporter/popup.html && sed -n '1,260p' tools/chrome-cookie-exporter/README.md`
Expected: wording reflects runtime bundle default and diagnostic secondary mode

- [ ] **Step 4: Compare the runtime bundle against a real `h5api` request-cookie header**

Manual requirement:
1. open Chrome DevTools on a logged-in Goofish page
2. capture a real request to `https://h5api.m.goofish.com/`
3. copy the `request-cookie` header value
4. export the runtime bundle from the extension immediately afterward
5. compare the two strings after normalizing into key sets

Record at minimum:
- exact key count in the real request header
- exact key count in the extension export
- keys missing from the extension export
- keys present only in the extension export
- whether the ordering and serialization still satisfy the runtime parser contract

Expected:
- the extension export is in the same plain Cookie-header format
- the extension export materially matches the real request header key set for the targeted request surface

- [ ] **Step 5: Record the manual verification gap if parity cannot be closed in-session**

Note explicitly that this session still cannot prove:
- exact header parity, if the manual comparison above was not executed
- the post-slider “export again” path in a live logged-in browser, if that flow was not executed

- [ ] **Step 6: Record the recommended smoke test**

Document the manual smoke procedure:
1. log into Goofish in Chrome
2. capture one real `h5api.m.goofish.com` request-cookie header from DevTools
3. export runtime cookie bundle once
4. compare normalized keys against the captured header
5. paste into Feishu and observe
6. refresh page / complete slider if prompted
7. export again immediately
8. compare both header parity and recovery behavior against the first submission
