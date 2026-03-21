import json
import time

import requests


class FeishuClient:
    def __init__(self, app_id: str, app_secret: str, base_url: str = "https://open.feishu.cn"):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = base_url.rstrip("/")
        self._tenant_access_token = ""
        self._tenant_access_token_expiry = 0.0

    def get_tenant_access_token(self) -> str:
        now = time.time()
        if self._tenant_access_token and now < self._tenant_access_token_expiry:
            return self._tenant_access_token

        response = requests.post(
            f"{self.base_url}/open-apis/auth/v3/tenant_access_token/internal",
            json={
                "app_id": self.app_id,
                "app_secret": self.app_secret,
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise ValueError(f"Feishu tenant token request failed: {payload}")

        self._tenant_access_token = payload["tenant_access_token"]
        expires_in = int(payload.get("expire", 7200))
        self._tenant_access_token_expiry = now + max(expires_in - 60, 1)
        return self._tenant_access_token

    def send_text_message(self, open_id: str, text: str):
        response = requests.post(
            f"{self.base_url}/open-apis/im/v1/messages?receive_id_type=open_id",
            headers={
                "Authorization": f"Bearer {self.get_tenant_access_token()}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={
                "receive_id": open_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise ValueError(f"Feishu send message request failed: {payload}")
        return payload
