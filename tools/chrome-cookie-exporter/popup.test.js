const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const { createPopupApp } = require("./popup.js");
const exporter = require("./exporter.js");

const popupHtml = fs.readFileSync(path.join(__dirname, "popup.html"), "utf8");
const popupCss = fs.readFileSync(path.join(__dirname, "popup.css"), "utf8");

function createFakeElement() {
  return {
    textContent: "",
    value: "",
    disabled: false,
    hidden: false,
    className: "",
    children: [],
    _listeners: {},
    addEventListener(type, handler) {
      this._listeners[type] = handler;
    },
    async click() {
      if (this._listeners.click) {
        return this._listeners.click();
      }
    },
    replaceChildren() {
      this.children = [];
    },
    appendChild(node) {
      this.children.push(node);
    },
  };
}

function createFakeDocument() {
  const elements = {
    status: createFakeElement(),
    readinessSummary: createFakeElement(),
    warnings: createFakeElement(),
    cookieOutput: createFakeElement(),
    modeBadge: createFakeElement(),
    copyButton: createFakeElement(),
    toggleExportModeButton: createFakeElement(),
    retryWithoutValidationButton: createFakeElement(),
  };

  return {
    elements,
    getElementById(id) {
      return elements[id] || null;
    },
    createElement() {
      return createFakeElement();
    },
  };
}

function createChromeStub({
  activeTabUrl = "https://www.goofish.com/im",
  cookieByUrlAndName = {},
  fullCookieBuckets = {},
} = {}) {
  const calls = {
    tabsQuery: 0,
    cookiesGet: [],
    cookiesGetAll: [],
  };

  const chromeApi = {
    tabs: {
      async query() {
        calls.tabsQuery += 1;
        return [{ url: activeTabUrl }];
      },
    },
    cookies: {
      async get(details) {
        calls.cookiesGet.push(details);
        return cookieByUrlAndName[`${details.url}|${details.name}`];
      },
      async getAll(details) {
        calls.cookiesGetAll.push(details);
        return fullCookieBuckets[details.url] || fullCookieBuckets[details.domain] || [];
      },
    },
  };

  return { chromeApi, calls };
}

function createClipboardStub({ fail = false } = {}) {
  const writes = [];

  return {
    writes,
    async writeText(value) {
      writes.push(value);
      if (fail) {
        throw new Error("clipboard rejected");
      }
    },
  };
}

function getWarningTexts(document) {
  return document.elements.warnings.children.map((node) => node.textContent);
}

test("popup markup documents the runtime bundle as the default recovery path", () => {
  assert.doesNotMatch(popupHtml, /当前导出配置/u);
  assert.doesNotMatch(popupHtml, /警告与补充提示/u);
  assert.match(popupHtml, /id="modeBadge"/u);
  assert.match(popupHtml, /id="status"/u);
  assert.match(popupHtml, /id="readinessSummary"/u);
  assert.match(popupHtml, /id="warnings"/u);
  assert.match(popupHtml, /id="cookieOutput"/u);
  assert.match(popupHtml, /id="copyButton"/u);
  assert.match(popupHtml, /id="toggleExportModeButton"/u);
  assert.match(popupHtml, /id="retryWithoutValidationButton"/u);
  assert.match(popupHtml, />复制</u);
  assert.match(popupHtml, />诊断</u);
});

test("popup styles keep warnings visually distinct and export text selectable", () => {
  assert.doesNotMatch(popupCss, /\.warnings-panel/u);
  assert.match(popupCss, /\.cookie-output/u);
  assert.match(popupCss, /user-select:\s*text/u);
  assert.match(popupCss, /\.button--text/u);
  assert.match(popupCss, /background:\s*transparent/u);
  assert.match(popupCss, /\.button--retry\[hidden\]/u);
  assert.match(popupCss, /\.warning-item--info/u);
  assert.match(popupCss, /\.warning-item--warning/u);
});

test("popup initialize auto-copies the default runtime bundle on a supported page", async () => {
  const document = createFakeDocument();
  const { chromeApi, calls } = createChromeStub({
    fullCookieBuckets: {
      "https://h5api.m.goofish.com/": [
        { name: "_m_h5_tk", value: "token_123" },
        { name: "cookie2", value: "cookie2-from-h5api" },
        { name: "unb", value: "unb-from-h5api" },
      ],
      "https://www.goofish.com/": [
        { name: "XSRF-TOKEN", value: "xsrf-www" },
        { name: "x5sec", value: "x5-www" },
        { name: "cookie2", value: "cookie2-shadowed" },
      ],
      "https://passport.goofish.com/": [
        { name: "cna", value: "cna-passport" },
        { name: "unb", value: "unb-shadowed" },
      ],
    },
  });
  const clipboard = createClipboardStub();

  const app = createPopupApp({ document, chromeApi, clipboard, exporter });
  await app.initialize();

  assert.equal(app.state.profile, "runtime");
  assert.equal(document.elements.status.textContent, "已复制到剪贴板。");
  assert.equal(
    document.elements.cookieOutput.value,
    "_m_h5_tk=token_123; cookie2=cookie2-from-h5api; unb=unb-from-h5api; XSRF-TOKEN=xsrf-www; x5sec=x5-www; cna=cna-passport",
  );
  assert.deepEqual(clipboard.writes, [
    "_m_h5_tk=token_123; cookie2=cookie2-from-h5api; unb=unb-from-h5api; XSRF-TOKEN=xsrf-www; x5sec=x5-www; cna=cna-passport",
  ]);
  assert.equal(document.elements.copyButton.disabled, false);
  assert.equal(document.elements.copyButton.textContent, "复制");
  assert.equal(document.elements.modeBadge.textContent, "默认推荐：运行时恢复包");
  assert.equal(document.elements.toggleExportModeButton.textContent, "诊断");
  assert.equal(document.elements.retryWithoutValidationButton.textContent, "忽略页面校验后重试");
  assert.equal(document.elements.retryWithoutValidationButton.hidden, true);
  assert.equal(
    document.elements.readinessSummary.textContent,
    "飞书入口识别：已满足；运行时关键项：完整；推荐补充项：缺少 tfstk, _m_h5_tk_enc",
  );
  assert.equal(calls.tabsQuery, 1);
  assert.deepEqual(calls.cookiesGet, []);
  assert.deepEqual(calls.cookiesGetAll, [
    { url: "https://h5api.m.goofish.com/" },
    { url: "https://www.goofish.com/" },
    { url: "https://passport.goofish.com/" },
    { url: "https://www.taobao.com/" },
  ]);
  assert.deepEqual(getWarningTexts(document), [
    "可选补充项缺失：tfstk, _m_h5_tk_enc",
  ]);
  assert.deepEqual(
    document.elements.warnings.children.map((node) => node.className),
    ["warning-item warning-item--info"],
  );
});

test("popup copy button re-copies the current export text", async () => {
  const document = createFakeDocument();
  const { chromeApi } = createChromeStub({
    fullCookieBuckets: {
      "https://h5api.m.goofish.com/": [
        { name: "_m_h5_tk", value: "token_123" },
        { name: "cookie2", value: "c2" },
      ],
      "https://www.goofish.com/": [
        { name: "unb", value: "u1" },
      ],
      "https://passport.goofish.com/": [
        { name: "cna", value: "cna1" },
      ],
    },
  });
  const clipboard = createClipboardStub();

  const app = createPopupApp({ document, chromeApi, clipboard, exporter });
  await app.initialize();
  await document.elements.copyButton.click();

  assert.equal(document.elements.status.textContent, "已重新复制到剪贴板。");
  assert.equal(document.elements.retryWithoutValidationButton.hidden, true);
  assert.deepEqual(clipboard.writes, [
    "_m_h5_tk=token_123; cookie2=c2; unb=u1; cna=cna1",
    "_m_h5_tk=token_123; cookie2=c2; unb=u1; cna=cna1",
  ]);
  assert.equal(
    document.elements.readinessSummary.textContent,
    "飞书入口识别：已满足；运行时关键项：完整；推荐补充项：缺少 XSRF-TOKEN, x5sec, tfstk, _m_h5_tk_enc",
  );
  assert.deepEqual(getWarningTexts(document), [
    "可选补充项缺失：XSRF-TOKEN, x5sec, tfstk, _m_h5_tk_enc",
  ]);
  assert.deepEqual(
    document.elements.warnings.children.map((node) => node.className),
    ["warning-item warning-item--info"],
  );
});

test("popup shows copy failure warning while keeping the exported text", async () => {
  const document = createFakeDocument();
  const { chromeApi } = createChromeStub({
    fullCookieBuckets: {
      "https://h5api.m.goofish.com/": [
        { name: "_m_h5_tk", value: "token_123" },
        { name: "cookie2", value: "c2" },
      ],
      "https://www.goofish.com/": [
        { name: "unb", value: "u1" },
      ],
      "https://passport.goofish.com/": [
        { name: "cna", value: "cna1" },
      ],
    },
  });
  const clipboard = createClipboardStub({ fail: true });

  const app = createPopupApp({ document, chromeApi, clipboard, exporter });
  await app.initialize();

  assert.equal(document.elements.status.textContent, "已生成文本，请手动复制。");
  assert.equal(document.elements.cookieOutput.value, "_m_h5_tk=token_123; cookie2=c2; unb=u1; cna=cna1");
  assert.equal(
    document.elements.readinessSummary.textContent,
    "飞书入口识别：已满足；运行时关键项：完整；推荐补充项：缺少 XSRF-TOKEN, x5sec, tfstk, _m_h5_tk_enc",
  );
  assert.deepEqual(getWarningTexts(document), [
    "可选补充项缺失：XSRF-TOKEN, x5sec, tfstk, _m_h5_tk_enc",
    "已生成文本，但自动复制失败，请手动复制下方内容。",
  ]);
  assert.deepEqual(
    document.elements.warnings.children.map((node) => node.className),
    ["warning-item warning-item--info", "warning-item warning-item--warning"],
  );
});

test("popup still renders export text when clipboard API is unavailable", async () => {
  const document = createFakeDocument();
  const { chromeApi } = createChromeStub({
    fullCookieBuckets: {
      "https://h5api.m.goofish.com/": [
        { name: "_m_h5_tk", value: "token_123" },
        { name: "cookie2", value: "c2" },
      ],
      "https://www.goofish.com/": [
        { name: "unb", value: "u1" },
      ],
      "https://passport.goofish.com/": [
        { name: "cna", value: "cna1" },
      ],
    },
  });

  const app = createPopupApp({ document, chromeApi, clipboard: null, exporter });
  await app.initialize();

  assert.equal(document.elements.status.textContent, "已生成文本，请手动复制。");
  assert.equal(document.elements.cookieOutput.value, "_m_h5_tk=token_123; cookie2=c2; unb=u1; cna=cna1");
  assert.equal(
    document.elements.readinessSummary.textContent,
    "飞书入口识别：已满足；运行时关键项：完整；推荐补充项：缺少 XSRF-TOKEN, x5sec, tfstk, _m_h5_tk_enc",
  );
  assert.deepEqual(getWarningTexts(document), [
    "可选补充项缺失：XSRF-TOKEN, x5sec, tfstk, _m_h5_tk_enc",
    "已生成文本，但自动复制失败，请手动复制下方内容。",
  ]);
  assert.deepEqual(
    document.elements.warnings.children.map((node) => node.className),
    ["warning-item warning-item--info", "warning-item warning-item--warning"],
  );
});

test("popup blocks unsupported pages until retry without validation is clicked", async () => {
  const document = createFakeDocument();
  const { chromeApi, calls } = createChromeStub({
    activeTabUrl: "https://example.com",
    fullCookieBuckets: {
      "https://h5api.m.goofish.com/": [
        { name: "_m_h5_tk", value: "token_123" },
        { name: "cookie2", value: "c2" },
      ],
      "https://www.goofish.com/": [
        { name: "unb", value: "u1" },
      ],
      "https://passport.goofish.com/": [
        { name: "cna", value: "cna1" },
      ],
    },
  });
  const clipboard = createClipboardStub();

  const app = createPopupApp({ document, chromeApi, clipboard, exporter });
  await app.initialize();

  assert.equal(document.elements.status.textContent, "请先打开闲鱼相关页面。");
  assert.equal(calls.cookiesGet.length, 0);
  assert.equal(calls.cookiesGetAll.length, 0);
  assert.equal(document.elements.retryWithoutValidationButton.hidden, false);

  await document.elements.retryWithoutValidationButton.click();

  assert.equal(document.elements.status.textContent, "已复制到剪贴板。");
  assert.equal(calls.cookiesGetAll.length, 4);
  assert.equal(document.elements.retryWithoutValidationButton.hidden, true);
});

test("popup retry without validation falls back when active tab URL cannot be queried for cookies", async () => {
  const document = createFakeDocument();
  const { chromeApi, calls } = createChromeStub({
    activeTabUrl: "chrome://newtab/",
    fullCookieBuckets: {
      "https://h5api.m.goofish.com/": [
        { name: "_m_h5_tk", value: "token_123" },
        { name: "cookie2", value: "c2" },
      ],
      "https://www.goofish.com/": [
        { name: "unb", value: "u1" },
      ],
      "https://passport.goofish.com/": [
        { name: "cna", value: "cna1" },
      ],
    },
  });
  const clipboard = createClipboardStub();

  const app = createPopupApp({ document, chromeApi, clipboard, exporter });
  await app.initialize();

  assert.equal(document.elements.status.textContent, "请先打开闲鱼相关页面。");
  assert.equal(document.elements.retryWithoutValidationButton.hidden, false);

  await document.elements.retryWithoutValidationButton.click();

  assert.equal(document.elements.status.textContent, "已复制到剪贴板。");
  assert.equal(document.elements.cookieOutput.value, "_m_h5_tk=token_123; cookie2=c2; unb=u1; cna=cna1");
  assert.deepEqual(calls.cookiesGetAll, [
    { url: "https://h5api.m.goofish.com/" },
    { url: "https://www.goofish.com/" },
    { url: "https://passport.goofish.com/" },
    { url: "https://www.taobao.com/" },
  ]);
});

test("popup profile toggle switches to the diagnostic summary mode", async () => {
  const document = createFakeDocument();
  const { chromeApi, calls } = createChromeStub({
    cookieByUrlAndName: {
      "https://www.goofish.com/im|unb": { name: "unb", value: "u1" },
      "https://h5api.m.goofish.com/|_m_h5_tk": { name: "_m_h5_tk", value: "token_123" },
      "https://passport.goofish.com/|cookie2": { name: "cookie2", value: "c2" },
      "https://passport.goofish.com/|cna": { name: "cna", value: "cna1" },
      "https://passport.goofish.com/|XSRF-TOKEN": { name: "XSRF-TOKEN", value: "xsrf" },
      "https://www.goofish.com/|x5sec": { name: "x5sec", value: "x5" },
    },
  });
  const clipboard = createClipboardStub();

  const app = createPopupApp({ document, chromeApi, clipboard, exporter });
  await app.initialize();
  await document.elements.toggleExportModeButton.click();

  assert.equal(document.elements.modeBadge.textContent, "诊断摘要");
  assert.equal(document.elements.toggleExportModeButton.textContent, "返回默认导出");
  assert.equal(document.elements.status.textContent, "已复制诊断摘要到剪贴板。");
  assert.equal(
    document.elements.readinessSummary.textContent,
    "飞书入口识别：已满足；运行时关键项：完整；推荐补充项：缺少 tfstk, _m_h5_tk_enc",
  );
  assert.equal(document.elements.cookieOutput.value, "unb=u1; _m_h5_tk=token_123; cookie2=c2; cna=cna1; XSRF-TOKEN=xsrf; x5sec=x5");
  assert.equal(calls.cookiesGetAll.length, 4);
  assert.ok(calls.cookiesGet.some((call) => call.name === "_m_h5_tk" && call.url === "https://h5api.m.goofish.com/"));
});

test("popup can show Feishu ingress satisfied while runtime readiness still warns", async () => {
  const document = createFakeDocument();
  const { chromeApi } = createChromeStub({
    fullCookieBuckets: {
      "https://h5api.m.goofish.com/": [
        { name: "_m_h5_tk", value: "token_123" },
        { name: "cookie2", value: "c2" },
      ],
      "https://www.goofish.com/": [
        { name: "unb", value: "u1" },
      ],
      "https://passport.goofish.com/": [
        { name: "cna", value: "cna1" },
      ],
    },
  });
  const clipboard = createClipboardStub();

  const app = createPopupApp({ document, chromeApi, clipboard, exporter });
  await app.initialize();

  assert.equal(document.elements.status.textContent, "已复制到剪贴板。");
  assert.equal(
    document.elements.readinessSummary.textContent,
    "飞书入口识别：已满足；运行时关键项：完整；推荐补充项：缺少 XSRF-TOKEN, x5sec, tfstk, _m_h5_tk_enc",
  );
  assert.deepEqual(getWarningTexts(document), [
    "可选补充项缺失：XSRF-TOKEN, x5sec, tfstk, _m_h5_tk_enc",
  ]);
  assert.deepEqual(
    document.elements.warnings.children.map((node) => node.className),
    ["warning-item warning-item--info"],
  );
});

test("popup runtime bundle falls back to taobao cookies for cookie2 and cna", async () => {
  const document = createFakeDocument();
  const { chromeApi, calls } = createChromeStub({
    fullCookieBuckets: {
      "https://h5api.m.goofish.com/": [
        { name: "_m_h5_tk", value: "token_123" },
      ],
      "https://www.goofish.com/": [
        { name: "unb", value: "u1" },
      ],
      "https://passport.goofish.com/": [],
      "https://www.taobao.com/": [
        { name: "cookie2", value: "c2-taobao" },
        { name: "cna", value: "cna-taobao" },
      ],
    },
  });
  const clipboard = createClipboardStub();

  const app = createPopupApp({ document, chromeApi, clipboard, exporter });
  await app.initialize();

  assert.equal(document.elements.cookieOutput.value, "_m_h5_tk=token_123; unb=u1; cookie2=c2-taobao; cna=cna-taobao");
  assert.equal(document.elements.status.textContent, "已复制到剪贴板。");
  assert.equal(
    document.elements.readinessSummary.textContent,
    "飞书入口识别：已满足；运行时关键项：完整；推荐补充项：缺少 XSRF-TOKEN, x5sec, tfstk, _m_h5_tk_enc",
  );
  assert.deepEqual(calls.cookiesGetAll, [
    { url: "https://h5api.m.goofish.com/" },
    { url: "https://www.goofish.com/" },
    { url: "https://passport.goofish.com/" },
    { url: "https://www.taobao.com/" },
  ]);
  assert.deepEqual(getWarningTexts(document), [
    "可选补充项缺失：XSRF-TOKEN, x5sec, tfstk, _m_h5_tk_enc",
  ]);
  assert.deepEqual(
    document.elements.warnings.children.map((node) => node.className),
    ["warning-item warning-item--info"],
  );
});

test("popup initialize fails fast when required DOM ids are missing", async () => {
  const document = createFakeDocument();
  delete document.elements.copyButton;

  const { chromeApi } = createChromeStub();
  const clipboard = createClipboardStub();
  const app = createPopupApp({ document, chromeApi, clipboard, exporter });

  await assert.rejects(
    () => app.initialize(),
    /缺少必要的弹窗节点: copyButton/u,
  );
});
