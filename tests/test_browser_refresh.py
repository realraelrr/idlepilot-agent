import json
import os
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
