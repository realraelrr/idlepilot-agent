import json
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from loguru import logger
from utils.feishu_client import FeishuClient


DEFAULT_CALLBACK_HOST = "127.0.0.1"
DEFAULT_CALLBACK_PORT = 8100
DEFAULT_CALLBACK_PATH = "/feishu/events"
DEFAULT_CALLBACK_MODE = "token"
DEFAULT_STALE_LOCK_SECONDS = 300
DEFAULT_COOKIE_FILE_PATH = os.path.join("data", "cookies.txt")
DEFAULT_SUBMISSION_STATE_PATH = os.path.join("data", "cookie_submission_state.json")
DEFAULT_RUNTIME_STATUS_PATH = os.path.join("data", "runtime_status.json")
DEFAULT_ALERT_STATE_PATH = os.path.join("data", "alert_state.json")
DEFAULT_FOLLOWUP_TIMEOUT_SECONDS = 60
DEFAULT_FOLLOWUP_POLL_INTERVAL_SECONDS = 1
DEFAULT_RUNTIME_STATUS_POLL_INTERVAL_SECONDS = 1


class SubmissionBusyError(Exception):
    pass


@dataclass(frozen=True)
class FeishuConfig:
    app_id: str
    app_secret: str
    admin_open_ids: set[str]
    callback_host: str
    callback_port: int
    callback_path: str
    callback_mode: str
    verification_token: str
    encrypt_key: str
    stale_lock_seconds: int


def _read_required_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _read_optional_env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _resolve_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(os.getcwd(), path)


def _ensure_parent_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path) or os.getcwd(), exist_ok=True)


def _atomic_write_text(path: str, content: str) -> None:
    _ensure_parent_dir(path)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=os.path.dirname(path) or os.getcwd(), delete=False) as temp_file:
        temp_file.write(content)
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_path = temp_file.name
    os.replace(temp_path, path)


def _atomic_write_json(path: str, payload: dict) -> None:
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _read_json_file(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _format_dt(dt: datetime) -> str:
    return dt.astimezone().isoformat(timespec="seconds")


def load_feishu_config() -> FeishuConfig:
    callback_mode = _read_optional_env("FEISHU_CALLBACK_MODE", DEFAULT_CALLBACK_MODE).lower()
    if callback_mode not in {"none", "token", "encrypt"}:
        raise ValueError("FEISHU_CALLBACK_MODE must be one of: none, token, encrypt")

    app_id = _read_required_env("FEISHU_APP_ID")
    app_secret = _read_required_env("FEISHU_APP_SECRET")
    raw_admin_open_ids = _read_required_env("FEISHU_ADMIN_OPEN_IDS")
    admin_open_ids = {item.strip() for item in raw_admin_open_ids.split(",") if item.strip()}
    if not admin_open_ids:
        raise ValueError("FEISHU_ADMIN_OPEN_IDS is required")

    verification_token = _read_optional_env("FEISHU_VERIFICATION_TOKEN")
    encrypt_key = _read_optional_env("FEISHU_ENCRYPT_KEY")

    if callback_mode == "token" and not verification_token:
        raise ValueError("FEISHU_VERIFICATION_TOKEN is required when FEISHU_CALLBACK_MODE=token")
    if callback_mode == "encrypt" and not encrypt_key:
        raise ValueError("FEISHU_ENCRYPT_KEY is required when FEISHU_CALLBACK_MODE=encrypt")

    callback_path = _read_optional_env("FEISHU_CALLBACK_PATH", DEFAULT_CALLBACK_PATH)
    if not callback_path.startswith("/"):
        callback_path = f"/{callback_path}"

    return FeishuConfig(
        app_id=app_id,
        app_secret=app_secret,
        admin_open_ids=admin_open_ids,
        callback_host=_read_optional_env("FEISHU_CALLBACK_HOST", DEFAULT_CALLBACK_HOST),
        callback_port=int(_read_optional_env("FEISHU_CALLBACK_PORT", str(DEFAULT_CALLBACK_PORT))),
        callback_path=callback_path,
        callback_mode=callback_mode,
        verification_token=verification_token,
        encrypt_key=encrypt_key,
        stale_lock_seconds=int(
            _read_optional_env("FEISHU_STALE_LOCK_SECONDS", str(DEFAULT_STALE_LOCK_SECONDS))
        ),
    )


class FeishuControlPlane:
    def __init__(
        self,
        config: FeishuConfig,
        feishu_client=None,
        cookie_file_path=None,
        submission_state_path=None,
        runtime_status_path=None,
        alert_state_path=None,
        event_handler=None,
        now_provider: Callable[[], datetime] | None = None,
        uuid_factory: Callable[[], str] | None = None,
        followup_timeout_seconds: int = DEFAULT_FOLLOWUP_TIMEOUT_SECONDS,
        followup_poll_interval_seconds: int = DEFAULT_FOLLOWUP_POLL_INTERVAL_SECONDS,
        runtime_status_poll_interval_seconds: int = DEFAULT_RUNTIME_STATUS_POLL_INTERVAL_SECONDS,
    ):
        self.config = config
        self.feishu_client = feishu_client or FeishuClient(config.app_id, config.app_secret)
        self.cookie_file_path = _resolve_path(
            cookie_file_path or os.getenv("COOKIE_FILE_PATH", DEFAULT_COOKIE_FILE_PATH)
        )
        self.submission_state_path = _resolve_path(
            submission_state_path or DEFAULT_SUBMISSION_STATE_PATH
        )
        self.runtime_status_path = _resolve_path(runtime_status_path or DEFAULT_RUNTIME_STATUS_PATH)
        self.alert_state_path = _resolve_path(alert_state_path or DEFAULT_ALERT_STATE_PATH)
        self.event_handler = event_handler or self._handle_event
        self._now_provider = now_provider or _now_dt
        self._uuid_factory = uuid_factory or (lambda: uuid.uuid4().hex[:6])
        self.followup_timeout_seconds = followup_timeout_seconds
        self.followup_poll_interval_seconds = followup_poll_interval_seconds
        self.runtime_status_poll_interval_seconds = runtime_status_poll_interval_seconds
        self._processed_event_ids = set()
        self._mutation_lock = threading.Lock()
        self._alert_state = self._load_alert_state()
        self.recover_stale_submission_lock()

    def _verify_payload(self, payload: dict) -> bool:
        if self.config.callback_mode == "none":
            return True

        payload_token = (payload.get("token") or payload.get("header", {}).get("token") or "").strip()
        if self.config.callback_mode == "token":
            return payload_token == self.config.verification_token

        return False

    @staticmethod
    def _extract_event_id(payload: dict) -> str:
        header = payload.get("header") or {}
        if header.get("event_id"):
            return str(header["event_id"])

        event = payload.get("event") or {}
        message = event.get("message") or {}
        if message.get("message_id"):
            return str(message["message_id"])
        return ""

    def handle_callback_request(self, raw_body: bytes):
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return 400, {"error": "invalid callback payload"}

        if self.config.callback_mode == "encrypt":
            return 501, {"error": "encrypted callback payloads are not supported in this build"}

        if not self._verify_payload(payload):
            return 403, {"error": "untrusted callback request"}

        if payload.get("type") == "url_verification":
            return 200, {"challenge": payload.get("challenge", "")}

        event_id = self._extract_event_id(payload)
        if event_id and event_id in self._processed_event_ids:
            return 200, {"duplicate": True}

        try:
            response_payload = self.event_handler(payload)
        except Exception as exc:
            logger.warning(f"callback event handling failed: {exc}")
            return 500, {"error": "callback handling failed"}

        if event_id:
            self._processed_event_ids.add(event_id)

        return 200, response_payload

    def _handle_event(self, payload: dict):
        event = payload.get("event") or {}
        sender_open_id = (
            event.get("sender", {})
            .get("sender_id", {})
            .get("open_id", "")
            .strip()
        )
        message = event.get("message") or {}
        chat_type = (message.get("chat_type") or "").strip()
        message_type = (message.get("message_type") or "").strip()

        if sender_open_id not in self.config.admin_open_ids:
            self._send_reply_safely(sender_open_id, "未授权，无法执行此操作")
            return {"ok": True}

        if chat_type != "p2p":
            self._send_reply_safely(sender_open_id, "仅支持私聊提交 Cookie 或查询状态")
            return {"ok": True}

        if message_type != "text":
            self._send_reply_safely(sender_open_id, "仅支持文本消息")
            return {"ok": True}

        text = self._extract_text_content(message.get("content"))
        if text == "/status":
            self._send_reply_safely(sender_open_id, self._format_status_reply())
            return {"ok": True}

        if text == "/help":
            self._send_reply_safely(sender_open_id, self._format_help_reply())
            return {"ok": True}

        if self._looks_like_cookie(text):
            self._submit_cookie(sender_open_id, text)
            return {"ok": True}

        self._send_reply_safely(sender_open_id, self._format_help_reply())
        return {"ok": True}

    @staticmethod
    def _extract_text_content(raw_content) -> str:
        if not raw_content:
            return ""
        if isinstance(raw_content, str):
            try:
                parsed = json.loads(raw_content)
            except json.JSONDecodeError:
                return raw_content.strip()
            return str(parsed.get("text") or "").strip()
        if isinstance(raw_content, dict):
            return str(raw_content.get("text") or "").strip()
        return ""

    @staticmethod
    def _looks_like_cookie(text: str) -> bool:
        pairs = []
        keys = set()
        for part in text.split(";"):
            stripped = part.strip()
            if "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if not key.strip() or not value.strip():
                continue
            pairs.append(stripped)
            keys.add(key.strip())

        important_keys = {"unb", "_m_h5_tk", "cookie2", "cna"}
        return len(pairs) >= 2 and len(keys & important_keys) >= 2

    def _send_reply(self, open_id: str, text: str) -> None:
        if not open_id:
            return
        self.feishu_client.send_text_message(open_id, text)

    def _send_reply_safely(self, open_id: str, text: str) -> bool:
        try:
            self._send_reply(open_id, text)
            return True
        except Exception as exc:
            logger.warning(f"failed to send Feishu reply to {open_id}: {exc}")
            return False

    def _format_status_reply(self) -> str:
        status = _read_json_file(self.runtime_status_path)
        if not status:
            return "当前状态: idle\n更新时间: n/a\n说明: 暂无运行状态"
        return (
            f"当前状态: {status.get('state', 'unknown')}\n"
            f"更新时间: {status.get('updated_at', 'n/a')}\n"
            f"说明: {status.get('message', '')}"
        )

    @staticmethod
    def _format_help_reply() -> str:
        return "支持命令:\n/help\n/status\n直接发送完整 Cookie 文本以更新运行时 Cookie"

    def _generate_submission_id(self) -> str:
        return f"{self._now_provider().strftime('%Y%m%dT%H%M%SZ')}-{self._uuid_factory()}"

    def _build_submission_state(
        self,
        submission_id: str,
        sender_open_id: str,
        state: str,
        message: str = "",
        source: str = "feishu_manual",
    ) -> dict:
        return {
            "submission_id": submission_id,
            "source": source,
            "sender_open_id": sender_open_id,
            "requested_at": _format_dt(self._now_provider()),
            "state": state,
            "message": message,
        }

    def _load_submission_state(self) -> dict:
        return _read_json_file(self.submission_state_path)

    def _write_submission_state(self, payload: dict) -> None:
        _atomic_write_json(self.submission_state_path, payload)

    @staticmethod
    def _build_default_alert_state() -> dict:
        return {
            "last_alerted_waiting_episode_id": "",
            "awaiting_terminal_episode_id": "",
            "delivered_admin_open_ids": [],
        }

    def _load_alert_state(self) -> dict:
        alert_state = self._build_default_alert_state()
        persisted_state = _read_json_file(self.alert_state_path)
        if isinstance(persisted_state, dict):
            alert_state["last_alerted_waiting_episode_id"] = str(
                persisted_state.get("last_alerted_waiting_episode_id") or ""
            ).strip()
            alert_state["awaiting_terminal_episode_id"] = str(
                persisted_state.get("awaiting_terminal_episode_id") or ""
            ).strip()
            delivered_admin_open_ids = persisted_state.get("delivered_admin_open_ids")
            if isinstance(delivered_admin_open_ids, list):
                alert_state["delivered_admin_open_ids"] = sorted(
                    {
                        str(open_id).strip()
                        for open_id in delivered_admin_open_ids
                        if str(open_id).strip() in self.config.admin_open_ids
                    }
                )
        return alert_state

    def _write_alert_state(self) -> None:
        _atomic_write_json(self.alert_state_path, self._alert_state)

    @staticmethod
    def _extract_waiting_episode_id(runtime_status: dict) -> str:
        return str(runtime_status.get("cookie_invalid_episode_id") or "").strip()

    @staticmethod
    def _format_waiting_alert(runtime_status: dict, episode_id: str) -> str:
        message = str(runtime_status.get("message") or "Cookie invalid, waiting for refresh").strip()
        return (
            "检测到 App Bot 正在等待新的 Cookie。\n"
            f"当前状态: {runtime_status.get('state', 'waiting_for_cookie')}\n"
            f"失效事件: {episode_id}\n"
            f"说明: {message}"
        )

    def _persist_waiting_episode_delivery_state(self, episode_id: str, delivered_admin_open_ids: set[str]) -> None:
        delivered_admin_open_ids = {
            open_id for open_id in delivered_admin_open_ids if open_id in self.config.admin_open_ids
        }
        self._alert_state["last_alerted_waiting_episode_id"] = (
            episode_id if delivered_admin_open_ids == self.config.admin_open_ids else ""
        )
        self._alert_state["awaiting_terminal_episode_id"] = episode_id
        self._alert_state["delivered_admin_open_ids"] = sorted(delivered_admin_open_ids)
        self._write_alert_state()

    def _clear_waiting_episode_alert(self, episode_id: str) -> None:
        if self._alert_state.get("awaiting_terminal_episode_id") != episode_id:
            return
        self._alert_state["last_alerted_waiting_episode_id"] = ""
        self._alert_state["awaiting_terminal_episode_id"] = ""
        self._alert_state["delivered_admin_open_ids"] = []
        self._write_alert_state()

    def poll_runtime_status_once(self) -> None:
        runtime_status = _read_json_file(self.runtime_status_path)
        if not runtime_status:
            return

        state = str(runtime_status.get("state") or "").strip()
        if not state:
            return

        with self._mutation_lock:
            awaiting_terminal_episode_id = self._alert_state.get("awaiting_terminal_episode_id", "")
            episode_id = self._extract_waiting_episode_id(runtime_status)
            if not episode_id:
                return

            if state == "waiting_for_cookie":
                if awaiting_terminal_episode_id and awaiting_terminal_episode_id != episode_id:
                    return
                if self._alert_state.get("last_alerted_waiting_episode_id") == episode_id:
                    return
                alert_text = self._format_waiting_alert(runtime_status, episode_id)
                delivered_admin_open_ids = set(
                    self._alert_state.get("delivered_admin_open_ids", [])
                    if awaiting_terminal_episode_id == episode_id
                    else []
                )
                pending_admin_open_ids = [
                    admin_open_id
                    for admin_open_id in sorted(self.config.admin_open_ids)
                    if admin_open_id not in delivered_admin_open_ids
                ]
                for admin_open_id in pending_admin_open_ids:
                    if self._send_reply_safely(admin_open_id, alert_text):
                        delivered_admin_open_ids.add(admin_open_id)
                self._persist_waiting_episode_delivery_state(episode_id, delivered_admin_open_ids)
                return

            if state in {"recovered", "validation_failed"}:
                self._clear_waiting_episode_alert(episode_id)

    def watch_runtime_status_forever(self) -> None:
        poll_interval = max(self.runtime_status_poll_interval_seconds, 0)
        while True:
            try:
                self.poll_runtime_status_once()
            except Exception as exc:
                logger.warning(f"runtime status watcher failed: {exc}")

            if poll_interval <= 0:
                return
            time.sleep(poll_interval)

    def start_runtime_status_watcher(self) -> None:
        threading.Thread(
            target=self.watch_runtime_status_forever,
            daemon=True,
        ).start()

    def recover_stale_submission_lock(self) -> None:
        state = self._load_submission_state()
        if state.get("state") != "in_progress":
            return

        requested_at = state.get("requested_at")
        if not requested_at:
            return
        try:
            requested_dt = datetime.fromisoformat(requested_at)
        except ValueError:
            return

        if self._now_provider() - requested_dt.astimezone(timezone.utc) >= timedelta(
            seconds=self.config.stale_lock_seconds
        ):
            state["state"] = "timed_out"
            state["message"] = "stale submission lock recovered on startup"
            state["updated_at"] = _format_dt(self._now_provider())
            self._write_submission_state(state)

    def submit_cookie_update(
        self,
        *,
        source: str,
        cookie_text: str,
        sender_open_id: str = "",
        send_replies: bool = True,
    ) -> str:
        persisted_sender_open_id = sender_open_id if send_replies else ""
        with self._mutation_lock:
            self.recover_stale_submission_lock()
            existing_state = self._load_submission_state()
            if existing_state.get("state") == "in_progress":
                raise SubmissionBusyError()

            submission_id = self._generate_submission_id()
            submission_state = self._build_submission_state(
                submission_id,
                persisted_sender_open_id,
                "in_progress",
                source=source,
            )
            self._write_submission_state(submission_state)

            try:
                _atomic_write_text(self.cookie_file_path, cookie_text)
            except OSError:
                submission_state["state"] = "aborted"
                submission_state["message"] = "cookie replace failed"
                submission_state["updated_at"] = _format_dt(self._now_provider())
                self._write_submission_state(submission_state)
                raise

        self.start_followup_task(submission_id, persisted_sender_open_id)
        return submission_id

    def _submit_cookie(self, sender_open_id: str, cookie_text: str) -> None:
        try:
            self.submit_cookie_update(
                source="feishu_manual",
                cookie_text=cookie_text,
                sender_open_id=sender_open_id,
                send_replies=True,
            )
        except SubmissionBusyError:
            self._send_reply_safely(sender_open_id, "已有更新在校验，请稍后重试")
            return
        except OSError:
            self._send_reply_safely(sender_open_id, "Cookie 写入失败，请稍后重试")
            return

        self._send_reply_safely(sender_open_id, "已接收，开始校验")

    def start_followup_task(self, submission_id: str, sender_open_id: str) -> None:
        threading.Thread(
            target=self.follow_submission_result,
            args=(submission_id, sender_open_id),
            daemon=True,
        ).start()

    def _mark_submission_finished(self, state_name: str, message: str) -> None:
        state = self._load_submission_state()
        if not state:
            return
        state["state"] = state_name
        state["message"] = message
        state["updated_at"] = _format_dt(self._now_provider())
        self._write_submission_state(state)

    def follow_submission_result(self, submission_id: str, sender_open_id: str) -> None:
        deadline = time.monotonic() + max(self.followup_timeout_seconds, 0)
        submission_state = self._load_submission_state()
        reply_open_id = ""
        if submission_state.get("submission_id") == submission_id:
            reply_open_id = str(submission_state.get("sender_open_id") or "").strip()
        should_send_reply = bool(reply_open_id)

        while time.monotonic() <= deadline:
            runtime_status = _read_json_file(self.runtime_status_path)
            if runtime_status.get("submission_id") == submission_id:
                status = runtime_status.get("state")
                if status == "recovered":
                    self._mark_submission_finished("completed", runtime_status.get("message", ""))
                    if should_send_reply:
                        self._send_reply_safely(reply_open_id, "Cookie 已生效，连接已恢复")
                    return
                if status == "validation_failed":
                    self._mark_submission_finished("completed", runtime_status.get("message", ""))
                    if should_send_reply:
                        self._send_reply_safely(reply_open_id, "Cookie 已接收，但校验失败，请重新获取")
                    return

            if self.followup_poll_interval_seconds <= 0:
                break
            time.sleep(self.followup_poll_interval_seconds)

        self._mark_submission_finished("timed_out", "cookie validation timed out")
        if should_send_reply:
            self._send_reply_safely(reply_open_id, "Cookie 校验超时，请稍后使用 /status 查看结果")


def build_request_handler(control_plane: FeishuControlPlane):
    class FeishuCallbackHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != control_plane.config.callback_path:
                self.send_response(404)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'{"error":"not found"}')
                return

            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length)
            status_code, payload = control_plane.handle_callback_request(raw_body)

            response_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, format, *args):
            return

    return FeishuCallbackHandler


def build_manual_validation_command(config: FeishuConfig) -> str:
    return (
        "curl -X POST "
        f"http://{config.callback_host}:{config.callback_port}{config.callback_path} "
        "-H 'Content-Type: application/json' "
        f"-d '{json.dumps({'type': 'url_verification', 'challenge': 'ping', 'token': config.verification_token}, ensure_ascii=False)}'"
    )


def run_control_plane_server():
    config = load_feishu_config()
    control_plane = FeishuControlPlane(config)
    control_plane.start_runtime_status_watcher()
    server = ThreadingHTTPServer(
        (config.callback_host, config.callback_port),
        build_request_handler(control_plane),
    )
    print(
        f"Feishu control plane listening on http://{config.callback_host}:{config.callback_port}{config.callback_path}"
    )
    print(f"Manual validation command: {build_manual_validation_command(config)}")
    server.serve_forever()


if __name__ == "__main__":
    run_control_plane_server()
