import json
import os
import tempfile
import unittest
from collections import deque
from unittest import mock

import requests

from browser_refresh.cookie_bundle import (
    RECOMMENDED_EXTRA_KEYS,
    RUNTIME_CORE_KEYS,
    RuntimeCookieBundle,
    build_runtime_cookie_bundle,
)
from browser_refresh.runtime_state import RuntimeState, read_runtime_state


class RuntimeCookieBundleTests(unittest.TestCase):
    def test_build_runtime_cookie_bundle_serializes_first_seen_deduped_runtime_cookie_order(self):
        cookies = [
            {"name": "unb", "value": "first-unb", "domain": ".goofish.com"},
            {"name": "cookie2", "value": "cookie2-value", "domain": ".taobao.com"},
            {"name": "unb", "value": "second-unb-ignored", "domain": ".goofish.com"},
            {"name": "cna", "value": "cna-value", "domain": ".taobao.com"},
            {"name": "_m_h5_tk", "value": "token-value", "domain": ".goofish.com"},
            {"name": "x5sec", "value": "x5sec-value", "domain": ".goofish.com"},
        ]

        bundle = build_runtime_cookie_bundle(cookies)

        self.assertIsInstance(bundle, RuntimeCookieBundle)
        self.assertEqual(
            bundle.text,
            "unb=first-unb; cookie2=cookie2-value; cna=cna-value; _m_h5_tk=token-value; x5sec=x5sec-value",
        )
        self.assertEqual(
            [cookie.name for cookie in bundle.cookies],
            ["unb", "cookie2", "cna", "_m_h5_tk", "x5sec"],
        )
        self.assertEqual(bundle.missing_runtime_core_keys, ())
        self.assertEqual(bundle.missing_recommended_keys, ("XSRF-TOKEN", "tfstk", "_m_h5_tk_enc"))
        self.assertTrue(bundle.has_runtime_core_keys)
        self.assertEqual(bundle.runtime_target_urls, tuple(bundle.RUNTIME_TARGET_URLS))
        self.assertIsInstance(bundle.cookies, tuple)
        self.assertIsInstance(bundle.missing_runtime_core_keys, tuple)
        self.assertIsInstance(bundle.missing_recommended_keys, tuple)
        with self.assertRaises(AttributeError):
            bundle.cookies[0].value = "mutated"

    def test_build_runtime_cookie_bundle_reports_missing_recommended_keys_without_blocking_runtime_readiness(self):
        cookies = [
            {"name": "unb", "value": "user-1"},
            {"name": "cookie2", "value": "cookie2-value"},
            {"name": "cna", "value": "cna-value"},
            {"name": "_m_h5_tk", "value": "token-value"},
        ]

        bundle = build_runtime_cookie_bundle(cookies)

        self.assertEqual(bundle.missing_runtime_core_keys, ())
        self.assertEqual(bundle.missing_recommended_keys, tuple(RECOMMENDED_EXTRA_KEYS))
        self.assertTrue(bundle.has_runtime_core_keys)
        self.assertEqual(bundle.runtime_core_keys, tuple(RUNTIME_CORE_KEYS))


class RuntimeStateTests(unittest.TestCase):
    def test_read_runtime_state_returns_empty_inactive_state_when_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tempdir:
            status_path = os.path.join(tempdir, "missing_runtime_status.json")

            state = read_runtime_state(status_path)

        self.assertIsInstance(state, RuntimeState)
        self.assertEqual(state.state, "")
        self.assertEqual(state.episode_id, "")
        self.assertFalse(state.is_recovery_active)

    def test_read_runtime_state_treats_validation_failed_with_episode_id_as_recovery_active(self):
        with tempfile.TemporaryDirectory() as tempdir:
            data_dir = os.path.join(tempdir, "data")
            os.makedirs(data_dir, exist_ok=True)
            status_path = os.path.join(data_dir, "runtime_status.json")
            with open(status_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "state": "validation_failed",
                        "updated_at": "2026-04-03T12:00:00+08:00",
                        "message": "Cookie validation failed",
                        "cookie_invalid_episode_id": "episode-1",
                    },
                    f,
                )

            state = read_runtime_state(status_path)

        self.assertIsInstance(state, RuntimeState)
        self.assertTrue(state.is_recovery_active)
        self.assertEqual(state.episode_id, "episode-1")

    def test_read_runtime_state_reopens_path_each_poll_so_atomic_replace_is_visible(self):
        with tempfile.TemporaryDirectory() as tempdir:
            data_dir = os.path.join(tempdir, "data")
            os.makedirs(data_dir, exist_ok=True)
            status_path = os.path.join(data_dir, "runtime_status.json")
            with open(status_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "state": "waiting_for_cookie",
                        "cookie_invalid_episode_id": "episode-1",
                    },
                    f,
                )

            first = read_runtime_state(status_path)

            replacement_path = os.path.join(data_dir, "runtime_status.tmp")
            with open(replacement_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "state": "recovered",
                        "cookie_invalid_episode_id": "episode-1",
                    },
                    f,
                )
            os.replace(replacement_path, status_path)

            second = read_runtime_state(status_path)

        self.assertEqual(first.state, "waiting_for_cookie")
        self.assertTrue(first.is_recovery_active)
        self.assertEqual(second.state, "recovered")
        self.assertFalse(second.is_recovery_active)


class BrowserSessionTests(unittest.TestCase):
    class _FakeHttpResponse:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class _FakeHttpClient:
        def __init__(self, tab_payloads=None):
            self.tab_payloads = deque(tab_payloads or [])
            self.get_calls = []
            self.put_calls = []

        def get(self, url, timeout=None):
            self.get_calls.append((url, timeout))
            if not self.tab_payloads:
                raise AssertionError(f"unexpected GET {url}")
            return BrowserSessionTests._FakeHttpResponse(self.tab_payloads.popleft())

        def put(self, url, timeout=None):
            self.put_calls.append((url, timeout))
            return BrowserSessionTests._FakeHttpResponse({})

    class _FakeWebSocket:
        def __init__(self, responses):
            self._responses = deque(responses)
            self.sent_messages = []
            self.recv_calls = 0

        def send(self, message):
            self.sent_messages.append(json.loads(message))

        def recv(self, timeout=None):
            self.recv_calls += 1
            if not self._responses:
                raise AssertionError("unexpected websocket recv")
            return json.dumps(self._responses.popleft())

        def close(self):
            return None

    class _TimeoutWebSocket:
        def __init__(self):
            self.sent_messages = []
            self.recv_calls = 0

        def send(self, message):
            self.sent_messages.append(json.loads(message))

        def recv(self, timeout=None):
            self.recv_calls += 1
            raise TimeoutError(f"timed out after {timeout}")

        def close(self):
            return None

    def test_browser_client_refreshes_existing_goofish_tab_before_reading_cookies(self):
        from browser_refresh.browser_client import BrowserSessionClient

        attached_browser = mock.Mock()
        attached_browser.find_target_tab.return_value = {"id": "tab-1", "url": "https://www.goofish.com/im"}

        client = BrowserSessionClient(attached_browser=attached_browser)
        client.prepare_target_page()

        attached_browser.refresh_tab.assert_called_once()
        attached_browser.open_url.assert_not_called()

    def test_browser_client_navigates_im_then_root_when_no_goofish_tab_exists(self):
        from browser_refresh.browser_client import BrowserSessionClient

        attached_browser = mock.Mock()
        attached_browser.find_target_tab.return_value = None
        attached_browser.wait_for_ready_state.side_effect = [False, True]

        client = BrowserSessionClient(attached_browser=attached_browser)
        client.prepare_target_page()

        self.assertEqual(
            attached_browser.open_url.call_args_list,
            [mock.call("https://www.goofish.com/im"), mock.call("https://www.goofish.com/")],
        )

    def test_browser_client_classifies_slider_page_as_needs_human_verification(self):
        from browser_refresh.browser_client import BrowserSessionClient

        attached_browser = mock.Mock()
        attached_browser.inspect_page.return_value = {
            "url": "https://login.goofish.com/challenge",
            "title": "请完成验证",
            "html": "<div>请拖动滑块完成验证</div>",
        }

        client = BrowserSessionClient(attached_browser=attached_browser)

        self.assertEqual(client.classify_page_state(), "needs_human_verification")

    def test_browser_client_classifies_login_page_as_needs_login(self):
        from browser_refresh.browser_client import BrowserSessionClient

        attached_browser = mock.Mock()
        attached_browser.inspect_page.return_value = {
            "url": "https://login.taobao.com/member/login.jhtml",
            "title": "扫码登录",
            "html": "<div>扫码登录</div>",
        }

        client = BrowserSessionClient(attached_browser=attached_browser)

        self.assertEqual(client.classify_page_state(), "needs_login")

    def test_browser_client_classifies_unexpected_page_as_unknown_error(self):
        from browser_refresh.browser_client import BrowserSessionClient

        attached_browser = mock.Mock()
        attached_browser.inspect_page.return_value = {
            "url": "https://www.goofish.com/error",
            "title": "502 Bad Gateway",
            "html": "<html>upstream error</html>",
        }

        client = BrowserSessionClient(attached_browser=attached_browser)

        self.assertEqual(client.classify_page_state(), "unknown_error")

    def test_browser_client_connect_refreshes_existing_tab_over_remote_debugger(self):
        from browser_refresh.browser_client import BrowserSessionClient

        http_client = self._FakeHttpClient(
            tab_payloads=[
                [
                    {
                        "id": "tab-1",
                        "type": "page",
                        "url": "https://www.goofish.com/im",
                        "webSocketDebuggerUrl": "ws://debug/tab-1",
                    }
                ]
            ]
        )
        websocket = self._FakeWebSocket([{"id": 1, "result": {}}])

        client = BrowserSessionClient.connect(
            "http://127.0.0.1:9222",
            http_client=http_client,
            websocket_factory=lambda url: websocket,
        )
        client.prepare_target_page()

        self.assertEqual(http_client.get_calls, [("http://127.0.0.1:9222/json/list", 10)])
        self.assertEqual(websocket.sent_messages[0]["method"], "Page.reload")

    def test_browser_client_connect_reads_page_state_and_cookies_over_remote_debugger(self):
        from browser_refresh.browser_client import BrowserSessionClient

        http_client = self._FakeHttpClient(
            tab_payloads=[
                [
                    {
                        "id": "tab-1",
                        "type": "page",
                        "url": "https://www.goofish.com/im",
                        "webSocketDebuggerUrl": "ws://debug/tab-1",
                    }
                ]
            ]
        )
        websocket = self._FakeWebSocket(
            [
                {
                    "id": 1,
                    "result": {
                        "result": {
                            "value": {
                                "url": "https://www.goofish.com/im",
                                "title": "Goofish",
                                "html": "<html>ok</html>",
                            }
                        }
                    },
                },
                {"id": 2, "result": {"cookies": [{"name": "unb", "value": "u1", "domain": ".goofish.com"}]}},
            ]
        )

        client = BrowserSessionClient.connect(
            "http://127.0.0.1:9222",
            http_client=http_client,
            websocket_factory=lambda url: websocket,
        )

        self.assertEqual(client.classify_page_state(), "ready")
        self.assertEqual(
            client.get_cookies(),
            [{"name": "unb", "value": "u1", "domain": ".goofish.com"}],
        )

    def test_browser_client_connect_raises_timeout_when_cdp_response_deadline_expires(self):
        from browser_refresh.browser_client import BrowserSessionClient

        http_client = self._FakeHttpClient(
            tab_payloads=[
                [
                    {
                        "id": "tab-1",
                        "type": "page",
                        "url": "https://www.goofish.com/im",
                        "webSocketDebuggerUrl": "ws://debug/tab-1",
                    }
                ]
            ]
        )
        websocket = self._TimeoutWebSocket()

        client = BrowserSessionClient.connect(
            "http://127.0.0.1:9222",
            http_client=http_client,
            websocket_factory=lambda url: websocket,
        )

        with self.assertRaisesRegex(RuntimeError, "timed out waiting for CDP response"):
            client.prepare_target_page()


class BrowserSubmitterTests(unittest.TestCase):
    def test_browser_cookie_submitter_posts_to_configured_internal_endpoint(self):
        from browser_refresh.submitter import BrowserCookieSubmitter

        transport = mock.Mock()
        submitter = BrowserCookieSubmitter(
            submit_url="http://feishu-control-plane:8100/internal/browser-cookie-submit",
            shared_secret="browser-secret",
            transport=transport,
        )

        submitter.submit("unb=1; cookie2=2; cna=3; _m_h5_tk=4", "episode-1")

        transport.post.assert_called_once_with(
            "http://feishu-control-plane:8100/internal/browser-cookie-submit",
            headers={"Authorization": "Bearer browser-secret"},
            json={
                "source": "browser-refresh",
                "cookie": "unb=1; cookie2=2; cna=3; _m_h5_tk=4",
                "episode_id": "episode-1",
            },
            timeout=10,
        )


class BrowserAgentTests(unittest.TestCase):
    def test_browser_agent_resubmits_same_episode_after_validation_failed_when_cookie_bundle_changes(self):
        from browser_refresh.agent import BrowserRefreshAgent

        status_reader = mock.Mock(
            side_effect=[
                RuntimeState("waiting_for_cookie", "episode-1", True),
                RuntimeState("validation_failed", "episode-1", True),
            ]
        )
        browser_client = mock.Mock()
        browser_client.prepare_target_page.return_value = None
        browser_client.classify_page_state.side_effect = ["ready", "ready"]
        browser_client.get_cookies.side_effect = [
            [
                {"name": "unb", "value": "u1"},
                {"name": "cookie2", "value": "c2"},
                {"name": "cna", "value": "cna1"},
                {"name": "_m_h5_tk", "value": "token_123"},
            ],
            [
                {"name": "unb", "value": "u2"},
                {"name": "cookie2", "value": "c2"},
                {"name": "cna", "value": "cna1"},
                {"name": "_m_h5_tk", "value": "token_456"},
            ],
        ]
        submitter = mock.Mock()

        agent = BrowserRefreshAgent(status_reader=status_reader, browser_client=browser_client, submitter=submitter)
        agent.run_once()
        agent.run_once()

        self.assertEqual(submitter.submit.call_count, 2)

    def test_browser_agent_does_not_resubmit_same_bundle_twice_in_one_episode(self):
        from browser_refresh.agent import BrowserRefreshAgent

        status_reader = mock.Mock(
            side_effect=[
                RuntimeState("waiting_for_cookie", "episode-1", True),
                RuntimeState("validation_failed", "episode-1", True),
            ]
        )
        browser_client = mock.Mock()
        browser_client.prepare_target_page.return_value = None
        browser_client.classify_page_state.side_effect = ["ready", "ready"]
        browser_client.get_cookies.return_value = [
            {"name": "unb", "value": "u1"},
            {"name": "cookie2", "value": "c2"},
            {"name": "cna", "value": "cna1"},
            {"name": "_m_h5_tk", "value": "token_123"},
        ]
        submitter = mock.Mock()

        agent = BrowserRefreshAgent(status_reader=status_reader, browser_client=browser_client, submitter=submitter)
        agent.run_once()
        agent.run_once()

        submitter.submit.assert_called_once()

    def test_browser_agent_does_not_reprepare_same_episode_while_human_verification_is_pending(self):
        from browser_refresh.agent import BrowserRefreshAgent

        status_reader = mock.Mock(
            side_effect=[
                RuntimeState("waiting_for_cookie", "episode-1", True),
                RuntimeState("validation_failed", "episode-1", True),
            ]
        )
        browser_client = mock.Mock()
        browser_client.classify_page_state.side_effect = [
            "needs_human_verification",
            "needs_human_verification",
        ]
        submitter = mock.Mock()

        agent = BrowserRefreshAgent(status_reader=status_reader, browser_client=browser_client, submitter=submitter)
        agent.run_once()
        agent.run_once()

        browser_client.prepare_target_page.assert_called_once()
        self.assertEqual(browser_client.classify_page_state.call_count, 2)
        submitter.submit.assert_not_called()

    def test_browser_agent_does_not_reprepare_same_episode_while_login_is_pending(self):
        from browser_refresh.agent import BrowserRefreshAgent

        status_reader = mock.Mock(
            side_effect=[
                RuntimeState("waiting_for_cookie", "episode-1", True),
                RuntimeState("validation_failed", "episode-1", True),
            ]
        )
        browser_client = mock.Mock()
        browser_client.classify_page_state.side_effect = ["needs_login", "needs_login"]
        submitter = mock.Mock()

        agent = BrowserRefreshAgent(status_reader=status_reader, browser_client=browser_client, submitter=submitter)
        agent.run_once()
        agent.run_once()

        browser_client.prepare_target_page.assert_called_once()
        self.assertEqual(browser_client.classify_page_state.call_count, 2)
        submitter.submit.assert_not_called()

    def test_browser_agent_does_not_reprepare_same_episode_after_ready_while_validation_continues(self):
        from browser_refresh.agent import BrowserRefreshAgent

        status_reader = mock.Mock(
            side_effect=[
                RuntimeState("waiting_for_cookie", "episode-1", True),
                RuntimeState("validating_new_cookie", "episode-1", True),
            ]
        )
        browser_client = mock.Mock()
        browser_client.classify_page_state.side_effect = ["ready", "ready"]
        browser_client.get_cookies.return_value = [
            {"name": "unb", "value": "u1"},
            {"name": "cookie2", "value": "c2"},
            {"name": "cna", "value": "cna1"},
            {"name": "_m_h5_tk", "value": "token_123"},
        ]
        submitter = mock.Mock()

        agent = BrowserRefreshAgent(status_reader=status_reader, browser_client=browser_client, submitter=submitter)
        agent.run_once()
        agent.run_once()

        browser_client.prepare_target_page.assert_called_once()
        self.assertEqual(browser_client.classify_page_state.call_count, 2)
        submitter.submit.assert_called_once()

    def test_browser_agent_wraps_browser_client_timeouts_as_recoverable(self):
        from browser_refresh.agent import BrowserRefreshAgent, BrowserRefreshRecoverableError

        status_reader = mock.Mock(return_value=RuntimeState("waiting_for_cookie", "episode-1", True))
        browser_client = mock.Mock()
        browser_client.prepare_target_page.side_effect = RuntimeError("timed out waiting for CDP response")
        submitter = mock.Mock()

        agent = BrowserRefreshAgent(status_reader=status_reader, browser_client=browser_client, submitter=submitter)

        with self.assertRaisesRegex(BrowserRefreshRecoverableError, "browser client"):
            agent.run_once()

    def test_browser_agent_wraps_browser_transport_errors_as_recoverable(self):
        from browser_refresh.agent import BrowserRefreshAgent, BrowserRefreshRecoverableError

        status_reader = mock.Mock(return_value=RuntimeState("waiting_for_cookie", "episode-1", True))
        browser_client = mock.Mock()
        browser_client.prepare_target_page.side_effect = requests.ConnectionError("debugger offline")
        submitter = mock.Mock()

        agent = BrowserRefreshAgent(status_reader=status_reader, browser_client=browser_client, submitter=submitter)

        with self.assertRaisesRegex(BrowserRefreshRecoverableError, "browser client"):
            agent.run_once()

    def test_browser_agent_wraps_submit_conflicts_as_recoverable(self):
        from browser_refresh.agent import BrowserRefreshAgent, BrowserRefreshRecoverableError

        status_reader = mock.Mock(return_value=RuntimeState("waiting_for_cookie", "episode-1", True))
        browser_client = mock.Mock()
        browser_client.classify_page_state.return_value = "ready"
        browser_client.get_cookies.return_value = [
            {"name": "unb", "value": "u1"},
            {"name": "cookie2", "value": "c2"},
            {"name": "cna", "value": "cna1"},
            {"name": "_m_h5_tk", "value": "token_123"},
        ]
        response = mock.Mock(status_code=409)
        submitter = mock.Mock()
        submitter.submit.side_effect = requests.HTTPError("conflict", response=response)

        agent = BrowserRefreshAgent(status_reader=status_reader, browser_client=browser_client, submitter=submitter)

        with self.assertRaisesRegex(BrowserRefreshRecoverableError, "submit"):
            agent.run_once()


class EntrypointTests(unittest.TestCase):
    def test_run_agent_iteration_survives_browser_transport_failures_from_real_agent(self):
        from browser_refresh.agent import BrowserRefreshAgent
        from browser_refresh.entrypoint import run_agent_iteration

        status_reader = mock.Mock(
            side_effect=[
                RuntimeState("waiting_for_cookie", "episode-1", True),
                RuntimeState("waiting_for_cookie", "episode-1", True),
            ]
        )
        browser_client = mock.Mock()
        browser_client.prepare_target_page.side_effect = [
            requests.ConnectionError("debugger offline"),
            None,
        ]
        browser_client.classify_page_state.return_value = "needs_login"
        submitter = mock.Mock()
        logger = mock.Mock()

        agent = BrowserRefreshAgent(status_reader=status_reader, browser_client=browser_client, submitter=submitter)

        run_agent_iteration(agent, logger=logger)
        run_agent_iteration(agent, logger=logger)

        self.assertEqual(browser_client.prepare_target_page.call_count, 2)
        logger.warning.assert_called_once()

    def test_run_agent_iteration_logs_recoverable_failures_and_continues(self):
        from browser_refresh.agent import BrowserRefreshRecoverableError
        from browser_refresh.entrypoint import run_agent_iteration

        agent = mock.Mock()
        agent.run_once.side_effect = [
            BrowserRefreshRecoverableError("cdp timeout"),
            None,
        ]
        logger = mock.Mock()

        run_agent_iteration(agent, logger=logger)
        run_agent_iteration(agent, logger=logger)

        self.assertEqual(agent.run_once.call_count, 2)
        logger.warning.assert_called_once()

    def test_run_agent_iteration_does_not_swallow_programmer_errors(self):
        from browser_refresh.entrypoint import run_agent_iteration

        agent = mock.Mock()
        agent.run_once.side_effect = ValueError("bug")

        with self.assertRaises(ValueError):
            run_agent_iteration(agent, logger=mock.Mock())


if __name__ == "__main__":
    unittest.main()
