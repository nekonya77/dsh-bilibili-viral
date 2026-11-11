"""Filtering, relevance and viral scoring."""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .config import Config
from .util import age_hours, now_cn, percentile


def _text(value: Any) -> str:
    return str(value or "").lower()


def category_text(video: Dict[str, Any]) -> str:
    return " ".join(
        str(video.get(k) or "")
        for k in ("typename", "parent_area", "parent_area_name", "tname")
    )


def relevance(video: Dict[str, Any], keyword: str) -> float:
    kw = _text(keyword).strip()
    if not kw:
        return 0.5
    title = _text(video.get("clean_title") or video.get("title"))
    tags = " ".join(_text(t) for t in (video.get("tags") or []))
    desc = _text(video.get("description") or video.get("desc"))
    cat = _text(category_text(video))

    tokens = [t for t in re.split(r"\s+", kw) if t]
    title_hits = sum(1 for t in tokens if t in title)
    tag_hits = sum(1 for t in tokens if t in tags)
    desc_hits = sum(1 for t in tokens if t in desc)
    title_hit = 1.0 if (kw in title or (tokens and title_hits == len(tokens))) else (
        0.6 if title_hits else 0.0
    )
    tag_hit = 1.0 if (kw in tags or (tokens and tag_hits == len(tokens))) else (
        0.6 if tag_hits else 0.0
    )
    desc_hit = 1.0 if kw in desc or desc_hits else 0.0
    return round(0.5 * title_hit + 0.3 * tag_hit + 0.2 * desc_hit, 3)


def is_blocked_category(video: Dict[str, Any], cfg: Config) -> bool:
    cat = category_text(video)
    if not cat:
        return False
    for blocked in cfg.filters.get("block_categories", []):
        if blocked and blocked in cat:
            return True
    return False


def is_blocked_title(video: Dict[str, Any], cfg: Config) -> bool:
    title = str(video.get("clean_title") or video.get("title") or "")
    for pattern in cfg.filters.get("block_title_patterns", []):
        if pattern and pattern in title:
            return True
    return False


def is_paid(video: Dict[str, Any]) -> bool:
    raw = video.get("raw") or video.get("raw_json") or {}
    keys = (
        "is_pay", "badgepay", "is_charge_video", "is_upower_exclusive",
        "is_ugc_pay", "pay_badge",
    )
    for key in keys:
        if video.get(key):
            return True
        if isinstance(raw, dict) and raw.get(key):
            return True
    return False


def is_live(video: Dict[str, Any]) -> bool:
    raw = video.get("raw") or video.get("raw_json") or {}
    if video.get("is_live_room_inline"):
        return True
    if isinstance(raw, dict) and raw.get("is_live_room_inline"):
        return True
    return False


def passes_filters(
    video: Dict[str, Any],
    cfg: Config,
    begin_ts: int,
    end_ts: int,
) -> bool:
    if not video.get("bvid"):
        return False
    if int(video.get("play") or 0) < int(cfg.filters.get("min_play", 0)):
        return False
    duration = int(video.get("duration_s") or 0)
    if duration < int(cfg.filters.get("min_duration_s", 0)):
        return False
    if duration > int(cfg.filters.get("max_duration_s", 10 ** 9)):
        return False
    try:
        pub = int(video.get("pubdate") or 0)
    except (TypeError, ValueError):
        return False
    if pub and not (begin_ts <= pub <= end_ts):
        return False
    if is_blocked_category(video, cfg):
        return False
    if is_blocked_title(video, cfg):
        return False
    if cfg.filters.get("exclude_paid", True) and is_paid(video):
        return False
    if is_live(video):
        return False
    return True


def dedupe(videos: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for video in videos:
        bvid = video.get("bvid")
        if not bvid:
            continue
        if bvid not in seen:
            seen[bvid] = video
        else:
            old = seen[bvid]
            # Prefer the record with more known stats / details.
            if int(video.get("play") or 0) > int(old.get("play") or 0):
                seen[bvid] = video
    return list(seen.values())


def _metric_values(videos: List[Dict[str, Any]]) -> Dict[str, List[float]]:
    plays: List[float] = []
    velocities: List[float] = []
    engagements: List[float] = []
    breakouts: List[float] = []
    for v in videos:
        play = float(v.get("play") or 0)
        like = float(v.get("like") or 0)
        favorite = float(v.get("favorite") or 0)
        coin = float(v.get("coin") or 0)
        share = float(v.get("share") or 0)
        reply = float(v.get("reply") or 0)
        danmaku = float(v.get("danmaku") or 0)
        follower = float(v.get("follower") or 0)
        engagement = (
            like + favorite * 2 + coin * 2 + share * 3 + reply + danmaku
        ) / max(play, 1.0)
        velocity = play / max(age_hours(v.get("pubdate")), 0.1)
        breakout = math.log1p(play / max(follower, 1000.0))
        plays.append(play)
        velocities.append(velocity)
        engagements.append(engagement)
        breakouts.append(breakout)
    return {
        "play": plays,
        "velocity": velocities,
        "engagement": engagements,
        "breakout": breakouts,
    }


def score_videos(
    videos: List[Dict[str, Any]],
    cfg: Config,
) -> List[Dict[str, Any]]:
    if not videos:
        return []
    weights = cfg.scoring.get("weights", {})
    hot_score = float(cfg.scoring.get("hot_score", 75))
    hot_play = int(cfg.scoring.get("hot_play", 100000))
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for video in videos:
        groups[str(video.get("keyword_group") or "默认")].append(video)

    global_values = _metric_values(videos)
    for group, items in groups.items():
        values = _metric_values(items)
        if len(items) < 3:
            values = global_values
        for video in items:
            play = float(video.get("play") or 0)
            like = float(video.get("like") or 0)
            favorite = float(video.get("favorite") or 0)
            coin = float(video.get("coin") or 0)
            share = float(video.get("share") or 0)
            reply = float(video.get("reply") or 0)
            danmaku = float(video.get("danmaku") or 0)
            follower = float(video.get("follower") or 0)
            engagement = (
                like + favorite * 2 + coin * 2 + share * 3 + reply + danmaku
            ) / max(play, 1.0)
            velocity = play / max(age_hours(video.get("pubdate")), 0.1)
            breakout = math.log1p(play / max(follower, 1000.0))
            p_play = percentile(values["play"], play)
            p_velocity = percentile(values["velocity"], velocity)
            p_engagement = percentile(values["engagement"], engagement)
            p_breakout = percentile(values["breakout"], breakout)
            weighted = (
                weights.get("play", 0.45) * p_play
                + weights.get("velocity", 0.25) * p_velocity
                + weights.get("engagement", 0.20) * p_engagement
                + weights.get("breakout", 0.10) * p_breakout
            )
            duration = int(video.get("duration_s") or 0)
            penalty = 1.0
            if duration > 1800:
                penalty *= 0.92
            if duration < 60:
                penalty *= 0.9
            title = str(video.get("clean_title") or video.get("title") or "")
            if any(x in title for x in ("合集", "全集", "全套")):
                penalty *= 0.9
            age_days = age_hours(video.get("pubdate")) / 24.0
            recency = 0.9 + 0.1 * math.exp(-age_days / 7.0)
            score = round(100.0 * weighted * penalty * recency, 2)
            video["score"] = score
            video["is_hot"] = bool(score >= hot_score or play >= hot_play)
            video["score_json"] = {
                "play": round(p_play, 3),
                "velocity": round(p_velocity, 3),
                "engagement": round(p_engagement, 3),
                "breakout": round(p_breakout, 3),
                "penalty": round(penalty, 3),
                "recency": round(recency, 3),
            }
    videos.sort(key=lambda v: (float(v.get("score") or 0), int(v.get("play") or 0)), reverse=True)
    return videos


def select_top(
    videos: List[Dict[str, Any]],
    limit: int,
    per_group_first: bool = True,
) -> List[Dict[str, Any]]:
    if limit <= 0:
        return []
    ordered = sorted(
        videos,
        key=lambda v: (float(v.get("score") or 0), int(v.get("play") or 0)),
        reverse=True,
    )
    if not per_group_first:
        return ordered[:limit]
    picked: List[Dict[str, Any]] = []
    seen_groups = set()
    for video in ordered:
        group = video.get("keyword_group") or "默认"
        if group not in seen_groups:
            picked.append(video)
            seen_groups.add(group)
        if len(picked) >= limit:
            return picked
    seen_bvids = {v["bvid"] for v in picked}
    for video in ordered:
        if len(picked) >= limit:
            break
        if video["bvid"] not in seen_bvids:
            picked.append(video)
            seen_bvids.add(video["bvid"])
    return picked


def trend_terms(videos: List[Dict[str, Any]], top_n: int = 20) -> List[Tuple[str, int]]:
    counter: Counter = Counter()
    for video in videos:
        for tag in video.get("tags") or []:
            tag = str(tag).strip()
            if 2 <= len(tag) <= 12:
                counter[tag] += 1
    return counter.most_common(top_n)


def group_counts(videos: List[Dict[str, Any]]) -> Dict[str, int]:
    counter: Counter = Counter()
    for video in videos:
        counter[str(video.get("keyword_group") or "默认")] += 1
    return dict(counter)
