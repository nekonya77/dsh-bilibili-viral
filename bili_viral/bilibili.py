"""Bilibili API client with caching, rate limiting and tolerant parsing."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from curl_cffi import requests as crequests

from .config import Config
from .util import (
    RateLimiter,
    clean_title,
    ensure_dir,
    normalize_pic,
    now_cn,
    parse_duration,
    parse_tags,
    read_json,
    sha1,
    write_json,
)

SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"
VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
PLAYER_URL = "https://api.bilibili.com/x/player/wbi/v2"
RELATION_URL = "https://api.bilibili.com/x/relation/stat"
REPLY_URL = "https://api.bilibili.com/x/v2/reply"
HOME_URL = "https://www.bilibili.com/"


class BiliError(Exception):
    pass


class BiliAuthError(BiliError):
    pass


class BiliClient:
    def __init__(
        self,
        cfg: Config,
        session: crequests.Session,
        logger: Optional[logging.Logger] = None,
    ):
        self.cfg = cfg
        self.session = session
        self.logger = logger or logging.getLogger("bili_viral.api")
        self.limiter = RateLimiter(
            float(cfg.limits.get("requests_per_second", 0.8)),
            jitter=0.25,
        )
        self.cache_dir = cfg.cache_dir
        for sub in ("search", "view", "player", "subtitle", "reply", "relation"):
            ensure_dir(self.cache_dir / sub)
        self.request_count = 0

    # ------------------------------------------------------------------ cache
    def _cache_file(self, kind: str, key: str) -> Path:
        return self.cache_dir / kind / f"{sha1(key)}.json"

    def _cache_get(self, kind: str, key: str, ttl: int) -> Optional[Any]:
        path = self._cache_file(kind, key)
        if not path.exists():
            return None
        if ttl >= 0 and time.time() - path.stat().st_mtime > ttl:
            return None
        return read_json(path, default=None)

    def _cache_put(self, kind: str, key: str, data: Any) -> None:
        write_json(self._cache_file(kind, key), data)

    # ---------------------------------------------------------------- request
    def _get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        kind: str = "misc",
        key: str = "",
        ttl: int = 21600,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        cache_key = key or (url + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items())))
        cached = self._cache_get(kind, cache_key, ttl)
        if cached is not None:
            return cached
        last_error: Optional[Exception] = None
        for attempt in range(3):
            self.limiter.wait()
            try:
                resp = self.session.get(
                    url, params=params, headers=headers, timeout=25
                )
                self.request_count += 1
                text = resp.text or ""
                if resp.status_code == 412 or text.lstrip().startswith("<"):
                    raise BiliAuthError("Bilibili returned 412/HTML; cookies or buvid may be invalid")
                data = resp.json()
                code = data.get("code")
                if code not in (0, None):
                    if code in (-101, -352, -412, -403):
                        raise BiliAuthError(f"Bilibili auth/code error: {code}")
                    raise BiliError(f"Bilibili API code={code} message={data.get('message')}")
                self._cache_put(kind, cache_key, data)
                return data
            except BiliAuthError:
                raise
            except Exception as exc:
                last_error = exc
                self.logger.warning("Request failed (%s/3): %s", attempt + 1, exc)
                time.sleep(2 ** attempt)
        raise BiliError(f"Request failed after retries: {last_error}")

    def bootstrap(self) -> None:
        try:
            self.session.get(HOME_URL, timeout=20)
        except Exception as exc:
            self.logger.warning("Bootstrap failed: %s", exc)

    # ------------------------------------------------------------------ search
    def search(
        self,
        keyword: str,
        order: str,
        begin_ts: int,
        end_ts: int,
        page: int = 1,
        group: str = "",
    ) -> List[Dict[str, Any]]:
        params = {
            "search_type": "video",
            "keyword": keyword,
            "order": order,
            "pubtime_begin_s": begin_ts,
            "pubtime_end_s": end_ts,
            "page": page,
            "page_size": 20,
        }
        cache_key = f"{keyword}|{order}|{begin_ts}|{end_ts}|{page}"
        try:
            data = self._get_json(
                SEARCH_URL, params=params, kind="search", key=cache_key, ttl=21600
            )
        except BiliAuthError:
            self.bootstrap()
            data = self._get_json(
                SEARCH_URL, params=params, kind="search", key=cache_key, ttl=21600
            )
        result = ((data or {}).get("data") or {}).get("result") or []
        out: List[Dict[str, Any]] = []
        for item in result:
            if not isinstance(item, dict) or item.get("type") not in (None, "video"):
                continue
            normalized = self.normalize_search_item(item, keyword, group)
            if normalized:
                out.append(normalized)
        return out

    def normalize_search_item(
        self, item: Dict[str, Any], keyword: str, group: str
    ) -> Optional[Dict[str, Any]]:
        bvid = item.get("bvid")
        if not bvid:
            return None
        return {
            "bvid": bvid,
            "aid": item.get("aid"),
            "title": item.get("title") or "",
            "clean_title": clean_title(item.get("title")),
            "pic": normalize_pic(item.get("pic")),
            "play": int(item.get("play") or 0),
            "like": int(item.get("like") or 0),
            "favorite": int(item.get("favorites") or item.get("favorite") or 0),
            "coin": int(item.get("coin") or 0),
            "share": int(item.get("share") or 0),
            "reply": int(item.get("review") or item.get("reply") or 0),
            "danmaku": int(item.get("danmaku") or 0),
            "pubdate": int(item.get("pubdate") or 0),
            "duration_s": parse_duration(item.get("duration")),
            "tags": parse_tags(item.get("tag")),
            "typename": item.get("typename") or item.get("tname") or "",
            "parent_area": item.get("parent_area_name") or item.get("parent_area") or "",
            "owner_mid": item.get("mid") or item.get("uid"),
            "owner_name": item.get("author") or item.get("owner", {}).get("name")
            if isinstance(item.get("owner"), dict)
            else item.get("author") or "",
            "follower": None,
            "cid": None,
            "description": item.get("description") or "",
            "keyword": keyword,
            "keyword_group": group,
            "raw": item,
        }

    # -------------------------------------------------------------------- view
    def view(self, bvid: str, ttl: int = 21600) -> Dict[str, Any]:
        data = self._get_json(
            VIEW_URL, params={"bvid": bvid}, kind="view", key=bvid, ttl=ttl
        )
        item = data.get("data") or {}
        return self.normalize_view(item, bvid)

    def normalize_view(self, item: Dict[str, Any], bvid: str) -> Dict[str, Any]:
        stat = item.get("stat") or {}
        pages = item.get("pages") or []
        cid = pages[0].get("cid") if pages else None
        owner = item.get("owner") or {}
        tags = []
        for tag in item.get("tags") or []:
            if isinstance(tag, dict) and tag.get("tag_name"):
                tags.append(tag["tag_name"])
        return {
            "bvid": bvid,
            "aid": item.get("aid"),
            "title": item.get("title") or "",
            "clean_title": clean_title(item.get("title")),
            "pic": normalize_pic(item.get("pic")),
            "play": int(stat.get("view") or 0),
            "like": int(stat.get("like") or 0),
            "favorite": int(stat.get("favorite") or 0),
            "coin": int(stat.get("coin") or 0),
            "share": int(stat.get("share") or 0),
            "reply": int(stat.get("reply") or 0),
            "danmaku": int(stat.get("danmaku") or 0),
            "pubdate": int(item.get("pubdate") or 0),
            "duration_s": parse_duration(item.get("duration")),
            "tags": tags,
            "typename": item.get("tname") or "",
            "parent_area": item.get("tname_v2") or "",
            "owner_mid": owner.get("mid"),
            "owner_name": owner.get("name") or "",
            "follower": None,
            "cid": cid,
            "description": item.get("desc") or "",
            "raw": item,
        }

    # ------------------------------------------------------------------ player
    def player(self, bvid: str, cid: int, ttl: int = 21600) -> Dict[str, Any]:
        data = self._get_json(
            PLAYER_URL,
            params={"bvid": bvid, "cid": cid},
            kind="player",
            key=f"{bvid}|{cid}",
            ttl=ttl,
        )
        return data.get("data") or {}

    def choose_subtitle(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        sub = data.get("subtitle") or {}
        subtitles = sub.get("subtitles") or []
        if not subtitles:
            return None
        priority = ["ai-zh", "zh-CN", "zh-Hans", "zh", "ai-en", "en"]
        for lan in priority:
            for item in subtitles:
                if item.get("lan") == lan and item.get("subtitle_url"):
                    return item
        for item in subtitles:
            if item.get("subtitle_url"):
                return item
        return None

    def subtitle_json(self, url: str, ttl: int = 86400) -> List[Dict[str, Any]]:
        if url.startswith("//"):
            url = "https:" + url
        cached = self._cache_get("subtitle", url, ttl)
        if cached is not None:
            return cached if isinstance(cached, list) else cached.get("body", [])
        self.limiter.wait()
        resp = self.session.get(
            url,
            headers={"Referer": "https://www.bilibili.com/"},
            timeout=25,
        )
        self.request_count += 1
        data = resp.json()
        cues = data.get("body", data) if isinstance(data, dict) else data
        if not isinstance(cues, list):
            cues = []
        self._cache_put("subtitle", url, cues)
        return cues

    # ---------------------------------------------------------------- relation
    def follower(self, mid: int, ttl: int = 2592000) -> Optional[int]:
        if not mid:
            return None
        try:
            data = self._get_json(
                RELATION_URL,
                params={"vmid": mid},
                kind="relation",
                key=str(mid),
                ttl=ttl,
            )
            return int((data.get("data") or {}).get("follower") or 0)
        except Exception as exc:
            self.logger.warning("Follower lookup failed for %s: %s", mid, exc)
            return None

    # ------------------------------------------------------------------ reply
    def comments(self, aid: int, ps: int = 5) -> List[Dict[str, Any]]:
        if not aid:
            return []
        try:
            data = self._get_json(
                REPLY_URL,
                params={"type": 1, "oid": aid, "sort": 2, "ps": ps, "pn": 1},
                kind="reply",
                key=f"{aid}|{ps}",
                ttl=21600,
            )
            replies = ((data.get("data") or {}).get("replies") or [])
            out = []
            for reply in replies[:ps]:
                content = reply.get("content") or {}
                out.append(
                    {
                        "like": int(reply.get("like") or 0),
                        "message": clean_title(content.get("message") or ""),
                        "ctime": reply.get("ctime"),
                    }
                )
            return out
        except Exception as exc:
            self.logger.warning("Comment lookup failed for %s: %s", aid, exc)
            return []

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass
