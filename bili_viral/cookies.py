"""Read Bilibili cookies from Chrome (via yt-dlp) and cache them locally."""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from curl_cffi import requests as crequests

from .config import Config
from .util import now_cn, read_json, write_json

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
HOME_URL = "https://www.bilibili.com/"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class CookieStore:
    def __init__(self, cfg: Config, logger: Optional[logging.Logger] = None):
        self.cfg = cfg
        self.logger = logger or logging.getLogger("bili_viral.cookies")
        self.path = cfg.cookie_file
        self.ttl_days = int(cfg.data.get("cookies", {}).get("cache_ttl_days", 7))

    def load_cached(self) -> List[Dict[str, Any]]:
        data = read_json(self.path, default=[])
        if isinstance(data, dict):
            data = data.get("cookies", [])
        return data if isinstance(data, list) else []

    def save(self, cookies: List[Dict[str, Any]]) -> None:
        write_json(self.path, cookies)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def is_fresh(self) -> bool:
        if not self.path.exists():
            return False
        age = time.time() - self.path.stat().st_mtime
        return age < self.ttl_days * 86400

    def extract_from_chrome(self) -> List[Dict[str, Any]]:
        try:
            from yt_dlp.cookies import extract_cookies_from_browser
        except Exception as exc:  # pragma: no cover - env dependent
            self.logger.warning("yt-dlp is not available: %s", exc)
            return []
        try:
            jar = extract_cookies_from_browser(
                self.cfg.data.get("cookies", {}).get("browser", "chrome")
            )
        except Exception as exc:
            self.logger.warning("Could not read Chrome cookies: %s", exc)
            return []
        now = time.time()
        out: List[Dict[str, Any]] = []
        for cookie in jar:
            domain = cookie.domain or ""
            if "bilibili.com" not in domain:
                continue
            expires = cookie.expires
            if expires and expires < now:
                continue
            out.append(
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": domain,
                    "path": cookie.path or "/",
                    "expires": expires,
                    "secure": bool(cookie.secure),
                }
            )
        self.logger.info("Extracted %s Bilibili cookies from Chrome", len(out))
        return out

    def apply(self, session: crequests.Session, cookies: List[Dict[str, Any]]) -> None:
        for cookie in cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            if not name or value is None:
                continue
            domain = cookie.get("domain") or ".bilibili.com"
            if not domain.startswith("."):
                domain = "." + domain.lstrip(".")
            try:
                session.cookies.set(name, value, domain=domain, path=cookie.get("path") or "/")
            except Exception:
                try:
                    session.cookies.set(name, value, domain=".bilibili.com")
                except Exception:
                    pass

    def new_session(self) -> crequests.Session:
        session = crequests.Session(impersonate="chrome")
        session.headers.update(DEFAULT_HEADERS)
        return session

    def bootstrap(self, session: crequests.Session) -> None:
        try:
            session.get(HOME_URL, timeout=20)
        except Exception as exc:
            self.logger.warning("Could not visit Bilibili home: %s", exc)

    def is_logged_in(self, session: crequests.Session) -> bool:
        try:
            resp = session.get(NAV_URL, timeout=20)
            data = resp.json()
            return bool((data.get("data") or {}).get("isLogin"))
        except Exception as exc:
            self.logger.warning("Login check failed: %s", exc)
            return False

    def ensure(self, force_chrome: bool = False) -> Tuple[crequests.Session, bool, Dict[str, Any]]:
        """Return a ready session, login state and a diagnostic dict."""
        cached = [] if force_chrome else self.load_cached()
        session = self.new_session()
        info: Dict[str, Any] = {
            "cached": bool(cached),
            "cache_fresh": self.is_fresh(),
            "source": "none",
        }
        if cached:
            self.apply(session, cached)
            self.bootstrap(session)
            if self.is_logged_in(session):
                info.update({"source": "cache", "logged_in": True, "count": len(cached)})
                return session, True, info
            self.logger.warning("Cached cookies are not logged in; refreshing from Chrome")
        extracted = self.extract_from_chrome()
        if extracted:
            self.save(extracted)
            session = self.new_session()
            self.apply(session, extracted)
            self.bootstrap(session)
            logged_in = self.is_logged_in(session)
            info.update(
                {
                    "source": "chrome",
                    "logged_in": logged_in,
                    "count": len(extracted),
                }
            )
            return session, logged_in, info
        # No cookies: still allow public access (search may work with buvid).
        session = self.new_session()
        self.bootstrap(session)
        logged_in = self.is_logged_in(session)
        info.update({"source": "public", "logged_in": logged_in, "count": 0})
        return session, logged_in, info


def cookie_summary(cookies: List[Dict[str, Any]]) -> Dict[str, Any]:
    names = {c.get("name") for c in cookies}
    return {
        "count": len(cookies),
        "has_sessdata": "SESSDATA" in names,
        "has_bili_jct": "bili_jct" in names,
        "has_buvid3": "buvid3" in names,
        "updated_at": now_cn().isoformat(timespec="seconds"),
    }
