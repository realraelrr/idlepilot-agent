# IdlePilot Agent

面向二手交易场景的 AI 运营 agent，用于客服回复、专家路由、议价和运行时恢复。

[English README](README.md)

IdlePilot 用 LLM 意图路由、会话记忆、专门的回复 agent 和飞书运维控制面，让交易会话在账号 Cookie 失效等运行时问题发生后也能恢复。

## 契约

- 将买家消息路由到 `price`、`tech` 或 `default` 专家流程。
- 保留近期会话历史作为模型上下文。
- 使用兼容 OpenAI `responses` 的模型端点。
- 把 Cookie 失效视为可恢复运行状态。
- 通过白名单飞书私聊接收替换 Cookie。
- 浏览器 Cookie 提取仅作为本地运维工具，不作为常驻服务。

## 结构

```text
main.py                         主服务循环和恢复状态
XianyuAgent.py                  消息编排和专家路由
XianyuApis.py                   交易平台 API 适配
context_manager.py              会话记忆
services/feishu_control_plane.py 飞书运维控制面
tools/chrome-cookie-exporter/   本地 Chrome Cookie 提取工具
tests/                          回归测试
```

## 配置

复制 `.env.example` 为 `.env`，并填写本地值：

```env
API_KEY=
COOKIES_STR=
COOKIE_FILE_PATH=data/cookies.txt
MODEL_BASE_URL=
MODEL_NAME=
MODEL_REASONING_EFFORT=
CLASSIFY_MODEL_REASONING_EFFORT=
PRICE_MODEL_REASONING_EFFORT=
TECH_MODEL_REASONING_EFFORT=
DEFAULT_MODEL_REASONING_EFFORT=
TECH_ENABLE_SEARCH=False
TOGGLE_KEYWORDS=.
SIMULATE_HUMAN_TYPING=False
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_ADMIN_OPEN_IDS=
FEISHU_CALLBACK_HOST=127.0.0.1
FEISHU_CALLBACK_PORT=8100
FEISHU_CALLBACK_PATH=/feishu/events
FEISHU_CALLBACK_MODE=token
FEISHU_VERIFICATION_TOKEN=
FEISHU_ENCRYPT_KEY=
FEISHU_STALE_LOCK_SECONDS=300
```

不要提交 `.env`、真实 Cookie、回调 URL、运维 open_id、运行状态或 agent 计划文件。

## 运行

安装依赖：

```bash
pip install -r requirements.txt
```

创建本地 prompt 文件：

```bash
cp prompts/classify_prompt_example.txt prompts/classify_prompt.txt
cp prompts/price_prompt_example.txt prompts/price_prompt.txt
cp prompts/tech_prompt_example.txt prompts/tech_prompt.txt
cp prompts/default_prompt_example.txt prompts/default_prompt.txt
```

运行主 agent：

```bash
python main.py
```

运行飞书控制面：

```bash
python -m services.feishu_control_plane
```

Docker Compose：

```bash
docker compose up -d --build --remove-orphans xianyu-main feishu-control-plane
docker compose logs -f xianyu-main
docker compose logs -f feishu-control-plane
```

## 恢复

Cookie 失效时，主进程会把运行状态写到 `data/` 并等待有效替换。飞书控制面会通知白名单运维人员，并通过私聊接收完整 Cookie 文本。校验成功后状态进入 `recovered`；校验失败时保留当前 episode，继续等待下一次替换。

`tools/chrome-cookie-exporter/` 可用于本地浏览器 Cookie 提取。旧的常驻浏览器 sidecar 服务已移除。

## 验证

```bash
python -m unittest discover -s tests
```

预期结果：

```text
Ran 48 tests
OK
```

## 范围

这个仓库用于受控运营和实验。连接真实账号前，应先确认目标平台条款、使用保守 prompt，并保留人工接管路径。
