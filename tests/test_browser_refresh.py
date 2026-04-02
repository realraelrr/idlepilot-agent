import unittest

from browser_refresh.cookie_bundle import (
    RECOMMENDED_EXTRA_KEYS,
    RUNTIME_CORE_KEYS,
    RuntimeCookieBundle,
    build_runtime_cookie_bundle,
)


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
            bundle.serialized_cookie_header,
            "unb=first-unb; cookie2=cookie2-value; cna=cna-value; _m_h5_tk=token-value; x5sec=x5sec-value",
        )
        self.assertEqual(
            [cookie["name"] for cookie in bundle.cookies],
            ["unb", "cookie2", "cna", "_m_h5_tk", "x5sec"],
        )
        self.assertEqual(bundle.missing_runtime_core_keys, [])
        self.assertTrue(bundle.runtime_ready)
        self.assertEqual(bundle.runtime_target_urls, tuple(bundle.RUNTIME_TARGET_URLS))

    def test_build_runtime_cookie_bundle_reports_missing_recommended_extras_without_blocking_runtime_readiness(self):
        cookies = [
            {"name": "unb", "value": "user-1"},
            {"name": "cookie2", "value": "cookie2-value"},
            {"name": "cna", "value": "cna-value"},
            {"name": "_m_h5_tk", "value": "token-value"},
        ]

        bundle = build_runtime_cookie_bundle(cookies)

        self.assertEqual(bundle.missing_runtime_core_keys, [])
        self.assertEqual(bundle.missing_recommended_extra_keys, RECOMMENDED_EXTRA_KEYS)
        self.assertTrue(bundle.runtime_ready)
        self.assertFalse(bundle.recommended_extras_present)
        self.assertEqual(bundle.runtime_core_keys, tuple(RUNTIME_CORE_KEYS))


if __name__ == "__main__":
    unittest.main()
