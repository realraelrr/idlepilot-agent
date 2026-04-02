import datetime
import os
import json
import tempfile
import unittest
from unittest import mock


def build_test_env(**overrides):
    env = {
        "FEISHU_APP_ID": "cli_app_id",
        "FEISHU_APP_SECRET": "cli_app_secret",
        "FEISHU_ADMIN_OPEN_IDS": "ou_admin_1, ou_admin_2",
        "FEISHU_CALLBACK_HOST": "127.0.0.1",
        "FEISHU_CALLBACK_PORT": "8100",
        "FEISHU_CALLBACK_PATH": "/feishu/events",
        "FEISHU_CALLBACK_MODE": "token",
        "FEISHU_VERIFICATION_TOKEN": "verify-token",
    }
    env.update(overrides)
    return env


def build_message_event(
    *,
    open_id="ou_admin_1",
    chat_type="p2p",
    message_type="text",
    text="/help",
    event_id="evt-1",
    message_id="om-1",
):
    event = {
        "header": {
            "event_id": event_id,
            "event_type": "im.message.receive_v1",
        },
        "event": {
            "sender": {
                "sender_id": {
                    "open_id": open_id,
                }
            },
            "message": {
                "chat_type": chat_type,
                "message_type": message_type,
                "message_id": message_id,
            },
        },
        "token": "verify-token",
    }
    if message_type == "text":
        event["event"]["message"]["content"] = json.dumps({"text": text}, ensure_ascii=False)
    else:
        event["event"]["message"]["content"] = json.dumps({"image_key": "img_v3_123"})
    return json.dumps(event, ensure_ascii=False).encode("utf-8")


class FeishuConfigTests(unittest.TestCase):
    def test_load_feishu_config_requires_app_credentials_and_admin_open_ids(self):
        from services.feishu_control_plane import load_feishu_config

        env = {
            "FEISHU_CALLBACK_HOST": "127.0.0.1",
            "FEISHU_CALLBACK_PORT": "8100",
            "FEISHU_CALLBACK_PATH": "/feishu/events",
            "FEISHU_CALLBACK_MODE": "token",
            "FEISHU_VERIFICATION_TOKEN": "verify-token",
        }

        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ValueError, "FEISHU_APP_ID"):
                load_feishu_config()

        env["FEISHU_APP_ID"] = "cli_app_id"
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ValueError, "FEISHU_APP_SECRET"):
                load_feishu_config()

        env["FEISHU_APP_SECRET"] = "cli_app_secret"
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(ValueError, "FEISHU_ADMIN_OPEN_IDS"):
                load_feishu_config()


class CallbackBootstrapTests(unittest.TestCase):
    def test_callback_verification_request_returns_expected_challenge_payload(self):
        from services.feishu_control_plane import FeishuControlPlane, load_feishu_config

        with mock.patch.dict(os.environ, build_test_env(), clear=True):
            plane = FeishuControlPlane(load_feishu_config())

        status_code, payload = plane.handle_callback_request(
            b'{"type":"url_verification","challenge":"challenge-token","token":"verify-token"}'
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload, {"challenge": "challenge-token"})

    def test_untrusted_callback_request_is_rejected_before_event_parsing(self):
        from services.feishu_control_plane import FeishuControlPlane, load_feishu_config

        event_handler = mock.Mock()
        with mock.patch.dict(os.environ, build_test_env(), clear=True):
            plane = FeishuControlPlane(load_feishu_config(), event_handler=event_handler)

        status_code, payload = plane.handle_callback_request(
            b'{"header":{"event_id":"evt-1"},"event":{},"token":"wrong-token"}'
        )

        self.assertEqual(status_code, 403)
        self.assertEqual(payload["error"], "untrusted callback request")
        event_handler.assert_not_called()

    def test_duplicate_callback_event_is_acknowledged_without_repeating_side_effects(self):
        from services.feishu_control_plane import FeishuControlPlane, load_feishu_config

        event_handler = mock.Mock(return_value={"ok": True})
        with mock.patch.dict(os.environ, build_test_env(), clear=True):
            plane = FeishuControlPlane(load_feishu_config(), event_handler=event_handler)

        raw_body = (
            b'{"header":{"event_id":"evt-1","event_type":"im.message.receive_v1"},'
            b'"event":{"sender":{"sender_id":{"open_id":"ou_admin_1"}}}'
            b',"token":"verify-token"}'
        )

        first_status, first_payload = plane.handle_callback_request(raw_body)
        second_status, second_payload = plane.handle_callback_request(raw_body)

        self.assertEqual(first_status, 200)
        self.assertEqual(first_payload, {"ok": True})
        self.assertEqual(second_status, 200)
        self.assertEqual(second_payload["duplicate"], True)
        event_handler.assert_called_once()

    def test_failed_event_handling_is_not_marked_duplicate_so_retry_can_reprocess(self):
        from services.feishu_control_plane import FeishuControlPlane, load_feishu_config

        event_handler = mock.Mock(side_effect=[RuntimeError("transient failure"), {"ok": True}])
        with mock.patch.dict(os.environ, build_test_env(), clear=True):
            plane = FeishuControlPlane(load_feishu_config(), event_handler=event_handler)

        raw_body = (
            b'{"header":{"event_id":"evt-retry","event_type":"im.message.receive_v1"},'
            b'"event":{"sender":{"sender_id":{"open_id":"ou_admin_1"}}},"token":"verify-token"}'
        )

        first_status, first_payload = plane.handle_callback_request(raw_body)
        second_status, second_payload = plane.handle_callback_request(raw_body)

        self.assertEqual(first_status, 500)
        self.assertEqual(first_payload["error"], "callback handling failed")
        self.assertEqual(second_status, 200)
        self.assertEqual(second_payload, {"ok": True})
        self.assertEqual(event_handler.call_count, 2)


class FeishuClientTests(unittest.TestCase):
    def test_feishu_client_fetches_and_reuses_tenant_access_token(self):
        from utils.feishu_client import FeishuClient

        token_response = mock.Mock()
        token_response.json.return_value = {
            "code": 0,
            "tenant_access_token": "tenant-token-1",
            "expire": 7200,
        }
        token_response.raise_for_status.return_value = None

        with mock.patch("requests.post", return_value=token_response) as mocked_post:
            client = FeishuClient("app-id", "app-secret")
            first_token = client.get_tenant_access_token()
            second_token = client.get_tenant_access_token()

        self.assertEqual(first_token, "tenant-token-1")
        self.assertEqual(second_token, "tenant-token-1")
        self.assertEqual(mocked_post.call_count, 1)

    def test_feishu_client_sends_text_message_to_open_id(self):
        from utils.feishu_client import FeishuClient

        token_response = mock.Mock()
        token_response.json.return_value = {
            "code": 0,
            "tenant_access_token": "tenant-token-1",
            "expire": 7200,
        }
        token_response.raise_for_status.return_value = None

        send_response = mock.Mock()
        send_response.json.return_value = {"code": 0, "data": {"message_id": "om_dc13264520392913993dd051dba21dcf"}}
        send_response.raise_for_status.return_value = None

        with mock.patch("requests.post", side_effect=[token_response, send_response]) as mocked_post:
            client = FeishuClient("app-id", "app-secret")
            response = client.send_text_message("ou_admin_1", "已接收，开始校验")

        self.assertEqual(response["code"], 0)
        self.assertEqual(mocked_post.call_count, 2)
        send_call = mocked_post.call_args_list[1]
        self.assertIn("receive_id_type=open_id", send_call.args[0])
        self.assertEqual(send_call.kwargs["headers"]["Authorization"], "Bearer tenant-token-1")
        self.assertEqual(send_call.kwargs["json"]["receive_id"], "ou_admin_1")
        self.assertEqual(send_call.kwargs["json"]["msg_type"], "text")


class ControlPlaneTests(unittest.TestCase):
    def create_plane(self, tempdir, **env_overrides):
        from services.feishu_control_plane import FeishuControlPlane, load_feishu_config

        feishu_client = mock.Mock()
        env = build_test_env(**env_overrides)
        with mock.patch.dict(os.environ, env, clear=True):
            plane = FeishuControlPlane(
                load_feishu_config(),
                feishu_client=feishu_client,
                cookie_file_path=os.path.join(tempdir, "data", "cookies.txt"),
                submission_state_path=os.path.join(tempdir, "data", "cookie_submission_state.json"),
                runtime_status_path=os.path.join(tempdir, "data", "runtime_status.json"),
            )
        return plane, feishu_client

    def test_private_message_rejects_non_whitelisted_open_id_with_reply(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client = self.create_plane(tempdir)

            status_code, payload = plane.handle_callback_request(
                build_message_event(open_id="ou_not_allowed", text="/status")
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload, {"ok": True})
        feishu_client.send_text_message.assert_called_once()
        self.assertEqual(feishu_client.send_text_message.call_args.args[0], "ou_not_allowed")
        self.assertIn("未授权", feishu_client.send_text_message.call_args.args[1])

    def test_group_message_cookie_submission_is_rejected_with_reply(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client = self.create_plane(tempdir)

            plane.handle_callback_request(
                build_message_event(chat_type="group", text="unb=1; cookie2=2; cna=3; _m_h5_tk=4")
            )

        self.assertEqual(feishu_client.send_text_message.call_args.args[0], "ou_admin_1")
        self.assertIn("私聊", feishu_client.send_text_message.call_args.args[1])

    def test_private_status_command_returns_current_runtime_state(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client = self.create_plane(tempdir)
            os.makedirs(os.path.join(tempdir, "data"), exist_ok=True)
            with open(plane.runtime_status_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "state": "waiting_for_cookie",
                        "updated_at": "2026-03-21T19:00:00+08:00",
                        "message": "Cookie invalid, waiting for refresh",
                    },
                    f,
                    ensure_ascii=False,
                )

            plane.handle_callback_request(build_message_event(text="/status"))

        reply_text = feishu_client.send_text_message.call_args.args[1]
        self.assertIn("waiting_for_cookie", reply_text)
        self.assertIn("2026-03-21T19:00:00+08:00", reply_text)

    def test_private_help_command_returns_supported_commands(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client = self.create_plane(tempdir)

            plane.handle_callback_request(build_message_event(text="/help"))

        reply_text = feishu_client.send_text_message.call_args.args[1]
        self.assertIn("/help", reply_text)
        self.assertIn("/status", reply_text)
        self.assertIn("Cookie", reply_text)

    def test_plain_private_message_with_cookie_shape_is_treated_as_cookie_submission(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client = self.create_plane(tempdir)
            plane.start_followup_task = mock.Mock()

            plane.handle_callback_request(
                build_message_event(text="unb=1; cookie2=2; cna=3; _m_h5_tk=4")
            )

            with open(plane.cookie_file_path, "r", encoding="utf-8") as f:
                stored_cookie = f.read()

        self.assertEqual(stored_cookie, "unb=1; cookie2=2; cna=3; _m_h5_tk=4")
        self.assertEqual(feishu_client.send_text_message.call_args.args[1], "已接收，开始校验")
        plane.start_followup_task.assert_called_once()

    def test_browser_submission_core_writes_source_without_sender_open_id(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, _ = self.create_plane(tempdir, BROWSER_REFRESH_SHARED_SECRET="browser-secret")
            plane.start_followup_task = mock.Mock()

            submission_id = plane.submit_cookie_update(
                source="browser_refresh",
                cookie_text="unb=1; cookie2=2; cna=3; _m_h5_tk=4",
                sender_open_id="",
                send_replies=False,
            )

            with open(plane.submission_state_path, "r", encoding="utf-8") as f:
                submission_state = json.load(f)

        self.assertEqual(submission_state["submission_id"], submission_id)
        self.assertEqual(submission_state["source"], "browser_refresh")
        self.assertEqual(submission_state["sender_open_id"], "")

    def test_submission_core_clears_persisted_reply_target_when_send_replies_disabled(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, _ = self.create_plane(tempdir, BROWSER_REFRESH_SHARED_SECRET="browser-secret")
            plane.start_followup_task = mock.Mock()

            plane.submit_cookie_update(
                source="browser_refresh",
                cookie_text="unb=1; cookie2=2; cna=3; _m_h5_tk=4",
                sender_open_id="ou_admin_1",
                send_replies=False,
            )

            with open(plane.submission_state_path, "r", encoding="utf-8") as f:
                submission_state = json.load(f)

        self.assertEqual(submission_state["sender_open_id"], "")

    def test_browser_cookie_submit_rejects_missing_or_invalid_shared_secret(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, _ = self.create_plane(tempdir, BROWSER_REFRESH_SHARED_SECRET="browser-secret")

            status_code, payload = plane.handle_browser_cookie_submit_request(
                headers={"Authorization": "Bearer wrong-secret"},
                raw_body=b'{"cookie":"unb=1; cookie2=2; cna=3; _m_h5_tk=4","episode_id":"episode-1"}',
            )

        self.assertEqual(status_code, 403)
        self.assertEqual(payload["error"], "untrusted browser refresh request")

    def test_browser_cookie_submit_accepts_valid_request_without_feishu_reply(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client = self.create_plane(
                tempdir,
                BROWSER_REFRESH_SHARED_SECRET="browser-secret",
            )
            plane.start_followup_task = mock.Mock()
            os.makedirs(os.path.dirname(plane.runtime_status_path), exist_ok=True)
            with open(plane.runtime_status_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "state": "waiting_for_cookie",
                        "cookie_invalid_episode_id": "episode-1",
                        "updated_at": "2026-04-03T12:00:00+08:00",
                    },
                    f,
                    ensure_ascii=False,
                )

            status_code, payload = plane.handle_browser_cookie_submit_request(
                headers={"Authorization": "Bearer browser-secret"},
                raw_body=b'{"cookie":"unb=1; cookie2=2; cna=3; _m_h5_tk=4","episode_id":"episode-1"}',
            )

            with open(plane.submission_state_path, "r", encoding="utf-8") as f:
                submission_state = json.load(f)

        self.assertEqual(status_code, 202)
        self.assertEqual(payload["ok"], True)
        self.assertEqual(submission_state["source"], "browser_refresh")
        feishu_client.send_text_message.assert_not_called()

    def test_browser_cookie_submit_rejects_stale_or_mismatched_episode(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, _ = self.create_plane(
                tempdir,
                BROWSER_REFRESH_SHARED_SECRET="browser-secret",
            )
            plane.start_followup_task = mock.Mock()
            os.makedirs(os.path.dirname(plane.runtime_status_path), exist_ok=True)
            with open(plane.runtime_status_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "state": "waiting_for_cookie",
                        "cookie_invalid_episode_id": "episode-current",
                        "updated_at": "2026-04-03T12:00:00+08:00",
                    },
                    f,
                    ensure_ascii=False,
                )

            status_code, payload = plane.handle_browser_cookie_submit_request(
                headers={"Authorization": "Bearer browser-secret"},
                raw_body=b'{"cookie":"unb=1; cookie2=2; cna=3; _m_h5_tk=4","episode_id":"episode-stale"}',
            )

        self.assertEqual(status_code, 409)
        self.assertEqual(payload["error"], "browser refresh episode is not active")
        self.assertFalse(os.path.exists(plane.submission_state_path))
        plane.start_followup_task.assert_not_called()

    def test_browser_cookie_submit_accepts_active_validation_failed_episode(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, _ = self.create_plane(
                tempdir,
                BROWSER_REFRESH_SHARED_SECRET="browser-secret",
            )
            plane.start_followup_task = mock.Mock()
            os.makedirs(os.path.dirname(plane.runtime_status_path), exist_ok=True)
            with open(plane.runtime_status_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "state": "validation_failed",
                        "cookie_invalid_episode_id": "episode-1",
                        "updated_at": "2026-04-03T12:00:05+08:00",
                    },
                    f,
                    ensure_ascii=False,
                )

            status_code, payload = plane.handle_browser_cookie_submit_request(
                headers={"Authorization": "Bearer browser-secret"},
                raw_body=b'{"cookie":"unb=1; cookie2=2; cna=3; _m_h5_tk=4","episode_id":"episode-1"}',
            )

        self.assertEqual(status_code, 202)
        self.assertEqual(payload["ok"], True)
        plane.start_followup_task.assert_called_once()

    def test_non_text_private_message_is_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client = self.create_plane(tempdir)

            plane.handle_callback_request(build_message_event(message_type="image"))

        self.assertIn("文本", feishu_client.send_text_message.call_args.args[1])


class CookieWriteTests(unittest.TestCase):
    def create_plane(self, tempdir):
        from services.feishu_control_plane import FeishuControlPlane, load_feishu_config

        feishu_client = mock.Mock()
        with mock.patch.dict(os.environ, build_test_env(), clear=True):
            plane = FeishuControlPlane(
                load_feishu_config(),
                feishu_client=feishu_client,
                cookie_file_path=os.path.join(tempdir, "data", "cookies.txt"),
                submission_state_path=os.path.join(tempdir, "data", "cookie_submission_state.json"),
                runtime_status_path=os.path.join(tempdir, "data", "runtime_status.json"),
            )
        plane.start_followup_task = mock.Mock()
        return plane, feishu_client

    def test_cookie_submission_replaces_cookie_file_atomically(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, _ = self.create_plane(tempdir)
            os.makedirs(os.path.dirname(plane.cookie_file_path), exist_ok=True)
            with open(plane.cookie_file_path, "w", encoding="utf-8") as f:
                f.write("old_cookie")

            plane.handle_callback_request(build_message_event(text="unb=1; cookie2=2; cna=3; _m_h5_tk=4"))

            with open(plane.cookie_file_path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "unb=1; cookie2=2; cna=3; _m_h5_tk=4")

    def test_cookie_submission_writes_submission_state_with_unique_submission_id(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, _ = self.create_plane(tempdir)

            plane.handle_callback_request(build_message_event(text="unb=1; cookie2=2; cna=3; _m_h5_tk=4"))

            with open(plane.submission_state_path, "r", encoding="utf-8") as f:
                submission_state = json.load(f)

        self.assertEqual(submission_state["sender_open_id"], "ou_admin_1")
        self.assertEqual(submission_state["state"], "in_progress")
        self.assertTrue(submission_state["submission_id"])

    def test_second_cookie_submission_is_rejected_while_first_is_in_progress(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client = self.create_plane(tempdir)

            plane.handle_callback_request(build_message_event(event_id="evt-1", message_id="om-1", text="unb=1; cookie2=2; cna=3; _m_h5_tk=4"))
            plane.handle_callback_request(build_message_event(event_id="evt-2", message_id="om-2", text="unb=9; cookie2=8; cna=7; _m_h5_tk=6"))

        self.assertIn("稍后重试", feishu_client.send_text_message.call_args.args[1])

    def test_cookie_submission_marks_aborted_when_cookie_replace_fails(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, _ = self.create_plane(tempdir)

            from services import feishu_control_plane as control_plane_module

            original_atomic_write_text = control_plane_module._atomic_write_text
            write_calls = {"count": 0}

            def failing_cookie_write(path, content):
                write_calls["count"] += 1
                if write_calls["count"] == 2:
                    raise OSError("disk full")
                return original_atomic_write_text(path, content)

            with mock.patch(
                "services.feishu_control_plane._atomic_write_text",
                side_effect=failing_cookie_write,
            ):
                plane.handle_callback_request(build_message_event(text="unb=1; cookie2=2; cna=3; _m_h5_tk=4"))

            with open(plane.submission_state_path, "r", encoding="utf-8") as f:
                submission_state = json.load(f)

        self.assertEqual(submission_state["state"], "aborted")

    def test_cookie_submission_starts_followup_even_if_immediate_reply_fails(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client = self.create_plane(tempdir)
            plane.start_followup_task = mock.Mock()
            feishu_client.send_text_message.side_effect = RuntimeError("temporary feishu send failure")

            status_code, payload = plane.handle_callback_request(
                build_message_event(text="unb=1; cookie2=2; cna=3; _m_h5_tk=4")
            )

            with open(plane.submission_state_path, "r", encoding="utf-8") as f:
                submission_state = json.load(f)

        self.assertEqual(status_code, 200)
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(submission_state["state"], "in_progress")
        plane.start_followup_task.assert_called_once()


class AckLoopTests(unittest.TestCase):
    def create_plane(self, tempdir):
        from services.feishu_control_plane import FeishuControlPlane, load_feishu_config

        feishu_client = mock.Mock()
        with mock.patch.dict(os.environ, build_test_env(), clear=True):
            plane = FeishuControlPlane(
                load_feishu_config(),
                feishu_client=feishu_client,
                cookie_file_path=os.path.join(tempdir, "data", "cookies.txt"),
                submission_state_path=os.path.join(tempdir, "data", "cookie_submission_state.json"),
                runtime_status_path=os.path.join(tempdir, "data", "runtime_status.json"),
                followup_timeout_seconds=1,
                followup_poll_interval_seconds=0,
            )
        return plane, feishu_client

    def test_cookie_submission_reports_recovery_success_when_status_turns_recovered(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client = self.create_plane(tempdir)
            os.makedirs(os.path.dirname(plane.submission_state_path), exist_ok=True)
            with open(plane.submission_state_path, "w", encoding="utf-8") as f:
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
            with open(plane.runtime_status_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "submission_id": "sub-1",
                        "state": "recovered",
                        "updated_at": "2026-03-21T19:00:01+08:00",
                        "message": "Cookie validated and websocket reconnected",
                    },
                    f,
                    ensure_ascii=False,
                )

            plane.follow_submission_result("sub-1")

            with open(plane.submission_state_path, "r", encoding="utf-8") as f:
                submission_state = json.load(f)

        self.assertEqual(submission_state["state"], "completed")
        self.assertEqual(feishu_client.send_text_message.call_args.args[1], "Cookie 已生效，连接已恢复")

    def test_cookie_submission_reports_validation_failure_when_status_turns_failed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client = self.create_plane(tempdir)
            os.makedirs(os.path.dirname(plane.submission_state_path), exist_ok=True)
            with open(plane.submission_state_path, "w", encoding="utf-8") as f:
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
            with open(plane.runtime_status_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "submission_id": "sub-1",
                        "state": "validation_failed",
                        "updated_at": "2026-03-21T19:00:01+08:00",
                        "message": "Cookie validation failed",
                    },
                    f,
                    ensure_ascii=False,
                )

            plane.follow_submission_result("sub-1")

            with open(plane.submission_state_path, "r", encoding="utf-8") as f:
                submission_state = json.load(f)

        self.assertEqual(submission_state["state"], "completed")
        self.assertEqual(feishu_client.send_text_message.call_args.args[1], "Cookie 已接收，但校验失败，请重新获取")

    def test_browser_submission_completion_does_not_send_private_chat_reply(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client = self.create_plane(tempdir)
            plane._generate_submission_id = mock.Mock(return_value="sub-1")
            plane.start_followup_task = (
                lambda submission_id: plane.follow_submission_result(submission_id)
            )
            os.makedirs(os.path.dirname(plane.runtime_status_path), exist_ok=True)
            with open(plane.runtime_status_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "submission_id": "sub-1",
                        "state": "recovered",
                        "cookie_invalid_episode_id": "episode-1",
                        "updated_at": "2026-04-03T12:00:05+08:00",
                        "message": "Cookie validated and websocket reconnected",
                    },
                    f,
                    ensure_ascii=False,
                )

            plane.submit_cookie_update(
                source="browser_refresh",
                cookie_text="unb=1; cookie2=2; cna=3; _m_h5_tk=4",
                sender_open_id="",
                send_replies=False,
            )

        feishu_client.send_text_message.assert_not_called()


class ProactiveAlertTests(unittest.TestCase):
    def create_plane(self, tempdir, **env_overrides):
        from services.feishu_control_plane import FeishuControlPlane, load_feishu_config

        feishu_client = mock.Mock()
        with mock.patch.dict(os.environ, build_test_env(**env_overrides), clear=True):
            with mock.patch("os.getcwd", return_value=tempdir):
                plane = FeishuControlPlane(
                    load_feishu_config(),
                    feishu_client=feishu_client,
                    cookie_file_path=os.path.join(tempdir, "data", "cookies.txt"),
                    submission_state_path=os.path.join(tempdir, "data", "cookie_submission_state.json"),
                    runtime_status_path=os.path.join(tempdir, "data", "runtime_status.json"),
                )
        return plane, feishu_client, os.path.join(tempdir, "data", "alert_state.json")

    @staticmethod
    def write_runtime_status(path, payload):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

    def test_runtime_status_poller_sends_waiting_for_cookie_alert_to_all_admins_once_per_episode(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client, _ = self.create_plane(tempdir)
            self.write_runtime_status(
                plane.runtime_status_path,
                {
                    "state": "waiting_for_cookie",
                    "updated_at": "2026-03-22T09:00:00+08:00",
                    "message": "Cookie invalid, waiting for refresh",
                    "cookie_invalid_episode_id": "episode-1",
                },
            )

            plane.poll_runtime_status_once()
            plane.poll_runtime_status_once()

        self.assertEqual(feishu_client.send_text_message.call_count, 2)
        self.assertEqual(
            {call.args[0] for call in feishu_client.send_text_message.call_args_list},
            {"ou_admin_1", "ou_admin_2"},
        )
        for call in feishu_client.send_text_message.call_args_list:
            self.assertIn("Cookie", call.args[1])
            self.assertIn("episode-1", call.args[1])

    def test_persisted_alert_state_prevents_duplicate_waiting_alert_after_restart(self):
        with tempfile.TemporaryDirectory() as tempdir:
            first_plane, first_client, alert_state_path = self.create_plane(tempdir)
            self.write_runtime_status(
                first_plane.runtime_status_path,
                {
                    "state": "waiting_for_cookie",
                    "updated_at": "2026-03-22T09:00:00+08:00",
                    "message": "Cookie invalid, waiting for refresh",
                    "cookie_invalid_episode_id": "episode-1",
                },
            )

            first_plane.poll_runtime_status_once()

            with open(alert_state_path, "r", encoding="utf-8") as f:
                persisted_state = json.load(f)

            second_plane, second_client, _ = self.create_plane(tempdir)
            second_plane.poll_runtime_status_once()

        self.assertEqual(first_client.send_text_message.call_count, 2)
        self.assertEqual(second_client.send_text_message.call_count, 0)
        self.assertEqual(persisted_state["last_alerted_waiting_episode_id"], "episode-1")

    def test_waiting_alert_mentions_remote_browser_url_and_keeps_same_episode_open_after_validation_failed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client, alert_state_path = self.create_plane(
                tempdir,
                BROWSER_REFRESH_URL="https://browser.example.ts.net",
            )
            self.write_runtime_status(
                plane.runtime_status_path,
                {
                    "state": "waiting_for_cookie",
                    "updated_at": "2026-04-03T12:00:00+08:00",
                    "message": "Cookie invalid, waiting for refresh",
                    "cookie_invalid_episode_id": "episode-1",
                },
            )
            plane.poll_runtime_status_once()

            self.write_runtime_status(
                plane.runtime_status_path,
                {
                    "state": "validation_failed",
                    "updated_at": "2026-04-03T12:00:05+08:00",
                    "message": "Cookie validation failed",
                    "cookie_invalid_episode_id": "episode-1",
                },
            )
            plane.poll_runtime_status_once()

            with open(alert_state_path, "r", encoding="utf-8") as f:
                persisted_state = json.load(f)

        sent_text = feishu_client.send_text_message.call_args.args[1]
        self.assertIn("远程浏览器", sent_text)
        self.assertIn("https://browser.example.ts.net", sent_text)
        self.assertEqual(persisted_state["last_alerted_waiting_episode_id"], "episode-1")
        self.assertEqual(persisted_state["awaiting_terminal_episode_id"], "episode-1")
        self.assertEqual(feishu_client.send_text_message.call_count, 2)

    def test_recovered_state_allows_next_invalid_cookie_episode_to_alert_again(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client, alert_state_path = self.create_plane(tempdir)
            self.write_runtime_status(
                plane.runtime_status_path,
                {
                    "state": "waiting_for_cookie",
                    "updated_at": "2026-03-22T09:00:00+08:00",
                    "message": "Cookie invalid, waiting for refresh",
                    "cookie_invalid_episode_id": "episode-1",
                },
            )
            plane.poll_runtime_status_once()

            self.write_runtime_status(
                plane.runtime_status_path,
                {
                    "state": "recovered",
                    "updated_at": "2026-03-22T09:01:00+08:00",
                    "message": "Cookie recovered",
                    "cookie_invalid_episode_id": "episode-1",
                },
            )
            plane.poll_runtime_status_once()

            with open(alert_state_path, "r", encoding="utf-8") as f:
                reset_state = json.load(f)

            self.write_runtime_status(
                plane.runtime_status_path,
                {
                    "state": "waiting_for_cookie",
                    "updated_at": "2026-03-22T09:02:00+08:00",
                    "message": "Cookie invalid again, waiting for refresh",
                    "cookie_invalid_episode_id": "episode-2",
                },
            )
            plane.poll_runtime_status_once()

            with open(alert_state_path, "r", encoding="utf-8") as f:
                final_state = json.load(f)

        self.assertEqual(reset_state["last_alerted_waiting_episode_id"], "")
        self.assertEqual(final_state["last_alerted_waiting_episode_id"], "episode-2")
        self.assertEqual(feishu_client.send_text_message.call_count, 4)
        alerted_episodes = {
            "episode-1": False,
            "episode-2": False,
        }
        for call in feishu_client.send_text_message.call_args_list:
            for episode_id in alerted_episodes:
                if episode_id in call.args[1]:
                    alerted_episodes[episode_id] = True
        self.assertEqual(alerted_episodes, {"episode-1": True, "episode-2": True})

    def test_new_waiting_episode_replaces_existing_waiting_alert_state(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client, alert_state_path = self.create_plane(tempdir)
            self.write_runtime_status(
                plane.runtime_status_path,
                {
                    "state": "waiting_for_cookie",
                    "updated_at": "2026-03-22T09:00:00+08:00",
                    "message": "Cookie invalid, waiting for refresh",
                    "cookie_invalid_episode_id": "episode-1",
                },
            )
            plane.poll_runtime_status_once()

            self.write_runtime_status(
                plane.runtime_status_path,
                {
                    "state": "waiting_for_cookie",
                    "updated_at": "2026-03-22T09:01:00+08:00",
                    "message": "A second invalid-cookie episode appeared before terminal state",
                    "cookie_invalid_episode_id": "episode-2",
                },
            )
            plane.poll_runtime_status_once()

            with open(alert_state_path, "r", encoding="utf-8") as f:
                persisted_state = json.load(f)

        self.assertEqual(feishu_client.send_text_message.call_count, 4)
        episode_counts = {"episode-1": 0, "episode-2": 0}
        for call in feishu_client.send_text_message.call_args_list:
            for episode_id in episode_counts:
                if episode_id in call.args[1]:
                    episode_counts[episode_id] += 1
        self.assertEqual(episode_counts, {"episode-1": 2, "episode-2": 2})
        self.assertEqual(persisted_state["last_alerted_waiting_episode_id"], "episode-2")
        self.assertEqual(persisted_state["awaiting_terminal_episode_id"], "episode-2")

    def test_waiting_state_without_cookie_invalid_episode_id_does_not_send_proactive_alert(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client, alert_state_path = self.create_plane(tempdir)
            self.write_runtime_status(
                plane.runtime_status_path,
                {
                    "state": "waiting_for_cookie",
                    "updated_at": "2026-03-22T09:00:00+08:00",
                    "message": "Cookie invalid, waiting for refresh",
                },
            )
            plane.poll_runtime_status_once()

        self.assertFalse(os.path.exists(alert_state_path))
        feishu_client.send_text_message.assert_not_called()

    def test_partial_admin_delivery_retries_only_missing_admins(self):
        with tempfile.TemporaryDirectory() as tempdir:
            plane, feishu_client, alert_state_path = self.create_plane(tempdir)
            feishu_client.send_text_message.side_effect = [
                None,
                RuntimeError("temporary feishu send failure"),
                None,
            ]
            self.write_runtime_status(
                plane.runtime_status_path,
                {
                    "state": "waiting_for_cookie",
                    "updated_at": "2026-03-22T09:00:00+08:00",
                    "message": "Cookie invalid, waiting for refresh",
                    "cookie_invalid_episode_id": "episode-1",
                },
            )

            plane.poll_runtime_status_once()

            if os.path.exists(alert_state_path):
                with open(alert_state_path, "r", encoding="utf-8") as f:
                    first_state = json.load(f)
            else:
                first_state = {
                    "last_alerted_waiting_episode_id": "",
                    "awaiting_terminal_episode_id": "",
                    "delivered_admin_open_ids": [],
                }

            plane.poll_runtime_status_once()

            with open(alert_state_path, "r", encoding="utf-8") as f:
                second_state = json.load(f)

        self.assertEqual(first_state["last_alerted_waiting_episode_id"], "")
        self.assertEqual(first_state["awaiting_terminal_episode_id"], "episode-1")
        self.assertEqual(first_state["delivered_admin_open_ids"], ["ou_admin_1"])
        self.assertEqual(second_state["last_alerted_waiting_episode_id"], "episode-1")
        self.assertEqual(second_state["awaiting_terminal_episode_id"], "episode-1")
        self.assertEqual(second_state["delivered_admin_open_ids"], ["ou_admin_1", "ou_admin_2"])
        self.assertEqual(
            [call.args[0] for call in feishu_client.send_text_message.call_args_list],
            ["ou_admin_1", "ou_admin_2", "ou_admin_2"],
        )

class ServiceBootstrapTests(unittest.TestCase):
    def test_stale_in_progress_submission_is_marked_timed_out_on_startup(self):
        from services.feishu_control_plane import FeishuControlPlane, load_feishu_config

        with tempfile.TemporaryDirectory() as tempdir:
            data_dir = os.path.join(tempdir, "data")
            os.makedirs(data_dir, exist_ok=True)
            submission_state_path = os.path.join(data_dir, "cookie_submission_state.json")
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

            now_provider = lambda: datetime.datetime(2026, 3, 21, 12, 0, tzinfo=datetime.timezone.utc)

            with mock.patch.dict(
                os.environ,
                build_test_env(FEISHU_STALE_LOCK_SECONDS="1"),
                clear=True,
            ):
                FeishuControlPlane(
                    load_feishu_config(),
                    feishu_client=mock.Mock(),
                    submission_state_path=submission_state_path,
                    now_provider=now_provider,
                )

            with open(submission_state_path, "r", encoding="utf-8") as f:
                submission_state = json.load(f)

        self.assertEqual(submission_state["state"], "timed_out")
