function createPopupApp({
  exporter = globalThis.CookieExporter,
  chromeApi = globalThis.chrome,
  clipboard = globalThis.navigator ? globalThis.navigator.clipboard : null,
  document = globalThis.document,
} = {}) {
  const state = {
    profile: "runtime",
    strictValidation: true,
    currentText: "",
    currentResult: null,
  };

  function requireElement(id) {
    const element = document.getElementById(id);
    if (!element) {
      throw new Error(`缺少必要的弹窗节点: ${id}`);
    }
    return element;
  }

  function resolveElements() {
    return {
      status: requireElement("status"),
      readinessSummary: requireElement("readinessSummary"),
      warnings: requireElement("warnings"),
      cookieOutput: requireElement("cookieOutput"),
      modeBadge: requireElement("modeBadge"),
      copyButton: requireElement("copyButton"),
      toggleExportModeButton: requireElement("toggleExportModeButton"),
      retryWithoutValidationButton: requireElement("retryWithoutValidationButton"),
    };
  }

  async function initialize() {
    if (!exporter) {
      throw new Error("Cookie exporter helpers are unavailable");
    }
    if (!chromeApi) {
      throw new Error("Chrome extension APIs are unavailable");
    }

    const elements = resolveElements();
    elements.copyButton.addEventListener("click", () => handleCopy(elements));
    elements.toggleExportModeButton.addEventListener("click", async () => {
      state.profile = state.profile === "runtime" ? "diagnostic" : "runtime";
      await runExport(elements);
    });
    elements.retryWithoutValidationButton.addEventListener("click", async () => {
      state.strictValidation = false;
      await runExport(elements);
    });

    await runExport(elements);
    return elements;
  }

  async function runExport(elements) {
    setStatus(elements, "处理中，请稍候…");
    setWarnings(elements, []);
    setReadinessSummary(elements, "");
    elements.cookieOutput.value = "";
    elements.copyButton.disabled = true;
    state.currentText = "";
    state.currentResult = null;
    updateModeLabels(elements);

    try {
      const activeTab = await getActiveTab();
      const pageError = exporter.getPageValidationError(activeTab.url, state.strictValidation);
      if (pageError) {
        setStatus(elements, "请先打开闲鱼相关页面。");
        setWarnings(elements, []);
        setReadinessSummary(elements, "");
        setRetryVisibility(elements, true);
        return;
      }

      const cookies = state.profile === exporter.EXPORT_PROFILES.diagnostic
        ? await collectDiagnosticCookies(activeTab.url)
        : await collectRuntimeCookies();
      const profile = getActiveProfile();

      const result = exporter.buildExportResult({
        cookies,
        profile,
      });

      state.currentText = result.text;
      state.currentResult = result;
      elements.cookieOutput.value = result.text;
      elements.copyButton.disabled = !result.text;
      setReadinessSummary(elements, buildReadinessSummary(result));
      setRetryVisibility(elements, false);

      if (!result.text) {
        setStatus(elements, "没有读取到可导出的 Cookie，请确认你已登录闲鱼网页版。");
        setWarnings(elements, buildPopupWarnings(result, true));
        return;
      }

      let copySucceeded = false;
      copySucceeded = await tryWriteClipboard(result.text);

      const statusText = copySucceeded
        ? getSuccessStatus(profile)
        : "已生成文本，请手动复制。";

      setStatus(elements, statusText);
      setWarnings(elements, buildPopupWarnings(result, copySucceeded));
    } catch (error) {
      const message = error instanceof Error ? error.message : "未知错误";
      setStatus(elements, `导出失败: ${message}`);
      setWarnings(elements, []);
    }
  }

  async function handleCopy(elements) {
    if (!state.currentText) {
      return;
    }

    try {
      const copySucceeded = await tryWriteClipboard(state.currentText);
      if (!copySucceeded) {
        throw new Error("clipboard unavailable");
      }
      setStatus(elements, "已重新复制到剪贴板。");
      setWarnings(elements, buildPopupWarnings(state.currentResult, true));
    } catch {
      setStatus(elements, "复制失败，请手动复制下方内容。");
      setWarnings(elements, buildPopupWarnings(state.currentResult, false));
    }
  }

  async function getActiveTab() {
    const tabs = await chromeApi.tabs.query({
      active: true,
      lastFocusedWindow: true,
    });

    if (!tabs || tabs.length === 0) {
      throw new Error("未找到当前活动标签页");
    }

    return tabs[0];
  }

  async function collectDiagnosticCookies(activeTabUrl) {
    const collected = [];

    for (const spec of exporter.KEY_COOKIE_QUERY_SPECS) {
      const queryUrls = buildQueryUrls(activeTabUrl, spec.queryUrls);
      for (const url of queryUrls) {
        try {
          const cookie = await chromeApi.cookies.get({ url, name: spec.name });
          if (cookie) {
            collected.push(cookie);
            break;
          }
        } catch {
          continue;
        }
      }
    }

    return collected;
  }

  async function collectRuntimeCookies() {
    const cookieBuckets = await Promise.all(
      exporter.RUNTIME_TARGET_URLS.map((url) => chromeApi.cookies.getAll({ url })),
    );

    return cookieBuckets.flat();
  }

  function getActiveProfile() {
    return state.profile === "diagnostic"
      ? exporter.EXPORT_PROFILES.diagnostic
      : exporter.EXPORT_PROFILES.runtime;
  }

  function getSuccessStatus(profile) {
    return profile === exporter.EXPORT_PROFILES.diagnostic
      ? "已复制诊断摘要到剪贴板。"
      : "已复制到剪贴板。";
  }

  function buildQueryUrls(activeTabUrl, queryUrls) {
    const urls = [];
    for (const queryUrl of queryUrls) {
      const candidateUrl = queryUrl === "ACTIVE_TAB_URL" ? activeTabUrl : queryUrl;
      if (typeof candidateUrl !== "string" || !candidateUrl.trim()) {
        continue;
      }
      if (!isCookieQueryableUrl(candidateUrl)) {
        continue;
      }
      if (!urls.includes(candidateUrl)) {
        urls.push(candidateUrl);
      }
    }
    return urls;
  }

  async function tryWriteClipboard(text) {
    if (!clipboard || typeof clipboard.writeText !== "function") {
      return false;
    }

    try {
      await clipboard.writeText(text);
      return true;
    } catch {
      return false;
    }
  }

  function isCookieQueryableUrl(url) {
    try {
      const parsedUrl = new URL(url);
      return parsedUrl.protocol === "http:" || parsedUrl.protocol === "https:";
    } catch {
      return false;
    }
  }

  function setStatus(elements, message) {
    elements.status.textContent = message;
  }

  function setWarnings(elements, warnings) {
    elements.warnings.replaceChildren();
    for (const warning of warnings) {
      const item = document.createElement("li");
      item.textContent = warning;
      item.className = getWarningClassName(warning);
      elements.warnings.appendChild(item);
    }
    elements.warnings.hidden = warnings.length === 0;
  }

  function getWarningClassName(warning) {
    if (typeof warning === "string" && warning.startsWith("可选补充项缺失：")) {
      return "warning-item warning-item--info";
    }
    return "warning-item warning-item--warning";
  }

  function setReadinessSummary(elements, message) {
    elements.readinessSummary.textContent = message;
  }

  function updateModeLabels(elements) {
    const profile = getActiveProfile();
    elements.modeBadge.textContent = profile === exporter.EXPORT_PROFILES.diagnostic
      ? "诊断摘要"
      : "默认推荐：运行时恢复包";
    elements.modeBadge.hidden = true;
    elements.copyButton.textContent = "复制";
    elements.toggleExportModeButton.textContent = profile === exporter.EXPORT_PROFILES.diagnostic
      ? "返回默认导出"
      : "诊断";
    elements.retryWithoutValidationButton.textContent = "忽略页面校验后重试";
    elements.retryWithoutValidationButton.disabled = false;
  }

  function setRetryVisibility(elements, isVisible) {
    elements.retryWithoutValidationButton.hidden = !isVisible;
  }

  function buildPopupWarnings(result, copySucceeded) {
    return exporter.buildWarningMessages({
      ...result.warningContext,
      copySucceeded,
      shouldWarnRecommendedExtras: state.profile === exporter.EXPORT_PROFILES.runtime,
    });
  }

  function buildReadinessSummary(result) {
    const ingressText = result.readiness.hasFeishuIngressKeys
      ? "飞书入口识别：已满足"
      : "飞书入口识别：未满足";
    const runtimeText = result.readiness.hasRuntimeCoreKeys
      ? "运行时关键项：完整"
      : `运行时关键项：缺少 ${result.warningContext.missingRuntimeCoreKeys.join(", ")}`;
    const extrasText = result.readiness.recommendedExtrasPresent
      ? "推荐补充项：完整"
      : `推荐补充项：缺少 ${result.warningContext.missingRecommendedExtras.join(", ")}`;

    return `${ingressText}；${runtimeText}；${extrasText}`;
  }

  return {
    initialize,
    runExport,
    handleCopy,
    state,
  };
}

function bootstrapPopup() {
  const app = createPopupApp();
  document.addEventListener("DOMContentLoaded", () => {
    void app.initialize();
  });
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    createPopupApp,
  };
}

if (
  typeof document !== "undefined"
  && typeof chrome !== "undefined"
  && typeof navigator !== "undefined"
) {
  bootstrapPopup();
}
