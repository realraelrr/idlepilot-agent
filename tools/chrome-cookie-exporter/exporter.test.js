const test = require("node:test");
const assert = require("node:assert/strict");

const {
  RUNTIME_TARGET_URLS,
  buildExportResult,
  buildWarningMessages,
  getPageValidationError,
  isSupportedHost,
} = require("./exporter.js");

function makeCookie(name, value, domain = ".goofish.com") {
  return { name, value, domain };
}

test("buildExportResult defaults to the runtime profile and exports the full deduped bundle", () => {
  const cookies = [
    makeCookie("cookie2", "cookie2-value"),
    makeCookie("unb", "unb-value"),
    makeCookie("tfstk", "tfstk-value"),
    makeCookie("cna", "cna-value", ".taobao.com"),
    makeCookie("_m_h5_tk", "token-value"),
    makeCookie("_m_h5_tk_enc", "enc-value"),
    makeCookie("XSRF-TOKEN", "xsrf-value"),
    makeCookie("x5sec", "x5sec-value"),
  ];

  const result = buildExportResult({ cookies });

  assert.equal(
    result.text,
    "cookie2=cookie2-value; unb=unb-value; tfstk=tfstk-value; cna=cna-value; _m_h5_tk=token-value; _m_h5_tk_enc=enc-value; XSRF-TOKEN=xsrf-value; x5sec=x5sec-value",
  );
  assert.deepEqual(
    result.selectedCookies.map((cookie) => cookie.name),
    ["cookie2", "unb", "tfstk", "cna", "_m_h5_tk", "_m_h5_tk_enc", "XSRF-TOKEN", "x5sec"],
  );
  assert.equal(result.hasFeishuIngressKeys, true);
  assert.equal(result.hasRuntimeCoreKeys, true);
  assert.equal(result.recommendedExtrasPresent, true);
  assert.equal(result.exportedCookieCount, 8);
  assert.equal(result.exportedTextLength, result.text.length);
});

test("buildExportResult uses the diagnostic profile to preserve the stable summary order", () => {
  const cookies = [
    makeCookie("tfstk", "tfstk-value"),
    makeCookie("cookie2", "cookie2-value"),
    makeCookie("unb", "unb-value"),
    makeCookie("x5sec", "x5sec-value"),
    makeCookie("cna", "cna-value", ".taobao.com"),
    makeCookie("_m_h5_tk", "token-value"),
    makeCookie("XSRF-TOKEN", "xsrf-value"),
  ];

  const result = buildExportResult({
    cookies,
    profile: "diagnostic",
  });

  assert.equal(
    result.text,
    "unb=unb-value; _m_h5_tk=token-value; cookie2=cookie2-value; cna=cna-value; XSRF-TOKEN=xsrf-value; x5sec=x5sec-value",
  );
  assert.deepEqual(
    result.selectedCookies.map((cookie) => cookie.name),
    ["unb", "_m_h5_tk", "cookie2", "cna", "XSRF-TOKEN", "x5sec"],
  );
});

test("buildExportResult serializes both export profiles as a single Cookie header line", () => {
  const cookies = [
    makeCookie("unb", "first"),
    makeCookie("_m_h5_tk", "contains=equals"),
    makeCookie("cookie2", "third"),
  ];

  const runtimeResult = buildExportResult({
    cookies,
    profile: "runtime",
  });
  const diagnosticResult = buildExportResult({
    cookies,
    profile: "diagnostic",
  });

  assert.equal(runtimeResult.text, "unb=first; _m_h5_tk=contains=equals; cookie2=third");
  assert.equal(diagnosticResult.text, "unb=first; _m_h5_tk=contains=equals; cookie2=third");
  assert.equal(runtimeResult.text.includes("\n"), false);
  assert.equal(diagnosticResult.text.includes("\n"), false);
  assert.equal(runtimeResult.text.endsWith(";"), false);
  assert.equal(diagnosticResult.text.endsWith(";"), false);
});

test("buildExportResult reports layered readiness fields for partial runtime bundles", () => {
  const result = buildExportResult({
    cookies: [
      makeCookie("unb", "unb-value"),
      makeCookie("cookie2", "cookie2-value"),
      makeCookie("cna", "cna-value"),
      makeCookie("x5sec", "x5sec-value"),
    ],
  });

  assert.equal(result.hasFeishuIngressKeys, true);
  assert.equal(result.hasRuntimeCoreKeys, false);
  assert.equal(result.recommendedExtrasPresent, false);
  assert.equal(result.exportedCookieCount, 4);
  assert.equal(result.exportedTextLength, result.text.length);
  assert.deepEqual(result.missingFeishuIngressKeys, ["_m_h5_tk"]);
  assert.deepEqual(result.missingRuntimeCoreKeys, ["_m_h5_tk"]);
  assert.deepEqual(result.missingRecommendedExtras, ["XSRF-TOKEN", "tfstk", "_m_h5_tk_enc"]);
});

test("buildWarningMessages mention missing runtime core keys instead of the old generic gate", () => {
  const result = buildExportResult({
    cookies: [
      makeCookie("unb", "unb-value"),
      makeCookie("_m_h5_tk", "token-value"),
      makeCookie("cookie2", "cookie2-value"),
      makeCookie("cna", "cna-value"),
    ],
  });

  const warnings = buildWarningMessages({
    ...result.warningContext,
    copySucceeded: true,
  });

  assert.deepEqual(warnings, ["可选补充项缺失：XSRF-TOKEN, x5sec, tfstk, _m_h5_tk_enc"]);
});

test("buildExportResult keeps the first occurrence across merged request-surface buckets", () => {
  const cookies = [
    makeCookie("unb", "active-tab"),
    makeCookie("cookie2", "cookie2-value"),
    makeCookie("unb", "passport-fallback"),
    makeCookie("cookie2", "cookie2-shadowed"),
    makeCookie("_m_h5_tk", "token-value"),
  ];

  const result = buildExportResult({ cookies });

  assert.equal(result.text, "unb=active-tab; cookie2=cookie2-value; _m_h5_tk=token-value");
});

test("buildExportResult preserves first-seen ordering for the runtime profile", () => {
  const cookies = [
    makeCookie("tfstk", "tfstk-value"),
    makeCookie("unb", "unb-value"),
    makeCookie("cookie2", "cookie2-value"),
    makeCookie("XSRF-TOKEN", "xsrf-value"),
  ];

  const result = buildExportResult({
    cookies,
    profile: "runtime",
  });

  assert.deepEqual(
    result.selectedCookies.map((cookie) => cookie.name),
    ["tfstk", "unb", "cookie2", "XSRF-TOKEN"],
  );
});

test("buildExportResult reports an empty runtime export cleanly", () => {
  const result = buildExportResult({
    cookies: [],
    profile: "runtime",
  });

  assert.equal(result.text, "");
  assert.equal(result.exportedCookieCount, 0);
  assert.equal(result.exportedTextLength, 0);
  assert.equal(result.hasFeishuIngressKeys, false);
  assert.equal(result.hasRuntimeCoreKeys, false);
  assert.equal(result.recommendedExtrasPresent, false);
});

test("buildWarningMessages still warn about missing runtime core keys when Feishu ingress is satisfied", () => {
  const result = buildExportResult({
    cookies: [
      makeCookie("unb", "unb-value"),
      makeCookie("_m_h5_tk", "token-value"),
      makeCookie("cookie2", "cookie2-value"),
      makeCookie("cna", "cna-value"),
      makeCookie("x5sec", "x5sec-value"),
    ],
  });

  const warnings = buildWarningMessages({
    ...result.warningContext,
    copySucceeded: true,
  });

  assert.equal(result.hasFeishuIngressKeys, true);
  assert.equal(result.hasRuntimeCoreKeys, true);
  assert.deepEqual(warnings, ["可选补充项缺失：XSRF-TOKEN, tfstk, _m_h5_tk_enc"]);
});

test("buildExportResult reports recommended extras without treating them as hard requirements", () => {
  const result = buildExportResult({
    cookies: [
      makeCookie("unb", "unb-value"),
      makeCookie("_m_h5_tk", "token-value"),
      makeCookie("cookie2", "cookie2-value"),
      makeCookie("cna", "cna-value"),
      makeCookie("XSRF-TOKEN", "xsrf-value"),
    ],
  });

  assert.equal(result.hasFeishuIngressKeys, true);
  assert.equal(result.hasRuntimeCoreKeys, true);
  assert.equal(result.recommendedExtrasPresent, false);
  assert.deepEqual(result.missingRecommendedExtras, ["x5sec", "tfstk", "_m_h5_tk_enc"]);
});

test("buildWarningMessages do not treat missing recommended extras as hard-failure key warnings", () => {
  const result = buildExportResult({
    cookies: [
      makeCookie("unb", "unb-value"),
      makeCookie("_m_h5_tk", "token-value"),
      makeCookie("cookie2", "cookie2-value"),
      makeCookie("cna", "cna-value"),
      makeCookie("XSRF-TOKEN", "xsrf-value"),
    ],
  });

  const warnings = buildWarningMessages({
    ...result.warningContext,
    copySucceeded: true,
  });

  assert.deepEqual(warnings, ["可选补充项缺失：x5sec, tfstk, _m_h5_tk_enc"]);
});

test("buildWarningMessages label optional supplemental-cookie gaps as informational", () => {
  const warnings = buildWarningMessages({
    missingRecommendedExtras: ["XSRF-TOKEN"],
    shouldWarnRecommendedExtras: true,
    copySucceeded: true,
  });

  assert.deepEqual(warnings, ["可选补充项缺失：XSRF-TOKEN"]);
});

test("buildExportResult exposes layered readiness and warning metadata for task consumers", () => {
  const result = buildExportResult({
    cookies: [
      makeCookie("unb", "unb-value"),
      makeCookie("cookie2", "cookie2-value"),
      makeCookie("cna", "cna-value"),
      makeCookie("x5sec", "x5sec-value"),
      makeCookie("tfstk", "tfstk-value"),
    ],
  });

  assert.deepEqual(result.readiness, {
    hasFeishuIngressKeys: true,
    hasRuntimeCoreKeys: false,
    recommendedExtrasPresent: false,
    exportedCookieCount: 5,
    exportedTextLength: result.text.length,
  });
  assert.deepEqual(result.warningContext, {
    missingFeishuIngressKeys: ["_m_h5_tk"],
    missingRuntimeCoreKeys: ["_m_h5_tk"],
    missingRecommendedExtras: ["XSRF-TOKEN", "_m_h5_tk_enc"],
    shouldWarnFeishuIngress: false,
    shouldWarnRuntimeCore: true,
    shouldWarnRecommendedExtras: true,
  });
});

test("buildExportResult keeps serialization stable when values contain equals characters", () => {
  const result = buildExportResult({
    cookies: [
      makeCookie("_m_h5_tk", "prefix=payload"),
      makeCookie("tfstk", "aa=bb=cc"),
    ],
    profile: "runtime",
  });

  assert.equal(result.text, "_m_h5_tk=prefix=payload; tfstk=aa=bb=cc");
});

test("isSupportedHost recognizes supported Xianyu hosts", () => {
  assert.equal(isSupportedHost("www.goofish.com"), true);
  assert.equal(isSupportedHost("h5.goofish.com"), true);
  assert.equal(isSupportedHost("login.taobao.com"), true);
  assert.equal(isSupportedHost("example.com"), false);
  assert.equal(isSupportedHost(""), false);
});

test("getPageValidationError enforces supported pages in strict mode", () => {
  assert.equal(getPageValidationError("https://www.goofish.com/im", true), "");
  assert.match(
    getPageValidationError("https://example.com", true),
    /请先打开闲鱼相关页面/u,
  );
  assert.equal(getPageValidationError("https://example.com", false), "");
  assert.match(getPageValidationError("", true), /无法识别当前页面/u);
});

test("buildWarningMessages includes missing cookie and copy warnings", () => {
  const warnings = buildWarningMessages({
    missingFeishuIngressKeys: ["_m_h5_tk"],
    missingRuntimeCoreKeys: ["_m_h5_tk"],
    missingRecommendedExtras: ["x5sec"],
    shouldWarnFeishuIngress: true,
    shouldWarnRuntimeCore: true,
    shouldWarnRecommendedExtras: false,
    hasRuntimeCoreKeys: false,
    copySucceeded: false,
  });

  assert.deepEqual(warnings, [
    "缺少飞书入口关键 Cookie: _m_h5_tk",
    "当前结果缺少运行时关键 Cookie: _m_h5_tk",
    "已生成文本，但自动复制失败，请手动复制下方内容。",
  ]);
});

test("RUNTIME_TARGET_URLS stays aligned with the runtime request-surface priority", () => {
  assert.deepEqual(RUNTIME_TARGET_URLS, [
    "https://h5api.m.goofish.com/",
    "https://www.goofish.com/",
    "https://passport.goofish.com/",
    "https://www.taobao.com/",
  ]);
});

test("buildExportResult does not treat missing XSRF-TOKEN as a runtime-core failure", () => {
  const result = buildExportResult({
    cookies: [
      makeCookie("unb", "unb-value"),
      makeCookie("_m_h5_tk", "token-value"),
      makeCookie("cookie2", "cookie2-value"),
      makeCookie("cna", "cna-value", ".taobao.com"),
    ],
  });

  assert.equal(result.hasRuntimeCoreKeys, true);
  assert.deepEqual(result.missingRuntimeCoreKeys, []);
  assert.deepEqual(result.missingRecommendedExtras, ["XSRF-TOKEN", "x5sec", "tfstk", "_m_h5_tk_enc"]);
});
