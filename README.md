# IdlePilot Agent

AI operations agent for second-hand marketplace customer service, expert
routing, bargaining, and runtime recovery.

[中文 README](README.zh-CN.md)

IdlePilot keeps marketplace conversations moving with LLM-backed intent routing,
conversation memory, specialized reply agents, and a Feishu operator control
plane for cookie recovery.

This is a continued-development version based on
[shaxiu/XianyuAutoAgent](https://github.com/shaxiu/XianyuAutoAgent).

## Contract

- Route buyer messages through `price`, `tech`, or `default` expert flows.
- Keep recent conversation history as model context.
- Use OpenAI-compatible `responses` model endpoints.
- Treat expired cookies as recoverable runtime state.
- Accept replacement cookies through allowlisted Feishu private chats.
- Keep browser cookie extraction as a local operator helper, not a long-running
  service.

## Layout

```text
main.py                         main service loop and recovery state
XianyuAgent.py                  message orchestration and expert routing
XianyuApis.py                   marketplace API adapter
context_manager.py              conversation memory
services/feishu_control_plane.py Feishu operator control plane
tools/chrome-cookie-exporter/   local Chrome cookie extraction helper
tests/                          regression tests
```

## Configure

Copy `.env.example` to `.env` and fill the local values:

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

Do not commit `.env`, live cookies, callback URLs, operator IDs, runtime state,
or agent planning files.

## Run

Install dependencies:

```bash
pip install -r requirements.txt
```

Create local prompt files:

```bash
cp prompts/classify_prompt_example.txt prompts/classify_prompt.txt
cp prompts/price_prompt_example.txt prompts/price_prompt.txt
cp prompts/tech_prompt_example.txt prompts/tech_prompt.txt
cp prompts/default_prompt_example.txt prompts/default_prompt.txt
```

Run the agent:

```bash
python main.py
```

Run the Feishu control plane:

```bash
python -m services.feishu_control_plane
```

Docker Compose:

```bash
docker compose up -d --build --remove-orphans xianyu-main feishu-control-plane
docker compose logs -f xianyu-main
docker compose logs -f feishu-control-plane
```

## Recovery

When cookies expire, the main process writes runtime status under `data/` and
waits for a valid replacement. The Feishu control plane notifies allowlisted
operators and accepts full cookie text through private chat. A validated cookie
returns the agent to `recovered`; a failed validation keeps the episode open for
the next replacement.

`tools/chrome-cookie-exporter/` is available for local browser-side extraction.
The legacy long-running browser sidecar service has been removed.

## Verify

```bash
python -m unittest discover -s tests
```

Expected result:

```text
Ran 48 tests
OK
```

## Scope

This repository is for controlled operational use and experimentation. Review
the target marketplace's terms, keep conservative prompts, and keep manual
takeover available before connecting a live account.
