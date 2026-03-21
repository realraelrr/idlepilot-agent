import json
import os
import tempfile
import time
import unittest
from unittest import mock

from main import XianyuLive, check_and_complete_env
from XianyuApis import XianyuApis, CookieInvalidError
from utils.notifier import FeishuNotifier


class CookieRecoveryTests(unittest.TestCase):
    def test_load_cookie_string_prefers_cookie_file_over_env(self):
        env_cookie = "unb=env_unb; foo=env"
        file_cookie = "unb=file_unb; foo=file"

        with tempfile.TemporaryDirectory() as tempdir:
            data_dir = os.path.join(tempdir, "data")
            os.makedirs(data_dir, exist_ok=True)
            cookie_path = os.path.join(data_dir, "cookies.txt")
            with open(cookie_path, "w", encoding="utf-8") as f:
                f.write(file_cookie)

            with mock.patch.dict(os.environ, {"COOKIES_STR": env_cookie}, clear=False):
                with mock.patch("os.getcwd", return_value=tempdir):
                    live = XianyuLive(env_cookie)
                    self.assertEqual(live.load_cookie_string(), file_cookie)

    def test_load_cookie_string_falls_back_to_env_when_file_empty(self):
        env_cookie = "unb=env_unb; foo=env"

        with tempfile.TemporaryDirectory() as tempdir:
            data_dir = os.path.join(tempdir, "data")
            os.makedirs(data_dir, exist_ok=True)
            cookie_path = os.path.join(data_dir, "cookies.txt")
            with open(cookie_path, "w", encoding="utf-8") as f:
                f.write("   ")

            with mock.patch.dict(os.environ, {"COOKIES_STR": env_cookie}, clear=False):
                with mock.patch("os.getcwd", return_value=tempdir):
                    live = XianyuLive(env_cookie)
                    self.assertEqual(live.load_cookie_string(), env_cookie)

    def test_get_token_raises_cookie_invalid_error_on_rgv587(self):
        api = XianyuApis()
        api.session.cookies.set("_m_h5_tk", "token_1234")

        response = mock.Mock()
        response.json.return_value = {
            "ret": ["FAIL_SYS_RGV587_ERROR::被挤爆啦"]
        }
        response.headers = {}

        with mock.patch.object(api.session, "post", return_value=response):
            with self.assertRaises(CookieInvalidError):
                api.get_token("device-id")

    def test_get_item_info_raises_cookie_invalid_error_on_rgv587(self):
        api = XianyuApis()
        api.session.cookies.set("_m_h5_tk", "token_1234")

        response = mock.Mock()
        response.json.return_value = {
            "ret": ["FAIL_SYS_RGV587_ERROR::被挤爆啦"]
        }
        response.headers = {}

        with mock.patch.object(api.session, "post", return_value=response):
            with self.assertRaises(CookieInvalidError):
                api.get_item_info("item-1")

    def test_apply_cookie_string_refreshes_cookie_headers_identity_and_device(self):
        live = XianyuLive("unb=old_user; foo=1")
        old_device_id = live.device_id

        new_cookie = "unb=new_user; foo=2; bar=3"
        live.apply_cookie_string(new_cookie)

        self.assertEqual(live.cookies_str, new_cookie)
        self.assertEqual(live.cookies.get("unb"), "new_user")
        self.assertEqual(live.xianyu.session.cookies.get("unb"), "new_user")
        self.assertEqual(live.myid, "new_user")
        self.assertNotEqual(live.device_id, old_device_id)
        self.assertTrue(live.device_id.endswith("-new_user"))

    def test_cookie_invalid_transition_sends_single_feishu_alert(self):
        live = XianyuLive("unb=user_a; foo=1")
        live.notifier = mock.Mock()

        live.send_cookie_invalid_alert_once()
        live.send_cookie_invalid_alert_once()
        live.notifier.send_cookie_invalid_alert.assert_called_once()

        live.reset_cookie_invalid_alert()
        live.send_cookie_invalid_alert_once()
        self.assertEqual(live.notifier.send_cookie_invalid_alert.call_count, 2)

    def test_check_and_complete_env_persists_api_key_to_dotenv(self):
        with tempfile.TemporaryDirectory() as tempdir:
            env_path = os.path.join(tempdir, ".env")
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("builtins.input", return_value="test-api-key"):
                    current_dir = os.getcwd()
                    try:
                        os.chdir(tempdir)
                        check_and_complete_env()
                    finally:
                        os.chdir(current_dir)

            with open(env_path, "r", encoding="utf-8") as f:
                env_content = f.read()

            self.assertIn("API_KEY='test-api-key'", env_content)

    def test_feishu_alert_mentions_configured_cookie_file_path(self):
        notifier = FeishuNotifier(enabled=True, webhook_url="https://example.com/webhook")
        response = mock.Mock(status_code=200)

        with mock.patch.dict(os.environ, {"COOKIE_FILE_PATH": "/tmp/custom-cookies.txt"}, clear=False):
            with mock.patch("requests.post", return_value=response) as mocked_post:
                notifier.send_cookie_invalid_alert()

        payload = mocked_post.call_args.kwargs["json"]
        self.assertIn("/tmp/custom-cookies.txt", payload["content"]["text"])

    def test_publish_connected_idle_status_does_not_overwrite_active_recovered_submission(self):
        recovered_status = {
            "submission_id": "sub-1",
            "state": "recovered",
            "updated_at": "2026-03-21T19:00:01+08:00",
            "message": "Cookie validated and websocket reconnected",
        }

        with tempfile.TemporaryDirectory() as tempdir:
            data_dir = os.path.join(tempdir, "data")
            os.makedirs(data_dir, exist_ok=True)
            with open(os.path.join(data_dir, "cookie_submission_state.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "submission_id": "sub-1",
                        "sender_open_id": "ou_admin_1",
                        "requested_at": "2026-03-21T19:00:00+08:00",
                        "state": "in_progress",
                    },
                    f,
                    ensure_ascii=False,
                )
            with open(os.path.join(data_dir, "runtime_status.json"), "w", encoding="utf-8") as f:
                json.dump(recovered_status, f, ensure_ascii=False)

            with mock.patch("os.getcwd", return_value=tempdir):
                live = XianyuLive("unb=user_a; foo=1")
                live.publish_connected_idle_status()

            with open(os.path.join(data_dir, "runtime_status.json"), "r", encoding="utf-8") as f:
                runtime_status = json.load(f)

        self.assertEqual(runtime_status["state"], "recovered")
        self.assertEqual(runtime_status["submission_id"], "sub-1")


class CookieRecoveryAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_message_propagates_cookie_invalid_from_item_info_fetch(self):
        live = XianyuLive("unb=seller_user; foo=1; _m_h5_tk=token_1234")
        live.context_manager.get_item_info = mock.Mock(return_value=None)
        live.xianyu.get_item_info = mock.Mock(side_effect=CookieInvalidError("cookie invalid"))

        message = {
            "1": {
                "2": "chat123@goofish",
                "5": str(int(time.time() * 1000)),
                "10": {
                    "reminderTitle": "buyer",
                    "senderUserId": "buyer_user",
                    "reminderContent": "在吗",
                    "reminderUrl": "https://www.goofish.com/im?itemId=item123",
                },
            },
            "3": {},
        }

        message_data = {
            "headers": {"mid": "mid-1", "sid": "sid-1"},
            "body": {
                "syncPushPackage": {
                    "data": [{"data": "encrypted-payload"}]
                }
            },
        }

        websocket = mock.AsyncMock()

        decrypted_message = (
            '{"1":{"2":"chat123@goofish","5":"'
            + message["1"]["5"]
            + '","10":{"reminderTitle":"buyer","senderUserId":"buyer_user","reminderContent":"在吗","reminderUrl":"https://www.goofish.com/im?itemId=item123"}},"3":{}}'
        )

        with mock.patch("main.decrypt", return_value=decrypted_message):
            with mock.patch.object(live, "is_chat_message", return_value=True):
                with mock.patch.object(live, "is_sync_package", return_value=True):
                    with mock.patch.object(live, "is_typing_status", return_value=False):
                        with mock.patch.object(live, "is_bracket_system_message", return_value=False):
                            with mock.patch.object(live, "is_system_message", return_value=False):
                                with self.assertRaises(CookieInvalidError):
                                    await live.handle_message(message_data, websocket)

    async def test_wait_for_cookie_refresh_validates_before_reconnect(self):
        old_cookie = "unb=old_user; foo=1"
        new_cookie = "unb=new_user; foo=2"

        with tempfile.TemporaryDirectory() as tempdir:
            data_dir = os.path.join(tempdir, "data")
            os.makedirs(data_dir, exist_ok=True)
            cookie_path = os.path.join(data_dir, "cookies.txt")
            with open(cookie_path, "w", encoding="utf-8") as f:
                f.write(old_cookie)

            with mock.patch("os.getcwd", return_value=tempdir):
                live = XianyuLive(old_cookie)
                live.refresh_token = mock.AsyncMock(return_value="token-ok")

                sleep_calls = {"count": 0}

                async def fake_sleep(_):
                    sleep_calls["count"] += 1
                    if sleep_calls["count"] == 1:
                        with open(cookie_path, "w", encoding="utf-8") as f:
                            f.write(new_cookie)

                with mock.patch("asyncio.sleep", side_effect=fake_sleep):
                    await live.wait_for_cookie_refresh()

                live.refresh_token.assert_awaited_once()
                self.assertEqual(live.cookies_str, new_cookie)
                self.assertEqual(live.myid, "new_user")

    async def test_wait_for_cookie_refresh_keeps_waiting_when_validation_returns_none(self):
        old_cookie = "unb=old_user; foo=1"
        invalid_new_cookie = "unb=retry_user; foo=2"
        valid_new_cookie = "unb=final_user; foo=3"

        with tempfile.TemporaryDirectory() as tempdir:
            data_dir = os.path.join(tempdir, "data")
            os.makedirs(data_dir, exist_ok=True)
            cookie_path = os.path.join(data_dir, "cookies.txt")
            with open(cookie_path, "w", encoding="utf-8") as f:
                f.write(old_cookie)

            with mock.patch("os.getcwd", return_value=tempdir):
                live = XianyuLive(old_cookie)
                live.refresh_token = mock.AsyncMock(side_effect=[None, "token-ok"])

                sleep_calls = {"count": 0}

                async def fake_sleep(_):
                    sleep_calls["count"] += 1
                    if sleep_calls["count"] == 1:
                        with open(cookie_path, "w", encoding="utf-8") as f:
                            f.write(invalid_new_cookie)
                    elif sleep_calls["count"] == 2:
                        with open(cookie_path, "w", encoding="utf-8") as f:
                            f.write(valid_new_cookie)

                with mock.patch("asyncio.sleep", side_effect=fake_sleep):
                    await live.wait_for_cookie_refresh()

                self.assertEqual(live.refresh_token.await_count, 2)
                self.assertEqual(live.cookies_str, valid_new_cookie)
                self.assertEqual(live.myid, "final_user")

    async def test_runtime_status_file_updates_on_waiting_validating_and_recovered_states(self):
        old_cookie = "unb=old_user; foo=1"
        new_cookie = "unb=new_user; foo=2"

        with tempfile.TemporaryDirectory() as tempdir:
            data_dir = os.path.join(tempdir, "data")
            os.makedirs(data_dir, exist_ok=True)
            cookie_path = os.path.join(data_dir, "cookies.txt")
            submission_state_path = os.path.join(data_dir, "cookie_submission_state.json")
            runtime_status_path = os.path.join(data_dir, "runtime_status.json")

            with open(cookie_path, "w", encoding="utf-8") as f:
                f.write(old_cookie)

            with open(submission_state_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "submission_id": "sub-1",
                        "sender_open_id": "ou_admin_1",
                        "requested_at": "2026-03-21T19:00:00+08:00",
                        "state": "in_progress",
                    },
                    f,
                    ensure_ascii=False,
                )

            with mock.patch("os.getcwd", return_value=tempdir):
                live = XianyuLive(old_cookie)
                live.refresh_token = mock.AsyncMock(return_value="token-ok")

                recorded_statuses = []
                original_publish_runtime_status = live.publish_runtime_status

                def record_and_publish(state, message, submission_id=""):
                    recorded_statuses.append((state, submission_id))
                    original_publish_runtime_status(state, message, submission_id=submission_id)

                live.publish_runtime_status = record_and_publish

                sleep_calls = {"count": 0}

                async def fake_sleep(_):
                    sleep_calls["count"] += 1
                    if sleep_calls["count"] == 1:
                        with open(cookie_path, "w", encoding="utf-8") as f:
                            f.write(new_cookie)

                with mock.patch("asyncio.sleep", side_effect=fake_sleep):
                    await live.wait_for_cookie_refresh()

            with open(runtime_status_path, "r", encoding="utf-8") as f:
                runtime_status = json.load(f)

        self.assertEqual(
            recorded_statuses,
            [
                ("waiting_for_cookie", "sub-1"),
                ("validating_new_cookie", "sub-1"),
                ("recovered", "sub-1"),
            ],
        )
        self.assertEqual(runtime_status["submission_id"], "sub-1")
        self.assertEqual(runtime_status["state"], "recovered")
