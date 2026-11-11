"""Configuration loading and project paths."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .util import PROJECT_ROOT, ensure_dir

DEFAULTS: Dict[str, Any] = {
    "project": {
        "name": "B站爆款雷达",
        "timezone": "Asia/Shanghai",
        "data_dir": "data",
        "output_dir": "output",
        "retention_days": 90,
        "disk_guard_gb": 1.5,
    },
    "creator": {
        "niche": ["AI工具/效率实操", "副业/搞钱/个人IP"],
        "face_on_camera": False,
        "production": "录屏 + 口播/字幕卡",
        "videos_per_week": 5,
        "video_length": "3-6min",
        "publish_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "strengths": ["AI工具实操", "效率工作流", "副业案例拆解"],
    },
    "keywords": [
        {"term": "AI工具", "group": "AI效率", "weight": 1.0},
        {"term": "AI Agent", "group": "AI效率", "weight": 1.0},
        {"term": "DeepSeek", "group": "AI效率", "weight": 1.0},
        {"term": "WorkBuddy", "group": "AI效率", "weight": 1.0},
        {"term": "AI编程", "group": "AI效率", "weight": 1.0},
        {"term": "AI副业", "group": "副业变现", "weight": 1.0},
        {"term": "AI接单", "group": "副业变现", "weight": 1.0},
        {"term": "普通人搞钱", "group": "副业变现", "weight": 1.0},
        {"term": "自媒体变现", "group": "副业变现", "weight": 1.0},
        {"term": "个人IP", "group": "副业变现", "weight": 1.0},
    ],
    "filters": {
        "window_days": 7,
        "daily_window_days": 2,
        "min_play": 10000,
        "min_duration_s": 60,
        "max_duration_s": 2700,
        "block_categories": [
            "音乐", "影视", "娱乐", "游戏", "动画", "鬼畜", "舞蹈",
            "时尚", "美食", "动物", "搞笑",
        ],
        "category_allow": [
            "科技", "计算机", "职场", "财经", "知识", "教育", "数码", "商业",
        ],
        "block_title_patterns": [
            "小曲", "鬼畜", "混剪", "直播回放", "预告", "花絮", "纯音乐",
            "MMD", "游戏实况", "合集", "全集", "全套",
        ],
        "exclude_paid": True,
    },
    "limits": {
        "max_videos_per_run": 120,
        "max_details": 30,
        "max_transcripts": 15,
        "max_covers": 30,
        "requests_per_second": 0.8,
        "search_pages": 2,
    },
    "scoring": {
        "weights": {"play": 0.45, "velocity": 0.25, "engagement": 0.20, "breakout": 0.10},
        "hot_score": 75.0,
        "hot_play": 100000,
    },
    "cookies": {
        "browser": "chrome",
        "cache_ttl_days": 7,
        "cache_file": "cookies/bilibili.json",
    },
    "cover": {
        "font": "/System/Library/Fonts/STHeiti Medium.ttc",
        "fallback_fonts": [
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Supplemental/Songti.ttc",
        ],
        "size": [1280, 720],
        "variants": 2,
        "download_width": 800,
        "download_height": 450,
    },
    "schedule": {
        "daily_time": "09:00",
        "timezone": "Asia/Shanghai",
        "weekly_day": "Mon",
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    def __init__(self, data: Dict[str, Any], root: Path):
        self.data = data
        self.root = root

    @property
    def project(self) -> Dict[str, Any]:
        return self.data["project"]

    @property
    def creator(self) -> Dict[str, Any]:
        return self.data["creator"]

    @property
    def filters(self) -> Dict[str, Any]:
        return self.data["filters"]

    @property
    def limits(self) -> Dict[str, Any]:
        return self.data["limits"]

    @property
    def scoring(self) -> Dict[str, Any]:
        return self.data["scoring"]

    @property
    def cover(self) -> Dict[str, Any]:
        return self.data["cover"]

    @property
    def data_dir(self) -> Path:
        return self.root / self.project.get("data_dir", "data")

    @property
    def output_dir(self) -> Path:
        return self.root / self.project.get("output_dir", "output")

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def cookie_file(self) -> Path:
        return self.data_dir / self.data["cookies"].get("cache_file", "cookies/bilibili.json")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bili.db"

    @property
    def font_path(self) -> str:
        candidates = [self.cover.get("font", "")] + list(self.cover.get("fallback_fonts", []))
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return candidate
        # Last attempt: any known macOS CJK font.
        for candidate in [
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Supplemental/Songti.ttc",
        ]:
            if Path(candidate).exists():
                return candidate
        return ""

    @property
    def keywords(self) -> List[Dict[str, Any]]:
        return self.data.get("keywords", [])

    def ensure_dirs(self) -> None:
        for path in [
            self.data_dir,
            self.cache_dir,
            self.data_dir / "cookies",
            self.data_dir / "runs",
            self.data_dir / "analysis",
            self.data_dir / "plans",
            self.data_dir / "cover_specs",
            self.data_dir / "transcripts",
            self.data_dir / "knowledge",
            self.data_dir / "logs",
            self.output_dir,
            self.output_dir / "dashboard",
            self.output_dir / "covers" / "library",
            self.output_dir / "covers" / "library" / "sheets",
            self.output_dir / "covers" / "generated",
            self.output_dir / "scripts",
            self.output_dir / "daily",
            self.output_dir / "weekly",
        ]:
            ensure_dir(path)
        for sub in ["search", "view", "player"]:
            ensure_dir(self.cache_dir / sub)

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(self.data)


def load_config(path: Optional[Path] = None, root: Optional[Path] = None) -> Config:
    root = root or PROJECT_ROOT
    path = path or (root / "config.yaml")
    override: Dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            override = yaml.safe_load(f) or {}
    cfg = Config(_deep_merge(DEFAULTS, override), root)
    cfg.ensure_dirs()
    return cfg
