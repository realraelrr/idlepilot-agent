const EXPORT_PROFILES = {
  runtime: "runtime",
  diagnostic: "diagnostic",
};

const FEISHU_INGRESS_KEYS = ["unb", "_m_h5_tk", "cookie2", "cna"];
const RUNTIME_CORE_KEYS = ["unb", "cookie2", "cna", "_m_h5_tk"];
const RECOMMENDED_EXTRA_KEYS = ["XSRF-TOKEN", "x5sec", "tfstk", "_m_h5_tk_enc"];
const DIAGNOSTIC_COOKIE_ORDER = [
  "unb",
  "_m_h5_tk",
  "cookie2",
  "cna",
  "XSRF-TOKEN",
  "x5sec",
];
const RUNTIME_TARGET_URLS = [
  "https://h5api.m.goofish.com/",
  "https://www.goofish.com/",
  "https://passport.goofish.com/",
  "https://www.taobao.com/",
];

const COOKIE_CONTRACT = {
  detectionKeys: FEISHU_INGRESS_KEYS,
  runtimeKeys: RUNTIME_CORE_KEYS,
  recommendedKeys: RECOMMENDED_EXTRA_KEYS,
};

const KEY_COOKIE_QUERY_SPECS = [
  {
    name: "unb",
    queryUrls: [
      "ACTIVE_TAB_URL",
      "https://passport.goofish.com/",
      "https://www.goofish.com/",
      "https://www.taobao.com/",
    ],
  },
  {
    name: "_m_h5_tk",
    queryUrls: [
      "https://h5api.m.goofish.com/",
      "https://www.goofish.com/",
      "https://www.taobao.com/",
    ],
  },
  {
    name: "cookie2",
    queryUrls: [
      "https://passport.goofish.com/",
      "https://www.goofish.com/",
      "https://www.taobao.com/",
    ],
  },
  {
    name: "cna",
    queryUrls: [
      "https://passport.goofish.com/",
      "https://www.goofish.com/",
      "https://www.taobao.com/",
    ],
  },
  {
    name: "XSRF-TOKEN",
    queryUrls: [
      "https://passport.goofish.com/",
      "https://www.goofish.com/",
    ],
  },
  {
    name: "x5sec",
    queryUrls: [
      "https://www.goofish.com/",
      "https://passport.goofish.com/",
    ],
  },
];

const SUPPORTED_HOST_SUFFIXES = [
  "goofish.com",
  "taobao.com",
];

function normalizeCookie(cookie) {
  if (!cookie || typeof cookie !== "object") {
    return null;
  }

  const name = typeof cookie.name === "string" ? cookie.name.trim() : "";
  const value = typeof cookie.value === "string" ? cookie.value.trim() : "";
  const domain = typeof cookie.domain === "string" ? cookie.domain.trim() : "";

  if (!name || !value) {
    return null;
  }

  return { name, value, domain };
}

function dedupeCookies(cookies) {
  const deduped = new Map();

  for (const cookie of cookies || []) {
    const normalized = normalizeCookie(cookie);
    if (!normalized) {
      continue;
    }
    if (!deduped.has(normalized.name)) {
      deduped.set(normalized.name, normalized);
    }
  }

  return deduped;
}

function getMissingKeys(dedupedCookies, keys) {
  return keys.filter((key) => !dedupedCookies.has(key));
}

function hasAtLeastTwoKeys(dedupedCookies, keys) {
  return keys.filter((key) => dedupedCookies.has(key)).length >= 2;
}

function selectCookiesForProfile(dedupedCookies, profile) {
  if (profile === EXPORT_PROFILES.diagnostic) {
    return DIAGNOSTIC_COOKIE_ORDER
      .filter((key) => dedupedCookies.has(key))
      .map((key) => dedupedCookies.get(key));
  }

  return [...dedupedCookies.values()];
}

function serializeCookies(cookies) {
  return cookies.map((cookie) => `${cookie.name}=${cookie.value}`).join("; ");
}

function buildExportResult({ cookies, profile = EXPORT_PROFILES.runtime } = {}) {
  const normalizedProfile = profile === EXPORT_PROFILES.diagnostic
    ? EXPORT_PROFILES.diagnostic
    : EXPORT_PROFILES.runtime;
  const deduped = dedupeCookies(cookies);
  const selectedCookies = selectCookiesForProfile(deduped, normalizedProfile);
  const missingFeishuIngressKeys = getMissingKeys(deduped, FEISHU_INGRESS_KEYS);
  const missingRuntimeCoreKeys = getMissingKeys(deduped, RUNTIME_CORE_KEYS);
  const missingRecommendedExtras = getMissingKeys(deduped, RECOMMENDED_EXTRA_KEYS);
  const missingKeys = getMissingKeys(deduped, RUNTIME_CORE_KEYS);
  const text = serializeCookies(selectedCookies);
  const hasFeishuIngressKeys = hasAtLeastTwoKeys(deduped, FEISHU_INGRESS_KEYS);
  const hasRuntimeCoreKeys = missingRuntimeCoreKeys.length === 0;
  const recommendedExtrasPresent = missingRecommendedExtras.length === 0;
  const readiness = {
    hasFeishuIngressKeys,
    hasRuntimeCoreKeys,
    recommendedExtrasPresent,
    exportedCookieCount: selectedCookies.length,
    exportedTextLength: text.length,
  };
  const warningContext = {
    missingFeishuIngressKeys,
    missingRuntimeCoreKeys,
    missingRecommendedExtras,
    shouldWarnFeishuIngress: !hasFeishuIngressKeys && missingFeishuIngressKeys.length > 0,
    shouldWarnRuntimeCore: !hasRuntimeCoreKeys && missingRuntimeCoreKeys.length > 0,
    shouldWarnRecommendedExtras: missingRecommendedExtras.length > 0,
  };

  return {
    profile: normalizedProfile,
    text,
    missingKeys,
    missingFeishuIngressKeys,
    missingRuntimeCoreKeys,
    missingRecommendedExtras,
    hasRequiredCookies: hasFeishuIngressKeys,
    hasFeishuIngressKeys,
    hasRuntimeCoreKeys,
    recommendedExtrasPresent,
    exportedCookieCount: readiness.exportedCookieCount,
    exportedTextLength: readiness.exportedTextLength,
    selectedCookies,
    readiness,
    warningContext,
  };
}

function isSupportedHost(host) {
  const normalizedHost = typeof host === "string" ? host.trim().toLowerCase() : "";
  if (!normalizedHost) {
    return false;
  }

  return SUPPORTED_HOST_SUFFIXES.some(
    (suffix) => normalizedHost === suffix || normalizedHost.endsWith(`.${suffix}`),
  );
}

function getPageValidationError(url, strictValidation = true) {
  if (!strictValidation) {
    return "";
  }

  if (typeof url !== "string" || !url.trim()) {
    return "无法识别当前页面，请先打开闲鱼相关页面。";
  }

  let host = "";
  try {
    host = new URL(url).hostname;
  } catch {
    return "无法识别当前页面，请先打开闲鱼相关页面。";
  }

  if (isSupportedHost(host)) {
    return "";
  }

  return "请先打开闲鱼相关页面，再点击扩展。";
}

function buildWarningMessages(options = {}) {
  const {
    missingKeys = [],
    hasRequiredCookies = false,
    missingFeishuIngressKeys = missingKeys,
    missingRuntimeCoreKeys = [],
    missingRecommendedExtras = [],
    shouldWarnFeishuIngress = !hasRequiredCookies && missingFeishuIngressKeys.length > 0,
    hasRuntimeCoreKeys = true,
    shouldWarnRuntimeCore = !hasRuntimeCoreKeys && missingRuntimeCoreKeys.length > 0,
    shouldWarnRecommendedExtras = missingRecommendedExtras.length > 0,
    copySucceeded = true,
  } = options;
  const warnings = [];
  const receivedStructuredWarningContext =
    Object.prototype.hasOwnProperty.call(options, "shouldWarnFeishuIngress")
    || Object.prototype.hasOwnProperty.call(options, "shouldWarnRuntimeCore")
    || Object.prototype.hasOwnProperty.call(options, "shouldWarnRecommendedExtras")
    || Object.prototype.hasOwnProperty.call(options, "missingFeishuIngressKeys")
    || Object.prototype.hasOwnProperty.call(options, "missingRuntimeCoreKeys")
    || Object.prototype.hasOwnProperty.call(options, "missingRecommendedExtras");

  if (shouldWarnFeishuIngress && missingFeishuIngressKeys.length > 0) {
    warnings.push(`缺少飞书入口关键 Cookie: ${missingFeishuIngressKeys.join(", ")}`);
  }

  if (shouldWarnRuntimeCore && missingRuntimeCoreKeys.length > 0) {
    warnings.push(`当前结果缺少运行时关键 Cookie: ${missingRuntimeCoreKeys.join(", ")}`);
  } else if (!receivedStructuredWarningContext && !hasRequiredCookies && !shouldWarnFeishuIngress) {
    warnings.push("当前结果可能不足以通过项目校验，请确认你已登录闲鱼网页版。");
  }

  if (shouldWarnRecommendedExtras && missingRecommendedExtras.length > 0) {
    warnings.push(`可选补充项缺失：${missingRecommendedExtras.join(", ")}`);
  }

  if (!copySucceeded) {
    warnings.push("已生成文本，但自动复制失败，请手动复制下方内容。");
  }

  return warnings;
}

const exported = {
  COOKIE_CONTRACT,
  DIAGNOSTIC_COOKIE_ORDER,
  EXPORT_PROFILES,
  FEISHU_INGRESS_KEYS,
  KEY_COOKIE_QUERY_SPECS,
  RECOMMENDED_EXTRA_KEYS,
  RUNTIME_CORE_KEYS,
  RUNTIME_TARGET_URLS,
  SUPPORTED_HOST_SUFFIXES,
  buildExportResult,
  buildWarningMessages,
  getPageValidationError,
  isSupportedHost,
};

if (typeof module !== "undefined" && module.exports) {
  module.exports = exported;
}

if (typeof globalThis !== "undefined") {
  globalThis.CookieExporter = exported;
}
