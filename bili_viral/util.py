"""Shared helpers for the Bilibili viral radar."""
from __future__ import annotations

import hashlib
import html
import json
import logging
import math
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

CN_TZ = ZoneInfo("Asia/Shanghai")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def now_cn() -> datetime:
    return datetime.now(CN_TZ)


def today_str(dt: Optional[datetime] = None) -> str:
    return (dt or now_cn()).strftime("%Y-%m-%d")


def week_key(dt: Optional[datetime] = None) -> str:
    d = dt or now_cn()
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def parse_duration(value: Any) -> int:
    """Parse 'MM:SS' / 'HH:MM:SS' / seconds into seconds."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if not s:
        return 0
    if s.isdigit():
        return int(s)
    parts = s.split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return 0
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0


def clean_title(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = s.replace("\u200b", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def normalize_pic(value: Any) -> str:
    if not value:
        return ""
    s = str(value).strip()
    if s.startswith("//"):
        return "https:" + s
    if s.startswith("http://"):
        return "https://" + s[len("http://"):]
    return s


def parse_tags(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in re.split(r"[,，]", str(value)) if x.strip()]


def human_num(value: Any) -> str:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return "0"
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}亿"
    if n >= 10_000:
        return f"{n / 10_000:.1f}万"
    return str(n)


def human_duration(seconds: Any) -> str:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "0:00"
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def atomic_write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return default


def chinese_char_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n...[truncated]"


def safe_ascii_id(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", value or "").strip("-")
    return s or "item"


def setup_logging(log_dir: Path, name: str = "bili_viral") -> logging.Logger:
    ensure_dir(log_dir)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(log_dir / f"run-{today_str()}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    logger.propagate = False
    return logger


class RateLimiter:
    def __init__(self, requests_per_second: float = 0.8, jitter: float = 0.3):
        self.min_interval = 1.0 / max(requests_per_second, 0.1)
        self.jitter = jitter
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delay = self.min_interval - (now - self._last)
        if delay > 0:
            time.sleep(delay)
        if self.jitter:
            time.sleep((time.monotonic() * 7919) % self.jitter)
        self._last = time.monotonic()


def age_hours(pubdate: Any, now: Optional[datetime] = None) -> float:
    try:
        ts = int(pubdate)
    except (TypeError, ValueError):
        return 24.0
    current = (now or now_cn()).timestamp()
    return max((current - ts) / 3600.0, 0.1)


def days_ago_ts(days: int, now: Optional[datetime] = None) -> int:
    return int(((now or now_cn()) - timedelta(days=days)).timestamp())


def disk_free_gb(path: Path) -> float:
    try:
        st = os.statvfs(str(path))
        return (st.f_bavail * st.f_frsize) / (1024 ** 3)
    except OSError:
        return 0.0


def percentile(values: List[float], x: float) -> float:
    """Fraction of values <= x, in [0, 1]."""
    if not values:
        return 0.5
    if len(values) == 1:
        return 1.0
    below = sum(1 for v in values if v <= x)
    return max(0.0, min(1.0, below / float(len(values))))


def mean(values: Iterable[float]) -> float:
    vals = list(values)
    return sum(vals) / len(vals) if vals else 0.0


def log_soft(value: float) -> float:
    return math.log1p(max(value, 0.0))


def strip_markdown(md: str) -> str:
    s = re.sub(r"```.*?```", " ", md or "", flags=re.S)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"^[#>*\-\s]+", "", s, flags=re.M)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def now_iso(dt: Optional[datetime] = None) -> str:
    return (dt or now_cn()).isoformat(timespec="seconds")
