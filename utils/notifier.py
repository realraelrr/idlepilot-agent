import os

import requests
from loguru import logger


def get_cookie_file_label():
    return os.getenv("COOKIE_FILE_PATH", "data/cookies.txt")


class FeishuNotifier:
    def __init__(self, enabled=False, webhook_url=""):
        self.enabled = enabled
        self.webhook_url = webhook_url.strip()

    def send_cookie_invalid_alert(self):
        if not self.enabled:
            return False
        if not self.webhook_url:
            logger.warning("飞书告警已启用，但未配置FEISHU_WEBHOOK_URL")
            return False

        payload = {
            "msg_type": "text",
            "content": {
                "text": f"XianyuAutoAgent检测到Cookie失效，已进入等待刷新状态。请更新 {get_cookie_file_label()}。"
            },
        }
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=5)
            if resp.status_code >= 400:
                logger.warning(f"飞书告警发送失败，HTTP状态码: {resp.status_code}")
                return False
            return True
        except Exception as e:
            logger.warning(f"飞书告警发送异常: {e}")
            return False


def build_notifier_from_env():
    enabled = os.getenv("FEISHU_NOTIFY_ENABLED", "False").lower() == "true"
    webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "")
    return FeishuNotifier(enabled=enabled, webhook_url=webhook_url)
