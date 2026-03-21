import importlib
import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock


class _DummyLogger:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


class FakeResponsesAPI:
    def __init__(self):
        self.calls = []
        self.response = SimpleNamespace(output_text="responses reply")

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeChatCompletionsAPI:
    def __init__(self):
        self.calls = []
        self.response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="chat reply"))]
        )

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self):
        self.responses = FakeResponsesAPI()
        self.chat = SimpleNamespace(completions=FakeChatCompletionsAPI())


def load_agent_module():
    sys.modules.pop("XianyuAgent", None)

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = object

    fake_loguru = types.ModuleType("loguru")
    fake_loguru.logger = _DummyLogger()

    with mock.patch.dict(
        sys.modules,
        {
            "openai": fake_openai,
            "loguru": fake_loguru,
        },
    ):
        return importlib.import_module("XianyuAgent")


class XianyuAgentRequestTests(unittest.TestCase):
    def setUp(self):
        self.module = load_agent_module()
        self.client = FakeClient()

    def test_responses_mode_uses_agent_specific_reasoning_effort(self):
        env = {
            "MODEL_NAME": "gpt-5.4",
            "MODEL_REASONING_EFFORT": "low",
            "PRICE_MODEL_REASONING_EFFORT": "xhigh",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            agent = self.module.PriceAgent(self.client, "price prompt", lambda text: text)
            reply = agent.generate("最低多少", "二手耳机", "assistant: 在的", bargain_count=2)

        self.assertEqual(reply, "responses reply")
        self.assertEqual(len(self.client.responses.calls), 1)
        request = self.client.responses.calls[0]
        self.assertEqual(request["model"], "gpt-5.4")
        self.assertEqual(request["reasoning"], {"effort": "xhigh"})
        self.assertIn("【商品信息】二手耳机", request["instructions"])
        self.assertIn("price prompt", request["instructions"])
        self.assertEqual(request["input"], "最低多少")

    def test_responses_mode_falls_back_to_global_reasoning_effort(self):
        env = {
            "MODEL_NAME": "gpt-5.4",
            "MODEL_REASONING_EFFORT": "medium",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            agent = self.module.DefaultAgent(self.client, "default prompt", lambda text: text)
            agent.generate("还在吗", "一台相机", "assistant: 在")

        request = self.client.responses.calls[0]
        self.assertEqual(request["reasoning"], {"effort": "medium"})

    def test_classify_agent_uses_responses_api(self):
        env = {
            "MODEL_NAME": "gpt-5.4",
            "CLASSIFY_MODEL_REASONING_EFFORT": "high",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            agent = self.module.ClassifyAgent(self.client, "classify prompt", lambda text: text)
            reply = agent.generate(user_msg="支持刀吗", item_desc="显示器", context="assistant: 在")

        self.assertEqual(reply, "responses reply")
        request = self.client.responses.calls[0]
        self.assertEqual(request["reasoning"], {"effort": "high"})
        self.assertEqual(request["model"], "gpt-5.4")

    def test_tech_agent_disables_search_by_default(self):
        env = {
            "MODEL_NAME": "gpt-5.4",
            "TECH_MODEL_REASONING_EFFORT": "high",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            agent = self.module.TechAgent(self.client, "tech prompt", lambda text: text)
            agent.generate("参数是什么", "网卡", "assistant: 在", bargain_count=0)

        request = self.client.responses.calls[0]
        self.assertEqual(request["reasoning"], {"effort": "high"})
        self.assertNotIn("extra_body", request)

    def test_tech_agent_can_opt_in_search(self):
        env = {
            "MODEL_NAME": "gpt-5.4",
            "TECH_MODEL_REASONING_EFFORT": "high",
            "TECH_ENABLE_SEARCH": "true",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            agent = self.module.TechAgent(self.client, "tech prompt", lambda text: text)
            agent.generate("参数是什么", "网卡", "assistant: 在", bargain_count=0)

        request = self.client.responses.calls[0]
        self.assertEqual(request["extra_body"], {"enable_search": True})


if __name__ == "__main__":
    unittest.main()
