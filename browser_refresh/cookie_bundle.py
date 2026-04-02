from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Iterable, Mapping


RUNTIME_TARGET_URLS = [
    "https://h5api.m.goofish.com/",
    "https://www.goofish.com/",
    "https://passport.goofish.com/",
    "https://www.taobao.com/",
]
RUNTIME_CORE_KEYS = ["unb", "cookie2", "cna", "_m_h5_tk"]
RECOMMENDED_EXTRA_KEYS = ["XSRF-TOKEN", "x5sec", "tfstk", "_m_h5_tk_enc"]


@dataclass(frozen=True)
class RuntimeCookie:
    name: str
    value: str
    domain: str


@dataclass(frozen=True)
class RuntimeCookieBundle:
    RUNTIME_TARGET_URLS: ClassVar[tuple[str, ...]] = tuple(RUNTIME_TARGET_URLS)
    RUNTIME_CORE_KEYS: ClassVar[tuple[str, ...]] = tuple(RUNTIME_CORE_KEYS)
    RECOMMENDED_EXTRA_KEYS: ClassVar[tuple[str, ...]] = tuple(RECOMMENDED_EXTRA_KEYS)

    cookies: tuple[RuntimeCookie, ...]
    text: str
    has_runtime_core_keys: bool
    missing_runtime_core_keys: tuple[str, ...]
    missing_recommended_keys: tuple[str, ...]
    runtime_target_urls: tuple[str, ...] = RUNTIME_TARGET_URLS
    runtime_core_keys: tuple[str, ...] = RUNTIME_CORE_KEYS
    recommended_extra_keys: tuple[str, ...] = RECOMMENDED_EXTRA_KEYS


def _normalize_cookie(cookie: Mapping[str, object] | None) -> RuntimeCookie | None:
    if not cookie:
        return None

    raw_name = cookie.get("name", "")
    raw_value = cookie.get("value", "")
    raw_domain = cookie.get("domain", "")
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    value = raw_value.strip() if isinstance(raw_value, str) else ""
    domain = raw_domain.strip() if isinstance(raw_domain, str) else ""
    if not name or not value:
        return None
    return RuntimeCookie(name=name, value=value, domain=domain)


def build_runtime_cookie_bundle(cookies: Iterable[Mapping[str, object]] | None) -> RuntimeCookieBundle:
    deduped_by_name: dict[str, RuntimeCookie] = {}
    for cookie in cookies or ():
        normalized = _normalize_cookie(cookie)
        if normalized is None:
            continue
        if normalized.name not in deduped_by_name:
            deduped_by_name[normalized.name] = normalized

    selected_cookies = tuple(deduped_by_name.values())
    missing_runtime_core_keys = tuple(key for key in RUNTIME_CORE_KEYS if key not in deduped_by_name)
    missing_recommended_keys = tuple(key for key in RECOMMENDED_EXTRA_KEYS if key not in deduped_by_name)

    return RuntimeCookieBundle(
        cookies=selected_cookies,
        text="; ".join(f"{cookie.name}={cookie.value}" for cookie in selected_cookies),
        has_runtime_core_keys=not missing_runtime_core_keys,
        missing_runtime_core_keys=missing_runtime_core_keys,
        missing_recommended_keys=missing_recommended_keys,
    )
